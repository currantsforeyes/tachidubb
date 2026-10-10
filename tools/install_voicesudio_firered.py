"""Install the out-of-tree FireRedTTS3 engine into a VoiceStudio install.

Copies ``voicesudio_addon/fireredtts3/`` into
``%APPDATA%/VoiceStudio/runtime/project/backend/engines/`` and registers the
backend id in ``services/tts_backend.py::_LAZY_REGISTRY`` (original backed up
to ``tts_backend.py.bak-firered`` first). Idempotent: re-running only
refreshes the engine files; the registry edit happens once.

VoiceStudio's packaged Python env is read-only and code-signed, so nothing is
installed into it - the engine sidecar runs under ComfyUI's interpreter.

    python tools/install_voicesudio_firered.py          # install
    python tools/install_voicesudio_firered.py --check  # verify only

After installing, restart VoiceStudio and pick "FireRedTTS3 (...)" in the
engine picker.
"""
from __future__ import annotations

import argparse
import io
import os
import py_compile
import shutil
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "voicesudio_addon" / "fireredtts3"
ENGINE_ID = "fireredtts3"
ANCHOR = "_LAZY_REGISTRY: dict[str, tuple[str, str]] = {"
ENTRY = '    "fireredtts3": ("engines.fireredtts3", "FireRedTTS3Backend"),'
COMMENT = (
    "    # Out-of-tree engine: FireRedTTS3 on ComfyUI's interpreter\n"
    "    # (tools/install_voicesudio_firered.py). Remove to uninstall.\n"
)
BACKUP_SUFFIX = ".bak-firered"


def backend_root() -> Path:
    override = os.environ.get("TACHIDUBB_VS_BACKEND")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("APPDATA is not set - cannot locate VoiceStudio")
    return Path(appdata) / "VoiceStudio" / "runtime" / "project" / "backend"


def _decode(data: bytes) -> "tuple[str, str]":
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding), encoding


def install(backend: Path, check_only: bool) -> int:
    engines = backend / "engines" / ENGINE_ID
    registry = backend / "services" / "tts_backend.py"

    if not registry.exists():
        print(f"NOT INSTALLED: no VoiceStudio backend at {backend}")
        return 1

    # --- 1. registry entry -------------------------------------------------
    data = registry.read_bytes()
    text, encoding = _decode(data)
    problems: list[str] = []

    if ENGINE_ID in text and ENTRY.strip() in text:
        print("registry: already registered")
    elif ANCHOR not in text:
        problems.append(
            "registry: anchor line not found - VoiceStudio layout changed; "
            "add this line inside _LAZY_REGISTRY manually:\n    " + ENTRY
        )
    elif check_only:
        problems.append("registry: engine id NOT registered (run without --check)")
    else:
        backup = registry.with_name(registry.name + BACKUP_SUFFIX)
        if not backup.exists():
            backup.write_bytes(data)
            print(f"registry: backup -> {backup.name}")
        new_text = text.replace(ANCHOR, ANCHOR + "\n" + COMMENT + ENTRY, 1)
        registry.write_bytes(new_text.encode(encoding))
        print("registry: registered fireredtts3 in _LAZY_REGISTRY")

    # --- 2. engine files ---------------------------------------------------
    if check_only:
        for name in ("__init__.py", "main.py"):
            if not (engines / name).exists():
                problems.append(f"engine: missing {engines / name}")
        if engines.exists():
            print("engine: files present")
    else:
        engines.mkdir(parents=True, exist_ok=True)
        for name in ("__init__.py", "main.py"):
            shutil.copy2(SRC / name, engines / name)
        shutil.rmtree(engines / "__pycache__", ignore_errors=True)
        print(f"engine: copied -> {engines}")

    # --- 3. verify ---------------------------------------------------------
    for name in ("__init__.py", "main.py"):
        target = engines / name
        if not target.exists():
            problems.append(f"verify: {target} missing")
            continue
        try:
            py_compile.compile(str(target), doraise=True)
        except py_compile.PyCompileError as exc:
            problems.append(f"verify: {target} does not compile: {exc}")
    if ENGINE_ID not in _decode(registry.read_bytes())[0]:
        problems.append("verify: registry entry not present after patch")
    elif not problems:
        print("verify: compile + registry OK")

    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        return 1

    if not check_only:
        print(
            "\nDone. Restart VoiceStudio, then select "
            '"FireRedTTS3 (15-lang zero-shot clone - ComfyUI runtime)" '
            "in the engine picker."
        )
    return 0


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only")
    args = parser.parse_args(argv)
    if not (SRC / "main.py").exists():
        print(f"NOT FOUND: {SRC / 'main.py'}")
        return 1
    return install(backend_root(), args.check)


if __name__ == "__main__":
    sys.exit(main())
