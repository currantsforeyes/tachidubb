"""SQLite job store — persistence, large-field stripping, JSON import and
schema versioning (PRAGMA user_version migrations)."""
import asyncio
import json
import sqlite3

import pytest

import app.db as db


@pytest.fixture
def store(tmp_path):
    db._DB_PATH = None
    db.init_db(tmp_path / "tachidubb.db")
    yield tmp_path / "tachidubb.db"
    db._DB_PATH = None


def _user_version(path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


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


# ── schema versioning (PRAGMA user_version) ───────────────────────────
def test_fresh_db_is_stamped_with_current_version(store):
    assert _user_version(store) == db.SCHEMA_VERSION


def test_reinit_is_idempotent(store):
    """Second startup must not re-run migrations or touch data."""
    db.save_job_sync({"id": "job1", "status": "complete", "created": 1.0})
    db.init_db(store)

    assert _user_version(store) == db.SCHEMA_VERSION
    assert "job1" in db.load_all_jobs()


def test_preversioning_db_adopts_version_in_place(tmp_path):
    """A DB from before versioning (v0, table already exists) gets stamped
    without a table rebuild and keeps its rows."""
    path = tmp_path / "tachidubb.db"
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            data   TEXT NOT NULL,
            status TEXT GENERATED ALWAYS AS (json_extract(data, '$.status')) VIRTUAL,
            created REAL GENERATED ALWAYS AS (json_extract(data, '$.created')) VIRTUAL,
            batch_id TEXT GENERATED ALWAYS AS (json_extract(data, '$.batch_id')) VIRTUAL
        )
    """)
    conn.execute(
        "INSERT INTO jobs(job_id, data) VALUES(?, ?)",
        ("old_job", json.dumps({"id": "old_job", "status": "complete"})),
    )
    conn.commit()
    conn.close()
    assert _user_version(path) == 0  # pre-versioning state

    db._DB_PATH = None
    db.init_db(path)
    try:
        assert _user_version(path) == db.SCHEMA_VERSION
        assert "old_job" in db.load_all_jobs()
    finally:
        db._DB_PATH = None


def test_future_db_is_refused(tmp_path, monkeypatch):
    """A DB written by a newer build must not be opened (we'd guess at a
    schema we don't understand)."""
    path = tmp_path / "tachidubb.db"
    db._DB_PATH = None
    db.init_db(path)
    db._DB_PATH = None
    conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="newer TachiDUBB"):
        db.init_db(path)
    assert _user_version(path) == db.SCHEMA_VERSION + 1  # untouched


def test_failed_migration_rolls_back_schema_and_version(tmp_path, monkeypatch):
    """A migration that dies mid-step must leave neither its DDL nor its
    version bump behind — next startup retries from the old version."""
    path = tmp_path / "tachidubb.db"
    db._DB_PATH = None
    db.init_db(path)  # at current version
    db._DB_PATH = None
    good_version = db.SCHEMA_VERSION
    failing_version = good_version + 1

    def _half_applied(conn):
        conn.execute("CREATE TABLE half_applied (x TEXT)")  # survives if not txn'd
        raise ValueError("disk on fire")

    monkeypatch.setattr(db, "MIGRATIONS", {**db.MIGRATIONS, failing_version: _half_applied})
    monkeypatch.setattr(db, "SCHEMA_VERSION", failing_version)

    with pytest.raises(ValueError, match="disk on fire"):
        db.init_db(path)

    assert _user_version(path) == good_version  # bump rolled back
    conn = sqlite3.connect(str(path))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "half_applied" not in tables  # DDL rolled back too


def test_registry_version_mismatch_is_caught(tmp_path, monkeypatch):
    """SCHEMA_VERSION edited without registering the migration step."""
    path = tmp_path / "tachidubb.db"
    db._DB_PATH = None
    db.init_db(path)
    db._DB_PATH = None

    monkeypatch.setattr(db, "SCHEMA_VERSION", db.SCHEMA_VERSION + 1)

    with pytest.raises(RuntimeError, match="drifted apart"):
        db.init_db(path)