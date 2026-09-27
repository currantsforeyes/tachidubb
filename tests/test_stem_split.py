"""Stem split runs FIRST, for every job (pipeline/audio.build_speech_track).

Regression this pins: separation used to sit behind the ``keep_bg`` flag and
after transcription prep, so Whisper read the raw full mix (music, crowd),
and on machines without a separator "keep background" silently did nothing.
Now the vocals stem is the ASR input for every job, ``keep_bg`` only decides
whether the background stem is mixed under the final dub, and a missing
separator degrades to the full mix instead of failing.
"""
import shutil
from pathlib import Path

import pytest

import pipeline.audio as audio_mod
from pipeline.models import check_separator


def _touch(path: Path) -> str:
    path.write_bytes(b"RIFFfake")
    return str(path)


def test_separator_available_returns_bool():
    assert isinstance(audio_mod._separator_available(), bool)


def test_check_separator_reports_ok_flag():
    assert set(check_separator()) & {"ok", "hint", "error"}


def test_no_separator_falls_back_to_full_mix(tmp_path, monkeypatch):
    """Without demucs/audio-separator: full mix, no background, no work."""
    monkeypatch.setattr(audio_mod, "_separator_available", lambda: False)
    calls = []
    monkeypatch.setattr(audio_mod, "extract_audio_hq",
                        lambda *a: calls.append("extract") or _touch(tmp_path / "hq.wav"))

    full_mix = _touch(tmp_path / "audio_16k.wav")
    speech, bg = audio_mod.build_speech_track(
        "video.mp4", str(tmp_path), full_mix, keep_bg=True)

    assert speech == full_mix
    assert bg == ""
    assert calls == []  # no wasted HQ extraction


def test_stem_split_runs_even_without_keep_bg(tmp_path, monkeypatch):
    """keep_bg=False must NOT skip separation — the stem IS the ASR input."""
    monkeypatch.setattr(audio_mod, "_separator_available", lambda: True)
    monkeypatch.setattr(audio_mod, "extract_audio_hq",
                        lambda video, dst: _touch(Path(dst)))
    monkeypatch.setattr(audio_mod, "_downsample_16k_mono",
                        lambda src, dst: _touch(Path(dst)))
    separated = []
    def fake_separate(audio_path, output_dir):
        separated.append(audio_path)
        _touch(Path(output_dir) / "vocals.wav")
        _touch(Path(output_dir) / "background.wav")
        return str(Path(output_dir) / "vocals.wav"), str(Path(output_dir) / "background.wav")
    monkeypatch.setattr(audio_mod, "separate_background", fake_separate)

    full_mix = _touch(tmp_path / "audio_16k.wav")
    speech, bg = audio_mod.build_speech_track(
        "video.mp4", str(tmp_path), full_mix, keep_bg=False)

    assert len(separated) == 1                    # separation ran
    assert speech == str(tmp_path / "audio_speech.wav")
    assert Path(speech).exists()                  # downsampled stem is the ASR input
    assert bg == ""                               # ...but nothing mixed under the dub


def test_keep_bg_returns_background_stem(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_mod, "_separator_available", lambda: True)
    monkeypatch.setattr(audio_mod, "extract_audio_hq",
                        lambda video, dst: _touch(Path(dst)))
    monkeypatch.setattr(audio_mod, "_downsample_16k_mono",
                        lambda src, dst: _touch(Path(dst)))
    def fake_separate(audio_path, output_dir):
        _touch(Path(output_dir) / "vocals.wav")
        bg = Path(output_dir) / "background.wav"
        _touch(bg)
        return str(Path(output_dir) / "vocals.wav"), str(bg)
    monkeypatch.setattr(audio_mod, "separate_background", fake_separate)

    full_mix = _touch(tmp_path / "audio_16k.wav")
    speech, bg = audio_mod.build_speech_track(
        "video.mp4", str(tmp_path), full_mix, keep_bg=True)

    assert speech == str(tmp_path / "audio_speech.wav")
    assert bg == str(tmp_path / "background.wav")


def test_separation_failure_degrades_to_full_mix(tmp_path, monkeypatch):
    """A broken separator must not kill the job — full mix, no background."""
    monkeypatch.setattr(audio_mod, "_separator_available", lambda: True)
    def boom(video, dst):
        raise RuntimeError("cuda OOM")
    monkeypatch.setattr(audio_mod, "extract_audio_hq", boom)

    full_mix = _touch(tmp_path / "audio_16k.wav")
    speech, bg = audio_mod.build_speech_track(
        "video.mp4", str(tmp_path), full_mix, keep_bg=True)

    assert speech == full_mix
    assert bg == ""


@pytest.mark.skipif(shutil.which("ffmpeg") is None,
                    reason="ffmpeg required for the downsample")
def test_downsample_produces_16k_mono(tmp_path):
    """The stem arrives as 44.1kHz stereo from demucs; ASR needs 16k mono."""
    import subprocess
    import soundfile as sf

    src = tmp_path / "stereo44.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ar", "44100", "-ac", "2", str(src)],
        check=True, capture_output=True, timeout=60,
    )
    dst = tmp_path / "speech16k.wav"
    audio_mod._downsample_16k_mono(str(src), str(dst))

    info = sf.info(str(dst))
    assert info.samplerate == 16000
    assert info.channels == 1
    assert info.frames / info.samplerate == pytest.approx(1.0, abs=0.05)
