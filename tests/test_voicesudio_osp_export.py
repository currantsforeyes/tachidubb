"""VoiceStudio job folder -> OpenShot .osp exporter: contract tests.

Builds a synthetic job (wavs + dummy video + a dub_history row in a temp
sqlite db) and asserts the produced project against the schema verified
against OpenShot 4.0.1 / libopenshot: template shape preserved, layer
numbering the Add-to-Timeline dialog uses, absolute existing paths, segment
clips at their source starts, muted flags, and graceful degradation without
the db or optional stems.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import export_voicesudio_to_openshot as ex  # noqa: E402

REAL_JOB = Path.home() / "AppData/Roaming/OmniVoice/dub_jobs/f79b4319-e236-4331-aaf3-8be5e00640fd"
REAL_DB = Path.home() / "AppData/Roaming/OmniVoice/omnivoice.db"


def _wav(path: Path, seconds: float, sr: int = 16000, channels: int = 1) -> None:
    t = int(seconds * sr)
    sf.write(str(path), np.zeros(t, dtype=np.float32), sr)


def make_job(root: Path) -> tuple[Path, Path]:
    """Synthetic job folder + its db, mirroring VoiceStudio's layout."""
    job = root / "dub_jobs" / "testjob-1234"
    job.mkdir(parents=True)
    _wav(job / "audio.wav", 1.0, sr=16000)
    _wav(job / "no_vocals.wav", 1.0, sr=44100, channels=2)
    _wav(job / "dubbed_en.wav", 1.1, sr=24000)
    _wav(job / "seg_en_s00000.wav", 0.3, sr=24000)
    _wav(job / "seg_en_s00001.wav", 0.25, sr=24000)
    (job / "original.mp4").write_bytes(b"\x00" * 64)  # duration comes from the db

    db = root / "omnivoice.db"
    con = sqlite3.connect(db)
    con.execute(
        "create table dub_history ("
        "id text primary key, filename text, duration real,"
        "segments_count integer, language text, language_code text,"
        "tracks text, job_data text, content_hash text, created_at text)"
    )
    job_data = {
        "duration": 1.0,
        "segments": [
            {"id": "s00000", "start": 0.0, "end": 0.4, "text": "hello"},
            {"id": "s00001", "start": 0.5, "end": 1.0, "text": "world"},
        ],
        "dubbed_tracks": {"en": {"path": str(job / "dubbed_en.wav")}},
    }
    con.execute(
        "insert into dub_history (id, job_data, language_code) values (?, ?, ?)",
        ("testjob-1234", json.dumps(job_data), "en"),
    )
    con.commit()
    con.close()
    return job, db


@pytest.fixture()
def job(tmp_path):
    return make_job(tmp_path)


def _load(project: dict, title_sub: str) -> dict:
    hits = [c for c in project["clips"] if title_sub in c["title"]]
    assert hits, f"no clip matching {title_sub!r}"
    return hits[0]


def test_project_shape_from_template(job):
    job_dir, db = job
    project, notes = ex.build(job_dir, db_path=db)
    for key in ("fps", "layers", "clips", "files", "duration", "profile",
                "settings", "history", "version"):
        assert key in project
    layer_ids = [ly["id"] for ly in project["layers"]]
    assert layer_ids[:5] == ["L1", "L2", "L3", "L4", "L5"]
    assert [ly["number"] for ly in project["layers"]] == [n * 1000000 for n in range(1, 6)]
    # Never the template's 0.0.0: that triggers the legacy alpha-upgrade walk.
    assert project["version"] == {"openshot-qt": "4.0.1", "libopenshot": "1.0.1"}
    assert project["playhead_position"] == 0


def test_track_layout_and_muting(job):
    job_dir, db = job
    project, _ = ex.build(job_dir, db_path=db)

    # Bottom -> top: source speech, background, segments, dub, video.
    def layer_of(sub: str) -> int:
        return _load(project, sub)["layer"]

    assert layer_of("audio.wav") == 1000000
    assert layer_of("no_vocals") == 2000000
    assert layer_of("seg_en_s00000") == 3000000
    assert layer_of("dubbed_en") == 4000000
    assert layer_of("original.mp4") == 5000000

    def audible(clip: dict) -> bool:
        return clip["has_audio"]["Points"][0]["co"]["Y"] == 1.0

    assert not audible(_load(project, "original.mp4"))  # picture only
    assert audible(_load(project, "no_vocals"))         # background on
    assert audible(_load(project, "dubbed_en"))         # dub on
    assert not audible(_load(project, "audio.wav"))     # reference lane silent
    assert not audible(_load(project, "seg_en_s00000")) # segments overlap the dub


def test_segment_clips_sit_at_source_starts(job):
    job_dir, db = job
    project, _ = ex.build(job_dir, db_path=db)
    assert _load(project, "seg_en_s00000")["position"] == 0.0
    assert _load(project, "seg_en_s00001")["position"] == 0.5
    # Each segment clip spans its own audio length, starting at 0 in-file.
    seg = _load(project, "seg_en_s00001")
    assert seg["start"] == 0.0
    assert seg["end"] == pytest.approx(0.25)


def test_paths_absolute_and_existing(job):
    job_dir, db = job
    project, _ = ex.build(job_dir, db_path=db)
    assert len(project["files"]) == 6  # video + source + bg + dub + 2 segments
    ids = [f["id"] for f in project["files"]]
    assert len(ids) == len(set(ids))
    for f in project["files"]:
        p = Path(f["path"])
        assert p.is_absolute(), f["path"]
        assert p.is_file(), f["path"]
        assert f["media_type"] in ("video", "audio")
        assert f["duration"] > 0
    for c in project["clips"]:
        assert Path(c["reader"]["path"]).is_file()
        assert c["reader"]["type"] == "FFmpegReader"
        assert c["file_id"] in ids
    assert project["duration"] > max(c["position"] + c["end"] for c in project["clips"])


def test_no_segments_flag(job):
    job_dir, db = job
    project, _ = ex.build(job_dir, db_path=db, with_segments=False)
    assert not any("seg_" in c["title"] for c in project["clips"])
    assert not any("seg_" in f["name"] for f in project["files"])
    # video moves down to the now-unused slot? No: 4 slots, video stays on top.
    assert _load(project, "original.mp4")["layer"] == 4000000


def test_without_db_still_exports_but_skips_segments(job, monkeypatch):
    job_dir, _ = job
    # Without the db there is no duration for the (garbage) fixture video.
    monkeypatch.setattr(ex, "probe_video", lambda p: {"duration": 1.0})
    project, notes = ex.build(job_dir, db_path=None)
    assert any("segment" in n for n in notes)
    assert not any("seg_" in c["title"] for c in project["clips"])
    # 4 slots without segments: source, background, dub, video (top).
    assert _load(project, "dubbed_en")["layer"] == 3000000
    assert _load(project, "original.mp4")["layer"] == 4000000


def test_minimal_job_errors_without_video(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        ex.build(tmp_path / "empty", db_path=None, with_segments=False)


def test_video_duration_falls_back_to_db_without_ffprobe(job, monkeypatch):
    job_dir, db = job
    monkeypatch.setattr(ex.shutil, "which", lambda name: None)
    project, _ = ex.build(job_dir, db_path=db)
    video = _load(project, "original.mp4")
    assert video["end"] == pytest.approx(1.0)  # from dub_history.duration


def test_output_writes_valid_utf8_json(job, tmp_path):
    job_dir, db = job
    project, _ = ex.build(job_dir, db_path=db)
    out = tmp_path / "out.osp"
    ex.write_project(project, out)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["clips"] == project["clips"]


@pytest.mark.skipif(not REAL_JOB.is_dir(), reason="real VoiceStudio job not present")
def test_real_job_export():
    project, notes = ex.build(REAL_JOB, db_path=REAL_DB if REAL_DB.is_file() else None)
    segs = [c for c in project["clips"] if "seg_en_" in c["title"]]
    # The known job has 6 segments at documented starts.
    starts = sorted(c["position"] for c in segs)
    assert starts == pytest.approx([0.0, 7.17, 10.357777777777777,
                                    11.033333333333331, 13.94, 21.0])
    assert _load(project, "original.mp4")["layer"] == 5000000
    assert Path(_load(project, "original.mp4")["reader"]["path"]).is_file()
