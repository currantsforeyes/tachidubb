"""TTS engine factory cache + GPU cleanup (extracted from server.py)."""
import app.tts as tts


def test_free_gpu_memory_does_not_raise():
    # Must be safe even when torch isn't available or CUDA is absent.
    tts.free_gpu_memory()


def test_get_cached_engine_defaults_to_none(monkeypatch):
    monkeypatch.setattr(tts, "_tts_engine", None)
    assert tts.get_cached_engine() is None


def test_get_tts_engine_returns_cached_without_building(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(tts, "_tts_engine", sentinel)
    assert tts.get_tts_engine() is sentinel
    assert tts.get_cached_engine() is sentinel


def test_spoken_text_prefers_tts_text():
    from pipeline.synthesizer import _spoken_text

    assert _spoken_text({"tts_text": "A", "translated_text": "B", "text": "C"}) == "A"
    assert _spoken_text({"translated_text": "B", "text": "C"}) == "B"
    assert _spoken_text({"text": "C"}) == "C"
    assert _spoken_text({"translated_text": "  B  "}) == "B"