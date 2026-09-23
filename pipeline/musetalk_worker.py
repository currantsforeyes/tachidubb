"""MuseTalk subprocess worker.

Runs inside the isolated ``musetalk-runtime`` interpreter (created by
``install-musetalk.bat`` / ``.sh``), which carries MuseTalk's OpenMMLab
dependencies. The main TachiDUBB server never imports MuseTalk directly.

Usage (from server.py):
    <musetalk-runtime>/python -u pipeline/musetalk_worker.py <job.json>

Where job.json is the dict produced by ``pipeline.lipsync.build_worker_job``::

    {
      "repo_dir": "...", "version": "v15",
      "unet_model_path": "...", "unet_config": "...",
      "video_path": "...", "audio_path": "...",
      "output_path": "...", "ffmpeg_bin": ""
    }

Emits one JSON line per event on stdout, e.g.::

    {"event": "launch", "cmd": [...]}
    {"event": "done", "output": "...", "seconds": 93.2}

The worker writes MuseTalk's required YAML config into the checkout, invokes
its ``scripts.inference`` module, then copies the produced mp4 to output_path.
"""
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path


def event(**payload) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def write_config(path: Path, video: str, audio: str) -> None:
    """Write the minimal MuseTalk inference config (its test.yaml format)."""
    Path(path).write_text(
        "task_0:\n"
        f'  video_path: "{video}"\n'
        f'  audio_path: "{audio}"\n',
        encoding="utf-8",
    )


def newest_mp4(root: Path):
    files = list(Path(root).rglob("*.mp4"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def main(job_path: str) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    repo = Path(job["repo_dir"])
    out = Path(job["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)

    # Fresh per-run result dir so "newest mp4" can't pick up a stale output.
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
    if job.get("ffmpeg_bin"):
        cmd += ["--ffmpeg_path", job["ffmpeg_bin"]]

    event(event="launch", version=job["version"], repo=job["repo_dir"])
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo), capture_output=True, text=True, timeout=3600,
        )
    except subprocess.TimeoutExpired:
        event(event="fatal", error="MuseTalk timed out after 60 minutes")
        sys.exit(1)

    if proc.returncode != 0:
        event(event="fatal",
              error=f"MuseTalk exited with code {proc.returncode}",
              stderr=(proc.stderr or "")[-1500:])
        sys.exit(1)

    produced = newest_mp4(result_dir)
    if not produced:
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