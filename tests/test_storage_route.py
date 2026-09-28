"""POST /api/storage/cleanup — the bulk-delete contract the System tab reads.

Pins two things the storage UI depends on:

  * the response keys ``affected`` / ``mb_freed``. The tab once read
    ``affected_count`` / ``freed_mb``, which the server never emitted, so
    every preview claimed "0 job(s), ? MB" and the buttons looked broken.
  * ``older_than_days=0`` selecting *every* settled job. The UI's smallest
    preset used to be 1 day, which made jobs created today impossible to
    clear — the exact "no way to clear all previous generations" report.

Both tests use ``dry_run`` so nothing touches disk beyond the tmp fixture.
"""
import time

import app.routers.storage as storage_routes
import app.storage as storage_mod
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

JOB = "cleanupjob"


def _seed(tmp_path, monkeypatch, created):
    """One settled job whose output dir holds 4 KB of junk."""
    monkeypatch.setattr(storage_mod, "OUTPUT_DIR", tmp_path)
    # Patch the router's own reference so stray jobs left in the shared
    # store by other tests can't change what the candidates selector sees.
    monkeypatch.setattr(storage_routes, "jobs", {JOB: {
        "id": JOB, "created": created, "status": "complete",
    }})
    work = tmp_path / JOB
    work.mkdir()
    (work / "seg0.wav").write_bytes(b"\0" * 4096)


def _cleanup(**form):
    data = {
        "older_than_days": "0",
        "mode": "intermediate",
        "dry_run": "true",
        "include_errored": "true",
        "include_cancelled": "true",
    }
    data.update({k: str(v) for k, v in form.items()})
    return client.post("/api/storage/cleanup", data=data)


def test_cleanup_reports_the_keys_the_ui_reads(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, created=time.time() - 5 * 86400)

    body = _cleanup().json()

    assert body["affected"] == 1
    assert isinstance(body["mb_freed"], float)
    assert body["bytes_freed"] == 4096
    assert body["candidates"] == 1
    # The names the UI used to read — they must never come back, or the
    # regression this test pins would be invisible from the server side.
    assert "affected_count" not in body
    assert "freed_mb" not in body


def test_zero_days_selects_a_job_created_today(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, created=time.time())  # made a moment ago

    last_day = _cleanup(older_than_days=1).json()
    everything = _cleanup(older_than_days=0).json()

    assert last_day["affected"] == 0      # what the old 1-day minimum gave you
    assert everything["affected"] == 1    # the "All" preset


def test_cleanup_never_touches_starred_or_running_jobs(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, created=time.time())
    storage_routes.jobs[JOB]["starred"] = True

    assert _cleanup().json()["affected"] == 0

    storage_routes.jobs[JOB]["starred"] = False
    storage_routes.jobs[JOB]["status"] = "running"

    assert _cleanup().json()["affected"] == 0
