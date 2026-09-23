"""Multilingual showcase assembly.

Extracted from ``server.py``. After all sibling dubs of a showcase batch
finish, each language's dub is sliced to an equal time window (snapped to
sentence boundaries), a "· LL ·" badge is overlaid, and the slices are
concatenated into one reel.
"""
import asyncio
import json
import logging
import time
from pathlib import Path

from app.config import OUTPUT_DIR
from app.languages import QUICK_TEST_DEFAULT_LANGS as _QUICK_TEST_DEFAULT_LANGS
from app.state import jobs
from pipeline.media import (
    find_drawtext_font as _find_drawtext_font,
    probe_duration as _probe_duration,
)
from pipeline.showcase import (
    load_placements as _load_placements,
    snap_boundaries_to_sentences as _snap_boundaries_to_sentences,
)

log = logging.getLogger("tachidubb.showcase")


_showcase_assembling: set = set()  # in-progress batch IDs (de-dupe re-entry)
_showcase_tasks: set = set()       # strong refs so asyncio GC doesn't kill them


async def maybe_assemble_showcase(batch_id: str) -> None:
    """Hook called after each job finishes. If all jobs in `batch_id` are
    complete and this batch is a 'showcase', assemble the combined reel.
    No-op otherwise. Safe to call multiple times — guarded by status check
    and an in-progress set."""
    log.info(f"[showcase] maybe_assemble_showcase('{batch_id}') called")
    if not batch_id:
        log.info("[showcase] empty batch_id, skipping")
        return
    if batch_id in _showcase_assembling:
        log.info(f"[showcase] {batch_id} already assembling, skipping")
        return

    # Collect sibling jobs
    siblings = [j for j in jobs.values()
                if j.get("batch_id") == batch_id
                and j.get("batch_kind") == "showcase"]
    if not siblings:
        log.warning(f"[showcase] no siblings found for {batch_id}")
        return
    expected_total = max((j.get("batch_total") or 0) for j in siblings)
    if expected_total and len(siblings) < expected_total:
        log.info(f"[showcase] {batch_id}: only {len(siblings)}/{expected_total} jobs registered, waiting")
        return

    # All must be complete (not error/queued/running)
    statuses = [j.get("status") for j in siblings]
    if not all(s == "complete" for s in statuses):
        log.info(f"[showcase] {batch_id}: not all complete (statuses={statuses})")
        return

    # Already assembled? Bail.
    showcase_dir = OUTPUT_DIR / f"showcase_{batch_id}"
    out_mp4 = showcase_dir / "showcase.mp4"
    if out_mp4.exists():
        log.info(f"[showcase] {batch_id}: already assembled at {out_mp4}")
        return

    log.info(f"[showcase] {batch_id}: all checks passed, kicking off ffmpeg")
    _showcase_assembling.add(batch_id)
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, assemble_showcase_sync, batch_id, siblings, showcase_dir
        )
    except Exception as e:
        log.error(f"[showcase] {batch_id}: assembler crashed: {e}", exc_info=True)
    finally:
        _showcase_assembling.discard(batch_id)



def assemble_showcase_sync(batch_id: str, siblings: list, showcase_dir: Path) -> None:
    """Synchronous worker for showcase assembly. Runs in a thread to keep
    the event loop responsive (ffmpeg is blocking)."""
    import subprocess  # follow existing per-function-import pattern
    siblings = sorted(siblings, key=lambda j: j.get("batch_position", 0))
    n = len(siblings)
    log.info(f"[showcase] {batch_id}: assembling {n} language segments…")

    # ── Load source segment times (any sibling has them; pick the first) ─
    segments: list = []
    for j in siblings:
        work = OUTPUT_DIR / j["id"]
        for cp_name in ("checkpoint_translation_done.json",
                        "checkpoint_transcription_done.json"):
            cp = work / cp_name
            if cp.exists():
                try:
                    data = json.loads(cp.read_text(encoding="utf-8"))
                    segments = data.get("segments", []) or []
                    if segments:
                        break
                except Exception as e:
                    log.warning(f"[showcase] couldn't parse {cp}: {e}")
        if segments:
            break

    # ── Verify all dub files exist ────────────────────────────────────
    missing = [OUTPUT_DIR / j["id"] / "dubbed_video.mp4"
               for j in siblings
               if not (OUTPUT_DIR / j["id"] / "dubbed_video.mp4").exists()]
    if missing:
        log.error(f"[showcase] {batch_id}: {len(missing)} dub file(s) missing — aborting")
        return

    # ── Pre-load ALL placements once, compute effective dub duration ──
    # The dubbed audio for each language is typically shorter than the source
    # video because TTS may run faster (atempo-stretched) and the assembler
    # trims trailing silence. The VIDEO container duration == source duration
    # (we pad the last frame), so probing the mp4 gives ~120s for a 120s
    # source — but the AUDIO ends at 95-106s. If we slice into [95-120s] of
    # a dub that has no audio there, we get silence in the showcase.
    # Solution: compute total_dur from the ACTUAL last placed segment in every
    # dub (max dub_end across placements), then take min so every language
    # has content throughout the full showcase.
    all_placements: dict = {}   # job_id -> list of placement rows
    effective_ends: list = []   # max dub_end per sibling
    for j in siblings:
        pl = _load_placements(OUTPUT_DIR / j["id"])
        all_placements[j["id"]] = pl
        if pl:
            effective_ends.append(max(p["dub_end"] for p in pl))
        else:
            # Fallback: probe dubbed audio track duration (not the mp4 container)
            # using ffprobe's stream-level query which returns audio stream duration.
            import subprocess as _sp
            audio_dur = 0.0
            try:
                r = _sp.run(
                    ["ffprobe", "-v", "error",
                     "-select_streams", "a:0",
                     "-show_entries", "stream=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1",
                     str(OUTPUT_DIR / j["id"] / "dubbed_video.mp4")],
                    check=True, capture_output=True, text=True, timeout=15,
                )
                audio_dur = float((r.stdout or "0").strip() or 0)
            except Exception:
                pass
            if audio_dur > 0:
                effective_ends.append(audio_dur)
            else:
                log.warning(f"[showcase] {j['id']}: no placements and audio probe failed; "
                            "showcase may include silent tail for this language")

    if not effective_ends:
        # True last-resort: use source video duration
        first_source = Path(siblings[0].get("source", ""))
        fallback_dur = _probe_duration(first_source) if first_source.exists() else 0.0
        if fallback_dur <= 0:
            log.error(f"[showcase] {batch_id}: could not determine any dub duration — aborting")
            return
        total_dur = fallback_dur
        log.warning(f"[showcase] using source duration as total_dur fallback ({total_dur:.1f}s)")
    else:
        total_dur = min(effective_ends)
        log.info(f"[showcase] effective dub durations: "
                 f"{[f'{d:.1f}' for d in effective_ends]}s → using min={total_dur:.1f}s")

    slices = _snap_boundaries_to_sentences(segments, total_dur, n)
    log.info(f"[showcase] source-time slices: {[f'{s:.1f}-{e:.1f}' for s, e in slices]}")

    # ── Map each source-time slice to per-dub time using placements ────
    # Key fix: use OVERLAP matching — a segment spans [src_start, src_end]
    # in source time and [dub_start, dub_end] in dub time. We want every
    # segment that OVERLAPS the slice [g_s, g_e], not just those whose start
    # falls inside. Without overlap matching, a long merged segment (e.g.
    # src [30-85s]) will cover several source slices but only be found for
    # the one whose boundary contains 30s. This caused 30s source slices to
    # map to only 7s of dub time (one tail segment found instead of all).
    LEAD = 0.05   # 50ms lead so we don't clip a word's onset
    TRAIL = 0.15  # 150ms trail for a clean release
    per_dub_ranges: list = []
    for slice_idx, (g_s, g_e) in enumerate(slices):
        job = siblings[slice_idx]
        placements = all_placements.get(job["id"], [])
        # Effective audio end for this dub (from placements or fallback)
        eff_end = (max(p["dub_end"] for p in placements)
                   if placements else effective_ends[slice_idx]
                   if slice_idx < len(effective_ends) else total_dur)
        # Overlap matching: segment overlaps slice if src_start < g_e AND src_end > g_s
        in_slice = [
            p for p in placements
            if p["src_start"] < g_e + 0.001 and p["src_end"] > g_s - 0.001
        ]
        if in_slice:
            # Key: include the SOURCE time range as well as the dub placement
            # range. In the dubbed video, non-speech gaps keep source timing
            # (assembler places segments at their source timestamps). So a
            # slice [67.5-79s] that has a speech segment placed at dub[70-72s]
            # should show dub[67.5-79s] — not just [70-72s] — to include the
            # gap/background content before and after the speech burst.
            d_start = max(0.0, min(min(p["dub_start"] for p in in_slice), g_s) - LEAD)
            d_end = min(eff_end, max(max(p["dub_end"] for p in in_slice), g_e) + TRAIL)
            # Sanity: never go past eff_end or before 0
            if d_end <= d_start + 0.1:
                d_start = max(0.0, g_s)
                d_end = min(eff_end, g_e)
            log.info(f"[showcase] slice {slice_idx} ({job.get('target_lang')}): "
                     f"src [{g_s:.2f}-{g_e:.2f}] -> dub [{d_start:.2f}-{d_end:.2f}] "
                     f"({len(in_slice)} segs, eff_end={eff_end:.1f}s)")
        else:
            # No speech in this slice — show source-equivalent gap content,
            # clamped to effective audio end.
            d_start = max(0.0, g_s)
            d_end = min(g_e, eff_end)
            if d_end <= d_start + 0.05:
                log.warning(f"[showcase] slice {slice_idx} ({job.get('target_lang')}): "
                            f"no speech and eff_end={eff_end:.1f}s < slice_start={g_s:.1f}s "
                            f"— skipping (will use 0.1s stub)")
                d_end = d_start + 0.1  # avoid zero-length segment crashing ffmpeg
            else:
                log.warning(f"[showcase] slice {slice_idx} ({job.get('target_lang')}): "
                            f"no speech in slice, showing gap [{d_start:.2f}-{d_end:.2f}]")
        per_dub_ranges.append((job, d_start, d_end))

    # ── Build ffmpeg filter_complex ───────────────────────────────────
    showcase_dir.mkdir(parents=True, exist_ok=True)
    font_path = _find_drawtext_font()
    # ffmpeg filter syntax requires escaped colons on Windows paths
    font_arg = font_path.replace("\\", "/").replace(":", r"\:") if font_path else ""

    filter_parts = []
    inputs = []
    for idx, (job, start, end) in enumerate(per_dub_ranges):
        src = OUTPUT_DIR / job["id"] / "dubbed_video.mp4"
        inputs.extend(["-i", str(src)])
        lang_code = (job.get("target_lang") or "").upper()
        label = f"· {lang_code} ·"  # · LL ·
        seg_dur = max(0.1, end - start)

        # Escape single quotes and special chars for drawtext text= field
        text_safe = label.replace("'", r"\'")

        drawtext = (
            "drawtext="
            + (f"fontfile='{font_arg}':" if font_arg else "")
            + f"text='{text_safe}':"
            "fontsize=22:fontcolor=white:"
            "box=1:boxcolor=black@0.55:boxborderw=8:"
            "x=w-tw-24:y=24"
        )

        filter_parts.append(
            f"[{idx}:v]trim=start={start:.3f}:end={end:.3f},"
            f"setpts=PTS-STARTPTS,{drawtext}[v{idx}]"
        )
        # apad+atrim guarantees the audio is EXACTLY seg_dur long: if the
        # dub's audio stream ends before `end` (TTS finished early) apad
        # fills with silence; atrim caps any overflow. Without this, ffmpeg
        # concat hands us a shorter audio stream than video and you get
        # the "audio cuts off at 50.6s while video runs 60s" bug.
        filter_parts.append(
            f"[{idx}:a]atrim=start={start:.3f}:end={end:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"apad=whole_dur={seg_dur:.3f},"
            f"atrim=duration={seg_dur:.3f}[a{idx}]"
        )

    # Concat all trimmed pieces
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[vout][aout]")
    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(showcase_dir / "showcase.mp4"),
    ]

    out_dur = sum(e - s for _, s, e in per_dub_ranges)
    log.info(f"[showcase] running ffmpeg ({n} inputs, {out_dur:.1f}s out)")
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")[-1200:]
        log.error(f"[showcase] ffmpeg failed:\n{err}")
        # Write a marker so the UI can surface the failure
        try:
            (showcase_dir / "error.txt").write_text(err, encoding="utf-8")
        except Exception:
            pass
        return

    # Write a manifest for the UI
    try:
        manifest = {
            "batch_id": batch_id,
            "created": time.time(),
            "n_segments": n,
            "slices": [
                {
                    "lang": j.get("target_lang"),
                    "src_start": float(src_s),
                    "src_end": float(src_e),
                    "dub_start": float(d_s),
                    "dub_end": float(d_e),
                    "job_id": j["id"],
                }
                for (j, d_s, d_e), (src_s, src_e) in zip(per_dub_ranges, slices)
            ],
            "total_seconds": float(out_dur),
        }
        (showcase_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        log.warning(f"[showcase] manifest write failed: {e}")

    log.info(f"[showcase] {batch_id}: done -> {showcase_dir / 'showcase.mp4'}")


# Default language picks for the Showcase feature — same defaults as
# Quick Test but kept separate so they can diverge if needed.
_SHOWCASE_DEFAULT_LANGS = _QUICK_TEST_DEFAULT_LANGS

