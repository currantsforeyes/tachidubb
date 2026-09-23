"""Pronunciation overrides for TTS.

A small, user-editable dictionary that rewrites *how* a word is spoken without
changing the subtitles. Useful for names, acronyms and loanwords the TTS
mispronounces or stresses wrong (e.g. ``nginx`` -> ``engine x``,
``Kubernetes`` -> ``koo-ber-net-eez``).

Stored as JSON at ``presets/pronunciation.json``::

    { "rules": [ { "from": "nginx", "to": "engine x" }, ... ] }

Rules are applied case-insensitively on word boundaries, longest ``from``
first, to the text handed to the TTS engines (``segment["tts_text"]``) — never
to ``translated_text``, so on-screen subtitles keep the correct spelling.
"""
import json
import logging
import re
from typing import Optional

from app.config import PRONUNCIATION_FILE

log = logging.getLogger("tachidubb.pronunciation")

# Tiny mtime-based cache so we don't re-read/compile on every segment.
_cache: dict = {"mtime": None, "rules": [], "compiled": []}


def validate_rules(data) -> Optional[str]:
    """Return an error message if ``data`` is malformed, else None."""
    if not isinstance(data, dict):
        return "Top level must be an object"
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        return "'rules' must be an array"
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            return f"rules[{i}] must be an object"
        if not isinstance(r.get("from", ""), str) or not r.get("from", "").strip():
            return f"rules[{i}].from must be a non-empty string"
        if not isinstance(r.get("to", ""), str):
            return f"rules[{i}].to must be a string"
    return None


def load_rules() -> list:
    """Return the configured rules (``[]`` if the file is missing/invalid)."""
    if not PRONUNCIATION_FILE.exists():
        return []
    try:
        mtime = PRONUNCIATION_FILE.stat().st_mtime
    except OSError:
        return []
    if _cache["mtime"] == mtime:
        return _cache["rules"]
    try:
        data = json.loads(PRONUNCIATION_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"[pronunciation] could not read {PRONUNCIATION_FILE.name}: {e}")
        return []
    rules = [r for r in data.get("rules", []) if isinstance(r, dict) and r.get("from")]
    # Longest source first so "reverse de la riva" wins over "de la riva".
    rules.sort(key=lambda r: len(str(r.get("from", ""))), reverse=True)
    compiled = []
    for r in rules:
        try:
            compiled.append((
                re.compile(r"(?<!\w)" + re.escape(str(r["from"])) + r"(?!\w)", re.IGNORECASE),
                str(r.get("to", "")),
            ))
        except re.error as e:
            log.warning(f"[pronunciation] bad rule {r!r}: {e}")
    _cache.update(mtime=mtime, rules=rules, compiled=compiled)
    return rules


def apply(text: str) -> str:
    """Apply all pronunciation rules to ``text`` (no-op if none configured)."""
    if not text:
        return text
    load_rules()
    out = text
    for pattern, repl in _cache["compiled"]:
        out = pattern.sub(repl, out)
    return out


def save_rules(data: dict) -> None:
    """Persist the rules and invalidate the cache."""
    PRONUNCIATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRONUNCIATION_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _cache.update(mtime=None, rules=[], compiled=[])
    load_rules()


def clear() -> None:
    PRONUNCIATION_FILE.unlink(missing_ok=True)
    _cache.update(mtime=None, rules=[], compiled=[])