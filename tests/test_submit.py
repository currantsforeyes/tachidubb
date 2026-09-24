"""Job-submission helpers (app/submit.py) shared by batch + folder watcher."""
import asyncio
import time

import pytest

import app.submit as submit


@pytest.fixture
def capture(monkeypatch):
    """Isolate the job store and capture enqueue calls."""
    state = {"jobs": {}, "enqueued": []}
    monkeypatch.setattr(submit, "jobs", state["jobs"])
    monkeypatch.setattr(submit, "save_job", lambda job: None)

    async def fake_enqueue(job_id, args):
        state["enqueued"].append((job_id, args))

    monkeypatch.setattr(submit, "enqueue_job", fake_enqueue)
    return state


def _run(coro):
    return asyncio.run(coro)


# ── create_file_job ──────────────────────────────────────────────────
def test_create_file_job_shape_and_enqueue(capture, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    jid = _run(submit.create_file_job(
        src, target_lang="fr", model="aya-expanse:8b",
        narration_mode=True, batch_id="watch", batch_label="Folder watch"))

    job = capture["jobs"][jid]
    assert job["status"] == "queued"
    assert job["source"] == str(src)
    assert job["source_type"] == "file"
    assert job["source_label"] == "clip.mp4"
    assert job["target_lang"] == "fr"
    assert job["model"] == "aya-expanse:8b"
    assert job["voice_mode"] == "preset"
    assert job["narration_mode"] is True
    assert job["batch_id"] == "watch"
    assert job["batch_label"] == "Folder watch"
    assert job["scheduled_at"] == 0
    assert job["_pending_args"] is None

    assert len(capture["enqueued"]) == 1
    enqueued_id, args = capture["enqueued"][0]
    assert enqueued_id == jid
    assert args["target_lang"] == "fr"
    assert args["source"] == str(src)
    assert args["narration_mode"] is True
    assert args["reference_audio"] == ""


def test_create_file_job_explicit_id_and_reference(capture, tmp_path):
    src = tmp_path / "a.mov"
    src.write_bytes(b"x")

    jid = _run(submit.create_file_job(
        src, target_lang="de", model="m", job_id="abcd1234",
        reference_audio="/refs/r.wav", voice_style="warm"))

    assert jid == "abcd1234"
    assert capture["jobs"]["abcd1234"]["voice_mode"] == "upload"


def test_create_file_job_scheduled_is_not_enqueued(capture, tmp_path):
    src = tmp_path / "b.mp4"
    src.write_bytes(b"x")

    jid = _run(submit.create_file_job(
        src, target_lang="fr", model="m", scheduled_at=time.time() + 3600))

    job = capture["jobs"][jid]
    assert job["status"] == "scheduled"
    assert job["scheduled_at"] > 0
    assert job["_pending_args"]["target_lang"] == "fr"
    assert capture["enqueued"] == []


# ── resolve_model ────────────────────────────────────────────────────
def test_resolve_model_falls_back_when_missing(monkeypatch):
    async def fake_check(url=""):
        return True, ["qwen2.5:7b"]

    monkeypatch.setattr(submit, "check_ollama", fake_check)
    model, err = _run(submit.resolve_model("nope:1b"))
    assert model == "qwen2.5:7b"
    assert err is None


def test_resolve_model_errors_when_none_installed(monkeypatch):
    async def fake_check(url=""):
        return True, []

    monkeypatch.setattr(submit, "check_ollama", fake_check)
    model, err = _run(submit.resolve_model("nope:1b"))
    assert model == ""
    assert "No translation model" in err


def test_resolve_model_passes_through_when_ollama_down(monkeypatch):
    async def fake_check(url=""):
        return False, []

    monkeypatch.setattr(submit, "check_ollama", fake_check)
    model, err = _run(submit.resolve_model("x:1b"))
    assert model == "x:1b"
    assert err is None