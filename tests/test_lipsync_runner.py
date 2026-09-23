"""MuseTalk lip-sync orchestration error paths (extracted from server.py)."""
import app.lipsync as runner


def test_missing_job(monkeypatch):
    monkeypatch.setattr(runner, "jobs", {})
    res = runner.run_lipsync("nope")
    assert res["error"] == "job_not_found"


def test_not_installed_returns_guide(monkeypatch):
    monkeypatch.setattr(runner, "jobs", {"j1": {"id": "j1"}})
    monkeypatch.setattr(runner, "find_musetalk_setup", lambda: None)

    res = runner.run_lipsync("j1")

    assert res["error"] == "musetalk_not_installed"
    assert res["guide"]["engine"] == "musetalk"