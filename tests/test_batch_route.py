"""Guard the /api/dub/batch file branch after it moved to app.submit.

The route now delegates job creation to ``app.submit.create_file_job``; this
pins the resulting job shape so the refactor can't silently change it.
"""
import time

from fastapi.testclient import TestClient

import app.routers.dub as dub_routes
import app.submit as submit
from app.main import app

client = TestClient(app)


def _isolate(monkeypatch, tmp_path):
    """Fresh job store, no DB writes, capture enqueues."""
    store = {}
    enq = []
    monkeypatch.setattr(submit, "jobs", store)
    monkeypatch.setattr(submit, "save_job", lambda job: None)

    async def fake_enqueue(job_id, args):
        enq.append((job_id, args))

    monkeypatch.setattr(submit, "enqueue_job", fake_enqueue)
    monkeypatch.setattr(dub_routes, "UPLOAD_DIR", tmp_path)

    async def fake_resolve(model):
        return model, None

    monkeypatch.setattr(dub_routes, "resolve_model", fake_resolve)
    return store, enq


def test_batch_upload_creates_file_job(monkeypatch, tmp_path):
    store, enq = _isolate(monkeypatch, tmp_path)

    r = client.post(
        "/api/dub/batch",
        data={"target_lang": "fr", "model": "aya-expanse:8b"},
        files={"videos": ("clip.mp4", b"fakevideo", "video/mp4")},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    jid = body["job_ids"][0]

    job = store[jid]
    assert job["source_type"] == "file"
    assert job["source_label"] == "clip.mp4"
    assert job["target_lang"] == "fr"
    assert job["batch_id"] == body["batch_id"]
    assert job["status"] == "queued"
    assert job["narration_mode"] is False
    assert (tmp_path / f"{jid}.mp4").exists()
    assert enq and enq[0][0] == jid


def test_batch_upload_scheduled_is_deferred(monkeypatch, tmp_path):
    store, enq = _isolate(monkeypatch, tmp_path)

    r = client.post(
        "/api/dub/batch",
        data={
            "target_lang": "fr",
            "model": "aya-expanse:8b",
            "scheduled_at": str(time.time() + 3600),
        },
        files={"videos": ("clip.mp4", b"fakevideo", "video/mp4")},
    )

    assert r.status_code == 200
    jid = r.json()["job_ids"][0]
    assert store[jid]["status"] == "scheduled"
    assert store[jid]["_pending_args"]["target_lang"] == "fr"
    assert enq == []