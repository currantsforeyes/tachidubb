"""Segment post-processing cleanup — merge / absorb / split passes.

These passes run on every job right after speaker assignment. Getting them
wrong silently degrades every dub (garbled short segments, or one segment
eating the whole timeline), so they get dedicated coverage.
"""
from pipeline.segment_post import (
    postprocess_segments,
    _absorb_micro_segments,
    _split_very_long_segments,
)


def seg(start, end, text, speaker=None, **extra):
    d = {"start": start, "end": end, "text": text}
    if speaker is not None:
        d["speaker"] = speaker
    d.update(extra)
    return d


def test_empty_input_returns_empty():
    assert postprocess_segments([]) == []


def test_merges_unfinished_continuation():
    a = seg(0.0, 1.0, "hello world")
    b = seg(1.2, 2.5, "this is fine.")

    out = postprocess_segments([a, b])

    assert len(out) == 1
    assert out[0]["text"] == "hello world this is fine."
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 2.5


def test_does_not_merge_across_large_gap():
    out = postprocess_segments([seg(0.0, 1.0, "Done."), seg(3.0, 4.0, "Next one.")])
    assert len(out) == 2


def test_does_not_merge_finished_sentence_with_loose_gap():
    # prev ends in "." and the gap is not tight (<0.2s), so they stay separate
    out = postprocess_segments([seg(0.0, 1.0, "Done."), seg(1.3, 2.5, "Next sentence here.")])
    assert len(out) == 2


def test_does_not_merge_different_speakers():
    out = postprocess_segments([
        seg(0.0, 1.0, "hello", speaker="A"),
        seg(1.1, 2.0, "world", speaker="B"),
    ])
    assert len(out) == 2


def test_input_is_not_mutated():
    a = seg(0.0, 1.0, "hello world")
    b = seg(1.2, 2.5, "this is fine.")

    postprocess_segments([a, b])

    assert a["end"] == 1.0
    assert a["text"] == "hello world"
    assert b["text"] == "this is fine."


def test_absorb_micro_segment_into_previous():
    out = _absorb_micro_segments(
        [seg(0.0, 2.0, "Hello there friend."), seg(2.05, 2.4, "ok")],
        threshold_sec=1.0,
        threshold_chars=40,
    )
    assert len(out) == 1
    assert out[0]["end"] == 2.4
    assert out[0]["text"].endswith("ok")


def test_absorb_micro_segment_into_next():
    out = _absorb_micro_segments(
        [seg(0.0, 0.4, "Yes"), seg(0.5, 3.0, "main sentence")],
        threshold_sec=1.0,
        threshold_chars=40,
    )
    assert len(out) == 1
    assert out[0]["text"] == "Yes main sentence"
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 3.0


def test_split_very_long_segment_at_sentence_boundary():
    text = "This is the first sentence. And this is a second sentence that is long."
    words = [{"word": w} for w in text.split()]
    original = seg(0.0, 20.0, text, words=words)

    out = _split_very_long_segments([original], threshold=15.0)

    assert len(out) == 2
    assert out[0]["text"] == "This is the first sentence."
    assert out[1]["text"].startswith("And")
    # contiguous, and total duration preserved
    assert abs(out[0]["end"] - out[1]["start"]) < 1e-9
    assert abs(sum(s["end"] - s["start"] for s in out) - 20.0) < 1e-9
    # word alignment is partitioned, not duplicated or dropped
    assert len(out[0]["words"]) + len(out[1]["words"]) == len(words)


def test_long_segment_without_boundary_is_left_alone():
    out = _split_very_long_segments([seg(0.0, 20.0, "a" * 60)], threshold=15.0)
    assert len(out) == 1
    assert out[0]["text"] == "a" * 60


def test_short_segments_are_not_split():
    text = "One. Two. Three."
    out = _split_very_long_segments([seg(0.0, 5.0, text)], threshold=15.0)
    assert len(out) == 1
    assert out[0]["text"] == text