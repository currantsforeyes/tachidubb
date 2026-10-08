"""Per-speaker stems: derived from existing clips, placed at recorded times."""
import numpy as np
import soundfile as sf

from pipeline.assembler import assemble_speaker_stems, speakers_in_segments

SR = 8000


def _tone(path, seconds, freq=440.0):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * freq * t)).astype("float32"), SR)
    return str(path)


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def test_speakers_in_segments_ignores_missing_audio(tmp_path):
    good = _tone(tmp_path / "good.wav", 0.2)
    segs = [
        {"speaker": "SPEAKER_00", "audio_path": str(tmp_path / "gone.wav")},
        {"speaker": "SPEAKER_01", "audio_path": good},
    ]
    assert speakers_in_segments(segs) == ["SPEAKER_01"]


def test_stems_place_each_speaker_in_its_own_window(tmp_path):
    a0 = _tone(tmp_path / "a0.wav", 0.5)
    a1 = _tone(tmp_path / "a1.wav", 0.5, freq=660.0)
    segs = [
        {"speaker": "SPEAKER_00", "audio_path": a0, "start": 1.0, "end": 1.5,
         "placed_start": 1.0, "placed_end": 1.5},
        {"speaker": "SPEAKER_01", "audio_path": a1, "start": 3.0, "end": 3.5,
         "placed_start": 3.0, "placed_end": 3.5},
    ]

    paths = assemble_speaker_stems(segs, 5.0, tmp_path, sample_rate=SR)
    assert set(paths) == {"SPEAKER_00", "SPEAKER_01"}

    s0, _ = sf.read(str(paths["SPEAKER_00"]))
    s1, _ = sf.read(str(paths["SPEAKER_01"]))

    # SPEAKER_00 speaks at 1.0-1.5s only
    assert _rms(s0[int(1.05 * SR):int(1.45 * SR)]) > 0.1
    assert _rms(s0[:int(0.9 * SR)]) < 1e-6

    # SPEAKER_01 speaks at 3.0-3.5s only
    assert _rms(s1[int(3.05 * SR):int(3.45 * SR)]) > 0.1
    assert _rms(s1[:int(2.9 * SR)]) < 1e-6


def test_stem_uses_recorded_placement_not_source_start(tmp_path):
    """The clip was shifted to 2.0s in the dub, so the stem must be too."""
    a = _tone(tmp_path / "a.wav", 0.5)
    segs = [{"speaker": "SPEAKER_00", "audio_path": a, "start": 0.0, "end": 0.5,
             "placed_start": 2.0, "placed_end": 2.5}]

    paths = assemble_speaker_stems(segs, 4.0, tmp_path, sample_rate=SR)
    s, _ = sf.read(str(paths["SPEAKER_00"]))

    assert len(s) >= int(2.4 * SR)                       # extended past 2.0s
    assert _rms(s[:int(1.9 * SR)]) < 1e-6                # nothing at source 0
    assert _rms(s[int(2.05 * SR):int(2.45 * SR)]) > 0.1


def test_stems_only_renders_requested_speaker(tmp_path):
    a0 = _tone(tmp_path / "a0.wav", 0.2)
    a1 = _tone(tmp_path / "a1.wav", 0.2)
    segs = [
        {"speaker": "SPEAKER_00", "audio_path": a0, "start": 0.0, "end": 0.2,
         "placed_start": 0.0, "placed_end": 0.2},
        {"speaker": "SPEAKER_01", "audio_path": a1, "start": 0.3, "end": 0.5,
         "placed_start": 0.3, "placed_end": 0.5},
    ]
    paths = assemble_speaker_stems(segs, 1.0, tmp_path, sample_rate=SR, only="SPEAKER_01")
    assert set(paths) == {"SPEAKER_01"}


def test_stems_span_the_whole_timeline(tmp_path):
    """A stem is dropped at t=0, so it must be as long as the timeline.

    It used to be trimmed to 0.5s after that speaker's own last clip —
    SPEAKER_01's stem was 1.0s in a 5.0s job — so the track ended mid-video
    and stems no longer lined up with dubbed_audio.wav.
    """
    a0 = _tone(tmp_path / "a0.wav", 0.3)
    a1 = _tone(tmp_path / "a1.wav", 0.3, freq=660.0)
    segs = [
        {"speaker": "SPEAKER_00", "audio_path": a0, "start": 0.0, "end": 0.3,
         "placed_start": 0.0, "placed_end": 0.3},
        {"speaker": "SPEAKER_01", "audio_path": a1, "start": 0.3, "end": 0.6,
         "placed_start": 0.3, "placed_end": 0.6},
    ]

    paths = assemble_speaker_stems(segs, 5.0, tmp_path, sample_rate=SR)

    for path in paths.values():
        assert sf.info(str(path)).frames == int(5.0 * SR), \
            f"{path.name} must span the whole timeline, not just its own clips"

    s1, _ = sf.read(str(paths["SPEAKER_01"]))
    assert _rms(s1[:int(0.25 * SR)]) < 1e-6        # silence before they speak
    assert _rms(s1[int(1.0 * SR):]) < 1e-6         # silence after, to the end
    assert len(s1) == int(5.0 * SR)