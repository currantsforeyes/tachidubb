"""FireRedTTS3 engine (pipeline/synthesizer.py): discovery, spawn, protocol.

The engine runs a worker on **ComfyUI's Python**; these tests never touch
ComfyUI, the pack's model or a GPU. Instead a stub worker speaks the exact
event protocol (loading / loaded / segment / fatal / job_done over stdout,
next job path over stdin), which is what the engine's client loop is written
against — so spawn-vs-reuse, progress, sample-rate capture, fatal handling and
the sync/anchoring classification are all pinned without weights.

What is deliberately NOT faked: path discovery, the job file the engine
writes, and every decision it makes about segments (empty text, missing
reference, tts_speed -> flow steps).
"""
import json
import sys
from pathlib import Path

import pytest

from pipeline.synthesizer import (
    ANCHORED_TIERS,
    SYNC_ENGINES,
    FireRedTTSEngine,
    segments_anchored,
)

STUB_WORKER = r'''
import json, os, sys

def _log(event):
    print(json.dumps(event), flush=True)

def _record_launch():
    path = os.environ.get("STUB_LAUNCH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("launch\n")

def run(path):
    job = json.load(open(path, encoding="utf-8-sig"))
    mode = os.environ.get("STUB_MODE", "")
    _log({"event": "loading", "model": job["backend"].get("repo")})
    _log({"event": "loaded", "seconds": 0.01})
    if mode == "fatal":
        _log({"event": "fatal", "error": "stub exploded"})
    elif mode != "silent":
        for seg in job["segments"]:
            _log({"event": "segment", "idx": seg["idx"], "ok": True,
                  "path": seg["output"],
                  "sample_rate": int(os.environ.get("STUB_SR", 24000)),
                  "seconds": 0.01})
    _log({"event": "job_done"})

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "--daemon":
        sys.exit(2)
    _record_launch()          # once per process spawn, not per job served
    run(sys.argv[2])
    for line in sys.stdin:            # daemon: one job path per line
        line = line.strip()
        if line:
            run(line)
'''


@pytest.fixture
def stub(tmp_path):
    path = tmp_path / "stub_worker.py"
    path.write_text(STUB_WORKER, encoding="utf-8")
    return path


@pytest.fixture
def engine(tmp_path, stub, monkeypatch):
    """An engine wired to the stub worker instead of ComfyUI's runtime."""
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "loader.py").write_text("# stand-in for the pack's loader\n",
                                    encoding="utf-8")
    monkeypatch.delenv("TACHIDUBB_COMFY_ROOT", raising=False)
    eng = FireRedTTSEngine(comfy_root=tmp_path, pack_dir=pack,
                           python=sys.executable, worker=stub)
    launch_log = tmp_path / "launches.txt"
    monkeypatch.setenv("STUB_LAUNCH_LOG", str(launch_log))
    monkeypatch.setenv("STUB_MODE", "")
    eng._launch_log = launch_log
    yield eng
    eng.unload()


def _segments(*texts, speaker="SPEAKER_00"):
    return [{"idx": i, "speaker": speaker, "translated_text": text}
            for i, text in enumerate(texts)]


def _refs(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    return {"SPEAKER_00": str(ref)}


def _count_launches(engine):
    return (len(engine._launch_log.read_text(encoding="utf-8").splitlines())
            if engine._launch_log.exists() else 0)


# ── discovery ────────────────────────────────────────────────────────
def test_explicit_paths_resolve_and_load_passes(engine):
    engine.load()                       # must not raise: everything exists

    comfy, pack, python, worker = engine._paths()
    assert comfy == Path(engine.comfy_root)
    assert pack.name == "pack"
    assert python == Path(sys.executable)
    assert worker.name == "stub_worker.py"


def test_missing_pack_is_reported_with_the_install_hint(engine):
    (engine.pack_dir / "loader.py").unlink()

    with pytest.raises(RuntimeError, match="Install the pack"):
        engine.load()


def test_no_comfyui_anywhere_is_a_clear_error(tmp_path, stub, monkeypatch):
    monkeypatch.delenv("TACHIDUBB_COMFY_ROOT", raising=False)
    monkeypatch.setattr(FireRedTTSEngine, "COMFY_CANDIDATES", ())

    with pytest.raises(RuntimeError, match="TACHIDUBB_COMFY_ROOT"):
        FireRedTTSEngine(python=sys.executable, worker=stub)._paths()


def test_env_var_selects_the_comfy_root(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("TACHIDUBB_COMFY_ROOT", str(tmp_path))

    resolved = FireRedTTSEngine(python=sys.executable, worker=stub)._paths()

    assert resolved[0] == tmp_path


def test_comfy_root_without_a_python_is_reported(tmp_path, stub):
    with pytest.raises(RuntimeError, match="No Python interpreter"):
        FireRedTTSEngine(comfy_root=tmp_path, worker=stub)._paths()


# ── synthesis ────────────────────────────────────────────────────────
def test_synthesizes_every_segment_and_marks_them_anchored(engine, tmp_path):
    refs = _refs(tmp_path)
    segments = _segments("Hello", "World")
    progress = []

    out = engine.synthesize_segments(
        segments, str(tmp_path / "tts"), speaker_refs=refs,
        speaker_transcripts={"SPEAKER_00": "the reference transcript"},
        progress_callback=lambda done, total: progress.append((done, total)),
        target_lang="ru")

    assert [s["audio_path"] for s in out] == [
        str(tmp_path / "tts" / "seg_0000.wav"),
        str(tmp_path / "tts" / "seg_0001.wav"),
    ]
    # tts_tier is what segments_anchored() reads on later rebuilds.
    assert {s["tts_tier"] for s in out} == {"firered"}
    assert segments_anchored(out) is True
    assert progress and progress[-1] == (2, 2)
    assert engine.sample_rate == 24000          # captured from the segment event


def test_job_file_carries_the_backend_and_speed_mapping(engine, tmp_path):
    out_dir = tmp_path / "tts"

    engine.synthesize_segments(_segments("Hello"), str(out_dir),
                               speaker_refs=_refs(tmp_path),
                               speaker_transcripts={"SPEAKER_00": "the reference transcript"},
                               tts_speed="fast", target_lang="de")

    job = json.loads((out_dir / "_firered_tts_job.json").read_text(encoding="utf-8"))
    assert job["backend"]["comfy_root"] == str(engine.comfy_root)
    assert job["backend"]["repo"] == "FireRedTTS3-int8"
    # fast -> fewer flow-matching steps, balanced -> the official default.
    assert job["defaults"]["n_timesteps"] == 6
    seg = job["segments"][0]
    assert seg["language"] == "de"          # ISO in; the worker maps to the tag
    assert seg["text"] == "Hello"
    assert Path(seg["prompt_audio"]).exists()
    assert seg["prompt_text"] == "the reference transcript"


def test_empty_text_is_skipped_and_never_reaches_the_worker(
        engine, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "fatal")   # would fail if it were called
    segments = [{"idx": 0, "speaker": "SPEAKER_00", "translated_text": ""}]

    out = engine.synthesize_segments(segments, str(tmp_path / "tts"),
                                     speaker_refs=_refs(tmp_path),
                                     target_lang="en")

    assert out[0]["audio_path"] is None
    assert not (tmp_path / "tts" / "_firered_tts_job.json").exists()


def test_a_reference_voice_is_required(engine, tmp_path):
    with pytest.raises(RuntimeError, match="reference voice"):
        engine.synthesize_segments(_segments("Hi"), str(tmp_path / "tts"),
                                   speaker_refs={})


def test_a_fatal_event_becomes_an_error(engine, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "fatal")

    with pytest.raises(RuntimeError, match="stub exploded"):
        engine.synthesize_segments(_segments("Hi"), str(tmp_path / "tts"),
                                   speaker_refs=_refs(tmp_path), target_lang="en")


def test_the_worker_is_spawned_once_and_then_reused(engine, tmp_path):
    refs = _refs(tmp_path)
    out_dir = str(tmp_path / "tts")

    engine.synthesize_segments(_segments("one"), out_dir, speaker_refs=refs,
                               target_lang="en")
    assert _count_launches(engine) == 1, "first call must spawn the daemon"

    engine.synthesize_segments(_segments("two"), out_dir, speaker_refs=refs,
                               target_lang="en")
    assert _count_launches(engine) == 1, \
        "the loaded bundle must be reused, not paid for again"

    engine.unload()                        # kill the idle daemon
    assert engine._worker_proc is None


def test_a_dead_worker_is_respawned(engine, tmp_path):
    refs = _refs(tmp_path)
    out_dir = str(tmp_path / "tts")

    engine.synthesize_segments(_segments("one"), out_dir, speaker_refs=refs,
                               target_lang="en")
    engine._worker_proc.kill()
    engine._worker_proc.wait(timeout=30)

    engine.synthesize_segments(_segments("two"), out_dir, speaker_refs=refs,
                               target_lang="en")

    assert _count_launches(engine) == 2, "a dead daemon must not be reused"
    engine.unload()


# ── classification shared with the rest of the pipeline ──────────────
def test_firered_is_a_sync_anchoring_engine():
    assert isinstance(FireRedTTSEngine(), SYNC_ENGINES)
    assert FireRedTTSEngine.anchors_to_slots is True


def test_segments_anchored_reads_the_persisted_tier():
    assert segments_anchored([{"tts_tier": "firered"}]) is True
    assert segments_anchored([{"tts_tier": "qwen3-xvector"}]) is True
    assert segments_anchored([{"tts_tier": "voxcpm2"}]) is False
    assert segments_anchored([{"tts_tier": None}]) is False
    assert segments_anchored([]) is False
    assert segments_anchored(None) is False
    assert all(t in ("qwen3", "firered") for t in ANCHORED_TIERS)
