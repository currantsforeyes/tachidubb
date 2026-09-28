"""GET /api/dub/{id}/timeline — data behind the dialogue editor.

Pins the fields the DAW-style UI relies on: per-segment original text (for the
"Original Text" lane) and the dubbed-audio waveform peaks.
"""
import json

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

import app.checkpoints as checkpoints
import app.routers.dub as dub_routes
from app.main import app

client = TestClient(app)

JOB = "tljob"


def _wav(path, seconds=1.0, sr=8000, amp=0.3):
    y = (np.ones(int(sr * seconds)) * amp).astype("float32")
    sf.write(str(path), y, sr)
    return path


def _seed(tmp_path, monkeypatch):
    # The route loads its checkpoint via app.checkpoints (module-level
    # OUTPUT_DIR) and reads clips via dub_routes.OUTPUT_DIR — patch both.
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    d = tmp_path / JOB
    d.mkdir()
    a1 = _wav(d / "seg0.wav", seconds=1.0)
    a2 = _wav(d / "seg1.wav", seconds=1.0)
    (d / "checkpoint_tts_done.json").write_text(json.dumps({
        "duration": 4.0,
        "timeline_cuts": [1.0],
        "segments": [
            {"idx": 0, "start": 0.0, "end": 1.0, "text": "Hello",
             "translated_text": "Bonjour", "speaker": "SPEAKER_00",
             "audio_path": str(a1)},
            {"idx": 1, "start": 1.0, "end": 2.0, "text": "World",
             "translated_text": "Monde", "speaker": "SPEAKER_01",
             "audio_path": str(a2)},
        ],
    }), encoding="utf-8")
    _wav(d / "dubbed_audio.wav", seconds=4.0)
    _wav(d / "audio_16k.wav", seconds=4.0)
    return d


def test_timeline_returns_clips_original_text_and_peaks(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    r = client.get(f"/api/dub/{JOB}/timeline")

    assert r.status_code == 200
    body = r.json()
    assert body["duration"] == 4.0
    assert body["cuts"] == [1.0]

    seg0 = body["segments"][0]
    assert seg0["original_text"] == "Hello"     # original-language lane
    assert seg0["text"] == "Bonjour"            # translated lane
    assert seg0["speaker"] == "SPEAKER_00"
    assert seg0["duration"] == 1.0

    assert len(body["segments"]) == 2
    assert body["dubbed_video_url"].endswith("dubbed_video.mp4")
    assert body["peaks"] and max(body["peaks"]) == 1.0
    assert body["source_peaks"] and max(body["source_peaks"]) == 1.0


def test_timeline_without_checkpoint_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    (tmp_path / JOB).mkdir()
    r = client.get(f"/api/dub/{JOB}/timeline")
    assert r.status_code == 404


def test_timeline_exposes_the_two_reference_stem_lanes(tmp_path, monkeypatch):
    """The editor's top two lanes read speech_peaks (separated source speech)
    and bg_peaks (separated background) — both must be served when the stems
    exist, with source_peaks kept for older consumers."""
    d = _seed(tmp_path, monkeypatch)
    # Constant-amplitude content normalises to all-1.0 in waveform_peaks, so
    # give the two stems different shapes to prove each lane reads its own file.
    sf.write(str(d / "vocals.wav"),
             np.linspace(0, 1, 4 * 8000, dtype="float32"), 8000)
    _wav(d / "background.wav", seconds=4.0, amp=0.1)

    r = client.get(f"/api/dub/{JOB}/timeline")

    assert r.status_code == 200
    body = r.json()
    assert body["speech_stem"] is True
    assert body["speech_peaks"] and max(body["speech_peaks"]) == 1.0
    assert body["bg_peaks"] and max(body["bg_peaks"]) == 1.0
    # The full original mix stays on the payload (tests + MCP read it).
    assert body["source_peaks"] and max(body["source_peaks"]) == 1.0
    # Different shapes per lane — an identical pair would mean one file was
    # read twice and the lanes are showing the same stem.
    assert body["speech_peaks"] != body["bg_peaks"]


def test_timeline_without_stems_falls_back_to_the_full_mix(tmp_path, monkeypatch):
    """Jobs that predate always-on stem split get an honest fallback: the
    speech lane shows the mix (speech_stem False) and the background lane is
    empty so the UI can say so instead of drawing a phantom track."""
    _seed(tmp_path, monkeypatch)  # no vocals.wav / background.wav

    r = client.get(f"/api/dub/{JOB}/timeline")

    assert r.status_code == 200
    body = r.json()
    assert body["speech_stem"] is False
    assert body["speech_peaks"] == body["source_peaks"]
    assert body["bg_peaks"] == []
