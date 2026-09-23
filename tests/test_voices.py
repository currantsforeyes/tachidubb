"""Voice preset library extracted from server.py."""
import hashlib
import json

import app.voices as voices


# ── sanitize_voice_name ──────────────────────────────────────────────────
def test_sanitize_accepts_simple_name():
    assert voices.sanitize_voice_name("My Voice") == "My Voice"


def test_sanitize_collapses_whitespace_and_strips_trailing_dots():
    assert voices.sanitize_voice_name("  Alice   Smith... ") == "Alice Smith"


def test_sanitize_rejects_empty():
    assert voices.sanitize_voice_name("") is None
    assert voices.sanitize_voice_name("   ") is None


def test_sanitize_rejects_leading_dash():
    assert voices.sanitize_voice_name("-bad") is None


def test_sanitize_rejects_path_separators():
    assert voices.sanitize_voice_name("a/b") is None
    assert voices.sanitize_voice_name("a\\b") is None


def test_sanitize_rejects_too_long():
    assert voices.sanitize_voice_name("A" + "b" * 60) is None


# ── metadata helpers ─────────────────────────────────────────────────────
def test_voice_metadata_path_swaps_suffix(tmp_path):
    assert voices.voice_metadata_path(tmp_path / "x.wav") == tmp_path / "x.json"


def test_read_voice_metadata_from_json(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"")
    (tmp_path / "a.json").write_text(json.dumps({"display_name": "Alice"}), encoding="utf-8")
    assert voices.read_voice_metadata(audio)["display_name"] == "Alice"


def test_read_voice_metadata_legacy_txt(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"")
    (tmp_path / "a.txt").write_text("  a nice voice  ", encoding="utf-8")
    assert voices.read_voice_metadata(audio) == {"description": "a nice voice"}


def test_read_voice_metadata_missing_returns_empty(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"")
    assert voices.read_voice_metadata(audio) == {}


# ── scan_file_presets ────────────────────────────────────────────────────
def test_scan_returns_empty_for_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path / "nope")
    assert voices.scan_file_presets() == {}


def test_scan_reads_audio_and_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path)
    (tmp_path / "alice.wav").write_bytes(b"12345")
    (tmp_path / "alice.json").write_text(json.dumps({
        "display_name": "Alice",
        "gender": "female",
        "language": "en",
        "tags": ["calm"],
        "description": "soft spoken",
    }), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

    presets = voices.scan_file_presets()

    assert set(presets) == {"file:alice"}
    p = presets["file:alice"]
    assert p["name"] == "Alice"
    assert p["gender"] == "female"
    assert p["tags"] == ["calm"]
    assert p["file_ext"] == "wav"
    assert p["file_size"] == 5
    assert p["audio_url"] == "/api/voice_presets/file:alice/audio"


def test_scan_ignores_non_audio_files(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path)
    (tmp_path / "readme.md").write_text("x", encoding="utf-8")
    assert voices.scan_file_presets() == {}


# ── resolve_voice_config ─────────────────────────────────────────────────
def test_resolve_prefers_file_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path)
    ref = tmp_path / "bob.wav"
    ref.write_bytes(b"")

    eff_style, seed, ref_file = voices.resolve_voice_config("file:bob", "", "job1")

    assert eff_style == ""
    assert seed == 0
    assert ref_file == str(ref)


def test_resolve_builtin_preset_uses_fixed_seed():
    eff_style, seed, ref_file = voices.resolve_voice_config("male_deep", "", "job1")
    assert eff_style == voices.VOICE_PRESETS["male_deep"]["style"]
    assert seed == 202
    assert ref_file == ""


def test_resolve_explicit_style_overrides_but_keeps_seed():
    eff_style, seed, _ = voices.resolve_voice_config("male_deep", "custom style", "job1")
    assert eff_style == "custom style"
    assert seed == 202


def test_resolve_auto_derives_seed_from_style():
    eff_style, seed, _ = voices.resolve_voice_config("auto", "a style", "job1")
    expected = int(hashlib.md5(b"a style").hexdigest()[:8], 16) & 0x7FFFFFFF
    assert eff_style == "a style"
    assert seed == expected


def test_resolve_auto_derives_seed_from_job_id_when_no_style():
    _eff, seed_a, _ = voices.resolve_voice_config("auto", "", "job-abc")
    _eff, seed_b, _ = voices.resolve_voice_config("auto", "", "job-abc")
    assert seed_a == seed_b
    expected = int(hashlib.md5(b"job-abc").hexdigest()[:8], 16) & 0x7FFFFFFF
    assert seed_a == expected


def test_resolve_unknown_preset_falls_back_to_auto():
    eff_style, seed, ref = voices.resolve_voice_config("does_not_exist", "", "job1")
    assert eff_style == ""
    assert ref == ""
    assert seed == int(hashlib.md5(b"job1").hexdigest()[:8], 16) & 0x7FFFFFFF


# ── voice_preset_payload ─────────────────────────────────────────────────
def test_payload_lists_file_then_style_presets(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path)
    (tmp_path / "carol.mp3").write_bytes(b"")

    payload = voices.voice_preset_payload()
    ids = [p["id"] for p in payload["presets"]]

    assert ids[0] == "file:carol"
    assert "auto" in ids
    file_entry = payload["presets"][0]
    assert file_entry["type"] == "file"
    assert file_entry["reference_file"] == "carol.mp3"
    style_entry = next(p for p in payload["presets"] if p["id"] == "auto")
    assert style_entry["type"] == "style"


# ── file_preset_path ─────────────────────────────────────────────────────
def test_file_preset_path_resolves_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path)
    ref = tmp_path / "dave.flac"
    ref.write_bytes(b"")
    assert voices.file_preset_path("file:dave") == ref


def test_file_preset_path_rejects_non_file_id():
    assert voices.file_preset_path("male_deep") is None


def test_file_preset_path_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path)
    assert voices.file_preset_path("file:../secret") is None


def test_file_preset_path_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICE_PRESETS_DIR", tmp_path)
    assert voices.file_preset_path("file:absent") is None