"""Batch folder watcher — auto-dub videos dropped into a folder.

Opt-in (``TACHIDUBB_WATCH_ENABLED=1`` or ``watch_enabled`` in config). A
background task polls the watch directory and, for every *completed* video
file it finds, creates a normal dub job (via :func:`app.submit.create_file_job`)
and moves the file into ``<watch>/processed/``. Because processed files are
moved out, re-starting the server never re-dubs them.

Files that look half-copied are skipped until their mtime is older than
``MIN_AGE_SECONDS`` — so a large file still being written isn't picked up
mid-transfer. Nothing here touches the GPU; the jobs go through the same
serial queue as everything else.
"""
import asyncio
import logging
import shutil
import time
from pathlib import Path

from app.config import BASE, WATCH_DIR, cfg
from app.submit import create_file_job, resolve_model

log = logging.getLogger("tachidubb.watch")

VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v",
    ".flv", ".wmv", ".mpeg", ".mpg", ".ts",
}
# Browser/downloader leftovers that must never be treated as final files.
PARTIAL_SUFFIXES = (".part", ".crdownload", ".tmp", ".download", ".filepart")

MIN_AGE_SECONDS = 5.0
MAX_HISTORY = 20

_watch_task = None
# Files already acted on this session (created a job for, or failed). Guards
# against re-enqueueing when the move to processed/ didn't happen.
_handled: set = set()
_recent_processed: list = []
_recent_errors: list = []


# ── directory resolution ─────────────────────────────────────────────
def watch_dir() -> Path:
    """The directory being watched (config override, else <repo>/watch)."""
    raw = (getattr(cfg, "watch_dir", "") or "").strip()
    if not raw:
        return WATCH_DIR
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (BASE / p)


def processed_dir() -> Path:
    return watch_dir() / "processed"


# ── scanning ─────────────────────────────────────────────────────────
def is_candidate(path: Path) -> bool:
    """True if `path` is a video file we should consider (not a partial/temp)."""
    try:
        if not path.is_file():
            return False
    except OSError:
        return False
    name = path.name
    if name.startswith("."):
        return False
    if path.suffix.lower() not in VIDEO_EXTS:
        return False
    return not name.lower().endswith(PARTIAL_SUFFIXES)


def list_candidates(directory: Path | None = None) -> list[Path]:
    """All candidate video files in the watch dir (recency not considered)."""
    d = Path(directory) if directory is not None else watch_dir()
    if not d.is_dir():
        return []
    try:
        entries = sorted(d.iterdir())
    except OSError:
        return []
    return [p for p in entries if is_candidate(p)]


def list_ready_files(
    directory: Path | None = None,
    *,
    now: float | None = None,
    min_age: float = MIN_AGE_SECONDS,
    skip: set | None = None,
) -> list[Path]:
    """Candidates whose mtime is at least `min_age` old (i.e. fully written)."""
    now = time.time() if now is None else now
    skip = skip or set()
    ready = []
    for p in list_candidates(directory):
        if p in skip:
            continue
        try:
            age = now - p.stat().st_mtime
        except OSError:
            continue
        if age >= min_age:
            ready.append(p)
    return ready


def _move_to_processed(path: Path) -> Path:
    dst_dir = processed_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / path.name
    if dst.exists():  # same filename dropped twice — keep both
        dst = dst_dir / f"{path.stem}__{int(time.time())}{path.suffix}"
    shutil.move(str(path), str(dst))
    return dst


# ── one scan ─────────────────────────────────────────────────────────
async def scan_once() -> list[dict]:
    """Enqueue a job for every ready file; return what was enqueued.

    Returns a list of ``{"file", "job_id", "moved_to"}`` dicts. On a model
    error nothing is enqueued and the files are left in place to retry.
    """
    files = list_ready_files(skip=_handled)
    if not files:
        return []

    model = (getattr(cfg, "watch_model", "") or "").strip() or cfg.translation_model
    model, err = await resolve_model(model)
    if err:
        _record_error(err)
        log.warning(f"[watch] not enqueueing {len(files)} file(s): {err}")
        return []

    created: list[dict] = []
    for f in files:
        _handled.add(f)  # never act on the same path twice in one session
        try:
            jid = await create_file_job(
                f,
                target_lang=cfg.watch_target_lang,
                model=model,
                whisper_model=cfg.whisper_model,
                tts_speed=cfg.tts_speed,
                auto_denoise=cfg.auto_denoise,
                wizard_mode="auto",
                source_label=f.name,
                batch_id="watch",
                batch_label="Folder watch",
            )
            moved = _move_to_processed(f)
            entry = {"file": f.name, "job_id": jid, "moved_to": str(moved)}
            created.append(entry)
            _recent_processed.append(entry)
            log.info(f"[watch] {f.name} -> job {jid} (moved to {moved})")
        except Exception as e:
            msg = f"{f.name}: {e}"
            _record_error(msg)
            log.warning(f"[watch] failed to enqueue {f.name}: {e}", exc_info=True)
    return created


def _record_error(msg: str) -> None:
    _recent_errors.append({"at": time.time(), "error": msg})


# ── background loop ──────────────────────────────────────────────────
async def watch_loop() -> None:
    log.info(f"[watch] Watching {watch_dir()} every {cfg.watch_poll_seconds}s "
             f"-> {cfg.watch_target_lang}")
    try:
        while True:
            try:
                await scan_once()
            except Exception as e:
                log.warning(f"[watch] scan failed (continuing): {e}")
            await asyncio.sleep(max(5, int(cfg.watch_poll_seconds)))
    except asyncio.CancelledError:
        log.info("[watch] Loop cancelled, exiting")


def start() -> None:
    """Start the watcher if enabled. Idempotent; no-op when disabled."""
    global _watch_task
    if _watch_task is not None and not _watch_task.done():
        return
    if not getattr(cfg, "watch_enabled", False):
        log.debug("[watch] disabled")
        return
    log.info("[watch] Enabled")
    _watch_task = asyncio.create_task(watch_loop())


async def stop() -> None:
    global _watch_task
    if _watch_task is not None and not _watch_task.done():
        _watch_task.cancel()
        try:
            await _watch_task
        except (asyncio.CancelledError, Exception):
            pass
    _watch_task = None


def status() -> dict:
    """Snapshot for the /api/watch/status endpoint and the CLI."""
    d = watch_dir()
    return {
        "enabled": bool(getattr(cfg, "watch_enabled", False)),
        "running": _watch_task is not None and not _watch_task.done(),
        "dir": str(d),
        "processed_dir": str(processed_dir()),
        "target_lang": cfg.watch_target_lang,
        "poll_seconds": cfg.watch_poll_seconds,
        "pending": [p.name for p in list_candidates(d) if p not in _handled],
        "handled": len(_handled),
        "recent_processed": list(_recent_processed[-MAX_HISTORY:]),
        "recent_errors": list(_recent_errors[-MAX_HISTORY:]),
    }