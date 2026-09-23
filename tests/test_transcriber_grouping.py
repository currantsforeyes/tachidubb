"""WhisperX word grouping into TTS-friendly chunks.

This decides where each synthesized take begins and ends, so a regression here
turns into garbled or mis-timed speech across every language.
"""
from pipeline.transcriber import _group_into_tts_segments


def words(*specs):
    """specs: (word, start, end[, speaker])"""
    out = []
    for s in specs:
        w = {"word": s[0], "start": s[1], "end": s[2]}
        if len(s) > 3:
            w["speaker"] = s[3]
        out.append(w)
    return out


def test_empty_input_returns_empty():
    assert _group_into_tts_segments([], "en") == []


def test_segment_without_words_uses_whole_text():
    chunks = _group_into_tts_segments(
        [{"text": "Hello there", "start": 0.0, "end": 1.0}], "en"
    )
    assert len(chunks) == 1
    assert chunks[0]["text"] == "Hello there"
    assert chunks[0]["start"] == 0.0
    assert chunks[0]["end"] == 1.0


def test_splits_on_sentence_end():
    seg = {"words": words(("a.", 0.0, 0.5), ("b.", 0.5, 1.0), ("c.", 1.0, 1.5))}
    chunks = _group_into_tts_segments([seg], "en")

    assert [c["text"] for c in chunks] == ["a. b.", "c."]


def test_splits_on_long_pause():
    seg = {"words": words(("hello", 0.0, 0.5), ("world", 2.0, 2.5), ("end", 2.5, 3.0))}
    chunks = _group_into_tts_segments([seg], "en")

    assert [c["text"] for c in chunks] == ["hello world", "end"]


def test_splits_on_speaker_change():
    seg = {"words": words(("hi", 0.0, 0.5, "A"), ("there", 0.5, 1.0, "B"))}
    chunks = _group_into_tts_segments([seg], "en")

    assert len(chunks) == 2
    assert [c["speaker"] for c in chunks] == ["A", "B"]
    assert [c["text"] for c in chunks] == ["hi", "there"]


def test_splits_when_max_chars_exceeded():
    seg = {"words": words(("aaaa", 0.0, 0.5), ("bbbb", 0.5, 1.0), ("cc", 1.0, 1.5))}
    chunks = _group_into_tts_segments([seg], "en", max_chars=5)

    assert [c["text"] for c in chunks] == ["aaaa bbbb", "cc"]


def test_short_chunk_is_extended_to_min_duration():
    seg = {"words": words(("hi", 0.0, 0.2))}
    chunks = _group_into_tts_segments([seg], "en", min_duration=0.6)

    assert len(chunks) == 1
    assert chunks[0]["end"] == 0.6


def test_missing_word_timings_do_not_crash():
    seg = {"words": [{"word": "hey", "start": None, "end": None}]}
    chunks = _group_into_tts_segments([seg], "en")

    assert len(chunks) == 1
    assert chunks[0]["text"] == "hey"
    assert chunks[0]["end"] >= 0.6