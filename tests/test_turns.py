"""Speaker-turn slicing: the plan (where cuts land) and the WAV export.

Pins the two contracts the editor's "slice at speaker changes" flow rests on:
  1. plan_speaker_turns tiles [0, duration] at speaker-change boundaries
     (plus manual cuts), matching the cut lines the editor draws.
  2. export_turn_wavs slices dubbed_audio.wav exactly at those boundaries,
     drops stale files, and never reads past the end of the file.
Route tests for GET/POST /api/dub/{id}/turns live at the bottom.
"""
import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import app.checkpoints as checkpoints
import app.routers.dub as dub_routes
import pipeline.media as media
from app.main import app

client = TestClient(app)

JOB = "turnjob"
SR = 8000


def _row(start, speaker, text="hello", duration=1.0, source_start=None):
    return {
        "idx": int(start * 10), "start": start, "speaker": speaker,
        "text": text, "original_text": text,
        "source_start": start if source_start is None else source_start,
        "source_end": start + duration,
        "duration": duration,
    }


# ── plan_speaker_turns ───────────────────────────────────────────────
def test_plan_splits_only_where_speaker_changes():
    # Same speaker keeps talking across 1.0 → no boundary there.
    rows = [
        _row(0.0, "SPEAKER_00"), _row(1.0, "SPEAKER_00"),
        _row(2.0, "SPEAKER_01"), _row(3.5, "SPEAKER_00"),
    ]
    turns = media.plan_speaker_turns(rows, duration=5.0)

    assert [(t["start"], t["end"], t["speaker"]) for t in turns] == [
        (0.0, 2.0, "SPEAKER_00"),
        (2.0, 3.5, "SPEAKER_01"),
        (3.5, 5.0, "SPEAKER_00"),
    ]
    # Text inside a turn is the join of its segments.
    assert turns[0]["text"] == "hello hello"
    # Source ranges stay on the original clock.
    assert turns[1]["source_start"] == 2.0
    assert turns[1]["source_end"] == 3.0


def test_plan_manual_cuts_split_turns_too():
    rows = [_row(0.0, "SPEAKER_00"), _row(3.0, "SPEAKER_00")]
    turns = media.plan_speaker_turns(rows, duration=5.0, extra_cuts=[1.5])

    assert [(t["start"], t["end"]) for t in turns] == [(0.0, 1.5), (1.5, 5.0)]


def test_plan_keeps_speech_when_cut_lands_mid_segment():
    # A manual cut at 1.5 splits one segment [0, 2): BOTH tiles must keep
    # the speech — the second one by overlap, not by start.
    rows = [_row(0.0, "SPEAKER_00", duration=2.0)]
    turns = media.plan_speaker_turns(rows, duration=5.0, extra_cuts=[1.5])

    assert [(t["start"], t["end"]) for t in turns] == [(0.0, 1.5), (1.5, 5.0)]
    assert all(t["speaker"] == "SPEAKER_00" for t in turns)
    assert all(t["text"] == "hello" for t in turns)


def test_plan_skips_pure_silence_tiles():
    # Cut inside a silent gap: no segment overlaps [1.5, 2.0) → not a turn.
    rows = [_row(0.0, "SPEAKER_00", duration=1.0),
            _row(3.0, "SPEAKER_01", duration=1.0)]
    turns = media.plan_speaker_turns(rows, duration=5.0, extra_cuts=[1.5])

    starts = [(t["start"], t["end"]) for t in turns]
    assert starts == [(0.0, 1.5), (3.0, 5.0)]


def test_plan_is_3dp_and_handles_empty_input():
    assert media.plan_speaker_turns([], duration=5.0) == []
    assert media.plan_speaker_turns([_row(0.0, "A")], duration=0.0) == []
    # Boundary rounding matches what the timeline route persists.
    rows = [_row(0.0, "A"), _row(1.23456, "B")]
    turns = media.plan_speaker_turns(rows, duration=5.0)
    assert turns[0]["end"] == 1.235


def test_plan_single_speaker_is_one_turn():
    rows = [_row(0.0, "A"), _row(2.0, "A")]
    turns = media.plan_speaker_turns(rows, duration=5.0)
    assert len(turns) == 1
    assert turns[0]["start"] == 0.0 and turns[0]["end"] == 5.0


# ── export_turn_wavs ─────────────────────────────────────────────────
def _wav(path, seconds, freq=440.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    sf.write(str(path), (0.4 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)
    return str(path)


def test_export_slices_at_boundaries_and_cleans_stale(tmp_path):
    dubbed = _wav(tmp_path / "dubbed_audio.wav", 4.0)
    out = tmp_path / "turns"
    out.mkdir()
    stale = out / "turn_99_0.00-1.00_STALE.wav"
    stale.write_bytes(b"old export")

    turns = [
        {"index": 0, "start": 0.0, "end": 1.5, "speaker": "SPEAKER_00",
         "text": "a", "original_text": "a", "source_start": 0.0, "source_end": 1.5},
        {"index": 1, "start": 1.5, "end": 4.0, "speaker": "SPEAKER_01",
         "text": "b", "original_text": "b", "source_start": 1.5, "source_end": 4.0},
    ]
    written = media.export_turn_wavs(turns, dubbed, out)

    assert not stale.exists(), "stale export must be replaced"
    assert [w["file"] for w in written] == [
        "turn_00_0.00-1.50_SPEAKER_00.wav", "turn_01_1.50-4.00_SPEAKER_01.wav"]
    d0 = sf.info(str(out / written[0]["file"]))
    d1 = sf.info(str(out / written[1]["file"]))
    assert d0.frames / d0.samplerate == pytest.approx(1.5, abs=0.01)
    assert d1.frames / d1.samplerate == pytest.approx(2.5, abs=0.01)
    # Slices together cover the whole file: no gap, no overlap.
    assert d0.frames + d1.frames == sf.info(str(dubbed)).frames


def test_export_clamps_past_end_of_file(tmp_path):
    # Plan says 6s (video length) but the rendered file is only 4s.
    dubbed = _wav(tmp_path / "dubbed_audio.wav", 4.0)
    turns = [
        {"index": 0, "start": 0.0, "end": 3.0, "speaker": "A",
         "text": "a", "original_text": "a", "source_start": 0.0, "source_end": 3.0},
        {"index": 1, "start": 3.0, "end": 6.0, "speaker": "B",
         "text": "b", "original_text": "b", "source_start": 3.0, "source_end": 6.0},
        {"index": 2, "start": 7.0, "end": 8.0, "speaker": "C",
         "text": "c", "original_text": "c", "source_start": 7.0, "source_end": 8.0},
    ]
    written = media.export_turn_wavs(turns, dubbed, tmp_path / "turns")

    # Turn 1 clamps to the file end; turn 2 lies beyond it and is skipped.
    assert [w["index"] for w in written] == [0, 1]
    info = sf.info(str(tmp_path / "turns" / written[1]["file"]))
    assert info.frames / info.samplerate == pytest.approx(1.0, abs=0.01)


# ── HTTP routes ──────────────────────────────────────────────────────
def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB, "status": "complete"}})
    d = tmp_path / JOB
    d.mkdir()
    a0 = _wav(d / "seg0.wav", 1.0)
    a1 = _wav(d / "seg1.wav", 1.0)
    (d / "checkpoint_tts_done.json").write_text(json.dumps({
        "duration": 4.0,
        "timeline_cuts": [3.0],
        "segments": [
            {"idx": 0, "speaker": "SPEAKER_00", "audio_path": a0,
             "text": "Hola", "translated_text": "Hello",
             "start": 0.0, "end": 1.0},
            {"idx": 1, "speaker": "SPEAKER_01", "audio_path": a1,
             "text": "Adios", "translated_text": "Bye",
             "start": 1.5, "end": 2.5},
        ],
    }), encoding="utf-8")
    _wav(d / "dubbed_audio.wav", 4.0)
    return d


def test_get_turns_returns_plan_and_empty_export(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    r = client.get(f"/api/dub/{JOB}/turns")

    assert r.status_code == 200
    body = r.json()
    assert body["duration"] == 4.0
    # Speaker change at 1.5 + manual cut at 3.0. The [3.0, 4.0] tail holds
    # no speech (last clip ends at 2.5) so it is silence, not a turn.
    assert [(t["start"], t["end"], t["speaker"]) for t in body["turns"]] == [
        (0.0, 1.5, "SPEAKER_00"),
        (1.5, 3.0, "SPEAKER_01"),
    ]
    assert body["turns"][0]["text"] == "Hello"
    assert body["exported"] == []


def test_get_turns_404_without_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    (tmp_path / JOB).mkdir()
    assert client.get(f"/api/dub/{JOB}/turns").status_code == 404


def test_export_turns_writes_wavs_and_manifest(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    r = client.post(f"/api/dub/{JOB}/turns/export")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == body["planned"] == 2
    assert all(t["url"].startswith(f"/outputs/{JOB}/turns/") for t in body["turns"])
    work = tmp_path / JOB
    for t in body["turns"]:
        assert (work / "turns" / t["file"]).exists()
    manifest = json.loads((work / "turns" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["job_id"] == JOB
    assert manifest["source"] == "dubbed_audio.wav"
    assert [m["file"] for m in manifest["turns"]] == [t["file"] for t in body["turns"]]
    assert manifest["turns"][0]["url"].endswith(".wav")

    # A second GET now reports the export.
    body2 = client.get(f"/api/dub/{JOB}/turns").json()
    assert len(body2["exported"]) == 2


def test_export_rejects_unknown_job_and_missing_checkpoints(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(dub_routes, "jobs", {})          # job not in memory
    assert client.post(f"/api/dub/{JOB}/turns/export").status_code == 404

    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB}})
    (tmp_path / JOB / "checkpoint_tts_done.json").unlink()
    assert client.post(f"/api/dub/{JOB}/turns/export").status_code == 404
    assert client.get(f"/api/dub/{JOB}/turns").status_code == 404


def test_export_404_without_dubbed_audio(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    (d / "dubbed_audio.wav").unlink()
    r = client.post(f"/api/dub/{JOB}/turns/export")
    assert r.status_code == 404
    assert "dubbed_audio" in r.json()["error"]


def test_export_400_when_no_segments(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    cp = json.loads((d / "checkpoint_tts_done.json").read_text(encoding="utf-8"))
    cp["segments"] = []
    (d / "checkpoint_tts_done.json").write_text(json.dumps(cp), encoding="utf-8")
    r = client.post(f"/api/dub/{JOB}/turns/export")
    assert r.status_code == 400
