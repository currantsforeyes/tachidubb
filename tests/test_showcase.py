"""Showcase timeline slicing (extracted from server.py)."""
from pipeline.showcase import (
    load_placements,
    save_placements,
    snap_boundaries_to_sentences,
)


def test_single_part_returns_whole_timeline():
    assert snap_boundaries_to_sentences([], 100.0, 1) == [(0.0, 100.0)]


def test_no_segments_returns_whole_timeline():
    assert snap_boundaries_to_sentences([], 100.0, 4) == [(0.0, 100.0)]


def test_boundaries_snap_to_segment_ends():
    segments = [{"end": 25.0}, {"end": 50.0}, {"end": 75.0}]
    slices = snap_boundaries_to_sentences(segments, 100.0, 4)
    assert slices == [(0.0, 25.0), (25.0, 50.0), (50.0, 75.0), (75.0, 100.0)]


def test_interior_boundary_snaps_to_nearest_end():
    slices = snap_boundaries_to_sentences([{"end": 40.0}], 100.0, 2)
    assert slices == [(0.0, 40.0), (40.0, 100.0)]


def test_slices_are_contiguous_and_cover_timeline():
    segments = [{"end": e} for e in (7.0, 19.0, 31.0, 58.0, 88.0)]
    slices = snap_boundaries_to_sentences(segments, 100.0, 5)

    assert slices[0][0] == 0.0
    assert slices[-1][1] == 100.0
    assert all(s[1] > s[0] for s in slices)
    for prev, curr in zip(slices, slices[1:]):
        assert prev[1] == curr[0]


def test_boundaries_keep_minimum_spacing():
    slices = snap_boundaries_to_sentences([{"end": 1.0}], 10.0, 3)
    assert len(slices) == 3
    assert all(s[1] > s[0] for s in slices)
    for prev, curr in zip(slices, slices[1:]):
        assert prev[1] == curr[0]


def test_save_and_load_placements_round_trip(tmp_path):
    segments = [
        {"idx": 0, "start": 0.0, "end": 1.0, "placed_start": 0.0, "placed_end": 1.1},
        {"idx": 1, "start": 1.0, "end": 2.0},  # no placement -> skipped
    ]
    save_placements(tmp_path, segments)

    rows = load_placements(tmp_path)
    assert len(rows) == 1
    assert rows[0] == {
        "idx": 0, "src_start": 0.0, "src_end": 1.0, "dub_start": 0.0, "dub_end": 1.1,
    }


def test_load_placements_missing_returns_empty(tmp_path):
    assert load_placements(tmp_path) == []