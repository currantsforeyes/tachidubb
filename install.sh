#!/usr/bin/env bash
set -e

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; C='\033[0;36m'; B='\033[1m'; N='\033[0m'
ok()   { echo -e "${G}[✓]${N} $*"; }
warn() { echo -e "${Y}[!]${N} $*"; }
err()  { echo -e "${R}[✗]${N} $*"; }
step() { echo -e "\n${C}${B}── $* ──${N}"; }

cd "$(dirname "$0")"

echo -e "${B}"
echo "╔══════════════════════════════════════════════╗"
echo "║    TachiDUBB Studio — AI Video Dubbing       ║"
echo "║    by TachikomaRed and smolemaru             ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${N}"

# ── Python ──
step "Checking Python"
PY_V=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJ=${PY_V%.*}; PY_MIN=${PY_V#*.}
if [[ "$PY_MAJ" != "3" || "$PY_MIN" -lt 10 || "$PY_MIN" -gt 12 ]]; then
    err "Python $PY_V — need 3.10-3.12 (VoxCPM2 constraint)"
    exit 1
fi
ok "Python $PY_V"

# ── FFmpeg ──
step "FFmpeg"
if command -v ffmpeg &>/dev/null; then ok "Found"
else
    warn "Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then brew install ffmpeg
    elif command -v apt-get &>/dev/null; then sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg
    elif command -v dnf &>/dev/null; then sudo dnf install -y ffmpeg
    else err "Install FFmpeg manually: https://ffmpeg.org"; exit 1; fi
    ok "Installed"
fi

# ── venv + core packages ──
step "Python environment"
[ ! -d "venv" ] && python3 -m venv venv && ok "venv created" || ok "venv exists"
source venv/bin/activate
pip install --upgrade pip wheel setuptools -q

step "Core packages"
pip install -q fastapi "uvicorn[standard]" python-multipart httpx soundfile numpy pydub nltk yt-dlp edge-tts
ok "Core installed"

# ── PyTorch ──
step "PyTorch"
if command -v nvidia-smi &>/dev/null; then
    ok "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
    if ! python3 -c "import torch" 2>/dev/null; then
        pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    fi
else
    warn "No GPU — CPU PyTorch"
    pip install -q torch torchvision torchaudio
fi
ok "PyTorch ready"

# ── Whisper ──
step "Whisper"
pip install -q faster-whisper 2>/dev/null && ok "faster-whisper installed" || {
    pip install -q openai-whisper
    ok "openai-whisper (fallback)"
}

# ── VoxCPM2 ──
step "VoxCPM2 (voice cloning)"
read -p "$(echo -e ${Y}'Install VoxCPM2? Downloads ~5GB on first use [Y/n]: '${N})" -n 1 -r; echo ""
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    pip install -q voxcpm && ok "VoxCPM2 installed" || warn "VoxCPM2 install failed — edge-tts fallback"
fi

# ── Ollama ──
step "Ollama"
if command -v ollama &>/dev/null; then ok "Found"
else
    warn "Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Installed"
fi

# ── NLTK data ──
python3 -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"
ok "NLTK data ready"

# ── Create launcher ──
cat > start.sh <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
source venv/bin/activate
[ -f .env ] && export $(grep -v '^#' .env | xargs)
if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
    command -v ollama &>/dev/null && { echo "Starting Ollama..."; ollama serve &>/dev/null & sleep 2; }
fi
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  TachiDUBB Studio — http://localhost:8910      ║"
echo "╚══════════════════════════════════════╝"
echo ""
python server.py
EOF
chmod +x start.sh

mkdir -p uploads outputs jobs_db

step "Pull translation model"
if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
    ollama serve &>/dev/null & sleep 3
fi
echo ""
echo -e "${B}Choose a model (or skip and pull later from UI):${N}"
echo "  1) qwen2.5:7b  — Recommended (4.7GB)"
echo "  2) qwen2.5:14b — Best (9GB)"
echo "  3) qwen2.5:3b  — Lightweight (1.9GB)"
echo "  4) Skip"
read -p "$(echo -e ${C}'Select [1-4, default=1]: '${N})" -n 1 -r; echo ""
case "${REPLY:-1}" in
    1) ollama pull qwen2.5:7b ;;
    2) ollama pull qwen2.5:14b ;;
    3) ollama pull qwen2.5:3b ;;
esac

step "Done!"
echo -e "   ${G}${B}./start.sh${N}   →   http://localhost:8910"
echo ""
