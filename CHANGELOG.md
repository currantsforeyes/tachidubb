# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
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
