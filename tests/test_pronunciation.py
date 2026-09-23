"""Pronunciation overrides for TTS (speech-only word rewriting)."""
import app.pronunciation as pron


def _use_file(monkeypatch, tmp_path):
    target = tmp_path / "pronunciation.json"
    monkeypatch.setattr(pron, "PRONUNCIATION_FILE", target)
    pron._cache.update(mtime=None, rules=[], compiled=[])
    return target


def test_validate_accepts_valid():
    assert pron.validate_rules({"rules": []}) is None
    assert pron.validate_rules({"rules": [{"from": "nginx", "to": "engine x"}]}) is None


def test_validate_rejects_malformed():
    assert pron.validate_rules([]) == "Top level must be an object"
    assert pron.validate_rules({"rules": {}}) == "'rules' must be an array"
    assert pron.validate_rules({"rules": ["x"]}) == "rules[0] must be an object"
    assert pron.validate_rules({"rules": [{"to": "x"}]}) == "rules[0].from must be a non-empty string"
    assert pron.validate_rules({"rules": [{"from": "x", "to": 5}]}) == "rules[0].to must be a string"


def test_apply_no_rules_is_noop(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    assert pron.apply("Hello world") == "Hello world"


def test_apply_is_case_insensitive_and_word_bounded(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    pron.save_rules({"rules": [{"from": "nginx", "to": "engine x"}]})

    assert pron.apply("Nginx is fast") == "engine x is fast"
    assert pron.apply("NGINX and nginx") == "engine x and engine x"
    # must not match inside a longer word
    assert pron.apply("nginxish") == "nginxish"


def test_apply_longest_rule_wins(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    pron.save_rules({"rules": [
        {"from": "riva", "to": "Y"},
        {"from": "de la riva", "to": "X"},
    ]})

    assert pron.apply("de la riva") == "X"


def test_apply_empty_replacement_drops_word(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    pron.save_rules({"rules": [{"from": "um", "to": ""}]})

    out = pron.apply("hello um world")
    assert "um" not in out
    assert out.startswith("hello") and out.endswith("world")


def test_clear_removes_rules(monkeypatch, tmp_path):
    target = _use_file(monkeypatch, tmp_path)
    pron.save_rules({"rules": [{"from": "a", "to": "b"}]})
    assert target.exists()

    pron.clear()
    assert not target.exists()
    assert pron.apply("a") == "a"