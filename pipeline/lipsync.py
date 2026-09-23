"""Lip-sync backend — MuseTalk (real-time, MIT).

Lip-sync is an optional post-processing step that rewrites mouth movement in
the dubbed video so it matches the dubbed audio, making the result look much
less like a dub.

MuseTalk 1.5 (Tencent Music / Lyra Lab) is the default backend: it inpaints a
256x256 mouth region in latent space (single step, not diffusion), runs at
real-time speed, needs ~4 GB VRAM in fp16, and is MIT-licensed. It replaces the
old Wav2Lip backend (96x96, non-commercial weights).

Why not ship as a pip dependency of the main venv:
  - MuseTalk needs the OpenMMLab stack (mmcv/mmdet/mmpose), which is brittle
    and conflicts with the main app's torch/whisperx pins.
  - It therefore runs in its own project-local runtime (``musetalk-runtime``)
    via ``pipeline/musetalk_worker.py``, mirroring the isolated Qwen runtimes.

This module holds only detection + command construction (pure, unit-testable);
the actual subprocess orchestration lives in server.py.
"""
import logging
import os
from pathlib import Path
from typing import Optional

from app.config import BASE

log = logging.getLogger("tachidubb.lipsync")

LIPSYNC_ENGINE = "musetalk"
MUSETALK_REPO_URL = "https://github.com/TMElyralab/MuseTalk.git"

# Output filename produced in the job dir by a successful lip-sync pass.
LIPSYNC_OUTPUT_NAME = "dubbed_video_lipsync.mp4"

# Where a MuseTalk checkout might live (env override wins).
_MUSETALK_ENV_DIR = "TACHIDUBB_MUSETALK_DIR"
_MUSETALK_ENV_PYTHON = "TACHIDUBB_MUSETALK_PYTHON"


def candidate_repo_dirs() -> list:
    """Directories to scan for a MuseTalk checkout, most specific first."""
    dirs = []
    env_dir = os.getenv(_MUSETALK_ENV_DIR, "").strip()
    if env_dir:
        dirs.append(Path(env_dir))
    dirs += [
        BASE / "MuseTalk",
        BASE / "external" / "MuseTalk",
        BASE.parent / "MuseTalk",
        Path.home() / "MuseTalk",
    ]
    return dirs


def _default_runtime_python() -> Optional[Path]:
    """Project-local runtime interpreter created by install-musetalk.{bat,sh}."""
    if os.name == "nt":
        p = BASE / "musetalk-runtime" / "Scripts" / "python.exe"
    else:
        p = BASE / "musetalk-runtime" / "bin" / "python"
    return p if p.exists() else None


def resolve_runtime_python() -> Optional[str]:
    """Return the MuseTalk runtime interpreter path, or None if not installed."""
    env_py = os.getenv(_MUSETALK_ENV_PYTHON, "").strip()
    if env_py and Path(env_py).exists():
        return env_py
    default = _default_runtime_python()
    return str(default) if default else None


def _find_weights(repo_dir: Path) -> tuple:
    """Return (version, unet_path, config_path) or (None, None, None).

    Prefers MuseTalk 1.5 (``musetalkV15``) over 1.0 (``musetalk``).
    """
    models = repo_dir / "models"
    v15_unet = models / "musetalkV15" / "unet.pth"
    v15_cfg = models / "musetalkV15" / "musetalk.json"
    if v15_unet.exists() and v15_cfg.exists():
        return "v15", str(v15_unet), str(v15_cfg)
    v1_unet = models / "musetalk" / "pytorch_model.bin"
    v1_cfg = models / "musetalk" / "musetalk.json"
    if v1_unet.exists() and v1_cfg.exists():
        return "v1", str(v1_unet), str(v1_cfg)
    return None, None, None


def find_musetalk_setup() -> Optional[dict]:
    """Locate a usable MuseTalk install.

    Requires all three of: a checkout with the inference entry point, the
    model weights, and the dedicated runtime interpreter. Returns a dict or
    None (callers surface a guide instead).
    """
    for d in candidate_repo_dirs():
        if not d.exists():
            continue
        if not (d / "scripts" / "inference.py").exists():
            continue
        version, unet, config = _find_weights(d)
        if not unet:
            continue
        python = resolve_runtime_python()
        if not python:
            log.info("[lipsync] MuseTalk found at %s but runtime interpreter missing", d)
            continue
        return {
            "engine": LIPSYNC_ENGINE,
            "repo_dir": str(d),
            "python": python,
            "version": version,
            "unet_model_path": unet,
            "unet_config": config,
        }
    return None


def musetalk_install_guide() -> dict:
    """Structured install guide returned when MuseTalk isn't available."""
    return {
        "error": "musetalk_not_installed",
        "engine": LIPSYNC_ENGINE,
        "message": (
            "Lip-sync uses MuseTalk (optional). Install it only if you want mouth "
            "movement to match the dubbed audio. Works best on talking-head "
            "footage; useless for action / wide shots."
        ),
        "install_steps": [
            {"label": "1. One-time setup (creates an isolated runtime)",
             "cmd": f'cd "{BASE}" && install-musetalk.bat' if os.name == "nt"
                    else f'cd "{BASE}" && ./install-musetalk.sh'},
            {"label": "2. Restart TachiDUBB Studio",
             "cmd": "The lip-sync button lights up automatically once MuseTalk "
                    "and its weights are detected."},
        ],
        "steps": [
            "install-musetalk.bat   (Windows)  /  ./install-musetalk.sh   (Linux/macOS)",
            "Restart TachiDUBB Studio",
        ],
        "note": (
            "MuseTalk needs clear, roughly front-facing faces. It fails on fast "
            "cuts, extreme angles and low-res video. Budget roughly real-time "
            "processing (~1x video duration on a modern GPU)."
        ),
        "env_override": (
            f"If MuseTalk is already installed elsewhere, set {_MUSETALK_ENV_DIR}=<path> "
            f"and {_MUSETALK_ENV_PYTHON}=<python> in .env"
        ),
    }


def lipsync_status_payload() -> dict:
    """Response body for GET /api/lip_sync/status."""
    setup = find_musetalk_setup()
    if not setup:
        return {"installed": False, "engine": LIPSYNC_ENGINE,
                "guide": musetalk_install_guide()}
    return {
        "installed": True,
        "engine": LIPSYNC_ENGINE,
        "repo_dir": setup["repo_dir"],
        "version": setup["version"],
    }


# ── Command builders (pure) ──────────────────────────────────────────────
def extract_audio_cmd(src_video: str, dst_wav: str) -> list:
    """ffmpeg command: strip a 16 kHz mono PCM WAV from a video."""
    return [
        "ffmpeg", "-y", "-i", str(src_video),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(dst_wav),
    ]


def worker_cmd(python: str, worker_script: str, job_json: str) -> list:
    """Launch the MuseTalk worker in its isolated runtime."""
    return [python, "-u", str(worker_script), str(job_json)]


def remux_cmd(lipsynced_video: str, src_video: str, dst_video: str) -> list:
    """ffmpeg command: keep MuseTalk's video, restore the full-quality dub audio."""
    return [
        "ffmpeg", "-y",
        "-i", str(lipsynced_video),
        "-i", str(src_video),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        str(dst_video),
    ]


def build_worker_job(setup: dict, video: str, audio: str, out: str, ffmpeg_bin: str = "") -> dict:
    """Assemble the JSON spec consumed by pipeline/musetalk_worker.py."""
    return {
        "repo_dir": setup["repo_dir"],
        "version": setup["version"],
        "unet_model_path": setup["unet_model_path"],
        "unet_config": setup["unet_config"],
        "video_path": str(video),
        "audio_path": str(audio),
        "output_path": str(out),
        "ffmpeg_bin": ffmpeg_bin,
    }