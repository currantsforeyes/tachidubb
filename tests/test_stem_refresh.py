"""Always-on per-speaker stems: refresh at every rebuild + export endpoint.

Phase 4 contracts:
  1. refresh_speaker_stems renders every stem and NEVER raises (stems are
     an editing aid — a failure must not kill a completed pipeline run).
  2. Every rebuild site (fresh pipeline, resume/retry/regen, timeline apply)
     calls it, so the editor's solo/mute never plays stale placements.
  3. fit_to_slots threads through: a mismatched stretch cap makes a stem's
     clip a different tempo than the mix it sums with.
  4. POST /stems/export renders missing stems, writes stems_manifest.json
     (clip positions on the same clock the editor shows) and returns
     download links.
  5. _atempo_stretch reuses a previous stretch instead of re-running ffmpeg
     per stem (the main mix and N stems stretch the same clips).
"""
import asyncio
import json
import os
import time

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

import app.checkpoints as checkpoints
import app.pipeline as app_pipeline
import app.routers.dub as dub_routes
import pipeline.assembler as assembler
from app.main import app

client = TestClient(app)

JOB = "stemrefresh"
SR = 8000


def _tone(path, seconds=0.4, freq=440.0):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * freq * t)).astype("float32"), SR)
    return str(path)


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


# ── refresh_speaker_stems ────────────────────────────────────────────
def test_refresh_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("cuda OOM")
    monkeypatch.setattr(assembler, "assemble_speaker_stems", boom)

    out = assembler.refresh_speaker_stems([{"speaker": "SPEAKER_00"}], 4.0, tmp_path)

    assert out == {}          # logged, not raised


def test_refresh_renders_all_speakers(tmp_path):
    a0 = _tone(tmp_path / "s0.wav")
    a1 = _tone(tmp_path / "s1.wav")
    segs = [
        {"speaker": "SPEAKER_00", "audio_path": a0, "start": 0.0, "end": 0.4},
        {"speaker": "SPEAKER_01", "audio_path": a1, "start": 2.0, "end": 2.4},
    ]
    paths = assembler.refresh_speaker_stems(segs, 4.0, tmp_path, sample_rate=SR)

    assert set(paths) == {"SPEAKER_00", "SPEAKER_01"}
    assert (tmp_path / "stem_SPEAKER_00.wav").exists()
    assert (tmp_path / "stem_SPEAKER_01.wav").exists()


def test_fit_to_slots_threads_to_assembly(tmp_path, monkeypatch):
    """A Qwen-built mix uses fit_to_slots=True (1.40 cap) — the stems must
    stretch with the SAME cap or an overlong clip lands at a different tempo."""
    captured = {}

    def fake_assemble(segments, total_duration, output_path, **kwargs):
        captured.update(kwargs)
        return output_path

    monkeypatch.setattr(assembler, "assemble_dubbed_audio", fake_assemble)
    a0 = _tone(tmp_path / "s0.wav")

    assembler.assemble_speaker_stems(
        [{"speaker": "SPEAKER_00", "audio_path": a0}], 4.0, tmp_path,
        sample_rate=SR, fit_to_slots=True)

    assert captured["fit_to_slots"] is True
    assert captured["use_recorded"] is True
    assert captured["apply_loudnorm"] is False
    assert captured["sample_rate"] == SR


def test_atempo_reuses_existing_stretch(tmp_path, monkeypatch):
    """Main mix + N stems stretch the same clip: reuse, don't re-run ffmpeg."""
    src = _tone(tmp_path / "clip.wav", seconds=1.0)
    out = src + ".1.15x.wav"

    def no_ffmpeg(*a, **k):  # must not be reached on cache hit
        raise AssertionError("ffmpeg should not run for a fresh cached stretch")

    # Cache fresh (output newer than source) → returned without ffmpeg.
    _tone(out, seconds=1.0, freq=880.0)
    now = time.time()
    os.utime(src, (now - 60, now - 60))
    os.utime(out, (now, now))
    monkeypatch.setattr(assembler.subprocess, "run", no_ffmpeg)
    assert assembler._atempo_stretch(src, 1.15) == out

    # Source re-synthesized after the stretch (per-segment regen) → rebuild.
    os.utime(src, (now + 5, now + 5))   # source strictly newer than output
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        class R: returncode = 0
        return R()

    monkeypatch.setattr(assembler.subprocess, "run", fake_run)
    result = assembler._atempo_stretch(src, 1.15)
    assert len(calls) == 1, "stale stretch must be rebuilt"
    assert result == out


# ── site 2: resume / retry / per-segment regen ───────────────────────
def _fake_engine():
    class FakeTTS:
        sample_rate = SR
    return FakeTTS()


def test_resume_stage_refreshes_stems(tmp_path, monkeypatch):
    """_run_tts_and_merge_stage (the retry/regen/continue path) must
    re-render stems after placements — else solo/mute plays stale audio."""
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(app_pipeline, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(app_pipeline, "save_job", lambda job: None)
    monkeypatch.setattr(app_pipeline, "get_tts_engine", lambda: _fake_engine())
    monkeypatch.setattr(app_pipeline, "merge_audio_video", lambda *a, **k: None)
    monkeypatch.setattr(app_pipeline, "assemble_dubbed_audio",
                        lambda *a, **k: None)  # main mix not under test here
    work = tmp_path / JOB
    work.mkdir()
    a0 = _tone(work / "seg0.wav")
    state = {
        "duration": 4.0,
        "video_path": str(work / "source_video.mp4"),
        "target_lang": "ru",
        "effective_src": "en",
        "segments": [
            {"idx": 0, "speaker": "SPEAKER_00", "audio_path": a0,
             "start": 1.0, "end": 1.4, "text": "hi", "translated_text": "privet"},
        ],
    }
    job = {"id": JOB, "status": "synthesizing"}

    asyncio.run(app_pipeline._run_tts_and_merge_stage(
        job, work, state,
        voice_style="", voice_preset="auto", tts_speed="balanced",
        ref_path_override="",
        preserve_existing_audio_paths=True,   # all audio valid → no TTS
    ))

    stem = work / "stem_SPEAKER_00.wav"
    assert stem.exists(), "resume path must render stems"
    # use_recorded placement: clip lands at its source start (1.0s), not 0.
    s, sr = sf.read(str(stem))
    assert _rms(s[:int(0.8 * sr)]) < 1e-6
    assert _rms(s[int(1.05 * sr):int(1.35 * sr)]) > 0.1
    # save_placements wrote next to it (site 2 ordering: placements before stems)
    assert (work / "tts_placements.json").exists()


# ── site 3: editor timeline apply ─────────────────────────────────────
def test_timeline_apply_refreshes_stems(tmp_path, monkeypatch):
    """Dragging clips in the editor must move the stems too."""
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB, "status": "complete"}})
    monkeypatch.setattr(dub_routes, "save_job", lambda job: None)
    # Route-internal main mix + video merge are not under test; the refresh
    # inside the route calls the REAL assembler via refresh_speaker_stems.
    monkeypatch.setattr(dub_routes, "assemble_dubbed_audio", lambda *a, **k: None)
    monkeypatch.setattr(dub_routes, "merge_audio_video", lambda *a, **k: None)
    d = tmp_path / JOB
    d.mkdir()
    a0 = _tone(d / "seg0.wav")
    (d / "checkpoint_tts_done.json").write_text(json.dumps({
        "duration": 4.0,
        "sample_rate": SR,
        "video_path": str(d / "source_video.mp4"),
        "segments": [
            {"idx": 0, "speaker": "SPEAKER_00", "audio_path": a0,
             "start": 0.0, "end": 0.4, "text": "hi", "translated_text": "privet"},
        ],
    }), encoding="utf-8")

    r = client.post(f"/api/dub/{JOB}/timeline",
                    data={"placements": json.dumps([{"idx": 0, "start": 3.0}]),
                          "cuts": "[]"})

    assert r.status_code == 200, r.text
    stem = d / "stem_SPEAKER_00.wav"
    assert stem.exists(), "timeline apply must refresh the stem"
    s, sr = sf.read(str(stem))
    # dragged to 3.0s: silent before, audio at the NEW position
    assert _rms(s[:int(2.8 * sr)]) < 1e-6
    assert _rms(s[int(3.05 * sr):int(3.35 * sr)]) > 0.1


# ── export endpoint ──────────────────────────────────────────────────
def _seed(tmp_path, monkeypatch, sample_rate=SR):
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB, "status": "complete"}})
    d = tmp_path / JOB
    d.mkdir()
    a0 = _tone(d / "seg0.wav")
    a1 = _tone(d / "seg1.wav")
    (d / "checkpoint_tts_done.json").write_text(json.dumps({
        "duration": 4.0,
        "sample_rate": sample_rate,
        "segments": [
            {"idx": 0, "speaker": "SPEAKER_00", "audio_path": a0,
             "start": 0.0, "end": 0.4, "text": "Hola", "translated_text": "Hello"},
            {"idx": 1, "speaker": "SPEAKER_01", "audio_path": a1,
             "start": 2.0, "end": 2.4, "text": "Adios", "translated_text": "Bye"},
        ],
    }), encoding="utf-8")
    (d / "tts_placements.json").write_text(json.dumps([
        {"idx": 0, "src_start": 0.0, "src_end": 0.4,
         "dub_start": 1.0, "dub_end": 1.4},   # dragged right by 1s
        {"idx": 1, "src_start": 2.0, "src_end": 2.4,
         "dub_start": 2.0, "dub_end": 2.4},
    ]), encoding="utf-8")
    return d


def test_export_renders_writes_manifest_and_links(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)

    r = client.post(f"/api/dub/{JOB}/stems/export")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 2
    assert [s["speaker"] for s in body["stems"]] == ["SPEAKER_00", "SPEAKER_01"]
    assert all(s["url"].startswith(f"/api/dub/{JOB}/stem/") for s in body["stems"])
    assert body["manifest_url"] == f"/outputs/{JOB}/stems_manifest.json"
    for s in body["stems"]:
        assert (d / s["file"]).exists()

    manifest = json.loads((d / "stems_manifest.json").read_text(encoding="utf-8"))
    assert manifest["job_id"] == JOB
    assert manifest["duration"] == 4.0
    assert manifest["sample_rate"] == SR
    stems = {m["speaker"]: m for m in manifest["stems"]}
    # Clip 0 was dragged to 1.0 — manifest must report the DUB clock
    # (what an editor dropping the WAV at 0 needs), not the source time.
    assert stems["SPEAKER_00"]["clips"][0]["start"] == 1.0
    assert stems["SPEAKER_00"]["clips"][0]["end"] == 1.4
    assert stems["SPEAKER_00"]["clips"][0]["source_start"] == 0.0
    assert stems["SPEAKER_00"]["clips"][0]["text"] == "Hello"
    assert stems["SPEAKER_00"]["clips"][0]["original_text"] == "Hola"
    assert stems["SPEAKER_01"]["clips"][0]["start"] == 2.0
    # manifest written to the job folder (the /outputs URL it advertises is
    # served from the REAL OUTPUT_DIR, so assert on disk here)
    assert (d / "stems_manifest.json").exists()


def test_export_skips_stems_that_are_already_current(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    assembler.assemble_speaker_stems(
        [{"speaker": "SPEAKER_00", "audio_path": str(d / "seg0.wav"),
          "start": 1.0, "end": 1.4}], 4.0, d, sample_rate=SR, only="SPEAKER_00")
    keep = (d / "stem_SPEAKER_00.wav").stat().st_mtime_ns

    r = client.post(f"/api/dub/{JOB}/stems/export")

    assert r.status_code == 200
    # correct-rate existing stem untouched; missing one rendered
    assert (d / "stem_SPEAKER_00.wav").stat().st_mtime_ns == keep
    assert (d / "stem_SPEAKER_01.wav").exists()


def test_export_rerenders_stem_with_wrong_sample_rate(tmp_path, monkeypatch):
    """Old jobs' stems were rendered at 48k regardless of the job rate —
    shipping those with a 24k manifest would mislead every DAW import."""
    d = _seed(tmp_path, monkeypatch, sample_rate=24000)
    wrong = d / "stem_SPEAKER_00.wav"
    sf.write(str(wrong), np.zeros(int(0.1 * SR), dtype="float32"), SR)  # 8k file

    r = client.post(f"/api/dub/{JOB}/stems/export")

    assert r.status_code == 200
    assert sf.info(str(wrong)).samplerate == 24000


def test_export_error_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(dub_routes, "jobs", {})
    d = tmp_path / JOB
    d.mkdir()
    # unknown job (not in memory)
    assert client.post(f"/api/dub/{JOB}/stems/export").status_code == 404
    # known job, no tts_done checkpoint
    monkeypatch.setattr(dub_routes, "jobs", {JOB: {"id": JOB}})
    assert client.post(f"/api/dub/{JOB}/stems/export").status_code == 404
    assert client.get(f"/api/dub/{JOB}/stems").status_code == 404


def test_export_400_when_no_rendered_audio(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    cp = json.loads((d / "checkpoint_tts_done.json").read_text(encoding="utf-8"))
    cp["segments"][0]["audio_path"] = str(d / "gone.wav")
    cp["segments"][1]["audio_path"] = str(d / "gone2.wav")
    (d / "checkpoint_tts_done.json").write_text(json.dumps(cp), encoding="utf-8")
    r = client.post(f"/api/dub/{JOB}/stems/export")
    assert r.status_code == 400


def test_stems_list_reports_export_affordances(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    r = client.get(f"/api/dub/{JOB}/stems")
    assert r.status_code == 200
    body = r.json()
    assert body["export_url"] == f"/api/dub/{JOB}/stems/export"
    assert body["manifest_exists"] is False
    client.post(f"/api/dub/{JOB}/stems/export")
    assert client.get(f"/api/dub/{JOB}/stems").json()["manifest_exists"] is True
    assert d / "stems_manifest.json"
