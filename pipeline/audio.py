"""Audio extraction and vocal/background separation.

Separation priority:
  1. Demucs (htdemucs_ft) — best quality, ships with torch, no extra install
  2. audio-separator — alternative if installed
  3. Silent background fallback — if neither is available
"""
import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger("tachidubb.audio")


def _run(cmd, desc="", timeout=600):
    log.info(f"[{desc}] {' '.join(str(c) for c in cmd[:8])}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{desc} failed: {r.stderr[:400]}")
    return r


def extract_audio(video_path: str, audio_path: str) -> str:
    """Extract 16kHz mono WAV for Whisper."""
    _run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path,
    ], "extract audio")
    return audio_path


def extract_audio_hq(video_path: str, audio_path: str) -> str:
    """Extract 44.1kHz stereo WAV for background separation."""
    _run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
        audio_path,
    ], "extract HQ audio")
    return audio_path


def _separate_demucs(audio_path: str, output_dir: str) -> tuple[str, str]:
    """Separate vocals/background using Demucs (htdemucs_ft model).

    Demucs ships with torch — no extra install required if torch is present.
    Uses the fine-tuned htdemucs_ft model (best for speech/music separation).

    Returns (vocals_path, background_path) as 44.1kHz stereo WAVs.
    """
    import torch

    log.info("Separating vocals with Demucs (htdemucs_ft)...")
    try:
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
        import torchaudio

        model = get_model("htdemucs_ft")
        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()

        wav, sr = torchaudio.load(audio_path)
        # Demucs expects (batch, channels, time) at its native sample rate
        if sr != model.samplerate:
            wav = torchaudio.functional.resample(wav, sr, model.samplerate)
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)  # mono → stereo

        with torch.no_grad():
            sources = apply_model(model, wav.unsqueeze(0))

        stems = model.sources  # e.g. ["drums", "bass", "other", "vocals"]
        vocals_idx = stems.index("vocals")

        vocals_wav = sources[0, vocals_idx].cpu()
        # Background = everything except vocals (sum non-vocal stems)
        bg_parts = [sources[0, i].cpu() for i in range(len(stems)) if i != vocals_idx]
        bg_wav = sum(bg_parts)

        vocals_path = os.path.join(output_dir, "vocals.wav")
        bg_path = os.path.join(output_dir, "background.wav")

        torchaudio.save(vocals_path, vocals_wav, model.samplerate)
        torchaudio.save(bg_path, bg_wav, model.samplerate)

        log.info("Demucs separation complete")
        return vocals_path, bg_path

    except ImportError:
        raise RuntimeError("demucs not installed — run: pip install demucs")


def _separate_audio_separator(audio_path: str, output_dir: str) -> tuple[str, str]:
    """Fallback separation using audio-separator library."""
    vocals = os.path.join(output_dir, "vocals.wav")
    bg = os.path.join(output_dir, "background.wav")

    from audio_separator.separator import Separator
    sep = Separator(output_dir=output_dir)
    sep.load_model()
    outputs = sep.separate(audio_path)
    if isinstance(outputs, (list, tuple)) and len(outputs) >= 2:
        for out in outputs:
            if "vocal" in out.lower():
                shutil.move(out, vocals)
            elif any(k in out.lower() for k in ("instrumental", "bg", "no_vocal")):
                shutil.move(out, bg)
        if not os.path.exists(vocals) and outputs:
            shutil.move(outputs[0], vocals)
        if not os.path.exists(bg) and len(outputs) > 1:
            shutil.move(outputs[1], bg)
    log.info("audio-separator separation complete")
    return vocals, bg


def _make_silent_bg(duration: float, output_dir: str) -> str:
    """Create a silent WAV of the given duration as background placeholder."""
    bg = os.path.join(output_dir, "background.wav")
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"anullsrc=r=44100:cl=stereo:d={duration}",
        "-acodec", "pcm_s16le", bg,
    ], "silent bg")
    return bg


def _downsample_16k_mono(src_path: str, dst_path: str) -> str:
    """Resample any audio file to the 16 kHz mono WAV the ASR chain expects."""
    _run([
        "ffmpeg", "-y", "-i", src_path,
        "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", dst_path,
    ], "downsample speech track")
    return dst_path


def _separator_available() -> bool:
    """True when demucs or audio-separator can actually run."""
    for mod in ("demucs", "audio_separator"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


def build_speech_track(video_path: str, work_dir: str, full_mix: str,
                       keep_bg: bool) -> tuple[str, str]:
    """Stem split FIRST: separate background from speech, then hand back the
    speech track the whole ASR chain reads.

    Runs for every job — the clean vocals stem is what makes Whisper,
    diarization and speaker-ref extraction good — while the background stem
    it also writes (``work_dir/background.wav``) is only returned for the
    final mix when ``keep_bg`` is set. Both stems are written either way:
    the editor and future per-speaker work read them from the job dir.

    Returns ``(speech_path, background_path)``:
      - speech_path: vocals stem downsampled to 16 kHz mono; falls back to
        ``full_mix`` when no separator is installed or separation fails, so
        the pipeline then behaves exactly like pre-stem builds.
      - background_path: background stem to mix under the dub ("" when
        ``keep_bg`` is off or separation is unavailable).
    """
    if not _separator_available():
        if keep_bg:
            log.warning(
                "keep_bg is on but no separator (demucs/audio-separator) is "
                "installed — transcribing the full mix, background will NOT "
                "be mixed (see System page)"
            )
        else:
            log.info("[stems] No separator installed — ASR uses the full mix")
        return full_mix, ""

    try:
        t0 = time.time()
        audio_hq = os.path.join(work_dir, "audio_hq.wav")
        extract_audio_hq(video_path, audio_hq)
        vocals, bg = separate_background(audio_hq, work_dir)
        speech = os.path.join(work_dir, "audio_speech.wav")
        _downsample_16k_mono(vocals, speech)
        log.info(
            f"[stems] Split in {time.time()-t0:.0f}s: vocals -> "
            f"audio_speech.wav (ASR input), background -> background.wav "
            f"({'mixed' if keep_bg else 'kept for editor, not mixed'})"
        )
        return speech, (bg if keep_bg else "")
    except Exception as e:
        log.warning(f"Stem separation unavailable (ASR uses the full mix): {e}")
        return full_mix, ""


def separate_background(audio_path: str, output_dir: str) -> tuple[str, str]:
    """Separate vocals from background audio.

    Tries in order:
      1. Demucs (htdemucs_ft) — best quality
      2. audio-separator — alternative
      3. Silent background fallback

    Returns (vocals_path, background_path).
    """
    vocals = os.path.join(output_dir, "vocals.wav")
    bg = os.path.join(output_dir, "background.wav")

    # Try Demucs first
    try:
        return _separate_demucs(audio_path, output_dir)
    except RuntimeError as e:
        if "not installed" in str(e):
            log.info("Demucs not installed, trying audio-separator...")
        else:
            log.warning(f"Demucs failed: {e}, trying audio-separator...")
    except Exception as e:
        log.warning(f"Demucs error: {e}, trying audio-separator...")

    # Try audio-separator
    try:
        return _separate_audio_separator(audio_path, output_dir)
    except ImportError:
        log.warning("Neither demucs nor audio-separator installed — no separation")
    except Exception as e:
        log.warning(f"audio-separator failed: {e}")

    # Fallback: copy audio as vocals, silent background
    shutil.copy2(audio_path, vocals)
    dur = get_duration(audio_path)
    bg = _make_silent_bg(dur, output_dir)
    return vocals, bg


def get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0
