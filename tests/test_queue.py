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