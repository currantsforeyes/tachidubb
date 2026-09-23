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


class _FakeProc:
    def __init__(self):
        self.killed = False

    def poll(self):
        return None

    def kill(self):
        self.killed = True


def test_recycle_threshold_parsing(monkeypatch):
    from pipeline.synthesizer import VoxCPMSynthesizer

    monkeypatch.setenv("TACHIDUBB_TTS_RECYCLE_SEGMENTS", "5")
    assert VoxCPMSynthesizer._recycle_threshold() == 5
    monkeypatch.setenv("TACHIDUBB_TTS_RECYCLE_SEGMENTS", "not-an-int")
    assert VoxCPMSynthesizer._recycle_threshold() == 400


def test_recycle_worker_after_threshold(monkeypatch):
    from pipeline.synthesizer import VoxCPMSynthesizer

    monkeypatch.setenv("TACHIDUBB_TTS_RECYCLE_SEGMENTS", "5")
    s = VoxCPMSynthesizer()
    proc = _FakeProc()
    s._worker_proc = proc

    s._maybe_recycle_worker(3)
    assert s._worker_proc is proc  # below threshold

    s._maybe_recycle_worker(2)     # cumulative 5 -> recycle
    assert s._worker_proc is None
    assert proc.killed is True


def test_recycle_disabled_by_zero(monkeypatch):
    from pipeline.synthesizer import VoxCPMSynthesizer

    monkeypatch.setenv("TACHIDUBB_TTS_RECYCLE_SEGMENTS", "0")
    s = VoxCPMSynthesizer()
    s._worker_proc = _FakeProc()

    s._maybe_recycle_worker(100000)
    assert s._worker_proc is not None