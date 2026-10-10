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

Uninstall: remove the `"fireredtts3"` entry from
`services/tts_backend.py::_LAZY_REGISTRY` (original backed up as
`tts_backend.py.bak-firered`) and delete `backend/engines/fireredtts3/`.

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

## Verified

- 7 contract tests (wire round-trip on the stub, step budget, PCM encoding,
  installed wiring)
- live sidecar: ready 57 s, 2.56 s clip, audible (RMS 0.116), rc=0
- through VoiceStudio's own code: registry resolves the class,
  `list_backends()` shows `available: true, isolation_mode: subprocess`,
  `health_check() -> (True, 'pong')`, `generate() -> Tensor [1, 69120]`,
  `unload() -> ok`
