"""Showcase slicing helpers — pure and dependency-free.

When a multilingual showcase reel is stitched together, each language needs
to own a contiguous slice of the timeline. Cutting at arbitrary equal-time
chunks lands mid-word, so interior boundaries are snapped to the nearest
segment end that the TTS actually produced.

Extracted from ``server.py`` so this logic is unit-testable without importing
the FastAPI app (and its GPU/ffmpeg dependencies).
"""
import json
import logging
from typing import List, Tuple

log = logging.getLogger("tachidubb.showcase")


def snap_boundaries_to_sentences(
    segments: list, total_dur: float, n_parts: int
) -> List[Tuple[float, float]]:
    """Compute n_parts contiguous slices that together cover [0, total_dur].

    Slices are equal time chunks (`total_dur / n_parts`), with each interior
    boundary snapped to the nearest segment END time. Returns a list of
    (start, end) tuples — guaranteed contiguous, non-empty, sorted.
    """
    if n_parts <= 1 or not segments:
        return [(0.0, float(total_dur))]

    seg_ends = sorted({float(s.get("end", 0.0)) for s in segments if s.get("end")})
    seg_ends = [e for e in seg_ends if 0 < e < total_dur]

    target_each = total_dur / n_parts
    boundaries = []
    prev = 0.0
    for i in range(1, n_parts):
        target = i * target_each
        # Snap to the nearest segment end, but never go backwards past `prev`
        # (otherwise we'd get a zero-length or negative slice).
        candidates = [e for e in seg_ends if e > prev + 0.5]
        if candidates:
            snapped = min(candidates, key=lambda e: abs(e - target))
        else:
            snapped = target
        snapped = max(snapped, prev + 0.5)
        snapped = min(snapped, total_dur - (n_parts - i) * 0.5)
        boundaries.append(snapped)
        prev = snapped

    slices = []
    last = 0.0
    for b in boundaries:
        slices.append((last, b))
        last = b
    slices.append((last, float(total_dur)))
    return slices


def save_placements(work_dir, segments: list) -> None:
    """Write tts_placements.json next to dubbed_video.mp4.

    Records where each segment ended up in the final dubbed track
    (placed_start/end), which may differ from the source-time start/end due to
    overlap-pushing and atempo stretching in the assembler. Showcase reels
    need these to cut each dub at its OWN word boundaries instead of at fixed
    source timestamps.
    """
    try:
        rows = []
        for seg in segments:
            ps = seg.get("placed_start")
            pe = seg.get("placed_end")
            if ps is None or pe is None:
                continue
            rows.append({
                "idx": seg.get("idx"),
                "src_start": float(seg.get("start", 0.0)),
                "src_end": float(seg.get("end", 0.0)),
                "dub_start": float(ps),
                "dub_end": float(pe),
            })
        out = work_dir / "tts_placements.json"
        out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        if rows:
            log.info(f"[placements] saved {len(rows)} rows -> {out.name} "
                     f"(dub range [{rows[0]['dub_start']:.1f}–{rows[-1]['dub_end']:.1f}s])")
        else:
            log.warning(f"[placements] 0 rows written to {out} — "
                        "assembler did not set placed_start/end on any segment")
    except Exception as e:
        log.warning(f"[placements] failed to save: {e}")


def load_placements(work_dir) -> list:
    """Inverse of save_placements. Returns [] if file missing/unparseable."""
    p = work_dir / "tts_placements.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning(f"[placements] failed to load {p}: {e}")
        return []