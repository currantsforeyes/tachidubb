"""Serverless worker (tools/dub_worker.py): spec in, NDJSON events out.

This is what an external host — the OpenShot add-on — spawns instead of running
the web server, so what's pinned here is the *protocol*: the event sequence,
the exit codes, and that a cancel behaves exactly like the server's Cancel
button. No GPU, network or queue is involved: ``run_pipeline`` is faked.
"""
import asyncio
import io
import json

import pytest

import app.submit as submit
from app.queue import JobCancelled
from app.state import jobs
from tools import dub_worker


@pytest.fixture
def isolated(monkeypatch):
    """Own the shared job store for one test; never let it leak.

    Other files assert ``GET /api/jobs`` is empty, so the store is snapshotted
    and restored rather than merely cleared. ``save_job`` is stubbed because a
    previous test may have initialised the SQLite store — this worker must not
    write into someone else's database. ``enqueue_job`` raises, proving that
    ``enqueue=False`` really keeps the job off the queue.
    """
    saved = dict(jobs)
    jobs.clear()
    monkeypatch.setattr(dub_worker, "save_job", lambda job: None)
    monkeypatch.setattr(submit, "save_job", lambda job: None)

    async def _must_not_enqueue(job_id, args):
        raise AssertionError("create_file_job(enqueue=False) must not enqueue")

    monkeypatch.setattr(submit, "enqueue_job", _must_not_enqueue)
    yield
    jobs.clear()
    jobs.update(saved)


def _events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()
            if line.strip()]


def _spec(tmp_path, **extra):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    spec = {"source": str(src), "target_lang": "fr",
            "model": "aya-expanse:8b"}
    spec.update(extra)
    return spec


def test_streams_job_progress_and_done(monkeypatch, isolated, tmp_path):
    seen = {}

    async def fake_run(jid, **args):
        seen["jid"], seen["args"] = jid, args
        job = jobs[jid]
        job.update(status="translating", progress=45,
                   step_detail="Translating to French...")
        await asyncio.sleep(0.03)          # give the watcher a tick to observe
        job.update(status="complete", progress=100,
                   output_url=f"/outputs/{jid}/dubbed_video.mp4")

    monkeypatch.setattr(dub_worker, "run_pipeline", fake_run)
    status_file = tmp_path / "progress.jsonl"
    out = io.StringIO()

    code = asyncio.run(dub_worker.run(
        _spec(tmp_path), out, tick=0.005, status_file=status_file))

    events = _events(out)
    assert code == 0
    assert events[0]["type"] == "job" and events[0]["job_id"]
    assert events[0]["work"].endswith(events[0]["job_id"])

    # The pipeline's own args reached run_pipeline — no second arg-building path.
    assert seen["jid"] == events[0]["job_id"]
    assert seen["args"]["target_lang"] == "fr"
    assert seen["args"]["model"] == "aya-expanse:8b"

    progress = [e for e in events if e["type"] == "progress"]
    assert any(e.get("progress") == 45 for e in progress), \
        "an intermediate state must be streamed, not just the final one"
    assert progress[-1]["progress"] == 100, "terminal state must be reported"

    assert events[-1]["type"] == "done"
    assert events[-1]["output"] == f"/outputs/{events[-1]['job_id']}/dubbed_video.mp4"

    # The status-file mirror carries exactly the same stream.
    assert status_file.read_text(encoding="utf-8").splitlines() == \
        out.getvalue().splitlines()


def test_failure_reports_error_and_exits_nonzero(monkeypatch, isolated, tmp_path):
    async def boom(jid, **args):
        raise RuntimeError("cuda out of memory")

    monkeypatch.setattr(dub_worker, "run_pipeline", boom)
    out = io.StringIO()

    code = asyncio.run(dub_worker.run(_spec(tmp_path), out, tick=0.005))

    events = _events(out)
    assert code == 1
    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "cuda out of memory"
    jid = events[0]["job_id"]
    assert jobs[jid]["status"] == "error"


def test_cancellation_is_not_an_error(monkeypatch, isolated, tmp_path):
    """Mirrors app/queue.py: JobCancelled -> status cancelled, exit 2."""

    async def cancelled(jid, **args):
        raise JobCancelled("cancelled by user")

    monkeypatch.setattr(dub_worker, "run_pipeline", cancelled)
    out = io.StringIO()

    code = asyncio.run(dub_worker.run(_spec(tmp_path), out, tick=0.005))

    events = _events(out)
    assert code == 2
    assert events[-1]["type"] == "cancelled"
    jid = events[0]["job_id"]
    assert jobs[jid]["status"] == "cancelled"
    assert "cancel_requested" not in jobs[jid]


def test_cancel_file_stops_the_job(monkeypatch, isolated, tmp_path):
    """A host cancels by touching a file — no second control channel needed."""
    cancel_file = tmp_path / "cancel.me"
    cancel_file.write_text("", encoding="utf-8")

    async def watch_for_cancel(jid, **args):
        for _ in range(200):
            if jobs[jid].get("cancel_requested"):
                raise JobCancelled("cancelled by user")
            await asyncio.sleep(0.01)
        raise AssertionError("cancel_requested was never set by the watcher")

    monkeypatch.setattr(dub_worker, "run_pipeline", watch_for_cancel)
    out = io.StringIO()

    code = asyncio.run(dub_worker.run(
        _spec(tmp_path), out, cancel_file=cancel_file, tick=0.005))

    assert code == 2
    assert _events(out)[-1]["type"] == "cancelled"


def test_bad_spec_exits_three_without_running(monkeypatch, isolated, tmp_path):
    ran = False

    async def fake_run(jid, **args):
        nonlocal ran
        ran = True

    monkeypatch.setattr(dub_worker, "run_pipeline", fake_run)

    # Unknown key: catch a typo before it silently drops a setting.
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_spec(tmp_path, targe_lang="fr")),
                   encoding="utf-8")
    out = io.StringIO()
    assert dub_worker.main(["--spec", str(bad)], out=out) == 3
    assert "unknown spec keys: targe_lang" in _events(out)[0]["error"]

    # Missing required key.
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"source": "x.mp4"}), encoding="utf-8")
    out = io.StringIO()
    assert dub_worker.main(["--spec", str(missing)], out=out) == 3
    assert "spec is missing" in _events(out)[0]["error"]

    assert not ran, "a bad spec must fail before any pipeline work starts"


def test_spec_file_that_is_not_json_exits_three(isolated, tmp_path):
    spec = tmp_path / "broken.json"
    spec.write_text("{not json", encoding="utf-8")

    out = io.StringIO()
    assert dub_worker.main(["--spec", str(spec)], out=out) == 3
    assert "not valid JSON" in _events(out)[0]["error"]


def test_spec_written_with_a_windows_bom_still_loads(tmp_path):
    """Notepad and PowerShell save UTF-8 *with* a BOM by default, so a
    hand-edited spec must not be rejected for the bytes Windows wrote."""
    spec = tmp_path / "bom.json"
    spec.write_bytes(b"\xef\xbb\xbf"
                     + json.dumps(_spec(tmp_path)).encode("utf-8"))

    loaded = dub_worker.load_spec(spec)

    assert loaded["target_lang"] == "fr"
    assert loaded["model"] == "aya-expanse:8b"
