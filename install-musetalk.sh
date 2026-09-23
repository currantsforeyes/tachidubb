#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "Installing the optional MuseTalk lip-sync backend..."

# MuseTalk wants Python 3.10. Prefer `uv`, which downloads a local 3.10 with no
# system install; otherwise fall back to an installed Python 3.10.
if command -v uv &>/dev/null; then
    MAKE_VENV="uv venv --seed --python 3.10"
elif command -v python3.10 &>/dev/null; then
    MAKE_VENV="python3.10 -m venv"
else
    echo "MuseTalk needs Python 3.10. Install uv (https://docs.astral.sh/uv/) —"
    echo "it fetches a local 3.10 with no system install — or install Python 3.10,"
    echo "then rerun this script."
    exit 1
fi

if [ ! -f "MuseTalk/scripts/inference.py" ]; then
    echo "Cloning MuseTalk..."
    git clone https://github.com/TMElyralab/MuseTalk.git MuseTalk
fi

[ -d musetalk-runtime ] || $MAKE_VENV musetalk-runtime
PY=musetalk-runtime/bin/python
$PY -m pip install --upgrade pip
$PY -m pip install setuptools wheel "numpy==1.23.5"
# chumpy's setup.py does `import pip`, which fails under pip's isolated build
# environment (no pip in it). Build it without isolation instead.
$PY -m pip install chumpy --no-build-isolation
# CUDA 12.8 torch: MuseTalk runs OpenMMLab-free here (the worker patches
# preprocessing.py to use MuseTalk's vendored face detector), so we can use a
# modern torch with native kernels for RTX 40/50-series (Blackwell) GPUs.
$PY -m pip install torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0+cu128 \
    --index-url https://download.pytorch.org/whl/cu128
$PY -m pip install -r MuseTalk/requirements.txt
# OpenMMLab (mmcv/mmdet/mmpose) is intentionally NOT installed — their prebuilt
# wheels stop at torch 2.1/CUDA 12.1 which has no Blackwell kernels.

echo "Downloading MuseTalk weights (a few GB)..."
( cd MuseTalk && bash download_weights.sh )

echo "Verifying weights (fills in any the downloader skipped)..."
$PY tools/ensure_musetalk_weights.py || true

echo "Running MuseTalk diagnostic..."
[ -x venv/bin/python ] && venv/bin/python tools/diagnose_musetalk.py || true

echo "MuseTalk is ready. Restart TachiDUBB Studio to enable lip-sync."