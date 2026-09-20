"""One-shot Qwen3-TTS worker for the isolated Python 3.12 runtime.

The main TachiDUBB server remains on its existing environment.  This worker is
started only for Qwen jobs, so Qwen's pinned Transformers version cannot affect
WhisperX, pyannote, or VoxCPM.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def event(**payload) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def configure_windows_dlls() -> None:
    candidates = [
        os.environ.get("TACHIDUBB_FFMPEG_BIN", ""),
        r"C:\Users\mrgar\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            os.add_dll_directory(candidate)
            return


def main(job_path: str) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    configure_windows_dlls()
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    event(event="loading", model=job["model"])
    started = time.time()
    model = Qwen3TTSModel.from_pretrained(
        job["model"], dtype=torch.bfloat16, device_map="cuda:0"
    )
    event(event="loaded", seconds=round(time.time() - started, 1), sample_rate=24000)

    ok = 0
    for segment in job["segments"]:
        idx = segment["idx"]
        try:
            reference_text = (segment.get("reference_text") or "").strip()
            kwargs = {
                "text": segment["text"],
                "language": job.get("target_language", "English"),
                "ref_audio": segment["reference_audio"],
                "non_streaming_mode": True,
            }
            if reference_text:
                kwargs["ref_text"] = reference_text
            else:
                # This is lower fidelity than the transcript-plus-audio path,
                # but still preserves the source timbre if reference ASR fails.
                kwargs["x_vector_only_mode"] = True
            audio, sample_rate = model.generate_voice_clone(**kwargs)
            sf.write(segment["output_path"], audio[0], sample_rate)
            ok += 1
            event(event="segment", idx=idx, ok=True, sample_rate=sample_rate,
                  reference_mode="transcript" if reference_text else "xvector")
        except Exception as exc:
            event(event="segment", idx=idx, ok=False, error=f"{type(exc).__name__}: {exc}")
    event(event="done", ok=ok, total=len(job["segments"]))


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as exc:
        event(event="fatal", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        raise
