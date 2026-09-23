"""Storage accounting + cleanup selection (extracted from server.py)."""
from app.storage import (
    dir_size_bytes,
    select_cleanup_candidates,
    build_storage_stats,
    KEEP_ON_INTERMEDIATE_CLEAN,
    CLEANABLE_STATUSES,
)


# ── dir_size_bytes ───────────────────────────────────────────────────────
def test_dir_size_bytes_sums_recursively(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"12345")          # 5
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"123")                 # 3
    assert dir_size_bytes(tmp_path) == 8


def test_dir_size_bytes_missing_path_returns_zero(tmp_path):
    assert dir_size_bytes(tmp_path / "nope") == 0


# ── select_cleanup_candidates ────────────────────────────────────────────
def make_jobs():
    return {
        "old_complete": {"created": 100, "status": "complete"},
        "new_complete": {"created": 1000, "status": "complete"},
        "running": {"created": 100, "status": "running"},
        "starred": {"created": 100, "status": "complete", "starred": True},
        "errored": {"created": 100, "status": "error"},
        "cancelled": {"created": 100, "status": "cancelled"},
        "nodir": {"created": 100, "status": "complete"},
    }


def make_dirs(tmp_path):
    for jid in ("old_complete", "new_complete", "running", "starred", "errored", "cancelled"):
        (tmp_path / jid).mkdir()


def ids(cands):
    return {c[0] for c in cands}


def test_select_cleanup_candidates_default(tmp_path):
    make_dirs(tmp_path)
    cands = select_cleanup_candidates(make_jobs(), cutoff=500, output_dir=tmp_path)
    assert ids(cands) == {"old_complete", "errored", "cancelled"}


def test_select_cleanup_excludes_errored_when_disabled(tmp_path):
    make_dirs(tmp_path)
    cands = select_cleanup_candidates(
        make_jobs(), cutoff=500, include_errored=False, output_dir=tmp_path
    )
    assert ids(cands) == {"old_complete", "cancelled"}


def test_select_cleanup_excludes_cancelled_when_disabled(tmp_path):
    make_dirs(tmp_path)
    cands = select_cleanup_candidates(
        make_jobs(), cutoff=500, include_cancelled=False, output_dir=tmp_path
    )
    assert ids(cands) == {"old_complete", "errored"}


def test_select_cleanup_candidate_work_path(tmp_path):
    make_dirs(tmp_path)
    cands = select_cleanup_candidates(
        {"old_complete": {"created": 100, "status": "complete"}},
        cutoff=500,
        output_dir=tmp_path,
    )
    _, _, work = cands[0]
    assert work == tmp_path / "old_complete"


def test_cleanable_statuses_are_settled_only():
    assert set(CLEANABLE_STATUSES) == {"complete", "error", "cancelled"}


# ── build_storage_stats ──────────────────────────────────────────────────
def test_build_storage_stats(tmp_path):
    now = 1_000_000.0
    created = now - 2 * 86400  # exactly 2 days ago

    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "big.bin").write_bytes(b"12345")  # 5
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "small.bin").write_bytes(b"123")  # 3

    jobs = {
        "a": {"created": created, "status": "complete", "source_label": "Alpha"},
        "b": {"created": created, "status": "complete"},
        "missing": {"created": created, "status": "complete"},
    }

    stats = build_storage_stats(jobs, output_dir=tmp_path, now=now)

    assert stats["job_count"] == 2
    assert stats["total_bytes"] == 8
    # sorted biggest first
    assert [r["id"] for r in stats["jobs"]] == ["a", "b"]
    row = stats["jobs"][0]
    assert row["label"] == "Alpha"
    assert row["size_bytes"] == 5
    assert row["age_days"] == 2.0
    # b has no source_label -> falls back to id
    assert stats["jobs"][1]["label"] == "b"


def test_build_storage_stats_empty(tmp_path):
    stats = build_storage_stats({}, output_dir=tmp_path)
    assert stats["job_count"] == 0
    assert stats["total_bytes"] == 0


# ── keep set ─────────────────────────────────────────────────────────────
def test_keep_set_includes_deliverables():
    assert "dubbed_video.mp4" in KEEP_ON_INTERMEDIATE_CLEAN
    assert "translated.srt" in KEEP_ON_INTERMEDIATE_CLEAN