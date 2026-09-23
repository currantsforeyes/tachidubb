"""Shared job-store state (extracted from server.py)."""
import pytest

import app.db as db
import app.state as state


@pytest.fixture
def store(tmp_path):
    db._DB_PATH = None
    db.init_db(tmp_path / "tachidubb.db")
    state.jobs.clear()
    yield
    state.jobs.clear()
    db._DB_PATH = None


def test_save_job_persists(store):
    state.save_job({"id": "c", "status": "complete", "created": 1.0})
    assert db.load_all_jobs()["c"]["status"] == "complete"


def test_load_marks_stale_active_jobs_resumable(store):
    db.save_job_sync({"id": "a", "status": "transcribing", "created": 1.0})
    db.save_job_sync({"id": "b", "status": "complete", "created": 1.0})

    state.load_jobs_from_disk()

    assert state.jobs["a"]["status"] == "error"
    assert state.jobs["a"]["stale_from_restart"] is True
    assert "Resume" in state.jobs["a"]["error"]
    assert state.jobs["b"]["status"] == "complete"
    # the stale marking is persisted back to disk
    assert db.load_all_jobs()["a"]["status"] == "error"


def test_load_preserves_prior_error_message(store):
    db.save_job_sync({"id": "a", "status": "queued", "created": 1.0, "error": "prior boom"})
    state.load_jobs_from_disk()
    assert state.jobs["a"]["error"] == "prior boom"


def test_load_loads_all_persisted_jobs(store):
    db.save_job_sync({"id": "x", "status": "complete", "created": 1.0})
    db.save_job_sync({"id": "y", "status": "error", "created": 2.0})
    state.load_jobs_from_disk()
    assert set(state.jobs) == {"x", "y"}


def test_jobs_is_stable_dict(store):
    ref = state.jobs
    state.load_jobs_from_disk()
    assert state.jobs is ref


def test_active_statuses_cover_pipeline_stages():
    assert {"queued", "transcribing", "translating", "synthesizing"} <= state.ACTIVE_STATUSES