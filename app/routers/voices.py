"""Voice-preset routes: list, audio streaming, create, update, delete.

Third route group extracted from ``server.py``. All domain logic already lives
in ``app.voices``; these handlers are thin HTTP glue.
"""
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import VOICE_PRESETS_DIR
from app.voices import (
    VOICE_AUDIO_EXTS,
    file_preset_path,
    read_voice_metadata,
    sanitize_voice_name,
    scan_file_presets,
    voice_metadata_path,
    voice_preset_payload,
)

log = logging.getLogger("tachidubb.routes.voices")

router = APIRouter()


@router.get("/api/voices")
async def list_voice_presets():
    """List all available voice presets (built-in styles + user file presets)."""
    return voice_preset_payload()


@router.get("/api/voice_presets")
async def list_voice_presets_v2():
    """Alias for /api/voices — preferred name for new clients (CLI, MCP)."""
    return voice_preset_payload()


@router.get("/api/voice_presets/{preset_id}/audio")
async def get_voice_preset_audio(preset_id: str):
    """Stream the audio file behind a file-based preset. Used by the
    Voices tab's inline player and the dub form's preview."""
    p = file_preset_path(preset_id)
    if not p:
        return JSONResponse({"error": "Preset not found or not a file preset"}, 404)
    media = {
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".ogg": "audio/ogg", ".m4a": "audio/mp4",
    }.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=media, filename=p.name)


@router.post("/api/voice_presets")
async def create_voice_preset(
    audio: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    gender: str = Form(""),
    language: str = Form(""),
    tags: str = Form(""),                  # comma-separated
    style: str = Form(""),
):
    """Upload a new voice reference. Saves the audio as
    `presets/voices/<name>.<ext>` and writes a JSON sidecar with the
    structured metadata. Re-upload with the same name overwrites.

    The new preset is immediately usable in any dub form (id = `file:<name>`).
    """
    clean = sanitize_voice_name(name)
    if not clean:
        return JSONResponse({
            "error": "Name must be 1-50 chars, letters/digits/space/dash/underscore, "
                     "starting with a letter or digit."
        }, 400)

    if not audio.filename:
        return JSONResponse({"error": "No audio file provided"}, 400)
    ext = Path(audio.filename).suffix.lower()
    if ext not in VOICE_AUDIO_EXTS:
        return JSONResponse({
            "error": f"Unsupported audio extension '{ext}'. Use one of: "
                     f"{', '.join(VOICE_AUDIO_EXTS)}"
        }, 400)

    VOICE_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = VOICE_PRESETS_DIR / f"{clean}{ext}"
    # If a file with same stem but different ext already exists, remove the
    # old one so we don't keep duplicates (e.g. user re-uploads as mp3).
    for old_ext in VOICE_AUDIO_EXTS:
        old = VOICE_PRESETS_DIR / f"{clean}{old_ext}"
        if old.exists() and old != audio_path:
            try:
                old.unlink()
            except Exception as e:
                log.warning(f"[voice_presets] couldn't remove old {old.name}: {e}")

    try:
        with open(audio_path, "wb") as f:
            shutil.copyfileobj(audio.file, f)
    except Exception as e:
        return JSONResponse({"error": f"Couldn't save audio: {e}"}, 500)

    # Normalize tags
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    meta = {
        "display_name": clean,
        "description": (description or "").strip()[:500],
        "gender": (gender or "").strip().lower(),
        "language": (language or "").strip().lower(),
        "tags": tag_list,
        "style": (style or "").strip()[:300],
        "created_at": time.time(),
    }
    try:
        voice_metadata_path(audio_path).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"[voice_presets] couldn't write metadata: {e}")

    log.info(f"[voice_presets] created '{clean}' ({audio_path.stat().st_size} bytes)")
    pid = f"file:{clean}"
    return {"ok": True, "id": pid, "preset": scan_file_presets().get(pid, {})}


@router.put("/api/voice_presets/{preset_id}")
async def update_voice_preset(
    preset_id: str,
    name: Optional[str] = Form(None),       # rename
    description: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
):
    """Update metadata for a file-based preset. Optionally rename it
    (renames the audio file + sidecar). Fields left as None are preserved."""
    src_audio = file_preset_path(preset_id)
    if not src_audio:
        return JSONResponse({"error": "File preset not found"}, 404)

    # Load existing metadata, then merge in updates
    meta = read_voice_metadata(src_audio)
    if description is not None:
        meta["description"] = description.strip()[:500]
    if gender is not None:
        meta["gender"] = gender.strip().lower()
    if language is not None:
        meta["language"] = language.strip().lower()
    if tags is not None:
        meta["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if style is not None:
        meta["style"] = style.strip()[:300]

    # Rename if a new name was given
    final_audio = src_audio
    new_id = preset_id
    if name is not None:
        clean = sanitize_voice_name(name)
        if not clean:
            return JSONResponse({"error": "Invalid name"}, 400)
        new_audio = VOICE_PRESETS_DIR / f"{clean}{src_audio.suffix}"
        if new_audio.exists() and new_audio != src_audio:
            return JSONResponse({"error": f"A preset named '{clean}' already exists"}, 409)
        if new_audio != src_audio:
            old_meta_path = voice_metadata_path(src_audio)
            old_txt_path = src_audio.with_suffix(".txt")
            src_audio.rename(new_audio)
            if old_meta_path.exists():
                old_meta_path.rename(voice_metadata_path(new_audio))
            if old_txt_path.exists():
                old_txt_path.rename(new_audio.with_suffix(".txt"))
            final_audio = new_audio
            new_id = f"file:{clean}"
            meta["display_name"] = clean

    try:
        voice_metadata_path(final_audio).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        return JSONResponse({"error": f"Couldn't save metadata: {e}"}, 500)

    log.info(f"[voice_presets] updated '{final_audio.stem}'")
    return {"ok": True, "id": new_id, "preset": scan_file_presets().get(new_id, {})}


@router.delete("/api/voice_presets/{preset_id}")
async def delete_voice_preset(preset_id: str):
    """Delete a file-based preset (audio + metadata sidecars).
    Built-in style presets cannot be deleted."""
    p = file_preset_path(preset_id)
    if not p:
        return JSONResponse({"error": "File preset not found"}, 404)
    try:
        p.unlink()
        for sidecar in (voice_metadata_path(p), p.with_suffix(".txt")):
            if sidecar.exists():
                sidecar.unlink()
    except Exception as e:
        return JSONResponse({"error": f"Couldn't delete: {e}"}, 500)
    log.info(f"[voice_presets] deleted '{preset_id}'")
    return {"ok": True, "id": preset_id}