"""Tests for ``assemble_showcase_sync`` — the multilingual reel stitcher.

The early-exit guards are ffmpeg-free; the full stitch runs real ffmpeg and is
skipped unless the drawtext filter and a usable font are available.
"""
import json
import subprocess

import pytest

import app.showcase as showcase
from app.checkpoints import save_checkpoint
from pipeline.media import probe_duration


def _job(jid, lang, pos):
    return {
        "id": jid,
        "target_lang": lang,
        "batch_position": pos,
        "batch_id": "B1",
        "batch_kind": "showcase",
        "status": "complete",
    }


@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(showcase, "OUTPUT_DIR", tmp_path)
    return tmp_path


def _make_video(path, seconds=2):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=teal:s=320x240:r=25:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True, timeout=120,
    )


# ── early-exit guards (no ffmpeg) ─────────────────────────────────────
def test_aborts_when_dub_files_are_missing(output_dir):
    siblings = [_job("j1", "fr", 0), _job("j2", "es", 1)]
    (output_dir / "j1").mkdir()
    (output_dir / "j2").mkdir()

    showcase.assemble_showcase_sync("B1", siblings, output_dir / "showcase_B1")

    assert not (output_dir / "showcase_B1" / "showcase.mp4").exists()


def test_aborts_when_no_duration_can_be_determined(output_dir, monkeypatch):
    siblings = [_job("j1", "fr", 0), _job("j2", "es", 1)]
    for j in siblings:
        d = output_dir / j["id"]
        d.mkdir()
        (d / "dubbed_video.mp4").write_bytes(b"x")

    monkeypatch.setattr(showcase, "_load_placements", lambda _w: [])
    monkeypatch.setattr(showcase, "_probe_duration", lambda _p: 0.0)

    def boom(*_a, **_k):  # ffprobe fails -> no audio duration
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(showcase.subprocess, "run", boom)

    showcase.assemble_showcase_sync("B1", siblings, output_dir / "showcase_B1")

    assert not (output_dir / "showcase_B1" / "showcase.mp4").exists()


# ── full stitch (real ffmpeg) ─────────────────────────────────────────
def test_stitches_two_languages_into_one_reel(output_dir, ffmpeg_drawtext):
    """Two 1s slices -> a ~2s reel.

    Guards the overlap-matching boundary bug: with the old
    ``g_e + 0.001`` / ``g_s - 0.001`` tolerance each slice also claimed the
    segment merely touching its boundary, so every slice expanded to the whole
    timeline and the reel came out N× too long (4s instead of 2s here).
    """
    siblings = [_job("j1", "fr", 0), _job("j2", "es", 1)]
    for j in siblings:
        d = output_dir / j["id"]
        d.mkdir()
        _make_video(d / "dubbed_video.mp4", seconds=2)
        save_checkpoint(j["id"], d, "tts_done", {"segments": [
            {"idx": 0, "start": 0.0, "end": 1.0, "text": "a", "translated_text": "a"},
            {"idx": 1, "start": 1.0, "end": 2.0, "text": "b", "translated_text": "b"},
        ]})
        (d / "tts_placements.json").write_text(json.dumps([
            {"idx": 0, "src_start": 0.0, "src_end": 1.0, "dub_start": 0.0, "dub_end": 1.0},
            {"idx": 1, "src_start": 1.0, "src_end": 2.0, "dub_start": 1.0, "dub_end": 2.0},
        ]), encoding="utf-8")

    out_dir = output_dir / "showcase_B1"
    showcase.assemble_showcase_sync("B1", siblings, out_dir)

    out_mp4 = out_dir / "showcase.mp4"
    assert out_mp4.exists() and out_mp4.stat().st_size > 1000

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["n_segments"] == 2
    assert [s["lang"] for s in manifest["slices"]] == ["fr", "es"]

    # Both 1s slices concatenated -> ~2s reel (not 1s, not 4s).
    assert 1.5 < probe_duration(out_mp4) < 2.6