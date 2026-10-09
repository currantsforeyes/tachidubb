"""FireRedTTS3 daemon worker — synthesis on **ComfyUI's Python**, not ours.

Why a different interpreter: FireRedTTS3 wants Transformers 5.3+ and lives in
``ComfyUI-Easy-Install`` (transformers 5.14, torch 2.11, comfy_kitchen for the
INT8 weights), while TachiDUBB's own venv runs transformers 4.57 — upgrading it
would risk the whisperx/pyannote stack the dubbing depends on. So the engine
spawns *this* file with ComfyUI's ``python_embeded\\python.exe`` and the model,
weights and quantization handling all stay on that side of the fence.

Rather than reimplement INT8 ConvRot loading, sdpa selection and weight
downloads, we import the FireRedTTS3-ComfyUI pack's own ``loader``/``native``
modules. The pack uses relative imports (``from . import int8``), so it is bound
as a synthetic package whose ``__path__`` points at the pack folder — that way
its ``__init__.py`` (which registers ComfyUI nodes) never runs, and
``loader.py``'s module-level ``comfy.*`` / ``folder_paths`` imports resolve
because ComfyUI's root is on ``sys.path``.

Protocol (identical shape to tts_worker.py, so the engine's client loop is
shared): one JSON event per line on stdout until ``{"event": "job_done"}``,
then the daemon blocks on stdin reading the next job path. stderr goes to a
file in the parent — a PIPE buffer is only 8 KB on Windows and a stack trace
would hang the child.

Usage::

    firered_worker.py --daemon <job.json>
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import types
from pathlib import Path

# ISO code -> the language tag FireRedTTS3 expects inside <|...|>.
# Kept beside the worker because it is FireRed-specific knowledge; the pipeline
# speaks ISO codes everywhere else. tests/test_firered_worker.py pins it against
# frontend/src/constants.js so a language added to the UI cannot silently miss
# the ability to be dubbed with this engine.
LANGUAGE_TAGS = {
    "en": "English", "ru": "Russian", "es": "Spanish", "pt": "Portuguese",
    "fr": "French", "de": "German", "it": "Italian", "pl": "Polish",
    "tr": "Turkish", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
    "ar": "Arabic", "hi": "Hindi", "nl": "Dutch",
}

# 25 latent frames per second, 4 latents per AR step -> 6.25 steps per second
# of audio. Taken from the ComfyUI pack's own _max_gen_steps().
STEPS_PER_SECOND = 25.0 / 4.0

# Safety net against a stop-token failure. Left unchecked, the model falls back
# to its hard ceiling of 400 steps = 64s of audio, which on a 1.02s window then
# sat underneath the rest of the dub as ~10s of double speech. Anchor the cap to
# the source window instead: real translations run well inside 2x the window,
# and tiny fragments still get enough steps to speak.
MAX_WINDOW_FACTOR = 2.0
MIN_AUDIO_SECONDS = 2.0


def max_gen_steps_for(slot_seconds) -> int:
    """AR-step budget for a segment, from the source window it belongs to."""
    seconds = max(float(slot_seconds) * MAX_WINDOW_FACTOR, MIN_AUDIO_SECONDS)
    return max(6, int(round(seconds * STEPS_PER_SECOND)))


def emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def language_tag(iso_code: str) -> str:
    code = str(iso_code or "").strip().lower()
    if code not in LANGUAGE_TAGS:
        raise ValueError(
            f"FireRedTTS3 has no tag for language {iso_code!r} "
            f"(known: {', '.join(sorted(LANGUAGE_TAGS))})")
    return LANGUAGE_TAGS[code]


def load_reference_audio(path) -> "object":
    """Reference clip as a mono (1, T) float tensor — what the pack expects."""
    import numpy as np
    import soundfile as sf
    import torch

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    if mono.size == 0:
        raise ValueError(f"reference audio is empty: {path}")
    return torch.from_numpy(np.ascontiguousarray(mono)).unsqueeze(0), sr


def _load_backend(cfg: dict):
    """Import the pack and load the bundle. Separated so tests can fake it."""
    comfy_root = Path(cfg["comfy_root"])
    pack_dir = Path(cfg["pack_dir"])
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
        repo_choice=cfg.get("repo", "FireRedTTS3-int8"),
        variant=cfg.get("variant", "fireredtts3_base"),
        dtype_name=cfg.get("dtype", "auto"),
        device_name=cfg.get("device", "auto"),
        attention=cfg.get("attention", "auto"),
        download_if_missing=bool(cfg.get("download_if_missing", True)),
    )
    return native, bundle


def run_job(job: dict, native, bundle) -> None:
    """Synthesize every segment of one job, emitting progress as we go."""
    defaults = job.get("defaults") or {}
    segments = job.get("segments") or []
    if not segments:
        raise ValueError("job has no segments")

    # Reference clip -> latents + speaker embedding, once per distinct clip:
    # cloning conditions on the reference, so every segment spoken by the same
    # speaker reuses the same cached encoding instead of re-running CAM++.
    prompt_cache: dict = {}

    for i, seg in enumerate(segments):
        idx = seg.get("idx", i)
        ref_path = seg.get("prompt_audio") or ""
        if not ref_path:
            raise ValueError(f"segment {idx}: no prompt_audio (reference clip)")
        if ref_path not in prompt_cache:
            waveform, sr = load_reference_audio(ref_path)
            prompt_cache[ref_path] = (
                native.tokenize_prompt_audio(bundle, waveform, sr),
                native.speaker_embedding(bundle, waveform, sr),
            )
        (prompt_latents, prompt_audio_len), spk_emb = prompt_cache[ref_path]

        out_path = Path(seg["output"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        slot = float(seg.get("slot_seconds") or 0.0)
        started = time.time()
        audio, sample_rate = native.base_clone_one(
            bundle,
            text=str(seg["text"]),
            language=language_tag(seg.get("language", "en")),
            prompt_text=str(seg.get("prompt_text") or ""),
            prompt_latents=prompt_latents,
            prompt_audio_len=prompt_audio_len,
            spk_emb=spk_emb,
            stop_threshold=float(defaults.get("stop_threshold", 0.5)),
            n_timesteps=int(defaults.get("n_timesteps", 10)),
            inference_cfg=float(defaults.get("inference_cfg", 2.0)),
            seed=int(defaults.get("seed", 1234)),
            # Window-anchored budget. Without it the core falls back to 400
            # steps = 64s, and one stop-token failure produced a 64s clip for a
            # 1.02s window that then played under the rest of the dub.
            max_gen_steps=(max_gen_steps_for(slot) if slot > 0 else None),
        )
        _save(audio, out_path, sample_rate)
        produced = float(audio.shape[-1]) / float(sample_rate)
        event = {"event": "segment", "idx": idx, "ok": True,
                 "path": str(out_path), "sample_rate": int(sample_rate),
                 "audio_seconds": round(produced, 2),
                 "seconds": round(time.time() - started, 2)}
        if slot > 0 and produced > slot * MAX_WINDOW_FACTOR + 0.25:
            # Not fatal (the assembler tolerates spill) but worth surfacing:
            # this is what a run-up-to-the-cap clip looks like.
            event["overrun"] = round(produced - slot, 2)
        emit(event)


def _save(audio, out_path: Path, sample_rate: int) -> None:
    """Write the clip. base_clone_one returns (1, T)."""
    import soundfile as sf

    data = audio.detach().cpu().float().numpy()
    while data.ndim > 1:
        data = data[0]
    if data.size == 0:
        raise RuntimeError(f"model returned no audio for {out_path.name}")
    sf.write(str(out_path), data, int(sample_rate))


def process_job_file(path) -> None:
    job = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    backend = job.get("backend") or {}
    emit({"event": "loading", "model": backend.get("repo", "FireRedTTS3")})
    started = time.time()
    native, bundle = _load_backend(backend)
    emit({"event": "loaded", "seconds": round(time.time() - started, 2)})
    run_job(job, native, bundle)


def main_daemon(first_job: str) -> None:
    """Load once, serve the first job, then wait for more job paths on stdin."""
    try:
        process_job_file(first_job)
    except Exception as exc:  # noqa: BLE001 - reported, then keep the daemon
        emit({"event": "fatal", "error": f"{type(exc).__name__}: {exc}"})
    emit({"event": "job_done"})

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            process_job_file(line)
        except Exception as exc:  # noqa: BLE001
            emit({"event": "fatal", "error": f"{type(exc).__name__}: {exc}"})
        emit({"event": "job_done"})


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "--daemon":
        print(json.dumps({"event": "fatal",
                          "error": "usage: firered_worker.py --daemon <job.json>"}))
        return 2
    main_daemon(sys.argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
