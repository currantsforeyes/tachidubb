"""Download any MuseTalk weight files that are missing.

MuseTalk's own ``download_weights.bat`` uses ``--include "a" "b"`` (two
patterns), but only the second+ pattern actually downloads — the first pattern
of each command is silently skipped (e.g. ``sd-vae/config.json``). That leaves
inference failing later with a confusing error. This script re-checks the
required files and fetches just the missing ones.

Run with a Python that has ``huggingface_hub`` (the musetalk runtime):

    musetalk-runtime\\Scripts\\python.exe tools\\ensure_musetalk_weights.py

Exit code is 0 when all weights are present, 1 otherwise.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AUX = [
    "sd-vae/config.json",
    "sd-vae/diffusion_pytorch_model.bin",
    "whisper/config.json",
    "whisper/preprocessor_config.json",
    "whisper/pytorch_model.bin",
    "dwpose/dw-ll_ucoco_384.pth",
    "face-parse-bisent/79999_iter.pth",
    "face-parse-bisent/resnet18-5c106cde.pth",
    "syncnet/latentsync_syncnet.pt",
]
VERSION = {
    "v15": ["musetalkV15/unet.pth", "musetalkV15/musetalk.json"],
    "v1": ["musetalk/pytorch_model.bin", "musetalk/musetalk.json"],
}
# relative path -> Hugging Face repo id
SOURCE = {
    "sd-vae/config.json": "stabilityai/sd-vae-ft-mse",
    "sd-vae/diffusion_pytorch_model.bin": "stabilityai/sd-vae-ft-mse",
    "whisper/config.json": "openai/whisper-tiny",
    "whisper/preprocessor_config.json": "openai/whisper-tiny",
    "whisper/pytorch_model.bin": "openai/whisper-tiny",
    "dwpose/dw-ll_ucoco_384.pth": "yzd-v/DWPose",
    "face-parse-bisent/79999_iter.pth": "ManyOtherFunctions/face-parse-bisent",
    "face-parse-bisent/resnet18-5c106cde.pth": "ManyOtherFunctions/face-parse-bisent",
    "syncnet/latentsync_syncnet.pt": "ByteDance/LatentSync",
    "musetalk/musetalk.json": "TMElyralab/MuseTalk",
    "musetalk/pytorch_model.bin": "TMElyralab/MuseTalk",
    "musetalkV15/musetalk.json": "TMElyralab/MuseTalk",
    "musetalkV15/unet.pth": "TMElyralab/MuseTalk",
}


def find_repo() -> Path:
    env = os.getenv("TACHIDUBB_MUSETALK_DIR", "").strip()
    candidates = ([Path(env)] if env else []) + [
        ROOT / "MuseTalk", ROOT / "external" / "MuseTalk", Path.home() / "MuseTalk",
    ]
    for d in candidates:
        if (d / "scripts" / "inference.py").exists():
            return d
    raise SystemExit("MuseTalk checkout not found (set TACHIDUBB_MUSETALK_DIR)")


def main() -> int:
    repo = find_repo()
    models = repo / "models"
    version = "v15" if (models / "musetalkV15" / "unet.pth").exists() else "v1"
    required = AUX + VERSION[version]

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("huggingface_hub is not installed. Install it (pip install huggingface_hub) "
              "or run this with the musetalk runtime Python.")
        return 1

    missing = [rel for rel in required if not (models / rel).exists()]
    if not missing:
        print(f"All {len(required)} required weights present under {models} (version {version}).")
        return 0

    print(f"Missing {len(missing)} weight file(s) (version {version}):")
    remaining = []
    for rel in missing:
        repo_id = SOURCE.get(rel)
        if not repo_id:
            remaining.append(rel)
            print(f"  !! {rel} (no known source)")
            continue
        dest = models / Path(rel).parent
        dest.mkdir(parents=True, exist_ok=True)
        try:
            hf_hub_download(repo_id=repo_id, filename=Path(rel).name, local_dir=str(dest))
            print(f"  OK {rel}")
        except Exception as exc:  # noqa: BLE001
            remaining.append(rel)
            print(f"  !! {rel}: {type(exc).__name__}: {str(exc)[:120]}")

    if remaining:
        print(f"\n{len(remaining)} file(s) still missing.")
        return 1
    print("\nAll required weights are now present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())