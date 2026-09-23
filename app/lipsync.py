"""MuseTalk lip-sync orchestration (synchronous, job-dir based).

Extracted from ``server.py`` so both the manual route and the queue's
auto-lip-sync hook can call it without importing the application module.

Runs the isolated ``musetalk-runtime`` worker via ``pipeline.lipsync``'s
command builders, then re-muxes the full-quality dubbed audio back on.
"""
import json
import logging
import subprocess as _sp
import time

from app.config import BASE, OUTPUT_DIR
from app.state import jobs, save_job
from pipeline.lipsync import (
    LIPSYNC_ENGINE,
    LIPSYNC_OUTPUT_NAME,
    build_worker_job,
    extract_audio_cmd,
    find_musetalk_setup,
    musetalk_install_guide,
    probe_musetalk,
    remux_cmd,
    resolve_ffmpeg_bin,
    worker_cmd,
)

log = logging.getLogger("tachidubb.lipsync")


def run_lipsync(job_id: str) -> dict:
    """Synchronously apply MuseTalk to a job's dubbed_video.mp4.

    Used by both the manual `POST /api/dub/{id}/lip_sync` endpoint AND the
    auto-lip-sync hook in the queue worker (when the job was submitted with
    `lip_sync=True`).

    Returns a dict with `ok`, `url`, `elapsed_sec` on success — or `error` +
    `message` (+ optional `stderr_tail`) on failure. Updates
    `jobs[job_id]['lipsync_status']` ('running' → 'done' | 'error') and
    `lipsync_url` so the UI can poll for completion.
    """
    if job_id not in jobs:
        return {"error": "job_not_found", "message": f"Job {job_id} not found"}

    setup = find_musetalk_setup()
    if not setup:
        return {"error": "musetalk_not_installed", "guide": musetalk_install_guide()}

    info = probe_musetalk()
    if info["missing_weights"]:
        return {
            "error": "musetalk_weights_incomplete",
            "message": "MuseTalk is installed but some model weight files are missing. "
                       "Run tools/ensure_musetalk_weights.py (or MuseTalk's download_weights).",
            "missing": info["missing_weights"],
        }

    work = OUTPUT_DIR / job_id
    src_video = work / "dubbed_video.mp4"
    if not src_video.exists():
        return {"error": "no_dub", "message": "Dubbed video not generated yet"}

    dub_wav = work / "_lipsync_dub.wav"
    try:
        _sp.run(extract_audio_cmd(str(src_video), str(dub_wav)),
                check=True, capture_output=True, timeout=120)
    except _sp.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")[-400:]
        return {"error": "audio_extract_failed", "message": err}

    raw_out = work / "_lipsync_raw.mp4"
    job_json_path = work / "_lipsync_job.json"
    job_spec = build_worker_job(
        setup, str(src_video), str(dub_wav), str(raw_out),
        resolve_ffmpeg_bin(),
    )
    try:
        job_json_path.write_text(
            json.dumps(job_spec, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        return {"error": "lipsync_setup_failed", "message": str(e)}

    worker_script = BASE / "pipeline" / "musetalk_worker.py"
    log.info(f"[lipsync] Running MuseTalk ({setup['version']}) for job {job_id}")
    jobs[job_id]["lipsync_status"] = "running"
    jobs[job_id]["lipsync_engine"] = LIPSYNC_ENGINE
    save_job(jobs[job_id])
    elapsed = 0.0
    try:
        t0 = time.time()
        result = _sp.run(
            worker_cmd(setup["python"], str(worker_script), str(job_json_path)),
            cwd=str(BASE), capture_output=True, text=True, timeout=3600,
        )
        if result.returncode != 0:
            err_tail = ((result.stderr or "") + (result.stdout or ""))[-600:]
            log.warning(f"[lipsync] MuseTalk failed: {err_tail}")
            jobs[job_id]["lipsync_status"] = "error"
            jobs[job_id]["lipsync_error"] = err_tail
            save_job(jobs[job_id])
            return {
                "error": "musetalk_runtime_error",
                "message": "MuseTalk ran but failed. Likely no face detected, "
                           "GPU OOM, or missing runtime dependencies.",
                "stderr_tail": err_tail,
            }
        elapsed = time.time() - t0
        log.info(f"[lipsync] MuseTalk done in {elapsed:.0f}s")
    except _sp.TimeoutExpired:
        jobs[job_id]["lipsync_status"] = "error"
        save_job(jobs[job_id])
        return {"error": "musetalk_timeout", "message": "Didn't finish in 60 minutes"}

    if not raw_out.exists():
        jobs[job_id]["lipsync_status"] = "error"
        save_job(jobs[job_id])
        return {"error": "musetalk_no_output",
                "message": "MuseTalk reported success but produced no output"}

    # Re-mux with the original full-quality dub audio (MuseTalk's output is
    # video-only; the dubbed audio track is carried over from src_video).
    final_out = work / LIPSYNC_OUTPUT_NAME
    try:
        _sp.run(remux_cmd(str(raw_out), str(src_video), str(final_out)),
                check=True, capture_output=True, timeout=300)
    except _sp.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")[-400:]
        jobs[job_id]["lipsync_status"] = "error"
        save_job(jobs[job_id])
        return {"error": "final_mux_failed", "message": err}
    finally:
        for p in (dub_wav, raw_out, job_json_path):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    url = f"/outputs/{job_id}/{LIPSYNC_OUTPUT_NAME}?v={int(time.time())}"
    jobs[job_id]["lipsync_status"] = "done"
    jobs[job_id]["lipsync_url"] = url
    jobs[job_id].pop("lipsync_error", None)
    save_job(jobs[job_id])
    return {"ok": True, "url": url, "elapsed_sec": round(elapsed, 1)}