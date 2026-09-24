"""HTTP surface for per-speaker stems used by the dialogue editor."""
import json

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

import app.checkpoints as checkpoints
import app.routers.dub as dub_routes
from app.main import app

client = TestClient(app)

JOB = "stemjob"
SR = 8000


def _tone(path, seconds=0.4):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32"), SR)
    return str(path)


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB, "status": "complete"}})
    d = tmp_path / JOB
    d.mkdir()
    a0 = _tone(d / "seg0.wav")
    a1 = _tone(d / "seg1.wav")
    (d / "checkpoint_tts_done.json").write_text(json.dumps({
        "duration": 2.0,
        "segments": [
            {"idx": 0, "speaker": "SPEAKER_00", "audio_path": a0,
             "start": 0.0, "end": 0.4, "placed_start": 0.0, "placed_end": 0.4},
            {"idx": 1, "speaker": "SPEAKER_01", "audio_path": a1,
             "start": 1.0, "end": 1.4, "placed_start": 1.0, "placed_end": 1.4},
        ],
    }), encoding="utf-8")
    return d


def test_list_stems(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    r = client.get(f"/api/dub/{JOB}/stems")

    assert r.status_code == 200
    stems = r.json()["stems"]
    assert [s["speaker"] for s in stems] == ["SPEAKER_00", "SPEAKER_01"]
    assert all(s["ready"] is False for s in stems)      # not rendered yet
    assert stems[0]["audio_url"] == f"/api/dub/{JOB}/stem/SPEAKER_00/audio"


def test_stem_audio_is_generated_on_demand(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)

    r = client.get(f"/api/dub/{JOB}/stem/SPEAKER_00/audio")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.content[:4] == b"RIFF"
    assert (d / "stem_SPEAKER_00.wav").exists()

    # and it now reports ready
    stems = client.get(f"/api/dub/{JOB}/stems").json()["stems"]
    assert next(s for s in stems if s["speaker"] == "SPEAKER_00")["ready"] is True


def test_stem_invalid_speaker_id_400(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    r = client.get(f"/api/dub/{JOB}/stem/../etc/audio")
    assert r.status_code in (400, 404)


def test_stem_unknown_speaker_404(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    r = client.get(f"/api/dub/{JOB}/stem/SPEAKER_99/audio")
    assert r.status_code == 404


def test_stems_without_checkpoint_404(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    (tmp_path / JOB).mkdir()
    r = client.get(f"/api/dub/{JOB}/stems")
    assert r.status_code == 404


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def test_stem_uses_placements_file_when_checkpoint_has_none(tmp_path, monkeypatch):
    """Normal runs save tts_done BEFORE assembly, so placement is only in
    tts_placements.json — the stem must still land at the dubbed position."""
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB}})
    d = tmp_path / JOB
    d.mkdir()
    a = _tone(d / "seg0.wav")          # 0.4s
    (d / "checkpoint_tts_done.json").write_text(json.dumps({
        "duration": 3.0,
        "segments": [{"idx": 0, "speaker": "SPEAKER_00", "audio_path": a,
                      "start": 0.0, "end": 0.4}],   # note: no placed_start
    }), encoding="utf-8")
    (d / "tts_placements.json").write_text(json.dumps([
        {"idx": 0, "src_start": 0.0, "src_end": 0.4, "dub_start": 2.0, "dub_end": 2.4},
    ]), encoding="utf-8")

    r = client.get(f"/api/dub/{JOB}/stem/SPEAKER_00/audio")

    assert r.status_code == 200
    s, sr = sf.read(str(d / "stem_SPEAKER_00.wav"))
    assert _rms(s[:int(1.5 * sr)]) < 1e-6                    # not at source 0
    assert _rms(s[int(2.05 * sr):int(2.35 * sr)]) > 0.1      # at placed 2.0s


def test_empty_speaker_id_is_normalised(tmp_path, monkeypatch):
    """Older single-speaker jobs store speaker="" — treat it as SPEAKER_00."""
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB}})
    d = tmp_path / JOB
    d.mkdir()
    a = _tone(d / "seg0.wav")
    (d / "checkpoint_tts_done.json").write_text(json.dumps({
        "duration": 1.0,
        "segments": [{"idx": 0, "speaker": "", "audio_path": a,
                      "start": 0.0, "end": 0.4}],
    }), encoding="utf-8")

    stems = client.get(f"/api/dub/{JOB}/stems").json()["stems"]

    assert [s["speaker"] for s in stems] == ["SPEAKER_00"]
    assert client.get(f"/api/dub/{JOB}/stem/SPEAKER_00/audio").status_code == 200