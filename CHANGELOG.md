# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Original Audio lane** in the dialogue editor, above the Original Text row:
  a waveform of the source dialogue (`/timeline` now returns `source_peaks`
  from the job's `audio_16k` track). The **playhead is now draggable** — drag on
  the ruler, source-audio lane or any speaker lane to scrub the video — and
  cuts **snap to speaker-change points** (within 0.35s) so slicing lands on the
  turn instead of mid-word.
- **Folder watcher** (`app/watcher.py` + `/api/watch/*`): with
  `TACHIDUBB_WATCH_ENABLED=1`, videos dropped into `watch/` are auto-dubbed and
  moved to `watch/processed/`. Skips half-copied files (mtime grace + `.part`
  style suffixes), leaves files in place when no translation model is available,
  and runs everything through the normal serial queue. `GET /api/watch/status`,
  `POST /api/watch/scan`, `POST /api/watch/enable`; settings in `UserConfig`
  (`watch_enabled`, `watch_dir`, `watch_target_lang`, `watch_model`,
  `watch_poll_seconds`).
- `app/submit.py`: `create_file_job` + `resolve_model`, now shared by
  `/api/dub/batch`'s file branch and the watcher so both produce the same job
  shape (and the batch route's duplicated model-fallback list is gone).
- **Narrator mode everywhere.** The batch, quick-test, showcase and re-dub
  routes now accept `narration_mode` (previously `/api/dub` only), and it's
  exposed through the CLI (`--narrator` on `dub` / `compare` / `showcase` /
  `redub`) and the MCP tools.
- CLI example for `--narrator` in the README.
- CI now rebuilds the frontend and fails if the committed
  `static/dist/app.js` is stale (guards against source/bundle drift).
- **Dialogue editor redrawn as a DAW-style workspace** (matching the design
  mock): video preview with a custom transport bar (start / prev / stop /
  play / next / end, Dubbed↔Original toggle), an HH:MM:SS:FF timecode readout,
  a timecode ruler, aligned lanes for **Original Text**, **Translated Text**
  (draggable clips), and one **waveform lane per speaker** with solo/mute,
  plus zoom, playback speed and volume controls and select/razor tools.
- **Per-speaker audio stems** (`/api/dub/{id}/stems`, `…/stem/{speaker}/audio`):
  each speaker's clips laid onto a full-length track, built from the placement
  already recorded in `tts_placements.json` (merged in, since a normal run
  writes the `tts_done` checkpoint *before* assembly) — no re-synthesis, so
  existing jobs work as-is. Empty speaker ids from older single-speaker jobs
  are normalised to `SPEAKER_00`. The editor's **S / M** buttons now drive a
  real stem mixer (video muted while it's on), so solo and mute are audible
  instead of decorative. Stems are rendered on first request and cached next
  to the job.

### Changed
- `pipeline.assembler.assemble_dubbed_audio` gained `use_recorded=` (place
  clips at the timeline_start/placed_start the pipeline already saved instead
  of re-deriving them), and `assemble_speaker_stems()` builds one WAV per
  speaker on top of it. Stems are deliberately not loudness-normalised, so
  their levels stay relative to each other.
- `GET /api/dub/{id}/timeline` now also returns per-segment `original_text`
  (for the Original Text lane), `dubbed_video_url`, and `peaks` — a downsampled
  waveform envelope of `dubbed_audio.wav` (`pipeline.media.waveform_peaks`).
  The editor page is now full-bleed instead of a centred card.

### Docs
- `docs/PACKAGING.md`: what we ship and why (source + installer, tag-triggered
  GitHub Releases, checksum verification), plus a requirements catalogue and
  definition-of-done for a future container image. Linked from the README.

### Fixed
- **The dialogue editor could sit on "Loading clips…" forever.** A stalled
  timeline request now aborts after 10s and shows the reason with a **Retry**
  button instead of spinning indefinitely (verified live: forced failure,
  forced 10s stall, and recovery via Retry).
- **Subtitle preview rendered the wrong cue.** `/api/dub/{id}/subs_preview`
  seeks with `-ss` before `-i` for speed, which rebases timestamps to ~0, so
  the `subtitles` filter drew the cue at t=0 instead of the cue at the requested
  timestamp — previewing a later line came out blank. Added `-copyts` to keep
  the original timeline. (Roadmap's "burn-in is SRT-sidecar only" note was also
  stale: burn-in already ships.)
- **Showcase reels came out N× too long.** `assemble_showcase_sync` matched
  segments to a slice with `src_start < g_e + 0.001` / `src_end > g_s - 0.001`.
  Since slice boundaries are snapped exactly onto segment edges, that also
  claimed the segment merely *touching* each boundary, so every slice expanded
  to the neighbours' full extent and each language replayed the whole timeline
  (a 2-language, 2-second reel measured 4 s). The tolerance now sits inside the
  bounds (`< g_e - 0.001`, `> g_s + 0.001`), keeping the documented
  long-merged-segment coverage without double-counting neighbours. Existing
  reels can be regenerated with `tachidubb showcase-rebuild <batch_id>`.

### Changed
- Subtitle SRT materialisation is now one shared helper,
  `app.checkpoints.ensure_translated_srt` (+ `latest_segments`), used by the
  preview, burn-in and platform-export routes — previously three near-duplicate
  copies that disagreed on which checkpoint was authoritative. All three now
  take the most advanced checkpoint (tts → translation → transcription), so a
  job that only got as far as transcription still gets an SRT.
  `assemble_showcase_sync` now uses `latest_segments` too (it only needs
  segment end times, which no stage rewrites) instead of its own checkpoint
  loop; its two function-scope `subprocess` imports moved to module scope.
- `burn_subs` validates `style` like `subs_preview` does (and export does when
  the preset burns subs); all three handle `TimeoutExpired` / ffmpeg-missing
  with a clear 500 instead of an unhandled error.
- Platform export without a transcript now logs and exports the video without
  subtitles rather than failing.

### Tests
- `tests/test_client_narration.py` covers the client/CLI narration plumbing.
- `test_routes` now asserts the served bundle actually contains the
  Pronunciation tab and Narrator-mode toggle.
- `tests/test_media_routes.py`: 15 HTTP tests for `/subs_preview` and
  `/burn_subs` (error paths are ffmpeg-free; happy paths run real ffmpeg and
  skip when absent). Includes a behavioral regression test for the preview
  timeline fix — it fails against the old `-ss`-only command.
- `tests/test_export_preset.py`: 10 HTTP tests for `/api/dub/{id}/export`.
- `tests/test_checkpoints.py`: 6 tests for `latest_segments` /
  `ensure_translated_srt`.
- `tests/test_showcase_assembly.py`: 3 tests for the reel stitcher — two
  ffmpeg-free early-exit guards and a full 2-language stitch that asserts the
  reel length (guarding the N× overlap bug). A shared `ffmpeg_subs` fixture (in
  `tests/conftest.py`) skips subtitle-rendering tests when ffmpeg+libass is
  unavailable, and `ffmpeg_drawtext` covers the badge overlay.
- `tests/test_watcher.py` (11): candidate filtering, the mtime grace period,
  enqueue-and-move, model-error retry, in-session de-dupe, name collisions and
  start/stop. `tests/test_submit.py` (6) covers `create_file_job`/`resolve_model`
  and `tests/test_batch_route.py` (2) pins the batch job shape after the
  refactor.
- `tests/test_waveform_peaks.py` (4) and `tests/test_timeline_route.py` (2)
  cover the editor's waveform envelope and the new `/timeline` fields.
- `tests/test_stems.py` (4) checks stems place each speaker's audio in its own
  window and honour the recorded placement; `tests/test_stem_route.py` (7)
  covers the on-demand stem endpoints, including merging placement from
  `tts_placements.json` when the checkpoint has none, and empty-speaker
  normalisation. Verified end-to-end against a real job on disk.

## [0.3.0] - 2026-09-23

### Added
- GitHub **release workflow** (`.github/workflows/release.yml`): on a `v*` tag it
  runs the test suite, then publishes a GitHub Release with a source archive and
  `SHA256SUMS.txt` plus generated notes.
- **Narrator mode** (`narration_mode=true` on `/api/dub`): assigns every segment
  to a single voice and skips diarization, for localized narration
  (Voicer-style) rather than per-speaker dubbing. Reuses an uploaded reference
  or voice preset as the narrator; with no reference it falls back to one
  reference built from the source. Toggle in the Home form's Advanced section.
- **Pronunciation overrides** (`presets/pronunciation.json` + `/api/pronunciation`):
  rewrite how a word is *spoken* (e.g. `nginx` → `engine x`) without changing
  the subtitles. Applied via a new `segment["tts_text"]` field that every TTS
  engine prefers; `translated_text` is untouched. Editable in
  **System → Pronunciation**.
- `translategemma:27b` added to the translation model catalog.
- Optional **staged translation** (`TACHIDUBB_TRANSLATION_MODE=staged`, or
  `translation_mode` in config): clean raw subtitles, translate, then adapt for
  spoken narration as three separate model passes. Best-effort — any step
  failing falls back to the existing single-pass prompt for that batch.
- **OpenAI-compatible translation backend** (`TACHIDUBB_TRANSLATION_BACKEND=openai`
  with `TRANSLATION_BASE_URL` / `TRANSLATION_API_KEY`): use LM Studio, llama.cpp's
  server, vLLM or the OpenAI API instead of Ollama. Works with any server
  exposing `/chat/completions`. Ollama stays the default.
- VoxCPM's persistent TTS worker is recycled after
  `TACHIDUBB_TTS_RECYCLE_SEGMENTS` (default 400, `0` disables) segments to
  bound memory growth on long runs.
- MuseTalk now runs **OpenMMLab-free**: the worker patches
  `musetalk/utils/preprocessing.py` (backing up the original) to use MuseTalk's
  vendored face detector instead of DWPose, and the installer uses
  **torch 2.8.0+cu128** instead of the pinned 2.0.1+cu118. mmcv/mmdet/mmpose
  are no longer installed. This makes lip-sync practical on RTX 40/50-series
  (Blackwell) GPUs — a 3 s test clip went from 25+ min to ~80 s end-to-end.

### Fixed
- MuseTalk under torch >=2.6: set `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` for the
  child process, since MuseTalk loads legacy `.tar` checkpoints that the new
  `weights_only=True` default rejects.
- `install-musetalk`: build `chumpy` (a transitive dependency) with
  `--no-build-isolation`. Its `setup.py` imports `pip`, which isn't present in
  pip's isolated build environment, so the dependency install aborted.
- Lip-sync worker: quote Windows paths in MuseTalk's generated YAML config
  (single quotes + forward slashes — double-quoted `\M` is an invalid YAML
  escape) and force UTF-8 I/O for the child process (MuseTalk prints CJK text
  that aborted inference under the default cp1252 codec).
- MuseTalk weights: verify the required files and fetch any that are missing
  (`tools/ensure_musetalk_weights.py`); `tools/diagnose_musetalk.py` and
  `/api/lip_sync/status` now report incomplete weights. This works around
  MuseTalk's `download_weights` using `--include "a" "b"`, which only downloads
  the second+ patterns and silently skipped `sd-vae/config.json`,
  `whisper/config.json` and `face-parse-bisent/79999_iter.pth`.

## [0.2.0] - 2026-09-23

### Added
- Stitched multilingual showcase reel rendering with per-language `· LL ·` badges
- Resume-from-checkpoint for jobs that errored mid-pipeline
- `tachidubb_rebuild_showcase` (MCP) / `showcase-rebuild` (CLI) — re-stitch without re-dubbing
- `tachidubb_list_models` — query installed Ollama translation models
- `examples/` directory with ready-to-run dub, showcase, and agent scripts
- `tests/` pytest suite covering the pure pipeline helpers (segment cleanup,
  speech grouping, speaker assignment/smoothing, TTS QA scoring, translation
  parsing, SRT rendering, showcase slicing) and the SQLite job store
- `pipeline/showcase.py` — timeline slicing extracted from `server.py` so it is
  unit-testable without the FastAPI/GPU stack
- `app/checkpoints.py` — per-stage checkpoint/resume logic extracted from
  `server.py` for the same reason
- `pipeline/media.py` — SRT writing, video trimming, duration probing and
  drawtext font lookup extracted from `server.py`
- `app/voices.py` — built-in voice styles plus user file-preset scanning,
  resolution and name sanitization extracted from `server.py`
- `app/storage.py` — disk-usage accounting, cleanup-candidate selection and
  stats aggregation extracted from `server.py`
- `pipeline/subtitles.py` — subtitle style map, ffmpeg `subtitles` filter
  construction and preview-timestamp picking extracted from `server.py`
- `app/state.py` — shared in-memory job store + restart-recovery logic
  extracted from `server.py`
- `app/routers/storage.py` — first route group split out of `server.py`
  (storage stats / starring / cleanup)
- `app/routers/system.py` — health, model management, config, preferences and
  glossary routes split out of `server.py`
- `app/routers/voices.py` — voice-preset list / audio-stream / create / update
  / delete routes split out of `server.py`
- `app/routers/media.py` — waveform, subtitle preview and subtitle burn-in
  routes split out of `server.py`
- `app/routers/lipsync.py` + `app/lipsync.py` — lip-sync status/run routes and
  the MuseTalk orchestration (`run_lipsync`) split out of `server.py`
- `app/queue.py` — the serial GPU job queue, cron-style scheduler, Windows
  sleep prevention and `JobCancelled` extracted from `server.py`. The queue
  worker receives the pipeline runner + showcase hook via `start()` (avoids an
  import cycle); the server lifespan and cancel route were rewired to it
- `app/pipeline.py` — the `run_pipeline` orchestrator extracted from
  `server.py`; `terminate_tts_worker` moved to `app/tts.py` and
  `save_placements`/`load_placements` moved to `pipeline/showcase.py` so the
  orchestrator has no server-local dependencies
- `app/routers/jobs.py` — job list/get/cancel/delete/download, per-speaker
  reference inspection and transcript-export routes split out of `server.py`
- `app/routers/dub.py` — the submit routes (`/api/dub`, `/api/dub/batch`,
  `/api/quick_test`) and the per-job editing routes (`checkpoint`, `continue`,
  `retry_tts`, `retranslate`, `timeline`, `regenerate_segment`, `edit_*`)
- stage helpers (`_run_translate_stage`, `_run_tts_and_merge_stage`,
  `retry_tts_pipeline`, `_continue_from_checkpoint`, `_retranslate_stage`,
  `_regen_single_segment`) appended to `app/pipeline.py`
- `app/languages.py` — quick-test/batch language sets shared by the dub and
  showcase routes
- `app/showcase.py` + `app/routers/showcase.py` — the showcase batch state and
  assembly helpers, and the showcase/redub/export routes, split out of
  `server.py`
- `app/main.py` — the FastAPI app, lifespan, logging filters and router
  registration moved out of `server.py`; `server.py` is now a 20-line
  `uvicorn` entry point (still the launcher used by `start.bat` /
  `start-qwen.bat`)
- `app/tts.py` — TTS engine factory + GPU-cleanup helper extracted from
  `server.py` (so routers can obtain an engine without importing the app)
- `app/glossary.py` — user-glossary example + validation extracted from
  `server.py`
- MuseTalk lip-sync backend replacing Wav2Lip as the default (MIT, 256×256
  mouth region, ~4 GB VRAM fp16): `pipeline/lipsync.py`,
  `pipeline/musetalk_worker.py`, and `install-musetalk.bat` / `.sh` which set
  up an isolated `musetalk-runtime` (OpenMMLab deps stay out of the main venv)
- `tools/diagnose_musetalk.py` — one-command MuseTalk readiness check
  (checkout, weights, isolated-runtime deps + CUDA, ffmpeg); the installer runs
  it automatically. `/api/lip_sync/status` also returns a structured `probe`
  when MuseTalk isn't ready, and the worker preflights its runtime deps and
  discovers ffmpeg itself
- `install-musetalk.bat` / `.sh` now prefer `uv venv --seed --python 3.10`, so
  Python 3.10 is fetched into uv's local cache with **no system install**
  (falls back to `py -3.10` / `python3.10` when uv isn't present)
- `install-qwen.bat` uses the same uv-based provisioning for Python 3.12, so
  neither optional backend (MuseTalk or Qwen) requires a system Python
- The UI now ships as a local esbuild bundle (`frontend/src/app.jsx` →
  `static/dist/app.js`): React, ReactDOM and three.js are bundled and served
  from `/static`, so the page loads with **no CDN scripts and no in-browser
  Babel** (previously it fetched the React *development* build + Babel +
  three.js from unpkg on every load)
- UI fonts (Geist, Titillium Web, JetBrains Mono) are now **self-hosted** under
  `static/fonts/` (one `static/fonts.css`), so the page makes no external
  requests at all
- CI `test` job, plus explicit `ruff` + `pytest` configuration in `pyproject.toml`

### Fixed
- **CI never ran** — `.github/workflows/lint.yml` targeted the nonexistent
  `main` branch while the default branch is `master`
- `VoxCPMSynthesizer.unload()` referenced an undefined `subprocess` in its
  worker-kill fallback, so a hung worker was never force-killed (the resulting
  `NameError` was swallowed by the outer handler)
- Removed a duplicate `"reverse de la riva"` glossary entry whose second mapping
  was silently ignored
- **Voice consistency in cross-lingual cloning** — QA retries were mutating the seed
  per retry attempt in cloning mode, producing audibly different timbres for
  segments that failed-then-retried. Cloning mode now sets `MAX_QA_RETRIES = 0`
  and falls through to the next tier with the original `voice_seed` intact.
- CUDA non-determinism — `torch.backends.cudnn.deterministic=True` plus
  `CUBLAS_WORKSPACE_CONFIG=:4096:8` for reproducible diffusion sampling

## [0.1.0] — initial public release

### Added
- One-click installers for Windows (`install.bat`) and Linux/macOS (`install.sh`)
- FastAPI server + React UI
- yt-dlp → faster-whisper → pyannote → Ollama → VoxCPM2 → ffmpeg pipeline
- 28 target languages
- Multi-speaker diarization (pyannote, optional)
- Background music preservation (audio-separator, optional)
- Persistent job history
- MCP server (`tools/tachidubb_mcp.py`) — Claude Code / agent integration
- CLI (`tools/tachidubb_cli.py`) — scriptable from any shell
- Claude Code skill (`.claude/skills/tachidubb/SKILL.md`)
- Whisper-roundtrip QA on synthesized segments with seed-mutation retries
- Tiered TTS fallback: VoxCPM2 cloning → VoxCPM2 reference → voice design → edge-tts
