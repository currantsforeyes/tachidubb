"""Speaker assignment and micro-turn smoothing.

The pipeline relies on this to keep one voice per speaker and to avoid
one-word TTS fragments at diarization turn boundaries.
"""
from pipeline.diarizer import assign_speakers_to_segments, _total_duration


def test_no_turns_defaults_everyone_to_speaker_00():
    segments = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    out = assign_speakers_to_segments(segments, [])
    assert out[0]["speaker"] == "SPEAKER_00"


def test_whole_segment_assigned_by_largest_overlap():
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    turns = [(0.0, 0.6, "A"), (0.6, 1.0, "B")]
    out = assign_speakers_to_segments(segments, turns)
    assert out[0]["speaker"] == "A"


def test_word_level_split_on_speaker_change():
    segments = [{
        "start": 0.0,
        "end": 1.0,
        "text": "hi there",
        "words": [
            {"word": "hi", "start": 0.0, "end": 0.5},
            {"word": "there", "start": 0.5, "end": 1.0},
        ],
    }]
    turns = [(0.0, 0.5, "A"), (0.5, 1.0, "B")]

    out = assign_speakers_to_segments(segments, turns)

    assert len(out) == 2
    assert [s["speaker"] for s in out] == ["A", "B"]
    assert [s["text"] for s in out] == ["hi", "there"]


def test_short_word_flanked_by_same_speaker_is_smoothed():
    segments = [{
        "start": 0.0,
        "end": 1.2,
        "text": "Hello oh there",
        "words": [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "oh", "start": 0.5, "end": 0.7},
            {"word": "there", "start": 0.7, "end": 1.2},
        ],
    }]
    # A spurious one-word B flip between two A turns
    turns = [(0.0, 0.5, "A"), (0.5, 0.7, "B"), (0.7, 1.2, "A")]

    out = assign_speakers_to_segments(segments, turns)

    assert len(out) == 1
    assert out[0]["speaker"] == "A"
    assert out[0]["text"] == "Hello oh there"


def test_cross_chunk_micro_turn_merges_into_next():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "First line"},
        {"start": 1.0, "end": 1.3, "text": "Еще"},
        {"start": 1.3, "end": 2.0, "text": "заработаем"},
    ]
    turns = [(0.0, 1.0, "A"), (1.0, 1.3, "B"), (1.3, 2.0, "A")]

    out = assign_speakers_to_segments(segments, turns)

    assert len(out) == 2
    assert out[1]["start"] == 1.0
    assert "Еще" in out[1]["text"]
    assert "заработаем" in out[1]["text"]


def test_total_duration_sums_only_matching_speaker():
    turns = [(0.0, 1.0, "A"), (1.0, 3.0, "B"), (3.0, 4.0, "A")]
    assert _total_duration(turns, "A") == 2.0
    assert _total_duration(turns, "B") == 2.0
    assert _total_duration(turns, "C") == 0.0