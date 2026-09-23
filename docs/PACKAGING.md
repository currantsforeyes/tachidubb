# Packaging & distribution

How TachiDUBB Studio is shipped today, how a release is cut, and what it would
take to add a container image later. Nothing in this document is required to
*run* the app — see the [README quickstart](../README.md#-30-second-quickstart)
for that.

---

## TL;DR — what we ship

| Channel | Status | What you get | Models included? |
|---|---|---|---|
| `git clone` + installer (`install.bat` / `./install.sh`) | **Supported** | Source + project-local `venv`; models download on first run | No |
| GitHub Release source archive | **Supported** | Tagged source `.zip` + `SHA256SUMS.txt` | No |
| Prebuilt desktop/OS installer (`.exe`, `.dmg`, `.deb`) | Not provided | — | — |
| Container image (Docker/Podman) | Not provided | — | — |
| Python package on PyPI | Not provided | — | — |

The two supported channels are equivalent: they deliver *source*, and the
installer provisions the runtimes and downloads models on the machine that
will run the app. That is deliberate — see [Why no prebuilt binaries](#why-no-prebuilt-binaries).

---

## 1. GitHub Releases (the tag-triggered workflow)

`.github/workflows/release.yml` runs whenever a `v*` tag is pushed.

**What it does**

1. `test` job — installs `requirements-dev.txt`, runs `ruff check .` and `pytest -q`.
   The release is blocked if either fails.
2. `release` job (only for tag refs) — builds a source archive and publishes a
   GitHub Release with generated notes.

**Artifacts**

| Asset | Built from | Contents |
|---|---|---|
| `tachidubb-<tag>.zip` | `git archive --format=zip HEAD` | Everything git tracks at the tag: Python source (`app/`, `pipeline/`, `server.py`), installers, `requirements*.txt`, `presets/`, and the **prebuilt frontend** (`static/dist/app.js`, fonts). |
| `SHA256SUMS.txt` | `sha256sum` of the archive | Integrity check for the download. |

Because the archive is produced with `git archive`, it contains exactly the
tracked tree — no `venv/`, `node_modules/`, `musetalk-runtime/`, `MuseTalk/`,
uploads, outputs, databases, or downloaded weights (all `.gitignore`d). It is
*source + bundled UI*, not a runnable bundle: the user still runs the installer.

Cutting a release:

```bash
# from a clean master with the work committed
git tag -a v0.4.0 -m "TachiDUBB Studio v0.4.0"
git push origin v0.4.0
# watch it:  gh run list --workflow=release
```

> The workflow also has `workflow_dispatch`, but the publish job is gated on
> `startsWith(github.ref, 'refs/tags/')`, so a manual run only exercises the
> test job. Use it to dry-run the suite without publishing.

**Not done by the workflow** (on purpose): no code signing, no notarization,
no checksums of anything except the archive, and no attachment of models. Add
signing only alongside a real binary, otherwise it signs nothing meaningful.

---

## Why no prebuilt binaries

1. **Models dominate the download.** A full setup is ~18 GB, and the weights
   are not ours to redistribute: pyannote diarization weights are gated behind
   Hugging Face terms, and Whisper/VoxCPM/Demucs/Ollama checkpoints each have
   their own licences. Shipping them would mean shipping other people's
   licensed artifacts.
2. **The GPU stack is host-specific.** `torch` must match the driver's CUDA
   capability. This fork already carries two paths (`requirements.txt` for
   CUDA ≤ 12.1 wheels, `requirements-cuda128.txt` for RTX 50-series / CUDA
   12.8). Baking one choice into a binary breaks the other.
3. **Three Python interpreters.** The main app targets **3.11**; the optional
   MuseTalk lip-sync runtime wants **3.10**; the optional Qwen backend wants
   **3.12**. The installers provision each with `uv` *without* a system-wide
   install. A single bundled binary would have to carry all three.
4. **The UI is already bundled.** `static/dist/app.js` is committed and built
   with esbuild, so the source archive runs the UI with no `npm` step. That was
   the main reason a "build" step used to exist; it no longer does.

---

## What a container image would require

A future Docker/Podman image is tracked on the [roadmap](../README.md#-roadmap).
This section is the requirements catalogue so a container PR can be reviewed
against something concrete. **No Dockerfile is committed** — an image must be
built and run on real hardware before we ship one (see
[Definition of done](#definition-of-done-for-a-container-pr)).

### Base image & interpreters

| Option | Notes |
|---|---|
| `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04` | Ships CUDA/cuDNN runtime; Python is **3.12**. Good for the Qwen/MuseTalk runtimes, but the main app targets 3.11. |
| `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04` + `uv python install 3.11` | Closest to the supported baseline. `uv` already provisions interpreters for MuseTalk/Qwen, so reuse it for the app too. |
| `python:3.11-slim` | **CPU-only.** No CUDA; every job falls back to slow CPU paths. Only sensible as a dev/demo image. |

Do **not** rely on the distro `python3` alone: pin 3.11 for the app and let
`uv` provide 3.10/3.12 for the optional backends if you bake them in.

### System packages

- `ffmpeg` (and `ffprobe`) — required for trimming, muxing, subtitle burn-in.
  The Windows installer bundles a static build into `bin/`; in a container,
  install from the distro, and make sure it is on `PATH` rather than in `bin/`.
- `git`, `curl`, `ca-certificates` — weight/dependency downloads.
- Optional: `espeak-ng` only if a fallback TTS path needs it (not required for
  the default VoxCPM2 clone path).

### Torch / CUDA ordering

Install Torch first, from the matching index, then the rest — exactly as the
installer does:

```
pip install -r requirements-cuda128.txt --index-url https://download.pytorch.org/whl/cu128   # torch/torchvision/torchaudio
pip install -r requirements.txt                                                               # everything else
```

Installing `requirements.txt` first pulls a PyPI torch, which then has to be
replaced; keep the order.

### Ollama

Ollama is a separate service (default `http://localhost:11434`) and is **not**
part of this image. Two options:

- **Sidecar container** — run `ollama/ollama` alongside, and set
  `OLLAMA_URL=http://ollama:11434`. Model pulls populate the Ollama volume.
- **Host Ollama** — point `OLLAMA_URL` at the host (e.g.
  `http://host.docker.internal:11434` on Docker Desktop). Simplest when the
  user already runs Ollama natively.

Either way the translation model must be pulled once (`ollama pull ...`).

### Paths: what must be writable

All paths are relative to the repo root (`app/config.py` → `BASE`). The app
**creates** missing directories at import, so bind-mount them, don't mount
read-only:

| Path | Contents | Persist? |
|---|---|---|
| `uploads/` | downloaded/uploaded source videos | optional |
| `outputs/` | finished dubs and showcase reels | **yes** |
| `jobs_db/` | per-job JSON | yes |
| `tachidubb.db` | SQLite job store | yes |
| `config-user.json`, `user_prefs.json` | UI settings | yes |
| `presets/voices/` | uploaded reference voices (may be private) | yes |
| `presets/pronunciation.json`, `presets/user_glossary.json` | user overrides | yes |
| HF cache (`HF_HOME` / `~/.cache/huggingface`) | Whisper, VoxCPM, pyannote weights | **yes (huge)** |
| Torch hub cache (`~/.cache/torch`) | some weights | yes (huge) |
| MuseTalk checkout + `musetalk-runtime/` | optional lip-sync backend | yes (large) |

A single named volume over the repo directory is the pragmatic approach for a
self-contained image; splitting `outputs/` from the caches is nicer if you care
about backup size.

### Runtime configuration

| Env var | Container value | Why |
|---|---|---|
| `DOCKER=1` | set it | The app checks this (`app/main.py`) and skips opening a browser. |
| `TACHIDUBB_OPEN_BROWSER=0` | set it | Explicit belt-and-braces alternative to `DOCKER`. |
| `OLLAMA_URL` | sidecar/host URL | Where the translation LLM lives. |
| `TACHIDUBB_TRANSLATION_BACKEND` / `TRANSLATION_BASE_URL` / `TRANSLATION_API_KEY` | optional | Use an OpenAI-compatible server instead of Ollama. |
| `HF_TOKEN` | host-supplied secret | Only needed for multi-speaker diarization. |
| `TACHIDUBB_WARMUP=1` | optional | Pre-spawns the TTS worker; costs ~4 GB VRAM up front. |

Expose port **8910**.

### GPU passthrough

Requires the NVIDIA Container Toolkit on the host (`--gpus all`, or
`deploy.resources.reservations.devices` in Compose). Without it the app still
starts but falls back to CPU/edge-tts. Verify with the built-in health check
after start: `curl localhost:8910/api/system` (or `tachidubb system`).

### Offline / air-gapped

The app itself is fully offline once weights exist. For an air-gapped image,
pre-seed the HF/torch caches, the MuseTalk checkout, and an Ollama model into
volumes at build time; otherwise the first job will try to reach the network.
Note that gated weights (pyannote) cannot be redistributed — diarization would
have to be downloaded by the user, not baked in.

### Rough size

- CUDA + cuDNN base: ~2–3 GB
- Torch cu128 + whisperx/voxcpm/transformers stack: ~6–8 GB
- Image without models: **~10 GB compressed-ish**
- Model volumes on top: **~13–18 GB** (HF caches + Ollama models)

Multi-stage build helps only marginally here — the wheels are the payload, not
the build tooling.

### Definition of done for a container PR

A container addition should not merge until all of these hold:

- [ ] `docker build` and `docker run --gpus all` succeed on a CUDA 12.8 host,
      and `/api/system` reports the GPU as OK.
- [ ] A real end-to-end job completes: YouTube/file source → translated dub
      → output file on a mounted volume.
- [ ] `TACHIDUBB_OPEN_BROWSER`/`DOCKER` leave no browser-launch attempt in logs.
- [ ] Ollama sidecar **and** host-Ollama paths are both documented and tried.
- [ ] Volumes documented and verified to survive `docker run --rm`.
- [ ] CI gains an (optional, non-blocking) `docker build` smoke job so the
      file does not silently rot.
- [ ] README + this document updated; the roadmap checkbox flipped.

Until that checklist is met, the source archive plus installer remains the only
supported way to distribute TachiDUBB.

---

## Verifying a download

Every release attaches `SHA256SUMS.txt`. To check a download:

```bash
# Linux / macOS
sha256sum -c SHA256SUMS.txt        # or: shasum -a 256 -c SHA256SUMS.txt
```

```powershell
# Windows PowerShell
$expected = (Get-Content SHA256SUMS.txt) -split ' ' | Select-Object -First 1
$actual = (Get-FileHash tachidubb-v0.4.0.zip -Algorithm SHA256).Hash.ToLower()
if ($actual -eq $expected) { 'OK' } else { 'MISMATCH' }
```

There is no signing yet; the checksum only proves the download matches what the
workflow produced.