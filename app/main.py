"""TachiDUBB Studio — FastAPI application.

Owns the app instance, the lifespan (SQLite init, serial job queue, optional
TTS warmup) and router registration. ``server.py`` is the thin entry point
that runs this with uvicorn.

The speechbrain/k2 stub block MUST come before any ``pipeline`` import so that
WhisperX / pyannote (which transitively import speechbrain) see the stubs from
the very first load. The Windows FFmpeg DLL registration must likewise happen
before torchcodec/pyannote import.
"""
# ═══════════════════════════════════════════════════════════════════
# SPEECHBRAIN / K2 WORKAROUND — MUST RUN BEFORE ANY OTHER IMPORT
# ═══════════════════════════════════════════════════════════════════
# speechbrain 1.x uses lazy modules for `integrations.k2_fsa` and a few
# deprecated-redirect paths. On Windows the `k2` wheel doesn't exist, so
# these lazy imports fail the moment anything walks speechbrain's namespace
# (e.g. inspect.getmembers during TTS). We pre-populate sys.modules with empty
# stubs so importlib.import_module returns the stub instead of trying to load
# the broken chain.
import sys as _sys
import types as _types


def _tachidubb_stub_module(_name: str) -> None:
    if _name in _sys.modules:
        return
    m = _types.ModuleType(_name)
    m.__file__ = f"<tachidubb-stub:{_name}>"
    m.__path__ = []
    _sys.modules[_name] = m


for _n in (
    "k2",
    "speechbrain.k2_integration",
    "speechbrain.integrations.k2_fsa",
    "speechbrain.integrations.k2_fsa.ctc_loss",
    "speechbrain.integrations.k2_fsa.graph_compiler",
    "speechbrain.integrations.k2_fsa.lattice_decoder",
    "speechbrain.integrations.k2_fsa.lexicon",
    "speechbrain.integrations.k2_fsa.losses",
    "speechbrain.integrations.k2_fsa.prepare_lang",
    "speechbrain.integrations.k2_fsa.utils",
    "speechbrain.wordemb",
    "speechbrain.lobes.models.huggingface_transformers",
):
    _tachidubb_stub_module(_n)

# NOTE: `_sys`/`_types` are intentionally left in the module namespace.
# Deleting module-level import aliases here triggers ruff F821 false positives
# on the references inside `_tachidubb_stub_module` above.
del _tachidubb_stub_module, _n

# ═══════════════════════════════════════════════════════════════════

import asyncio
import logging
import os
import shutil
import sys
import time
import webbrowser
from contextlib import asynccontextmanager

from app.config import BASE

# Load .env file if python-dotenv is installed (HF_TOKEN, etc)
try:
    from dotenv import load_dotenv
    _env_path = BASE / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
        print(f"[env] Loaded {_env_path}")
except ImportError:
    pass  # dotenv optional


# Load .env manually (no python-dotenv dependency) so HF_TOKEN etc. are picked up
def _load_dotenv_simple() -> None:
    env_path = BASE / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv_simple()

# Force UTF-8 stdout for foreign-language transcripts on Windows cp1252 consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ─────────────────────────────────────────────────────────────
# Windows: help torchcodec find FFmpeg DLLs
# ─────────────────────────────────────────────────────────────
# torchcodec ships libtorchcodec_coreN.dll which in turn loads avformat/
# avcodec/avutil DLLs from wherever they happen to live. Python 3.8+ requires
# os.add_dll_directory() explicitly. We scan typical install locations and
# register any that contain avformat*.dll. No-op if torchcodec is absent.
if sys.platform == "win32":
    try:
        import os as _os
        _ffmpeg_candidates = []
        for _env_var in ("FFMPEG_DIR", "FFMPEG_PATH"):
            _p = _os.environ.get(_env_var, "").strip()
            if _p and _os.path.isdir(_p):
                _ffmpeg_candidates.append(_p)
                _bin = _os.path.join(_p, "bin")
                if _os.path.isdir(_bin):
                    _ffmpeg_candidates.append(_bin)
        _ffmpeg_on_path = shutil.which("ffmpeg")
        if _ffmpeg_on_path:
            _ffmpeg_candidates.append(_os.path.dirname(_ffmpeg_on_path))
        for _root in (
            r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
            _os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
        ):
            if _os.path.isdir(_root):
                _ffmpeg_candidates.append(_root)
        _added = set()
        for _d in _ffmpeg_candidates:
            if _d in _added or not _os.path.isdir(_d):
                continue
            try:
                _has_av = any(
                    f.lower().startswith("avformat") and f.lower().endswith(".dll")
                    for f in _os.listdir(_d)
                )
                if _has_av:
                    _os.add_dll_directory(_d)
                    _added.add(_d)
                    print(f"[ffmpeg] Registered DLL dir for torchcodec: {_d}")
            except Exception:
                continue
        # Not fatal — torchcodec is optional; pyannote has a fallback.
    except Exception as _e:
        print(f"[ffmpeg] DLL registration skipped: {_e}")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pipeline.synthesizer import VoxCPMSynthesizer

from app.config import OUTPUT_DIR, STATIC_DIR
from app.db import init_db
from app.state import load_jobs_from_disk
from app.routers.storage import router as storage_router
from app.routers.system import router as system_router
from app.routers.voices import router as voices_router
from app.routers.media import router as media_router
from app.routers.lipsync import router as lipsync_router
from app.routers.jobs import router as jobs_router
from app.routers.dub import router as dub_router
from app.routers.showcase import router as showcase_router
from app.routers.watch import router as watch_router
from app.showcase import maybe_assemble_showcase
from app.watcher import start as start_watcher, stop as stop_watcher
from app.queue import (
    shutdown as shutdown_queue,
    start as start_queue,
)
from app.pipeline import run_pipeline
from app.tts import get_tts_engine

# Paths come from app.config (already created at import time)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("tachidubb.server")


# Silence extremely repetitive polling endpoints that flood the console
class _QuietPolling(logging.Filter):
    _QUIET_SUBSTRINGS = (
        "/api/system",
        "/api/tags",
        "/api/job/",
        "/api/voices",
        "/outputs/",       # range-requests for video playback after completion
    )

    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not any(q in msg for q in self._QUIET_SUBSTRINGS)


for _logger_name in ("uvicorn.access", "httpx", "httpcore"):
    logging.getLogger(_logger_name).addFilter(_QuietPolling())
# httpx logs Ollama calls at INFO, demote to WARNING so only errors show
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# Windows ProactorEventLoop spams harmless WinError 10054 ("connection forcibly
# closed by remote host") every time a browser tab is closed or the video
# player seeks. Filter them out so real errors stand out.
class _WindowsConnResetFilter(logging.Filter):
    _NOISE_SUBSTRINGS = (
        "WinError 10054",
        "ConnectionResetError",
        "_call_connection_lost",
    )

    def filter(self, record):
        try:
            msg = record.getMessage()
            if any(n in msg for n in self._NOISE_SUBSTRINGS):
                return False
            if record.exc_info:
                exc_str = str(record.exc_info[1])
                if any(n in exc_str for n in self._NOISE_SUBSTRINGS):
                    return False
        except Exception:
            pass
        return True


logging.getLogger("asyncio").addFilter(_WindowsConnResetFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init SQLite store (creates table + migrates legacy JSON files)
    init_db(BASE / "tachidubb.db")
    load_jobs_from_disk()

    # Initialize job queue + start serial worker. Using a single worker
    # ensures GPU-heavy pipelines don't collide and OOM the card.
    start_queue(run_pipeline, maybe_assemble_showcase)

    # Batch folder watcher — no-op unless watch_enabled / TACHIDUBB_WATCH_ENABLED.
    start_watcher()

    if os.getenv("TACHIDUBB_OPEN_BROWSER", "1") == "1" and not os.getenv("DOCKER"):
        async def open_browser():
            await asyncio.sleep(1.5)
            try:
                webbrowser.open("http://localhost:8910")
            except Exception:
                pass
        asyncio.create_task(open_browser())

    # Optional TTS warmup (off by default — see README). VoxCPM holds ~4 GB of
    # VRAM for its lifetime, which starves larger translation models on 12 GB
    # cards. Opt in with TACHIDUBB_WARMUP=1.
    if os.getenv("TACHIDUBB_WARMUP", "0") == "1":
        async def warmup_tts():
            await asyncio.sleep(2.0)  # let server finish binding port
            try:
                import struct as _struct
                import tempfile as _tmp
                import wave as _wave
                log.info("[warmup] Pre-spawning persistent TTS worker...")
                t0 = time.time()
                tts = get_tts_engine()
                if not isinstance(tts, VoxCPMSynthesizer):
                    return  # Edge-TTS fallback doesn't need warmup
                # Create a minimal valid WAV file to serve as dummy reference
                dummy_dir = _tmp.mkdtemp(prefix="tachidubb_warmup_")
                dummy_ref = os.path.join(dummy_dir, "dummy_ref.wav")
                with _wave.open(dummy_ref, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                    w.writeframes(_struct.pack("<" + "h"*16000, *([0]*16000)))
                dummy_segs = [{
                    "idx": 0, "start": 0.0, "end": 1.0,
                    "text": "привет", "translated_text": "привет",
                    "speaker": "SPEAKER_00",
                }]
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: tts.synthesize_segments(
                    dummy_segs, dummy_dir,
                    speaker_refs={"SPEAKER_00": dummy_ref},
                    speaker_transcripts={"SPEAKER_00": ""},
                    tts_speed="balanced",
                ))
                log.info(f"[warmup] TTS worker ready in {time.time()-t0:.1f}s "
                         f"— first dub will skip model-load")
                try:
                    shutil.rmtree(dummy_dir, ignore_errors=True)
                except Exception:
                    pass
            except Exception as e:
                log.warning(f"[warmup] Pre-load failed "
                            f"(engine will load on first real use): {e}")
        asyncio.create_task(warmup_tts())

    yield

    # Shutdown: cancel queue worker + scheduler so they don't hang the process
    await shutdown_queue()
    await stop_watcher()


app = FastAPI(title="TachiDUBB Studio", version="2.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(storage_router)
app.include_router(system_router)
app.include_router(voices_router)
app.include_router(media_router)
app.include_router(lipsync_router)
app.include_router(jobs_router)
app.include_router(dub_router)
app.include_router(showcase_router)
app.include_router(watch_router)


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


__all__ = ["app"]