"""System routes: health, model management, config, preferences, glossary.

Second route group extracted from ``server.py``. Depends on ``app.config``,
``app.tts``, ``app.glossary`` and the pipeline's models/translator modules.
"""
import asyncio
import json
import logging
import os

import httpx
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import cfg, PREFS_FILE, PRONUNCIATION_FILE, USER_GLOSSARY_FILE
from app.glossary import GLOSSARY_EXAMPLE, total_terms, validate_glossary
from app.pronunciation import clear as clear_pronunciation
from app.pronunciation import save_rules as save_pronunciation
from app.pronunciation import validate_rules as validate_pronunciation
from app.tts import get_tts_engine
from pipeline.models import MODEL_CATALOG, get_system_status
from pipeline.synthesizer import VoxCPMSynthesizer
from pipeline.translator import check_ollama, ollama_pull_stream

log = logging.getLogger("tachidubb.routes.system")

router = APIRouter()


@router.get("/api/system")
async def system_status():
    status = get_system_status()
    ollama_ok, ollama_models = await check_ollama()
    status["ollama"] = {
        "ok": ollama_ok,
        "models": ollama_models,
        "binary": status["ollama_binary"]["ok"],
    }
    status["catalog"] = MODEL_CATALOG

    tts_ready = status["voxcpm"]["ok"] or status["edge_tts"]["ok"]
    ready = (
        status["python"]["ok"] and
        status["ffmpeg"]["ok"] and
        status["yt_dlp"]["ok"] and
        status["whisper"]["ok"] and
        tts_ready and
        ollama_ok and
        len(ollama_models) > 0
    )
    status["ready"] = ready
    return status


@router.post("/api/models/pull")
async def pull_model(model: str = Form(...)):
    async def stream():
        try:
            async for event in ollama_pull_stream(model):
                total = event.get("total", 0)
                completed = event.get("completed", 0)
                st = event.get("status", "")
                pct = int(completed / total * 100) if total else 0
                payload = {"status": st, "completed": completed, "total": total, "percent": pct}
                yield f"data: {json.dumps(payload)}\n\n"
            yield f"data: {json.dumps({'status': 'success', 'percent': 100})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/api/models/delete")
async def delete_model(model: str = Form(...)):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(
                f"{os.getenv('OLLAMA_URL', 'http://localhost:11434')}/api/delete",
                json={"name": model},
            )
            if r.status_code == 200:
                return {"ok": True}
            return JSONResponse({"error": r.text}, 400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.post("/api/voxcpm/warmup")
async def voxcpm_warmup():
    try:
        tts = get_tts_engine()
        if isinstance(tts, VoxCPMSynthesizer):
            if not tts.is_loaded:
                await asyncio.get_event_loop().run_in_executor(None, tts.load)
            return {"ok": True, "loaded": True}
        return {"ok": True, "loaded": False, "fallback": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.get("/api/preferences")
async def get_preferences():
    """Return saved UI preferences (last-used models, voice, speed, etc).
    The UI uses localStorage as primary but falls back to this when
    localStorage is unavailable (private browsing, cross-device, etc)."""
    if not PREFS_FILE.exists():
        return {}
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Could not read prefs: {e}")
        return {}


@router.post("/api/preferences")
async def set_preferences(prefs: str = Form(...)):
    """Update UI preferences. Merges into existing prefs; doesn't replace."""
    try:
        new_prefs = json.loads(prefs)
        if not isinstance(new_prefs, dict):
            raise ValueError("prefs must be a JSON object")
    except Exception as e:
        return JSONResponse({"error": f"Invalid prefs JSON: {e}"}, 400)
    existing = {}
    if PREFS_FILE.exists():
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update(new_prefs)
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.get("/api/config")
async def get_config():
    """Return current UserConfig as JSON. Editable fields shown in Settings tab."""
    return cfg.to_dict()


@router.patch("/api/config")
async def patch_config(body: str = Form(...)):
    """Update one or more UserConfig fields and persist to config-user.json."""
    try:
        updates = json.loads(body)
        if not isinstance(updates, dict):
            raise ValueError("body must be a JSON object")
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, 400)
    try:
        cfg.update(**updates)
        return {"ok": True, "config": cfg.to_dict()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


# ── Glossary — user-editable term overrides ──────────────────────────────
# Built-in BJJ glossary lives in translator.py; users add their own domain
# terms here (sidecar JSON at presets/user_glossary.json).


@router.get("/api/glossary")
async def get_glossary():
    """Return the current user glossary JSON + metadata. If the file
    doesn't exist, return an example structure so the UI has something
    sensible to show as the starting template."""
    if not USER_GLOSSARY_FILE.exists():
        return {
            "exists": False,
            "data": GLOSSARY_EXAMPLE,
            "hint": "File will be created on first save. Built-in BJJ glossary stays active.",
        }
    try:
        with open(USER_GLOSSARY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"exists": True, "data": data}
    except Exception as e:
        return JSONResponse({
            "exists": True,
            "error": f"Could not parse glossary file: {e}",
            "raw_text": USER_GLOSSARY_FILE.read_text(encoding="utf-8", errors="replace"),
        }, 500)


@router.post("/api/glossary")
async def set_glossary(body: str = Form(...)):
    """Replace the user glossary. Validates structure server-side so a
    malformed save doesn't break the translator.

    Accepts:
      { "domains": [ { name, triggers, target_lang, terms }, ... ] }
    """
    try:
        data = json.loads(body)
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, 400)
    error = validate_glossary(data)
    if error:
        return JSONResponse({"error": error}, 400)

    # Ensure parent dir exists
    USER_GLOSSARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(USER_GLOSSARY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        n_domains = len(data.get("domains", []))
        n_terms = total_terms(data)
        log.info(f"[glossary] Saved {n_domains} domain(s), {n_terms} term(s) total")
        return {
            "ok": True,
            "domains": n_domains,
            "total_terms": n_terms,
            "path": str(USER_GLOSSARY_FILE),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.delete("/api/glossary")
async def delete_glossary():
    """Remove the user glossary file entirely. Built-in BJJ terms still
    apply; this just clears user additions."""
    if USER_GLOSSARY_FILE.exists():
        try:
            USER_GLOSSARY_FILE.unlink()
            log.info("[glossary] User glossary file removed")
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, 500)
    return {"ok": True, "note": "File didn't exist"}


# ── Pronunciation overrides — how TTS says a word (not the subtitle) ──────


@router.get("/api/pronunciation")
async def get_pronunciation():
    """Return the pronunciation rule set + metadata."""
    if not PRONUNCIATION_FILE.exists():
        return {
            "exists": False,
            "data": {"rules": []},
            "hint": "Rules rewrite what TTS speaks without changing subtitles, "
                    'e.g. {"from": "nginx", "to": "engine x"}.',
        }
    try:
        data = json.loads(PRONUNCIATION_FILE.read_text(encoding="utf-8"))
        return {"exists": True, "data": data}
    except Exception as e:
        return JSONResponse({
            "exists": True,
            "error": f"Could not parse pronunciation file: {e}",
            "raw_text": PRONUNCIATION_FILE.read_text(encoding="utf-8", errors="replace"),
        }, 500)


@router.post("/api/pronunciation")
async def set_pronunciation(body: str = Form(...)):
    """Replace the pronunciation rules.

    Accepts ``{ "rules": [ { "from": "...", "to": "..." }, ... ] }``.
    """
    try:
        data = json.loads(body)
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, 400)
    error = validate_pronunciation(data)
    if error:
        return JSONResponse({"error": error}, 400)
    try:
        save_pronunciation(data)
        n = len(data.get("rules", []))
        log.info(f"[pronunciation] Saved {n} rule(s)")
        return {"ok": True, "rules": n, "path": str(PRONUNCIATION_FILE)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.delete("/api/pronunciation")
async def delete_pronunciation():
    """Remove all pronunciation rules."""
    clear_pronunciation()
    log.info("[pronunciation] Rules cleared")
    return {"ok": True}