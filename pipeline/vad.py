"""Voice Activity Detection — strip non-speech regions before Whisper.

WhisperX already uses Silero VAD internally, but running it explicitly
upfront lets us:
  1. Remove long silence / music intros that cause Whisper hallucinations
  2. Report how much of the audio is actually speech (diagnostic)
  3. Optionally gate transcription on minimum speech ratio

Uses silero-vad (ONNX-based, 1 MB model, no GPU required).
Falls back gracefully if silero-vad is not installed.
"""
import logging
import subprocess

log = logging.getLogger("tachidubb.vad")

# Minimum ratio of speech to total audio — below this we warn the user
SPEECH_RATIO_WARNING = 0.15

# Padding added around each speech segment (seconds) to avoid clipping
SEGMENT_PAD = 0.1


def _run_ffmpeg(cmd, desc="", timeout=300):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{desc} failed: {r.stderr[:300]}")
    return r


def get_speech_timestamps(audio_path: str, threshold: float = 0.5) -> list[dict]:
    """Return Silero VAD timestamps as list of {start, end} dicts (seconds).

    Falls back to [{start: 0, end: duration}] if silero-vad not installed,
    so callers don't need to special-case the missing-dependency path.
    """
    try:
        import torch
        import torchaudio  # noqa — needed by silero-vad load_silero_vad

        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=True,
            verbose=False,
        )
        get_ts = utils[0]  # get_speech_timestamps is utils[0]
        read_audio = utils[2]

        wav = read_audio(audio_path, sampling_rate=16000)
        timestamps = get_ts(wav, model, sampling_rate=16000, threshold=threshold)
        result = [
            {"start": t["start"] / 16000, "end": t["end"] / 16000}
            for t in timestamps
        ]
        log.info(f"VAD: {len(result)} speech segments detected")
        return result
    except ImportError:
        log.debug("silero-vad not installed — VAD skipped, using full audio")
        return []
    except Exception as e:
        log.warning(f"VAD failed ({e}) — using full audio")
        return []


def _get_duration_ffprobe(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def speech_regions(audio_path: str, threshold: float = 0.5,
                   total_dur: float | None = None) -> list:
    """Padded + merged speech regions as [(start, end), ...] in ORIGINAL time.

    This is the exact geometry :func:`apply_vad_filter` uses to build its
    ``atrim``/``concat`` filter — anything that must translate between the
    compressed VAD output and the original timeline (see
    :func:`restore_original_times`) has to go through here so the mapping
    can never drift from the actual audio.

    Returns [] when Silero isn't installed or finds no speech (the caller
    then keeps the original audio unchanged). ``total_dur`` is passed in by
    callers that already probed it; otherwise it's read via ffprobe.
    """
    timestamps = get_speech_timestamps(audio_path, threshold=threshold)
    if not timestamps:
        return []
    if total_dur is None:
        total_dur = _get_duration_ffprobe(audio_path)
        if total_dur <= 0:
            return []

    # Add padding and clamp to audio bounds
    padded = []
    for t in timestamps:
        s = max(0.0, t["start"] - SEGMENT_PAD)
        e = min(total_dur, t["end"] + SEGMENT_PAD)
        padded.append((s, e))

    # Merge overlapping/adjacent segments
    merged = []
    for s, e in sorted(padded):
        if merged and s <= merged[-1][1] + 0.05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def map_time(t: float, regions: list | None) -> float:
    """Map a time from the compressed VAD output back to original time.

    ``t`` is a position in the concatenated file; ``regions`` are the padded
    speech regions (original time) that were concatenated to build it. Returns
    ``t`` unchanged when ``regions`` is None (no compression happened).
    Positions past the end of speech (Whisper can pad slightly beyond the
    file) clamp to the last region's end rather than extrapolating into
    nothing.
    """
    if not regions:
        return t
    acc = 0.0
    for s, e in regions:
        dur = e - s
        if t <= acc + dur:
            return max(0.0, s + (t - acc))
        acc += dur
    return regions[-1][1]


def restore_original_times(segments: list, regions: list | None) -> list:
    """Rewrite ``start``/``end`` (and word timings) from VAD-compressed time
    back to original video time, in place. No-op when ``regions`` is None.

    Segments carry both kinds of timing during the pipeline: VAD concatenates
    speech before Whisper runs, so transcript/diarization timestamps live on
    the compressed clock, while assembly, SRT, showcase cuts, the editor
    timeline and the review UI all compare against the source video. Calling
    this once, after the last consumer of the compressed audio (reference
    extraction), puts every later stage on the video clock.
    """
    if not regions:
        return segments
    for seg in segments:
        if seg.get("start") is not None:
            seg["start"] = map_time(float(seg["start"]), regions)
        if seg.get("end") is not None:
            seg["end"] = map_time(float(seg["end"]), regions)
        for w in seg.get("words") or []:
            if w.get("start") is not None:
                w["start"] = map_time(float(w["start"]), regions)
            if w.get("end") is not None:
                w["end"] = map_time(float(w["end"]), regions)
    return segments


def apply_vad_filter(audio_path: str, output_path: str,
                     threshold: float = 0.5) -> tuple[str, float, list | None]:
    """Extract only speech regions from audio_path into output_path.

    Returns ``(output_path, speech_ratio, regions)``:
      - speech_ratio: fraction of the original audio that is speech (0.0-1.0)
      - regions: the padded/merged speech regions (original time) that were
        concatenated, or None when the output keeps the original timeline
        (no Silero, no speech found, audio already dense, or ffmpeg failed) —
        i.e. None means "no remapping needed".

    NOTE: when regions is not None the output timeline is COMPRESSED —
    Whisper timestamps from it are NOT video timestamps. Use
    :func:`restore_original_times` before anything touches the video clock.

    If silero-vad isn't installed or VAD finds no segments, copies the
    original audio unchanged and returns speech_ratio=1.0 (conservative).

    This helps Whisper in two ways:
      1. Removes long music intros that cause hallucinations like
         "Translated by XYZ" or repeated filler phrases.
      2. Reduces total audio length → faster transcription.
    """
    total_dur = _get_duration_ffprobe(audio_path)
    if total_dur <= 0:
        import shutil
        shutil.copy2(audio_path, output_path)
        return output_path, 1.0, None

    regions = speech_regions(audio_path, threshold=threshold, total_dur=total_dur)
    if not regions:
        import shutil
        shutil.copy2(audio_path, output_path)
        return output_path, 1.0, None

    speech_seconds = sum(e - s for s, e in regions)
    speech_ratio = speech_seconds / total_dur if total_dur > 0 else 1.0

    if speech_ratio < SPEECH_RATIO_WARNING:
        log.warning(
            f"VAD: only {speech_ratio*100:.0f}% speech detected in audio. "
            f"Background music or silence may affect transcription quality."
        )

    if speech_ratio > 0.90:
        # Almost all speech — skip filtering, not worth the overhead.
        # Timeline unchanged, so regions stays None (no remap needed).
        log.info(
            f"VAD: {speech_ratio*100:.0f}% speech — audio is dense, skipping filter"
        )
        import shutil
        shutil.copy2(audio_path, output_path)
        return output_path, speech_ratio, None

    # Build ffmpeg filter: select speech intervals + concatenate
    # atrim=start=X:end=Y, then concat all pieces
    pieces = []
    for i, (s, e) in enumerate(regions):
        pieces.append(
            f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )

    n = len(regions)
    concat_inputs = "".join(f"[a{i}]" for i in range(n))
    filter_complex = ";".join(pieces) + f";{concat_inputs}concat=n={n}:v=0:a=1[out]"

    try:
        _run_ffmpeg([
            "ffmpeg", "-y", "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            output_path,
        ], "VAD filter", timeout=300)
        log.info(
            f"VAD: filtered {total_dur:.0f}s → {speech_seconds:.0f}s "
            f"({speech_ratio*100:.0f}% speech, {n} segments)"
        )
        return output_path, speech_ratio, regions
    except Exception as e:
        log.warning(f"VAD ffmpeg filter failed ({e}) — using full audio")
        import shutil
        shutil.copy2(audio_path, output_path)
        return output_path, 1.0, None
