"""SRT rendering — timestamp formatting and file output."""
from pipeline.assembler import format_srt_time, write_srt


def test_format_srt_time_zero():
    assert format_srt_time(0) == "00:00:00,000"


def test_format_srt_time_seconds_and_millis():
    assert format_srt_time(61.5) == "00:01:01,500"


def test_format_srt_time_hours():
    assert format_srt_time(3661.5) == "01:01:01,500"


def test_write_srt_uses_translation_and_numbers_from_one(tmp_path):
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Hello", "translated_text": "Bonjour"},
        {"start": 1.0, "end": 2.0, "text": "World"},
    ]
    out = tmp_path / "subs.srt"

    write_srt(segments, str(out))

    content = out.read_text(encoding="utf-8")
    assert content.startswith("1\n00:00:00,000 --> 00:00:01,000\nBonjour\n\n")
    assert "2\n00:00:01,000 --> 00:00:02,000\nWorld\n\n" in content


def test_write_srt_empty_segments(tmp_path):
    out = tmp_path / "empty.srt"
    write_srt([], str(out))
    assert out.read_text(encoding="utf-8") == ""