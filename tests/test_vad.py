"""VAD time-compression mapping (pipeline/vad.py).

The regression this pins: apply_vad_filter concatenates speech regions
(``atrim`` + ``concat``), so Whisper timestamps come back on the *compressed*
clock. Placed against the source video as-is, speech lands early — measured
on real job e0d2cc05 at -1.30s to -1.61s per segment.

REAL_REGIONS/REAL_CASES are the actual numbers from that job: 26.96s of
source audio filtered to 22.24s of speech, with segment starts drifting up
to 1.6s once placed. The regions are stored rounded to 2dp (as printed by
the probe), so assertions against them use abs=0.05 — 26x tighter than the
1.3s bug being guarded.
"""
import shutil
from pathlib import Path

import pytest

import pipeline.vad as vad

# Padded+merged speech regions of outputs/e0d2cc05/audio_16k.wav (original
# clock) — exactly what apply_vad_filter's atrim/concat consumed.
REAL_REGIONS = [
    (0.06, 4.10),
    (4.73, 6.63),
    (7.01, 8.16),
    (8.38, 13.63),
    (13.79, 16.29),
    (16.45, 19.71),
    (20.80, 24.93),
]

# (VAD-compressed segment start, original-video time) measured end-to-end.
REAL_CASES = [
    (0.07, 0.13),
    (7.26, 8.56),
    (8.94, 10.24),
    (10.52, 11.82),
    (13.75, 15.20),
    (14.93, 16.54),
]


# ── map_time ─────────────────────────────────────────────────────────
def test_map_time_identity_without_regions():
    """No compression (VAD skipped/dense/failed) => timestamps untouched."""
    assert vad.map_time(12.34, None) == 12.34
    assert vad.map_time(12.34, []) == 12.34


def test_map_time_matches_real_job_measurements():
    for vad_t, orig_t in REAL_CASES:
        got = vad.map_time(vad_t, REAL_REGIONS)
        assert got == pytest.approx(orig_t, abs=0.05), (
            f"VAD time {vad_t} mapped to {got}, expected {orig_t} "
            f"— speech would land {got - orig_t:+.2f}s off against the video"
        )


def test_map_time_preserves_offsets_within_a_region():
    # Region 1 starts at 0.06 (0.1s pad); +1.0s into the VAD file stays +1.0s.
    assert vad.map_time(1.06, REAL_REGIONS) == pytest.approx(1.12)
    # Near the end of region 1 the offset still tracks linearly.
    assert vad.map_time(4.03, REAL_REGIONS) == pytest.approx(4.09)


def test_map_time_reinserts_the_gap_for_cross_gap_segments():
    # 5.50 sits near the end of region 2, 6.00 just inside region 3 — the
    # 0.63s of silence VAD removed between them (4.10 -> 4.73) must come
    # back when a segment spans it: the video really does contain it.
    start = vad.map_time(5.50, REAL_REGIONS)
    end = vad.map_time(6.00, REAL_REGIONS)
    assert start == pytest.approx(6.19, abs=0.05)
    assert end == pytest.approx(7.07, abs=0.05)
    # Mapped duration exceeds the compressed duration by the removed gap.
    assert (end - start) > (6.00 - 5.50) + 0.3


def test_map_time_clamps_past_the_end_of_speech():
    # Whisper can report an end slightly beyond the file (22.255 vs the VAD
    # file's 22.236): clamp to the last speech end, never extrapolate.
    assert vad.map_time(22.255, REAL_REGIONS) == pytest.approx(24.93)
    assert vad.map_time(99.0, REAL_REGIONS) == pytest.approx(24.93)


# ── restore_original_times ───────────────────────────────────────────
def test_restore_is_a_noop_without_regions():
    segs = [{"start": 7.26, "end": 8.88, "text": "x"}]
    out = vad.restore_original_times(segs, None)
    assert out[0]["start"] == 7.26 and out[0]["end"] == 8.88


def test_restore_remaps_segments_and_words():
    segs = [{
        "start": 7.26, "end": 8.88, "text": "privet mir",
        "speaker": "SPEAKER_00", "idx": 1,
        "words": [
            {"word": "privet", "start": 7.30, "end": 7.50},
            {"word": "mir", "start": None, "end": None},  # alignment drops these
        ],
    }]
    out = vad.restore_original_times(segs, REAL_REGIONS)[0]

    # Start/end moved to the original clock (measured values).
    assert out["start"] == pytest.approx(8.56, abs=0.05)
    assert out["end"] == pytest.approx(10.17, abs=0.05)
    # Non-timing fields untouched.
    assert out["text"] == "privet mir"
    assert out["speaker"] == "SPEAKER_00"
    assert out["idx"] == 1
    # Words remapped; missing word timings survive as None.
    assert out["words"][0]["start"] == pytest.approx(8.59, abs=0.05)
    assert out["words"][0]["word"] == "privet"
    assert out["words"][1]["start"] is None
    assert out["words"][1]["end"] is None


def test_restore_keeps_ordering_monotonic():
    segs = [
        {"start": 0.07, "end": 7.22},
        {"start": 7.26, "end": 8.88},
        {"start": 14.93, "end": 22.25},
    ]
    out = vad.restore_original_times(segs, REAL_REGIONS)
    starts = [s["start"] for s in out]
    ends = [s["end"] for s in out]
    assert starts == sorted(starts)
    assert ends == sorted(ends)
    assert all(e >= s for s, e in zip(starts, ends))


# ── apply_vad_filter return contract ─────────────────────────────────
def _write_wav(path: Path, seconds: float = 10.0, rate: int = 16000):
    import numpy as np
    import soundfile as sf
    sf.write(str(path), np.zeros(int(seconds * rate), dtype=np.float32), rate)
    return path


def test_vad_no_speech_keeps_timeline(tmp_path, monkeypatch):
    """No Silero / no detections => copy unchanged, regions=None (no remap)."""
    src = _write_wav(tmp_path / "in.wav")
    monkeypatch.setattr(vad, "get_speech_timestamps", lambda *a, **k: [])

    out, ratio, regions = vad.apply_vad_filter(str(src), str(tmp_path / "out.wav"))

    assert regions is None
    assert ratio == 1.0
    assert Path(out).exists()


def test_vad_dense_audio_skips_filter(tmp_path, monkeypatch):
    """Speech >90% of the file => copy unchanged. regions MUST be None even
    though regions were detected — the file was not compressed, so mapping
    timestamps through the regions would corrupt them."""
    src = _write_wav(tmp_path / "in.wav", seconds=10.0)
    monkeypatch.setattr(vad, "_get_duration_ffprobe", lambda p: 10.0)
    monkeypatch.setattr(vad, "get_speech_timestamps",
                        lambda *a, **k: [{"start": 0.0, "end": 9.6}])

    out, ratio, regions = vad.apply_vad_filter(str(src), str(tmp_path / "out.wav"))

    assert regions is None
    assert ratio > 0.9
    assert Path(out).exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None,
                    reason="ffmpeg required for the compression path")
def test_vad_compression_returns_original_clock_regions(tmp_path, monkeypatch):
    """The compressed output ships the regions that map it back home.

    This is the invariant the whole fix rests on: whatever atrim+concat
    produced, the returned regions describe it in ORIGINAL time.
    """
    src = _write_wav(tmp_path / "in.wav", seconds=10.0)
    monkeypatch.setattr(vad, "_get_duration_ffprobe", lambda p: 10.0)
    # Two speech bursts with a removed gap between them (0.1s pad applies).
    monkeypatch.setattr(
        vad, "get_speech_timestamps",
        lambda *a, **k: [
            {"start": 0.5, "end": 2.0},
            {"start": 4.0, "end": 6.0},
        ],
    )

    out, ratio, regions = vad.apply_vad_filter(str(src), str(tmp_path / "out.wav"))

    # Padded by SEGMENT_PAD (0.1), clamped to bounds, gap preserved:
    assert regions == pytest.approx([(0.4, 2.1), (3.9, 6.1)])
    assert 0.3 < ratio < 0.6

    # The output is the concatenation: ~3.9s of speech from a 10s input.
    import soundfile as sf
    info = sf.info(out)
    assert info.frames / info.samplerate == pytest.approx(3.9, abs=0.1)

    # Round-trip: positions in the compressed output map back into the
    # original speech regions (this is what the pipeline does per segment).
    assert vad.map_time(0.0, regions) == pytest.approx(0.4)
    assert vad.map_time(2.7, regions) == pytest.approx(4.9)
