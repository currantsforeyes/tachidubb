"""Serverless dub runner: a job spec in, NDJSON progress out.

The process an external host — the OpenShot add-on — spawns instead of running
the FastAPI server. No uvicorn, no browser, no MCP. It drives the SAME tested
pipeline (``create_file_job`` records the job, ``run_pipeline`` does the work),
so there is no second implementation to drift out of sync.

Events — one JSON object per line on stdout::

    {"type": "job",       "job_id": "abc123", "work": ".../outputs/abc123"}
    {"type": "progress",  "job_id": "abc123", "status": "translating",
                          "progress": 45, "step_detail": "Translating..."}
    {"type": "done",      "job_id": "abc123", "output": ".../dubbed_video.mp4"}
    {"type": "error",     "job_id": "abc123", "error": "..."}
    {"type": "cancelled", "job_id": "abc123"}

A host should ignore any stdout line that isn't JSON carrying a ``type`` key:
pipeline logging goes to stderr, but a stray ``print`` must not be able to
desynchronise a reader.

Exit codes: ``0`` success, ``1`` pipeline error, ``2`` cancelled, ``3`` bad spec.

Cancellation mirrors the server's Cancel button: with ``--cancel-file PATH``
the worker sets ``job["cancel_requested"]`` as soon as that file appears, and
the pipeline raises JobCancelled at its next progress update — the same path
the server-side queue uses to turn a cancel into ``status="cancelled"``.

Usage::

    python tools/dub_worker.py --spec job.json
    python tools/dub_worker.py --spec job.json --status-file progress.jsonl

Example spec::

    {"source": "C:/videos/in.mp4", "source_lang": "ru",
     "target_lang": "en", "model": "aya-expanse:8b", "voice_preset": "auto"}
"""
import argparse
import asyncio
import inspect
import json
import sys
from pathlib import Path

# OpenShot launches this from its own working directory, so make the repo
# root importable regardless of cwd (script dir alone would not suffice).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import OUTPUT_DIR            # noqa: E402
from app.pipeline import run_pipeline        # noqa: E402
from app.queue import JobCancelled           # noqa: E402
from app.state import jobs, save_job         # noqa: E402
from app.submit import create_file_job       # noqa: E402

# Job fields the host renders. Emitted as a "progress" event whenever any of
# them changes, so the panel can bind to a stable set of keys.
_WATCHED = ("status", "progress", "step_detail", "error", "output_url", "srt_url")

# Spec keys create_file_job understands, minus the ones this CLI owns.
_CREATE_PARAMS = set(inspect.signature(create_file_job).parameters) - {
    "source_path", "job_id", "enqueue",
}
_REQUIRED = ("source", "target_lang", "model")


class UsageError(Exception):
    """The spec is malformed. Exit 3 — not a pipeline failure."""


def _validate(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise UsageError("spec must be a JSON object")
    missing = [k for k in _REQUIRED if not spec.get(k)]
    if missing:
        raise UsageError(f"spec is missing: {', '.join(missing)}")
    unknown = set(spec) - _CREATE_PARAMS - {"source", "job_id", "id"}
    if unknown:
        raise UsageError(f"unknown spec keys: {', '.join(sorted(unknown))}")
    return spec


def load_spec(path) -> dict:
    p = Path(path)
    try:
        # utf-8-sig: Windows editors (Notepad, PowerShell) save UTF-8 *with* a
        # BOM by default, and a hand-edited spec should not be rejected for it.
        raw = p.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise UsageError(f"cannot read spec {p}: {e}") from e
    try:
        return _validate(json.loads(raw))
    except json.JSONDecodeError as e:
        raise UsageError(f"spec is not valid JSON: {e}") from e


def _emit(obj: dict, out, status_file: Path = None) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    out.write(line + "\n")
    out.flush()
    if status_file is not None:
        try:
            with open(status_file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # the stdout channel is authoritative; a file is a convenience


async def _watch(jid: str, out, cancel_file, stop: asyncio.Event,
                 tick: float, status_file: Path = None) -> None:
    """Stream job-field changes; honour the cancel file; exit on ``stop``.

    The pipeline reports progress by mutating the shared job dict, so polling
    it is all a host needs — no HTTP involved. The final observation always
    happens after ``stop`` is set, so a run that finishes between two ticks
    still reports its terminal state.
    """
    last = None
    while True:
        job = jobs.get(jid) or {}
        if cancel_file is not None and cancel_file.exists() \
                and not job.get("cancel_requested"):
            job["cancel_requested"] = True
            save_job(job)
        snap = {k: job[k] for k in _WATCHED if job.get(k) is not None}
        if snap != last:
            last = snap
            _emit({"type": "progress", "job_id": jid, **snap}, out, status_file)
        if stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=tick)
        except asyncio.TimeoutError:
            pass


async def run(spec: dict, out, cancel_file=None, tick: float = 0.15,
              status_file: Path = None) -> int:
    """Run one job to completion; return the process exit code."""
    spec = dict(_validate(spec))
    jid = spec.pop("job_id", None) or spec.pop("id", None)
    source = spec.pop("source")

    jid = await create_file_job(source, job_id=jid, enqueue=False, **spec)
    _emit({"type": "job", "job_id": jid, "work": str(OUTPUT_DIR / jid)},
          out, status_file)

    stop = asyncio.Event()
    watcher = asyncio.create_task(
        _watch(jid, out, cancel_file, stop, tick, status_file))
    code = 0
    try:
        await run_pipeline(jid, **(jobs[jid].get("_pending_args") or {}))
    except JobCancelled:
        # Same handling as app/queue.py: a cancel is a user action, not a
        # crash, and cancel_requested must not linger on the record.
        job = jobs.get(jid) or {}
        job["status"] = "cancelled"
        job.pop("cancel_requested", None)
        save_job(job)
        code = 2
    except Exception as e:
        job = jobs.get(jid) or {}
        job["status"] = "error"
        job["error"] = str(e) or type(e).__name__
        save_job(job)
        code = 1
    finally:
        stop.set()
        await watcher

    job = jobs.get(jid) or {}
    if code == 0:
        _emit({"type": "done", "job_id": jid,
               "status": job.get("status", "complete"),
               "output": job.get("output_url")}, out, status_file)
    elif code == 2:
        _emit({"type": "cancelled", "job_id": jid}, out, status_file)
    else:
        _emit({"type": "error", "job_id": jid,
               "error": job.get("error", "")}, out, status_file)
    return code


def main(argv=None, out=None) -> int:
    out = out if out is not None else sys.stdout
    ap = argparse.ArgumentParser(
        description="Run one dub job and stream NDJSON progress on stdout.")
    ap.add_argument("--spec", required=True, help="path to the JSON job spec")
    ap.add_argument("--status-file", default=None,
                    help="also append every event to this file (truncated first)")
    ap.add_argument("--cancel-file", default=None,
                    help="when this file appears the job is cancelled (exit 2)")
    ap.add_argument("--tick", type=float, default=0.15,
                    help="progress poll interval in seconds (default 0.15)")
    ns = ap.parse_args(argv)

    try:
        spec = load_spec(ns.spec)
    except UsageError as e:
        _emit({"type": "error", "job_id": None, "error": str(e)}, out)
        return 3

    status_file = Path(ns.status_file) if ns.status_file else None
    if status_file is not None:
        status_file.write_text("", encoding="utf-8")  # truncate: this run owns it
    cancel_file = Path(ns.cancel_file) if ns.cancel_file else None

    try:
        return asyncio.run(run(spec, out, cancel_file, ns.tick, status_file))
    except UsageError as e:
        _emit({"type": "error", "job_id": None, "error": str(e)}, out)
        return 3


if __name__ == "__main__":
    sys.exit(main())
