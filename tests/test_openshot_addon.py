"""OpenShot add-on (openshot_addon/): the contract with OpenShot 4.0.1.

These pin the pieces we cannot afford to drift, because OpenShot's side is
closed source we do not control:

  * the template keys its AI menu reads,
  * the two placeholders OpenShot substitutes before queueing the graph,
  * the language table (kept in sync with the app's own LANGS list),
  * the ref shape ``extract_file_outputs`` collects, and the buckets it scans.
"""
import json
import re
from pathlib import Path

import pytest

from openshot_addon.comfy_nodes import openshot_dub as pack
from openshot_addon.comfy_nodes.openshot_dub import nodes

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "openshot_addon" / "templates" / "dub-to-language.json"
LANGS_JS = ROOT / "frontend" / "src" / "constants.js"


# ── template ─────────────────────────────────────────────────────────
def test_template_carries_the_keys_the_ai_menu_reads():
    tpl = json.loads(TEMPLATE.read_text(encoding="utf-8-sig"))

    # Read by ai_tools_menu.py / generation_service.build_menu_templates.
    assert tpl["template_id"] == "dub-target-language"
    assert tpl["menu_category"] == "enhance"        # appears under "Enhance with AI"
    assert tpl["open_dialog"] is True               # so the language can be typed
    assert tpl["input_type"] == "video"
    assert tpl["output_type"] in {"video", "audio"}
    assert isinstance(tpl["workflow"], dict) and tpl["workflow"]


def test_template_feeds_openShot_substitutes_into_our_node():
    tpl = json.loads(TEMPLATE.read_text(encoding="utf-8-sig"))
    (node_id, node), = tpl["workflow"].items()

    assert node["class_type"] == "OpenShotDubAudio"
    # generation_service.py substitutes exactly these two for us.
    assert node["inputs"]["source_path"] == "__openshot_input__"
    assert node["inputs"]["target_language"] == "__openshot_prompt__"


def test_template_node_is_registered_by_the_pack():
    tpl = json.loads(TEMPLATE.read_text(encoding="utf-8-sig"))
    (_, node), = tpl["workflow"].items()

    assert node["class_type"] in pack.NODE_CLASS_MAPPINGS
    assert pack.NODE_CLASS_MAPPINGS[node["class_type"]] is nodes.OpenShotDubAudio


# ── languages ────────────────────────────────────────────────────────
def _app_languages() -> dict:
    """Parse LANGS out of frontend/src/constants.js (the single source of truth)."""
    text = LANGS_JS.read_text(encoding="utf-8")
    return dict(re.findall(r"\{\s*c:\s*'([a-z-]+)',\s*n:\s*'([^']+)'\s*\}", text))


def test_languages_stay_in_sync_with_the_app():
    app = {c: n for c, n in _app_languages().items() if c != "auto"}
    addon = nodes.load_languages()

    assert set(addon) == set(app), \
        f"add-on codes drifted from the app: {set(addon) ^ set(app)}"
    for code, name in app.items():
        assert addon[code] == name, f"{code}: {addon[code]!r} != app {name!r}"


def test_resolve_language_accepts_codes_names_and_notes():
    langs = nodes.load_languages()

    assert nodes.resolve_language("en", langs) == "en"
    assert nodes.resolve_language("English", langs) == "en"
    assert nodes.resolve_language("english", langs) == "en"
    assert nodes.resolve_language("GERMAN", langs) == "de"
    assert nodes.resolve_language("Chinese (Mandarin)", langs) == "zh"
    assert nodes.resolve_language("  French  ", langs) == "fr"
    assert nodes.resolve_language("Japa", langs) == "ja"   # prefix of a name


def test_resolve_language_refuses_auto_and_unknown():
    langs = nodes.load_languages()

    with pytest.raises(ValueError, match="auto"):
        nodes.resolve_language("auto", langs)
    with pytest.raises(ValueError, match="Unknown target language"):
        nodes.resolve_language("Klingon", langs)
    with pytest.raises(ValueError, match="No target language"):
        nodes.resolve_language("   ", langs)


# ── publishing outputs (the part OpenShot downloads) ─────────────────
def test_publish_outputs_returns_refs_openShot_can_download(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "vocals.wav").write_bytes(b"RIFF")
    (job / "dubbed_video.mp4").write_bytes(b"\x00")
    out = tmp_path / "comfy_out"

    refs = nodes.publish_outputs([job / "vocals.wav", job / "dubbed_video.mp4"], out)

    assert len(refs) == 2
    for ref in refs:
        # extract_file_outputs reads exactly these three keys.
        assert set(ref) == {"filename", "subfolder", "type"}
        assert ref["type"] == "output"
        assert ref["subfolder"] == "openshot_dub"
        assert (out / "openshot_dub" / ref["filename"]).is_file()


def test_publish_outputs_keeps_the_extension_and_skips_missing(tmp_path):
    out = tmp_path / "comfy_out"
    existing = tmp_path / "vocals.wav"
    existing.write_bytes(b"RIFF")
    missing = tmp_path / "nope.wav"

    refs = nodes.publish_outputs([existing, missing], out)

    # The extension survives: _import_generation_outputs derives the saved name
    # from output_ref["filename"], and a .wav written as .txt would be junk.
    assert refs[0]["filename"].endswith(".wav")
    assert len(refs) == 1


def test_publish_outputs_never_overwrites_a_previous_import(tmp_path):
    out = tmp_path / "comfy_out"
    first = tmp_path / "a" / "stem_SPEAKER_00.wav"
    second = tmp_path / "b" / "stem_SPEAKER_00.wav"
    first.parent.mkdir(); second.parent.mkdir()
    first.write_bytes(b"1111")
    second.write_bytes(b"2222")

    refs = nodes.publish_outputs([first, second], out)

    names = [r["filename"] for r in refs]
    assert len(set(names)) == 2, "two same-named outputs must both survive"
    assert (out / "openshot_dub" / names[1]).read_bytes() == b"2222"


def test_buckets_match_the_keys_extract_file_outputs_scans():
    # Its scan list: images, videos, video, gifs, audios, audio, files, filenames.
    assert nodes.bucket_for("dubbed_video.mp4") == "videos"
    assert nodes.bucket_for("vocals.wav") == "audios"
    assert nodes.bucket_for("subtitles.srt") == "files"


def test_collect_outputs_expands_patterns_and_dedupes(tmp_path):
    (tmp_path / "vocals.wav").write_bytes(b"1")
    (tmp_path / "background.wav").write_bytes(b"2")
    for spk in ("SPEAKER_00", "SPEAKER_01"):
        (tmp_path / f"stem_{spk}.wav").write_bytes(b"3")
    (tmp_path / "dubbed_video.mp4").write_bytes(b"4")
    (tmp_path / "checkpoint.json").write_text("{}")

    found = nodes.collect_outputs(tmp_path, [
        "vocals.wav", "background.wav", "stem_*.wav", "dubbed_video.mp4",
    ])

    names = [p.name for p in found]
    assert names == ["vocals.wav", "background.wav",
                     "stem_SPEAKER_00.wav", "stem_SPEAKER_01.wav",
                     "dubbed_video.mp4"]
    assert "checkpoint.json" not in names


# ── node class contract ──────────────────────────────────────────────
def test_node_class_satisfies_comfyui_and_openshot_requirements():
    cls = nodes.OpenShotDubAudio

    inputs = cls.INPUT_TYPES()["required"]
    assert set(inputs) == {"source_path", "target_language"}
    assert inputs["source_path"][0] == "STRING"
    assert inputs["target_language"][0] == "STRING"

    # ComfyUI: callable named by FUNCTION, typed returns.
    assert callable(getattr(cls, cls.FUNCTION))
    assert cls.RETURN_TYPES == ("STRING",)

    # OpenShot only imports results from nodes flagged as outputs.
    assert cls.OUTPUT_NODE is True


def test_config_is_complete_and_points_at_a_worker():
    cfg = nodes.load_config()

    for key in ("runtime_root", "python", "worker", "outputs"):
        assert key in cfg
    assert cfg["worker"].endswith("dub_worker.py")
    assert cfg["outputs"], "publishing nothing would make the add-on a no-op"
