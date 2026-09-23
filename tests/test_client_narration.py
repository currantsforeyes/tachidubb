"""Client + CLI wiring for narrator mode.

These guard the plumbing that carries ``narration_mode`` from the CLI / MCP
clients to the server routes. They patch the HTTP layer, so no server, GPU or
network is involved.
"""
import asyncio

from tools.tachidubb_client import TachiDUBBClient
from tools.tachidubb_cli import build_parser


def _patch_request(monkeypatch):
    """Replace the client's HTTP layer; return the list of captured calls."""
    calls = []

    async def fake_request(self, method, path, **kw):
        calls.append((method, path, kw))
        return {"ok": True}

    monkeypatch.setattr(TachiDUBBClient, "_request", fake_request)
    return calls


def _run(coro_factory):
    async def _main():
        c = TachiDUBBClient()
        try:
            return await coro_factory(c)
        finally:
            await c.aclose()
    return asyncio.run(_main())


URL = "https://example.com/clip.mp4"


def test_submit_dub_sends_narration_mode(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.submit_dub(URL, "fr", narration_mode=True))
    data = calls[0][2]["data"]
    assert data["narration_mode"] == "true"


def test_submit_dub_defaults_narration_off(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.submit_dub(URL, "fr"))
    assert calls[0][2]["data"]["narration_mode"] == "false"


def test_submit_compare_sends_narration_mode(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.submit_compare(URL, ["fr", "es"], narration_mode=True))
    method, path, kw = calls[0]
    assert method == "POST" and path == "/api/quick_test"
    assert kw["data"]["narration_mode"] == "true"


def test_submit_showcase_sends_narration_mode(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.submit_showcase(URL, ["fr", "es"], narration_mode=True))
    method, path, kw = calls[0]
    assert method == "POST" and path == "/api/showcase"
    assert kw["data"]["narration_mode"] == "true"


def test_redub_omits_narration_when_unset(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.redub("abc12345", ["fr"]))
    assert "narration_mode" not in calls[0][2]["data"]


def test_redub_forwards_narration_override(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.redub("abc12345", ["fr"], narration_mode=True))
    assert calls[0][2]["data"]["narration_mode"] == "true"


def test_cli_dub_accepts_narrator_flag():
    a = build_parser().parse_args(["dub", URL, "--lang", "fr", "--narrator"])
    assert a.narrator is True
    assert a.handler.__name__ == "cmd_dub"


def test_cli_dub_narrator_defaults_off():
    a = build_parser().parse_args(["dub", URL, "--lang", "fr"])
    assert a.narrator is False


def test_cli_compare_and_showcase_and_redub_accept_narrator():
    for argv in (
        ["compare", URL, "--langs", "fr,es", "--narrator"],
        ["showcase", URL, "--langs", "fr,es", "--narrator"],
        ["redub", "abc12345", "--langs", "fr", "--narrator"],
    ):
        a = build_parser().parse_args(argv)
        assert a.narrator is True, argv