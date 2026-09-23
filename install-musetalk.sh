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
# MuseTalk pins an older CUDA 11.8 torch. On newer GPUs you may need a newer
# cu12x torch build instead — see the MuseTalk README.
$PY -m pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 \
    --index-url https://download.pytorch.org/whl/cu118
$PY -m pip install -r MuseTalk/requirements.txt
$PY -m pip install -U openmim

MIM=musetalk-runtime/bin/mim
$MIM install mmengine
$MIM install "mmcv==2.0.1"
$MIM install "mmdet==3.1.0"
$MIM install "mmpose==1.1.0"

echo "Downloading MuseTalk weights (a few GB)..."
( cd MuseTalk && bash download_weights.sh )

echo "Running MuseTalk diagnostic..."
[ -x venv/bin/python ] && venv/bin/python tools/diagnose_musetalk.py || true

echo "MuseTalk is ready. Restart TachiDUBB Studio to enable lip-sync."