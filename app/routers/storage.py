"""Storage routes: disk-usage stats, starring, and bulk cleanup.

First route group extracted from ``server.py``. Deliberately chosen because it
depends only on the shared job store (``app.state``) and the storage helpers
(``app.storage``) — no pipeline, queue or GPU coupling.
"""
import logging
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from app.state import jobs, save_job
from app.storage import (
    KEEP_ON_INTERMEDIATE_CLEAN,
    build_storage_stats,
    dir_size_bytes,
    select_cleanup_candidates,
)

log = logging.getLogger("tachidubb.routes.storage")

router = APIRouter()


@router.get("/api/storage/stats")
async def storage_stats():
    """Aggregate disk usage across all job outputs. Per-job breakdown so
    the UI can show a sortable list and identify the biggest offenders."""
    return build_storage_stats(jobs)


@router.post("/api/storage/star/{job_id}")
async def toggle_star(job_id: str, starred: bool = Form(...)):
    """Star/unstar a job to protect it from bulk cleanup."""
    if job_id not in jobs:
        return JSONResponse({"error": "Not found"}, 404)
    jobs[job_id]["starred"] = bool(starred)
    save_job(jobs[job_id])
    return {"ok": True, "starred": jobs[job_id]["starred"]}


@router.post("/api/storage/cleanup")
async def cleanup_storage(
    older_than_days: int = Form(30),
    mode: str = Form("intermediate"),  # "intermediate" | "all_files"
    dry_run: bool = Form(True),
    include_errored: bool = Form(True),
    include_cancelled: bool = Form(True),
):
    """Bulk-remove old job outputs. Starred jobs are always skipped.

    - older_than_days=N — affects jobs created more than N days ago
    - mode=intermediate — keep the dubbed mp4 + srt + checkpoints, drop
      source video + per-segment WAVs + intermediate audio (~90% saving
      on typical jobs, job stays "viewable" but Regenerate may need
      re-download)
    - mode=all_files — rm -rf the whole job output dir (job record kept;
      UI will show "(files deleted)" and no View button)
    - dry_run=True — report what would be deleted, don't touch disk.
    """
    if mode not in ("intermediate", "all_files"):
        return JSONResponse({"error": f"Invalid mode: {mode}"}, 400)

    cutoff = time.time() - older_than_days * 86400
    candidates = select_cleanup_candidates(
        jobs,
        cutoff,
        include_errored=include_errored,
        include_cancelled=include_cancelled,
    )

    bytes_freed = 0
    deleted_files = []
    errors = []
    for jid, job, work in candidates:
        try:
            if mode == "all_files":
                size = dir_size_bytes(work)
                if not dry_run:
                    shutil.rmtree(work, ignore_errors=True)
                    # Mark job as files-deleted so UI can show it without
                    # trying to link to missing mp4. Keep db entry so
                    # history preserves the metadata.
                    job["files_deleted"] = True
                    save_job(job)
                deleted_files.append({"id": jid, "mode": "all_files",
                                       "size_mb": round(size/1024/1024, 1)})
                bytes_freed += size
            else:  # intermediate
                freed_here = 0
                for entry in list(os.scandir(work)):
                    if entry.name in KEEP_ON_INTERMEDIATE_CLEAN:
                        continue
                    try:
                        if entry.is_file(follow_symlinks=False):
                            sz = entry.stat().st_size
                            if not dry_run:
                                Path(entry.path).unlink()
                            freed_here += sz
                        elif entry.is_dir(follow_symlinks=False):
                            sz = dir_size_bytes(Path(entry.path))
                            if not dry_run:
                                shutil.rmtree(entry.path, ignore_errors=True)
                            freed_here += sz
                    except OSError as e:
                        errors.append(f"{jid}: {entry.name}: {e}")
                if freed_here > 0:
                    deleted_files.append({"id": jid, "mode": "intermediate",
                                          "size_mb": round(freed_here/1024/1024, 1)})
                    bytes_freed += freed_here
                if not dry_run:
                    job["intermediate_cleaned"] = True
                    save_job(job)
        except Exception as e:
            errors.append(f"{jid}: {e}")

    action = "would delete" if dry_run else "deleted"
    log.info(f"[cleanup] {action} {len(deleted_files)} jobs, "
             f"{round(bytes_freed/1024/1024/1024, 2)} GB freed "
             f"(mode={mode}, older_than={older_than_days}d, dry_run={dry_run})")
    return {
        "dry_run": dry_run,
        "mode": mode,
        "candidates": len(candidates),
        "affected": len(deleted_files),
        "bytes_freed": bytes_freed,
        "mb_freed": round(bytes_freed / 1024 / 1024, 1),
        "gb_freed": round(bytes_freed / 1024 / 1024 / 1024, 2),
        "details": deleted_files[:50],  # cap to keep payload small
        "errors": errors[:10],
    }