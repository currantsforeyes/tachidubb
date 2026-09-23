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