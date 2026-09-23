"""Media routes: audio waveform rendering and subtitle preview / burn-in."""
import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from app.config import OUTPUT_DIR, UPLOAD_DIR
from app.state import jobs
from pipeline.media import write_srt_file
from pipeline.subtitles import SUB_STYLE_MAP, build_subtitles_filter, pick_preview_timestamp

log = logging.getLogger("tachidubb.routes.media")

router = APIRouter()


@router.post("/api/waveform")
async def generate_waveform(
    audio: UploadFile = File(...),
    width: int = Form(800),
    height: int = Form(120),
):
    """Returns a PNG of the audio waveform. Accepts any FFmpeg-readable
    audio file. Width/height in pixels; defaults suit a typical UI panel."""
    tmp_id = uuid.uuid4().hex[:8]
    ext = Path(audio.filename or "in.wav").suffix or ".wav"
    src = UPLOAD_DIR / f"wf_{tmp_id}{ext}"
    dst = UPLOAD_DIR / f"wf_{tmp_id}.png"
    try:
        with open(src, "wb") as f:
            shutil.copyfileobj(audio.file, f)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-filter_complex",
             f"aformat=channel_layouts=mono,"
             f"compand=0|0:1|1:-90/-60|-60/-40|-40/-30|-20/-20:6:0:-90:0.2,"
             f"showwavespic=s={width}x{height}:colors=0xfb923c:split_channels=0",
             "-frames:v", "1", str(dst)],
            check=True, capture_output=True, timeout=30,
        )
        with open(dst, "rb") as f:
            png_data = f.read()
        return Response(content=png_data, media_type="image/png")
    except subprocess.CalledProcessError as e:
        log.warning(f"[waveform] ffmpeg failed: {e.stderr[:200]}")
        return JSONResponse({"error": "Could not generate waveform"}, 500)
    finally:
        for p in (src, dst):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass


@router.post("/api/dub/{job_id}/subs_preview")
async def preview_subtitle_style(
    job_id: str,
    style: str = Form("default"),
    timestamp: float = Form(-1.0),  # seconds into video; -1 = auto-pick
):
    """Render a single frame from the dubbed video with subs overlaid in
    the given style — lets the user preview styling instantly instead of
    waiting for a full re-encode of the whole video.

    Timestamp selection:
      - User can specify a timestamp (UI may tie this to a scrub bar)
      - If -1, we auto-pick the middle of a segment that has subtitle
        text so the preview actually shows text (not a silent frame)
    """
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    if style not in SUB_STYLE_MAP:
        return JSONResponse(
            {"error": f"Unknown style '{style}'. Options: {list(SUB_STYLE_MAP)}"}, 400)

    work = OUTPUT_DIR / job_id
    src_video = work / "dubbed_video.mp4"
    srt_file = work / "translated.srt"

    if not src_video.exists():
        return JSONResponse({"error": "Dubbed video not yet generated"}, 400)

    if not srt_file.exists():
        cp_path = work / "checkpoint_tts_done.json"
        if not cp_path.exists():
            cp_path = work / "checkpoint_translation_done.json"
        if cp_path.exists():
            try:
                cp = json.loads(cp_path.read_text(encoding="utf-8"))
                write_srt_file(cp.get("segments", []), srt_file)
            except Exception as e:
                return JSONResponse({"error": f"Could not generate SRT: {e}"}, 500)
        else:
            return JSONResponse({"error": "No transcript data found"}, 400)

    # Auto-pick: find a segment with text that lasts at least 1s
    if timestamp < 0:
        segments = []
        try:
            cp_path = work / "checkpoint_tts_done.json"
            if not cp_path.exists():
                cp_path = work / "checkpoint_translation_done.json"
            if cp_path.exists():
                cp = json.loads(cp_path.read_text(encoding="utf-8"))
                segments = cp.get("segments", [])
        except Exception:
            pass
        timestamp = pick_preview_timestamp(segments)

    subs_filter = build_subtitles_filter(srt_file, style)

    # Render one frame at <timestamp> with subs overlaid. Use -ss BEFORE
    # -i for fast seek (less accurate but saves ~10x on long videos),
    # and -frames:v 1 to output just one PNG.
    out_png = work / f"subs_preview_{style}.png"
    try:
        subprocess.run(
            ["ffmpeg", "-y",
             "-ss", f"{timestamp:.2f}",
             "-i", str(src_video),
             "-vf", subs_filter,
             "-frames:v", "1",
             "-q:v", "3",  # good quality JPEG-equivalent
             str(out_png)],
            check=True, capture_output=True, timeout=30,
        )
        # Return a JSON URL so the browser can cache-bust the image.
        # The PNG is already accessible via the /outputs static mount.
        return JSONResponse({
            "url": f"/outputs/{job_id}/subs_preview_{style}.png?t={int(time.time())}"
        })
    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or b"").decode("utf-8", errors="replace")[-500:]
        log.warning(f"[subs_preview] ffmpeg failed: {err_msg}")
        return JSONResponse({"error": "Preview render failed",
                             "detail": err_msg[:300]}, 500)


@router.post("/api/dub/{job_id}/burn_subs")
async def burn_subtitles(
    job_id: str,
    style: str = Form("default"),  # "default" | "large" | "minimal" | "yellow" | "boxed"
):
    """Generate a version of the dubbed video with burned-in subtitles
    from the translated SRT. Produces dubbed_video_subs.mp4 in the job dir."""
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, 404)
    work = OUTPUT_DIR / job_id
    src_video = work / "dubbed_video.mp4"
    srt_file = work / "translated.srt"
    dst_video = work / "dubbed_video_subs.mp4"

    if not src_video.exists():
        return JSONResponse({"error": "Dubbed video not yet generated"}, 400)

    # Ensure SRT exists (it's written alongside translation checkpoint,
    # but regenerate if missing using current segments)
    if not srt_file.exists():
        cp_path = work / "checkpoint_tts_done.json"
        if not cp_path.exists():
            cp_path = work / "checkpoint_translation_done.json"
        if cp_path.exists():
            try:
                cp = json.loads(cp_path.read_text(encoding="utf-8"))
                segments = cp.get("segments", [])
                write_srt_file(segments, srt_file)
            except Exception as e:
                return JSONResponse({"error": f"Could not generate SRT: {e}"}, 500)
        else:
            return JSONResponse({"error": "No transcript data found"}, 400)

    # Use the shared style map (preview + burn-in stay in sync)
    subs_filter = build_subtitles_filter(srt_file, style)

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src_video),
             "-vf", subs_filter,
             "-c:a", "copy",  # don't re-encode audio
             "-preset", "fast",
             str(dst_video)],
            check=True, capture_output=True, timeout=600,
        )
        return {
            "ok": True,
            "url": f"/outputs/{job_id}/dubbed_video_subs.mp4?v={int(time.time())}",
        }
    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or b"").decode("utf-8", errors="replace")[-500:]
        log.warning(f"[burn_subs] ffmpeg failed for {job_id}: {err_msg}")
        return JSONResponse({
            "error": "Subtitle burn-in failed",
            "detail": err_msg[:300],
        }, 500)