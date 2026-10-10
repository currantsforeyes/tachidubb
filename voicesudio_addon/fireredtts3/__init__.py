"""FireRedTTS3 - out-of-tree sidecar engine for VoiceStudio.

Runs the model under **ComfyUI's interpreter** instead of VoiceStudio's: the
packaged build ships a read-only, code-signed Python environment (installing
into it would break the signature), and FireRedTTS3 needs a torch/transformers
stack of its own. ComfyUI's Python already has both - plus the
FireRedTTS3-ComfyUI pack and the weights - so ``venv_python()`` points there
and ``main.py`` carries VoiceStudio's length-prefixed JSON wire protocol to it.

This is the "installed alongside, selected by id" path from
``docs/engine-acceptance.md``: no core pipeline changes, registered by
``tools/install_voicesudio_firered.py`` into
``services/tts_backend.py::_LAZY_REGISTRY``.
"""
from __future__ import annotations

import os
from pathlib import Path

from services.subprocess_backend import SubprocessBackend

SUPPORTED_LANGUAGES = [
    "ar", "de", "en", "es", "fr", "hi", "it", "ja", "ko",
    "nl", "pl", "pt", "ru", "tr", "zh",
]

COMFY_ROOT_ENV = "OMNIVOICE_FIRERED_COMFY_ROOT"
DEFAULT_COMFY_ROOT = r"D:\ComfyUI-Easy-Install\ComfyUI"


def comfy_root() -> Path:
    """ComfyUI installation providing the runtime, pack and weights."""
    return Path(
        os.environ.get(COMFY_ROOT_ENV)
        or os.environ.get("TACHIDUBB_COMFY_ROOT")
        or DEFAULT_COMFY_ROOT
    )


def runtime_python(root: Path) -> "Path | None":
    """Locate ComfyUI's Python across the layouts we know about.

    Easy-Install keeps the interpreter *beside* the ComfyUI folder -
    ``<install>/python_embeded/python.exe`` next to ``<install>/ComfyUI`` -
    so probing only inside the code root finds nothing (which is how a run
    once silently fell back to Edge-TTS). Classic installs keep a venv inside
    the root instead. Same probe as tachidubb's
    ``synthesizer._find_interpreter``.
    """
    if os.name == "nt":
        names = (
            "python_embeded/python.exe",
            "venv/Scripts/python.exe",
            "python.exe",
        )
    else:
        names = ("python_embeded/python", "venv/bin/python", "python3")
    for base in (root, root.parent):
        for rel in names:
            path = base / rel
            if path.is_file():
                return path
    return None


def pack_dir(root: Path) -> Path:
    return Path(
        os.environ.get("OMNIVOICE_FIRERED_PACK_DIR")
        or (root / "custom_nodes" / "FireRedTTS3-ComfyUI")
    )


class FireRedTTS3Backend(SubprocessBackend):
    """Killable sidecar on ComfyUI's Python (dependency + crash isolation).

    Same shape as voxcpm2_subprocess: the parent prepares the reference clip,
    the sidecar renders, trim_trailing_silence() here finishes. Output is the
    pack's native 24 kHz; the parent masters/resamples as usual.
    """

    id = "fireredtts3"
    display_name = "FireRedTTS3 (15-lang zero-shot clone · ComfyUI runtime)"
    gpu_compat = ("cuda", "cpu")
    _DEFAULT_SAMPLE_RATE = 24_000
    max_ref_seconds = 30.0
    ref_strategy = "head"

    @classmethod
    def is_available(cls) -> "tuple[bool, str]":
        root = comfy_root()
        py = runtime_python(root)
        if py is None:
            return False, f"ComfyUI runtime not found under {root}"
        if not (pack_dir(root) / "loader.py").exists():
            return False, f"FireRedTTS3 pack not found in {pack_dir(root)}"
        return True, "ready"

    @classmethod
    def venv_python(cls) -> Path:
        py = runtime_python(comfy_root())
        if py is None:
            raise RuntimeError(
                "ComfyUI's Python runtime is missing - set "
                f"{COMFY_ROOT_ENV} to your ComfyUI folder."
            )
        return py

    @classmethod
    def sidecar_script(cls) -> Path:
        return Path(__file__).resolve().parent / "main.py"

    @property
    def sample_rate(self) -> int:
        return self._DEFAULT_SAMPLE_RATE

    @property
    def recv_timeout_s(self) -> float:
        # A cold model load (weights to VRAM) can take minutes on a busy GPU;
        # the sidecar heartbeats progress frames meanwhile.
        try:
            v = float(os.environ.get("OMNIVOICE_FIRERED_RECV_TIMEOUT_S", "900"))
        except (TypeError, ValueError):
            return 900.0
        return max(30.0, v)

    @property
    def supported_languages(self) -> "list[str]":
        return list(SUPPORTED_LANGUAGES)

    def generate(self, text: str, **kw):
        self._check_language(kw.get("language"))
        return super().generate(text, **kw)
