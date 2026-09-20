"""Generate a short multi-speaker Qwen3-TTS reference-audio comparison.

Run with qwen-tts-runtime\Scripts\python.exe after qwen_asr_refs.py.  It
uses TachiDUBB's translation checkpoint only as the text/speaker test set;
the generated WAVs remain separate from normal TachiDUBB outputs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def configure_windows_dlls() -> None:
    candidates = [
        os.environ.get("TACHIDUBB_FFMPEG_BIN", ""),
        r"C:\Users\mrgar\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            os.add_dll_directory(candidate)
            return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--translations", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    args = parser.parse_args()

    references = json.loads(args.references.read_text(encoding="utf-8"))
    translations = json.loads(args.translations.read_text(encoding="utf-8"))
    segments = translations["segments"][: args.limit]
    if not segments:
        raise SystemExit("No translated segments were found.")

    configure_windows_dlls()
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    model = Qwen3TTSModel.from_pretrained(args.model, dtype=torch.bfloat16, device_map="cuda:0")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for segment in segments:
        speaker = segment["speaker"]
        reference = references.get(speaker)
        if not reference or not reference.get("text"):
            raise RuntimeError(f"No usable ASR reference transcript for {speaker}.")
        audio, sample_rate = model.generate_voice_clone(
            text=segment["translated_text"],
            language="English",
            ref_audio=reference["audio"],
            ref_text=reference["text"],
            non_streaming_mode=True,
        )
        filename = f"segment_{segment['idx']:02d}_{speaker}.wav"
        output_path = args.output_dir / filename
        sf.write(output_path, audio[0], sample_rate)
        manifest.append({
            "segment": segment["idx"],
            "speaker": speaker,
            "text": segment["translated_text"],
            "reference_text": reference["text"],
            "audio": str(output_path),
        })
        print(f"Saved {output_path.name}")
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
