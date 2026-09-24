"""Job submission helpers shared by the HTTP routes and the folder watcher.

``create_file_job`` produces the same job shape as ``/api/dub/batch``'s file
branch, so watched files and uploaded files are indistinguishable downstream
(History, batch summary, cancel, resume). Keeping it here stops the two paths
from drifting.
"""
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from app.queue import enqueue_job
from app.state import jobs, save_job
from pipeline.translator import check_ollama

log = logging.getLogger("tachidubb.submit")

# Fallback order shared by the batch route and the watcher. Fast,
# translation-specialised models first; thinking models last (they stall on
# 12 GB cards).
PREFERRED_MODELS = [
    "aya-expanse:8b", "mistral-nemo:12b", "qwen2.5:14b",
    "qwen2.5:7b", "qwen2.5:3b", "gemma3:12b", "gemma3:4b",
    "llama3.2:3b", "gemma4:e4b", "gemma4:e2b",
]


async def resolve_model(model: str) -> tuple[str, Optional[str]]:
    """Return ``(usable_model, error)``, mirroring the batch route's fallback.

    If Ollama is reachable but the requested model isn't installed, fall back
    to the first preferred model that is. Returns an error string (and an empty
    model) only when Ollama is up with no usable model at all.
    """
    ok, installed = await check_ollama()
    if ok and model not in installed:
        fallback = next((m for m in PREFERRED_MODELS if m in installed), None)
        if fallback:
            log.warning(f"[submit] '{model}' not installed; using '{fallback}'")
            return fallback, None
        return "", "No translation model installed. Run: ollama pull aya-expanse:8b"
    return model, None


async def create_file_job(
    source_path,
    *,
    target_lang: str,
    model: str,
    source_lang: str = "auto",
    whisper_model: str = "large-v3",
    speaker_mode: str = "main",
    context_hint: str = "",
    voice_style: str = "",
    voice_preset: str = "auto",
    tts_speed: str = "balanced",
    keep_bg: bool = False,
    auto_denoise: bool = False,
    narration_mode: bool = False,
    wizard_mode: str = "auto",
    reference_audio: str = "",
    source_label: str = "",
    batch_id: str = "",
    batch_label: str = "",
    scheduled_at: float = 0.0,
    job_id: Optional[str] = None,
) -> str:
    """Create and (unless scheduled) enqueue a dub job for a local file.

    Returns the job id. A ``scheduled_at`` more than 10s in the future parks
    the job as ``status="scheduled"`` with its pipeline args stashed so the
    queue's scheduler can pick it up later.
    """
    jid = job_id or uuid.uuid4().hex[:8]
    src = str(source_path)
    is_scheduled = scheduled_at > time.time() + 10  # 10s grace for clock skew

    pipeline_args = {
        "source": src, "source_lang": source_lang,
        "target_lang": target_lang, "model": model,
        "keep_bg": keep_bg, "whisper_model": whisper_model,
        "reference_audio": reference_audio, "speaker_mode": speaker_mode,
        "context_hint": context_hint, "voice_style": voice_style,
        "voice_preset": voice_preset, "tts_speed": tts_speed,
        "wizard_mode": wizard_mode, "auto_denoise": auto_denoise,
        "narration_mode": bool(narration_mode),
    }

    jobs[jid] = {
        "id": jid,
        "status": "scheduled" if is_scheduled else "queued",
        "progress": 0,
        "source": src,
        "source_type": "file",
        "source_label": source_label or Path(src).name,
        "target_lang": target_lang,
        "model": model,
        "speaker_mode": speaker_mode,
        "context_hint": context_hint,
        "voice_style": voice_style,
        "voice_preset": voice_preset,
        "voice_mode": ("upload" if reference_audio else
                       ("custom" if voice_style.strip() else "preset")),
        "tts_speed": tts_speed,
        "whisper_model": whisper_model,
        "keep_bg": keep_bg,
        "wizard_mode": wizard_mode,
        "auto_denoise": auto_denoise,
        "narration_mode": bool(narration_mode),
        "batch_id": batch_id,
        "batch_label": batch_label,
        "created": time.time(),
        "scheduled_at": scheduled_at if is_scheduled else 0,
        "_pending_args": pipeline_args if is_scheduled else None,
    }
    save_job(jobs[jid])

    if is_scheduled:
        log.info(f"[submit] Job {jid} scheduled for {scheduled_at}")
    else:
        await enqueue_job(jid, pipeline_args)
    return jid