"""Pure helpers in the Ollama translator: response cleaning, script detection,
numbered-line parsing, and junk stripping."""
import asyncio

from pipeline.translator import (
    lang_name,
    _clean_response,
    _looks_untranslated,
    _parse_numbered,
    _strip_junk,
    _build_clean_prompt,
    _build_narration_prompt,
    _staged_batch,
    _default_backend,
    _call_openai,
    _call_model,
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


# ── staged translation prompts ───────────────────────────────────────────
def test_clean_prompt_mentions_editing_and_format():
    p = _build_clean_prompt("[1] (1.0s) hello world")
    assert "text editor" in p
    assert "Merge sentences" in p
    assert "[1] (1.0s) hello world" in p


def test_narration_prompt_names_target_language():
    p = _build_narration_prompt("Russian", "[1] привет")
    assert "Russian" in p
    assert "shorter" in p.lower()
    assert "[1] привет" in p


# ── _staged_batch ────────────────────────────────────────────────────────
def _fake_ollama(monkeypatch, responses, record):
    def factory():
        it = iter(responses)

        async def fake(url, model, prompt, **kwargs):
            record.append(prompt)
            return next(it)

        return fake
    monkeypatch.setattr("pipeline.translator._call_ollama", factory())


def test_staged_batch_runs_clean_translate_narrate(monkeypatch):
    calls = []
    _fake_ollama(monkeypatch, ["cleaned", "translated", "adapted"], calls)

    out = asyncio.run(_staged_batch("u", "m", "English", "Russian", "[1] hi", ""))

    assert out == "adapted"
    assert len(calls) == 3
    assert "text editor" in calls[0]          # clean step
    assert "Russian" in calls[1]              # translate step
    assert "Russian" in calls[2]              # narration step


def test_staged_batch_returns_none_when_clean_fails(monkeypatch):
    async def boom(url, model, prompt, **kwargs):
        raise RuntimeError("ollama down")
    monkeypatch.setattr("pipeline.translator._call_ollama", boom)

    assert asyncio.run(_staged_batch("u", "m", "English", "Russian", "[1] hi", "")) is None


def test_staged_batch_returns_none_on_empty_translation(monkeypatch):
    calls = []
    _fake_ollama(monkeypatch, ["cleaned", "   "], calls)

    assert asyncio.run(_staged_batch("u", "m", "English", "Russian", "[1] hi", "")) is None


def test_staged_batch_narration_step_is_optional(monkeypatch):
    calls = []

    async def fake(url, model, prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 3:
            raise RuntimeError("narration failed")
        return "cleaned" if len(calls) == 1 else "translated"

    monkeypatch.setattr("pipeline.translator._call_ollama", fake)

    # Falls back to the translation when only the narration step fails.
    assert asyncio.run(_staged_batch("u", "m", "English", "Russian", "[1] hi", "")) == "translated"


# ── OpenAI-compatible backend ────────────────────────────────────────────
def test_default_backend_env(monkeypatch):
    monkeypatch.delenv("TACHIDUBB_TRANSLATION_BACKEND", raising=False)
    assert _default_backend() == "ollama"
    monkeypatch.setenv("TACHIDUBB_TRANSLATION_BACKEND", "OpenAI")
    assert _default_backend() == "openai"


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    last = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeClient.last = (url, headers, json)
        return _FakeResp({"choices": [{"message": {"content": "Bonjour"}}]})


def test_call_openai_builds_request(monkeypatch):
    import pipeline.translator as T
    monkeypatch.setattr(T.httpx, "AsyncClient", _FakeClient)

    out = asyncio.run(_call_openai("http://localhost:1234/v1/", "qwen2.5", "hello", api_key="secret"))

    assert out == "Bonjour"
    url, headers, payload = _FakeClient.last
    assert url == "http://localhost:1234/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret"
    assert payload["model"] == "qwen2.5"
    assert payload["messages"][0]["content"] == "hello"


def test_call_openai_omits_auth_without_key(monkeypatch):
    import pipeline.translator as T
    monkeypatch.setattr(T.httpx, "AsyncClient", _FakeClient)

    asyncio.run(_call_openai("http://localhost:1234/v1", "m", "p"))

    assert "Authorization" not in _FakeClient.last[1]


def test_call_model_routes_by_backend(monkeypatch):
    import pipeline.translator as T
    routed = []

    async def fake_openai(url, model, prompt, api_key="", timeout=240.0):
        routed.append("openai")
        return "O"

    async def fake_ollama(url, model, prompt, timeout=240.0):
        routed.append("ollama")
        return "L"

    monkeypatch.setattr(T, "_call_openai", fake_openai)
    monkeypatch.setattr(T, "_call_ollama", fake_ollama)

    assert asyncio.run(_call_model("openai", "u", "m", "p")) == "O"
    assert asyncio.run(_call_model("ollama", "u", "m", "p")) == "L"
    assert asyncio.run(_call_model("", "u", "m", "p")) == "L"  # default
    assert routed == ["openai", "ollama", "ollama"]