"""Media / FFmpeg helpers used across the server routes.

Extracted from ``server.py`` so the trimming, duration probing, SRT rendering
and font-lookup logic can be unit-tested without importing the FastAPI app.

Everything here is a thin wrapper over ffmpeg/ffprobe plus small pure helpers.
The actual external calls are isolated so they can be monkeypatched in tests.
"""
import logging
import re
import subprocess
from pathlib import Path

from pipeline.assembler import format_srt_time

log = logging.getLogger("tachidubb.media")


# Candidate systems fonts for ffmpeg's drawtext filter (used by the showcase
# language badge and the subtitle burn-in preview).
SHOWCASE_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)


def write_srt_file(segments: list, dst: Path) -> None:
    """Write segments as an SRT file (SubRip format).

    Preferred text is ``translated_text`` (falling back to ``text``). Emotion
    tags like "(happy)" are TTS-only and are stripped from the visible
    subtitle. Segments that end up empty are omitted.
    """
    lines = []
    for i, seg in enumerate(segments, 1):
        start = format_srt_time(seg.get("start", 0.0))
        end = format_srt_time(seg.get("end", 0.0))
        text = (seg.get("translated_text") or seg.get("text") or "").strip()
        # Strip emotion tags like "(happy)" that are TTS-only and shouldn't
        # appear in subtitle text; keep only the spoken part
        text = re.sub(r"^\s*\([^)]+\)\s*", "", text).strip()
        if not text:
            continue
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    Path(dst).write_text("\n".join(lines), encoding="utf-8")


def trim_video(src: Path, dst: Path, seconds: int) -> Path:
    """Trim src to the first `seconds` seconds into dst.

    Tries stream-copy first (fast, requires keyframe alignment); on failure
    falls back to re-encode with libx264. Raises subprocess.CalledProcessError
    if both attempts fail. Returns dst on success.
    """
    seconds = max(1, int(seconds))
    # Attempt 1 — stream copy. Works when keyframes align with the cut point.
    try:
        subprocess.run(
            ["ffmpeg", "-y",
             "-ss", "0",
             "-i", str(src),
             "-t", str(seconds),
             "-c", "copy",
             "-avoid_negative_ts", "make_zero",
             str(dst)],
            check=True, capture_output=True, timeout=60,
        )
        log.info(f"[trim] {src.name} -> {dst.name} ({seconds}s, stream-copy)")
        return dst
    except subprocess.CalledProcessError as e1:
        log.warning(f"[trim] stream-copy failed for {src.name}: "
                    f"{(e1.stderr or b'').decode('utf-8', errors='replace')[-200:]}")
    # Attempt 2 — re-encode. Slower but works on any source.
    subprocess.run(
        ["ffmpeg", "-y",
         "-i", str(src),
         "-t", str(seconds),
         "-c:v", "libx264", "-preset", "veryfast",
         "-c:a", "aac", "-b:a", "128k",
         str(dst)],
        check=True, capture_output=True, timeout=120,
    )
    log.info(f"[trim] {src.name} -> {dst.name} ({seconds}s, re-encoded)")
    return dst


def find_drawtext_font() -> str:
    """Locate a usable TTF/TTC for ffmpeg drawtext. Empty string = let
    ffmpeg fall back to its default (may fail on some Windows builds)."""
    for c in SHOWCASE_FONT_CANDIDATES:
        if Path(c).exists():
            return c
    return ""


def probe_duration(path: Path) -> float:
    """ffprobe a media file and return duration in seconds (0.0 on failure).

    Tries ffprobe first (fast), falls back to parsing `ffmpeg -i` stderr
    if ffprobe isn't available. Logs the reason on every failure so we
    don't get silent zero-returns.
    """
    if not Path(path).exists():
        log.warning(f"[probe] file not found: {path}")
        return 0.0
    # Try ffprobe
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True, timeout=15,
        )
        d = float((r.stdout or "0").strip() or 0)
        if d > 0:
            return d
    except FileNotFoundError:
        log.warning("[probe] ffprobe not on PATH — falling back to ffmpeg -i")
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        log.warning(f"[probe] ffprobe failed for {path}: {err[-200:].strip() or e}")
    except Exception as e:
        log.warning(f"[probe] ffprobe error for {path}: {type(e).__name__}: {e}")

    # Fallback: parse "Duration: HH:MM:SS.ss" from ffmpeg -i stderr.
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", r.stderr or "")
        if m:
            h, mn, s = m.groups()
            return float(h) * 3600 + float(mn) * 60 + float(s)
        log.warning(f"[probe] ffmpeg fallback: no Duration in stderr for {path}")
    except FileNotFoundError:
        log.warning("[probe] ffmpeg not on PATH either — both probes failed")
    except Exception as e:
        log.warning(f"[probe] ffmpeg fallback failed: {type(e).__name__}: {e}")
    return 0.0


def waveform_peaks(audio_path, buckets: int = 1200) -> list:
    """Downsampled peak envelope for drawing a waveform: `buckets` values in 0..1.

    Streams the file in blocks (so a 30-minute dub doesn't have to fit in
    memory) and takes the max absolute sample per bucket, then normalises to
    the loudest bucket. Returns ``[]`` if the file can't be read — the UI then
    just draws an empty lane instead of failing.

    Used by the dialogue editor's waveform lanes.
    """
    try:
        import numpy as np
        import soundfile as sf

        info = sf.info(str(audio_path))
        total = int(info.frames)
        if total <= 0 or buckets <= 0:
            return []
        block = max(1, total // buckets)
        peaks = []
        with sf.SoundFile(str(audio_path)) as fh:
            remaining = total
            while remaining > 0:
                n = min(block, remaining)
                data = fh.read(n, dtype="float32", always_2d=True)
                peaks.append(float(np.abs(data).max()) if data.size else 0.0)
                remaining -= n
        loudest = max(peaks) or 1.0
        return [round(p / loudest, 4) for p in peaks]
    except Exception as e:
        log.warning(f"[waveform] peaks failed for {audio_path}: {type(e).__name__}: {e}")
        return []


def plan_speaker_turns(rows: list, duration: float, extra_cuts=()) -> list:
    """Tile ``[0, duration]`` into one entry per speaker turn.

    ``rows`` are editor timeline rows (dicts with dub-clock ``start`` and a
    ``speaker``); ``extra_cuts`` are additional boundaries (the editor's
    manual cuts, already in the same dub clock). A new turn begins wherever
    the speaker changes between consecutive segments, so the result matches
    exactly where the editor's "slice at speaker changes" puts its cut lines.
    Boundaries are rounded to 3 decimals — the same precision the timeline
    route persists cuts with.

    Returns turn dicts ``{index, start, end, speaker, text, original_text,
    source_start, source_end}`` for every tile that contains at least one
    segment (pure-silence tiles are not turns and are skipped). ``start``/
    ``end`` are dub-clock (where the piece sits in ``dubbed_audio.wav``);
    ``source_*`` is the min/max original-video range of the segments inside.
    """
    if duration <= 0 or not rows:
        return []
    ordered = sorted(rows, key=lambda r: float(r.get("start", 0.0)))
    bounds = {0.0, round(float(duration), 3)}
    prev = None
    for r in ordered:
        spk = r.get("speaker") or ""
        if prev is not None and spk != prev:
            b = round(float(r.get("start", 0.0)), 3)
            if 0 < b < duration:
                bounds.add(b)
        prev = spk
    for c in extra_cuts or ():
        try:
            c = round(float(c), 3)
        except (TypeError, ValueError):
            continue
        if 0 < c < duration:
            bounds.add(c)
    bounds = sorted(bounds)

    turns = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        # Membership uses the SAME 3dp rounding as the boundaries, so the
        # segment that triggers a change starts its own turn (not the
        # previous one) even when its raw start rounds across the edge.
        inside = [r for r in ordered
                  if a <= round(float(r.get("start", 0.0)), 3) < b]
        # Keep a tile if ANY segment overlaps it, not just one starting in
        # it: a manual cut mid-segment would otherwise drop that segment's
        # tail speech from every file. Pure-silence tiles are not turns.
        overlapping = [r for r in ordered
                       if float(r.get("start", 0.0)) < b
                       and float(r.get("start", 0.0)) + float(r.get("duration", 0.0)) > a]
        if not overlapping:
            continue
        content = inside or overlapping
        turns.append({
            "index": len(turns),
            "start": a,
            "end": b,
            "speaker": (content[0].get("speaker") or "SPEAKER_00"),
            "text": " ".join(t for t in (r.get("text") or "" for r in content) if t),
            "original_text": " ".join(t for t in (r.get("original_text") or "" for r in content) if t),
            "source_start": min(float(r.get("source_start", 0.0)) for r in content),
            "source_end": max(float(r.get("source_end", 0.0)) for r in content),
        })
    return turns


def export_turn_wavs(turns: list, dubbed_path, out_dir) -> list:
    """Slice ``dubbed_audio.wav`` into one WAV per turn, written to ``out_dir``.

    Removes stale ``turn_*.wav`` from a previous export first (boundaries may
    have moved after edits), then reads each turn's span straight from the
    source file via seek — a 30-minute dub is never loaded whole. Slices are
    clamped to the actual file length, so an export never fails just because
    the rendered audio is slightly shorter than the video duration.

    Returns the turn dicts augmented with ``file`` for every slice written;
    turns whose span falls entirely past the end of the file are skipped
    (logged) and absent from the result.
    """
    import soundfile as sf

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("turn_*.wav"):
        stale.unlink()

    written = []
    with sf.SoundFile(str(dubbed_path)) as fh:
        sr = fh.samplerate
        total = len(fh)
        for turn in turns:
            a = min(max(int(round(turn["start"] * sr)), 0), total)
            b = min(max(int(round(turn["end"] * sr)), 0), total)
            if b <= a:
                log.warning(
                    f"[turns] turn {turn['index']} "
                    f"({turn['start']:.2f}-{turn['end']:.2f}s) lies beyond "
                    f"{Path(dubbed_path).name} ({total / sr:.2f}s) — skipped"
                )
                continue
            safe_spk = re.sub(r"[^A-Za-z0-9_]", "_", turn.get("speaker") or "") or "SILENCE"
            name = (f"turn_{turn['index']:02d}_{turn['start']:.2f}"
                    f"-{turn['end']:.2f}_{safe_spk}.wav")
            fh.seek(a)
            data = fh.read(b - a, dtype="float32")
            sf.write(str(out / name), data, sr, subtype=fh.subtype)
            written.append({**turn, "file": name})
    return written
