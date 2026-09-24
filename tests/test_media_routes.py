"""HTTP tests for the subtitle preview + burn-in routes.

These drive the real routes through TestClient. The happy paths run actual
ffmpeg and are skipped when ffmpeg (with libass) isn't available; the error
paths are ffmpeg-free.

Regression note: ``/subs_preview`` seeks with ``-ss`` before ``-i``. That
rebases timestamps to ~0, so without ``-copyts`` the ``subtitles`` filter
draws the cue at t=0 instead of the cue at the requested timestamp —
``test_preview_draws_cue_at_requested_timestamp`` pins the fix.
"""
import json
import shutil
import subprocess

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.routers.media as media_routes
from app.main import app

client = TestClient(app)

JOB_ID = "testjob"


def _ffmpeg_supports_subtitles() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return False
    return any(" subtitles " in line for line in out.splitlines())


needs_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_supports_subtitles(),
    reason="ffmpeg with the libass 'subtitles' filter is required",
)


@pytest.fixture
def work(tmp_path, monkeypatch):
    """Isolate the routes: send OUTPUT_DIR to a temp dir and seed one job."""
    monkeypatch.setattr(media_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(media_routes, "jobs", {JOB_ID: {"id": JOB_ID, "status": "complete"}})
    d = tmp_path / JOB_ID
    d.mkdir()
    return d


# ── helpers ──────────────────────────────────────────────────────────
def _make_video(path, seconds=5):
    """A tiny solid-white clip (with audio) standing in for a dubbed video."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=white:s=320x240:r=25:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True, timeout=120,
    )


def _write_srt(path, start, end, text):
    def ts(t):
        m, s = divmod(t, 60)
        return f"00:{int(m):02d}:{s:06.3f}".replace(".", ",")
    path.write_text(f"1\n{ts(start)} --> {ts(end)}\n{text}\n", encoding="utf-8")


def _mean_luma(data: bytes) -> float:
    """Mean brightness (0-255) of an image, via ffmpeg -> raw gray."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "image2pipe", "-i", "-",
         "-vf", "format=gray", "-f", "rawvideo", "-"],
        input=data, check=True, capture_output=True, timeout=60,
    ).stdout
    arr = np.frombuffer(raw, dtype=np.uint8)
    return float(arr.mean()) if arr.size else -1.0


def _checkpoint(text="Salut"):
    return {"segments": [
        {"start": 0.0, "end": 1.0, "text": "Hi", "translated_text": text},
    ]}


# ── burn_subs: error paths (no ffmpeg needed) ─────────────────────────
def test_burn_subs_unknown_job_404(work):
    r = client.post("/api/dub/nope/burn_subs", data={"style": "default"})
    assert r.status_code == 404


def test_burn_subs_unknown_style_400(work):
    r = client.post(f"/api/dub/{JOB_ID}/burn_subs", data={"style": "nope"})
    assert r.status_code == 400
    assert "Unknown style" in r.json()["error"]


def test_burn_subs_missing_video_400(work):
    r = client.post(f"/api/dub/{JOB_ID}/burn_subs", data={"style": "default"})
    assert r.status_code == 400
    assert "not yet generated" in r.json()["error"]


def test_burn_subs_no_transcript_400(work):
    (work / "dubbed_video.mp4").write_bytes(b"x")  # exists, but no SRT/checkpoint
    r = client.post(f"/api/dub/{JOB_ID}/burn_subs", data={"style": "default"})
    assert r.status_code == 400
    assert "No transcript data" in r.json()["error"]


def test_burn_subs_regenerates_srt_from_checkpoint(work, monkeypatch):
    """A missing SRT is rebuilt from the checkpoint before ffmpeg runs."""
    (work / "dubbed_video.mp4").write_bytes(b"x")
    (work / "checkpoint_translation_done.json").write_text(
        json.dumps(_checkpoint("Salut")), encoding="utf-8")

    def boom(*_a, **_k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(media_routes.subprocess, "run", boom)
    r = client.post(f"/api/dub/{JOB_ID}/burn_subs", data={"style": "default"})

    assert r.status_code == 500
    assert "ffmpeg" in r.json()["error"].lower()
    assert "Salut" in (work / "translated.srt").read_text(encoding="utf-8")


def test_burn_subs_prefers_tts_checkpoint(work, monkeypatch):
    """checkpoint_tts_done (final text) wins over the translation checkpoint."""
    (work / "dubbed_video.mp4").write_bytes(b"x")
    (work / "checkpoint_translation_done.json").write_text(
        json.dumps(_checkpoint("translation")), encoding="utf-8")
    (work / "checkpoint_tts_done.json").write_text(
        json.dumps(_checkpoint("spoken")), encoding="utf-8")

    monkeypatch.setattr(media_routes.subprocess, "run",
                        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError()))
    client.post(f"/api/dub/{JOB_ID}/burn_subs", data={"style": "default"})

    srt = (work / "translated.srt").read_text(encoding="utf-8")
    assert "spoken" in srt and "translation" not in srt


def test_burn_subs_timeout_returns_500(work, monkeypatch):
    (work / "dubbed_video.mp4").write_bytes(b"x")
    (work / "translated.srt").write_text("", encoding="utf-8")

    def timeout(*_a, **_k):
        raise subprocess.TimeoutExpired("ffmpeg", 600)

    monkeypatch.setattr(media_routes.subprocess, "run", timeout)
    r = client.post(f"/api/dub/{JOB_ID}/burn_subs", data={"style": "default"})
    assert r.status_code == 500
    assert "timed out" in r.json()["error"]


# ── subs_preview: error paths (no ffmpeg needed) ──────────────────────
def test_preview_unknown_job_404(work):
    r = client.post("/api/dub/nope/subs_preview", data={"style": "default"})
    assert r.status_code == 404


def test_preview_unknown_style_400(work):
    r = client.post(f"/api/dub/{JOB_ID}/subs_preview", data={"style": "nope"})
    assert r.status_code == 400
    assert "Unknown style" in r.json()["error"]


def test_preview_missing_video_400(work):
    r = client.post(f"/api/dub/{JOB_ID}/subs_preview", data={"style": "default"})
    assert r.status_code == 400


def test_preview_no_transcript_400(work):
    (work / "dubbed_video.mp4").write_bytes(b"x")
    r = client.post(f"/api/dub/{JOB_ID}/subs_preview", data={"style": "default"})
    assert r.status_code == 400
    assert "No transcript data" in r.json()["error"]


def test_preview_ffmpeg_missing_returns_500(work, monkeypatch):
    (work / "dubbed_video.mp4").write_bytes(b"x")
    (work / "translated.srt").write_text("", encoding="utf-8")

    def boom(*_a, **_k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(media_routes.subprocess, "run", boom)
    r = client.post(f"/api/dub/{JOB_ID}/subs_preview",
                    data={"style": "default", "timestamp": "1.0"})
    assert r.status_code == 500
    assert "ffmpeg" in r.json()["error"].lower()


# ── happy paths (real ffmpeg) ─────────────────────────────────────────
@needs_ffmpeg
def test_burn_subs_end_to_end(work):
    _make_video(work / "dubbed_video.mp4")
    _write_srt(work / "translated.srt", 0.0, 1.0, "Bonjour")

    r = client.post(f"/api/dub/{JOB_ID}/burn_subs", data={"style": "default"})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "dubbed_video_subs.mp4" in body["url"]
    out = work / "dubbed_video_subs.mp4"
    assert out.exists() and out.stat().st_size > 1000


@needs_ffmpeg
def test_preview_end_to_end_returns_png(work):
    _make_video(work / "dubbed_video.mp4")
    _write_srt(work / "translated.srt", 0.0, 1.0, "Bonjour")

    r = client.post(f"/api/dub/{JOB_ID}/subs_preview",
                    data={"style": "minimal", "timestamp": "0.5"})

    assert r.status_code == 200
    assert "subs_preview_minimal.png" in r.json()["url"]
    png = work / "subs_preview_minimal.png"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@needs_ffmpeg
def test_preview_draws_cue_at_requested_timestamp(work):
    """A cue that exists only at 3.0-3.5s must appear when previewing 3.2s.

    Before the -copyts fix the timeline was rebased to 0, so the 3.2s preview
    was blank and the t=0 cue (if any) leaked in instead.
    """
    _make_video(work / "dubbed_video.mp4")
    _write_srt(work / "translated.srt", 3.0, 3.5, "LATE")

    r = client.post(f"/api/dub/{JOB_ID}/subs_preview",
                    data={"style": "large", "timestamp": "3.2"})
    assert r.status_code == 200
    at_cue = _mean_luma((work / "subs_preview_large.png").read_bytes())

    # Same frame at 1.0s, where the cue is not active -> the white baseline.
    r2 = client.post(f"/api/dub/{JOB_ID}/subs_preview",
                     data={"style": "large", "timestamp": "1.0"})
    assert r2.status_code == 200
    blank = _mean_luma((work / "subs_preview_large.png").read_bytes())

    assert blank - at_cue > 1.0, "subtitle text was not drawn at the requested timestamp"