"""Pipeline checkpoint files — per-stage resume state for a dub job.

Checkpoints live under ``outputs/<job_id>/``::

    checkpoint_transcription_done.json
    checkpoint_translation_done.json
    checkpoint_tts_done.json
    pipeline_state.json            (legacy; mirrors the most recent stage)

Each file is self-contained — loading it is enough to resume from the
corresponding stage. Extracted from ``server.py`` so the resume logic is
unit-testable without the FastAPI app or a GPU.

The stage/step_* naming is part of the on-disk format; do not rename without a
migration, since existing installs have these files on disk.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

from app.config import OUTPUT_DIR

log = logging.getLogger("tachidubb.checkpoints")

# Most advanced first, so "latest" reflects how far the pipeline got before it
# stopped.
STAGE_ORDER = ("tts_done", "translation_done", "transcription_done")


def _resolve(output_dir: Optional[Path]) -> Path:
    return Path(output_dir) if output_dir is not None else OUTPUT_DIR


def job_checkpoint_info(job_id: str, output_dir: Optional[Path] = None) -> dict:
    """Return which checkpoint stages exist on disk for a job.

    Used by list_jobs so the History UI knows whether an errored or
    cancelled job is resumable (and from where). Purely filesystem
    inspection — cheap enough to do on every /api/jobs poll.
    """
    work_dir = _resolve(output_dir) / job_id
    if not work_dir.exists():
        return {"has_checkpoint": False, "latest_checkpoint_stage": None}
    # Check most-advanced first so 'latest' reflects how far the
    # pipeline got before stopping.
    for stage in STAGE_ORDER:
        if (work_dir / f"checkpoint_{stage}.json").exists():
            return {"has_checkpoint": True, "latest_checkpoint_stage": stage}
    # Legacy single-file pipeline state
    legacy = work_dir / "pipeline_state.json"
    if legacy.exists():
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                d = json.load(f)
            return {
                "has_checkpoint": True,
                "latest_checkpoint_stage": d.get("stage") or "unknown",
            }
        except Exception:
            pass
    return {"has_checkpoint": False, "latest_checkpoint_stage": None}


def save_checkpoint(job_id: str, work_dir: Path, stage: str, data: dict) -> None:
    """Write a named per-stage checkpoint and mirror it to pipeline_state.json."""
    data["stage"] = stage
    data["job_id"] = job_id
    data["saved_at"] = time.time()

    # Named checkpoint (never overwritten by later stages)
    cpath = Path(work_dir) / f"checkpoint_{stage}.json"
    try:
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"[checkpoint] Saved: {stage} -> {cpath.name}")
    except Exception as e:
        log.warning(f"[checkpoint] Save failed ({stage}): {e}")

    # Legacy pipeline_state.json — always the MOST RECENT checkpoint
    try:
        with open(Path(work_dir) / "pipeline_state.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"[checkpoint] Legacy save failed: {e}")


def load_checkpoint(job_id: str, stage: str, output_dir: Optional[Path] = None) -> Optional[dict]:
    """Load a specific checkpoint. Returns None if not found."""
    work_dir = _resolve(output_dir) / job_id
    cpath = work_dir / f"checkpoint_{stage}.json"
    if not cpath.exists():
        # Fallback to legacy pipeline_state.json if it matches the stage
        legacy = work_dir / "pipeline_state.json"
        if legacy.exists():
            try:
                with open(legacy, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("stage") == stage:
                    return d
            except Exception:
                pass
        return None
    try:
        with open(cpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"[checkpoint] Load failed ({stage}): {e}")
        return None


def latest_checkpoint(job_id: str, output_dir: Optional[Path] = None) -> Optional[dict]:
    """Return the most advanced checkpoint available for a job."""
    for stage in STAGE_ORDER:
        cp = load_checkpoint(job_id, stage, output_dir=output_dir)
        if cp:
            return cp
    return None