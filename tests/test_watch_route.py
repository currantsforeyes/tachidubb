"""HTTP tests for the folder-watcher routes (/api/watch/*).

The watcher's *logic* (candidates, mtime grace, moves, error recording) is
covered by ``test_watcher.py``. This file pins the HTTP surface: response
shapes, form validation, and — most importantly — that the routes are actually
wired to the real ``app.watcher`` functions.

Patch points matter here:

- ``app/routers/watch.py`` does ``from app.watcher import scan_once, start,
  status, stop`` — the names are bound at import, so tests that replace the
  delegation target must patch ``app.routers.watch.<name>``.
- Anything *called by* those functions (``create_file_job``, ``resolve_model``,
  module state) lives in ``app.watcher``'s namespace.
- The enable route calls ``cfg.set``, which persists ``config-user.json`` —
  every enable test swaps it for a disk-free recorder first.
"""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routers.watch as watch_routes
import app.watcher as watcher
from app.config import cfg
from app.main import app

client = TestClient(app)


@pytest.fixture
def watch_env(tmp_path, monkeypatch):
    """Isolated watch dir + reset module state; never touches config-user.json."""
    monkeypatch.setattr(watcher.cfg, "watch_dir", str(tmp_path / "watch"))
    monkeypatch.setattr(watcher.cfg, "watch_enabled", False)
    monkeypatch.setattr(watcher.cfg, "watch_target_lang", "fr")
    monkeypatch.setattr(watcher.cfg, "watch_model", "")
    monkeypatch.setattr(watcher.cfg, "watch_poll_seconds", 3600)
    monkeypatch.setattr(watcher, "_handled", set())
    monkeypatch.setattr(watcher, "_recent_processed", [])
    monkeypatch.setattr(watcher, "_recent_errors", [])
    monkeypatch.setattr(watcher, "_watch_task", None)
    d = watcher.watch_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _record_cfg_set(monkeypatch):
    """Replace ``cfg.set`` with an in-memory recorder (no disk write).

    Applies the same mutation as the real method so ``start()``/``status()``
    observe the new value, and returns the call log for assertions.
    """
    calls = []

    def fake_set(key, value):
        calls.append((key, value))
        setattr(cfg, key, value)

    monkeypatch.setattr(cfg, "set", fake_set)
    return calls


def _aged(path: Path, seconds: float = 60.0) -> Path:
    """Create a file and backdate its mtime so it looks fully written."""
    path.write_bytes(b"x")
    t = time.time() - seconds
    os.utime(path, (t, t))
    return path


# ── GET /api/watch/status ─────────────────────────────────────────────
def test_status_reports_isolated_watch_dir(watch_env):
    (watch_env / "pending.mp4").write_bytes(b"x")
    (watch_env / "half.mp4.part").write_bytes(b"x")  # partial -> not pending

    r = client.get("/api/watch/status")

    assert r.status_code == 200
    body = r.json()
    assert body["dir"] == str(watch_env)
    assert body["processed_dir"] == str(watch_env / "processed")
    assert body["pending"] == ["pending.mp4"]
    assert body["enabled"] is False
    assert body["running"] is False
    assert body["target_lang"] == "fr"
    assert body["poll_seconds"] == 3600
    assert body["handled"] == 0
    assert body["recent_processed"] == []
    assert body["recent_errors"] == []


def test_status_route_registered():
    """Guard the router staying mounted as the app grows.

    Goes through the OpenAPI schema — the public contract clients generate
    from — because ``app.routes`` wraps included routers opaquely.
    """
    paths = set(app.openapi()["paths"])
    assert {"/api/watch/status", "/api/watch/scan", "/api/watch/enable"} <= paths


# ── POST /api/watch/scan ──────────────────────────────────────────────
def test_scan_route_delegates_to_scan_once(watch_env, monkeypatch):
    seen = []
    enqueued = [{"file": "a.mp4", "job_id": "j1", "moved_to": "/tmp/processed/a.mp4"}]

    async def fake_scan():
        seen.append(True)
        return enqueued

    monkeypatch.setattr(watch_routes, "scan_once", fake_scan)

    r = client.post("/api/watch/scan")

    assert r.status_code == 200
    assert r.json() == {"ok": True, "count": 1, "enqueued": enqueued}
    assert seen == [True]


def test_scan_route_runs_real_watcher(watch_env, monkeypatch):
    """End-to-end through HTTP: model resolve + job create + file moved."""
    _aged(watch_env / "clip.mkv")
    calls = []

    async def fake_resolve(model):
        return "aya-expanse:8b", None

    async def fake_create(path, **kw):
        calls.append((path, kw))
        return "job42"

    monkeypatch.setattr(watcher, "resolve_model", fake_resolve)
    monkeypatch.setattr(watcher, "create_file_job", fake_create)

    r = client.post("/api/watch/scan")

    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    entry = body["enqueued"][0]
    assert entry["file"] == "clip.mkv"
    assert entry["job_id"] == "job42"
    assert Path(entry["moved_to"]) == watch_env / "processed" / "clip.mkv"
    assert (watch_env / "processed" / "clip.mkv").exists()
    # The watcher's config reached job creation (route -> watcher -> cfg wiring).
    assert calls[0][1]["target_lang"] == "fr"
    assert calls[0][1]["batch_id"] == "watch"

    # A second scan must not re-enqueue the handled file.
    r2 = client.post("/api/watch/scan")
    assert r2.json()["count"] == 0
    assert len(calls) == 1


# ── POST /api/watch/enable ────────────────────────────────────────────
def test_enable_true_persists_and_starts(watch_env, monkeypatch):
    calls = _record_cfg_set(monkeypatch)

    r = client.post("/api/watch/enable", data={"enabled": "true"})

    assert r.status_code == 200
    body = r.json()
    assert calls == [("watch_enabled", True)]
    # Real start() ran: status() (same request) sees a live watch task.
    assert body["enabled"] is True
    assert body["running"] is True
    assert body["dir"] == str(watch_env)


def test_enable_false_persists_and_stops(watch_env, monkeypatch):
    calls = _record_cfg_set(monkeypatch)
    stopped = []

    async def fake_stop():
        stopped.append(True)

    monkeypatch.setattr(watch_routes, "stop", fake_stop)

    r = client.post("/api/watch/enable", data={"enabled": "false"})

    assert r.status_code == 200
    body = r.json()
    assert calls == [("watch_enabled", False)]
    assert stopped == [True]
    assert body["enabled"] is False
    assert body["running"] is False


def test_enable_requires_enabled_field(watch_env):
    # Validation fails before the handler runs, so cfg.set is never reached.
    assert client.post("/api/watch/enable").status_code == 422


def test_enable_rejects_non_boolean(watch_env):
    r = client.post("/api/watch/enable", data={"enabled": "maybe"})
    assert r.status_code == 422
    assert cfg.watch_enabled is False  # unchanged
