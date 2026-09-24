"""Dub routes: submit (single/batch/quick-test) and per-job editing.

Extracted from ``server.py``. Handlers are thin HTTP glue over ``app.pipeline``,
``app.queue`` and ``app.checkpoints``.
"""
import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.checkpoints import (
    latest_checkpoint as _latest_checkpoint,
    load_checkpoint as _load_checkpoint,
    save_checkpoint as _save_checkpoint,
)
from app.config import OUTPUT_DIR, UPLOAD_DIR
from app.languages import (
    QUICK_TEST_KNOWN_LANGS as _QUICK_TEST_KNOWN_LANGS,
)
from app.pipeline import (
    retry_tts_pipeline,
    _continue_from_checkpoint,
    _regen_single_segment,
    _retranslate_stage,
)
from app.queue import enqueue_job
from app.state import jobs, save_job
from app.submit import create_file_job, resolve_model
from pipeline.assembler import assemble_dubbed_audio, merge_audio_video, write_srt
from pipeline.media import trim_video as _trim_video
from pipeline.media import waveform_peaks as _waveform_peaks
from pipeline.showcase import (
    load_placements as _load_placements,
    save_placements as _save_placements,
)
from pipeline.translator import check_ollama

log = logging.getLogger("tachidubb.routes.dub")

router = APIRouter()



@router.post("/api/dub")
async def start_dub(
    source: str = Form(""),
    video: Optional[UploadFile] = File(None),
    reference: Optional[UploadFile] = File(None),
    source_lang: str = Form("auto"),
    target_lang: str = Form("ru"),
    model: str = Form("gemma4:e4b"),
    keep_bg: bool = Form(False),
    whisper_model: str = Form("large-v3"),
    speaker_mode: str = Form("main"),   # "main" | "all"
    speaker_count: int = Form(0),         # 0 = automatic; 2-20 = force count
    context_hint: str = Form(""),
    voice_style: str = Form(""),
    voice_preset: str = Form("auto"),
    tts_speed: str = Form("balanced"),
    wizard_mode: str = Form("auto"),  # "auto" | "review_translation" | "review_transcript"
    auto_denoise: bool = Form(False),
    lip_sync: bool = Form(False),  # if True, auto-run MuseTalk after the pipeline completes
    narration_mode: bool = Form(False),  # single narrator voice; skip diarization
):
    # Validate translation model exists in Ollama - fall back gracefully otherwise.
    _ok, _installed = await check_ollama()
    if _ok and model not in _installed:
        # Preference order: fast non-thinking translation-specialized
        # models first, then general purpose, then thinking models last.
        # gemma4:e4b/e2b work but hang on 12 GB GPUs due to thinking
        # mode — kept as last-resort fallback only.
        _preferred = [
            "aya-expanse:8b",      # Cohere multilingual, best EN↔RU
            "mistral-nemo:12b",    # Mistral, strong for European langs
            "qwen2.5:14b",         # Qwen direct-output, very good
            "qwen2.5:7b",          # Recommended balance of quality and VRAM
            "qwen2.5:3b",          # Lightweight direct-output fallback
            "gemma3:12b",          # Gemma3 (no thinking) — good quality
            "gemma3:4b",           # Gemma3 small
            "llama3.2:3b",         # Tiny fallback
            "qwen3:14b",           # Larger qwen3 (thinking optional)
            "gemma4:e4b",          # Thinking — heavy on 12 GB GPU
            "gemma4:e2b",          # Thinking — smaller but same issue
        ]
        _fallback = next((m for m in _preferred if m in _installed), None)
        if _fallback is None and _installed:
            _fallback = _installed[0]
        if _fallback:
            log.warning(f"Requested model '{model}' not installed; using '{_fallback}' instead")
            model = _fallback
        else:
            return JSONResponse({
                "error": "No translation model installed. Pull one via 'ollama pull aya-expanse:8b' "
                          "or use the Models panel."
            }, 400)

    # Multi-speaker dubbing requires diarization.  Without an HF token
    # pyannote is skipped and every line silently receives SPEAKER_00's
    # fallback reference, which is worse than an explicit setup error.
    if speaker_mode == "all" and not os.getenv("HF_TOKEN", "").strip():
        return JSONResponse({
            "error": (
                "Multi-speaker dubbing needs Hugging Face diarization, but HF_TOKEN "
                "is not configured. Add HF_TOKEN=hf_xxx to .env, accept the "
                "pyannote model terms, restart TachiDUBB, and retry."
            ),
            "setup_urls": [
                "https://huggingface.co/settings/tokens",
                "https://huggingface.co/pyannote/speaker-diarization-community-1",
            ],
        }, 400)
    if speaker_count < 0 or speaker_count > 20:
        return JSONResponse({"error": "Speaker count must be between 2 and 20, or auto."}, 400)
    if speaker_count == 1:
        speaker_count = 0

    job_id = uuid.uuid4().hex[:8]
    work = OUTPUT_DIR / job_id
    work.mkdir(exist_ok=True)

    if video and video.filename:
        ext = Path(video.filename).suffix or ".mp4"
        vid_path = str(UPLOAD_DIR / f"{job_id}{ext}")
        with open(vid_path, "wb") as f:
            shutil.copyfileobj(video.file, f)
        actual_source = vid_path
        source_type = "upload"
        source_label = video.filename
    elif source:
        actual_source = source
        source_type = "url" if source.startswith("http") else "path"
        source_label = source
    else:
        return JSONResponse({"error": "Provide a YouTube URL or upload a video"}, 400)

    ref_path = ""
    if reference and reference.filename:
        ref_ext = Path(reference.filename).suffix or ".wav"
        ref_path = str(UPLOAD_DIR / f"{job_id}_ref{ref_ext}")
        with open(ref_path, "wb") as f:
            shutil.copyfileobj(reference.file, f)

    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "source": actual_source,
        "source_type": source_type,
        "source_label": source_label,
        "target_lang": target_lang,
        "model": model,
        "speaker_mode": speaker_mode,
        "speaker_count_requested": speaker_count,
        "context_hint": context_hint,
        "voice_style": voice_style,
        "voice_preset": voice_preset,
        "voice_mode": ("upload" if ref_path else
                       ("custom" if voice_style.strip() else "preset")),
        "tts_speed": tts_speed,
        "wizard_mode": wizard_mode,
        "lip_sync": bool(lip_sync),
        "narration_mode": bool(narration_mode),
        "created": time.time(),
        "step_detail": "Queued...",
    }
    save_job(jobs[job_id])

    # Dispatch to pipeline — via queue if GPU is busy, else directly.
    # Multiple simultaneous dub requests would OOM the 12GB 3080 Ti
    # (WhisperX large-v3 + VoxCPM + pyannote = 9-10GB each). The queue
    # ensures only ONE GPU-heavy job runs at a time; others wait.
    await enqueue_job(job_id, {
        "source": actual_source,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": model,
        "keep_bg": keep_bg,
        "whisper_model": whisper_model,
        "reference_audio": ref_path,
        "speaker_mode": speaker_mode,
        "speaker_count": speaker_count,
        "context_hint": context_hint,
        "voice_style": voice_style,
        "voice_preset": voice_preset,
        "tts_speed": tts_speed,
        "wizard_mode": wizard_mode,
        "auto_denoise": auto_denoise,
        "narration_mode": bool(narration_mode),
    })

    return {"job_id": job_id}



@router.post("/api/dub/batch")
async def start_batch_dub(
    sources: str = Form(""),  # newline-separated URLs OR json list
    videos: Optional[list[UploadFile]] = File(None),
    reference: Optional[UploadFile] = File(None),
    source_lang: str = Form("auto"),
    target_lang: str = Form("ru"),
    model: str = Form("aya-expanse:8b"),
    keep_bg: bool = Form(False),
    whisper_model: str = Form("large-v3"),
    speaker_mode: str = Form("main"),
    context_hint: str = Form(""),
    voice_style: str = Form(""),
    voice_preset: str = Form("auto"),
    tts_speed: str = Form("balanced"),
    wizard_mode: str = Form("auto"),  # Usually "auto" for batch — no pauses
    auto_denoise: bool = Form(False),
    narration_mode: bool = Form(False),  # single narrator voice; skip diarization
    batch_label: str = Form(""),  # optional: "BJJ Course Week 1" for summary
    scheduled_at: float = Form(0.0),  # unix epoch seconds; 0 = start immediately
):
    """Enqueue multiple videos for night-mode processing.

    Intended flow: user drops 5-10 videos in UI, picks a preset, clicks
    "Queue all". Each video becomes a separate job sharing common
    settings (target lang, voice, context). Jobs run serially via the
    GPU queue. Sleep prevention auto-activates while queue is non-empty.

    When scheduled_at is set to a future timestamp, jobs are created
    with status="scheduled" and a background task enqueues them at the
    target time. Useful for "queue this now, start at 2 AM when
    electricity is cheap" workflows.

    Returns: {job_ids: [...], batch_id: str} so UI can track summary.
    """
    # Validate Ollama model once (not per-job)
    model, _model_err = await resolve_model(model)
    if _model_err:
        return JSONResponse({"error": _model_err}, 400)

    # Save shared reference once — all batch jobs reuse it
    ref_path = ""
    if reference and reference.filename:
        ref_ext = Path(reference.filename).suffix or ".wav"
        ref_path = str(UPLOAD_DIR / f"batch_{uuid.uuid4().hex[:8]}_ref{ref_ext}")
        with open(ref_path, "wb") as f:
            shutil.copyfileobj(reference.file, f)
        log.info(f"[batch] Saved shared reference: {ref_path}")

    # Collect sources: URLs from form + uploaded files
    batch_id = f"batch_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    job_ids = []

    # 1. URLs (newline-separated or JSON list)
    url_list = []
    if sources.strip():
        s = sources.strip()
        if s.startswith("["):
            try:
                url_list = json.loads(s)
            except Exception:
                url_list = [ln.strip() for ln in s.splitlines() if ln.strip()]
        else:
            url_list = [ln.strip() for ln in s.splitlines() if ln.strip()]

    # When a scheduled_at is in the future, jobs are parked in the jobs
    # dict with status='scheduled' and a background task wakes them up
    # at the target time. Otherwise we enqueue immediately as before.
    now = time.time()
    is_scheduled = scheduled_at > now + 10  # 10s grace for clock skew
    initial_status = "scheduled" if is_scheduled else "queued"

    async def _enqueue_or_defer(jid, pipeline_args):
        if not is_scheduled:
            await enqueue_job(jid, pipeline_args)
        else:
            # Just leave status=scheduled; the scheduler task will pick it up
            log.info(f"[schedule] Job {jid} deferred until {scheduled_at}")

    for url in url_list:
        if not url:
            continue
        jid = uuid.uuid4().hex[:8]
        jobs[jid] = {
            "id": jid,
            "status": initial_status,
            "progress": 0,
            "source": url,
            "source_type": "url",
            "source_label": url[:60] + ("..." if len(url) > 60 else ""),
            "target_lang": target_lang,
            "model": model,
            "speaker_mode": speaker_mode,
            "context_hint": context_hint,
            "voice_style": voice_style,
            "voice_preset": voice_preset,
            "voice_mode": ("upload" if ref_path else
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
            # When scheduled, stash full pipeline args on the job so the
            # scheduler can re-hydrate and enqueue later
            "_pending_args": ({
                "source": url, "source_lang": source_lang,
                "target_lang": target_lang, "model": model,
                "keep_bg": keep_bg, "whisper_model": whisper_model,
                "reference_audio": ref_path, "speaker_mode": speaker_mode,
                "context_hint": context_hint, "voice_style": voice_style,
                "voice_preset": voice_preset, "tts_speed": tts_speed,
                "wizard_mode": wizard_mode, "auto_denoise": auto_denoise,
                "narration_mode": bool(narration_mode),
            } if is_scheduled else None),
        }
        save_job(jobs[jid])
        await _enqueue_or_defer(jid, {
            "source": url, "source_lang": source_lang,
            "target_lang": target_lang, "model": model,
            "keep_bg": keep_bg, "whisper_model": whisper_model,
            "reference_audio": ref_path, "speaker_mode": speaker_mode,
            "context_hint": context_hint, "voice_style": voice_style,
            "voice_preset": voice_preset, "tts_speed": tts_speed,
            "wizard_mode": wizard_mode, "auto_denoise": auto_denoise,
            "narration_mode": bool(narration_mode),
        })
        job_ids.append(jid)

    # 2. Uploaded files
    for video in (videos or []):
        if not video.filename:
            continue
        jid = uuid.uuid4().hex[:8]
        video_ext = Path(video.filename).suffix or ".mp4"
        dest = UPLOAD_DIR / f"{jid}{video_ext}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(video.file, f)
        await create_file_job(
            dest, job_id=jid,
            target_lang=target_lang, model=model, source_lang=source_lang,
            whisper_model=whisper_model, speaker_mode=speaker_mode,
            context_hint=context_hint, voice_style=voice_style,
            voice_preset=voice_preset, tts_speed=tts_speed, keep_bg=keep_bg,
            auto_denoise=auto_denoise, narration_mode=narration_mode,
            wizard_mode=wizard_mode, reference_audio=ref_path,
            source_label=video.filename, batch_id=batch_id,
            batch_label=batch_label, scheduled_at=scheduled_at,
        )
        job_ids.append(jid)

    if is_scheduled:
        log.info(f"[batch] {batch_id}: SCHEDULED {len(job_ids)} jobs for "
                 f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(scheduled_at))} "
                 f"(label: {batch_label or 'untitled'})")
    else:
        log.info(f"[batch] {batch_id}: enqueued {len(job_ids)} jobs "
                 f"(label: {batch_label or 'untitled'})")
    return {
        "batch_id": batch_id,
        "job_ids": job_ids,
        "count": len(job_ids),
        "label": batch_label,
    }



@router.get("/api/dub/batch/{batch_id}")
async def get_batch_summary(batch_id: str):
    """Summary of a batch run — how many complete, failed, still running.
    Used by UI to show 'night-mode' dashboard."""
    batch_jobs = [j for j in jobs.values() if j.get("batch_id") == batch_id]
    if not batch_jobs:
        return JSONResponse({"error": "Batch not found"}, 404)
    total = len(batch_jobs)
    complete = sum(1 for j in batch_jobs if j.get("status") == "complete")
    errored = sum(1 for j in batch_jobs if j.get("status") == "error")
    queued = sum(1 for j in batch_jobs if j.get("status") == "queued")
    running = total - complete - errored - queued
    started = min((j.get("created", 0) for j in batch_jobs), default=0)
    finished = max((j.get("completed_at", j.get("created", 0))
                    for j in batch_jobs if j.get("status") in ("complete", "error")),
                   default=0)
    elapsed = (finished - started) if finished > started else (time.time() - started)
    return {
        "batch_id": batch_id,
        "label": batch_jobs[0].get("batch_label", ""),
        "total": total,
        "complete": complete,
        "errored": errored,
        "queued": queued,
        "running": running,
        "started": started,
        "finished": finished if complete + errored == total else None,
        "elapsed_sec": int(elapsed),
        "jobs": [{
            "id": j["id"],
            "label": j.get("source_label", j["id"]),
            "status": j.get("status"),
            "progress": j.get("progress", 0),
            "error": j.get("error", ""),
            "dubbed_url": (f"/outputs/{j['id']}/dubbed_video.mp4"
                          if j.get("status") == "complete" else None),
        } for j in sorted(batch_jobs, key=lambda x: x.get("created", 0))],
    }


@router.post("/api/quick_test")
async def start_quick_test(
    video: Optional[UploadFile] = File(None),
    source: str = Form(""),                # YouTube/direct URL
    reference: Optional[UploadFile] = File(None),
    trim_seconds: int = Form(60),
    target_langs: str = Form(""),          # comma-separated e.g. "es,fr,de,ja,pt"
    source_lang: str = Form("auto"),
    model: str = Form("aya-expanse:8b"),
    whisper_model: str = Form("large-v3"),
    speaker_mode: str = Form("main"),
    voice_preset: str = Form("auto"),
    voice_style: str = Form(""),
    tts_speed: str = Form("balanced"),
    keep_bg: bool = Form(False),
    auto_denoise: bool = Form(False),
    narration_mode: bool = Form(False),  # single narrator voice; skip diarization
    context_hint: str = Form(""),
    batch_label: str = Form(""),
):
    """Quick-test: trim a short clip and fan out into N normal dub jobs
    (one per target language) sharing a batch_id. The user gets a side-by-
    side comparison in the Batch view.
    """
    # ── Validate inputs ───────────────────────────────────────────────
    if not video and not source.strip():
        return JSONResponse({"error": "Provide either a video file or a URL"}, 400)
    if video and source.strip():
        return JSONResponse({"error": "Provide only one of video or url"}, 400)

    if trim_seconds < 15 or trim_seconds > 120:
        return JSONResponse(
            {"error": f"trim_seconds must be between 15 and 120 (got {trim_seconds})"},
            400,
        )

    langs = [c.strip() for c in target_langs.split(",") if c.strip()]
    if not (2 <= len(langs) <= 6):
        return JSONResponse(
            {"error": f"Pick 2-6 target languages (got {len(langs)})"}, 400)
    unknown = [c for c in langs if c not in _QUICK_TEST_KNOWN_LANGS]
    if unknown:
        return JSONResponse(
            {"error": f"Unknown language code(s): {unknown}"}, 400)
    if len(set(langs)) != len(langs):
        return JSONResponse({"error": "Duplicate language codes"}, 400)

    # ── Validate Ollama model (same fallback logic as start_batch_dub) ─
    _ok, _installed = await check_ollama()
    if _ok and model not in _installed:
        _preferred = ["aya-expanse:8b", "mistral-nemo:12b", "qwen2.5:14b",
                      "qwen2.5:7b", "qwen2.5:3b", "gemma3:12b", "gemma3:4b",
                      "llama3.2:3b", "gemma4:e4b", "gemma4:e2b"]
        _fallback = next((m for m in _preferred if m in _installed), None)
        if _fallback:
            log.warning(f"[quick_test] '{model}' not installed; using '{_fallback}'")
            model = _fallback
        else:
            return JSONResponse({
                "error": "No translation model installed. Run: ollama pull aya-expanse:8b"
            }, 400)

    # ── Save shared reference (one upload, reused by all jobs) ────────
    ref_path = ""
    if reference and reference.filename:
        ref_ext = Path(reference.filename).suffix or ".wav"
        ref_path = str(UPLOAD_DIR / f"qt_{uuid.uuid4().hex[:8]}_ref{ref_ext}")
        with open(ref_path, "wb") as f:
            shutil.copyfileobj(reference.file, f)
        log.info(f"[quick_test] Saved shared reference: {ref_path}")

    # ── Materialize the source file locally ───────────────────────────
    # File uploads write straight to uploads/. URLs go through yt-dlp first
    # so the trim step is centralized — we don't fan out N downloads.
    src_path: Path
    src_label: str
    if video and video.filename:
        ext = Path(video.filename).suffix or ".mp4"
        src_path = UPLOAD_DIR / f"qt_{uuid.uuid4().hex[:8]}{ext}"
        with open(src_path, "wb") as f:
            shutil.copyfileobj(video.file, f)
        src_label = video.filename
    else:
        from pipeline.downloader import download_video
        url = source.strip()
        src_label = url[:60] + ("..." if len(url) > 60 else "")
        try:
            dl_dir = UPLOAD_DIR / f"qt_{uuid.uuid4().hex[:8]}"
            dl_dir.mkdir(parents=True, exist_ok=True)
            src_path = Path(download_video(url, str(dl_dir)))
        except Exception as e:
            return JSONResponse(
                {"error": f"Could not download URL: {e}"}, 400)

    # ── Trim ──────────────────────────────────────────────────────────
    trimmed_path = src_path.parent / f"{src_path.stem}_qt{trim_seconds}s.mp4"
    try:
        _trim_video(src_path, trimmed_path, trim_seconds)
    except Exception as e:
        err_msg = ""
        if hasattr(e, "stderr") and getattr(e, "stderr", None):
            err_msg = e.stderr.decode("utf-8", errors="replace")[-300:]
        log.warning(f"[quick_test] trim failed: {e} :: {err_msg}")
        return JSONResponse(
            {"error": "Could not trim video", "detail": err_msg or str(e)}, 500)

    # ── Fan out: one job per language, all sharing one batch_id ───────
    batch_id = f"qt_{uuid.uuid4().hex[:8]}"
    label_final = batch_label or f"Quick test · {trim_seconds}s · {len(langs)} langs"
    job_ids: list = []

    for idx, lang in enumerate(langs):
        jid = uuid.uuid4().hex[:8]
        jobs[jid] = {
            "id": jid,
            "status": "queued",
            "progress": 0,
            "source": str(trimmed_path),
            "source_type": "file",
            "source_label": f"{src_label} -> {lang.upper()}",
            "target_lang": lang,
            "model": model,
            "speaker_mode": speaker_mode,
            "context_hint": context_hint,
            "voice_style": voice_style,
            "voice_preset": voice_preset,
            "voice_mode": ("upload" if ref_path else
                          ("custom" if voice_style.strip() else "preset")),
            "tts_speed": tts_speed,
            "whisper_model": whisper_model,
            "keep_bg": keep_bg,
            "wizard_mode": "auto",     # never pause in quick-test mode
            "auto_denoise": auto_denoise,
            "narration_mode": bool(narration_mode),
            "batch_id": batch_id,
            "batch_label": label_final,
            "batch_kind": "quick_test",
            "batch_position": idx,
            "batch_total": len(langs),
            "created": time.time(),
            "scheduled_at": 0,
            "_pending_args": None,
        }
        save_job(jobs[jid])
        await enqueue_job(jid, {
            "source": str(trimmed_path),
            "source_lang": source_lang,
            "target_lang": lang,
            "model": model,
            "keep_bg": keep_bg,
            "whisper_model": whisper_model,
            "reference_audio": ref_path,
            "speaker_mode": speaker_mode,
            "context_hint": context_hint,
            "voice_style": voice_style,
            "voice_preset": voice_preset,
            "tts_speed": tts_speed,
            "wizard_mode": "auto",
            "auto_denoise": auto_denoise,
            "narration_mode": bool(narration_mode),
        })
        job_ids.append(jid)

    log.info(f"[quick_test] {batch_id}: enqueued {len(job_ids)} jobs "
             f"({trim_seconds}s, langs={langs})")

    return {
        "ok": True,
        "batch_id": batch_id,
        "batch_kind": "quick_test",
        "job_ids": job_ids,
        "count": len(job_ids),
        "trimmed_file": f"/uploads/{trimmed_path.name}",
        "trim_seconds": trim_seconds,
        "target_langs": langs,
    }


@router.post("/api/dub/{job_id}/retry_tts")
async def retry_tts(
    job_id: str,
    voice_style: str = Form(""),
    voice_preset: str = Form("auto"),
    tts_speed: str = Form("balanced"),
    reference: Optional[UploadFile] = File(None),
):
    """Re-runs only TTS + merge stages using saved state from a completed job.
    Much faster than re-running the full pipeline (no download, transcribe,
    translate steps)."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)

    ref_path = ""
    if reference and reference.filename:
        ref_ext = Path(reference.filename).suffix or ".wav"
        ref_path = str(UPLOAD_DIR / f"{job_id}_retry_ref{ref_ext}")
        with open(ref_path, "wb") as f:
            shutil.copyfileobj(reference.file, f)

    asyncio.create_task(retry_tts_pipeline(
        job_id, voice_style, voice_preset, tts_speed, ref_path,
    ))
    return {"ok": True, "job_id": job_id}


# ─────────────────────────────────────────────────────────────
# API: Wizard / Checkpoint Endpoints
# ─────────────────────────────────────────────────────────────



@router.get("/api/dub/{job_id}/checkpoint/{stage}")
async def get_checkpoint(job_id: str, stage: str):
    """Return the contents of a saved checkpoint for the UI to display.
    Useful for editable transcript/translation review screens."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    cp = _load_checkpoint(job_id, stage)
    if not cp:
        return JSONResponse({"error": f"Checkpoint '{stage}' not found"}, 404)

    # Expose speaker_refs as {speaker_id: basename} — the UI shows the
    # filename so the user knows which ref is active and can replace it.
    # We don't send absolute paths (server-internal).
    refs_summary = {}
    for spk, path in (cp.get("speaker_refs") or {}).items():
        if path and os.path.exists(path):
            try:
                import soundfile as _sf
                info = _sf.info(path)
                refs_summary[spk] = {
                    "filename": os.path.basename(path),
                    "duration": round(info.frames / info.samplerate, 1),
                    "is_user_upload": os.path.basename(path).startswith("user_"),
                }
            except Exception:
                refs_summary[spk] = {
                    "filename": os.path.basename(path),
                    "duration": None, "is_user_upload": False,
                }

    return {
        "stage": cp.get("stage"),
        "saved_at": cp.get("saved_at"),
        "target_lang": cp.get("target_lang"),
        "duration": cp.get("duration"),
        "segments": cp.get("segments", []),
        "speaker_refs": refs_summary,
    }



@router.post("/api/dub/{job_id}/edit_translations")
async def edit_translations(job_id: str, edits: str = Form(...)):
    """Update the translated_text for one or more segments in the saved
    checkpoint. `edits` is a JSON string: {"<idx>": "new translation", ...}
    After editing, the user should call /continue to proceed to TTS."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    cp = _load_checkpoint(job_id, "translation_done")
    if not cp:
        return JSONResponse({"error": "No translation checkpoint to edit"}, 404)
    try:
        edit_map = json.loads(edits)
        if not isinstance(edit_map, dict):
            raise ValueError("edits must be a JSON object")
    except Exception as e:
        return JSONResponse({"error": f"Invalid edits JSON: {e}"}, 400)

    # Apply edits by segment index (string keys from the JSON)
    n_edited = 0
    for s in cp.get("segments", []):
        key = str(s.get("idx"))
        if key in edit_map:
            new_text = str(edit_map[key]).strip()
            if new_text and new_text != s.get("translated_text"):
                s["translated_text"] = new_text
                n_edited += 1
    # Re-save the translation_done checkpoint with the edits
    work = OUTPUT_DIR / job_id
    _save_checkpoint(job_id, work, stage="translation_done", data=cp)

    # Re-export SRT with the user's edits so .srt download always matches
    # what gets spoken. Also update tts_done if it exists (per-segment
    # regen panel uses it for translated_text display).
    if n_edited > 0:
        try:
            srt_path = str(work / "subtitles.srt")
            write_srt(cp.get("segments", []), srt_path)
        except Exception as e:
            log.warning(f"[edit] SRT re-export failed: {e}")
        tcp = _load_checkpoint(job_id, "tts_done")
        if tcp:
            tcp_segs = tcp.get("segments", [])
            tcp_by_idx = {s.get("idx"): s for s in tcp_segs}
            for seg in cp.get("segments", []):
                t = tcp_by_idx.get(seg.get("idx"))
                if t is not None:
                    t["translated_text"] = seg.get("translated_text", "")
            _save_checkpoint(job_id, work, stage="tts_done", data=tcp)

    log.info(f"[edit] Applied {n_edited} translation edits for job {job_id}")
    return {"ok": True, "edited": n_edited}



@router.post("/api/dub/{job_id}/edit_speaker_ref/{speaker_id}")
async def edit_speaker_ref(
    job_id: str, speaker_id: str,
    reference: UploadFile = File(...),
):
    """Replace the voice-cloning reference for one speaker.
    Used in wizard mode when diarization found a second speaker but only
    got 3-5 seconds of their audio (too short for clean cloning) — the
    user can upload a longer, cleaner clip of them from elsewhere."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    if not reference or not reference.filename:
        return JSONResponse({"error": "No file uploaded"}, 400)

    # Pick the earliest checkpoint that already has speaker_refs set; edit it
    # + later checkpoints so the new ref is picked up on /continue or regen.
    work = OUTPUT_DIR / job_id
    ref_dir = work / "speaker_refs"
    ref_dir.mkdir(exist_ok=True)
    ext = Path(reference.filename).suffix.lower() or ".wav"
    if ext not in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
        return JSONResponse({"error": f"Unsupported format: {ext}"}, 400)

    # Always store the user's upload as a fresh file so we don't clobber
    # the diarizer-extracted one (allows user to revert later if needed).
    user_ref = str(ref_dir / f"user_{speaker_id}{ext}")
    with open(user_ref, "wb") as f:
        shutil.copyfileobj(reference.file, f)

    n_updated = 0
    for stage in ("transcription_done", "translation_done", "tts_done"):
        cp = _load_checkpoint(job_id, stage)
        if cp and "speaker_refs" in cp:
            cp["speaker_refs"][speaker_id] = user_ref
            _save_checkpoint(job_id, work, stage=stage, data=cp)
            n_updated += 1

    if n_updated == 0:
        return JSONResponse(
            {"error": "No checkpoint has speaker_refs yet"}, 400
        )
    log.info(f"[edit_spk] Replaced ref for {speaker_id} on job {job_id} "
             f"({n_updated} checkpoints updated)")
    return {"ok": True, "speaker_id": speaker_id,
            "new_ref_path": user_ref, "checkpoints_updated": n_updated}



@router.post("/api/dub/{job_id}/edit_transcript")
async def edit_transcript(job_id: str, edits: str = Form(...)):
    """Update the source `text` for one or more segments in the transcription
    checkpoint. Used in wizard review_transcript mode when the user spots
    ASR errors before they get baked into the translation.
    `edits` is a JSON string: {"<idx>": "corrected text", ...}"""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    cp = _load_checkpoint(job_id, "transcription_done")
    if not cp:
        return JSONResponse({"error": "No transcription checkpoint to edit"}, 404)
    try:
        edit_map = json.loads(edits)
        if not isinstance(edit_map, dict):
            raise ValueError("edits must be a JSON object")
    except Exception as e:
        return JSONResponse({"error": f"Invalid edits JSON: {e}"}, 400)

    n_edited = 0
    for s in cp.get("segments", []):
        key = str(s.get("idx"))
        if key in edit_map:
            new_text = str(edit_map[key]).strip()
            if new_text and new_text != s.get("text"):
                s["text"] = new_text
                n_edited += 1
    work = OUTPUT_DIR / job_id
    _save_checkpoint(job_id, work, stage="transcription_done", data=cp)
    log.info(f"[edit] Applied {n_edited} transcript edits for job {job_id}")
    return {"ok": True, "edited": n_edited}



@router.post("/api/dub/{job_id}/continue")
async def continue_pipeline(
    job_id: str,
    voice_style: str = Form(""),
    voice_preset: str = Form(""),
    tts_speed: str = Form(""),
    reference: Optional[UploadFile] = File(None),
):
    """Continue the pipeline from the most recent checkpoint. Called after
    the user has reviewed (and possibly edited) the transcript/translation
    in wizard mode.

    - If stopped at translation_done: runs TTS + merge.
    - If stopped at transcription_done: runs translate + TTS + merge.

    Voice settings, if provided, override what was originally requested."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    job = jobs[job_id]

    ref_path = ""
    if reference and reference.filename:
        ref_ext = Path(reference.filename).suffix or ".wav"
        ref_path = str(UPLOAD_DIR / f"{job_id}_continue_ref{ref_ext}")
        with open(ref_path, "wb") as f:
            shutil.copyfileobj(reference.file, f)

    # Merge new voice settings with job defaults
    final_style = voice_style if voice_style else job.get("voice_style", "")
    final_preset = voice_preset if voice_preset else job.get("voice_preset", "auto")
    final_speed = tts_speed if tts_speed else job.get("tts_speed", "balanced")

    cp = _latest_checkpoint(job_id)
    if not cp:
        return JSONResponse({"error": "No checkpoint to continue from"}, 404)

    # Reset error/stale flags so the History UI immediately reflects that
    # the job is alive again. _continue_from_checkpoint will set status
    # to "translating"/"synthesizing" as it starts each stage.
    job["status"] = "resuming"
    job.pop("error", None)
    job.pop("stale_from_restart", None)
    save_job(job)

    asyncio.create_task(_continue_from_checkpoint(
        job_id, cp, final_style, final_preset, final_speed, ref_path,
    ))
    return {"ok": True, "job_id": job_id, "resuming_from": cp.get("stage")}



@router.post("/api/dub/{job_id}/retranslate")
async def retranslate(
    job_id: str,
    model: str = Form(""),
    context_hint: str = Form(""),
    target_lang: str = Form(""),
):
    """Re-run ONLY the translation step using the saved transcription
    checkpoint. Useful when the user wants to try a different model,
    adjust the context hint, or switch target language mid-flight."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    cp = _load_checkpoint(job_id, "transcription_done")
    if not cp:
        return JSONResponse(
            {"error": "No transcription checkpoint — start with wizard_mode"}, 404
        )

    final_model = model or cp.get("model", "gemma4:e4b")
    final_context = context_hint if context_hint else cp.get("context_hint", "")
    final_target = target_lang or cp.get("target_lang", "ru")

    asyncio.create_task(_retranslate_stage(
        job_id, cp, final_model, final_context, final_target,
    ))
    return {"ok": True, "job_id": job_id}



@router.get("/api/dub/{job_id}/timeline")
async def get_dub_timeline(job_id: str):
    """Return existing rendered segments as movable timeline clips."""
    cp = _load_checkpoint(job_id, "tts_done")
    if not cp:
        return JSONResponse({"error": "Timeline requires a completed TTS pass"}, 404)
    import soundfile as sf
    placement_map = {row.get("idx"): row for row in _load_placements(OUTPUT_DIR / job_id)}
    rows = []
    for i, seg in enumerate(cp.get("segments", [])):
        audio_path = seg.get("audio_path", "")
        if not audio_path or not os.path.exists(audio_path):
            continue
        try:
            info = sf.info(audio_path)
            clip_duration = info.frames / info.samplerate
        except Exception:
            continue
        placement = placement_map.get(seg.get("idx", i), {})
        rows.append({
            "idx": seg.get("idx", i),
            "text": seg.get("translated_text", ""),
            "original_text": seg.get("text", ""),
            "speaker": seg.get("speaker", "SPEAKER_00"),
            "start": float(seg.get("timeline_start", placement.get("dub_start", seg.get("start", 0.0)))),
            "source_start": float(seg.get("start", 0.0)),
            "source_end": float(seg.get("end", 0.0)),
            "duration": round(clip_duration, 4),
        })
    dubbed_wav = OUTPUT_DIR / job_id / "dubbed_audio.wav"
    peaks = _waveform_peaks(dubbed_wav) if dubbed_wav.exists() else []
    return {
        "duration": float(cp.get("duration", 0.0)), "segments": rows,
        "cuts": cp.get("timeline_cuts", []),
        "peaks": peaks,
        "source_video_url": f"/outputs/{job_id}/source_video.mp4",
        "dubbed_video_url": f"/outputs/{job_id}/dubbed_video.mp4",
        "source_audio_url": f"/outputs/{job_id}/audio_16k.wav",
        "dubbed_audio_url": f"/outputs/{job_id}/dubbed_audio.wav",
    }



@router.post("/api/dub/{job_id}/timeline")
async def apply_dub_timeline(job_id: str, placements: str = Form(...), cuts: str = Form("[]")):
    """Persist manually dragged clip starts and rebuild without re-synthesis."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    cp = _load_checkpoint(job_id, "tts_done")
    if not cp:
        return JSONResponse({"error": "Timeline requires a completed TTS pass"}, 404)
    try:
        incoming = json.loads(placements)
        if not isinstance(incoming, list):
            raise ValueError("placements must be an array")
        starts = {int(row["idx"]): max(0.0, min(float(row["start"]), float(cp["duration"])))
                  for row in incoming}
        cut_points = sorted({round(max(0.0, min(float(value), float(cp["duration"]))), 3)
                             for value in json.loads(cuts)})
    except Exception as exc:
        return JSONResponse({"error": f"Invalid placements: {exc}"}, 400)
    work = OUTPUT_DIR / job_id
    for i, seg in enumerate(cp.get("segments", [])):
        idx = int(seg.get("idx", i))
        if idx in starts:
            seg["timeline_start"] = starts[idx]
    cp["timeline_cuts"] = cut_points
    is_qwen = any(str(seg.get("tts_tier", "")).startswith("qwen3") for seg in cp["segments"])
    try:
        dubbed_wav = str(work / "dubbed_audio.wav")
        assemble_dubbed_audio(
            cp["segments"], cp["duration"], dubbed_wav, cp.get("sample_rate", 48000),
            apply_loudnorm=True, fit_to_slots=is_qwen,
            tail_audio_path=cp.get("audio_16k", "") if is_qwen else "",
        )
        _save_placements(work, cp["segments"])
        merge_audio_video(cp["video_path"], dubbed_wav, str(work / "dubbed_video.mp4"),
                          cp.get("bg_audio_path", "") if cp.get("keep_bg") else "")
        _save_checkpoint(job_id, work, stage="tts_done", data=cp)
        job = jobs[job_id]
        job.update(status="complete", progress=100, output_url=f"/outputs/{job_id}/dubbed_video.mp4",
                   completed_at=time.time(), step_detail="Timeline timing applied")
        save_job(job)
        return {"ok": True, "url": f"/outputs/{job_id}/dubbed_video.mp4?t={int(time.time())}"}
    except Exception as exc:
        log.error(f"[timeline] {job_id} rebuild failed: {exc}", exc_info=True)
        return JSONResponse({"error": str(exc)}, 500)



@router.post("/api/dub/{job_id}/regenerate_segment/{seg_idx}")
async def regenerate_segment(
    job_id: str, seg_idx: int,
    # Accept both 'translated_text' (UI form field name) and 'new_text'
    # (legacy) — whichever is populated wins.
    translated_text: str = Form(""),
    new_text: str = Form(""),
    voice_style: str = Form(""),
    voice_preset: str = Form(""),
    reference: Optional[UploadFile] = File(None),
):
    """Regenerate a SINGLE TTS segment. Optionally lets user edit the
    translated text and/or use a different voice for just this one line.
    After the new audio is rendered, the final video is rebuilt so the
    player immediately reflects the change."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    job = jobs[job_id]
    cp = _load_checkpoint(job_id, "tts_done")
    if not cp:
        return JSONResponse(
            {"error": "Per-segment regen requires tts_done checkpoint"}, 404
        )

    # Find the target segment
    segs = cp.get("segments", [])
    target = next((s for s in segs if s.get("idx") == seg_idx), None)
    if not target:
        return JSONResponse({"error": f"Segment {seg_idx} not found"}, 404)

    # Apply edits if any. Persist them to BOTH checkpoints immediately so
    # that even if the regen crashes, the user's edit isn't lost. Also
    # updates translation_done so a later full re-translate would only wipe
    # edits when the user explicitly requests it.
    edited = (translated_text or new_text).strip()
    if edited and edited != (target.get("translated_text") or "").strip():
        target["translated_text"] = edited
        # Also update the translation_done checkpoint so retranslate baseline
        # reflects the user's latest edit
        tcp = _load_checkpoint(job_id, "translation_done")
        if tcp:
            for ts in tcp.get("segments", []):
                if ts.get("idx") == seg_idx:
                    ts["translated_text"] = edited
                    break
            _save_checkpoint(job_id, OUTPUT_DIR / job_id,
                             stage="translation_done", data=tcp)
        log.info(f"[regen_seg] Edited segment {seg_idx} text: "
                 f"'{edited[:50]}{'...' if len(edited) > 50 else ''}'")

    ref_path = ""
    if reference and reference.filename:
        ref_ext = Path(reference.filename).suffix or ".wav"
        ref_path = str(UPLOAD_DIR / f"{job_id}_seg{seg_idx}_ref{ref_ext}")
        with open(ref_path, "wb") as f:
            shutil.copyfileobj(reference.file, f)

    # Delete the old audio_path so _run_tts_and_merge_stage treats it as "to do"
    old_audio = target.get("audio_path", "")
    if old_audio and os.path.exists(old_audio):
        try:
            os.remove(old_audio)
        except Exception:
            pass
    target["audio_path"] = ""

    # Persist the updated tts_done checkpoint to disk BEFORE dispatching the
    # async regen task. The stage reloads checkpoints per-run, and the
    # background task runs against THIS modified cp dict in-memory anyway,
    # but saving now guards against server crash between dispatch and save.
    _save_checkpoint(job_id, OUTPUT_DIR / job_id, stage="tts_done", data=cp)

    final_style = voice_style if voice_style else job.get("voice_style", "")
    final_preset = voice_preset if voice_preset else job.get("voice_preset", "auto")
    final_speed = job.get("tts_speed", "balanced")

    asyncio.create_task(_regen_single_segment(
        job_id, cp, seg_idx, final_style, final_preset, final_speed, ref_path,
    ))
    return {"ok": True, "job_id": job_id, "seg_idx": seg_idx}

