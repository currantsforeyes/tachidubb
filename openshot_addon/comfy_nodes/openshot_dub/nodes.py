"""OpenShotDubAudio — ComfyUI node: dub a clip and publish its tracks.

Why this shape (verified against OpenShot 4.0.1):

* OpenShot builds its ``Enhance with AI`` menu from workflow templates and, before
  POSTing the graph to ComfyUI, substitutes ``__openshot_input__`` with the file the
  user right-clicked and ``__openshot_prompt__`` with the text they type in the dialog
  (``classes/generation_service.py``: ``_is_placeholder_value`` / the
  ``_replace_prompt_placeholder`` chain). Our template feeds those into this node, so
  no OpenShot source edit is needed.
* After the run, ``ComfyClient.extract_file_outputs()`` scans the history entry for
  ``images|videos|video|gifs|audios|audio|files|filenames`` and collects
  ``{filename, subfolder, type}`` refs — **any** extension. ``_import_generation_outputs``
  then downloads each ref (its filename branch preserves the extension) and calls
  ``files_model.add_files()``, so the files land in **Project Files** ready for
  *Add to Timeline*. Returning bare ``.wav`` paths as text would instead be written
  out as a junk ``.txt``, which is why we publish real refs into ComfyUI's output tree.
* The pipeline runs as a **subprocess** via the serverless worker
  (``tools/dub_worker.py``): a dub takes minutes and needs whisperx/pyannote/demucs,
  which must not be installed into ComfyUI's embedded Python or block its executor.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACK_DIR / "config.json"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXTS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus"}


# ── helpers (module-level and side-effect free so they can be unit-tested) ──

def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    """Read config.json, with ``OPENSHOT_DUB_CONFIG`` overriding the location."""
    import os
    cfg_path = Path(os.environ.get("OPENSHOT_DUB_CONFIG", path))
    with open(cfg_path, encoding="utf-8-sig") as fh:
        cfg = json.load(fh)
    for key in ("runtime_root", "python", "worker", "outputs"):
        if key not in cfg:
            raise ValueError(f"config is missing '{key}': {cfg_path}")
    return cfg


def load_languages(path: Path = PACK_DIR / "languages.json") -> dict:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def resolve_language(text: str, langs: dict) -> str:
    """Map what the user typed onto an ISO code the pipeline accepts.

    Accepts a code (``en``), the display name (``English``), or a name with
    trailing notes (``English (UK)``); matching is case-insensitive. ``auto`` is
    rejected: dubbing needs an explicit target.
    """
    raw = str(text or "").strip().lower()
    if not raw:
        raise ValueError("No target language given — type one, e.g. English or en")
    if raw in ("auto", "auto-detect"):
        raise ValueError("Pick an explicit target language to dub into, not auto-detect")

    by_name = {name.strip().lower(): code for code, name in langs.items()}
    for candidate in (raw, raw.split("(")[0].strip(), raw.split()[0] if raw.split() else raw):
        if candidate in langs:
            return candidate
        if candidate in by_name:
            return by_name[candidate]

    # Last resort: the typed word starts a known name ("Eng…", "Japa…").
    for name, code in by_name.items():
        if name.startswith(raw) and len(raw) >= 3:
            return code

    supported = ", ".join(sorted(langs))
    raise ValueError(f"Unknown target language {text!r}. Try one of: {supported}")


def publish_outputs(paths, out_dir, subfolder: str = "openshot_dub") -> list:
    """Copy outputs into ComfyUI's output tree; return /view-compatible refs.

    OpenShot downloads refs through ComfyUI's ``/view`` endpoint, so the files
    must live under ComfyUI's output directory. Returns the ref dicts that
    ``extract_file_outputs`` expects: ``{filename, subfolder, type}``.
    """
    out_dir = Path(out_dir)
    target = out_dir / subfolder
    target.mkdir(parents=True, exist_ok=True)

    refs = []
    for raw in paths:
        src = Path(raw)
        if not src.is_file():
            continue
        dest = target / src.name
        if dest.exists() and dest.resolve() != src.resolve():
            # Never overwrite a previous import: unique-ify like OpenShot does.
            stem, ext = src.stem, src.suffix
            n = 2
            while dest.exists():
                dest = target / f"{stem}_{n}{ext}"
                n += 1
        if dest.resolve() != src.resolve():
            shutil.copy2(src, dest)
        refs.append({"filename": dest.name, "subfolder": subfolder, "type": "output"})
    return refs


def bucket_for(filename: str) -> str:
    """Which OpenShot-recognised key a ref belongs to (its scan key list)."""
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXTS:
        return "videos"
    if ext in AUDIO_EXTS:
        return "audios"
    return "files"


def collect_outputs(work_dir, patterns) -> list:
    """Expand config patterns against the job directory, stable order."""
    work_dir = Path(work_dir)
    seen, out = set(), []
    for pattern in patterns:
        for match in sorted(work_dir.glob(pattern)):
            if match.is_file() and match.resolve() not in seen:
                seen.add(match.resolve())
                out.append(match)
    return out


class _NoBar:
    """Progress sink used when the node runs outside ComfyUI (unit tests)."""

    def update_absolute(self, *args, **kwargs):
        pass

    def update(self, *args, **kwargs):
        pass


def _progress_bar(total: int = 100):
    try:
        from comfy.utils import ProgressBar
        return ProgressBar(total)
    except Exception:
        return _NoBar()


def _comfy_output_dir(cfg: dict) -> Path:
    if cfg.get("comfy_output"):
        return Path(cfg["comfy_output"])
    import folder_paths  # provided by ComfyUI at runtime
    return Path(folder_paths.get_output_directory())


# ── the node ──

class OpenShotDubAudio:
    """Dub ``source_path`` into ``target_language`` and publish the tracks."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Defaults are the placeholders OpenShot substitutes before
                # queueing, so the graph also works if hand-run in ComfyUI.
                "source_path": ("STRING", {"default": "__openshot_input__"}),
                "target_language": ("STRING", {"default": "__openshot_prompt__"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("published_files",)
    FUNCTION = "run"
    CATEGORY = "openshot"
    OUTPUT_NODE = True  # history carries our ui refs -> OpenShot imports them

    def run(self, source_path: str, target_language: str):
        cfg = load_config()
        lang = resolve_language(target_language, load_languages())

        source = Path(str(source_path).strip().strip('"'))
        if not source.is_file():
            raise FileNotFoundError(f"Source clip not found: {source}")

        root = Path(cfg["runtime_root"])
        python = Path(cfg["python"])
        worker = root / cfg["worker"]
        if not python.exists():
            raise FileNotFoundError(f"Runtime interpreter not found: {python}")
        if not worker.exists():
            raise FileNotFoundError(f"Worker not found: {worker}")

        spec = {
            "source": str(source),
            "target_lang": lang,
            "model": cfg.get("model", "aya-expanse:8b"),
            "whisper_model": cfg.get("whisper_model", "large-v3"),
            "tts_speed": cfg.get("tts_speed", "balanced"),
            "keep_bg": bool(cfg.get("keep_bg", True)),
            "narration_mode": bool(cfg.get("narration_mode", False)),
        }

        bar = _progress_bar(100)
        with tempfile.TemporaryDirectory(prefix="openshot_dub_") as tmp:
            tmp = Path(tmp)
            spec_path = tmp / "spec.json"
            status_path = tmp / "status.jsonl"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

            # stdout is discarded and progress flows through the status file:
            # a dead pipe can hang a minutes-long child process, and the worker's
            # protocol is designed to be read from either channel.
            proc = subprocess.Popen(
                [str(python), str(worker), "--spec", str(spec_path),
                 "--status-file", str(status_path)],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                events = _pump(status_path, proc, bar)
            finally:
                if proc.poll() is None:  # ComfyUI interrupted us: don't orphan it
                    proc.kill()
                    proc.wait(timeout=15)

        error = next((e for e in reversed(events) if e.get("type") == "error"), None)
        if error:
            raise RuntimeError(error.get("error") or "dub failed")
        if not any(e.get("type") == "done" for e in events):
            raise RuntimeError(f"dub worker exited with code {proc.returncode}")

        job_event = next((e for e in events if e.get("type") == "job"), {})
        work_dir = Path(job_event.get("work") or (root / "outputs"))
        outputs = collect_outputs(work_dir, cfg.get("outputs") or [])
        if not outputs:
            raise RuntimeError(f"dub finished but produced no matching outputs in {work_dir}")

        refs = publish_outputs(outputs, _comfy_output_dir(cfg))
        ui = {}
        for ref in refs:
            ui.setdefault(bucket_for(ref["filename"]), []).append(ref)

        bar.update_absolute(100)
        return {"ui": ui, "result": (json.dumps([r["filename"] for r in refs]),)}


def _pump(status_path: Path, proc, bar) -> list:
    """Tail the worker's NDJSON status file until the process exits.

    Returns every parsed event; unparseable lines are ignored (the protocol says
    a host must skip anything that isn't JSON with a ``type``).
    """
    events, seen, idle = [], 0, 0.0
    while True:
        if status_path.exists():
            lines = [ln for ln in status_path.read_text(
                encoding="utf-8-sig").splitlines() if ln.strip()]
            for line in lines[seen:]:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                events.append(event)
                if event.get("type") == "progress":
                    value = event.get("progress")
                    if isinstance(value, (int, float)):
                        bar.update_absolute(int(value))
            seen = len(lines)
        if proc.poll() is not None:
            break
        idle += 0.2
        time.sleep(0.2)
    return events
