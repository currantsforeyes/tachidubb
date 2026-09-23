"""Lip-sync routes: MuseTalk availability + on-demand run."""
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.lipsync import run_lipsync
from app.state import jobs
from pipeline.lipsync import find_musetalk_setup, lipsync_status_payload, musetalk_install_guide

log = logging.getLogger("tachidubb.routes.lipsync")

router = APIRouter()


@router.get("/api/lip_sync/status")
async def lip_sync_status():
    """Quick detection endpoint — UI calls this to decide whether to show
    the lip-sync button lit (ready) or greyed (needs install)."""
    return lipsync_status_payload()


@router.post("/api/dub/{job_id}/lip_sync")
async def lip_sync(job_id: str):
    """Apply MuseTalk to the dubbed video (manual on-demand endpoint).

    Returns the new video URL when done. Same code path is also used
    automatically by the pipeline when a job was submitted with
    `lip_sync=true` on the original form.
    """
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    if not find_musetalk_setup():
        return JSONResponse(musetalk_install_guide(), 501)
    # Run in executor — MuseTalk is heavy synchronous CPU/GPU work
    result = await asyncio.get_event_loop().run_in_executor(
        None, run_lipsync, job_id)
    if "error" in result:
        return JSONResponse(result, 500)
    return result