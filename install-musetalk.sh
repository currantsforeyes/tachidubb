#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "Installing the optional MuseTalk lip-sync backend..."

if ! command -v python3.10 &>/dev/null; then
    echo "Python 3.10 is required for MuseTalk. Install it, then rerun this script."
    exit 1
fi

if [ ! -f "MuseTalk/scripts/inference.py" ]; then
    echo "Cloning MuseTalk..."
    git clone https://github.com/TMElyralab/MuseTalk.git MuseTalk
fi

[ -d musetalk-runtime ] || python3.10 -m venv musetalk-runtime
PY=musetalk-runtime/bin/python
$PY -m pip install --upgrade pip
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

echo "MuseTalk is ready. Restart TachiDUBB Studio to enable lip-sync."