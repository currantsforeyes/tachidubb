"""TTS engine factory + GPU memory cleanup.

Selection follows ``cfg.tts_engine`` preference, falling back through the tier
chain (Qwen / VoxCPM2 / F5-TTS / Edge-TTS) when a higher tier isn't installed.
The chosen engine is cached process-wide.

Extracted from ``server.py`` so routes in ``app/routers`` can obtain an engine
without importing the application module.
"""
import atexit
import logging

from app.config import cfg
from pipeline.synthesizer import (
    EdgeTTSFallback,
    F5TTSEngine,
    QwenTTSEngine,
    VoxCPMSynthesizer,
)

log = logging.getLogger("tachidubb.tts")

_tts_engine = None


def free_gpu_memory() -> None:
    """Best-effort GPU memory cleanup before loading a heavy model.

    Safe to call even if torch isn't importable — fails silently.
    """
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            free_mb = torch.cuda.mem_get_info()[0] / (1024 ** 2)
            log.info(f"[gpu] Cleared torch cache; free VRAM ~{free_mb:.0f} MB")
    except Exception as e:
        log.debug(f"free_gpu_memory: {e}")


def get_cached_engine():
    """Return the already-constructed engine, or None (no side effects)."""
    return _tts_engine


def terminate_tts_worker() -> None:
    """Best-effort kill of the persistent VoxCPM TTS subprocess.

    Called when we detect cancel mid-synthesis so the next iteration of
    stdout.readline() exits immediately instead of waiting for the current
    segment to finish rendering.
    """
    try:
        tts = get_cached_engine()
        if tts is None:
            return
        proc = getattr(tts, "_worker_proc", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                log.info("[cancel] TTS worker terminated")
            except Exception as e:
                log.debug(f"[cancel] TTS worker terminate failed: {e}")
            try:
                tts._worker_proc = None
            except Exception:
                pass
    except Exception as e:
        log.debug(f"[cancel] terminate_tts_worker error: {e}")


def get_tts_engine():
    """TTS engine factory. Priority: VoxCPM2 → F5-TTS → Edge-TTS.

    Selection follows cfg.tts_engine preference, falling back through the
    tier chain when a higher-tier engine isn't installed or fails to load.
    """
    global _tts_engine
    if _tts_engine is not None:
        return _tts_engine
    free_gpu_memory()

    requested = cfg.tts_engine  # "qwen" | "voxcpm" | "f5tts" | "edge-tts"

    if requested == "qwen":
        _tts_engine = QwenTTSEngine()
        _tts_engine.load()
        log.info("TTS engine: Qwen3-TTS Base (reference-audio quality mode)")
        return _tts_engine

    # Tier 1: VoxCPM2
    if requested in ("voxcpm", "auto"):
        try:
            import voxcpm  # noqa
            _tts_engine = VoxCPMSynthesizer(
                model_id=cfg.voxcpm_model,
                load_denoiser=False,
                cfg_value=cfg.voxcpm_cfg,
                inference_timesteps=cfg.voxcpm_steps,
            )
            log.info("TTS engine: VoxCPM2 (voice cloning)")
            atexit.register(lambda: _tts_engine.unload() if _tts_engine else None)
            return _tts_engine
        except ImportError:
            log.info("VoxCPM2 not installed, trying F5-TTS...")

    # Tier 2: F5-TTS
    if requested in ("f5tts", "auto", "voxcpm"):
        try:
            import f5_tts  # noqa
            _tts_engine = F5TTSEngine()
            log.info("TTS engine: F5-TTS (voice cloning, lighter than VoxCPM2)")
            return _tts_engine
        except ImportError:
            log.info("F5-TTS not installed, falling back to Edge-TTS")

    # Tier 3: Edge-TTS (always available)
    _tts_engine = EdgeTTSFallback()
    log.warning("TTS engine: Edge-TTS fallback (no voice cloning)")
    return _tts_engine