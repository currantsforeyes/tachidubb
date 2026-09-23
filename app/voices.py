"""Voice preset library — built-in voice-design styles + user file presets.

Each built-in preset is a voice-design description plus a fixed seed. The seed
locks VoxCPM's random state so all segments in a job sound like the SAME voice
(voice design is non-deterministic by default per the VoxCPM docs).

User presets are audio files under ``presets/voices/`` with an optional
``<name>.json`` metadata sidecar (legacy ``<name>.txt`` is still read as a
description). Everything here is re-scanned on demand, so dropping a file into
the folder makes it usable immediately.

Extracted from ``server.py`` so the resolution/scanning logic is unit-testable
without the FastAPI app.
"""
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.config import VOICE_PRESETS_DIR

log = logging.getLogger("tachidubb.voices")


VOICE_PRESETS = {
    "auto": {
        "name": "Auto (use video voice if possible)",
        "style": "",
        "seed": None,  # random per-job
    },
    "male_warm": {
        "name": "Male — warm, middle-aged, calm",
        "style": "middle-aged male voice, warm and calm, clear articulation",
        "seed": 101,
    },
    "male_deep": {
        "name": "Male — deep, authoritative narrator",
        "style": "deep mature male voice, authoritative narrator, slow pace",
        "seed": 202,
    },
    "male_young": {
        "name": "Male — young, energetic",
        "style": "young adult male voice, energetic and friendly",
        "seed": 303,
    },
    "male_sports": {
        "name": "Male — sports instructor",
        "style": "grown adult male sports instructor, clear and steady, confident",
        "seed": 404,
    },
    "female_calm": {
        "name": "Female — warm, gentle",
        "style": "warm female voice, gentle and soothing, mid-tone",
        "seed": 505,
    },
    "female_narrator": {
        "name": "Female — professional narrator",
        "style": "professional female narrator, clear articulation, neutral tone",
        "seed": 606,
    },
    "female_young": {
        "name": "Female — young, cheerful",
        "style": "young adult female voice, friendly and cheerful",
        "seed": 707,
    },
}


VOICE_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")

_VOICE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,49}$")


def voice_metadata_path(audio_path: Path) -> Path:
    """Sidecar metadata file for a voice preset (<name>.json next to audio)."""
    return audio_path.with_suffix(".json")


def read_voice_metadata(audio_path: Path) -> dict:
    """Load JSON sidecar with structured metadata, falling back to legacy
    `<name>.txt` description if JSON doesn't exist. Always returns a dict."""
    j = voice_metadata_path(audio_path)
    if j.exists():
        try:
            return json.loads(j.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"[voice_presets] bad JSON in {j.name}: {e}")
    # Backward-compat: legacy .txt description file
    txt = audio_path.with_suffix(".txt")
    if txt.exists():
        try:
            return {"description": txt.read_text(encoding="utf-8").strip()[:300]}
        except Exception:
            pass
    return {}


def scan_file_presets() -> dict:
    """Scan presets/voices/ folder for voice references + their metadata.

    Each `<name>.{wav,mp3,flac,ogg,m4a}` becomes a file-based preset.
    Optional `<name>.json` sidecar carries structured metadata
    (description, gender, language, tags, created_at). Legacy `<name>.txt`
    is still read as the description for backward-compat.

    Re-scanned on every call — drop a file into the folder and it's available
    immediately, no restart needed.
    """
    presets = {}
    if not VOICE_PRESETS_DIR.exists():
        return presets
    for path in sorted(VOICE_PRESETS_DIR.iterdir()):
        if path.suffix.lower() not in VOICE_AUDIO_EXTS:
            continue
        meta = read_voice_metadata(path)
        pid = f"file:{path.stem}"
        presets[pid] = {
            "id": pid,
            "name": meta.get("display_name") or path.stem,
            "style": meta.get("style", ""),
            "seed": meta.get("seed"),
            "reference_file": str(path),
            "description": meta.get("description", ""),
            # Structured metadata for the Voices tab UI
            "gender": meta.get("gender", ""),         # 'male' | 'female' | 'neutral' | ''
            "language": meta.get("language", ""),     # iso code or empty
            "tags": meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
            "created_at": meta.get("created_at"),
            # File facts (computed, not stored)
            "file_size": path.stat().st_size if path.exists() else 0,
            "file_ext": path.suffix.lower().lstrip("."),
            "audio_url": f"/api/voice_presets/{pid}/audio",
        }
    return presets


def resolve_voice_config(voice_preset: str, voice_style: str, job_id: str):
    """Return (effective_voice_style, voice_seed, reference_file) for a run.

    reference_file is set ONLY when user picked a file-based preset
    from presets/voices/ folder. Otherwise it's empty string.
    """
    # Check file presets first (they live in a folder, re-scanned each call)
    file_presets = scan_file_presets()
    if voice_preset in file_presets:
        p = file_presets[voice_preset]
        return "", 0, p["reference_file"]

    preset = VOICE_PRESETS.get(voice_preset, VOICE_PRESETS["auto"])
    # Priority: explicit voice_style beats preset style (lets user override)
    eff_style = (voice_style or "").strip() or preset["style"]
    # Priority: preset seed > hash of voice_style > hash of job_id (random-ish)
    if preset.get("seed") is not None:
        seed = preset["seed"]
    elif eff_style:
        seed = int(hashlib.md5(eff_style.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF
    else:
        seed = int(hashlib.md5(job_id.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF
    return eff_style, seed, ""


def voice_preset_payload() -> dict:
    """Build the full presets list response used by both /api/voices
    and /api/voice_presets endpoints."""
    style_presets = [
        {"id": k, "name": v["name"], "style": v["style"], "type": "style"}
        for k, v in VOICE_PRESETS.items()
    ]
    file_presets = []
    for k, v in scan_file_presets().items():
        file_presets.append({
            "id": k, "name": v["name"], "style": v.get("style", ""),
            "type": "file",
            "description": v.get("description", ""),
            "reference_file": Path(v["reference_file"]).name,
            "gender": v.get("gender", ""),
            "language": v.get("language", ""),
            "tags": v.get("tags", []),
            "created_at": v.get("created_at"),
            "file_size": v.get("file_size", 0),
            "file_ext": v.get("file_ext", ""),
            "audio_url": v.get("audio_url"),
        })
    return {"presets": file_presets + style_presets}


def file_preset_path(preset_id: str) -> Optional[Path]:
    """Resolve a `file:NAME` preset id back to its actual audio file on
    disk, or None if not found / not a file preset."""
    if not preset_id.startswith("file:"):
        return None
    name = preset_id[len("file:"):]
    # No path traversal — the name is just a basename, must not contain separators
    if "/" in name or "\\" in name or ".." in name:
        return None
    for ext in VOICE_AUDIO_EXTS:
        p = VOICE_PRESETS_DIR / f"{name}{ext}"
        if p.exists():
            return p
    return None


def sanitize_voice_name(raw: str) -> Optional[str]:
    """Normalize a user-provided voice name to a filesystem-safe stem.
    Returns None if invalid (would let through path traversal or weird chars)."""
    if not raw:
        return None
    s = raw.strip()
    # Collapse internal whitespace runs, strip trailing dots
    s = re.sub(r"\s+", " ", s).rstrip(".")
    if not _VOICE_NAME_RE.match(s):
        return None
    return s