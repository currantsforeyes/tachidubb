"""Job routes: list/get/cancel/delete/download, speaker refs, transcripts."""
import asyncio
import logging
import os
import re
import shutil
import subprocess

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.checkpoints import job_checkpoint_info, load_checkpoint
from app.config import OUTPUT_DIR
from app.db import delete_job_db
from app.queue import get_queue
from app.state import jobs, save_job
from app.tts import terminate_tts_worker

log = logging.getLogger("tachidubb.routes.jobs")

router = APIRouter()


# ── Per-speaker reference inspection (diagnostic for review screen) ───────
# After diarization the pipeline extracts ~30s of clean speech per detected
# speaker into speaker_refs/ref_SPEAKER_XX.wav. These are fed to TTS as
# voice-cloning references — bad refs = bad dubbed voice. These endpoints let
# the review UI inspect/audition them. PNGs are cached under speaker_refs/.


@router.get("/api/job/{job_id}/speakers")
async def list_job_speakers(job_id: str):
    """Return per-speaker reference metadata for a job: list of
    {speaker, ref_path, duration_sec, exists} so the UI can enumerate
    detected speakers and render a waveform panel per speaker."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    refs_dir = OUTPUT_DIR / job_id / "speaker_refs"
    if not refs_dir.exists():
        return {"speakers": [], "hint": "No speaker references extracted for this job"}

    out = []
    for p in sorted(refs_dir.glob("ref_*.wav")):
        name = p.stem  # "ref_SPEAKER_00" or "ref_fallback"
        speaker = name.replace("ref_", "", 1)
        duration = 0.0
        try:
            # Fast duration read via ffprobe
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                capture_output=True, text=True, timeout=10,
            )
            duration = float(r.stdout.strip() or 0.0)
        except Exception:
            pass
        out.append({
            "speaker": speaker,
            "duration_sec": round(duration, 1),
            "audio_url": f"/api/job/{job_id}/speaker_ref/{speaker}/audio",
            "waveform_url": f"/api/job/{job_id}/speaker_ref/{speaker}/waveform",
        })
    return {"speakers": out}


@router.get("/api/job/{job_id}/speaker_ref/{speaker}/audio")
async def get_speaker_ref_audio(job_id: str, speaker: str):
    """Stream the speaker's reference WAV for in-browser playback.
    Lets the user quickly audition the extracted reference."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    # Strict filename validation — prevent path traversal via speaker id
    if not re.match(r"^[A-Za-z0-9_]+$", speaker):
        return JSONResponse({"error": "Invalid speaker id"}, 400)
    p = OUTPUT_DIR / job_id / "speaker_refs" / f"ref_{speaker}.wav"
    if not p.exists():
        return JSONResponse({"error": "Reference not found"}, 404)
    return FileResponse(str(p), media_type="audio/wav",
                        filename=f"ref_{speaker}.wav")


@router.get("/api/job/{job_id}/speaker_ref/{speaker}/waveform")
async def get_speaker_ref_waveform(
    job_id: str, speaker: str,
    width: int = 700, height: int = 80,
):
    """Return a cached PNG waveform for this speaker. Caches to
    speaker_refs/wf_{speaker}_{w}x{h}.png so repeated opens don't
    re-run ffmpeg. Cache invalidates only when the ref WAV's mtime
    changes (e.g. user re-uploaded via edit_speaker_ref)."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    if not re.match(r"^[A-Za-z0-9_]+$", speaker):
        return JSONResponse({"error": "Invalid speaker id"}, 400)
    refs_dir = OUTPUT_DIR / job_id / "speaker_refs"
    src = refs_dir / f"ref_{speaker}.wav"
    if not src.exists():
        return JSONResponse({"error": "Reference not found"}, 404)

    cache = refs_dir / f"wf_{speaker}_{width}x{height}.png"
    # Cache hit only if cached file exists AND was modified after source.
    if cache.exists() and cache.stat().st_mtime >= src.stat().st_mtime:
        return FileResponse(str(cache), media_type="image/png")

    # Miss: render + cache
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-filter_complex",
             f"aformat=channel_layouts=mono,"
             f"compand=0|0:1|1:-90/-60|-60/-40|-40/-30|-20/-20:6:0:-90:0.2,"
             f"showwavespic=s={width}x{height}:colors=0xfb923c:split_channels=0",
             "-frames:v", "1", str(cache)],
            check=True, capture_output=True, timeout=30,
        )
    except subprocess.CalledProcessError as e:
        log.warning(f"[waveform] per-speaker render failed: {e.stderr[:200]}")
        return JSONResponse({"error": "Could not render waveform"}, 500)
    return FileResponse(str(cache), media_type="image/png")


@router.get("/api/dub/{job_id}/transcripts.txt")
async def download_transcripts_txt(job_id: str):
    """Export side-by-side transcript as plain text. Useful for content
    creators who want to copy/paste into captions, descriptions, etc.

    Format:
        === SEGMENT 1 (0.0s → 5.6s · SPEAKER_00) ===
        EN: Original source text
        RU: Translated text (with any user edits applied)
    """
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)

    # Prefer tts_done (has user edits from per-segment regens), fall back
    # to translation_done. If neither exists, return 404.
    cp = load_checkpoint(job_id, "tts_done") or load_checkpoint(job_id, "translation_done")
    if not cp:
        return JSONResponse({"error": "No completed transcript yet"}, 404)

    segs = cp.get("segments", [])
    if not segs:
        return JSONResponse({"error": "No segments"}, 404)

    target = cp.get("target_lang", "ru").upper()
    lines = [
        f"TachiDUBB Studio transcript export · job {job_id}",
        f"Target language: {target} · {len(segs)} segments",
        "=" * 60, "",
    ]
    for s in segs:
        idx = s.get("idx", 0) + 1
        start = s.get("start", 0.0)
        end = s.get("end", 0.0)
        spk = s.get("speaker", "SPEAKER_00")
        lines.append(f"=== #{idx} · {start:.1f}s → {end:.1f}s · {spk} ===")
        lines.append(f"EN: {s.get('text', '').strip()}")
        lines.append(f"{target}: {s.get('translated_text', '').strip()}")
        lines.append("")

    return PlainTextResponse(
        content="\n".join(lines),
        headers={
            "Content-Disposition": f'attachment; filename="transcripts_{job_id}.txt"'
        },
    )


@router.get("/api/job/{job_id}")
async def get_job(job_id: str):
    if job_id not in jobs:
        return JSONResponse({"error": "Not found"}, 404)
    return jobs[job_id]


@router.post("/api/dub/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a queued or running job.

    - Queued: removed from the asyncio queue immediately, status=cancelled.
    - Running: sets cancel_requested flag. The pipeline's update() closures
      check this flag at every stage boundary and raise JobCancelled, which
      the queue worker catches and marks as cancelled. For TTS synthesis we
      additionally terminate the persistent VoxCPM subprocess so cancel
      takes effect within 1-2 seconds instead of waiting for the current
      segment to finish rendering (can be 30+ seconds on a long segment).
    """
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    j = jobs[job_id]
    status = j.get("status")

    if status in ("complete", "error", "cancelled"):
        return {"ok": False, "reason": f"Job is already {status}"}

    if status == "scheduled":
        # Not yet in the queue — just flip status; scheduler loop will
        # see status != 'scheduled' and skip it on next poll.
        j["status"] = "cancelled"
        j["step_detail"] = "Cancelled before scheduled start"
        j.pop("_pending_args", None)
        save_job(j)
        log.info(f"[scheduler] Job {job_id} cancelled before scheduled start")
        return {"ok": True, "cancelled_from": "scheduled"}

    if status == "queued":
        # Drain queue, drop target job, push rest back. asyncio.Queue
        # doesn't support random removal directly.
        drained = []
        while not get_queue().empty():
            try:
                item = get_queue().get_nowait()
                if item[0] != job_id:
                    drained.append(item)
            except asyncio.QueueEmpty:
                break
        for item in drained:
            await get_queue().put(item)
        j["status"] = "cancelled"
        j["step_detail"] = "Cancelled before start"
        save_job(j)
        log.info(f"[queue] Job {job_id} cancelled (removed from queue)")
        return {"ok": True, "cancelled_from": "queue"}

    # Running job — set flag, terminate TTS subprocess if mid-synth.
    # The pipeline's update() closures will pick up the flag at the next
    # stage boundary and raise JobCancelled cleanly.
    j["cancel_requested"] = True
    j["step_detail"] = "Cancelling..."
    save_job(j)
    # Proactively kill TTS worker so synth segments don't have to finish
    if status == "synthesizing":
        terminate_tts_worker()
    log.info(f"[queue] Job {job_id} cancel requested (was {status})")
    return {"ok": True, "cancelled_from": "running",
            "message": "Cancel requested. Job will stop at the next stage boundary "
                       "(usually within 1-5 seconds)."}


@router.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    if job_id not in jobs:
        return JSONResponse({"error": "Not found"}, 404)
    work = OUTPUT_DIR / job_id
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    delete_job_db(job_id)
    jobs.pop(job_id, None)
    return {"ok": True}


@router.get("/api/jobs")
async def list_jobs():
    # Annotate each job with checkpoint info so the History UI can
    # decide whether to show a Resume button. This is intentionally
    # done at read time (not stored on the job object) because users
    # can delete output dirs manually — reading live keeps UI honest.
    sorted_jobs = sorted(jobs.values(), key=lambda j: j.get("created", 0), reverse=True)
    enriched = []
    for j in sorted_jobs:
        info = job_checkpoint_info(j["id"])
        # Shallow-copy so we don't mutate the in-memory job store
        enriched.append({**j, **info})
    return {"jobs": enriched}


@router.get("/api/download/{job_id}")
async def download(job_id: str):
    if job_id not in jobs or jobs[job_id].get("status") != "complete":
        return JSONResponse({"error": "Not ready"}, 400)
    path = str(OUTPUT_DIR / job_id / "dubbed_video.mp4")
    if not os.path.exists(path):
        return JSONResponse({"error": "File missing"}, 404)
    return FileResponse(path, filename=f"dubbed_{job_id}.mp4")