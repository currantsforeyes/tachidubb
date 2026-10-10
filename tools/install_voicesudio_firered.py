"""Install the out-of-tree FireRedTTS3 engine into a VoiceStudio install.

VoiceStudio re-extracts ``%APPDATA%/VoiceStudio/runtime/project`` from its
install-time source ``<install>/resources/backend`` on every launch - we
watched it delete an engine folder and revert a registry edit minutes after
they were applied (and ``app.asar`` holds no backend source, so ``resources``
is the only source of truth). Patching ``runtime`` alone therefore does not
survive a restart; this installer patches **both trees**:

- ``<install>/resources/backend`` - the source of truth; every re-extraction
  carries the engine forward. Lost on app updates (electron-updater replaces
  ``resources``) -> just re-run this script.
- ``%APPDATA%/VoiceStudio/runtime/project/backend`` - for immediate effect on
  the next restart without waiting for extraction.

Each patched ``services/tts_backend.py`` is backed up first
(``tts_backend.py.bak-firered``). Idempotent: re-running only refreshes the
engine files.

VoiceStudio's packaged Python env is read-only and code-signed, so nothing is
installed into it - the engine sidecar runs under ComfyUI's interpreter.

    python tools/install_voicesudio_firered.py          # install
    python tools/install_voicesudio_firered.py --check  # verify wiring

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


def resources_backend() -> Path | None:
    """The install-time source of truth: <install>/resources/backend."""
    override = os.environ.get("TACHIDUBB_VS_RESOURCES")
    if override:
        base = Path(override)
    else:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return None
        base = Path(local) / "Programs" / "VoiceStudio" / "resources"
    return base / "backend" if (base / "backend").is_dir() else None


def runtime_backend() -> Path | None:
    """The live tree the backend process actually imports from."""
    override = os.environ.get("TACHIDUBB_VS_BACKEND")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        base = Path(appdata) / "VoiceStudio" / "runtime" / "project" / "backend"
    return base if base.is_dir() else None


def _decode(data: bytes) -> tuple[str, str]:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding), encoding


def install_into(backend: Path, check_only: bool) -> list[str]:
    """Patch one tree; returns problems (empty = ok)."""
    problems: list[str] = []
    engines = backend / "engines" / ENGINE_ID
    registry = backend / "services" / "tts_backend.py"
    label = "resources" if "resources" in backend.parts else "runtime"

    if not registry.exists():
        return [f"{label}: no services/tts_backend.py under {backend}"]

    # --- 1. registry entry -------------------------------------------------
    data = registry.read_bytes()
    text, encoding = _decode(data)
    if ENTRY.strip() in text:
        print(f"[{label}] registry: already registered")
    elif ANCHOR not in text:
        problems.append(
            f"[{label}] registry: anchor line not found - VoiceStudio layout "
            "changed; add this line inside _LAZY_REGISTRY manually:\n    " + ENTRY
        )
    elif check_only:
        problems.append(f"[{label}] registry: engine id NOT registered")
    else:
        backup = registry.with_name(registry.name + BACKUP_SUFFIX)
        if not backup.exists():
            backup.write_bytes(data)
            print(f"[{label}] registry: backup -> {backup.name}")
        new_text = text.replace(ANCHOR, ANCHOR + "\n" + COMMENT + ENTRY, 1)
        registry.write_bytes(new_text.encode(encoding))
        print(f"[{label}] registry: registered fireredtts3 in _LAZY_REGISTRY")

    # --- 2. engine files ---------------------------------------------------
    if check_only:
        for name in ("__init__.py", "main.py"):
            if not (engines / name).exists():
                problems.append(f"[{label}] engine: missing {engines / name}")
        if engines.exists() and not problems:
            print(f"[{label}] engine: files present")
    else:
        engines.mkdir(parents=True, exist_ok=True)
        for name in ("__init__.py", "main.py"):
            shutil.copy2(SRC / name, engines / name)
        shutil.rmtree(engines / "__pycache__", ignore_errors=True)
        print(f"[{label}] engine: copied -> {engines}")

    # --- 3. verify ---------------------------------------------------------
    for name in ("__init__.py", "main.py"):
        target = engines / name
        if not target.exists():
            problems.append(f"[{label}] verify: {target} missing")
            continue
        try:
            py_compile.compile(str(target), doraise=True)
        except py_compile.PyCompileError as exc:
            problems.append(f"[{label}] verify: {target} does not compile: {exc}")
    if ENGINE_ID not in _decode(registry.read_bytes())[0]:
        problems.append(f"[{label}] verify: registry entry not present after patch")
    elif not problems:
        print(f"[{label}] verify: compile + registry OK")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only")
    args = parser.parse_args(argv)

    if not (SRC / "main.py").exists():
        print(f"NOT FOUND: {SRC / 'main.py'}")
        return 1

    trees = [t for t in (resources_backend(), runtime_backend()) if t is not None]
    if not trees:
        print("NOT INSTALLED: neither resources/backend nor runtime backend found")
        return 1

    problems: list[str] = []
    for tree in trees:
        problems.extend(install_into(tree, args.check))

    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        return 1

    if not args.check:
        print(
            "\nDone. Restart VoiceStudio (its launch re-extracts the runtime "
            "tree from the patched resources source), then select "
            '"FireRedTTS3 (15-lang zero-shot clone - ComfyUI runtime)" '
            "in the engine picker.\n"
            "Note: an app update replaces resources/ - re-run this script "
            "after updating."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
