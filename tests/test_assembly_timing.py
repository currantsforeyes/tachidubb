"""Placement timing: filling the window the line was translated for.

`assemble_dubbed_audio` has always compensated for TTS that comes out LONGER
than its subtitle window (speed it up, capped). The far more common case is
TTS that comes out SHORTER — measured across 30 recent segments, 77% were
short — which used to leave a hole: the voice stopped while the character was
still talking, and with fit_to_slots nothing ever closed the gap.

These pin the undertime branch and its quality cap: fill mildly
(UNDERTIME_MAX_SLOWDOWN), never slow a clip all the way to the window if that
would sound drawn out, and leave the overlong branch alone.
"""
import shutil

import numpy as np
import pytest
import soundfile as sf

from pipeline.assembler import UNDERTIME_MAX_SLOWDOWN, assemble_dubbed_audio

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="time-stretching goes through ffmpeg atempo",
)

SR = 8000


def _tone(path, seconds, freq=440.0):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * freq * t)).astype("float32"), SR)
    return str(path)


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def _duration(path):
    info = sf.info(str(path))
    return info.frames / info.samplerate


def _assemble(tmp_path, tts_seconds, slot_seconds, name="mix.wav"):
    """One segment: `tts_seconds` of speech in a `slot_seconds` window."""
    clip = _tone(tmp_path / f"{name}.clip.wav", tts_seconds)
    segs = [{"speaker": "SPEAKER_00", "audio_path": clip,
             "start": 0.0, "end": slot_seconds}]
    out = tmp_path / name
    assemble_dubbed_audio(segs, 4.0, str(out), sample_rate=SR,
                          apply_loudnorm=False)
    return out


def test_undertime_clip_is_stretched_over_the_hole_it_used_to_leave(tmp_path):
    # 0.40s of speech inside a 0.90s window: the original line runs to 0.90s,
    # so the voice used to stop at 0.40s and leave 0.50s of dead air.
    out = _assemble(tmp_path, tts_seconds=0.40, slot_seconds=0.90)

    x, sr = sf.read(str(out), dtype="float32")
    # Needs 2.25x slowdown to fill -> capped at 1.35x -> ~0.54s of audio.
    assert _rms(x[int(0.50 * sr):int(0.53 * sr)]) > 0.01, \
        "the window's tail should no longer be silent"
    assert _duration(out) > 0.40 + 0.5, "clip must have been made longer"


def test_undertime_stretch_stops_at_the_quality_cap(tmp_path):
    # Filling this window would take a 3.0x slowdown, which sounds drawn out.
    # The clip may grow to tts * 1.35 and no further.
    out = _assemble(tmp_path, tts_seconds=0.40, slot_seconds=1.20)

    dur = _duration(out)
    assert dur == pytest.approx(0.40 * UNDERTIME_MAX_SLOWDOWN + 0.5, abs=0.08)
    assert dur < 1.20, "must not slow the clip all the way to the window"


def test_overlong_clip_is_still_sped_up(tmp_path):
    # Regression guard: the pre-existing branch is untouched by the undertime
    # one. 1.00s in a 0.60s window -> atempo 1.15 (its cap) -> ~0.87s, so the
    # assembled track is 0.87 + the usual 0.5s tail.
    out = _assemble(tmp_path, tts_seconds=1.00, slot_seconds=0.60)

    dur = _duration(out)
    assert dur == pytest.approx(1.00 / 1.15 + 0.5, abs=0.08)
    assert dur < 1.00 + 0.5, "overlong audio must still be compressed"


def test_clip_that_already_fills_its_window_is_untouched(tmp_path):
    # Exactly on time: neither branch may fire (no pointless ffmpeg call, no
    # tempo drift on a segment that was already right).
    out = _assemble(tmp_path, tts_seconds=0.50, slot_seconds=0.50)

    assert _duration(out) == pytest.approx(0.50 + 0.5, abs=0.03)
