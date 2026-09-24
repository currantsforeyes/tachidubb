"""Waveform peak envelope used by the dialogue editor's lanes."""
import numpy as np
import soundfile as sf

from pipeline.media import waveform_peaks


def _write(path, values, sr=8000):
    sf.write(str(path), np.asarray(values, dtype="float32"), sr)
    return path


def test_peaks_are_bucketed_and_normalised(tmp_path):
    # 2s at 8 kHz: silent for 1s, then a constant 0.5 amplitude.
    sr = 8000
    t = np.arange(sr * 2) / sr
    y = np.where(t < 1.0, 0.0, 0.5)
    path = _write(tmp_path / "a.wav", y, sr=sr)

    peaks = waveform_peaks(path, buckets=20)

    assert len(peaks) == 20
    assert max(peaks) == 1.0                # loudest bucket normalised to 1
    assert peaks[0] == 0.0                  # silent half
    assert peaks[-1] > 0.5                  # loud half


def test_peaks_handle_silence(tmp_path):
    path = _write(tmp_path / "silent.wav", np.zeros(8000))
    peaks = waveform_peaks(path, buckets=8)
    assert len(peaks) == 8
    assert all(p == 0.0 for p in peaks)


def test_peaks_missing_file_returns_empty(tmp_path):
    assert waveform_peaks(tmp_path / "nope.wav") == []


def test_peaks_zero_buckets_returns_empty(tmp_path):
    path = _write(tmp_path / "a.wav", np.ones(800))
    assert waveform_peaks(path, buckets=0) == []