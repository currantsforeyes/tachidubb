"""Folder-watcher routes.

Thin HTTP surface over :mod:`app.watcher` so the watcher can be inspected and
driven without editing config by hand.
"""
from fastapi import APIRouter, Form

from app.config import cfg
from app.watcher import scan_once, start, status, stop

router = APIRouter()


@router.get("/api/watch/status")
async def watch_status():
    """Enabled/running state, the watched dir, pending files, recent history."""
    return status()


@router.post("/api/watch/scan")
async def watch_scan():
    """Run one scan immediately. Returns the jobs that were enqueued."""
    created = await scan_once()
    return {"ok": True, "count": len(created), "enqueued": created}


@router.post("/api/watch/enable")
async def watch_enable(enabled: bool = Form(...)):
    """Turn the watcher on/off at runtime (persisted to config-user.json)."""
    cfg.set("watch_enabled", bool(enabled))
    if enabled:
        start()
    else:
        await stop()
    return status()