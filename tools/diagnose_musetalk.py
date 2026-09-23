"""Standalone MuseTalk diagnostic.

Checks everything needed for the lip-sync feature and prints an actionable
report:

  * MuseTalk checkout + entry point
  * model weights (v1.5 vs v1.0)
  * the isolated musetalk-runtime interpreter
  * runtime deps (torch / OpenMMLab) + CUDA availability
  * ffmpeg

Run with:  python tools/diagnose_musetalk.py   (or venv\\Scripts\\python.exe ...)
Exit code is 0 when MuseTalk is ready to use, 1 otherwise.
"""
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.lipsync import probe_musetalk  # noqa: E402

_DEP_SCRIPT = (
    "import importlib, json\n"
    "out = {}\n"
    "for m in ('torch', 'mmcv', 'mmpose', 'mmdet'):\n"
    "    try:\n"
    "        mod = importlib.import_module(m)\n"
    "        out[m] = getattr(mod, '__version__', 'ok')\n"
    "    except Exception as e:\n"
    "        out[m] = 'ERROR ' + type(e).__name__\n"
    "try:\n"
    "    import torch\n"
    "    out['cuda'] = bool(torch.cuda.is_available())\n"
    "    if torch.cuda.is_available():\n"
    "        out['capability'] = list(torch.cuda.get_device_capability())\n"
    "    out['torch_cuda'] = getattr(torch.version, 'cuda', None)\n"
    "except Exception:\n"
    "    out['cuda'] = False\n"
    "print(json.dumps(out))\n"
)


def _line(ok, label, detail=""):
    mark = "OK " if ok else "!! "
    print(f"  [{mark}] {label}" + (f"  ({detail})" if detail else ""))
    return ok


def runtime_deps(python: str) -> dict:
    """Import torch/mmcv/mmpose/mmdet inside the isolated runtime."""
    try:
        proc = subprocess.run(
            [python, "-c", _DEP_SCRIPT],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {"error": (proc.stderr or proc.stdout or "unknown error")[-400:]}
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"error": "could not parse runtime output"}


def main() -> int:
    print("=" * 70)
    print("MuseTalk lip-sync diagnostic " + "=" * 43)
    print("=" * 70)

    info = probe_musetalk()

    print("\nDetection")
    _line(info["repo_dir"] is not None, "MuseTalk checkout",
          info["repo_dir"] or "not found")
    _line(info["unet_model_path"] is not None, "model weights",
          f"version={info['version']}" if info["version"] else "not found")
    _line(info["runtime_python"] is not None, "runtime interpreter",
          info["runtime_python"] or "not found")
    _line(bool(info["ffmpeg_bin"]), "ffmpeg", info["ffmpeg_bin"] or "not found")
    _line(bool(info.get("facealign_patch")), "OpenMMLab-free patch",
          "applied" if info.get("facealign_patch") else "will be applied on first lip-sync run")

    dep_ok = True
    if info["runtime_python"]:
        print("\nRuntime dependencies")
        deps = runtime_deps(info["runtime_python"])
        if "error" in deps:
            dep_ok = False
            _line(False, "could not probe runtime", deps["error"][:120])
        else:
            torch_val = str(deps.get("torch", "missing"))
            dep_ok = not torch_val.startswith("ERROR")
            _line(dep_ok, "torch", torch_val)
            # OpenMMLab is optional now (only the unpatched DWPose path needs it)
            for mod in ("mmcv", "mmpose", "mmdet"):
                val = str(deps.get(mod, "missing"))
                _line(not val.startswith("ERROR"), f"{mod} (optional)", val)
            _line(bool(deps.get("cuda")), "CUDA available",
                  f"torch cuda={deps.get('torch_cuda')}")
            cap = deps.get("capability")
            torch_cuda = deps.get("torch_cuda")
            if cap and tuple(cap) >= (12, 0) and torch_cuda:
                try:
                    if float(torch_cuda) < 12.8:
                        print(f"  [!! ] {cap} GPU with a CUDA <12.8 torch build — no native "
                              "kernels, inference falls back to a very slow path. "
                              "See the README (RTX 50-series).")
                except ValueError:
                    pass

    print("\nCandidate locations")
    for c in info["candidates"]:
        state = "checkout" if c["has_inference"] else ("dir" if c["exists"] else "absent")
        _line(c["has_inference"], c["dir"], state)

    if info.get("missing_weights"):
        print("\nMissing weights (run tools/ensure_musetalk_weights.py)")
        for w in info["missing_weights"]:
            print(f"  !! {w}")

    if info["problems"]:
        print("\nProblems")
        for p in info["problems"]:
            print(f"  - {p}")

    ready = info["installed"] and dep_ok and bool(info["ffmpeg_bin"])
    print("\n" + "=" * 70)
    if ready:
        print("MuseTalk looks READY. Restart the server and enable lip-sync.")
    else:
        print("MuseTalk is NOT ready. Run install-musetalk.bat (or .sh), then")
        print("re-run this diagnostic. Fix the [!!] lines above.")
    print("=" * 70)
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())