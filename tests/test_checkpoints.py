"""Pipeline checkpoint / resume logic (extracted from server.py)."""
import json

import pytest

from app.checkpoints import (
    job_checkpoint_info,
    save_checkpoint,
    load_checkpoint,
    latest_checkpoint,
    latest_segments,
    ensure_translated_srt,
    NoTranscriptError,
    STAGE_ORDER,
)


def test_save_then_load_named_stage(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()

    save_checkpoint("job1", work, "translation_done", {"segments": [{"i": 0}]})
    loaded = load_checkpoint("job1", "translation_done", output_dir=tmp_path)

    assert loaded is not None
    assert loaded["stage"] == "translation_done"
    assert loaded["job_id"] == "job1"
    assert "saved_at" in loaded
    assert loaded["segments"] == [{"i": 0}]


def test_save_also_writes_legacy_state(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    save_checkpoint("job1", work, "transcription_done", {"segments": []})

    assert (work / "pipeline_state.json").exists()


def test_load_missing_returns_none(tmp_path):
    (tmp_path / "job1").mkdir()
    assert load_checkpoint("job1", "tts_done", output_dir=tmp_path) is None


def test_load_falls_back_to_matching_legacy_state(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    (work / "pipeline_state.json").write_text(
        json.dumps({"stage": "translation_done", "hello": "world"}), encoding="utf-8"
    )

    loaded = load_checkpoint("job1", "translation_done", output_dir=tmp_path)
    assert loaded["hello"] == "world"


def test_load_ignores_non_matching_legacy_state(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    (work / "pipeline_state.json").write_text(
        json.dumps({"stage": "tts_done"}), encoding="utf-8"
    )

    assert load_checkpoint("job1", "translation_done", output_dir=tmp_path) is None


def test_latest_checkpoint_prefers_most_advanced(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    # Save in reverse order; latest must still report tts_done.
    save_checkpoint("job1", work, "translation_done", {"n": 1})
    save_checkpoint("job1", work, "transcription_done", {"n": 2})
    save_checkpoint("job1", work, "tts_done", {"n": 3})

    latest = latest_checkpoint("job1", output_dir=tmp_path)
    assert latest["stage"] == "tts_done"
    assert latest["n"] == 3


def test_named_checkpoints_are_not_overwritten(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    save_checkpoint("job1", work, "transcription_done", {"n": 1})
    save_checkpoint("job1", work, "tts_done", {"n": 2})

    earlier = load_checkpoint("job1", "transcription_done", output_dir=tmp_path)
    assert earlier["n"] == 1


def test_checkpoint_info_missing_dir(tmp_path):
    assert job_checkpoint_info("nope", output_dir=tmp_path) == {
        "has_checkpoint": False,
        "latest_checkpoint_stage": None,
    }


def test_checkpoint_info_reports_most_advanced_stage(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    save_checkpoint("job1", work, "transcription_done", {})
    save_checkpoint("job1", work, "tts_done", {})

    info = job_checkpoint_info("job1", output_dir=tmp_path)
    assert info == {"has_checkpoint": True, "latest_checkpoint_stage": "tts_done"}


def test_checkpoint_info_reads_legacy_stage(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    (work / "pipeline_state.json").write_text(
        json.dumps({"stage": "translation_done"}), encoding="utf-8"
    )

    info = job_checkpoint_info("job1", output_dir=tmp_path)
    assert info == {"has_checkpoint": True, "latest_checkpoint_stage": "translation_done"}


def test_checkpoint_info_corrupt_legacy_is_not_resumable(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    (work / "pipeline_state.json").write_text("{not json", encoding="utf-8")

    info = job_checkpoint_info("job1", output_dir=tmp_path)
    assert info["has_checkpoint"] is False


def test_stage_order_is_most_advanced_first():
    assert STAGE_ORDER == ("tts_done", "translation_done", "transcription_done")


# ── latest_segments / ensure_translated_srt (shared by preview, burn, export)
def test_latest_segments_prefers_most_advanced_checkpoint(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    save_checkpoint("job1", work, "translation_done", {"segments": [{"t": "tr"}]})
    save_checkpoint("job1", work, "tts_done", {"segments": [{"t": "tts"}]})

    assert latest_segments("job1", output_dir=tmp_path) == [{"t": "tts"}]


def test_latest_segments_empty_without_checkpoints(tmp_path):
    (tmp_path / "job1").mkdir()
    assert latest_segments("job1", output_dir=tmp_path) == []


def test_ensure_srt_regenerates_from_checkpoint(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    save_checkpoint("job1", work, "tts_done", {"segments": [
        {"start": 0.0, "end": 1.0, "text": "Hi", "translated_text": "Salut"}]})

    path = ensure_translated_srt("job1", output_dir=tmp_path)

    assert path == work / "translated.srt"
    assert "Salut" in path.read_text(encoding="utf-8")


def test_ensure_srt_keeps_existing_file(tmp_path):
    work = tmp_path / "job1"
    work.mkdir()
    srt = work / "translated.srt"
    srt.write_text("hand-edited", encoding="utf-8")

    # No checkpoint at all — must still return the existing SRT untouched.
    assert ensure_translated_srt("job1", output_dir=tmp_path) == srt
    assert srt.read_text(encoding="utf-8") == "hand-edited"


def test_ensure_srt_raises_without_checkpoint(tmp_path):
    (tmp_path / "job1").mkdir()
    with pytest.raises(NoTranscriptError):
        ensure_translated_srt("job1", output_dir=tmp_path)


def test_ensure_srt_falls_back_to_transcription_checkpoint(tmp_path):
    """A job that only reached transcription still yields an SRT (source text)."""
    work = tmp_path / "job1"
    work.mkdir()
    save_checkpoint("job1", work, "transcription_done", {"segments": [
        {"start": 0.0, "end": 1.0, "text": "Hello"}]})

    path = ensure_translated_srt("job1", output_dir=tmp_path)
    assert "Hello" in path.read_text(encoding="utf-8")