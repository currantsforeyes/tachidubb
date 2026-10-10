"""FireRedTTS3 worker (pipeline/firered_worker.py): protocol, job handling,
language mapping and reference caching â€” with the model faked.

What matters here is everything *around* the model: that the daemon speaks the
same event protocol the engine's client loop reads, that an ISO code becomes the
language tag FireRedTTS3 validates against, that one reference clip is encoded
once per job (CAM++ + latents are the expensive part), and that a bad segment
is reported as fatal instead of killing the daemon.

The real bundle is never loaded: ComfyUI's Python, comfy.* and the weights all
stay out of these tests.
"""
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

# CI (requirements-dev.txt) is deliberately torch-free; this module needs the
# real tensor path, so it runs where torch exists and skips where it does not.
torch = pytest.importorskip("torch")

from pipeline import firered_worker as fw  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LANGS_JS = ROOT / "frontend" / "src" / "constants.js"


# â”€â”€ fakes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class FakeNative:
    """Stands in for the pack's native module."""

    def __init__(self, audio_seconds=0.1):
        self.prompt_calls = 0
        self.spk_calls = 0
        self.clone_calls = []
        self._samples = int(audio_seconds * 16000)

    def tokenize_prompt_audio(self, bundle, audio, sr):
        self.prompt_calls += 1
        return f"latents:{audio.shape[-1]}", audio.shape[-1] // 2

    def speaker_embedding(self, bundle, audio, sr):
        self.spk_calls += 1
        return "spk-embedding"

    def base_clone_one(self, bundle, **kwargs):
        self.clone_calls.append(kwargs)
        return torch.zeros(1, self._samples), 16000


@pytest.fixture
def native():
    return FakeNative()


def _reference(tmp_path, name="ref.wav", channels=1):
    path = tmp_path / name
    frames = 3200
    data = (0.1 * np.ones((frames, channels))).astype("float32")
    sf.write(str(path), data, 16000)
    return str(path)


def _job(tmp_path, *, language="ru", segments=None):
    ref = _reference(tmp_path)
    out = tmp_path / "tts"
    if segments is None:
        segments = [
            {"idx": 0, "text": "Hello there", "language": language,
             "prompt_audio": ref, "prompt_text": "",
             "output": str(out / "seg_0000.wav")},
            {"idx": 1, "text": "And again", "language": language,
             "prompt_audio": ref, "prompt_text": "",
             "output": str(out / "seg_0001.wav")},
        ]
    return {
        "backend": {"repo": "FireRedTTS3-int8", "variant": "fireredtts3_base"},
        "defaults": {"n_timesteps": 7, "inference_cfg": 1.5,
                     "stop_threshold": 0.4, "seed": 99},
        "segments": segments,
    }


def _events(capsys):
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines()
            if line.strip().startswith("{")]


# â”€â”€ language mapping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_language_tags_cover_every_language_the_app_offers():
    """A language added to the UI must not silently be undubbable here."""
    text = LANGS_JS.read_text(encoding="utf-8")
    app = dict(re.findall(r"\{\s*c:\s*'([a-z-]+)',\s*n:\s*'([^']+)'\s*\}", text))
    app = {c: n for c, n in app.items() if c != "auto"}

    assert set(app) <= set(fw.LANGUAGE_TAGS), \
        f"missing tags: {set(app) - set(fw.LANGUAGE_TAGS)}"


def test_language_tag_maps_iso_to_firered_tag():
    assert fw.language_tag("ru") == "Russian"
    assert fw.language_tag("EN") == "English"
    assert fw.language_tag("zh") == "Chinese"


def test_language_tag_rejects_unknown_and_auto():
    with pytest.raises(ValueError, match="no tag for language"):
        fw.language_tag("auto")
    with pytest.raises(ValueError, match="no tag for language"):
        fw.language_tag("xx")


# â”€â”€ reference audio â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_reference_audio_is_becomes_one_channel(tmp_path):
    path = tmp_path / "stereo.wav"
    data = np.zeros((4800, 2), dtype="float32")
    data[:, 0] = 0.5
    data[:, 1] = -0.5
    sf.write(str(path), data, 24000)

    waveform, sr = fw.load_reference_audio(path)

    assert waveform.ndim == 2 and waveform.shape[0] == 1  # (1, T)
    assert waveform.shape[1] == 4800
    assert sr == 24000


def test_empty_reference_is_rejected(tmp_path):
    path = tmp_path / "empty.wav"
    sf.write(str(path), np.zeros(0, dtype="float32"), 16000)

    with pytest.raises(ValueError, match="empty"):
        fw.load_reference_audio(path)


# â”€â”€ one job â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_run_job_writes_every_clip_and_reports_progress(tmp_path, native, capsys):
    job = _job(tmp_path)

    fw.run_job(job, native, "bundle")

    for i in range(2):
        clip = tmp_path / "tts" / f"seg_000{i}.wav"
        assert clip.is_file()
        assert sf.info(str(clip)).duration > 0

    events = _events(capsys)
    assert [e["event"] for e in events] == ["segment", "segment"]
    assert [e["idx"] for e in events] == [0, 1]
    assert all(e["ok"] for e in events)


def test_reference_is_encoded_once_for_a_shared_clip(tmp_path, native, capsys):
    fw.run_job(_job(tmp_path), native, "bundle")

    # Both segments use the same speaker clip: latents + CAM++ run once.
    assert native.prompt_calls == 1
    assert native.spk_calls == 1
    assert len(native.clone_calls) == 2


def test_iso_code_becomes_the_tag_the_model_validates(tmp_path, native, capsys):
    fw.run_job(_job(tmp_path, language="ru"), native, "bundle")
    fw.run_job(_job(tmp_path, language="de"), native, "bundle")

    assert native.clone_calls[0]["language"] == "Russian"
    assert native.clone_calls[2]["language"] == "German"


def test_generation_defaults_reach_the_model(tmp_path, native, capsys):
    fw.run_job(_job(tmp_path), native, "bundle")

    call = native.clone_calls[0]
    assert call["n_timesteps"] == 7
    assert call["inference_cfg"] == 1.5
    assert call["stop_threshold"] == 0.4
    assert call["seed"] == 99
    assert call["text"] == "Hello there"


def test_segment_without_a_reference_clip_is_rejected(tmp_path, native):
    segments = [{"idx": 0, "text": "hi", "language": "en", "prompt_audio": "",
                 "output": str(tmp_path / "x.wav")}]

    with pytest.raises(ValueError, match="no prompt_audio"):
        fw.run_job({"segments": segments}, native, "bundle")


def test_generation_budget_is_anchored_to_the_source_window():
    """Regression: a 1.02s window ran to the model's 400-step (64s) ceiling.

    That 64s clip was then placed in a 1.02s slot and sat underneath the rest
    of the dub as ~10s of double speech. The budget now comes from the window.
    """
    assert fw.max_gen_steps_for(1.02) == 13      # was 400 (64s of audio)
    assert fw.max_gen_steps_for(0.1) >= 6        # tiny fragments still speak
    assert fw.max_gen_steps_for(9.0) > 100       # long windows keep room
    assert fw.STEPS_PER_SECOND == 6.25           # 25 latent frames / 4 latents


def test_run_job_passes_the_window_budget_to_the_model(tmp_path, native, capsys):
    job = _job(tmp_path)
    job["segments"][0]["slot_seconds"] = 1.02
    job["segments"][1]["slot_seconds"] = 9.09

    fw.run_job(job, native, "bundle")

    steps = [c["max_gen_steps"] for c in native.clone_calls]
    assert steps == [fw.max_gen_steps_for(1.02), fw.max_gen_steps_for(9.09)]


def test_segment_event_reports_audio_length_and_overrun(tmp_path, capsys):
    long_native = FakeNative(audio_seconds=5.0)
    job = _job(tmp_path)
    job["segments"][0]["slot_seconds"] = 1.0

    fw.run_job(job, long_native, "bundle")

    events = _events(capsys)          # read once: readouterr() drains
    first = events[0]
    assert first["audio_seconds"] == 5.0
    assert first["overrun"] == 4.0, "an overrun must be surfaced, not hidden"
    # Second segment has no slot, so no overrun can be judged for it.
    assert "overrun" not in events[1]


def test_job_without_segments_is_rejected(tmp_path, native):
    with pytest.raises(ValueError, match="no segments"):
        fw.run_job({"segments": []}, native, "bundle")


# â”€â”€ daemon protocol â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_daemon_serves_the_first_job_then_next_on_stdin(tmp_path, native,
                                                        capsys, monkeypatch):
    job_a, job_b = tmp_path / "a.json", tmp_path / "b.json"
    job_a.write_text(json.dumps(_job(tmp_path)), encoding="utf-8")
    job_b.write_text(json.dumps(_job(tmp_path, language="fr")), encoding="utf-8")
    monkeypatch.setattr(fw, "_load_backend", lambda cfg: (native, "bundle"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{job_b}\n"))

    fw.main_daemon(str(job_a))

    events = _events(capsys)
    names = [e["event"] for e in events]
    # job_done delimits each job â€” that is what the engine's client loop waits on.
    assert names.count("job_done") == 2
    assert names.index("loading") < names.index("loaded")
    assert names.index("loaded") < names.index("segment")
    # Second job ran with French, proving stdin fed a whole new job through.
    fr = [c for c in native.clone_calls if c["language"] == "French"]
    assert fr, "the job handed in on stdin never reached the model"


def test_daemon_reports_a_fatal_but_stays_alive_for_the_next_job(
        tmp_path, native, capsys, monkeypatch):
    bad = {"segments": [{"idx": 0, "text": "x", "language": "en",
                         "prompt_audio": "", "output": str(tmp_path / "x.wav")}]}
    good = _job(tmp_path)
    bad_path, good_path = tmp_path / "bad.json", tmp_path / "good.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    good_path.write_text(json.dumps(good), encoding="utf-8")
    monkeypatch.setattr(fw, "_load_backend", lambda cfg: (native, "bundle"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{good_path}\n"))

    fw.main_daemon(str(bad_path))

    events = _events(capsys)
    names = [e["event"] for e in events]
    assert "fatal" in names, "a bad job must be reported, not raised"
    assert names.index("fatal") < names.index("job_done")
    # The daemon survived the failure and served the good job afterwards.
    assert names.count("job_done") == 2
    assert any(c["language"] == "Russian" for c in native.clone_calls), \
        "the good job handed in on stdin never reached the model"


def test_backend_paths_are_validated_before_any_model_load(tmp_path):
    with pytest.raises(FileNotFoundError, match="required path missing"):
        fw._load_backend({"comfy_root": str(tmp_path / "nope"),
                          "pack_dir": str(tmp_path / "also-nope")})
