r"""Locate the local FFmpeg bin directory so its DLLs resolve (Windows).

Shared by the Qwen worker scripts — ``pipeline/qwen_tts_worker.py``,
``tools/qwen_asr_refs.py`` and ``tools/qwen_tts_compare.py`` — which all run
as bare ``python script.py`` subprocesses inside the isolated Qwen runtimes
(no TachiDUBB package imports, minimal third-party deps).  This module
therefore lives in ``tools/`` next to two of them and sticks to the stdlib.

Discovery order (was: one developer's hardcoded WinGet path):

1. ``TACHIDUBB_FFMPEG_BIN`` — documented override (bin folder), same env var
   the lipsync/MuseTalk path honours.
2. ``FFMPEG_DIR`` / ``FFMPEG_PATH`` — the env vars ``app/main.py`` reads, so
   a configured server and its workers agree.
3. Per-user WinGet package layout under ``%LOCALAPPDATA%`` — matched by name
   rather than pinned to one username and one FFmpeg version, so any account
   and any upgraded package resolves without configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

# Env vars checked first, in precedence order.
_ENV_KEYS = ("TACHIDUBB_FFMPEG_BIN", "FFMPEG_DIR", "FFMPEG_PATH")


def ffmpeg_dll_candidates(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """Ordered candidate directories that may contain FFmpeg's DLLs.

    Pure discovery — touches neither the filesystem registry nor the loader.
    ``env`` defaults to ``os.environ``; tests pass a mapping.  The WinGet
    scan contributes a package only when its ``bin`` folder exists, so a
    half-installed package cannot shadow a working candidate.
    """
    if env is None:
        env = os.environ
    candidates: list[str] = []
    for key in _ENV_KEYS:
        value = (env.get(key) or "").strip()
        if value:
            candidates.append(value)

    # WinGet installs per-user packages as
    #   %LOCALAPPDATA%\Microsoft\WinGet\Packages\<id>\<payload>\bin
    # Scan by name so both the package dir and the payload dir stay
    # version- and account-independent (case handled below — WinGet ids
    # vary, e.g. Gyan.FFmpeg_...).
    local_app_data = (env.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if packages.is_dir():
            for pkg in sorted(packages.iterdir()):
                if not pkg.is_dir() or "ffmpeg" not in pkg.name.lower():
                    continue
                if (pkg / "bin").is_dir():  # payload placed directly under the id
                    candidates.append(str(pkg / "bin"))
                for payload in sorted(pkg.iterdir()):
                    if payload.is_dir() and (payload / "bin").is_dir():
                        candidates.append(str(payload / "bin"))
    return candidates


def configure_windows_dlls(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Register the first candidate that exists with the process DLL loader.

    Returns the directory registered, else ``None`` — no candidate exists,
    or the platform has no DLL loader: ``os.add_dll_directory`` is
    Windows-only, so this deliberately no-ops elsewhere instead of raising
    ``AttributeError`` the moment an env var happens to point somewhere.
    """
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return None
    for candidate in ffmpeg_dll_candidates(env):
        if candidate and Path(candidate).is_dir():
            add_dll_directory(candidate)
            return candidate
    return None
