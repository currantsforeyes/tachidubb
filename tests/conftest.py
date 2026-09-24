"""Shared test fixtures."""
import shutil
import subprocess

import pytest


def _has_libass_subtitles() -> bool:
    """True when ffmpeg is on PATH and compiled with the `subtitles` filter."""
    if shutil.which("ffmpeg") is None:
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return False
    return any(" subtitles " in line for line in out.splitlines())


@pytest.fixture(scope="session")
def ffmpeg_subs():
    """Skip tests that render subtitles when ffmpeg + libass is unavailable.

    Request this fixture from any test whose happy path shells out to ffmpeg
    with the `subtitles` filter; error-path tests should stay ffmpeg-free.
    """
    if not _has_libass_subtitles():
        pytest.skip("ffmpeg with the libass 'subtitles' filter is required")
    return "ffmpeg"


def _has_drawtext_filter() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return False
    return any(" drawtext " in line for line in out.splitlines())


@pytest.fixture(scope="session")
def ffmpeg_drawtext():
    """Skip showcase-stitching tests when ffmpeg can't draw text.

    The showcase assembler overlays a language badge with `drawtext`, which
    additionally needs a usable system font.
    """
    if not _has_drawtext_filter():
        pytest.skip("ffmpeg with the drawtext filter is required")

    from pipeline.media import find_drawtext_font

    if not find_drawtext_font():
        pytest.skip("no usable font found for ffmpeg drawtext")
    return "ffmpeg"