# FireRedTTS3 for VoiceStudio (out-of-tree engine)

Adds **FireRedTTS3** (https://huggingface.co/FireRedTeam/FireRedTTS3) to
VoiceStudio's engine picker as a subprocess-isolated sidecar - the
"installed alongside, selected by id" path from VoiceStudio's
`docs/engine-acceptance.md`, with no changes to their core pipelines.

## Why it is shaped like this

- VoiceStudio's packaged build ships a **read-only, code-signed Python
  environment**; installing FireRed's torch/transformers stack into it would
  break the signature.
- ComfyUI's interpreter already has the right stack **plus** the
  `FireRedTTS3-ComfyUI` pack and the weights - so `venv_python()` points at
  ComfyUI's Python (probed with the same sibling-layout logic as
  `synthesizer._find_interpreter`, the probe whose absence once fell back to
  Edge-TTS), and `main.py` speaks VoiceStudio's length-prefixed JSON wire
  protocol to it.
- Synthesis is tachidubb's validated `pipeline/firered_worker.py` path:
  pack import via synthetic package, prompt latents cached per reference
  clip, window-anchored `max_gen_steps` budget (the fix for the 64 s
  runaway → double-speech bug).
- The spawn handshake reads exactly one frame (`ready`), so the ~1 min cold
  load happens lazily on first synthesize, where progress frames re-arm the
  parent's recv deadline.

## Install / uninstall

```bash
python tools/install_voicesudio_firered.py          # install (idempotent)
python tools/install_voicesudio_firered.py --check  # verify wiring
python -m pytest tests/test_voicesudio_firered_addon.py -q  # contract tests
python tools/voicesudio_firered_smoke.py            # live test (real model)
```

Then **restart VoiceStudio** and pick
"FireRedTTS3 (15-lang zero-shot clone · ComfyUI runtime)" in the engine
picker.

**Persistence.** VoiceStudio re-extracts
`%APPDATA%/VoiceStudio/runtime/project` from its install-time source
`<install>/resources/backend` on *every launch* — patching the runtime tree
alone gets deleted and reverted within one restart (observed: engine folder
removed, registry edit restored to its packaged mtime, all engine dirs
re-created seconds apart). `app.asar` holds no backend source, so
`resources/backend` is the only source of truth: the installer patches **both
trees**, and every re-extraction then carries the engine forward. An app
update replaces `resources/` — re-run the installer after updating.

Uninstall: remove the `"fireredtts3"` entry from
`services/tts_backend.py::_LAZY_REGISTRY` in both trees (originals backed up
as `tts_backend.py.bak-firered`) and delete `backend/engines/fireredtts3/`.

## Configuration

| Env var | Default | Meaning |
| --- | --- | --- |
| `OMNIVOICE_FIRERED_COMFY_ROOT` | `TACHIDUBB_COMFY_ROOT` or `D:\ComfyUI-Easy-Install\ComfyUI` | ComfyUI code root (pack + weights) |
| `OMNIVOICE_FIRERED_PACK_DIR` | `<root>/custom_nodes/FireRedTTS3-ComfyUI` | pack location |
| `OMNIVOICE_FIRERED_RECV_TIMEOUT_S` | `900` | generate recv deadline (cold load) |
| `OMNIVOICE_FIRERED_STUB` | off | `1` = sine-wave fake model (CI round-trip) |

Output is the pack's native **24 kHz**; VoiceStudio masters/resamples as it
does for every engine. Loaded model holds ~6.8 GB VRAM while resident and is
reaped when idle.

## Video timeline: VoiceStudio job → OpenShot project

VoiceStudio has no video timeline; OpenShot does. Export any dub job folder:

```bash
python tools/export_voicesudio_to_openshot.py "%APPDATA%\OmniVoice\dub_jobs\<id>"
```

Writes `<job>/openshot.osp` — picture on top (original.mp4, audio muted),
then the full-length dub (audible), the per-segment dub clips placed at each
segment's source start (muted; mute the full dub to work line by line), the
background stem (audible) and the source speech lane (muted). Segment timings
come from VoiceStudio's `omnivoice.db` (`dub_history.job_data.segments`);
without the db the export still works, minus the segment track.

Verified end-to-end against OpenShot 4.0.1: loads with a clean log
(`Loaded project ...`, no exceptions), autosave round-trips, mute states and
segment positions preserved. Schema notes are in the exporter's docstring —
including the `version` trap: `_default.project` ships `0.0.0`, which sends
OpenShot down a legacy upgrade path that expects full clip keyframes.

## Verified

- 7 contract tests (wire round-trip on the stub, step budget, PCM encoding,
  installed wiring)
- live sidecar: ready 57 s, 2.56 s clip, audible (RMS 0.116), rc=0
- through VoiceStudio's own code: registry resolves the class,
  `list_backends()` shows `available: true, isolation_mode: subprocess`,
  `health_check() -> (True, 'pong')`, `generate() -> Tensor [1, 69120]`,
  `unload() -> ok`
