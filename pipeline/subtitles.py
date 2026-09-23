"""Subtitle styling + ffmpeg `subtitles` filter construction.

Shared by the burn-in, preview and export endpoints so their styling never
drifts apart. Pure string/timestamp logic — no ffmpeg calls here — extracted
from ``server.py`` to make it unit-testable.

ffmpeg's `subtitles` filter uses libass ``force_style`` syntax. BorderStyle=1
is outline+shadow; 3 is an opaque box.
"""
from pathlib import Path
from typing import Optional, Union

# Subtitle styling presets — shared by burn-in, preview and export.
SUB_STYLE_MAP = {
    "default": "Fontsize=22,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=28",
    "large":   "Fontsize=30,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=3,Shadow=1,MarginV=40,Bold=1",
    "minimal": "Fontsize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=1,Shadow=0,MarginV=20",
    # Yellow "classic cinema" style — high-legibility for action footage
    "yellow":  "Fontsize=24,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Shadow=2,MarginV=30,Bold=1",
    # Opaque box for noisy backgrounds (e.g. bright snow, chaotic action)
    "boxed":   "Fontsize=22,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BackColour=&HC0000000,BorderStyle=3,Outline=0,Shadow=0,MarginV=28",
}

DEFAULT_STYLE = "default"


def get_force_style(style: str) -> str:
    """Return the libass force_style string for a named preset (default fallback)."""
    return SUB_STYLE_MAP.get(style, SUB_STYLE_MAP[DEFAULT_STYLE])


def escape_subtitles_path(path: Union[str, Path]) -> str:
    """Escape an SRT path for ffmpeg's `subtitles` filter argument.

    The filter parses its argument like a filter string, so on Windows we
    need forward slashes and escaped drive-letter colons.
    """
    return str(path).replace("\\", "/").replace(":", r"\:")


def build_subtitles_filter(
    srt_path: Union[str, Path],
    style: str = DEFAULT_STYLE,
    force_style: Optional[str] = None,
) -> str:
    """Build `subtitles='<path>':force_style='<style>'` for a -vf chain.

    Pass ``force_style`` directly to override the named preset lookup.
    """
    if force_style is None:
        force_style = get_force_style(style)
    return f"subtitles='{escape_subtitles_path(srt_path)}':force_style='{force_style}'"


def pick_preview_timestamp(segments: list, fallback: float = 2.0) -> float:
    """Pick a timestamp likely to show subtitle text in a preview frame.

    Returns the midpoint of the first segment that has text and lasts at
    least 1s; otherwise ``fallback``.
    """
    for seg in segments:
        text = (seg.get("translated_text") or seg.get("text") or "").strip()
        dur = seg.get("end", 0) - seg.get("start", 0)
        if text and dur >= 1.0:
            # Pick middle of segment so sub is guaranteed visible
            return seg["start"] + dur / 2
    return fallback