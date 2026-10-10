"""Live smoke test: VoiceStudio's FireRedTTS3 sidecar on the real model.

Spawns ``voicesudio_addon/fireredtts3/main.py`` under **ComfyUI's Python**
(exactly what VoiceStudio's SubprocessBackend will do), drives the
length-prefixed JSON protocol - ready -> synthesize -> audio -> shutdown -
and writes the returned PCM to a wav.

    python tools/voicesudio_firered_smoke.py
    python tools/voicesudio_firered_smoke.py --lang ru --text "..."
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "voicesudio_addon" / "fireredtts3" / "main.py"
DEFAULT_COMFY = Path(os.environ.get("TACHIDUBB_COMFY_ROOT") or r"D:\ComfyUI-Easy-Install\ComfyUI")
DEFAULT_REF = REPO / "outputs" / "8ff2deae" / "speaker_refs" / "ref_SPEAKER_00.wav"


def runtime_python(root: Path) -> Path:
    """Same probe as synthesizer._find_interpreter: Easy-Install keeps the
    interpreter *beside* the ComfyUI folder, classic installs inside it."""
    if os.name == "nt":
        names = (
            "python_embeded/python.exe",
            "venv/Scripts/python.exe",
            "python.exe",
        )
    else:
        names = ("python_embeded/python", "venv/bin/python", "python3")
    for base in (root, root.parent):
        for rel in names:
            path = base / rel
            if path.is_file():
                return path
    raise SystemExit(f"ComfyUI python not found under {root} or {root.parent}")


class Sidecar:
    def __init__(self, python: Path):
        env = dict(os.environ)
        env.pop("OMNIVOICE_FIRERED_STUB", None)
        self.proc = subprocess.Popen(
            [str(python), str(SIDECAR)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.frames: "queue.Queue" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _pump(self) -> None:
        out = self.proc.stdout
        try:
            while True:
                header = out.read(4)
                if len(header) < 4:
                    self.frames.put(None)
                    return
                (length,) = struct.unpack(">I", header)
                self.frames.put(json.loads(out.read(length).decode("utf-8")))
        except Exception:
            self.frames.put(None)

    def _drain_stderr(self) -> None:
        for raw in iter(self.proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                print(f"    [sidecar] {line}", flush=True)

    def send(self, obj: dict) -> None:
        payload = json.dumps(obj).encode("utf-8")
        self.proc.stdin.write(struct.pack(">I", len(payload)) + payload)
        self.proc.stdin.flush()

    def expect(self, op: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        while True:
            frame = self.frames.get(timeout=max(1.0, deadline - time.time()))
            if frame is None:
                raise SystemExit(f"sidecar exited early (rc={self.proc.poll()})")
            if frame.get("op") == "progress":
                print(f"    [progress] {frame}", flush=True)
                continue
            if frame.get("op") == "error":
                raise SystemExit(f"sidecar error: {frame}")
            if frame.get("op") != op:
                raise SystemExit(f"wanted {op}, got {frame}")
            return frame


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--comfy", type=Path, default=DEFAULT_COMFY)
    ap.add_argument("--ref", type=Path, default=DEFAULT_REF)
    ap.add_argument("--ref-text", default="")
    ap.add_argument("--text", default="The sidecar is alive, and the waveform agrees.")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--out", type=Path,
                    default=Path(os.environ.get("TEMP", ".")) / "firered_smoke.wav")
    ap.add_argument("--load-timeout", type=float, default=600)
    ap.add_argument("--gen-timeout", type=float, default=300)
    args = ap.parse_args()

    if not args.ref.exists():
        raise SystemExit(f"reference clip not found: {args.ref}")

    python = runtime_python(args.comfy)
    print(f"spawn: {python} {SIDECAR}")
    sc = Sidecar(python)

    t0 = time.time()
    ready = sc.expect("ready", args.load_timeout)
    print(f"ready in {time.time() - t0:.1f}s  sr={ready['sample_rate']}")

    sc.send({"op": "ping"})
    pong = sc.expect("pong", 60)
    print(f"pong  vram={pong.get('vram_mb', '?')} MB")

    t1 = time.time()
    sc.send({
        "op": "synthesize",
        "text": args.text,
        "ref_audio": str(args.ref),
        "ref_text": args.ref_text,
        "language": args.lang,
    })
    audio = sc.expect("audio", args.gen_timeout)
    elapsed = time.time() - t1

    pcm = base64.b64decode(audio["audio_pcm_b64"])
    import numpy as np
    import soundfile as sf

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32767.0
    sf.write(str(args.out), samples, audio["sample_rate"])
    dur = len(samples) / audio["sample_rate"]
    print(
        f"audio: {dur:.2f}s at {audio['sample_rate']} Hz "
        f"in {elapsed:.1f}s  ->  {args.out}"
    )

    sc.send({"op": "shutdown"})
    rc = sc.proc.wait(timeout=30)
    print(f"shutdown rc={rc}")
    return 0 if rc == 0 and dur > 0.2 else 1


if __name__ == "__main__":
    sys.exit(main())
