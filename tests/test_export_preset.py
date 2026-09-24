"""HTTP tests for the platform-export route.

Drives ``/api/dub/{id}/export`` through TestClient: error paths are
ffmpeg-free; the encode paths run real ffmpeg and are skipped when it (with
libass) isn't available.

The export route shares its subtitle materialisation with the preview and
burn-in routes via ``app.checkpoints.ensure_translated_srt``; these tests pin
that it regenerates the SRT from a checkpoint and that a job with no transcript
at all still exports (without subtitles) instead of failing.
"""
import json
import subprocess

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.routers.showcase as showcase_routes
from app.main import app

client = TestClient(app)

JOB_ID = "exportjob"


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(showcase_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(showcase_routes, "jobs", {JOB_ID: {"id": JOB_ID, "status": "complete"}})
    d = tmp_path / JOB_ID
    d.mkdir()
    return d


def _make_video(path, seconds=1):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=white:s=320x240:r=25:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True, timeout=120,
    )


def _srt():
    return ("1\n00:00:00,000 --> 00:00:01,000\nBonjour\n")


def _srt_late():
    return ("1\n00:00:09,000 --> 00:00:09,500\nBonjour\n")


def _frame_luma(video, ts):
    """Mean brightness (0-255) of the video frame at `ts` (ffmpeg -> raw gray)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{ts}", "-i", str(video),
         "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout
    arr = np.frombuffer(raw, dtype=np.uint8)
    return float(arr.mean()) if arr.size else -1.0


# ── error paths (no ffmpeg) ───────────────────────────────────────────
def test_export_unknown_job_404(work):
    r = client.post("/api/dub/nope/export", data={"preset": "youtube_1080p"})
    assert r.status_code == 404


def test_export_unknown_preset_400(work):
    r = client.post(f"/api/dub/{JOB_ID}/export", data={"preset": "myspace"})
    assert r.status_code == 400
    assert "Unknown preset" in r.json()["error"]


def test_export_unknown_style_rejected_when_burning(work):
    (work / "dubbed_video.mp4").write_bytes(b"x")
    r = client.post(f"/api/dub/{JOB_ID}/export",
                    data={"preset": "tiktok", "style": "nope"})
    assert r.status_code == 400
    assert "Unknown style" in r.json()["error"]


def test_export_ignores_style_when_not_burning(work):
    # youtube_1080p doesn't burn subs, so a stray style must not 400 — but the
    # video is missing, so we still get the 400 for that instead.
    r = client.post(f"/api/dub/{JOB_ID}/export",
                    data={"preset": "youtube_1080p", "style": "nope"})
    assert r.status_code == 400
    assert "not yet generated" in r.json()["error"]


def test_export_missing_video_400(work):
    r = client.post(f"/api/dub/{JOB_ID}/export", data={"preset": "twitter"})
    assert r.status_code == 400
    assert "not yet generated" in r.json()["error"]


def test_export_timeout_returns_500(work, monkeypatch):
    (work / "dubbed_video.mp4").write_bytes(b"x")

    def timeout(*_a, **_k):
        raise subprocess.TimeoutExpired("ffmpeg", 900)

    monkeypatch.setattr(showcase_routes.subprocess, "run", timeout)
    r = client.post(f"/api/dub/{JOB_ID}/export", data={"preset": "twitter"})
    assert r.status_code == 500
    assert "timed out" in r.json()["error"]


def test_export_regenerates_srt_from_checkpoint(work, monkeypatch):
    (work / "dubbed_video.mp4").write_bytes(b"x")
    (work / "checkpoint_tts_done.json").write_text(
        json.dumps({"segments": [
            {"start": 0.0, "end": 1.0, "text": "Hi", "translated_text": "Salut"}]}),
        encoding="utf-8")

    def boom(*_a, **_k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(showcase_routes.subprocess, "run", boom)
    r = client.post(f"/api/dub/{JOB_ID}/export", data={"preset": "tiktok"})

    assert r.status_code == 500
    assert "ffmpeg" in r.json()["error"].lower()
    assert "Salut" in (work / "translated.srt").read_text(encoding="utf-8")


# ── happy paths (real ffmpeg) ─────────────────────────────────────────
def test_export_without_subs(work, ffmpeg_subs):
    _make_video(work / "dubbed_video.mp4")

    r = client.post(f"/api/dub/{JOB_ID}/export", data={"preset": "twitter"})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["preset"] == "twitter"
    out = work / "export_twitter.mp4"
    assert out.exists() and out.stat().st_size > 1000


def test_export_burns_subs_with_style(work, ffmpeg_subs):
    _make_video(work / "dubbed_video.mp4")
    (work / "translated.srt").write_text(_srt(), encoding="utf-8")

    r = client.post(f"/api/dub/{JOB_ID}/export",
                    data={"preset": "tiktok", "style": "large"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    with_text = _frame_luma(work / "export_tiktok.mp4", 0.5)

    # Same preset and style, but the cue is outside the sampled frame -> baseline.
    (work / "translated.srt").write_text(_srt_late(), encoding="utf-8")
    r2 = client.post(f"/api/dub/{JOB_ID}/export",
                     data={"preset": "tiktok", "style": "large"})
    assert r2.status_code == 200
    blank = _frame_luma(work / "export_tiktok.mp4", 0.5)

    assert blank - with_text > 1.0, "export did not burn the active subtitle cue"


def test_export_burn_preset_without_transcript_still_succeeds(work, ffmpeg_subs):
    """No SRT and no checkpoint: export the video, just without subtitles."""
    _make_video(work / "dubbed_video.mp4")

    r = client.post(f"/api/dub/{JOB_ID}/export", data={"preset": "reels"})

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert (work / "export_reels.mp4").exists()