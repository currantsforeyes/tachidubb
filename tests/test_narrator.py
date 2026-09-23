"""Narrator mode — one speaker for the whole video (diarization skipped)."""
from app.pipeline import _force_single_speaker


def test_force_single_speaker_sets_default_and_is_in_place():
    segments = [{"speaker": "A"}, {"speaker": "B"}, {}]

    out = _force_single_speaker(segments)

    assert out is segments  # in-place, returns the same list
    assert [s["speaker"] for s in segments] == ["SPEAKER_00"] * 3


def test_force_single_speaker_custom_id():
    segments = [{"speaker": "A"}]
    _force_single_speaker(segments, "NARRATOR")
    assert segments[0]["speaker"] == "NARRATOR"