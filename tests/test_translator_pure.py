"""Pure helpers in the Ollama translator: response cleaning, script detection,
numbered-line parsing, and junk stripping."""
from pipeline.translator import (
    lang_name,
    _clean_response,
    _looks_untranslated,
    _parse_numbered,
    _strip_junk,
)


# ── lang_name ────────────────────────────────────────────────────────────
def test_lang_name_known_code():
    assert lang_name("fr") == "French"


def test_lang_name_is_case_insensitive():
    assert lang_name("FR") == "French"


def test_lang_name_uses_first_two_chars():
    assert lang_name("fr-CA") == "French"


def test_lang_name_unknown_code_falls_back_to_input():
    assert lang_name("xx") == "xx"


# ── _clean_response ──────────────────────────────────────────────────────
LT = chr(60)  # "<"
GT = chr(62)  # ">"


def test_clean_response_strips_qwen_think_block():
    text = f"{LT}think{GT}reasoning here{LT}/think{GT}Bonjour"
    assert _clean_response(text) == "Bonjour"


def test_clean_response_strips_stray_control_tokens():
    text = f"Bonjour{LT}|endoftext|{GT}"
    assert _clean_response(text) == "Bonjour"


def test_clean_response_strips_standalone_thinking_line():
    assert _clean_response("Thinking...\nBonjour") == "Bonjour"


def test_clean_response_strips_thinking_process_block():
    text = "Thinking Process:\n1. Analyze\n2. Translate\n\nBonjour"
    assert _clean_response(text) == "Bonjour"


# ── _looks_untranslated ──────────────────────────────────────────────────
def test_looks_untranslated_latin_text_for_cyrillic_target():
    assert _looks_untranslated("Hello world", "ru") is True


def test_looks_untranslated_matching_script():
    assert _looks_untranslated("Привет мир", "ru") is False


def test_looks_untranslated_too_short_to_judge():
    assert _looks_untranslated("Hi", "ru") is False


def test_looks_untranslated_unknown_target_is_false():
    assert _looks_untranslated("Hello", "xx") is False


def test_looks_untranslated_empty_text():
    assert _looks_untranslated("   ", "ru") is False


# ── _parse_numbered ──────────────────────────────────────────────────────
def test_parse_numbered_bracket_format():
    assert _parse_numbered("[1] Привет\n[2] Пока", 2) == {1: "Привет", 2: "Пока"}


def test_parse_numbered_dot_and_paren_formats():
    assert _parse_numbered("1. one\n2) two", 2) == {1: "one", 2: "two"}


def test_parse_numbered_falls_back_to_bare_lines():
    assert _parse_numbered("alpha\nbeta", 2) == {1: "alpha", 2: "beta"}


# ── _strip_junk ──────────────────────────────────────────────────────────
def test_strip_junk_removes_quotes_and_numbering():
    assert _strip_junk('  "1. Hello"  ') == "Hello"


def test_strip_junk_removes_leading_dash():
    assert _strip_junk("- item") == "item"