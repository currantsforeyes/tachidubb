"""TTS QA scoring — text normalization, CER, and the accept threshold."""
import pytest

from pipeline.tts_qa import _cer, _normalize_text, is_acceptable


def test_cer_identical_strings_is_zero():
    assert _cer("abc", "abc") == 0.0


def test_cer_single_substitution():
    assert _cer("abc", "abd") == pytest.approx(1 / 3)


def test_cer_known_levenshtein_distance():
    # kitten -> sitting is 3 edits, denominator is len(reference) = 7
    assert _cer("kitten", "sitting") == pytest.approx(3 / 7)


def test_cer_empty_hypothesis_with_reference_is_one():
    assert _cer("", "abc") == 1.0


def test_cer_empty_reference_with_hypothesis_is_one():
    assert _cer("abc", "") == 1.0


def test_cer_both_empty_is_zero():
    assert _cer("", "") == 0.0


def test_normalize_lowercases_and_strips_punctuation():
    assert _normalize_text("Hello, World!") == "hello world"


def test_normalize_collapses_whitespace():
    assert _normalize_text("  multiple \t spaces  ") == "multiple spaces"


def test_normalize_keeps_cyrillic():
    assert _normalize_text("Привет, мир!") == "привет мир"


def test_normalize_empty_string():
    assert _normalize_text("") == ""


def test_is_acceptable_default_threshold():
    assert is_acceptable(0.3) is True
    assert is_acceptable(0.4) is True
    assert is_acceptable(0.41) is False


def test_is_acceptable_env_override(monkeypatch):
    monkeypatch.setenv("TACHIDUBB_QA_THRESHOLD", "0.9")
    assert is_acceptable(0.8) is True

    monkeypatch.delenv("TACHIDUBB_QA_THRESHOLD")
    assert is_acceptable(0.8) is False