"""Serial GPU job queue + scheduler plumbing (extracted from server.py)."""
import asyncio

import pytest

import app.queue as queue


@pytest.fixture(autouse=True)
def _fresh_queue(monkeypatch):
    monkeypatch.setattr(queue, "job_queue", None)
    monkeypatch.setattr(queue, "_run_pipeline", None)
    monkeypatch.setattr(queue, "_assemble_showcase", None)
    yield
    monkeypatch.setattr(queue, "job_queue", None)


def test_jobcancelled_is_exception():
    assert issubclass(queue.JobCancelled, Exception)


def test_init_queue_returns_queue():
    q = queue.init_queue()
    assert q is queue.get_queue()
    assert q.empty()


def test_configure_registers_hooks():
    def fn(*a, **k):
        return None

    def hook(*a, **k):
        return None

    queue.configure(fn, hook)
    assert queue._run_pipeline is fn
    assert queue._assemble_showcase is hook


def test_enqueue_marks_job_queued(monkeypatch):
    q = queue.init_queue()
    jobs = {"j1": {"id": "j1", "status": "created"}}
    monkeypatch.setattr(queue, "jobs", jobs)
    monkeypatch.setattr(queue, "save_job", lambda job: None)
    monkeypatch.setattr(queue, "_apply_sleep_prevention", lambda keep: None)

    asyncio.run(queue.enqueue_job("j1", {"target_lang": "fr"}))

    assert jobs["j1"]["status"] == "queued"
    assert jobs["j1"]["queue_position"] == 1
    assert q.qsize() == 1
    assert q.get_nowait() == ("j1", {"target_lang": "fr"})


def test_enqueue_activates_sleep_prevention(monkeypatch):
    queue.init_queue()
    monkeypatch.setattr(queue, "jobs", {"j1": {"id": "j1"}})
    monkeypatch.setattr(queue, "save_job", lambda job: None)
    calls = []
    monkeypatch.setattr(queue, "_apply_sleep_prevention", lambda keep: calls.append(keep))

    asyncio.run(queue.enqueue_job("j1", {}))

    assert calls == [True]


def test_enqueue_handles_unknown_job(monkeypatch):
    q = queue.init_queue()
    monkeypatch.setattr(queue, "jobs", {})
    monkeypatch.setattr(queue, "save_job", lambda job: None)
    monkeypatch.setattr(queue, "_apply_sleep_prevention", lambda keep: None)

    asyncio.run(queue.enqueue_job("ghost", {}))

    assert q.qsize() == 1


# ── _apply_sleep_prevention: the REAL function, Windows faked ────────
# ES_CONTINUOUS | ES_SYSTEM_REQUIRED, as declared in the implementation.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class _FakeKernel32:
    def __init__(self):
        self.calls = []

    def SetThreadExecutionState(self, flags):
        self.calls.append(flags)


@pytest.fixture
def fake_windll(monkeypatch):
    """Give `ctypes` a fake windll on any OS; reset the module's lock state."""
    import ctypes

    kernel32 = _FakeKernel32()
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": kernel32})(), raising=False)
    monkeypatch.setattr(queue, "_sleep_lock_active", False)
    return kernel32


def test_sleep_prevention_on_sets_flags_and_lock(fake_windll):
    queue._apply_sleep_prevention(True)

    assert fake_windll.calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]
    assert queue._sleep_lock_active is True


def test_sleep_prevention_is_idempotent_while_active(fake_windll):
    queue._apply_sleep_prevention(True)
    queue._apply_sleep_prevention(True)

    assert len(fake_windll.calls) == 1  # no duplicate Win32 call
    assert queue._sleep_lock_active is True


def test_sleep_prevention_off_releases(fake_windll):
    queue._apply_sleep_prevention(True)
    queue._apply_sleep_prevention(False)

    assert fake_windll.calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS]
    assert queue._sleep_lock_active is False


def test_sleep_prevention_off_without_lock_does_nothing(fake_windll):
    queue._apply_sleep_prevention(False)

    assert fake_windll.calls == []
    assert queue._sleep_lock_active is False


def test_sleep_prevention_noop_without_windll(monkeypatch):
    """The non-Windows path must return silently, not raise."""
    import ctypes

    monkeypatch.delattr(ctypes, "windll", raising=False)
    monkeypatch.setattr(queue, "_sleep_lock_active", False)

    queue._apply_sleep_prevention(True)  # must not raise

    assert queue._sleep_lock_active is False


def test_sleep_prevention_survives_a_failing_windll(monkeypatch):
    """A broken kernel32 call is logged, never propagated (queue must not die)."""
    import ctypes

    class _Exploding:
        class kernel32:
            @staticmethod
            def SetThreadExecutionState(flags):
                raise OSError("simulated Win32 failure")

    monkeypatch.setattr(ctypes, "windll", _Exploding(), raising=False)
    monkeypatch.setattr(queue, "_sleep_lock_active", False)

    queue._apply_sleep_prevention(True)  # must swallow the OSError

    assert queue._sleep_lock_active is False