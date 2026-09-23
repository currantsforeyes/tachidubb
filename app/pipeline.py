"""Dubbing pipeline orchestrator.

Extracted from ``server.py``. Runs one dub end to end: download -> extract ->
(VAD / denoise) -> transcribe -> diarize -> post-process -> translate -> TTS ->
assemble -> merge. Pauses at checkpoints when ``wizard_mode`` requests review.
"""
import asyncio
import logging
import os
import time
from pathlib import Path

from app.checkpoints import load_checkpoint, save_checkpoint
from app.config import OUTPUT_DIR, cfg
from app.queue import JobCancelled
from app.state import jobs, save_job
from app.tts import get_tts_engine, terminate_tts_worker
from app.voices import resolve_voice_config
from pipeline.assembler import assemble_dubbed_audio, merge_audio_video, write_srt
from pipeline.audio import (
    extract_audio,
    extract_audio_hq,
    get_duration,
    separate_background,
)
from pipeline.diarizer import (
    assign_speakers_to_segments,
    diarize_speakers,
    extract_fallback_reference,
    extract_speaker_audio,
)
from pipeline.downloader import download_video
from pipeline.showcase import save_placements
from pipeline.synthesizer import QwenTTSEngine, VoxCPMSynthesizer
from pipeline.transcriber import transcribe
from pipeline.translator import translate_segments, unload_ollama_model
from pipeline.vad import apply_vad_filter

log = logging.getLogger("tachidubb.pipeline")


async def run_pipeline(
    job_id: str,
    source: str,
    source_lang: str,
    target_lang: str,
    model: str,
    keep_bg: bool,
    whisper_model: str,
    reference_audio: str = "",
    speaker_mode: str = "main",
    speaker_count: int = 0,
    context_hint: str = "",
    voice_style: str = "",
    voice_preset: str = "auto",
    tts_speed: str = "balanced",
    wizard_mode: str = "auto",  # "auto" | "review_translation" | "review_transcript"
    auto_denoise: bool = True,  # apply ffmpeg denoise before WhisperX
):
    """Main dubbing pipeline. When wizard_mode != 'auto', pauses at the
    specified checkpoint with status='awaiting_review' so the user can
    inspect/edit intermediate results before continuing."""
    job = jobs[job_id]
    work = OUTPUT_DIR / job_id
    work.mkdir(exist_ok=True)
    job["wizard_mode"] = wizard_mode

    # Resolve final voice config once, store on job so UI can display it
    eff_style, voice_seed, preset_ref_file = resolve_voice_config(voice_preset, voice_style, job_id)
    job["voice_preset"] = voice_preset
    job["voice_style_effective"] = eff_style
    job["voice_seed"] = voice_seed

    # If a file-based preset was selected, it acts like user-uploaded reference
    if preset_ref_file and os.path.exists(preset_ref_file):
        log.info(f"[ref] File-preset selected: {preset_ref_file}")
        reference_audio = preset_ref_file

    def update(**kwargs):
        # Check the cancel flag at every stage transition. Any pipeline
        # path that calls update() will raise JobCancelled within ~1
        # instruction of the user clicking Cancel, and the outer handler
        # in the queue worker will mark status=cancelled cleanly.
        if job.get("cancel_requested"):
            terminate_tts_worker()
            raise JobCancelled(f"Job {job_id} cancelled by user")
        job.update(kwargs)
        save_job(job)

    try:
        # 1. Acquire video
        update(status="downloading", progress=2, step_detail="Getting video...")
        video_path = download_video(source, str(work))
        duration = get_duration(video_path)
        update(duration=round(duration, 1), progress=8)

        # 2. Extract audio
        update(status="extracting", progress=10, step_detail="Extracting audio tracks...")
        audio_16k = str(work / "audio_16k.wav")
        extract_audio(video_path, audio_16k)

        # 2b. Optional denoise for noisy source audio.
        # BJJ/cooking/sports videos often have mat noise, background music,
        # crowd, or equipment hum that WhisperX mistakes for words. We
        # apply an ffmpeg filter chain to clean the audio WITHOUT removing
        # voice quality. Enabled via auto_denoise flag (default True on
        # high-duration videos where noise can compound error rate).
        # Filter chain reasoning:
        #   - afftdn: FFT-based noise reduction (safe, preserves speech)
        #   - highpass=80: drop sub-bass rumble (room noise, AC)
        #   - lowpass=10000: drop tweeter noise (mic hiss, digital artifacts)
        # This is conservative; aggressive denoise can hurt Whisper accuracy.
        if auto_denoise:
            try:
                import subprocess
                denoise_start = time.time()
                audio_clean = str(work / "audio_16k_clean.wav")
                update(progress=12, step_detail="Cleaning audio...")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", audio_16k,
                     "-af", "afftdn=nr=10:nf=-25,highpass=f=80,lowpass=f=10000",
                     "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
                     audio_clean],
                    check=True, capture_output=True, timeout=180,
                )
                log.info(
                    f"[audio] Denoised in {time.time()-denoise_start:.1f}s "
                    f"(audio_16k_clean.wav) — feeding to WhisperX"
                )
                audio_16k = audio_clean
            except Exception as e:
                log.warning(f"Denoise failed (using raw audio): {e}")

        bg_audio_path = ""
        if keep_bg:
            try:
                audio_hq = str(work / "audio_hq.wav")
                extract_audio_hq(video_path, audio_hq)
                _, bg_audio_path = separate_background(audio_hq, str(work))
            except Exception as e:
                log.warning(f"BG separation skipped: {e}")
        update(progress=15)

        # 2c. VAD filtering — strip long silence/music before Whisper.
        # silero-vad is optional (graceful fallback to full audio).
        if cfg.vad_enabled:
            try:
                vad_out = str(work / "audio_16k_vad.wav")
                update(progress=16, step_detail="Filtering non-speech regions...")
                audio_16k, speech_ratio = apply_vad_filter(
                    audio_16k, vad_out, threshold=cfg.vad_threshold
                )
                if speech_ratio < 0.15:
                    log.warning(
                        f"[vad] Low speech ratio ({speech_ratio:.0%}) — "
                        f"consider disabling VAD or checking audio source"
                    )
            except Exception as e:
                log.warning(f"VAD skipped: {e}")

        # 3. Transcribe
        # 3. Transcribe with elapsed-time progress hint.
        # WhisperX doesn't expose internal progress, so during long transcription
        # (e.g. 20-min podcasts take 5-6min) the UI would just show "Transcribing..."
        # forever. We spawn a watchdog that updates step_detail with elapsed
        # seconds so the user can see it's still alive.
        update(status="transcribing", progress=18, step_detail="Transcribing speech...")
        _t_trans_start = time.time()
        _trans_done_flag = {"done": False}
        async def _trans_watchdog():
            while not _trans_done_flag["done"]:
                elapsed = int(time.time() - _t_trans_start)
                if elapsed > 10:  # only show after 10s to avoid noise on short videos
                    mins, secs = divmod(elapsed, 60)
                    hint = f"Transcribing ({duration:.0f}s audio)... elapsed {mins}m{secs:02d}s"
                    if elapsed > 120:
                        hint += " · try smaller whisper model for faster transcribe"
                    update(step_detail=hint)
                await asyncio.sleep(5)
        _watchdog_task = asyncio.create_task(_trans_watchdog())
        try:
            segments, detected_lang = transcribe(audio_16k, source_lang, whisper_model)
        finally:
            _trans_done_flag["done"] = True
            _watchdog_task.cancel()
            try:
                await _watchdog_task
            except (asyncio.CancelledError, Exception):
                pass
        log.info(
            f"[transcribe] Completed in {time.time() - _t_trans_start:.1f}s "
            f"({duration:.0f}s audio, ratio {duration / max(time.time() - _t_trans_start, 1):.1f}x realtime)"
        )
        effective_src = detected_lang if source_lang == "auto" else source_lang
        update(
            source_lang_detected=detected_lang,
            segment_count=len(segments),
            progress=35,
        )

        if not segments:
            raise RuntimeError("No speech detected in video")

        # 4. Diarize
        update(status="diarizing", progress=38, step_detail="Identifying speakers...")
        hf_token = os.getenv("HF_TOKEN", "")
        requested_speakers = speaker_count if speaker_count >= 2 else None
        speaker_turns = diarize_speakers(
            audio_16k,
            min_speakers=requested_speakers,
            max_speakers=requested_speakers,
            hf_token=hf_token,
        )
        segments = assign_speakers_to_segments(segments, speaker_turns)

        # Store raw transcript preview for UI
        transcript_preview_raw = [
            {
                "idx": i,
                "start": s["start"], "end": s["end"],
                "text": s["text"],
                "speaker": s.get("speaker", ""),
            }
            for i, s in enumerate(segments)
        ]
        update(transcript_raw=transcript_preview_raw)

        speaker_refs = {}
        speaker_transcripts = {}
        # Always-preserved copy of refs extracted from the SOURCE video.
        # Even when user picks a preset/upload (which overrides speaker_refs),
        # we still stash the original source refs here so that "retry TTS"
        # without re-choosing a ref can go back to the source voice. Without
        # this, the uploaded preset got baked into the checkpoint and retry
        # would silently reuse it forever.
        source_speaker_refs = {}

        # Case A: user uploaded a reference voice -> use it for ALL speakers.
        # Pure Controllable Cloning: just reference_wav_path, nothing else.
        # VoxCPM2 README: "Clone any voice from a short reference clip".
        if reference_audio and os.path.exists(reference_audio):
            log.info(f"[ref] Using USER-UPLOADED reference: {reference_audio}")
            unique_speakers = {s.get("speaker", "SPEAKER_00") for s in segments}
            for sp in unique_speakers:
                speaker_refs[sp] = reference_audio
                # NOT populating speaker_transcripts — we want clean Controllable
                # Cloning (reference_wav_path only), not Ultimate Cloning which
                # needs an exact transcript of the reference audio and is
                # stricter about audio continuation.
                speaker_transcripts[sp] = ""
            # Also extract source refs for potential retry-with-source-voice
            if speaker_turns:
                try:
                    refs_dir = str(work / "speaker_refs")
                    source_speaker_refs = extract_speaker_audio(
                        audio_16k, speaker_turns, refs_dir, main_only=False,
                    ) or {}
                    log.info(f"[ref] Also extracted {len(source_speaker_refs)} "
                             f"source-voice refs for potential retry use")
                except Exception as e:
                    log.warning(f"[ref] Source-ref extraction failed (ok to skip): {e}")

        # Case B: diarization worked -> per-speaker refs from the source
        elif speaker_turns:
            log.info("[ref] No user upload; extracting speaker refs from source video")
            refs_dir = str(work / "speaker_refs")
            main_only = speaker_mode == "main"
            speaker_refs = extract_speaker_audio(
                audio_16k, speaker_turns, refs_dir, main_only=main_only,
            )
            # Source refs = speaker_refs in this case (same origin)
            source_speaker_refs = dict(speaker_refs)
            if speaker_refs:
                # Populate speaker_transcripts (enables Tier 1 Ultimate Cloning)
                # ONLY for same-language dubbing. Cross-lingual Tier 1 makes
                # VoxCPM "continue" the source-language phonetics, so Russian
                # text comes out with English phonemes = gibberish. For
                # cross-lingual we want Tier 2 Controllable Cloning which just
                # clones timbre without audio-continuation.
                same_lang = (effective_src == target_lang)
                if same_lang:
                    for spk in speaker_refs:
                        texts = [s["text"] for s in segments
                                 if s.get("speaker") == spk]
                        if texts:
                            speaker_transcripts[spk] = " ".join(texts[:3])
                else:
                    log.info(f"[ref] Cross-lingual dub ({effective_src}→{target_lang}); "
                             f"clearing prompt_text to force Controllable Cloning")
                    for spk in speaker_refs:
                        speaker_transcripts[spk] = ""

            # If main_only: remap EVERY segment to the sole extracted speaker
            if main_only and speaker_refs:
                primary = next(iter(speaker_refs))
                for s in segments:
                    s["speaker"] = primary

        # Case C: diarization failed -> build ONE clean reference from long segments
        if not speaker_refs:
            log.info("[ref] No user upload + diarization unavailable - "
                     "building fallback single-speaker reference from source")
            fb_path = str(work / "speaker_refs" / "ref_fallback.wav")
            (work / "speaker_refs").mkdir(exist_ok=True)
            fb = extract_fallback_reference(audio_16k, segments, fb_path, duration=30.0)
            if fb:
                speaker_refs["SPEAKER_00"] = fb
                source_speaker_refs["SPEAKER_00"] = fb  # same source as above
                # Same cross-lingual guard as Case B
                if effective_src == target_lang:
                    speaker_transcripts["SPEAKER_00"] = " ".join(
                        s["text"] for s in segments[:5]
                    )
                else:
                    speaker_transcripts["SPEAKER_00"] = ""
                for s in segments:
                    s["speaker"] = "SPEAKER_00"

        # ─── POST-PROCESS SEGMENTS ───────────────────────────────
        # WhisperX cuts on VAD (breath) boundaries, not sentence boundaries,
        # so natural sentences often get split at pauses. The resulting
        # micro-fragments (10-20 chars, <2s) give TTS too little context to
        # clone voice correctly and produce "кашка" output. This pass
        # merges continuations, absorbs orphan fragments, and splits
        # monster segments. See pipeline/segment_post.py for details.
        try:
            from pipeline.segment_post import postprocess_segments
            segments = postprocess_segments(segments)
        except Exception as e:
            log.warning(f"Segment postprocess failed (continuing with raw): {e}")

        n_speakers = len(set(s.get("speaker", "?") for s in segments))
        update(speaker_count=n_speakers, progress=42)

        # ─── CHECKPOINT 1: after transcription+diarization+speaker_refs ──
        # Speaker refs are built now, so /continue from this checkpoint has
        # everything it needs to run translate → TTS → merge.
        save_checkpoint(job_id, work, stage="transcription_done", data={
            "video_path": video_path,
            "audio_16k": audio_16k,
            "bg_audio_path": bg_audio_path,
            "duration": duration,
            "effective_src": effective_src,
            "target_lang": target_lang,
            "keep_bg": keep_bg,
            "model": model,
            "context_hint": context_hint,
            "speaker_mode": speaker_mode,
            "speaker_count_requested": speaker_count,
            "reference_audio": reference_audio,
            "voice_style": voice_style,
            "voice_preset": voice_preset,
            "tts_speed": tts_speed,
            "speaker_refs": {k: v for k, v in speaker_refs.items()},
            "source_speaker_refs": {k: v for k, v in source_speaker_refs.items()},
            "speaker_transcripts": {k: v for k, v in speaker_transcripts.items()},
            "segments": [
                {
                    "idx": i, "start": s["start"], "end": s["end"],
                    "text": s["text"],
                    "speaker": s.get("speaker", "SPEAKER_00"),
                }
                for i, s in enumerate(segments)
            ],
        })

        if wizard_mode == "review_transcript":
            update(
                status="awaiting_transcript_review", progress=43,
                step_detail="Review transcription — edit or approve to continue",
                checkpoint_stage="transcription_done",
            )
            log.info(f"[wizard] Paused at transcript review for job {job_id}")
            return

        # 5. Translate
        update(status="translating", progress=45, step_detail=f"Translating to {target_lang}...")
        def _translate_progress(done, total, eta_sec):
            # Map translation progress into overall pipeline 45→62% range
            pct = 45 + int((done / max(total, 1)) * 17)
            eta_str = f" · ~{eta_sec // 60}m{eta_sec % 60}s left" if eta_sec > 30 else ""
            update(
                progress=min(pct, 62),
                step_detail=f"Translating batch {done}/{total}{eta_str}",
            )
        segments = await translate_segments(
            segments, effective_src, target_lang, model,
            context_hint=context_hint,
            progress_callback=_translate_progress,
        )

        # Sanity check: if a significant fraction of segments have
        # untranslated (source-language) text still in translated_text,
        # stop here instead of letting VoxCPM try to speak English with
        # Russian cross-lingual cfg (which crashes the worker). This
        # happens when Ollama times out on every request and per-line
        # fallback also fails.
        untranslated_count = 0
        for s in segments:
            tt = (s.get("translated_text") or "").strip()
            src_text = (s.get("text") or "").strip()
            if not tt or tt == src_text:
                untranslated_count += 1
        if untranslated_count == len(segments):
            raise RuntimeError(
                f"Translation completely failed — all {len(segments)} segments "
                f"still in source language. Check Ollama: run `ollama ps` and "
                f"try `ollama run {model} 'hi'` manually. If it hangs, the "
                f"model may be incompatible with your setup; try "
                f"`ollama pull qwen2.5:7b` and pick it in the UI."
            )
        if untranslated_count > len(segments) // 2:
            log.warning(
                f"[translate] {untranslated_count}/{len(segments)} segments "
                f"did not translate successfully — TTS quality may suffer"
            )

        # Unload Ollama model from VRAM before TTS. Without this, Ollama's
        # 9+ GB model sits in VRAM during TTS, leaving too little room for
        # VoxCPM (also ~4 GB). On 12 GB cards this causes VoxCPM to swap
        # to system RAM → slow inference. keep_alive=0 tells Ollama to
        # drop the model immediately after the next request; we pair it
        # with a cheap 1-token request to actually trigger the unload.
        try:
            await unload_ollama_model(model)
        except Exception as e:
            log.warning(f"Failed to unload Ollama model (non-fatal): {e}")

        transcript_preview = [
            {
                "start": s["start"], "end": s["end"],
                "text": s["text"],
                "translated": s.get("translated_text", ""),
                "speaker": s.get("speaker", ""),
            }
            for s in segments
        ]
        update(transcript=transcript_preview, progress=62)

        # ─── CHECKPOINT 2: after translation ──────────────────────────
        # Full state dump — retry_tts can load this and skip stages 1-5.
        srt_path = str(work / "subtitles.srt")
        write_srt(segments, srt_path)
        update(srt_url=f"/outputs/{job_id}/subtitles.srt")

        save_checkpoint(job_id, work, stage="translation_done", data={
            "video_path": video_path,
            "audio_16k": audio_16k,
            "bg_audio_path": bg_audio_path,
            "duration": duration,
            "effective_src": effective_src,
            "target_lang": target_lang,
            "keep_bg": keep_bg,
            "speaker_refs": {k: v for k, v in speaker_refs.items()},
            "source_speaker_refs": {k: v for k, v in source_speaker_refs.items()},
            "speaker_transcripts": {k: v for k, v in speaker_transcripts.items()},
            "reference_audio": reference_audio,
            "voice_style": voice_style,
            "voice_preset": voice_preset,
            "tts_speed": tts_speed,
            "segments": [
                {
                    "idx": i, "start": s["start"], "end": s["end"],
                    "text": s["text"],
                    "translated_text": s.get("translated_text", ""),
                    "speaker": s.get("speaker", "SPEAKER_00"),
                }
                for i, s in enumerate(segments)
            ],
        })

        if wizard_mode == "review_translation":
            update(
                status="awaiting_translation_review",
                progress=63,
                step_detail="Review translation — edit, retranslate, or approve to continue",
                checkpoint_stage="translation_done",
            )
            log.info(f"[wizard] Paused at translation review for job {job_id}")
            return

        # 6. Synthesize
        tts = get_tts_engine()
        tts_dir = str(work / "tts_segments")

        # ─── VOICE MODE ROUTING (see _run_tts_and_merge_stage) ──────────
        # VoxCPM has 3 mutually-exclusive modes; pick one based on user's
        # choice. NEVER mix style prefix with speaker refs — the model will
        # literally read the style description out loud in the cloned voice.
        has_ref = any(speaker_refs.values())
        if reference_audio and os.path.exists(reference_audio):
            first_pipeline_mode = "file_ref"   # user uploaded / file preset
        elif eff_style and eff_style.strip() and not has_ref:
            first_pipeline_mode = "voice_design"
        elif eff_style and eff_style.strip() and has_ref and cfg.tts_engine != "qwen":
            # User picked a style preset but we already extracted refs from
            # the source video. The user presumably wants a fresh designed
            # voice — drop the source refs.
            log.info("[pipeline] Style preset + source refs → dropping refs "
                     "for Voice Design")
            speaker_refs = {}
            speaker_transcripts = {}
            first_pipeline_mode = "voice_design"
        else:
            if eff_style and eff_style.strip() and has_ref and cfg.tts_engine == "qwen":
                log.info("[pipeline] Qwen TTS uses source reference audio; ignoring VoxCPM voice-design style")
            first_pipeline_mode = "source_refs"

        update(status="synthesizing", progress=65,
               step_detail=f"Generating speech (mode={first_pipeline_mode}, "
                           f"preset={voice_preset}, seed={voice_seed})...",
               voice_mode=("upload" if first_pipeline_mode == "file_ref" else
                           ("custom" if first_pipeline_mode == "voice_design"
                            else "source")))

        # Apply Voice Design prefix ONLY in voice_design mode
        if first_pipeline_mode == "voice_design" and isinstance(tts, VoxCPMSynthesizer):
            style = eff_style.strip().strip("()")
            for s in segments:
                base = s.get("translated_text") or s.get("text", "")
                if base and not base.startswith("("):
                    s["translated_text"] = f"({style}){base}"

        def synth_progress(done, total):
            pct = 65 + int((done / max(total, 1)) * 20)
            update(progress=min(pct, 85), step_detail=f"Synthesizing: {done}/{total}")

        if isinstance(tts, (VoxCPMSynthesizer, QwenTTSEngine)):
            segments = tts.synthesize_segments(
                segments, tts_dir,
                speaker_refs=speaker_refs,
                speaker_transcripts=speaker_transcripts,
                progress_callback=synth_progress,
                voice_seed=voice_seed,
                tts_speed=tts_speed,
                is_cross_lingual=(effective_src != target_lang),
                target_lang=target_lang,
            )
        else:
            segments = await tts.synthesize_segments_async(
                segments, tts_dir, target_lang,
                progress_callback=synth_progress,
            )

        synth_ok = sum(1 for s in segments if s.get("audio_path"))
        update(progress=85, step_detail=f"Synthesized {synth_ok}/{len(segments)}")

        if synth_ok == 0:
            raise RuntimeError("All TTS synthesis failed - check model/GPU")

        # ─── CHECKPOINT 3: after TTS (for per-segment regen) ──────────
        # Each segment now has an audio_path; store that so /regenerate_segment
        # can pick up where we left off without re-synthesizing everything.
        # QA score and tier are surfaced so the UI can flag problematic
        # segments with coloured badges in the review panel.
        save_checkpoint(job_id, work, stage="tts_done", data={
            "video_path": video_path,
            "audio_16k": audio_16k,
            "bg_audio_path": bg_audio_path,
            "duration": duration,
            "effective_src": effective_src,
            "target_lang": target_lang,
            "keep_bg": keep_bg,
            "speaker_refs": {k: v for k, v in speaker_refs.items()},
            "speaker_transcripts": {k: v for k, v in speaker_transcripts.items()},
            "reference_audio": reference_audio,
            "voice_style": voice_style,
            "voice_preset": voice_preset,
            "tts_speed": tts_speed,
            "sample_rate": tts.sample_rate if hasattr(tts, "sample_rate") else 48000,
            "segments": [
                {
                    "idx": i, "start": s["start"], "end": s["end"],
                    "text": s["text"],
                    "translated_text": s.get("translated_text", ""),
                    "speaker": s.get("speaker", "SPEAKER_00"),
                    "audio_path": s.get("audio_path", ""),
                    "qa_score": s.get("qa_score"),
                    "tts_tier": s.get("tts_tier"),
                }
                for i, s in enumerate(segments)
            ],
        })

        # 7. Assemble (with loudness normalization)
        update(status="assembling", progress=88, step_detail="Assembling dubbed audio...")
        dubbed_wav = str(work / "dubbed_audio.wav")
        assemble_dubbed_audio(
            segments, duration, dubbed_wav, tts.sample_rate, apply_loudnorm=True,
            fit_to_slots=isinstance(tts, QwenTTSEngine),
            tail_audio_path=audio_16k if isinstance(tts, QwenTTSEngine) else "",
        )
        save_placements(work, segments)

        # 8. Merge with video
        update(status="merging", progress=93, step_detail="Rendering final video...")
        output_mp4 = str(work / "dubbed_video.mp4")
        merge_audio_video(video_path, dubbed_wav, output_mp4, bg_audio_path)

        update(
            status="complete",
            progress=100,
            output_url=f"/outputs/{job_id}/dubbed_video.mp4",
            completed_at=time.time(),
            step_detail="Done!",
        )
        log.info(f"Pipeline complete: {output_mp4}")

    except JobCancelled:
        # Re-raise so the queue worker marks the job as 'cancelled'
        # rather than 'error'. Keep the exception on the stack — logging
        # is handled upstream.
        log.info(f"Pipeline cancelled for {job_id}")
        raise
    except Exception as e:
        update(status="error", error=str(e))
        log.exception(f"Pipeline failed: {e}")


async def _run_translate_stage(
    job: dict, work: Path, segments: list, effective_src: str,
    target_lang: str, model: str, context_hint: str,
) -> list:
    """Run translation on raw segments + return segments with translated_text."""
    def update(**kwargs):
        if job.get("cancel_requested"):
            raise JobCancelled(f"Job {job['id']} cancelled by user")
        job.update(kwargs); save_job(job)
    update(status="translating", progress=45,
           step_detail=f"Translating to {target_lang}...")
    translated = await translate_segments(
        segments, effective_src, target_lang, model,
        context_hint=context_hint,
    )
    # See comment on unload in main pipeline — free VRAM for VoxCPM
    try:
        await unload_ollama_model(model)
    except Exception as e:
        log.warning(f"Failed to unload Ollama model (non-fatal): {e}")
    return translated



async def _run_tts_and_merge_stage(
    job: dict, work: Path, state: dict,
    voice_style: str, voice_preset: str, tts_speed: str,
    ref_path_override: str = "",
    audio_output_name: str = "dubbed_audio.wav",
    tts_subdir: str = "tts_segments",
    preserve_existing_audio_paths: bool = False,
) -> dict:
    """Run TTS + assemble + merge. Returns dict with 'segments' and status.
    - preserve_existing_audio_paths: if True, segments that already have
      a valid audio_path keep their existing file (for per-segment regen).
    """
    job_id = job["id"]
    def update(**kwargs):
        if job.get("cancel_requested"):
            terminate_tts_worker()
            raise JobCancelled(f"Job {job_id} cancelled by user")
        job.update(kwargs); save_job(job)

    eff_style, voice_seed, preset_ref = resolve_voice_config(
        voice_preset, voice_style, job_id
    )
    ref_path = ref_path_override
    if preset_ref and os.path.exists(preset_ref):
        ref_path = preset_ref
        log.info(f"[stage] Using file-preset reference: {preset_ref}")

    # Force a FRESH voice_seed whenever this is NOT the first-time run:
    #   - retry_tts (audio_output_name is "dubbed_audio_retry.wav")
    #   - per-segment regen (preserve_existing_audio_paths=True)
    # Without re-seeding, identical inputs to VoxCPM produce byte-identical
    # outputs — so "click retry" would silently do nothing visible to user.
    is_rerun = (audio_output_name != "dubbed_audio.wav"
                or preserve_existing_audio_paths)
    if is_rerun:
        voice_seed = int(time.time() * 1000) % 2_147_483_647
        log.info(f"[stage] Re-run: rolled fresh voice_seed={voice_seed}")

    # ─── VOICE MODE ROUTING ──────────────────────────────────────────
    # VoxCPM has 3 mutually-exclusive modes — the user's UI choice maps
    # to ONE of them. Previously, mixing refs + style prefix was producing
    # garbage: VoxCPM would try to clone the video voice AND literally read
    # out the "(deep male voice, narrator)" style description as text.
    #
    #   Mode 1: File/uploaded reference → Controllable Cloning
    #           Clean reference_wav_path only, NO style prefix.
    #
    #   Mode 2: Style preset (e.g. "male_deep") → Voice Design
    #           "(style description)<text>" — NO reference at all.
    #
    #   Mode 3: No change (auto preset, no upload) → keep state refs
    #           Controllable/Ultimate Cloning from video refs, no prefix.
    mode = "source_refs"
    if ref_path and os.path.exists(ref_path):
        mode = "file_ref"
    elif eff_style and eff_style.strip() and cfg.tts_engine != "qwen":
        mode = "voice_design"

    update(
        status="synthesizing", progress=65,
        voice_preset=voice_preset, voice_style=voice_style,
        voice_style_effective=eff_style, voice_seed=voice_seed,
        tts_speed=tts_speed,
        voice_mode=("upload" if mode == "file_ref" else
                    ("custom" if mode == "voice_design" else "source")),
        step_detail="Generating speech...",
    )
    log.info(f"[stage] Voice mode: {mode} "
             f"(ref={bool(ref_path)}, style={bool(eff_style)})")

    # Start from state's refs, then override per mode
    speaker_refs = dict(state.get("speaker_refs", {}))
    speaker_transcripts = dict(state.get("speaker_transcripts", {}))

    if mode == "file_ref":
        log.info(f"[stage] Using file/upload ref for all speakers: {ref_path}")
        target_keys = list(speaker_refs.keys()) or ["SPEAKER_00"]
        for sp in target_keys:
            speaker_refs[sp] = ref_path
            speaker_transcripts[sp] = ""  # Controllable Cloning only
    elif mode == "voice_design":
        # CRITICAL: Voice Design needs NO reference. Without this clear,
        # VoxCPM sees ref + style prefix and produces broken output.
        log.info("[stage] Clearing speaker refs for Voice Design mode")
        speaker_refs = {}
        speaker_transcripts = {}
    else:
        # source_refs mode: use refs extracted from the source video.
        # CRITICAL: speaker_refs in the checkpoint may have been overwritten
        # by an earlier preset/upload (if the user previously dubbed with
        # zhirik.wav, speaker_refs contains zhirik paths). The real source
        # refs were stashed separately as source_speaker_refs — prefer those
        # when available so "retry without changing anything" truly falls
        # back to the original video's voice, not the last-used preset.
        source_refs_stash = state.get("source_speaker_refs") or {}
        if source_refs_stash and is_rerun:
            log.info(f"[stage] Retry: restoring ORIGINAL source refs "
                     f"(not previous preset): {list(source_refs_stash.keys())}")
            speaker_refs = dict(source_refs_stash)
            # Clear transcripts — cross-lingual/controllable cloning only
            for sp in speaker_refs:
                speaker_transcripts[sp] = ""
        else:
            log.info(f"[stage] Using original source speaker refs: "
                     f"{list(speaker_refs.keys())}")

    segments = [dict(s) for s in state["segments"]]
    tts = get_tts_engine()

    # Voice Design style prefix — ONLY when mode is voice_design.
    # If refs are used, the style description would literally be spoken.
    if mode == "voice_design" and isinstance(tts, VoxCPMSynthesizer):
        style = eff_style.strip().strip("()")
        for s in segments:
            base = s.get("translated_text") or s.get("text", "")
            if base and not base.startswith("("):
                s["translated_text"] = f"({style}){base}"

    # Preserve-mode: skip TTS for segments that already have valid audio
    if preserve_existing_audio_paths:
        todo, keep = [], []
        for s in segments:
            ap = s.get("audio_path", "")
            if ap and os.path.exists(ap):
                keep.append(s)
            else:
                todo.append(s)
        log.info(f"[stage] Preserving {len(keep)} existing segments, "
                 f"synthesizing {len(todo)} new")
        synth_input = todo
    else:
        synth_input = segments

    tts_dir = str(work / tts_subdir)
    total = len(synth_input)
    def synth_progress(done, total_inner):
        pct = 65 + int((done / max(total_inner, 1)) * 20)
        update(progress=min(pct, 85),
               step_detail=f"Synthesizing: {done}/{total_inner}")

    if total > 0:
        if isinstance(tts, (VoxCPMSynthesizer, QwenTTSEngine)):
            # Determine cross-lingual from state (may be missing from older
            # checkpoints — in that case assume cross-lingual as a safer default
            # since that's the common dubbing use-case)
            src_lang = state.get("effective_src") or state.get("source_lang", "en")
            tgt_lang = state.get("target_lang", "ru")
            synth_input = tts.synthesize_segments(
                synth_input, tts_dir,
                speaker_refs=speaker_refs,
                speaker_transcripts=speaker_transcripts,
                progress_callback=synth_progress,
                voice_seed=voice_seed,
                tts_speed=tts_speed,
                is_cross_lingual=(src_lang != tgt_lang),
                target_lang=tgt_lang,
            )
        else:
            synth_input = await tts.synthesize_segments_async(
                synth_input, tts_dir, state.get("target_lang", "ru"),
                progress_callback=synth_progress,
            )

    # Re-merge synth_input back into segments list if preserve-mode
    if preserve_existing_audio_paths:
        by_idx = {s.get("idx"): s for s in segments}
        for s in synth_input:
            if s.get("idx") in by_idx:
                by_idx[s["idx"]].update(s)
        segments = list(by_idx.values())

    synth_ok = sum(1 for s in segments if s.get("audio_path"))
    if synth_ok == 0:
        raise RuntimeError("All TTS synthesis failed - check model/GPU")
    update(progress=85, step_detail=f"Synthesized {synth_ok}/{len(segments)}")

    update(status="assembling", progress=88, step_detail="Assembling dubbed audio...")
    dubbed_wav = str(work / audio_output_name)
    assemble_dubbed_audio(
        segments, state["duration"], dubbed_wav, tts.sample_rate,
        apply_loudnorm=True, fit_to_slots=isinstance(tts, QwenTTSEngine),
        tail_audio_path=state.get("audio_16k", "") if isinstance(tts, QwenTTSEngine) else "",
    )
    save_placements(work, segments)

    update(status="merging", progress=93, step_detail="Rendering final video...")
    output_mp4 = str(work / "dubbed_video.mp4")
    merge_audio_video(
        state["video_path"], dubbed_wav, output_mp4,
        state.get("bg_audio_path", "") if state.get("keep_bg") else "",
    )

    # Update the tts_done checkpoint so next regen starts from current audio.
    # Existing qa_score/tts_tier on regenerated segments is preserved from the
    # worker (s.get("qa_score") is set by synthesizer); for non-regenerated
    # segments, read from the previous checkpoint to keep QA badges intact.
    prev = load_checkpoint(job_id, stage="tts_done") or {}
    prev_by_idx = {seg["idx"]: seg for seg in prev.get("segments", [])}

    def _meta(s, i):
        # Prefer fresh worker values on regenerated segments; else pull from prev
        pidx = s.get("idx", i)
        fallback = prev_by_idx.get(pidx, {})
        qa = s.get("qa_score")
        if qa is None: qa = fallback.get("qa_score")
        tier = s.get("tts_tier")
        if tier is None: tier = fallback.get("tts_tier")
        return qa, tier

    save_checkpoint(job_id, work, stage="tts_done", data={
        **state,
        "segments": [
            (lambda qa_tier: {
                "idx": s.get("idx", i),
                "start": s["start"], "end": s["end"],
                "text": s["text"],
                "translated_text": s.get("translated_text", ""),
                "speaker": s.get("speaker", "SPEAKER_00"),
                "audio_path": s.get("audio_path", ""),
                "qa_score": qa_tier[0],
                "tts_tier": qa_tier[1],
            })(_meta(s, i))
            for i, s in enumerate(segments)
        ],
    })

    update(
        status="complete", progress=100,
        step_detail="Done!",
        output_url=f"/outputs/{job_id}/dubbed_video.mp4?v={int(time.time())}",
        completed_at=time.time(),
    )
    log.info(f"[stage] Pipeline complete: {output_mp4}")
    return {"segments": segments, "output_url": f"/outputs/{job_id}/dubbed_video.mp4"}



async def retry_tts_pipeline(job_id: str, voice_style: str, voice_preset: str,
                              tts_speed: str, ref_path: str):
    """Re-runs ONLY TTS + assemble + merge using the previously-saved
    translation/transcription. Much faster than re-running the full pipeline."""
    job = jobs.get(job_id)
    if not job:
        return
    work = OUTPUT_DIR / job_id
    state = load_checkpoint(job_id, "translation_done") or \
            load_checkpoint(job_id, "tts_done")
    if not state:
        job["status"] = "error"
        job["error"] = "No saved state to retry - run full pipeline once first"
        save_job(job)
        return
    try:
        await _run_tts_and_merge_stage(
            job, work, state,
            voice_style=voice_style, voice_preset=voice_preset, tts_speed=tts_speed,
            ref_path_override=ref_path,
            audio_output_name="dubbed_audio_retry.wav",
            tts_subdir="tts_segments_retry",
        )
    except Exception as e:
        log.error(f"[retry] Failed: {e}", exc_info=True)
        job.update(status="error", error=str(e)); save_job(job)



async def _continue_from_checkpoint(
    job_id: str, cp: dict,
    voice_style: str, voice_preset: str, tts_speed: str, ref_path: str,
):
    """Dispatch to the right stage(s) depending on which checkpoint we have."""
    job = jobs.get(job_id)
    if not job:
        return
    work = OUTPUT_DIR / job_id
    def update(**kwargs):
        if job.get("cancel_requested"):
            terminate_tts_worker()
            raise JobCancelled(f"Job {job_id} cancelled by user")
        job.update(kwargs); save_job(job)

    stage = cp.get("stage", "")
    log.info(f"[continue] Resuming job {job_id} from stage '{stage}'")
    try:
        if stage == "transcription_done":
            # Need to translate first, then TTS
            update(status="translating", progress=45,
                   step_detail="Translating approved transcript...")
            effective_src = cp.get("effective_src", "en")
            target_lang = cp.get("target_lang", "ru")
            model = cp.get("model", "gemma4:e4b")
            context_hint = cp.get("context_hint", "")
            segments = await translate_segments(
                cp["segments"], effective_src, target_lang, model,
                context_hint=context_hint,
            )
            # Save translation_done checkpoint
            save_checkpoint(job_id, work, stage="translation_done", data={
                **cp,
                "segments": [
                    {
                        "idx": i, "start": s["start"], "end": s["end"],
                        "text": s["text"],
                        "translated_text": s.get("translated_text", ""),
                        "speaker": s.get("speaker", "SPEAKER_00"),
                    }
                    for i, s in enumerate(segments)
                ],
            })
            cp = load_checkpoint(job_id, "translation_done")

        # Now run TTS+merge from translation_done checkpoint
        await _run_tts_and_merge_stage(
            job, work, cp,
            voice_style=voice_style, voice_preset=voice_preset,
            tts_speed=tts_speed, ref_path_override=ref_path,
        )
    except Exception as e:
        log.error(f"[continue] Failed: {e}", exc_info=True)
        update(status="error", error=str(e))



async def _retranslate_stage(job_id: str, cp: dict, model: str,
                               context_hint: str, target_lang: str):
    job = jobs.get(job_id)
    if not job:
        return
    work = OUTPUT_DIR / job_id
    def update(**kwargs):
        if job.get("cancel_requested"):
            raise JobCancelled(f"Job {job_id} cancelled by user")
        job.update(kwargs); save_job(job)
    try:
        update(status="translating", progress=45, model=model, error=None,
               context_hint=context_hint, target_lang=target_lang,
               step_detail=f"Retranslating with {model}...")
        effective_src = cp.get("effective_src", "en")
        segments = await translate_segments(
            cp["segments"], effective_src, target_lang, model,
            context_hint=context_hint,
        )
        save_checkpoint(job_id, work, stage="translation_done", data={
            **cp,
            "target_lang": target_lang,
            "segments": [
                {
                    "idx": i, "start": s["start"], "end": s["end"],
                    "text": s["text"],
                    "translated_text": s.get("translated_text", ""),
                    "speaker": s.get("speaker", "SPEAKER_00"),
                }
                for i, s in enumerate(segments)
            ],
        })
        update(
            status="awaiting_translation_review", progress=63,
            error=None,
            step_detail="Retranslated — review and continue",
            checkpoint_stage="translation_done",
        )
    except Exception as e:
        log.error(f"[retranslate] Failed: {e}", exc_info=True)
        update(status="error", error=str(e))



async def _regen_single_segment(
    job_id: str, cp: dict, seg_idx: int,
    voice_style: str, voice_preset: str, tts_speed: str, ref_path: str,
):
    job = jobs.get(job_id)
    if not job:
        return
    work = OUTPUT_DIR / job_id
    def update(**kwargs):
        if job.get("cancel_requested"):
            terminate_tts_worker()
            raise JobCancelled(f"Job {job_id} cancelled by user")
        job.update(kwargs); save_job(job)
    try:
        update(status="synthesizing", progress=65,
               step_detail=f"Regenerating segment {seg_idx+1}...")
        # preserve_existing_audio_paths=True — only the cleared one will re-synth
        await _run_tts_and_merge_stage(
            job, work, cp,
            voice_style=voice_style, voice_preset=voice_preset,
            tts_speed=tts_speed, ref_path_override=ref_path,
            preserve_existing_audio_paths=True,
        )
    except Exception as e:
        log.error(f"[regen_seg] Failed: {e}", exc_info=True)
        update(status="error", error=str(e))

