"""Disk-usage accounting and cleanup selection for job outputs.

Extracted from ``server.py`` so the selection rules (which jobs are eligible
for cleanup) and the stats aggregation can be unit-tested against a temp
directory instead of the live ``outputs/`` tree.

Pure with respect to the job dicts: callers pass the in-memory ``jobs``
mapping and (optionally) an output dir.
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

from app.config import OUTPUT_DIR

log = logging.getLogger("tachidubb.storage")


# Files we keep when cleaning "intermediate" artifacts. These are the
# user-visible deliverables; everything else is regenerable from checkpoints.
KEEP_ON_INTERMEDIATE_CLEAN = {
    "dubbed_video.mp4",
    "dubbed_video_subs.mp4",  # burn-in output
    "translated.srt",
    "checkpoint_translation_done.json",
    "checkpoint_tts_done.json",
    # Keep final so Resume stays possible even on cleaned jobs
}

# Only jobs in a settled state may be cleaned; never a running job.
CLEANABLE_STATUSES = ("complete", "error", "cancelled")


def _resolve(output_dir: Optional[Path]) -> Path:
    return Path(output_dir) if output_dir is not None else OUTPUT_DIR


def dir_size_bytes(path: Path) -> int:
    """Fast recursive directory size via os.scandir. Returns 0 on error."""
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += dir_size_bytes(Path(entry.path))
            except OSError:
                continue
    except OSError:
        pass
    return total


def select_cleanup_candidates(
    jobs: dict,
    cutoff: float,
    include_errored: bool = True,
    include_cancelled: bool = True,
    output_dir: Optional[Path] = None,
) -> list:
    """Return ``(job_id, job, work_dir)`` for jobs eligible for cleanup.

    A job qualifies when it is not starred, was created at or before
    ``cutoff``, is in a settled status, and its output directory exists.
    """
    root = _resolve(output_dir)
    candidates = []
    for jid, job in jobs.items():
        if job.get("starred"):
            continue
        if job.get("created", 0) > cutoff:
            continue
        status = job.get("status", "")
        if status not in CLEANABLE_STATUSES:
            continue
        if status == "error" and not include_errored:
            continue
        if status == "cancelled" and not include_cancelled:
            continue
        work = root / jid
        if not work.exists():
            continue
        candidates.append((jid, job, work))
    return candidates


def build_storage_stats(jobs: dict, output_dir: Optional[Path] = None, now: Optional[float] = None) -> dict:
    """Aggregate disk usage across all job outputs.

    Per-job breakdown so the UI can show a sortable list and identify the
    biggest offenders. ``now`` is injectable for deterministic age math.
    """
    root = _resolve(output_dir)
    now = time.time() if now is None else now

    rows = []
    total_bytes = 0
    for jid, job in jobs.items():
        work = root / jid
        if not work.exists():
            continue
        size = dir_size_bytes(work)
        total_bytes += size
        rows.append({
            "id": jid,
            "label": job.get("source_label", jid),
            "status": job.get("status", ""),
            "target_lang": job.get("target_lang", ""),
            "created": job.get("created", 0),
            "completed_at": job.get("completed_at", 0),
            "starred": bool(job.get("starred")),
            "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 1),
            "age_days": round((now - job.get("created", now)) / 86400, 1),
        })
    rows.sort(key=lambda r: -r["size_bytes"])
    return {
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1024 / 1024, 1),
        "total_gb": round(total_bytes / 1024 / 1024 / 1024, 2),
        "job_count": len(rows),
        "jobs": rows,
    }