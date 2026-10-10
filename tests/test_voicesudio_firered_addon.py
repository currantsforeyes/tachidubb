"""Out-of-tree VoiceStudio engine (FireRedTTS3 sidecar): contract tests.

The sidecar speaks VoiceStudio's length-prefixed JSON wire protocol. These
tests drive ``voicesudio_addon/fireredtts3/main.py`` directly (its fd
privatization only runs under ``__main__``, so importing is safe) with the
stub model - the same CI round-trip idea as VoiceStudio's ``_echo`` sidecar -
plus the pure helpers, and verify the installed registry wiring when a
VoiceStudio install is present on this machine.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import queue
import struct
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "voicesudio_addon" / "fireredtts3" / "main.py"
VS_BACKEND = Path(
    os.environ.get("TACHIDUBB_VS_BACKEND")
    or (Path(os.environ.get("APPDATA", "")) / "VoiceStudio" / "runtime" / "project" / "backend")
)

_mod = None


def sidecar_module():
    global _mod
    if _mod is None:
        spec = importlib.util.spec_from_file_location("firered_sidecar", SIDECAR)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _mod = mod
    return _mod


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------


def test_language_tag_accepts_iso_codes_and_picker_names():
    mod = sidecar_module()
    assert mod.language_tag("en") == "English"
    assert mod.language_tag("English") == "English"
    assert mod.language_tag("ZH") == "Chinese"
    assert mod.language_tag(None) == "English"
    assert mod.language_tag("auto") == "English"
    with pytest.raises(ValueError, match="does not support"):
        mod.language_tag("kl")


def test_step_budget_is_window_anchored():
    mod = sidecar_module()
    # 6.25 steps/s with 2x headroom: a 4 s slot -> 8 s budget -> 50 steps.
    assert mod.max_gen_steps_for(4.0) == 50
    # floor: 2 s -> 12.5 rounds to 12 (banker's), min guard 6.
    assert mod.max_gen_steps_for(0.1) == 12
    # text estimate path: no duration -> ~12 chars/s * 2x headroom.
    assert mod._steps_for({}, "a" * 60) == mod.max_gen_steps_for(5.0)
    # an explicit duration wins over the estimate.
    assert mod._steps_for({"duration": 4.0}, "a" * 60) == 50


def test_pcm16_encoding_round_trip():
    mod = sidecar_module()
    audio = np.zeros((1, 100), dtype="float32")
    audio[0, 0] = 1.0
    audio[0, 1] = -2.0  # clipped to -1
    b64, n = mod._pcm16(audio)
    pcm = np.frombuffer(base64.b64decode(b64), dtype="<i2")
    assert n == 100
    assert pcm[0] == 32767
    assert pcm[1] == -32767


def test_steps_for_rejects_garbage_duration():
    mod = sidecar_module()
    assert mod._steps_for({"duration": "soon"}, "hi") == mod.max_gen_steps_for(
        max(len("hi") / 12.0, 1.0)
    )


# --------------------------------------------------------------------------
# wire round-trip against the stub model
# --------------------------------------------------------------------------


class _Sidecar:
    def __init__(self, env_extra: dict | None = None):
        env = dict(os.environ)
        env["OMNIVOICE_FIRERED_STUB"] = "1"
        env.update(env_extra or {})
        self.proc = subprocess.Popen(
            [sys.executable, str(SIDECAR)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.frames: "queue.Queue" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        out = self.proc.stdout
        try:
            while True:
                header = out.read(4)
                if len(header) < 4:
                    self.frames.put(None)
                    return
                (length,) = struct.unpack(">I", header)
                body = out.read(length)
                if len(body) < length:
                    self.frames.put(None)
                    return
                self.frames.put(json.loads(body.decode("utf-8")))
        except Exception:
            self.frames.put(None)

    def send(self, obj: dict) -> None:
        payload = json.dumps(obj).encode("utf-8")
        self.proc.stdin.write(struct.pack(">I", len(payload)) + payload)
        self.proc.stdin.flush()

    def expect(self, op: str, timeout: float = 60.0) -> dict:
        while True:
            frame = self.frames.get(timeout=timeout)
            if frame is None:
                raise AssertionError(
                    f"sidecar exited early (rc={self.proc.poll()}); "
                    f"wanted {op}"
                )
            if frame.get("op") == "progress":
                continue
            assert frame.get("op") == op, f"wanted {op}, got {frame}"
            return frame

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.send({"op": "shutdown"})
                self.proc.wait(timeout=15)
            except Exception:
                self.proc.kill()


def test_sidecar_round_trip_with_stub(tmp_path):
    ref = tmp_path / "ref.wav"
    sf.write(ref, np.zeros(int(0.5 * 24000), dtype="float32"), 24000)

    sc = _Sidecar()
    try:
        ready = sc.expect("ready")
        assert ready["engine"] == "fireredtts3"
        assert ready["sample_rate"] == 24000

        sc.send({"op": "ping"})
        sc.expect("pong")

        # missing reference -> structured error, session survives
        sc.send({"op": "synthesize", "text": "hello", "language": "en"})
        err = sc.expect("error")
        assert "ref_audio is required" in err["message"]
        sc.send({"op": "ping"})
        sc.expect("pong")

        # real synthesize
        sc.send({
            "op": "synthesize",
            "text": "hello world from the firered sidecar",
            "ref_audio": str(ref),
            "ref_text": "reference transcript",
            "language": "en",
        })
        audio = sc.expect("audio")
        pcm = np.frombuffer(base64.b64decode(audio["audio_pcm_b64"]), dtype="<i2")
        assert audio["sample_rate"] == 24000
        assert len(pcm) == audio["n_samples"]
        assert len(pcm) > 1000  # stub scales with text length

        # unknown op -> error frame, still alive
        sc.send({"op": "nope"})
        assert "unknown op" in sc.expect("error")["message"]

        sc.send({"op": "shutdown"})
        assert sc.proc.wait(timeout=30) == 0
    finally:
        sc.close()


def test_sidecar_load_failure_reports_error(tmp_path, monkeypatch):
    # No stub, bogus ComfyUI root -> load error frame + exit 1, not a hang.
    env = {"OMNIVOICE_FIRERED_STUB": "", "OMNIVOICE_FIRERED_COMFY_ROOT": str(tmp_path)}
    sc = _Sidecar(env)
    try:
        err = sc.expect("error", timeout=30)
        assert err["stage"] == "load"
        assert sc.proc.wait(timeout=30) == 1
    finally:
        if sc.proc.poll() is None:
            sc.proc.kill()


# --------------------------------------------------------------------------
# installed wiring (skipped until tools/install_voicesudio_firered.py runs)
# --------------------------------------------------------------------------


def test_installed_engine_files_and_registry():
    engines = VS_BACKEND / "engines" / "fireredtts3"
    registry = VS_BACKEND / "services" / "tts_backend.py"
    if not registry.exists():
        pytest.skip("VoiceStudio not installed on this machine")
    if not (engines / "main.py").exists():
        pytest.skip("engine not installed yet - run tools/install_voicesudio_firered.py")

    import py_compile

    for name in ("__init__.py", "main.py"):
        py_compile.compile(str(engines / name), doraise=True)
    text = registry.read_text(encoding="utf-8", errors="replace")
    assert '"fireredtts3": ("engines.fireredtts3", "FireRedTTS3Backend")' in text
