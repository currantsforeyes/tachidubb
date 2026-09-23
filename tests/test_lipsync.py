"""MuseTalk lip-sync backend: detection, guide, and command building."""
from pathlib import Path

import pipeline.lipsync as lipsync


def make_repo(root, weights="v15"):
    repo = root / "MuseTalk"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "inference.py").write_text("# stub", encoding="utf-8")
    if weights == "v15":
        (repo / "models" / "musetalkV15").mkdir(parents=True)
        (repo / "models" / "musetalkV15" / "unet.pth").write_bytes(b"")
        (repo / "models" / "musetalkV15" / "musetalk.json").write_bytes(b"")
    elif weights == "v1":
        (repo / "models" / "musetalk").mkdir(parents=True)
        (repo / "models" / "musetalk" / "pytorch_model.bin").write_bytes(b"")
        (repo / "models" / "musetalk" / "musetalk.json").write_bytes(b"")
    return repo


def make_runtime(root):
    py = root / "musetalk-runtime" / "python"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"")
    return py


def add_all_weights(repo, version="v15"):
    """Create (empty) files for every required weight, so probe is clean."""
    for rel in lipsync.required_weight_files(version):
        p = repo / "models" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    return repo


def set_env(monkeypatch, repo=None, python=None):
    if repo is not None:
        monkeypatch.setenv("TACHIDUBB_MUSETALK_DIR", str(repo))
    else:
        monkeypatch.delenv("TACHIDUBB_MUSETALK_DIR", raising=False)
    if python is not None:
        monkeypatch.setenv("TACHIDUBB_MUSETALK_PYTHON", str(python))
    else:
        monkeypatch.delenv("TACHIDUBB_MUSETALK_PYTHON", raising=False)
    # Isolate detection to exactly this dir, so a real MuseTalk install on the
    # developer's machine can't leak into the test.
    dirs = [Path(repo)] if repo is not None else []
    monkeypatch.setattr(lipsync, "candidate_repo_dirs", lambda: dirs)


# ── candidate dirs / runtime resolution ──────────────────────────────────
def test_env_dir_is_first_candidate(monkeypatch, tmp_path):
    set_env(monkeypatch, repo=tmp_path / "somewhere")
    assert lipsync.candidate_repo_dirs()[0] == tmp_path / "somewhere"


def test_resolve_runtime_python_env_override(monkeypatch, tmp_path):
    py = make_runtime(tmp_path)
    set_env(monkeypatch, python=py)
    assert lipsync.resolve_runtime_python() == str(py)


# ── find_musetalk_setup ──────────────────────────────────────────────────
def test_find_setup_v15(monkeypatch, tmp_path):
    repo = make_repo(tmp_path, "v15")
    set_env(monkeypatch, repo=repo, python=make_runtime(tmp_path))

    setup = lipsync.find_musetalk_setup()

    assert setup is not None
    assert setup["engine"] == "musetalk"
    assert setup["version"] == "v15"
    assert setup["repo_dir"] == str(repo)
    assert setup["unet_model_path"].endswith("unet.pth")


def test_find_setup_v1_fallback(monkeypatch, tmp_path):
    repo = make_repo(tmp_path, "v1")
    set_env(monkeypatch, repo=repo, python=make_runtime(tmp_path))
    assert lipsync.find_musetalk_setup()["version"] == "v1"


def test_find_setup_missing_weights(monkeypatch, tmp_path):
    repo = make_repo(tmp_path, weights=None)
    set_env(monkeypatch, repo=repo, python=make_runtime(tmp_path))
    assert lipsync.find_musetalk_setup() is None


def test_find_setup_missing_inference_entry(monkeypatch, tmp_path):
    repo = tmp_path / "MuseTalk"
    repo.mkdir()
    set_env(monkeypatch, repo=repo, python=make_runtime(tmp_path))
    assert lipsync.find_musetalk_setup() is None


def test_find_setup_missing_runtime(monkeypatch, tmp_path):
    repo = make_repo(tmp_path, "v15")
    set_env(monkeypatch, repo=repo)
    monkeypatch.setattr(lipsync, "resolve_runtime_python", lambda: None)
    assert lipsync.find_musetalk_setup() is None


# ── status / guide ───────────────────────────────────────────────────────
def test_install_guide_shape():
    guide = lipsync.musetalk_install_guide()
    assert guide["error"] == "musetalk_not_installed"
    assert guide["engine"] == "musetalk"
    assert guide["install_steps"] and guide["steps"]
    assert "env_override" in guide


def test_status_not_installed(monkeypatch, tmp_path):
    set_env(monkeypatch, repo=tmp_path / "nope")
    status = lipsync.lipsync_status_payload()
    assert status["installed"] is False
    assert status["engine"] == "musetalk"
    assert status["guide"]["error"] == "musetalk_not_installed"


def test_status_installed(monkeypatch, tmp_path):
    repo = make_repo(tmp_path, "v15")
    set_env(monkeypatch, repo=repo, python=make_runtime(tmp_path))
    status = lipsync.lipsync_status_payload()
    assert status["installed"] is True
    assert status["version"] == "v15"
    assert status["repo_dir"] == str(repo)


# ── command builders ─────────────────────────────────────────────────────
def test_extract_audio_cmd():
    cmd = lipsync.extract_audio_cmd("in.mp4", "out.wav")
    assert cmd[0] == "ffmpeg"
    assert "16000" in cmd and "-ac" in cmd
    assert cmd[-1] == "out.wav"


def test_worker_cmd():
    cmd = lipsync.worker_cmd("python.exe", "musetalk_worker.py", "job.json")
    assert cmd[0] == "python.exe"
    assert "-u" in cmd
    assert cmd[-1] == "job.json"


def test_remux_cmd_maps_worker_video_and_source_audio():
    cmd = lipsync.remux_cmd("raw.mp4", "src.mp4", "final.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-c:v" in cmd and "copy" in cmd
    assert "0:v" in cmd and "1:a" in cmd
    assert cmd[-1] == "final.mp4"


def test_build_worker_job():
    setup = {
        "repo_dir": "/repo", "version": "v15",
        "unet_model_path": "/repo/u.pth", "unet_config": "/repo/u.json",
    }
    job = lipsync.build_worker_job(setup, "v.mp4", "a.wav", "o.mp4", "/ffmpeg/bin")
    assert job["version"] == "v15"
    assert job["video_path"] == "v.mp4"
    assert job["output_path"] == "o.mp4"
    assert job["ffmpeg_bin"] == "/ffmpeg/bin"


# ── resolve_ffmpeg_bin ───────────────────────────────────────────────────
def test_resolve_ffmpeg_bin_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TACHIDUBB_FFMPEG_BIN", str(tmp_path))
    assert lipsync.resolve_ffmpeg_bin() == str(tmp_path)


def test_resolve_ffmpeg_bin_uses_path(monkeypatch):
    monkeypatch.delenv("TACHIDUBB_FFMPEG_BIN", raising=False)
    fake = str(Path("tools") / "ffmpeg.exe")
    monkeypatch.setattr(lipsync.shutil, "which", lambda name: fake)
    assert lipsync.resolve_ffmpeg_bin() == str(Path(fake).parent)


def test_resolve_ffmpeg_bin_missing(monkeypatch):
    monkeypatch.delenv("TACHIDUBB_FFMPEG_BIN", raising=False)
    monkeypatch.setattr(lipsync.shutil, "which", lambda name: None)
    assert lipsync.resolve_ffmpeg_bin() == ""


# ── probe_musetalk ───────────────────────────────────────────────────────
def test_probe_installed(monkeypatch, tmp_path):
    repo = make_repo(tmp_path, "v15")
    add_all_weights(repo, "v15")
    set_env(monkeypatch, repo=repo, python=make_runtime(tmp_path))
    monkeypatch.setattr(lipsync, "resolve_ffmpeg_bin", lambda: "/ffmpeg/bin")

    info = lipsync.probe_musetalk()

    assert info["installed"] is True
    assert info["version"] == "v15"
    assert info["runtime_python"] == str(make_runtime(tmp_path))
    assert info["ffmpeg_bin"] == "/ffmpeg/bin"
    assert info["missing_weights"] == []
    assert any(c["has_inference"] for c in info["candidates"])
    assert info["problems"] == []


def test_required_weight_files_are_version_aware():
    v15 = lipsync.required_weight_files("v15")
    assert "sd-vae/config.json" in v15          # aux
    assert "musetalkV15/unet.pth" in v15        # v1.5
    assert "musetalk/pytorch_model.bin" not in v15

    v1 = lipsync.required_weight_files("v1")
    assert "musetalk/pytorch_model.bin" in v1
    assert "musetalkV15/unet.pth" not in v1


def test_missing_weight_files_reports_absent(tmp_path):
    repo = make_repo(tmp_path, "v15")  # version weights only, no aux
    missing = lipsync.missing_weight_files(repo, "v15")

    assert "sd-vae/config.json" in missing
    assert "whisper/config.json" in missing
    assert "musetalkV15/unet.pth" not in missing


def test_probe_flags_missing_weights(monkeypatch, tmp_path):
    repo = make_repo(tmp_path, "v15")
    set_env(monkeypatch, repo=repo, python=make_runtime(tmp_path))

    info = lipsync.probe_musetalk()

    assert info["missing_weights"]
    assert any("missing" in p for p in info["problems"])


def test_worker_write_config_uses_safe_yaml(tmp_path):
    from pipeline.musetalk_worker import write_config

    cfg = tmp_path / "cfg.yaml"
    write_config(cfg, r"D:\a\b.mp4", r"D:\c\d.wav")
    text = cfg.read_text(encoding="utf-8")

    # single-quoted + forward slashes: double-quoted `\M` is an invalid YAML escape
    assert "video_path: 'D:/a/b.mp4'" in text
    assert "audio_path: 'D:/c/d.wav'" in text
    assert "\\" not in text


def test_facealign_patch_detection(tmp_path):
    repo = make_repo(tmp_path, "v15")
    assert lipsync.facealign_patch_applied(repo) is False

    p = repo / "musetalk" / "utils" / "preprocessing.py"
    p.parent.mkdir(parents=True)
    p.write_text("from mmpose import x\n", encoding="utf-8")
    assert lipsync.facealign_patch_applied(repo) is False

    p.write_text(lipsync.FACEALIGN_PATCH_MARKER, encoding="utf-8")
    assert lipsync.facealign_patch_applied(repo) is True


def test_worker_applies_preprocessing_patch(tmp_path):
    from pipeline.musetalk_worker import apply_preprocessing_patch

    repo = tmp_path / "MuseTalk"
    dst = repo / "musetalk" / "utils" / "preprocessing.py"
    dst.parent.mkdir(parents=True)
    dst.write_text("from mmpose.apis import inference_topdown\n", encoding="utf-8")

    assert apply_preprocessing_patch(repo) is True
    assert lipsync.FACEALIGN_PATCH_MARKER in dst.read_text(encoding="utf-8")
    assert dst.with_name("preprocessing.py.orig").exists()
    # idempotent — a second run does nothing
    assert apply_preprocessing_patch(repo) is False


def test_probe_not_installed_lists_problems(monkeypatch, tmp_path):
    set_env(monkeypatch, repo=tmp_path / "nope")
    monkeypatch.setattr(lipsync, "resolve_runtime_python", lambda: None)

    info = lipsync.probe_musetalk()

    assert info["installed"] is False
    assert any("checkout not found" in p for p in info["problems"])
    assert any("runtime interpreter not found" in p for p in info["problems"])


def test_status_includes_probe_when_missing(monkeypatch, tmp_path):
    set_env(monkeypatch, repo=tmp_path / "nope")

    status = lipsync.lipsync_status_payload()

    assert status["installed"] is False
    assert status["probe"]["installed"] is False