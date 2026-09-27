"""yt-dlp discovery across platforms (pipeline/downloader.py).

``_find_ytdlp`` picks its candidate list from ``sys.platform``, so on any
given OS only one branch ever executes in production — these tests pin both
branches on either OS by faking the platform, the interpreter location, and
``shutil.which``.
"""

import pytest

import pipeline.downloader as downloader


@pytest.fixture
def fake_venv(tmp_path, monkeypatch):
    """A fake interpreter layout: <tmp>/venv/Scripts/python.exe (+ .bat twin)."""
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    exe = scripts / "python.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(downloader.sys, "executable", str(exe))
    # Bare-name candidates are checked with os.path.isfile against the CWD;
    # isolate so a stray file in the repo root can't satisfy them.
    monkeypatch.chdir(tmp_path)
    return scripts


def _set_platform(monkeypatch, value):
    # downloader reads sys.platform through its own module import.
    monkeypatch.setattr(downloader.sys, "platform", value)


# ── Windows branch ───────────────────────────────────────────────────
def test_windows_finds_sibling_exe_first(fake_venv, monkeypatch):
    _set_platform(monkeypatch, "win32")
    ytdlp = fake_venv / "yt-dlp.exe"
    ytdlp.write_bytes(b"")

    found = downloader._find_ytdlp()

    assert found == str(ytdlp)


def test_windows_falls_back_to_path(fake_venv, monkeypatch):
    _set_platform(monkeypatch, "win32")
    # No sibling exe; pretend PATH provides it.
    monkeypatch.setattr(
        downloader.shutil, "which",
        lambda cmd, *a, **k: "C:\\tools\\yt-dlp.exe" if cmd == "yt-dlp.exe" else None,
    )

    assert downloader._find_ytdlp() == "C:\\tools\\yt-dlp.exe"


def test_windows_returns_none_so_caller_uses_python_m(fake_venv, monkeypatch):
    _set_platform(monkeypatch, "win32")
    monkeypatch.setattr(downloader.shutil, "which", lambda cmd, *a, **k: None)

    # No sibling file, nothing on PATH -> module-invocation fallback.
    assert downloader._find_ytdlp() is None


# ── POSIX branch ─────────────────────────────────────────────────────
def test_posix_finds_sibling_binary(fake_venv, monkeypatch):
    _set_platform(monkeypatch, "linux")
    ytdlp = fake_venv / "yt-dlp"  # no .exe suffix on POSIX
    ytdlp.write_bytes(b"")

    found = downloader._find_ytdlp()

    assert found == str(ytdlp)


def test_posix_ignores_windows_style_exe(fake_venv, monkeypatch):
    """The POSIX candidate list must not include .exe names."""
    _set_platform(monkeypatch, "linux")
    (fake_venv / "yt-dlp.exe").write_bytes(b"")
    monkeypatch.setattr(downloader.shutil, "which", lambda cmd, *a, **k: None)

    assert downloader._find_ytdlp() is None


def test_posix_falls_back_to_path(fake_venv, monkeypatch):
    _set_platform(monkeypatch, "linux")
    monkeypatch.setattr(
        downloader.shutil, "which",
        lambda cmd, *a, **k: "/usr/local/bin/yt-dlp" if cmd == "yt-dlp" else None,
    )

    assert downloader._find_ytdlp() == "/usr/local/bin/yt-dlp"


# ── platform-independent behaviour ───────────────────────────────────
def test_candidate_order_prefers_real_files_over_path(tmp_path, monkeypatch):
    """A venv sibling must win over a PATH hit (fresh venvs shadow system)."""
    scripts = tmp_path / "bin"
    scripts.mkdir()
    sibling = scripts / "yt-dlp"
    sibling.write_bytes(b"")
    monkeypatch.setattr(downloader.sys, "executable", str(scripts / "python"))
    _set_platform(monkeypatch, "linux")
    # PATH hit only for the bare name — full-path candidates must not match.
    monkeypatch.setattr(
        downloader.shutil, "which",
        lambda cmd, *a, **k: "/usr/bin/yt-dlp" if cmd == "yt-dlp" else None,
    )

    assert downloader._find_ytdlp() == str(sibling)


def test_accepts_path_hit_that_is_a_plain_file_not_on_path(tmp_path, monkeypatch):
    """shutil.which returns None for bare names, but a direct file still counts.

    The fallback ``os.path.isfile(candidate)`` branch covers bare names that
    resolve relative to the CWD — pin it so a future refactor keeps it.
    """
    scripts = tmp_path / "bin"
    scripts.mkdir()
    monkeypatch.setattr(downloader.sys, "executable", str(scripts / "python"))
    _set_platform(monkeypatch, "linux")
    monkeypatch.setattr(downloader.shutil, "which", lambda cmd, *a, **k: None)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "yt-dlp").write_bytes(b"")

    assert downloader._find_ytdlp() == "yt-dlp"
