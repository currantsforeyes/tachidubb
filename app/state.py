"""Shared in-memory state for the running server.

Single source of truth for the job store. Kept out of ``server.py`` so
routers and background workers can share it without importing the application
module (which would create import cycles once routes are split out).

``jobs`` is mutated in place and never rebound, so other modules may safely
hold a direct reference to this exact dict.
"""
import logging

from app.db import save_job_sync, load_all_jobs

log = logging.getLogger("tachidubb.state")

# In-memory job store: {job_id: job dict}
jobs: dict = {}

# Statuses that mean "the pipeline is actively working on this job". After a
# restart these can't still be running, so they are marked resumable.
ACTIVE_STATUSES = {
    "queued", "running", "downloading", "extracting",
    "transcribing", "translating", "synthesizing",
    "assembling", "merging",
}


def save_job(job: dict) -> None:
    """Persist one job to the SQLite store."""
    save_job_sync(job)


def load_jobs_from_disk() -> None:
    """Load persisted jobs, then mark any still-'active' jobs as resumable.

    After a server restart the in-memory queue is empty, so jobs that appear
    to still be running aren't actually being processed. Without this, the
    History tab shows them as permanently "transcribing..." / "queued". The
    user can still Resume (if a checkpoint exists) to pick up where the
    pipeline left off.
    """
    jobs.update(load_all_jobs())
    stale_count = 0
    for job in jobs.values():
        if job.get("status") in ACTIVE_STATUSES:
            job["status"] = "error"
            job["error"] = (
                job.get("error")
                or "Interrupted by server restart — click Resume to continue"
            )
            job["stale_from_restart"] = True
            save_job(job)
            stale_count += 1
    if stale_count:
        log.info(
            f"Marked {stale_count} stale job(s) as 'error' "
            f"(left over from previous server run)"
        )
    log.info(f"Loaded {len(jobs)} jobs from disk")