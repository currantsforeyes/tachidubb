"""MuseTalk subprocess worker.

Runs inside the isolated ``musetalk-runtime`` interpreter (created by
``install-musetalk.bat`` / ``.sh``), which carries MuseTalk's OpenMMLab
dependencies. The main TachiDUBB server never imports MuseTalk directly.

Usage (from app/lipsync.py):
    <musetalk-runtime>/python -u pipeline/musetalk_worker.py <job.json>

Where job.json is the dict produced by ``pipeline.lipsync.build_worker_job``::

    {
      "repo_dir": "...", "version": "v15",
      "unet_model_path": "...", "unet_config": "...",
      "video_path": "...", "audio_path": "...",
      "output_path": "...", "ffmpeg_bin": ""
    }

Emits one JSON line per event on stdout, e.g.::

    {"event": "preflight", "ok": true}
    {"event": "launch", "version": "v15", "repo": "..."}
    {"event": "done", "output": "...", "seconds": 93.2}

The worker validates its runtime deps, writes MuseTalk's required YAML config
into the checkout, invokes its ``scripts.inference`` module, then copies the
produced mp4 to output_path.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

# Deps that must be importable in the isolated runtime. Checked up-front so a
# broken/incomplete install fails with a clear message instead of mid-run.
# OpenMMLab (mmcv/mmpose) is NOT required: the preprocessing patch uses
# MuseTalk's vendored face detector instead (see PATCH_TEMPLATE below).
_REQUIRED_MODULES = ("torch",)

# Drop-in preprocessing that uses the vendored face detector instead of
# DWPose/mmcv, so MuseTalk runs on modern torch (cu128) — required for
# Blackwell (RTX 50) GPUs. See tools/musetalk_preprocessing_facealign.py.
PATCH_TEMPLATE = Path(__file__).resolve().parents[1] / "tools" / "musetalk_preprocessing_facealign.py"
PATCH_MARKER = "face detector mode (no DWPose)"


def apply_preprocessing_patch(repo: Path) -> bool:
    """Install the OpenMMLab-free preprocessing. Returns True if it wrote it."""
    dst = repo / "musetalk" / "utils" / "preprocessing.py"
    if not PATCH_TEMPLATE.exists() or not dst.parent.exists():
        return False
    try:
        current = dst.read_text(encoding="utf-8", errors="replace") if dst.exists() else ""
        if PATCH_MARKER in current:
            return False
        backup = dst.with_name("preprocessing.py.orig")
        if dst.exists() and not backup.exists():
            shutil.copyfile(dst, backup)
        dst.write_text(PATCH_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        event(event="patch_error", error=f"{type(exc).__name__}: {exc}")
        return False


def event(**payload) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def write_config(path: Path, video: str, audio: str) -> None:
    """Write the minimal MuseTalk inference config (its test.yaml format).

    Paths are single-quoted with forward slashes: YAML double-quoted scalars
    interpret backslashes as escapes, so a Windows path like ``D:\\MuseTalk``
    would fail to parse (``\\M`` is an unknown escape).
    """
    video = str(video).replace("\\", "/")
    audio = str(audio).replace("\\", "/")
    Path(path).write_text(
        "task_0:\n"
        f"  video_path: '{video}'\n"
        f"  audio_path: '{audio}'\n",
        encoding="utf-8",
    )


def newest_mp4(root: Path):
    files = list(Path(root).rglob("*.mp4"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def resolve_ffmpeg_bin(job: dict) -> str:
    """Directory containing ffmpeg for MuseTalk's --ffmpeg_path.

    Prefers the value the server resolved (which honours TACHIDUBB_FFMPEG_BIN),
    then falls back to `ffmpeg` on this runtime's PATH.
    """
    bin_dir = (job.get("ffmpeg_bin") or "").strip()
    if bin_dir and Path(bin_dir).is_dir():
        return bin_dir
    exe = shutil.which("ffmpeg")
    return str(Path(exe).parent) if exe else ""


def preflight() -> None:
    """Verify the runtime has its core deps; fatal with a clear message if not."""
    missing = []
    for mod in _REQUIRED_MODULES:
        try:
            __import__(mod)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{mod} ({type(exc).__name__})")
    if missing:
        event(event="fatal",
              error="MuseTalk runtime is missing dependencies: "
                    + ", ".join(missing)
                    + ". Re-run install-musetalk and try again.")
        sys.exit(1)
    event(event="preflight", ok=True)


def main(job_path: str) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    repo = Path(job["repo_dir"])
    out = Path(job["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)

    if not (repo / "scripts" / "inference.py").exists():
        event(event="fatal",
              error=f"MuseTalk checkout looks incomplete: {repo}/scripts/inference.py missing")
        sys.exit(1)

    event(event="preprocessing_patch", applied=apply_preprocessing_patch(repo))
    preflight()

    # Fresh per-run result dir so output discovery can't pick up a stale file.
    result_dir = out.parent / f"_musetalk_result_{int(time.time())}"
    result_dir.mkdir(parents=True, exist_ok=True)

    config = repo / "configs" / "inference" / "_tachidubb_auto.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    write_config(config, job["video_path"], job["audio_path"])

    cmd = [
        sys.executable, "-m", "scripts.inference",
        "--inference_config", str(config),
        "--result_dir", str(result_dir),
        "--unet_model_path", job["unet_model_path"],
        "--unet_config", job["unet_config"],
        "--version", job["version"],
    ]
    ffmpeg_bin = resolve_ffmpeg_bin(job)
    if ffmpeg_bin:
        cmd += ["--ffmpeg_path", ffmpeg_bin]

    event(event="launch", version=job["version"], repo=job["repo_dir"],
          ffmpeg_bin=ffmpeg_bin)
    started = time.time()
    # Force UTF-8 I/O in the child: MuseTalk prints CJK/log text that the
    # default Windows console codec (cp1252) cannot encode, which otherwise
    # aborts inference mid-run.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # MuseTalk loads legacy .tar checkpoints; torch >=2.6 defaults
    # torch.load(weights_only=True) and refuses them. This is the documented
    # escape hatch (trusted, locally-downloaded weights).
    env["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=3600, env=env,
        )
    except subprocess.TimeoutExpired:
        event(event="fatal", error="MuseTalk timed out after 60 minutes")
        sys.exit(1)

    if proc.returncode != 0:
        event(event="fatal",
              error=f"MuseTalk exited with code {proc.returncode}",
              stderr=(proc.stderr or "")[-1500:])
        sys.exit(1)

    # MuseTalk writes results/<name>/<version>.mp4; fall back to newest mp4.
    produced = result_dir / f"{job['version']}.mp4"
    if not produced.exists():
        produced = newest_mp4(result_dir)
    if produced is None or not Path(produced).exists():
        event(event="fatal", error="MuseTalk reported success but produced no mp4",
              stdout=(proc.stdout or "")[-800:])
        sys.exit(1)

    shutil.copyfile(produced, out)
    event(event="done", output=str(out), seconds=round(time.time() - started, 1))


if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            event(event="fatal", error="usage: musetalk_worker.py <job.json>")
            sys.exit(2)
        main(sys.argv[1])
    except Exception as exc:  # noqa: BLE001
        event(event="fatal", error=f"{type(exc).__name__}: {exc}",
              traceback=traceback.format_exc())
        sys.exit(1)