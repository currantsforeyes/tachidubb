"""FireRedTTS3 sidecar for VoiceStudio's SubprocessBackend wire protocol.

Speaks the length-prefixed JSON protocol implemented by
``backend/services/subprocess_backend.py`` and documented by the tree's
``_echo`` sidecar:

    [4-byte big-endian uint32 length][N bytes UTF-8 JSON]

It runs under **ComfyUI's interpreter**, not VoiceStudio's: the packaged
build's Python environment is read-only and code-signed, while FireRedTTS3
needs its own torch/transformers stack - which ComfyUI already has, along
with the FireRedTTS3-ComfyUI pack and the weights. The synthesis path is
tachidubb's validated ``pipeline/firered_worker.py`` (run 8ff2deae): pack
import via synthetic package, prompt latents cached per reference clip, and
the window-anchored ``max_gen_steps`` budget that keeps a stop-token failure
from emitting 64 s of double speech.

Op flow:
    start  -> {"op":"progress",...} -> {"op":"ready","engine":"fireredtts3",
                                        "sample_rate":24000}
    ping   -> {"op":"pong","vram_mb":N}
    synthesize {text, ref_audio, ref_text?, language?, duration?, ...}
             -> {"op":"audio","audio_pcm_b64":...,"sample_rate":...,
                 "n_samples":...}
    shutdown -> exit 0
    unknown/failed op -> {"op":"error","stage":...,"message":...} (continues)

``OMNIVOICE_FIRERED_STUB=1`` swaps in a sine-wave fake model - the CI
round-trip gate, same idea as ``_echo``.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import time
from pathlib import Path

MAX_FRAME_BYTES = 64 * 1024 * 1024
ENGINE_ID = "fireredtts3"
SAMPLE_RATE = 24_000  # pack native.py:47

# Same set as tachidubb's firered_worker: ISO-2 code -> FireRed language tag.
LANGUAGE_TAGS = {
    "en": "English", "ru": "Russian", "es": "Spanish", "pt": "Portuguese",
    "fr": "French", "de": "German", "it": "Italian", "pl": "Polish",
    "tr": "Turkish", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
    "ar": "Arabic", "hi": "Hindi", "nl": "Dutch",
}

# 25 latent frames per second, 4 latents per AR step -> 6.25 steps per second
# of audio. Taken from the ComfyUI pack's own _max_gen_steps().
STEPS_PER_SECOND = 25.0 / 4.0

# Anchoring the step budget to the slot the clip belongs to is what stopped a
# 1.02 s window from producing 64 s of audio (hard ceiling 400 steps) that then
# played under the rest of the dub as double speech.
MAX_WINDOW_FACTOR = 2.0
MIN_AUDIO_SECONDS = 2.0

_FRAME_FD: int | None = None
_NATIVE = None
_BUNDLE = None
_STUB = False
_PROMPT_CACHE: dict = {}


def max_gen_steps_for(slot_seconds) -> int:
    """AR-step budget for a clip, from the slot (or text estimate) it fills."""
    seconds = max(float(slot_seconds) * MAX_WINDOW_FACTOR, MIN_AUDIO_SECONDS)
    return max(6, int(round(seconds * STEPS_PER_SECOND)))


def language_tag(value) -> str:
    """ISO-2 code or picker name -> the tag FireRed's frontend expects."""
    raw = str(value or "en").strip()
    if not raw or raw.lower() == "auto":
        return "English"
    code = raw.lower()
    if code in LANGUAGE_TAGS:
        return LANGUAGE_TAGS[code]
    for tag in LANGUAGE_TAGS.values():
        if tag.lower() == code:
            return tag
    raise ValueError(
        f"FireRedTTS3 does not support language {raw!r} "
        f"(supported: {', '.join(sorted(LANGUAGE_TAGS))})"
    )


def _steps_for(msg: dict, text: str) -> int:
    """Window-anchored budget: requested duration wins, else a text estimate
    (~12 chars/s, then 2x headroom inside max_gen_steps_for)."""
    try:
        slot = float(msg.get("duration") or 0.0)
    except (TypeError, ValueError):
        slot = 0.0
    if slot <= 0:
        slot = max(len(text) / 12.0, 1.0)
    return max_gen_steps_for(slot)


def _num(msg: dict, key: str, default: float) -> float:
    try:
        v = float(msg.get(key, default))
    except (TypeError, ValueError):
        return float(default)
    return v if v == v and abs(v) != float("inf") else float(default)


def _send(obj: dict) -> None:
    if _FRAME_FD is None:
        raise RuntimeError("frame fd not set (run as a script, not an import)")
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError(f"frame too large: {len(payload)}")
    for chunk in (struct.pack(">I", len(payload)), payload):
        view = memoryview(chunk)
        while view:
            written = os.write(_FRAME_FD, view)
            view = view[written:]


def _read_exactly(n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = os.read(0, n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv() -> dict | None:
    header = _read_exactly(4)
    if header is None:
        return None
    (length,) = struct.unpack(">I", header)
    if length > MAX_FRAME_BYTES:
        raise ValueError(f"frame too large: {length}")
    body = _read_exactly(length)
    if body is None:
        raise EOFError("truncated frame body")
    return json.loads(body.decode("utf-8"))


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def comfy_paths() -> tuple[Path, Path]:
    root = Path(
        _env("OMNIVOICE_FIRERED_COMFY_ROOT")
        or _env("TACHIDUBB_COMFY_ROOT")
        or r"D:\ComfyUI-Easy-Install\ComfyUI"
    )
    pack = Path(
        _env("OMNIVOICE_FIRERED_PACK_DIR")
        or (root / "custom_nodes" / "FireRedTTS3-ComfyUI")
    )
    return root, pack


def _load_model(stub: bool):
    """Import the pack and load the bundle (port of firered_worker's
    ``_load_backend``), or the sine-wave fake in stub mode."""
    if stub:
        return _stub_native(), object()

    import importlib
    import types

    comfy_root, pack_dir = comfy_paths()
    for required in (comfy_root / "folder_paths.py", pack_dir / "loader.py"):
        if not required.exists():
            raise FileNotFoundError(f"required path missing: {required}")
    if str(comfy_root) not in sys.path:
        # loader.py imports comfy.* and folder_paths at module level.
        sys.path.insert(0, str(comfy_root))

    pkg_name = "firered_pack"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pack_dir)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    loader = importlib.import_module(f"{pkg_name}.loader")
    native = importlib.import_module(f"{pkg_name}.native")
    bundle = loader.load_firered_bundle(
        repo_choice=_env("OMNIVOICE_FIRERED_REPO", "FireRedTTS3-int8"),
        variant=_env("OMNIVOICE_FIRERED_VARIANT", "fireredtts3_base"),
        dtype_name="auto",
        device_name="auto",
        attention="auto",
        download_if_missing=True,
    )
    return native, bundle


def _stub_native():
    import numpy as np

    class _Stub:
        @staticmethod
        def tokenize_prompt_audio(bundle, waveform, sr):
            return ("stub-latents", int(waveform.shape[-1]))

        @staticmethod
        def speaker_embedding(bundle, waveform, sr):
            return "stub-spk"

        @staticmethod
        def base_clone_one(bundle, **kw):
            text = str(kw.get("text") or "")
            seconds = max(0.25, min(len(text) / 15.0, 4.0))
            t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
            wav = 0.25 * np.sin(2 * np.pi * 220.0 * t).astype("float32")
            return wav[None, :], SAMPLE_RATE

    return _Stub()


def _read_reference(path: str):
    """Reference clip as mono float32 + its sample rate."""
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    if mono.size == 0:
        raise ValueError(f"reference audio is empty: {path}")
    return np.ascontiguousarray(mono), int(sr)


def _to_waveform(mono):
    import torch

    return torch.from_numpy(mono).unsqueeze(0)


def _prompt_for(ref_path: str):
    """(prompt_latents, prompt_audio_len), spk_emb - cached per clip so the
    same speaker's reference is encoded once, not once per line."""
    try:
        mtime = os.path.getmtime(ref_path)
    except OSError:
        mtime = 0.0
    key = (ref_path, mtime)
    hit = _PROMPT_CACHE.get(key)
    if hit is not None:
        return hit
    mono, sr = _read_reference(ref_path)
    # The real pack wants a (1, T) torch tensor; the stub only reads .shape,
    # so stub mode stays torch-free (CI's requirements-dev has no torch).
    waveform = _to_waveform(mono) if not _STUB else mono
    entry = (
        _NATIVE.tokenize_prompt_audio(_BUNDLE, waveform, sr),
        _NATIVE.speaker_embedding(_BUNDLE, waveform, sr),
    )
    if len(_PROMPT_CACHE) >= 8:
        _PROMPT_CACHE.pop(next(iter(_PROMPT_CACHE)))
    _PROMPT_CACHE[key] = entry
    return entry


def _pcm16(audio) -> tuple[str, int]:
    """Model output -> base64 little-endian int16 PCM."""
    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    arr = np.asarray(audio, dtype="float32").reshape(-1)
    arr = np.clip(arr, -1.0, 1.0)
    pcm = (arr * 32767.0).round().astype("<i2")
    return base64.b64encode(pcm.tobytes()).decode("ascii"), int(pcm.size)


def _handle_synthesize(msg: dict) -> None:
    text = str(msg.get("text") or "")
    if not text.strip():
        raise ValueError("synthesize: text is required")
    ref_audio = str(msg.get("ref_audio") or "")
    if not ref_audio:
        raise ValueError(
            "synthesize: ref_audio is required (FireRedTTS3 clones a "
            "reference speaker; voice design is out of scope for this engine)"
        )
    if not Path(ref_audio).exists():
        raise ValueError(f"synthesize: ref_audio not found: {ref_audio}")

    # Lazy cold load: the spawn handshake accepts exactly one frame (ready),
    # while the generate recv loop re-arms its deadline on every progress
    # frame - so the slow part happens here, not before ready.
    if _NATIVE is None:
        try:
            _send({"op": "progress", "stage": "loading_model", "percent": 5})
            _load()
            _send({"op": "progress", "stage": "loading_model", "percent": 100})
        except Exception as exc:
            _send({
                "op": "error",
                "stage": "load",
                "message": f"{type(exc).__name__}: {exc}",
            })
            return

    ref_text = str(msg.get("ref_text") or "")
    language = language_tag(msg.get("language"))
    (prompt_latents, prompt_audio_len), spk_emb = _prompt_for(ref_audio)

    _send({"op": "progress", "stage": "synthesizing", "percent": 20})

    started = time.time()
    audio, sample_rate = _NATIVE.base_clone_one(
        _BUNDLE,
        text=text,
        language=language,
        prompt_text=ref_text,
        prompt_latents=prompt_latents,
        prompt_audio_len=prompt_audio_len,
        spk_emb=spk_emb,
        stop_threshold=_num(msg, "stop_threshold", 0.5),
        n_timesteps=int(_num(msg, "n_timesteps", 10)),
        inference_cfg=_num(msg, "inference_cfg", 2.0),
        seed=int(_num(msg, "seed", 1234)),
        max_gen_steps=_steps_for(msg, text),
    )
    pcm_b64, n_samples = _pcm16(audio)
    _send({
        "op": "audio",
        "audio_pcm_b64": pcm_b64,
        "sample_rate": int(sample_rate),
        "n_samples": n_samples,
    })
    print(
        f"[firered] {n_samples} samples in {time.time() - started:.2f}s",
        file=sys.stderr,
        flush=True,
    )


def _vram_mb() -> int:
    try:
        import torch

        if torch.cuda.is_available():
            return int(torch.cuda.memory_allocated() / (1024 * 1024))
    except Exception:
        pass
    return 0


def _load() -> None:
    """Cold load, once: progress frames are legal mid-generate."""
    global _NATIVE, _BUNDLE, _STUB
    _STUB = _env("OMNIVOICE_FIRERED_STUB") == "1"
    _NATIVE, _BUNDLE = _load_model(_STUB)


def main() -> int:
    stub = _env("OMNIVOICE_FIRERED_STUB") == "1"

    # The spawn handshake reads exactly one frame: ready (or error). A cold
    # load would take a minute of silence, so it runs lazily on the first
    # synthesize instead - a fast preflight catches a broken install early.
    if not stub:
        comfy_root, pack = comfy_paths()
        missing = [
            str(p)
            for p in (comfy_root / "folder_paths.py", pack / "loader.py")
            if not p.exists()
        ]
        if missing:
            _send({
                "op": "error",
                "stage": "load",
                "message": "required path missing: " + ", ".join(missing),
            })
            return 1
    _send({"op": "ready", "engine": ENGINE_ID, "sample_rate": SAMPLE_RATE})

    while True:
        try:
            msg = _recv()
        except Exception as exc:
            _send({
                "op": "error",
                "stage": "recv",
                "message": f"{type(exc).__name__}: {exc}",
            })
            return 1
        if msg is None:
            return 0  # parent closed the pipe
        op = msg.get("op")
        if op == "shutdown":
            return 0
        if op == "ping":
            _send({"op": "pong", "vram_mb": _vram_mb()})
            continue
        if op != "synthesize":
            _send({
                "op": "error",
                "stage": "dispatch",
                "message": f"unknown op: {op!r}",
            })
            continue
        try:
            _handle_synthesize(msg)
        except Exception as exc:
            _send({
                "op": "error",
                "stage": "synthesize",
                "message": f"{type(exc).__name__}: {exc}",
            })


def _privatize_frame_fd() -> None:
    """Frames go on a private fd; fd1 becomes stderr so every library that
    prints to stdout (torch, comfy, the pack) can't corrupt the protocol."""
    global _FRAME_FD
    _FRAME_FD = os.dup(1)
    os.dup2(2, 1)


if __name__ == "__main__":
    _privatize_frame_fd()
    sys.exit(main())
