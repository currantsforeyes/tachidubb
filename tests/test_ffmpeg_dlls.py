"""Shared FFmpeg DLL discovery (tools/ffmpeg_dlls.py) used by the Qwen workers.

These three scripts each carried a copy of ``configure_windows_dlls`` with a
hardcoded ``C:\\Users\\...`` WinGet path (one username, one FFmpeg version).
The extraction into ``ffmpeg_dlls`` is pinned here: candidate precedence, the
per-user WinGet scan, loader registration, and a source-level guard that no
worker ships a machine-specific path again.
"""
import os
from pathlib import Path

import pytest

import tools.ffmpeg_dlls as ffmpeg_dlls

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPTS = (
    REPO_ROOT / "pipeline" / "qwen_tts_worker.py",
    REPO_ROOT / "tools" / "qwen_asr_refs.py",
    REPO_ROOT / "tools" / "qwen_tts_compare.py",
)


# ── ffmpeg_dll_candidates ────────────────────────────────────────────
def test_env_vars_win_and_follow_documented_order():
    env = {
        "TACHIDUBB_FFMPEG_BIN": "/a/bin",
        "FFMPEG_DIR": "/b",
        "FFMPEG_PATH": "/c/bin",
        "LOCALAPPDATA": "",
    }
    assert ffmpeg_dlls.ffmpeg_dll_candidates(env) == ["/a/bin", "/b", "/c/bin"]


def test_empty_env_yields_no_candidates(monkeypatch):
    assert ffmpeg_dlls.ffmpeg_dll_candidates({}) == []
    # And the real environment of the test process contributes nothing either.
    monkeypatch.delenv("TACHIDUBB_FFMPEG_BIN", raising=False)
    monkeypatch.delenv("FFMPEG_DIR", raising=False)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert ffmpeg_dlls.ffmpeg_dll_candidates() == []


def test_winget_scan_finds_payload_regardless_of_user_and_version(tmp_path):
    """Any account + any FFmpeg version resolves — not one hardcoded path."""
    pkg = (
        tmp_path / "Microsoft" / "WinGet" / "Packages"
        / "Gyan.FFmpeg_Microsoft.Winget.Source_hash" / "ffmpeg-99.0.1-full_build" / "bin"
    )
    pkg.mkdir(parents=True)
    cands = ffmpeg_dlls.ffmpeg_dll_candidates({"LOCALAPPDATA": str(tmp_path)})
    assert str(pkg) in cands


def test_winget_scan_is_case_insensitive_on_package_id(tmp_path):
    pkg = tmp_path / "Microsoft" / "WinGet" / "Packages" / "gyan.ffmpeg_x" / "payload" / "bin"
    pkg.mkdir(parents=True)
    cands = ffmpeg_dlls.ffmpeg_dll_candidates({"LOCALAPPDATA": str(tmp_path)})
    assert str(pkg) in cands


def test_winget_scan_skips_non_dirs_files_and_binless_packages(tmp_path):
    packages = tmp_path / "Microsoft" / "WinGet" / "Packages"
    (packages / "Gyan.FFmpeg_junk").mkdir(parents=True)      # no bin/ at all
    (packages / "not-a-dir.mp4").write_text("")              # stray file
    (packages / "Other.Package_x" / "payload" / "bin").mkdir(parents=True)  # not ffmpeg
    (packages / "Gyan.FFmpeg_direct" / "bin").mkdir(parents=True)  # payload = bin itself

    cands = ffmpeg_dlls.ffmpeg_dll_candidates({"LOCALAPPDATA": str(tmp_path)})

    assert cands == [str(packages / "Gyan.FFmpeg_direct" / "bin")]


def test_missing_winget_root_is_not_an_error(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "does-not-exist")}
    assert ffmpeg_dlls.ffmpeg_dll_candidates(env) == []


# ── configure_windows_dlls ───────────────────────────────────────────
def test_registers_first_existing_candidate(tmp_path, monkeypatch):
    """Precedence holds at registration: first candidate that is a dir wins."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    registered = []
    # os.add_dll_directory is Windows-only; inject it for any-platform tests.
    monkeypatch.setattr(os, "add_dll_directory", registered.append, raising=False)

    chosen = ffmpeg_dlls.configure_windows_dlls({
        "TACHIDUBB_FFMPEG_BIN": str(tmp_path / "missing"),
        "FFMPEG_DIR": str(bin_dir),
    })

    assert chosen == str(bin_dir)
    assert registered == [str(bin_dir)]


def test_returns_none_when_no_candidate_exists(tmp_path, monkeypatch):
    registered = []
    monkeypatch.setattr(os, "add_dll_directory", registered.append, raising=False)

    chosen = ffmpeg_dlls.configure_windows_dlls({
        "TACHIDUBB_FFMPEG_BIN": str(tmp_path / "nope"),
        "LOCALAPPDATA": str(tmp_path / "nowhere"),
    })

    assert chosen is None
    assert registered == []


def test_noop_on_platforms_without_dll_loader(tmp_path, monkeypatch):
    """Non-Windows must not AttributeError when a candidate happens to exist."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.delattr(os, "add_dll_directory", raising=False)

    chosen = ffmpeg_dlls.configure_windows_dlls({"TACHIDUBB_FFMPEG_BIN": str(bin_dir)})

    assert chosen is None


# ── the worker scripts actually use the shared helper ────────────────
@pytest.mark.parametrize("script", WORKER_SCRIPTS, ids=lambda p: p.name)
def test_worker_scripts_use_shared_helper_without_machine_paths(script):
    source = script.read_text(encoding="utf-8")
    assert "from ffmpeg_dlls import configure_windows_dlls" in source
    assert "C:\\Users\\" not in source
    # The old duplicate definition must be gone, not shadowed.
    assert "def configure_windows_dlls" not in source
