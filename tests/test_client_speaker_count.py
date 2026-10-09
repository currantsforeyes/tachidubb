"""Client ``speaker_count`` plumbing — guards a real bug.

``submit_dub`` never sent ``speaker_count``, so the API's default (0 = auto)
always applied: a clip the UI had submitted with ``speaker_count=3`` came back
from a client-run as a single-speaker diarization, merging two thirds of the
dialogue into one voice.
"""
import asyncio

from tools.tachidubb_client import TachiDUBBClient

URL = "https://example.com/clip.mp4"


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
        client = TachiDUBBClient()
        try:
            return await coro_factory(client)
        finally:
            await client.aclose()
    return asyncio.run(_main())


def test_speaker_count_is_sent(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.submit_dub(URL, "en", speaker_count=3))

    assert calls[0][2]["data"]["speaker_count"] == "3"


def test_speaker_count_defaults_to_auto(monkeypatch):
    """0 is the API's "let pyannote decide" — the value that bit us."""
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.submit_dub(URL, "en"))

    assert calls[0][2]["data"]["speaker_count"] == "0"


def test_url_source_travels_as_a_field_not_an_upload(monkeypatch):
    calls = _patch_request(monkeypatch)
    _run(lambda c: c.submit_dub(URL, "en", speaker_count=3))

    method, path, kw = calls[0]
    assert method == "POST" and path == "/api/dub"
    assert kw["data"]["source"] == URL
    assert kw["files"] is None
