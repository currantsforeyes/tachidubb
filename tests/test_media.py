"""Media helpers extracted from server.py (SRT write, trim, probe, font)."""
import subprocess

import pipeline.media as media


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def make_run(responses):
    """A fake subprocess.run that pops queued responses (raising Exceptions)."""
    calls = []

    def _run(cmd, *args, **kwargs):
        calls.append(cmd)
        resp = responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    return _run, calls


# ── write_srt_file ───────────────────────────────────────────────────────
def test_write_srt_file_prefers_translation(tmp_path):
    out = tmp_path / "subs.srt"
    media.write_srt_file([
        {"start": 0.0, "end": 1.0, "text": "Hello", "translated_text": "Bonjour"},
        {"start": 1.0, "end": 2.0, "text": "World"},
    ], out)

    content = out.read_text(encoding="utf-8")
    assert content.startswith("1\n00:00:00,000 --> 00:00:01,000\nBonjour\n")
    assert "2\n00:00:01,000 --> 00:00:02,000\nWorld\n" in content


def test_write_srt_file_strips_emotion_tags(tmp_path):
    out = tmp_path / "subs.srt"
    media.write_srt_file([{"start": 0.0, "end": 1.0, "text": "(happy) Bonjour"}], out)
    assert "Bonjour" in out.read_text(encoding="utf-8")
    assert "(happy)" not in out.read_text(encoding="utf-8")


def test_write_srt_file_omits_empty_segments(tmp_path):
    out = tmp_path / "subs.srt"
    media.write_srt_file([
        {"start": 0.0, "end": 1.0, "text": "   "},
        {"start": 1.0, "end": 2.0, "text": "Second"},
    ], out)

    content = out.read_text(encoding="utf-8")
    assert "Second" in content
    # only one entry written
    assert content.count(" --> ") == 1


# ── trim_video ───────────────────────────────────────────────────────────
def test_trim_video_uses_stream_copy_when_it_works(tmp_path, monkeypatch):
    run, calls = make_run([Completed()])
    monkeypatch.setattr(media.subprocess, "run", run)

    out = media.trim_video(tmp_path / "a.mp4", tmp_path / "b.mp4", 30)

    assert out == tmp_path / "b.mp4"
    assert len(calls) == 1
    assert "-c" in calls[0]


def test_trim_video_falls_back_to_reencode(tmp_path, monkeypatch):
    err = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"keyframe mismatch")
    run, calls = make_run([err, Completed()])
    monkeypatch.setattr(media.subprocess, "run", run)

    out = media.trim_video(tmp_path / "a.mp4", tmp_path / "b.mp4", 30)

    assert out == tmp_path / "b.mp4"
    assert len(calls) == 2
    # second attempt re-encodes
    assert "libx264" in calls[1]


def test_trim_video_clamps_seconds_to_at_least_one(tmp_path, monkeypatch):
    run, calls = make_run([Completed()])
    monkeypatch.setattr(media.subprocess, "run", run)

    media.trim_video(tmp_path / "a.mp4", tmp_path / "b.mp4", 0)

    # "-t" is followed by "1" (clamped from 0)
    cmd = calls[0]
    assert cmd[cmd.index("-t") + 1] == "1"


# ── probe_duration ───────────────────────────────────────────────────────
def test_probe_duration_missing_file_returns_zero(tmp_path, monkeypatch):
    run, calls = make_run([])
    monkeypatch.setattr(media.subprocess, "run", run)

    assert media.probe_duration(tmp_path / "missing.mp4") == 0.0
    assert calls == []


def test_probe_duration_uses_ffprobe(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"")
    run, calls = make_run([Completed(stdout="12.5\n")])
    monkeypatch.setattr(media.subprocess, "run", run)

    assert media.probe_duration(f) == 12.5
    assert len(calls) == 1


def test_probe_duration_falls_back_to_ffmpeg_stderr(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"")
    run, calls = make_run([
        FileNotFoundError(),
        Completed(stderr="  Duration: 00:01:02.50, start: 0.000000, bitrate: ..."),
    ])
    monkeypatch.setattr(media.subprocess, "run", run)

    assert media.probe_duration(f) == 62.5
    assert len(calls) == 2


def test_probe_duration_zero_from_ffprobe_triggers_fallback(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"")
    run, calls = make_run([
        Completed(stdout="0\n"),
        Completed(stderr="Duration: 00:00:10.00, ..."),
    ])
    monkeypatch.setattr(media.subprocess, "run", run)

    assert media.probe_duration(f) == 10.0


def test_probe_duration_returns_zero_when_both_fail(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"")
    run, calls = make_run([FileNotFoundError(), FileNotFoundError()])
    monkeypatch.setattr(media.subprocess, "run", run)

    assert media.probe_duration(f) == 0.0


# ── find_drawtext_font ───────────────────────────────────────────────────
def test_find_drawtext_font_returns_empty_when_none_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "SHOWCASE_FONT_CANDIDATES", (str(tmp_path / "nope.ttf"),))
    assert media.find_drawtext_font() == ""


def test_find_drawtext_font_returns_first_existing(tmp_path, monkeypatch):
    font = tmp_path / "arial.ttf"
    font.write_bytes(b"")
    monkeypatch.setattr(media, "SHOWCASE_FONT_CANDIDATES", (str(font),))
    assert media.find_drawtext_font() == str(font)