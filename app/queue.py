"""Serial GPU job queue, scheduler, and Windows sleep prevention.

Extracted from ``server.py``. The queue worker needs the pipeline runner and
the showcase-assembly hook, which still live in the server, so they are
injected via ``start()`` rather than imported (avoids an import cycle).
"""
import asyncio
import logging
import time

from app.lipsync import run_lipsync
from app.state import jobs, save_job

log = logging.getLogger("tachidubb.queue")

job_queue = None
queue_worker_task = None
scheduler_task = None

_sleep_lock_active = False

# Injected by ``start()``.
_run_pipeline = None
_assemble_showcase = None


class JobCancelled(Exception):
    """Raised inside pipeline stages when the user has requested cancel."""


def configure(run_pipeline_fn, assemble_showcase_fn=None) -> None:
    """Register the server's pipeline runner + showcase hook (call at startup)."""
    global _run_pipeline, _assemble_showcase
    _run_pipeline = run_pipeline_fn
    _assemble_showcase = assemble_showcase_fn


def get_queue():
    """Return the live queue (or None before start)."""
    return job_queue


def init_queue():
    global job_queue
    job_queue = asyncio.Queue()
    return job_queue


def _apply_sleep_prevention(keep_awake: bool) -> None:
    """Toggle Windows sleep prevention. Safe no-op on non-Windows OS."""
    global _sleep_lock_active
    try:
        import ctypes
        if not hasattr(ctypes, "windll"):
            return  # not Windows
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        # ES_AWAYMODE_REQUIRED could be added on desktop to keep CPU active
        # even with lid closed; we leave it off to allow screen sleep but
        # prevent system sleep.
        if keep_awake and not _sleep_lock_active:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )
            _sleep_lock_active = True
            log.info("[power] Sleep prevention ON — PC stays awake during queue")
        elif not keep_awake and _sleep_lock_active:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            _sleep_lock_active = False
            log.info("[power] Sleep prevention OFF — PC can sleep again")
    except Exception as e:
        log.debug(f"[power] Sleep prevention toggle failed: {e}")


async def enqueue_job(job_id, pipeline_args) -> None:
    """Add a job to the queue; scheduler will pick it up.

    pipeline_args: dict of keyword args for run_pipeline (preferred),
        or legacy tuple of positional args (old enqueue sites).
    """
    global job_queue
    if job_queue is None:
        # Queue not initialized yet (shouldn't happen after startup)
        job_queue = asyncio.Queue()
    # Mark job as queued in the store so UI shows "queued" badge
    if job_id in jobs:
        jobs[job_id]["status"] = "queued"
        jobs[job_id]["queue_position"] = job_queue.qsize() + 1
        save_job(jobs[job_id])
    await job_queue.put((job_id, pipeline_args))
    log.info(f"[queue] Job {job_id} enqueued (position {job_queue.qsize()})")
    # Auto-activate sleep prevention when the queue has jobs waiting.
    # This ensures long unattended runs don't halt because Windows slept.
    _apply_sleep_prevention(True)


async def scheduler_loop() -> None:
    """Move scheduled jobs into the live queue once their time arrives.

    Polls every 30 seconds — good enough resolution for "start at 2 AM" use
    cases without thrashing CPU. Survives restarts because the job state
    (status='scheduled' + scheduled_at + _pending_args) is persisted to disk;
    jobs whose time already passed get enqueued on the next poll.
    """
    log.info("[scheduler] Loop started (polls every 30s)")
    while True:
        try:
            await asyncio.sleep(30)
            now = time.time()
            ready = [
                j for j in jobs.values()
                if j.get("status") == "scheduled"
                and j.get("scheduled_at", 0) > 0
                and j.get("scheduled_at", 0) <= now
            ]
            for j in ready:
                args = j.get("_pending_args")
                if not args:
                    j["status"] = "error"
                    j["error"] = "Scheduled job missing pipeline args"
                    save_job(j)
                    continue
                log.info(f"[scheduler] Job {j['id']} reached scheduled time — enqueueing")
                j.pop("_pending_args", None)
                await enqueue_job(j["id"], args)
        except asyncio.CancelledError:
            log.info("[scheduler] Loop cancelled, exiting")
            return
        except Exception as e:
            log.warning(f"[scheduler] Iteration failed (continuing): {e}")


async def job_queue_worker() -> None:
    """Background worker — runs pipelines serially from the queue."""
    log.info("[queue] Worker started")
    while True:
        try:
            job_id, pipeline_args = await job_queue.get()
        except asyncio.CancelledError:
            log.info("[queue] Worker cancelled, exiting")
            return
        try:
            # Update queue positions for waiting jobs so UI reflects movement
            for j in jobs.values():
                if j.get("status") == "queued":
                    # Decrement: this one just left the queue, others move up
                    pos = j.get("queue_position", 1) - 1
                    j["queue_position"] = max(pos, 1)
            log.info(f"[queue] Processing job {job_id}")
            # Mark actual start time so elapsed/ETA measurements are accurate
            # (created = enqueue time, which can be much earlier in a batch).
            if job_id in jobs:
                jobs[job_id]["started_at"] = time.time()
                save_job(jobs[job_id])
            # Queue stores args as a dict keyword, not positional tuple — so we
            # can add new pipeline params without breaking old enqueue sites
            if isinstance(pipeline_args, dict):
                await _run_pipeline(job_id, **pipeline_args)
            else:
                # Legacy positional tuple (back-compat with older queued jobs)
                await _run_pipeline(job_id, *pipeline_args[:12],
                                    wizard_mode=pipeline_args[12])
        except JobCancelled:
            # Cancel is a user action, not an error. Status was already set by
            # the exception raiser; just log cleanly.
            log.info(f"[queue] Job {job_id} cancelled by user")
            if job_id in jobs:
                jobs[job_id]["status"] = "cancelled"
                jobs[job_id].pop("cancel_requested", None)
                save_job(jobs[job_id])
        except Exception as e:
            log.error(f"[queue] Job {job_id} crashed: {e}", exc_info=True)
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e) or type(e).__name__
                save_job(jobs[job_id])
        else:
            # Job completed cleanly. Run post-success hooks:
            #   1. Auto lip-sync (MuseTalk) if the job opted in.
            #   2. Showcase stitch if this was the last sibling in a batch.
            # Both are best-effort — failures log but don't fail the job.
            try:
                if job_id in jobs and jobs[job_id].get("lip_sync"):
                    log.info(f"[queue] post-hook: running auto lip-sync on {job_id}")
                    await asyncio.get_event_loop().run_in_executor(
                        None, run_lipsync, job_id)
            except Exception as e:
                log.warning(f"[lipsync] auto hook failed: {e}", exc_info=True)
            try:
                if (job_id in jobs and jobs[job_id].get("batch_kind") == "showcase"
                        and _assemble_showcase is not None):
                    await _assemble_showcase(jobs[job_id].get("batch_id", ""))
            except Exception as e:
                log.warning(f"[showcase] post-process hook failed: {e}", exc_info=True)
        finally:
            job_queue.task_done()
            # Release sleep lock once nothing else is pending. Next enqueue
            # will re-acquire automatically.
            if job_queue.empty():
                _apply_sleep_prevention(False)


def start(run_pipeline_fn, assemble_showcase_fn=None):
    """Configure + start the worker and scheduler. Call from the app lifespan."""
    configure(run_pipeline_fn, assemble_showcase_fn)
    init_queue()
    global queue_worker_task, scheduler_task
    queue_worker_task = asyncio.create_task(job_queue_worker())
    # Scheduler: polls every 30s looking for jobs with status='scheduled'.
    scheduler_task = asyncio.create_task(scheduler_loop())
    return job_queue


async def shutdown() -> None:
    """Cancel the worker + scheduler so they don't hang process shutdown."""
    for t in (queue_worker_task, scheduler_task):
        if t and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass