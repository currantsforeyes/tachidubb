r"""Create Qwen3-ASR transcripts for source voice-reference clips.

Run this with qwen-runtime\Scripts\python.exe.  The output JSON is intended
for qwen_tts_compare.py, which supplies the original audio and its transcript
to Qwen3-TTS Base for reference-audio voice cloning.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def configure_windows_dlls() -> None:
    """Make the local FFmpeg DLL directory visible before importing Torch."""
    candidates = [
        os.environ.get("TACHIDUBB_FFMPEG_BIN", ""),
        r"C:\Users\mrgar\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            os.add_dll_directory(candidate)
            return


def parse_reference(value: str) -> tuple[str, Path]:
    try:
        speaker, raw_path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("References must use SPEAKER=PATH.") from exc
    path = Path(raw_path).resolve()
    if not speaker or not path.is_file():
        raise argparse.ArgumentTypeError(f"Invalid reference: {value}")
    return speaker, path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", action="append", required=True, type=parse_reference)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--language", default="Russian")
    args = parser.parse_args()

    configure_windows_dlls()
    import torch
    from qwen_asr import Qwen3ASRModel

    model = Qwen3ASRModel.from_pretrained(
        args.model,
        dtype=torch.bfloat16,
        device_map="cuda:0",
        max_inference_batch_size=1,
    )
    result: dict[str, dict[str, str]] = {}
    for speaker, path in args.reference:
        transcription = model.transcribe(str(path), language=args.language)[0]
        result[speaker] = {
            "audio": str(path),
            "text": transcription.text.strip(),
            "language": transcription.language,
        }
        print(f"{speaker}: {transcription.text.strip()}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved reference transcripts to {args.output}")


if __name__ == "__main__":
    main()
