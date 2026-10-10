"""ComfyUI translation worker (pipeline/comfy_translate_worker.py).

Pins the pieces that must not drift: which loader a path selects (a .gguf goes
to llama_cpp, a directory to transformers), the line-delimited JSON protocol,
and — most importantly — that one bad request cannot kill a daemon holding an
8.7 GB model, since reloading it per batch would cost more than the translation.

No model is ever loaded: ``load_model`` is faked.
"""
import io
import json
import sys

import pytest

from pipeline import comfy_translate_worker as w


def test_resolve_loader_infers_from_the_path(tmp_path):
    gguf = tmp_path / "Qwen3-8B-Q8_0.gguf"
    gguf.write_bytes(b"GGUF")
    model_dir = tmp_path / "Qwen3-8B-FP8"
    model_dir.mkdir()

    assert w.resolve_loader(gguf) == "llama"
    assert w.resolve_loader(model_dir) == "hf"
    with pytest.raises(FileNotFoundError, match="model not found"):
        w.resolve_loader(tmp_path / "missing.gguf")


def _run_worker(monkeypatch, capsys, requests, model="--model", fail_load=False):
    """Run main() with a fake model; return (exit code, parsed events)."""
    def fake_load(path, n_threads=0):
        if fail_load:
            raise RuntimeError("cannot load model")

        def run(system, user, opts):
            if user == "BOOM":
                raise RuntimeError("generation exploded")
            return f"{user}|{opts['max_tokens']}|{system[:10]}"

        return "llama", run

    monkeypatch.setattr(w, "load_model", fake_load)
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(r + "\n" for r in requests)))

    rc = w.main(["--model", str("x.gguf")])
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return rc, events


def test_ready_then_reply_roundtrip(monkeypatch, capsys):
    rc, events = _run_worker(
        monkeypatch, capsys,
        [json.dumps({"id": 1, "user": "hello", "max_tokens": 64})])

    assert rc == 0
    assert events[0] == {"event": "ready", "backend": "llama",
                         "seconds": events[0]["seconds"]}
    assert events[1]["id"] == 1
    assert events[1]["reply"].startswith("hello|64|")


def test_a_failed_request_does_not_kill_the_daemon(monkeypatch, capsys):
    """The model stays loaded; only that one request reports an error."""
    rc, events = _run_worker(
        monkeypatch, capsys,
        [json.dumps({"id": 1, "user": "BOOM"}),
         json.dumps({"id": 2, "user": "still alive"})])

    assert rc == 0
    assert "error" in events[1] and events[1]["id"] == 1
    assert "generation exploded" in events[1]["error"]
    assert events[2]["id"] == 2, "the daemon must keep serving after a failure"
    assert "still alive" in events[2]["reply"]


def test_defaults_match_the_translator_settings(monkeypatch, capsys):
    """temperature/top_p/max_tokens are what _call_ollama sends."""
    _, events = _run_worker(
        monkeypatch, capsys, [json.dumps({"id": 7, "user": "hi"})])

    assert "|2048|" in events[1]["reply"]
    assert w.DEFAULTS == {"temperature": 0.3, "max_tokens": 2048, "top_p": 0.9}


def test_malformed_input_reports_an_error_line(monkeypatch, capsys):
    _, events = _run_worker(monkeypatch, capsys, ["{not json at all"])

    # ready + the error line; malformed input must not crash the daemon.
    assert len(events) == 2
    assert events[1]["id"] is None
    assert "error" in events[1]


def test_load_failure_is_fatal_and_exits_nonzero(monkeypatch, capsys):
    rc, events = _run_worker(monkeypatch, capsys, [], fail_load=True)

    assert rc == 1
    assert events[0]["event"] == "fatal"
    assert "cannot load model" in events[0]["error"]
