"""Route smoke tests — the app builds and key routes behave.

These lock in the app/routers split without needing a GPU, ffmpeg or a running
server. They intentionally do NOT enter the lifespan context (no DB/queue
startup), so they're fast and side-effect free.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_jobs_empty():
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert r.json() == {"jobs": []}


def test_storage_stats_empty():
    r = client.get("/api/storage/stats")
    assert r.status_code == 200
    assert r.json()["job_count"] == 0


def test_lip_sync_status_reports_engine():
    r = client.get("/api/lip_sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "musetalk"
    assert isinstance(body["installed"], bool)


def test_voices_lists_presets():
    r = client.get("/api/voices")
    assert r.status_code == 200
    assert "presets" in r.json()


def test_config_roundtrip_shape():
    r = client.get("/api/config")
    assert r.status_code == 200
    assert "voxcpm_cfg" in r.json()


def test_missing_job_is_404():
    assert client.get("/api/job/does-not-exist").status_code == 404


def test_index_is_served():
    assert client.get("/").status_code == 200


def test_index_references_local_bundle():
    html = client.get("/").text
    assert "/static/dist/app.js" in html
    assert "unpkg.com" not in html
    assert "text/babel" not in html


def test_static_bundle_is_served():
    r = client.get("/static/dist/app.js")
    assert r.status_code == 200
    assert len(r.content) > 1000