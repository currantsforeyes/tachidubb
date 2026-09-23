"""Showcase routes: build/status/rebuild, redub, and platform export."""
import asyncio
import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.config import OUTPUT_DIR, UPLOAD_DIR
from app.languages import (
    QUICK_TEST_KNOWN_LANGS as _QUICK_TEST_KNOWN_LANGS,
)
from app.queue import enqueue_job
from app.showcase import (
    maybe_assemble_showcase,
    _showcase_assembling,
    _showcase_tasks,
)
from app.state import jobs, save_job
from pipeline.media import (
    trim_video as _trim_video,
    write_srt_file as _write_srt_file,
)
from pipeline.subtitles import build_subtitles_filter
from pipeline.translator import check_ollama

log = logging.getLogger("tachidubb.routes.showcase")

router = APIRouter()


@router.post("/api/showcase")
async def start_showcase(
    video: Optional[UploadFile] = File(None),
    source: str = Form(""),
    reference: Optional[UploadFile] = File(None),
    trim_seconds: int = Form(60),
    target_langs: str = Form(""),
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
    """Showcase: trim a short clip, fan out into N normal dub jobs, and
    when all finish, automatically stitch them into one multilingual reel
    (each segment in a different language with a corner badge)."""
    # ── Input validation — identical to /api/quick_test ───────────────
    if not video and not source.strip():
        return JSONResponse({"error": "Provide either a video file or a URL"}, 400)
    if video and source.strip():
        return JSONResponse({"error": "Provide only one of video or url"}, 400)
    if trim_seconds < 15 or trim_seconds > 120:
        return JSONResponse(
            {"error": f"trim_seconds must be between 15 and 120 (got {trim_seconds})"}, 400)

    langs = [c.strip() for c in target_langs.split(",") if c.strip()]
    if not (2 <= len(langs) <= 6):
        return JSONResponse({"error": f"Pick 2-6 target languages (got {len(langs)})"}, 400)
    unknown = [c for c in langs if c not in _QUICK_TEST_KNOWN_LANGS]
    if unknown:
        return JSONResponse({"error": f"Unknown language code(s): {unknown}"}, 400)
    if len(set(langs)) != len(langs):
        return JSONResponse({"error": "Duplicate language codes"}, 400)

    # Validate ollama model with fallback
    _ok, _installed = await check_ollama()
    if _ok and model not in _installed:
        _preferred = ["aya-expanse:8b", "mistral-nemo:12b", "qwen2.5:14b",
                      "qwen2.5:7b", "qwen2.5:3b", "gemma3:12b", "gemma3:4b",
                      "llama3.2:3b", "gemma4:e4b", "gemma4:e2b"]
        _fallback = next((m for m in _preferred if m in _installed), None)
        if _fallback:
            log.warning(f"[showcase] '{model}' not installed; using '{_fallback}'")
            model = _fallback
        else:
            return JSONResponse({
                "error": "No translation model installed. Run: ollama pull aya-expanse:8b"
            }, 400)

    # Shared reference (one upload, reused by all jobs)
    ref_path = ""
    if reference and reference.filename:
        ref_ext = Path(reference.filename).suffix or ".wav"
        ref_path = str(UPLOAD_DIR / f"sc_{uuid.uuid4().hex[:8]}_ref{ref_ext}")
        with open(ref_path, "wb") as f:
            shutil.copyfileobj(reference.file, f)
        log.info(f"[showcase] Saved shared reference: {ref_path}")

    # Materialize source (file or yt-dlp URL)
    src_path: Path
    src_label: str
    if video and video.filename:
        ext = Path(video.filename).suffix or ".mp4"
        src_path = UPLOAD_DIR / f"sc_{uuid.uuid4().hex[:8]}{ext}"
        with open(src_path, "wb") as f:
            shutil.copyfileobj(video.file, f)
        src_label = video.filename
    else:
        from pipeline.downloader import download_video
        url = source.strip()
        src_label = url[:60] + ("..." if len(url) > 60 else "")
        try:
            dl_dir = UPLOAD_DIR / f"sc_{uuid.uuid4().hex[:8]}"
            dl_dir.mkdir(parents=True, exist_ok=True)
            src_path = Path(download_video(url, str(dl_dir)))
        except Exception as e:
            return JSONResponse({"error": f"Could not download URL: {e}"}, 400)

    # Trim
    trimmed_path = src_path.parent / f"{src_path.stem}_sc{trim_seconds}s.mp4"
    try:
        _trim_video(src_path, trimmed_path, trim_seconds)
    except Exception as e:
        err_msg = ""
        if hasattr(e, "stderr") and getattr(e, "stderr", None):
            err_msg = e.stderr.decode("utf-8", errors="replace")[-300:]
        log.warning(f"[showcase] trim failed: {e} :: {err_msg}")
        return JSONResponse(
            {"error": "Could not trim video", "detail": err_msg or str(e)}, 500)

    # Fan out — one job per language, all sharing the batch_id
    batch_id = f"sc_{uuid.uuid4().hex[:8]}"
    label_final = batch_label or f"Showcase · {trim_seconds}s · {len(langs)} langs"
    job_ids: list = []

    for idx, lang in enumerate(langs):
        jid = uuid.uuid4().hex[:8]
        jobs[jid] = {
            "id": jid,
            "status": "queued",
            "progress": 0,
            "source": str(trimmed_path),
            "source_type": "file",
            "source_label": f"{src_label} -> {lang.upper()} [showcase]",
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
            "wizard_mode": "auto",
            "auto_denoise": auto_denoise,
            "narration_mode": bool(narration_mode),
            "batch_id": batch_id,
            "batch_label": label_final,
            "batch_kind": "showcase",
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

    log.info(f"[showcase] {batch_id}: enqueued {len(job_ids)} jobs "
             f"({trim_seconds}s, langs={langs})")

    return {
        "ok": True,
        "batch_id": batch_id,
        "batch_kind": "showcase",
        "job_ids": job_ids,
        "count": len(job_ids),
        "trimmed_file": f"/uploads/{trimmed_path.name}",
        "trim_seconds": trim_seconds,
        "target_langs": langs,
    }



@router.get("/api/showcase/{batch_id}")
async def get_showcase(batch_id: str):
    """Status + URL for an assembled showcase. Returns 404 if no showcase
    exists for this batch (either never started or still in progress)."""
    showcase_dir = OUTPUT_DIR / f"showcase_{batch_id}"
    mp4 = showcase_dir / "showcase.mp4"
    manifest = showcase_dir / "manifest.json"
    err_file = showcase_dir / "error.txt"

    # Sibling jobs (for progress reporting)
    siblings = [j for j in jobs.values()
                if j.get("batch_id") == batch_id
                and j.get("batch_kind") == "showcase"]

    if mp4.exists():
        man = {}
        if manifest.exists():
            try:
                man = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "ok": True,
            "status": "ready",
            "url": f"/outputs/showcase_{batch_id}/showcase.mp4",
            "manifest": man,
            "sibling_count": len(siblings),
        }

    if err_file.exists():
        try:
            err = err_file.read_text(encoding="utf-8")[-800:]
        except Exception:
            err = "Assembly failed (see server logs)"
        return JSONResponse(
            {"status": "error", "error": err}, 500)

    # Still in progress — count how many sibling jobs are done
    done = sum(1 for j in siblings if j.get("status") == "complete")
    errored = sum(1 for j in siblings if j.get("status") == "error")
    if siblings:
        return {
            "ok": True,
            "status": "assembling" if (done == len(siblings) and batch_id in _showcase_assembling)
                       else ("waiting_for_jobs" if errored == 0 else "jobs_failed"),
            "completed_jobs": done,
            "errored_jobs": errored,
            "total_jobs": len(siblings),
        }

    return JSONResponse({"status": "not_found"}, 404)



@router.post("/api/job/{job_id}/redub")
async def redub_job(
    job_id: str,
    target_langs: str = Form(""),
    mode: str = Form("compare"),          # 'single' | 'compare' | 'showcase'
    model: Optional[str] = Form(None),
    whisper_model: Optional[str] = Form(None),
    voice_preset: Optional[str] = Form(None),
    voice_style: Optional[str] = Form(None),
    tts_speed: Optional[str] = Form(None),
    keep_bg: Optional[bool] = Form(None),
    speaker_mode: Optional[str] = Form(None),
    narration_mode: Optional[bool] = Form(None),
):
    """Re-dub an existing video into new language(s). Reuses the original
    source (file path or URL) — no re-upload required, just specify which
    new languages you want and the mode.

    Modes:
      single   — one new dub in one new language
      compare  — N new dubs (2-6), each in a different language (like Quick Test)
      showcase — N dubs, then stitched into one multilingual reel
    """
    orig = jobs.get(job_id)
    if not orig:
        return JSONResponse({"error": f"Job {job_id} not found"}, 404)

    # Validate mode + langs
    if mode not in ("single", "compare", "showcase"):
        return JSONResponse({"error": f"Invalid mode '{mode}'"}, 400)

    langs = [c.strip().lower() for c in target_langs.split(",") if c.strip()]
    if not langs:
        return JSONResponse({"error": "Specify at least one target_lang"}, 400)
    if mode == "single" and len(langs) != 1:
        return JSONResponse({"error": "mode=single requires exactly 1 language"}, 400)
    if mode in ("compare", "showcase") and not (2 <= len(langs) <= 6):
        return JSONResponse({"error": f"mode={mode} needs 2-6 langs (got {len(langs)})"}, 400)
    unknown = [c for c in langs if c not in _QUICK_TEST_KNOWN_LANGS]
    if unknown:
        return JSONResponse({"error": f"Unknown language codes: {unknown}"}, 400)
    if len(set(langs)) != len(langs):
        return JSONResponse({"error": "Duplicate language codes"}, 400)

    # ── Locate the source (file path or URL) ──────────────────────────
    # Preference order:
    #   1) Original source path if file still exists (uploads/...)
    #   2) source_video.mp4 in the original job's output dir (always copied)
    #   3) Original URL — yt-dlp will re-fetch (cached if possible)
    orig_source = orig.get("source", "")
    source_type = orig.get("source_type", "file")
    src_for_new_jobs: str

    if source_type == "file":
        if orig_source and Path(orig_source).exists():
            src_for_new_jobs = orig_source
        else:
            backup = OUTPUT_DIR / job_id / "source_video.mp4"
            if backup.exists():
                src_for_new_jobs = str(backup)
            else:
                return JSONResponse({
                    "error": "Original source file is gone — can't redub. "
                             "Re-upload it instead.",
                    "original_source": orig_source,
                }, 400)
    else:
        # URL source — pass through. download_video() should hit cache.
        if not orig_source:
            return JSONResponse({"error": "Original job has no source URL"}, 400)
        src_for_new_jobs = orig_source

    # ── Validate / fallback the Ollama model ──────────────────────────
    chosen_model = model or orig.get("model", "aya-expanse:8b")
    _ok, _installed = await check_ollama()
    if _ok and chosen_model not in _installed:
        _preferred = ["aya-expanse:8b", "mistral-nemo:12b", "qwen2.5:14b",
                      "qwen2.5:7b", "qwen2.5:3b", "gemma3:12b", "gemma3:4b",
                      "llama3.2:3b", "gemma4:e4b", "gemma4:e2b"]
        _fallback = next((m for m in _preferred if m in _installed), None)
        if _fallback:
            log.warning(f"[redub] '{chosen_model}' not installed; using '{_fallback}'")
            chosen_model = _fallback
        else:
            return JSONResponse({
                "error": "No translation model installed",
            }, 400)

    # ── Build settings (inherit from original, accept overrides) ──────
    settings = {
        "model": chosen_model,
        "whisper_model": whisper_model or orig.get("whisper_model", "large-v3"),
        "voice_preset": voice_preset or orig.get("voice_preset", "auto"),
        "voice_style": voice_style if voice_style is not None else orig.get("voice_style", ""),
        "tts_speed": tts_speed or orig.get("tts_speed", "balanced"),
        "keep_bg": keep_bg if keep_bg is not None else bool(orig.get("keep_bg", False)),
        "speaker_mode": speaker_mode or orig.get("speaker_mode", "main"),
        "auto_denoise": bool(orig.get("auto_denoise", False)),
        "narration_mode": (bool(narration_mode) if narration_mode is not None
                           else bool(orig.get("narration_mode", False))),
        "context_hint": orig.get("context_hint", ""),
        "source_lang": orig.get("source_lang", "auto"),
    }
    label_base = orig.get("source_label", "") or Path(orig_source).name or job_id

    def _build_job_dict(jid: str, lang: str, extra: dict | None = None) -> dict:
        d = {
            "id": jid,
            "status": "queued",
            "progress": 0,
            "source": src_for_new_jobs,
            "source_type": source_type,
            "source_label": f"{label_base} -> {lang.upper()} [redub]",
            "target_lang": lang,
            "model": settings["model"],
            "speaker_mode": settings["speaker_mode"],
            "context_hint": settings["context_hint"],
            "voice_style": settings["voice_style"],
            "voice_preset": settings["voice_preset"],
            "voice_mode": orig.get("voice_mode", "preset"),
            "tts_speed": settings["tts_speed"],
            "whisper_model": settings["whisper_model"],
            "keep_bg": settings["keep_bg"],
            "wizard_mode": "auto",
            "auto_denoise": settings["auto_denoise"],
            "narration_mode": settings["narration_mode"],
            "redubbed_from": job_id,
            "created": time.time(),
            "scheduled_at": 0,
            "_pending_args": None,
        }
        if extra:
            d.update(extra)
        return d

    def _pipeline_args(lang: str) -> dict:
        return {
            "source": src_for_new_jobs,
            "source_lang": settings["source_lang"],
            "target_lang": lang,
            "model": settings["model"],
            "keep_bg": settings["keep_bg"],
            "whisper_model": settings["whisper_model"],
            "reference_audio": "",
            "speaker_mode": settings["speaker_mode"],
            "context_hint": settings["context_hint"],
            "voice_style": settings["voice_style"],
            "voice_preset": settings["voice_preset"],
            "tts_speed": settings["tts_speed"],
            "wizard_mode": "auto",
            "auto_denoise": settings["auto_denoise"],
            "narration_mode": settings["narration_mode"],
        }

    # ── Single mode: one job, no batch wrapper ────────────────────────
    if mode == "single":
        jid = uuid.uuid4().hex[:8]
        lang = langs[0]
        jobs[jid] = _build_job_dict(jid, lang)
        save_job(jobs[jid])
        await enqueue_job(jid, _pipeline_args(lang))
        log.info(f"[redub] queued single job {jid} ({lang}) from {job_id}")
        return {"ok": True, "job_id": jid, "redubbed_from": job_id, "target_lang": lang}

    # ── Compare / Showcase: batched fan-out ───────────────────────────
    batch_kind = "showcase" if mode == "showcase" else "quick_test"
    prefix = "sc" if mode == "showcase" else "rd"
    batch_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
    batch_label = f"Re-dub · {len(langs)} langs · from {job_id[:6]}"
    job_ids: list = []

    for idx, lang in enumerate(langs):
        jid = uuid.uuid4().hex[:8]
        jobs[jid] = _build_job_dict(jid, lang, extra={
            "batch_id": batch_id,
            "batch_label": batch_label,
            "batch_kind": batch_kind,
            "batch_position": idx,
            "batch_total": len(langs),
        })
        save_job(jobs[jid])
        await enqueue_job(jid, _pipeline_args(lang))
        job_ids.append(jid)

    log.info(f"[redub] {batch_id} ({batch_kind}): enqueued {len(job_ids)} jobs "
             f"from {job_id} ({langs})")
    return {
        "ok": True,
        "batch_id": batch_id,
        "batch_kind": batch_kind,
        "job_ids": job_ids,
        "redubbed_from": job_id,
        "target_langs": langs,
        "mode": mode,
    }



@router.post("/api/showcase/{batch_id}/rebuild")
async def rebuild_showcase(batch_id: str):
    """Manually re-trigger showcase assembly. Useful when the auto-hook
    failed (e.g. ffprobe issue) and the user doesn't want to re-run all
    N dubs from scratch. Deletes any prior showcase.mp4 / error.txt
    first so maybe_assemble_showcase() will actually rebuild."""
    siblings = [j for j in jobs.values()
                if j.get("batch_id") == batch_id
                and j.get("batch_kind") == "showcase"]
    if not siblings:
        return JSONResponse(
            {"error": f"No showcase batch with id {batch_id}"}, 404)

    incomplete = [j["id"] for j in siblings if j.get("status") != "complete"]
    if incomplete:
        return JSONResponse({
            "error": f"{len(incomplete)} of {len(siblings)} child jobs aren't "
                     f"complete yet — can't assemble",
            "incomplete_job_ids": incomplete,
        }, 400)

    showcase_dir = OUTPUT_DIR / f"showcase_{batch_id}"
    for marker in ("showcase.mp4", "error.txt"):
        p = showcase_dir / marker
        if p.exists():
            try:
                p.unlink()
            except Exception as e:
                log.warning(f"[showcase] couldn't remove {p}: {e}")
    _showcase_assembling.discard(batch_id)

    # Fire-and-forget — keep a strong reference in _showcase_tasks so the
    # event loop's weak-ref GC doesn't kill the task mid-execution.
    task = asyncio.create_task(maybe_assemble_showcase(batch_id))
    _showcase_tasks.add(task)
    task.add_done_callback(_showcase_tasks.discard)
    log.info(f"[showcase] {batch_id}: rebuild scheduled (task={task!r})")
    return {"ok": True, "status": "rebuilding", "batch_id": batch_id}



@router.post("/api/showcase/from_batch/{batch_id}")
async def stitch_batch_as_showcase(batch_id: str):
    """Convert any complete batch (quick_test, compare, …) into a showcase
    reel — no re-dubbing needed. Re-marks child jobs as batch_kind='showcase'
    so the normal assembly path picks them up, then triggers assembly.
    Idempotent: safe to call again if you want to re-stitch."""
    all_in_batch = [j for j in jobs.values() if j.get("batch_id") == batch_id]
    if not all_in_batch:
        return JSONResponse({"error": f"Batch {batch_id!r} not found"}, status_code=404)

    incomplete = [j["id"] for j in all_in_batch if j.get("status") != "complete"]
    if incomplete:
        return JSONResponse({
            "error": f"{len(incomplete)} of {len(all_in_batch)} jobs aren't complete yet",
            "incomplete_job_ids": incomplete,
        }, status_code=400)

    # Upgrade batch_kind so maybe_assemble_showcase finds these siblings
    for j in all_in_batch:
        if j.get("batch_kind") != "showcase":
            j["batch_kind"] = "showcase"
            save_job(j)

    # Clear any stale showcase output so assembly runs fresh
    showcase_dir = OUTPUT_DIR / f"showcase_{batch_id}"
    for marker in ("showcase.mp4", "error.txt"):
        p = showcase_dir / marker
        if p.exists():
            try:
                p.unlink()
            except Exception as e:
                log.warning(f"[showcase] couldn't clear {p}: {e}")
    _showcase_assembling.discard(batch_id)

    task = asyncio.create_task(maybe_assemble_showcase(batch_id))
    _showcase_tasks.add(task)
    task.add_done_callback(_showcase_tasks.discard)
    log.info(f"[showcase] {batch_id}: stitch-from-batch triggered "
             f"({len(all_in_batch)} jobs)")
    return {"ok": True, "status": "assembling", "batch_id": batch_id,
            "jobs": len(all_in_batch)}


# ═══════════════════════════════════════════════════════════════════════
#  Export for Platform — re-encode dubbed video for specific platforms
# ═══════════════════════════════════════════════════════════════════════
# Each preset defines an ffmpeg -vf filter chain, optional fps override,
# and whether to auto-burn translated subtitles into the frame.
#
# Crop/pad strategy:
#   16:9 outputs → letterbox (black bars) to preserve all content
#   9:16 / 1:1   → scale-to-fill + centre-crop (standard for social)
# ═══════════════════════════════════════════════════════════════════════

_EXPORT_PRESETS: dict = {
    "youtube_1080p": {
        "vf": "scale=1920:1080:force_original_aspect_ratio=decrease,"
              "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
        "fps": None, "burn_subs": False,
    },
    "youtube_4k": {
        "vf": "scale=3840:2160:force_original_aspect_ratio=decrease,"
              "pad=3840:2160:(ow-iw)/2:(oh-ih)/2:black",
        "fps": None, "burn_subs": False,
    },
    "tiktok": {
        "vf": "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "fps": 30, "burn_subs": True,
    },
    "shorts": {
        "vf": "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "fps": 30, "burn_subs": True,
    },
    "reels": {
        "vf": "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "fps": 30, "burn_subs": True,
    },
    "instagram_square": {
        "vf": "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080",
        "fps": None, "burn_subs": False,
    },
    "twitter": {
        "vf": "scale=1280:720:force_original_aspect_ratio=decrease,"
              "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
        "fps": None, "burn_subs": False,
    },
}



@router.post("/api/dub/{job_id}/export")
async def export_for_platform(
    job_id: str,
    preset: str = Form("youtube_1080p"),
    style: str = Form("default"),  # subtitle style — used when preset auto-burns subs
):
    """Re-encode the dubbed video for a specific platform preset.

    Returns JSON: {"ok": True, "url": "..."}  on success,
                  {"error": "...", "detail": "..."}  on failure.
    """
    import subprocess
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    if preset not in _EXPORT_PRESETS:
        return JSONResponse(
            {"error": f"Unknown preset '{preset}'. Options: {list(_EXPORT_PRESETS)}"}, 400)

    work = OUTPUT_DIR / job_id
    src_video = work / "dubbed_video.mp4"
    if not src_video.exists():
        return JSONResponse({"error": "Dubbed video not yet generated"}, 400)

    pc = _EXPORT_PRESETS[preset]
    dst_video = work / f"export_{preset}.mp4"
    vf = pc["vf"]

    # For presets that burn subs, append the subtitle filter to the chain
    if pc["burn_subs"]:
        srt_file = work / "translated.srt"
        if not srt_file.exists():
            cp_path = work / "checkpoint_tts_done.json"
            if not cp_path.exists():
                cp_path = work / "checkpoint_translation_done.json"
            if cp_path.exists():
                try:
                    cp = json.loads(cp_path.read_text(encoding="utf-8"))
                    _write_srt_file(cp.get("segments", []), srt_file)
                except Exception as e:
                    return JSONResponse({"error": f"Could not generate SRT: {e}"}, 500)
        if srt_file.exists():
            vf = f"{vf},{build_subtitles_filter(srt_file, style)}"

    cmd = [
        "ffmpeg", "-y", "-i", str(src_video),
        "-vf", vf,
        "-c:a", "copy",   # audio pass-through — no re-encode
        "-preset", "fast",
    ]
    if pc["fps"]:
        cmd += ["-r", str(pc["fps"])]
    cmd.append(str(dst_video))

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
        return JSONResponse({
            "ok": True,
            "url": f"/outputs/{job_id}/export_{preset}.mp4?v={int(time.time())}",
            "preset": preset,
        })
    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or b"").decode("utf-8", errors="replace")[-500:]
        log.warning(f"[export] ffmpeg failed for {job_id}/{preset}: {err_msg}")
        return JSONResponse({
            "error": f"Export failed for preset '{preset}'",
            "detail": err_msg[:300],
        }, 500)


# ─────────────────────────────────────────────────────────────
# Stage helpers — reusable from run_pipeline AND from resume endpoints
# ─────────────────────────────────────────────────────────────

