# OpenShot add-on: dubbing in the "Enhance with AI" menu

Puts TachiDUBB's dubbing pipeline behind OpenShot's own AI menu **without editing
a single line of OpenShot's Python**.

```
right-click a clip → Enhance with AI → Dub to another language… → type "English"
   ↓ their code (unchanged)
action_generate_trigger → placeholders substituted → ComfyUI POST /prompt
   ↓
openshot_dub node → spawns the serverless worker (tools/dub_worker.py)
   ↓
outputs copied into ComfyUI/output/openshot_dub/ → refs → OpenShot downloads
   ↓
Project Files: vocals.wav · background.wav · stem_SPEAKER_*.wav · dubbed_video.mp4 · subtitles.srt
   → select them → Add to Timeline…
```

## Install

### 1. ComfyUI node pack (no elevation needed)

Copy `comfy_nodes/openshot_dub` into ComfyUI's custom nodes:

```powershell
Copy-Item -Recurse openshot_addon\comfy_nodes\openshot_dub `
  D:\ComfyUI-Easy-Install\ComfyUI\custom_nodes\openshot_dub
```

Edit `custom_nodes\openshot_dub\config.json` so `runtime_root` / `python` point at
the AI runtime (where `pipeline/`, `app/` and `tools/dub_worker.py` live), and set
`outputs` to whichever files you want landing in Project Files.

> The runtime needs its own environment (torch, whisperx, pyannote, demucs, TTS
> models) — deliberately **not** installed into ComfyUI's embedded Python.

Restart ComfyUI afterwards.

### 2. The menu template (one file, needs elevation)

```powershell
Copy-Item openshot_addon\templates\dub-to-language.json `
  "C:\Program Files\OpenShot Video Editor\comfyui\"
```

Program Files isn't user-writable, so this step needs an elevated shell. Restart
OpenShot after copying.

## Why file refs instead of returning paths

`extract_file_outputs()` collects `{filename, subfolder, type}` refs from
`ui.{audios,videos,files}` for **any** extension, and `_import_generation_outputs()`
preserves the extension when it downloads them. A bare `.wav` path returned as *text*
would instead be written out as a `.txt` containing the path — so the node copies its
outputs into ComfyUI's output tree and returns proper refs.

Results land in **Project Files** (OpenShot's behaviour for every generation result),
not auto-placed on tracks — then *Add to Timeline…* puts them where you want.

## Config

| key | meaning |
|---|---|
| `runtime_root` | where `pipeline/`, `app/`, `tools/` live |
| `python` | interpreter that has the runtime's dependencies |
| `worker` | worker entry point, relative to `runtime_root` |
| `comfy_output` | override ComfyUI's output dir (empty = `folder_paths`) |
| `outputs` | glob patterns of job files to publish |
| `model`, `whisper_model`, `tts_speed`, `keep_bg`, `narration_mode` | pipeline defaults |

`OPENSHOT_DUB_CONFIG` points the node at a different config file.

## Translation stays local

The ComfyUI pack `ComfyUI_Text_Translation` wraps *cloud* translators (Google, Bing,
DeepL…). This integration deliberately keeps translation on the local Ollama backend:
the project's promise is no cloud and no uploading anyone's audio anywhere.
