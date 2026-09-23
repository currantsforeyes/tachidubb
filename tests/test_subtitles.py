"""Subtitle style map + ffmpeg filter construction (extracted from server.py)."""
from pipeline.subtitles import (
    SUB_STYLE_MAP,
    DEFAULT_STYLE,
    get_force_style,
    escape_subtitles_path,
    build_subtitles_filter,
    pick_preview_timestamp,
)


def test_style_map_has_expected_presets():
    assert set(SUB_STYLE_MAP) >= {"default", "large", "minimal", "yellow", "boxed"}
    assert DEFAULT_STYLE == "default"


def test_get_force_style_known_and_unknown():
    assert get_force_style("yellow") == SUB_STYLE_MAP["yellow"]
    assert get_force_style("does-not-exist") == SUB_STYLE_MAP["default"]


def test_escape_subtitles_path_windows():
    assert escape_subtitles_path(r"C:\a\b.srt") == r"C\:/a/b.srt"


def test_escape_subtitles_path_posix_unchanged():
    assert escape_subtitles_path("/tmp/a.srt") == "/tmp/a.srt"


def test_build_subtitles_filter_uses_named_style():
    f = build_subtitles_filter("/tmp/a.srt", "large")
    assert f == f"subtitles='/tmp/a.srt':force_style='{SUB_STYLE_MAP['large']}'"


def test_build_subtitles_filter_explicit_force_style_override():
    f = build_subtitles_filter("/tmp/a.srt", "default", force_style="Fontsize=99")
    assert f == "subtitles='/tmp/a.srt':force_style='Fontsize=99'"


def test_build_subtitles_filter_escapes_windows_path():
    f = build_subtitles_filter(r"C:\v\subs.srt", "default")
    assert f.startswith(r"subtitles='C\:/v/subs.srt'")


def test_pick_preview_timestamp_skips_invalid_segments():
    segments = [
        {"start": 0.0, "end": 0.5, "text": "hi"},              # < 1s
        {"start": 1.0, "end": 1.2, "text": "   "},            # empty
        {"start": 2.0, "end": 4.0, "translated_text": "Bonjour"},  # valid
    ]
    assert pick_preview_timestamp(segments) == 3.0


def test_pick_preview_timestamp_uses_plain_text_when_no_translation():
    assert pick_preview_timestamp([{"start": 1.0, "end": 3.0, "text": "Hello"}]) == 2.0


def test_pick_preview_timestamp_fallback():
    assert pick_preview_timestamp([]) == 2.0
    assert pick_preview_timestamp([{"start": 0.0, "end": 0.2, "text": "x"}]) == 2.0
    assert pick_preview_timestamp([], fallback=5.0) == 5.0