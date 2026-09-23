"""SQLite job store — persistence, large-field stripping, and JSON migration."""
import asyncio
import json

import pytest

import app.db as db


@pytest.fixture
def store(tmp_path):
    db._DB_PATH = None
    db.init_db(tmp_path / "tachidubb.db")
    yield tmp_path / "tachidubb.db"
    db._DB_PATH = None


def test_strip_large_fields_truncates_transcript():
    job = {"id": "x", "transcript": [{"i": i} for i in range(10)]}
    out = db._strip_large_fields(job)

    assert out["transcript"] == [{"i": i} for i in range(5)]
    assert out["transcript_truncated"] is True


def test_strip_large_fields_short_transcript_not_flagged():
    out = db._strip_large_fields({"id": "x", "transcript": [1, 2, 3]})
    assert out["transcript"] == [1, 2, 3]
    assert "transcript_truncated" not in out


def test_strip_large_fields_drops_transient_fields():
    out = db._strip_large_fields(
        {"id": "x", "transcript_raw": "big", "_pending_args": {"a": 1}}
    )
    assert "transcript_raw" not in out
    assert "_pending_args" not in out


def test_save_and_load_round_trip(store):
    job = {
        "id": "job1",
        "status": "complete",
        "created": 123.0,
        "transcript": [{"i": i} for i in range(10)],
        "_pending_args": {"x": 1},
    }
    db.save_job_sync(job)

    loaded = db.load_all_jobs()

    assert "job1" in loaded
    assert loaded["job1"]["status"] == "complete"
    assert loaded["job1"]["transcript"] == [{"i": i} for i in range(5)]
    assert loaded["job1"]["transcript_truncated"] is True
    assert "_pending_args" not in loaded["job1"]


def test_delete_job(store):
    db.save_job_sync({"id": "job1", "status": "queued", "created": 1.0})
    db.delete_job_db("job1")
    assert "job1" not in db.load_all_jobs()


def test_save_job_async(store):
    asyncio.run(db.save_job_async({"id": "job2", "status": "queued", "created": 2.0}))
    assert db.load_all_jobs()["job2"]["status"] == "queued"


def test_migrates_legacy_json_jobs(tmp_path):
    json_dir = tmp_path / "jobs_db"
    json_dir.mkdir()
    (json_dir / "legacy1.json").write_text(
        json.dumps({"id": "legacy1", "status": "complete", "created": 1.0}),
        encoding="utf-8",
    )

    db._DB_PATH = None
    db.init_db(tmp_path / "tachidubb.db")
    try:
        loaded = db.load_all_jobs()
        assert loaded["legacy1"]["status"] == "complete"
    finally:
        db._DB_PATH = None