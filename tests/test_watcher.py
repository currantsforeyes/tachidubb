"""Folder watcher (app/watcher.py): scanning, enqueueing and the loop."""
import asyncio
import os
import time
from pathlib import Path

import pytest

import app.watcher as watcher


@pytest.fixture
def watch_cfg(tmp_path, monkeypatch):
    """Point the watcher at an isolated, existing watch directory."""
    monkeypatch.setattr(watcher.cfg, "watch_dir", str(tmp_path / "watch"))
    monkeypatch.setattr(watcher.cfg, "watch_enabled", False)
    monkeypatch.setattr(watcher.cfg, "watch_target_lang", "fr")
    monkeypatch.setattr(watcher.cfg, "watch_model", "")
    monkeypatch.setattr(watcher.cfg, "watch_poll_seconds", 3600)
    monkeypatch.setattr(watcher.cfg, "translation_model", "aya-expanse:8b")
    monkeypatch.setattr(watcher.cfg, "whisper_model", "large-v3")
    monkeypatch.setattr(watcher.cfg, "tts_speed", "balanced")
    monkeypatch.setattr(watcher.cfg, "auto_denoise", False)
    d = watcher.watch_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(watcher, "_handled", set())
    monkeypatch.setattr(watcher, "_recent_processed", [])
    monkeypatch.setattr(watcher, "_recent_errors", [])
    monkeypatch.setattr(watcher, "_watch_task", None)


def _aged(path: Path, seconds: float = 60.0) -> Path:
    """Create a file and backdate its mtime so it looks fully written."""
    path.write_bytes(b"x")
    t = time.time() - seconds
    os.utime(path, (t, t))
    return path


def _ok_model(monkeypatch):
    async def fake_resolve(model):
        return "aya-expanse:8b", None

    monkeypatch.setattr(watcher, "resolve_model", fake_resolve)


# ── candidate selection ──────────────────────────────────────────────
def test_is_candidate_accepts_video(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    assert watcher.is_candidate(p)


def test_is_candidate_rejects_partials_hidden_and_non_video(tmp_path):
    for name in ("a.mp4.part", "a.crdownload", "a.txt", ".hidden.mp4", "a.tmp"):
        p = tmp_path / name
        p.write_bytes(b"x")
        assert not watcher.is_candidate(p), name


def test_is_candidate_rejects_directory(tmp_path):
    (tmp_path / "d.mp4").mkdir()
    assert not watcher.is_candidate(tmp_path / "d.mp4")


def test_list_ready_files_skips_fresh_and_processed(watch_cfg):
    old = _aged(watch_cfg / "old.mp4")
    fresh = watch_cfg / "fresh.mp4"
    fresh.write_bytes(b"x")
    (watch_cfg / "processed").mkdir()
    (watch_cfg / "processed" / "done.mp4").write_bytes(b"x")

    assert watcher.list_ready_files(watch_cfg) == [old]
    # The processed/ subdir itself is not a candidate, and we don't recurse.
    assert "done.mp4" not in [p.name for p in watcher.list_candidates(watch_cfg)]


# ── scan_once ────────────────────────────────────────────────────────
def test_scan_once_enqueues_and_moves(watch_cfg, monkeypatch):
    f = _aged(watch_cfg / "clip.mkv")
    calls = []

    async def fake_create(path, **kw):
        calls.append((path, kw))
        return "job1"

    monkeypatch.setattr(watcher, "create_file_job", fake_create)
    _ok_model(monkeypatch)

    created = asyncio.run(watcher.scan_once())

    assert len(created) == 1
    assert created[0]["job_id"] == "job1"
    assert created[0]["file"] == "clip.mkv"
    assert not f.exists()                        # moved out of the watch dir
    assert (watch_cfg / "processed" / "clip.mkv").exists()
    assert calls[0][1]["target_lang"] == "fr"    # uses the configured lang
    assert calls[0][1]["batch_id"] == "watch"


def test_scan_once_model_error_leaves_file_and_reports(watch_cfg, monkeypatch):
    f = _aged(watch_cfg / "x.mp4")

    async def fake_resolve(model):
        return "", "No translation model installed. Run: ollama pull aya-expanse:8b"

    monkeypatch.setattr(watcher, "resolve_model", fake_resolve)

    created = asyncio.run(watcher.scan_once())

    assert created == []
    assert f.exists()                            # left to retry later
    assert watcher.status()["recent_errors"]


def test_scan_once_error_is_not_retried_in_session(watch_cfg, monkeypatch):
    _aged(watch_cfg / "bad.mp4")
    _ok_model(monkeypatch)

    async def boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(watcher, "create_file_job", boom)
    assert asyncio.run(watcher.scan_once()) == []
    assert watcher.status()["recent_errors"]

    async def must_not_run(*_a, **_k):
        raise AssertionError("a failed file must not be retried this session")

    monkeypatch.setattr(watcher, "create_file_job", must_not_run)
    assert asyncio.run(watcher.scan_once()) == []


def test_scan_once_keeps_both_on_name_collision(watch_cfg, monkeypatch):
    processed = watch_cfg / "processed"
    processed.mkdir()
    (processed / "clip.mp4").write_bytes(b"older")
    _aged(watch_cfg / "clip.mp4")
    _ok_model(monkeypatch)

    async def fake_create(path, **kw):
        return "job1"

    monkeypatch.setattr(watcher, "create_file_job", fake_create)

    created = asyncio.run(watcher.scan_once())

    moved = Path(created[0]["moved_to"])
    assert moved.exists()
    assert moved.name != "clip.mp4"
    assert moved.name.startswith("clip__")


# ── status + lifecycle ───────────────────────────────────────────────
def test_status_reports_pending(watch_cfg):
    (watch_cfg / "pending.mp4").write_bytes(b"x")
    st = watcher.status()
    assert st["dir"] == str(watch_cfg)
    assert st["processed_dir"] == str(watch_cfg / "processed")
    assert "pending.mp4" in st["pending"]


def test_start_is_noop_when_disabled(watch_cfg, monkeypatch):
    monkeypatch.setattr(watcher.cfg, "watch_enabled", False)

    async def _run():
        watcher.start()
        assert watcher.status()["running"] is False

    asyncio.run(_run())


def test_start_and_stop_when_enabled(watch_cfg, monkeypatch):
    monkeypatch.setattr(watcher.cfg, "watch_enabled", True)

    async def _run():
        watcher.start()
        assert watcher.status()["running"] is True
        await watcher.stop()
        assert watcher.status()["running"] is False

    asyncio.run(_run())