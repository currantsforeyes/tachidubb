"""Export a VoiceStudio dub job folder as an OpenShot project (.osp).

Gives you the video timeline VoiceStudio does not have: open the generated
project in OpenShot 4 and the picture sits on the top track with the source
speech, the background stem, your full-length dub and the per-line dub clips
stacked underneath - ready to nudge against the picture.

Track layout (top of the timeline UI -> bottom):

    L5  original.mp4       picture           (audio muted; unmute to compare)
    L4  dubbed_<lang>.wav  full-length dub   (audible)
    L3  seg_<lang>_*.wav   one clip per segment, placed at that segment's
                           source start time (muted; mute L4 to work line by
                           line)
    L2  no_vocals.wav      background stem   (audible)
    L1  audio.wav          source speech     (muted; reference lane)

Segment timings come from VoiceStudio's own job record:
``%APPDATA%/OmniVoice/omnivoice.db`` -> ``dub_history.job_data.segments``
(``id``/``start``/``end``), matched to ``seg_<lang>_<id>.wav`` by segment id.
Without the DB row the export still works - just without the segment track.

Schema notes (verified against OpenShot 4.0.1 + libopenshot sources):
- the top-level shape comes from OpenShot's own ``settings/_default.project``
  (read from the install when present, embedded copy otherwise);
- clips reference a layer by its ``number`` (1000000-based), exactly like the
  Add-to-Timeline dialog builds them;
- ``Clip::SetJsonValue`` skips missing keys and only needs
  ``reader.type`` + ``reader.path``, so the reader dict stays minimal and
  libopenshot re-probes the real duration/fps itself;
- muting is ``has_audio`` with a single keyframe of Y=0 (the "Enable Audio"
  property).

    python tools/export_voicesudio_to_openshot.py <job_folder> [-o out.osp]
    python tools/export_voicesudio_to_openshot.py <job_folder> --no-segments
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

# Exact copy of OpenShot 4.0.1's settings/_default.project - the fallback for
# machines without an OpenShot install (tests, CI). merge_settings() on load
# fills anything we omit from the installed default anyway.
FALLBACK_TEMPLATE = {
    "id": "T0",
    "fps": {"num": 24, "den": 1},
    "display_ratio": {"num": 16, "den": 9},
    "pixel_ratio": {"num": 1, "den": 1},
    "width": 1280,
    "height": 720,
    "sample_rate": 48000,
    "channels": 2,
    "channel_layout": 3,
    "settings": {},
    "clips": [],
    "effects": [],
    "files": [],
    "duration": 300,
    "scale": 15.0,
    "tick_pixels": 100,
    "playhead_position": 0,
    "profile": "HD 720p 30 fps",
    "export_settings": None,
    "layers": [
        {"id": "L%s" % n, "label": "", "number": n * 1000000, "y": 0, "lock": False}
        for n in range(1, 6)
    ],
    "markers": [],
    "progress": [],
    "history": {"undo": [], "redo": []},
    "version": {"openshot-qt": "0.0.0", "libopenshot": "0.0.0"},
}

# Written unconditionally: _default.project ships "0.0.0", and
# upgrade_project_data_structures() treats that as "beta of OpenShot" and
# walks clip["alpha"]["Points"] - which minimal clips don't have (observed:
# KeyError: 'alpha' in openshot-qt.log on first load). Current versions come
# from a real 4.0.1 save; every upgrade branch then skips cleanly.
CURRENT_VERSIONS = {"openshot-qt": "4.0.1", "libopenshot": "1.0.1"}

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def installed_template() -> Path | None:
    """OpenShot's bundled default project on this machine, if installed."""
    candidates = []
    if sys.platform == "win32":
        for base in (
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            Path.home() / "AppData" / "Local" / "Programs",
        ):
            candidates.append(Path(base) / "OpenShot Video Editor" / "settings" / "_default.project")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/OpenShot Video Editor.app/Contents/Resources/settings/_default.project"))
    else:
        candidates.append(Path("/usr/share/openshot-qt/settings/_default.project"))
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_template(explicit: Path | None = None) -> dict:
    path = explicit or installed_template()
    if path is None:
        return json.loads(json.dumps(FALLBACK_TEMPLATE))
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def wav_info(path: Path) -> tuple[float, int, int]:
    """(duration, sample_rate, channels) for a wav via soundfile."""
    import soundfile as sf

    info = sf.info(str(path))
    return float(info.duration), int(info.samplerate), int(info.channels)


def probe_video(path: Path) -> dict | None:
    """duration/fps/size/audio for a video via ffprobe; None when unavailable."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    result: dict = {}
    duration = data.get("format", {}).get("duration") or (video or {}).get("duration")
    if duration:
        try:
            result["duration"] = float(duration)
        except (TypeError, ValueError):
            pass
    if video:
        if video.get("width") and video.get("height"):
            result["width"] = int(video["width"])
            result["height"] = int(video["height"])
        rate = video.get("r_frame_rate") or ""
        if "/" in rate:
            num, den = rate.split("/", 1)
            if int(den or 0) > 0 and int(num or 0) > 0:
                result["fps"] = {"num": int(num), "den": int(den)}
    if audio:
        for key, src in (("sample_rate", "sample_rate"), ("channels", "channels")):
            if audio.get(src):
                result[key] = int(audio[src])
    return result or None


def default_db_path() -> Path | None:
    import os

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    path = Path(appdata) / "OmniVoice" / "omnivoice.db"
    return path if path.is_file() else None


def load_job_record(job_id: str, db_path: Path | None) -> dict | None:
    """VoiceStudio's dub_history row for this job folder (read-only)."""
    if db_path is None or not db_path.is_file():
        return None
    try:
        con = sqlite3.connect(db_path.absolute().as_uri() + "?mode=ro", uri=True)
        try:
            row = con.execute(
                "select job_data, language_code from dub_history where id = ?",
                (job_id,),
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        job_data = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return {"job_data": job_data, "language_code": row[1] or ""}


def pick_dub(job_dir: Path, record: dict | None) -> Path | None:
    """The full-length dub wav: dubbed_tracks[<lang>].path, else any dubbed_*.wav."""
    if record:
        tracks = record["job_data"].get("dubbed_tracks") or {}
        ordered = []
        lang = record.get("language_code")
        if lang and lang in tracks:
            ordered.append(tracks[lang])
        ordered.extend(v for k, v in tracks.items() if not lang or k != lang)
        for entry in ordered:
            path = Path(entry.get("path") or "")
            if path.name and path.is_file():
                return path
    candidates = sorted(job_dir.glob("dubbed_*.wav"))
    return candidates[0] if candidates else None


def segment_files(job_dir: Path, lang: str) -> dict[str, Path]:
    """Map segment id -> seg_<lang>_<id>.wav."""
    out: dict[str, Path] = {}
    prefix = f"seg_{lang}_"
    for path in sorted(job_dir.glob(f"{prefix}*.wav")):
        seg_id = path.stem[len(prefix):]
        if seg_id:
            out[seg_id] = path
    return out


def _keyframe(value: float) -> dict:
    """Single-point keyframe (constant for all frames), OpenShot Point shape."""
    return {
        "Points": [
            {
                "co": {"X": 1.0, "Y": value},
                "handle_left": {"X": 0.5, "Y": value},
                "handle_right": {"X": 0.5, "Y": value},
            }
        ]
    }


def _file_entry(fid: str, path: Path, media_type: str, duration: float, extra: dict | None = None) -> dict:
    entry = {
        "id": fid,
        "path": str(path),
        "name": path.stem,
        "type": "FFmpegReader",
        "media_type": media_type,
        "duration": round(float(duration), 6),
    }
    if extra:
        entry.update(extra)
    return entry


def _clip(
    cid: str,
    file_id: str,
    layer_number: int,
    position: float,
    duration: float,
    path: Path,
    title: str,
    audible: bool,
) -> dict:
    return {
        "id": cid,
        "layer": layer_number,
        "position": round(float(position), 6),
        "start": 0.0,
        "end": round(float(duration), 6),
        "duration": round(float(duration), 6),
        "file_id": file_id,
        "title": title,
        "reader": {"type": "FFmpegReader", "path": str(path)},
        "has_audio": _keyframe(1.0 if audible else 0.0),
        "effects": [],
    }


def _layers_for(template: dict, needed: int) -> list[dict]:
    """Bottom-to-top layer list, extending the template if it has too few."""
    layers = sorted(template.get("layers") or [], key=lambda ly: ly.get("number", 0))
    while len(layers) < needed:
        n = len(layers) + 1
        layers.append(
            {"id": "L%s" % n, "label": "", "number": n * 1000000, "y": 0, "lock": False}
        )
    template["layers"] = layers + [
        ly for ly in (template.get("layers") or []) if ly not in layers
    ]
    return layers


def build(
    job_dir: Path,
    *,
    db_path: Path | None = None,
    with_segments: bool = True,
    template: dict | None = None,
) -> tuple[dict, list[str]]:
    """Build the .osp project dict for a job folder (plus notes/warnings)."""
    job_dir = job_dir.resolve()
    notes: list[str] = []

    video = next(
        (job_dir / n for n in ("original.mp4", "original.mov") if (job_dir / n).is_file()),
        None,
    )
    if video is None:
        hits = [p for p in sorted(job_dir.iterdir())
                if p.suffix.lower() in VIDEO_EXTS and p.is_file()]
        video = hits[0] if hits else None
    if video is None:
        raise FileNotFoundError(f"no video (original.mp4) in {job_dir}")

    record = load_job_record(job_dir.name, db_path)
    if record is None and with_segments:
        notes.append(
            "no dub_history row for this job - segment track omitted "
            f"(looked in {db_path})" if db_path else
            "no VoiceStudio db found - segment track omitted"
        )
        with_segments = False

    job_duration = 0.0
    if record:
        try:
            job_duration = float(record["job_data"].get("duration") or 0.0)
        except (TypeError, ValueError):
            job_duration = 0.0

    probe = probe_video(video) or {}
    video_duration = probe.get("duration") or job_duration
    if not video_duration:
        raise RuntimeError(
            "cannot determine the video duration (ffprobe missing and no "
            "dub_history duration) - install ffprobe or run next to the db"
        )

    lang = (record or {}).get("language_code") or ""
    if not lang:
        # Fall back to whatever dubbed_<lang>.wav / seg_<lang>_* files exist.
        dub_hits = sorted(job_dir.glob("dubbed_*.wav"))
        if dub_hits:
            lang = dub_hits[0].stem.split("_", 1)[1]
        seg_hits = sorted(job_dir.glob("seg_*_*.wav"))
        if not lang and seg_hits:
            lang = seg_hits[0].stem.split("_")[1]
    if not lang:
        lang = "en"

    dub = pick_dub(job_dir, record)
    if dub is None:
        notes.append("no dubbed_*.wav found - dub track omitted")
    background = job_dir / "no_vocals.wav"
    if not background.is_file():
        background = None
        notes.append("no no_vocals.wav - background track omitted")
    source = job_dir / "audio.wav"
    if not source.is_file():
        source = None
        notes.append("no audio.wav - source-speech track omitted")

    segments: list[dict] = []
    seg_paths: dict[str, Path] = {}
    if with_segments:
        segments = list((record or {}).get("job_data", {}).get("segments") or [])
        seg_paths = segment_files(job_dir, lang)
        if not seg_paths:
            notes.append(f"no seg_{lang}_*.wav files - segment track omitted")

    tpl = json.loads(json.dumps(template)) if template else load_template()
    tpl["version"] = dict(CURRENT_VERSIONS)
    files: list[dict] = []
    clips: list[dict] = []
    ends: list[float] = []

    # Bottom -> top: source speech, background, segments, dub, video.
    slot_count = 5 if (segments and seg_paths) else 4
    layers = _layers_for(tpl, slot_count)
    slots = layers[:slot_count]  # ascending: index 0 = bottom

    fid = 0
    cid = 0

    def next_file_id() -> str:
        nonlocal fid
        fid += 1
        return "F%03d" % fid

    def next_clip_id() -> str:
        nonlocal cid
        cid += 1
        return "C%03d" % cid

    def add_full_track(path: Path, media_type: str, duration: float,
                       layer: dict, audible: bool, extra: dict | None = None) -> None:
        file_id = next_file_id()
        files.append(_file_entry(file_id, path, media_type, duration, extra))
        clips.append(_clip(next_clip_id(), file_id, layer["number"], 0.0,
                           duration, path, path.name, audible))
        ends.append(duration)

    if source is not None:
        dur, sr, ch = wav_info(source)
        add_full_track(source, "audio", dur, slots[0], audible=False,
                       extra={"sample_rate": sr, "channels": ch})
    if background is not None:
        dur, sr, ch = wav_info(background)
        add_full_track(background, "audio", dur, slots[1], audible=True,
                       extra={"sample_rate": sr, "channels": ch})

    if segments and seg_paths:
        seg_layer = slots[2]
        placed = 0
        for seg in segments:
            path = seg_paths.get(str(seg.get("id")))
            if path is None:
                continue
            dur, sr, ch = wav_info(path)
            file_id = next_file_id()
            files.append(_file_entry(file_id, path, "audio", dur,
                                     extra={"sample_rate": sr, "channels": ch}))
            position = float(seg.get("start") or 0.0)
            clips.append(_clip(next_clip_id(), file_id, seg_layer["number"],
                               position, dur, path, path.name, audible=False))
            ends.append(position + dur)
            placed += 1
        if placed == 0:
            notes.append("segment ids did not match any seg files - segment track empty")

    if dub is not None:
        dur, sr, ch = wav_info(dub)
        add_full_track(dub, "audio", dur, slots[-2], audible=True,
                       extra={"sample_rate": sr, "channels": ch})

    video_extra = {k: probe[k] for k in ("width", "height", "fps", "sample_rate", "channels")
                   if k in probe}
    add_full_track(video, "video", video_duration, slots[-1], audible=False,
                   extra=video_extra)

    tpl["files"] = files
    tpl["clips"] = clips
    tpl["duration"] = max(10, math.ceil(max(ends)) + 2)
    tpl["playhead_position"] = 0
    if probe.get("fps"):
        # Keep profile and fps consistent (the template's own pair can drift).
        tpl["fps"] = probe["fps"]
    if probe.get("width") and probe.get("height"):
        tpl["width"] = probe["width"]
        tpl["height"] = probe["height"]
        tpl["display_ratio"] = _ratio(probe["width"], probe["height"]) or tpl["display_ratio"]
    return tpl, notes


def _ratio(a: int, b: int) -> dict | None:
    def gcd(x: int, y: int) -> int:
        while y:
            x, y = y, x % y
        return x

    if a <= 0 or b <= 0:
        return None
    g = gcd(a, b)
    return {"num": a // g, "den": b // g}


def write_project(project: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(project, fh, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Export a VoiceStudio dub job folder as an OpenShot project."
    )
    ap.add_argument("job", type=Path, help="VoiceStudio dub_jobs/<id> folder")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output .osp (default: <job>/openshot.osp)")
    ap.add_argument("--db", type=Path, default=None,
                    help="VoiceStudio omnivoice.db (default: %%APPDATA%%/OmniVoice/omnivoice.db)")
    ap.add_argument("--template", type=Path, default=None,
                    help="OpenShot _default.project to base the export on")
    ap.add_argument("--no-segments", action="store_true",
                    help="skip the per-segment clip track")
    args = ap.parse_args(argv)

    job = args.job
    if not job.is_dir():
        print(f"NOT A FOLDER: {job}")
        return 1

    db = args.db if args.db is not None else default_db_path()
    template = load_template(args.template)
    project, notes = build(
        job, db_path=db, with_segments=not args.no_segments, template=template
    )

    out = args.out or (job / "openshot.osp")
    write_project(project, out)

    for note in notes:
        print(f"note: {note}")
    print(f"wrote {out}")
    print(f"  files: {len(project['files'])}  clips: {len(project['clips'])}  "
          f"duration: {project['duration']}s")
    for clip in sorted(project["clips"], key=lambda c: (c["layer"], c["position"])):
        audible = clip["has_audio"]["Points"][0]["co"]["Y"]
        print(f"  layer {clip['layer']}  pos {clip['position']:>8.3f}s  "
              f"{'on ' if audible else 'MUTE'}  {clip['title']}")
    print("Open it in OpenShot: File > Open Project, or 'openshot-qt.exe <file>.osp'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
