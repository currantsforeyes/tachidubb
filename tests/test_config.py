"""UserConfig — validation, persistence, and env > file > defaults layering."""
import json

import pytest

import app.config as config


def test_set_unknown_key_raises():
    c = config.UserConfig()
    with pytest.raises(KeyError):
        c.set("does_not_exist", 1)


def test_set_persists_to_disk(tmp_path, monkeypatch):
    target = tmp_path / "config-user.json"
    monkeypatch.setattr(config, "CONFIG_FILE", target)

    c = config.UserConfig()
    c.set("whisper_model", "small")

    assert json.loads(target.read_text(encoding="utf-8"))["whisper_model"] == "small"


def test_update_persists_and_ignores_unknown(tmp_path, monkeypatch):
    target = tmp_path / "config-user.json"
    monkeypatch.setattr(config, "CONFIG_FILE", target)

    c = config.UserConfig()
    c.update(whisper_model="tiny", bogus_key=123)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["whisper_model"] == "tiny"
    assert "bogus_key" not in data


def test_to_dict_contains_defaults():
    d = config.UserConfig().to_dict()
    assert d["voxcpm_cfg"] == 2.0
    assert "whisper_model" in d
    assert d["translation_mode"] == "single"


def test_translation_mode_env_override(monkeypatch):
    monkeypatch.setenv("TACHIDUBB_TRANSLATION_MODE", "staged")
    assert config._load_config().translation_mode == "staged"


def test_load_config_reads_file(tmp_path, monkeypatch):
    target = tmp_path / "config-user.json"
    target.write_text(json.dumps({"whisper_model": "medium"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", target)
    monkeypatch.delenv("WHISPER_MODEL", raising=False)

    assert config._load_config().whisper_model == "medium"


def test_load_config_env_overrides_file(tmp_path, monkeypatch):
    target = tmp_path / "config-user.json"
    target.write_text(json.dumps({"whisper_model": "medium"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", target)
    monkeypatch.setenv("WHISPER_MODEL", "tiny")

    assert config._load_config().whisper_model == "tiny"


def test_load_config_missing_file_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "nope.json")
    monkeypatch.delenv("WHISPER_MODEL", raising=False)

    assert config._load_config().whisper_model == "large-v3"


def test_env_is_loaded_before_config_builds_its_singleton():
    """app/config.py reads os.environ while building its module-level ``cfg``.

    app/main.py therefore has to load .env *before* importing it — otherwise
    every setting documented in .env.example (HF_TOKEN, OLLAMA_URL,
    TACHIDUBB_TTS_ENGINE, the ComfyUI root) is read too late and silently
    ignored, which is how it behaved before this ordering was fixed.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
        encoding="utf-8")
    call = re.search(r"^_load_dotenv_simple\(\)\s*$", src, re.M)
    assert call, "the .env loader must be called at module level"
    assert call.start() < src.index("from app.config import BASE"), (
        ".env must be loaded before app.config is imported, or cfg never sees it")