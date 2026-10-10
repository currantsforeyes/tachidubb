"""ComfyUI-hosted translation worker — the Ollama replacement.

Runs on **ComfyUI's Python**, so one environment (torch 2.11 / transformers
5.14 / llama_cpp) owns every AI stage of the pipeline instead of Ollama being
a second installation to keep alive. Two loaders share one interface:

* ``llama`` — ``llama_cpp`` over a GGUF (installed in ComfyUI's env already;
  CPU on this build). The model can be Ollama's own weights: Ollama stores
  blobs that are byte-for-byte GGUF files, so it needs no download.
* ``hf`` — ``transformers`` + torch, GPU-capable, for an FP8/4-bit model in
  ComfyUI's ``models/LLM``.

The loader is inferred from the path: a ``.gguf`` file selects ``llama``, a
directory selects ``hf``.

Protocol (line-delimited JSON, mirroring firered_worker):

    spawn   <comfy python> -u comfy_translate_worker.py --model <abs path>
    loaded  {"event": "ready", "backend": "llama", "seconds": 35.2}
    request {"id": 1, "system": "...", "user": "...", "temperature": 0.3,
             "top_p": 0.9, "max_tokens": 2048}
    reply   {"id": 1, "reply": "..."}      or      {"id": 1, "error": "..."}
    fatal   {"event": "fatal", "error": "..."}     (model failed to load)

The model is loaded once and then serves requests until stdin closes, because
reloading an 8.7 GB model per batch would cost more than the translation.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

# Same system prompt pipeline/translator.py sends to Ollama, so the two
# backends are comparable and behaviour does not change when swapping.
SYSTEM_PROMPT = (
    "You are a professional translator for video dubbing. "
    "Output ONLY the requested translation. "
    "Do NOT explain, reason, or show any thinking. "
    "Do NOT add preamble or commentary. "
    "Just the translated lines, numbered as asked."
)

DEFAULTS = {"temperature": 0.3, "max_tokens": 2048, "top_p": 0.9}


def emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def resolve_loader(path) -> str:
    """``.gguf`` -> llama_cpp, directory -> transformers."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".gguf":
        return "llama"
    if p.is_dir():
        return "hf"
    raise FileNotFoundError(f"model not found: {path}")


def load_model(path, n_threads: int = 0):
    """Return ``(backend, callable)`` where callable(system, user, opts) -> str."""
    kind = resolve_loader(path)
    if kind == "llama":
        return "llama", _load_llama(path, n_threads)
    return "hf", _load_hf(path)


def _load_llama(path, n_threads: int = 0):
    import llama_cpp

    threads = n_threads or os.cpu_count() or 4
    llm = llama_cpp.Llama(
        model_path=str(path),
        n_ctx=8192,                 # batches are multi-hundred-line prompts
        n_threads=threads,
        verbose=False,
    )

    def run(system: str, user: str, opts: dict) -> str:
        out = llm.create_chat_completion(
            messages=[{"role": "system", "content": system or SYSTEM_PROMPT},
                      {"role": "user", "content": user}],
            max_tokens=int(opts["max_tokens"]),
            temperature=float(opts["temperature"]),
            top_p=float(opts["top_p"]),
        )
        text = (out["choices"][0]["message"]["content"] or "").strip()
        if not text:
            raise RuntimeError("model returned an empty completion")
        return text

    return run


def _load_hf(path):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(path), trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(path), torch_dtype="auto", device_map="auto", trust_remote_code=True)

    def run(system: str, user: str, opts: dict) -> str:
        messages = [{"role": "system", "content": system or SYSTEM_PROMPT},
                    {"role": "user", "content": user}]
        inputs = tok.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt")
        # transformers returns a tensor, or (newer) a BatchEncoding.
        ids = inputs.input_ids if hasattr(inputs, "input_ids") else inputs
        ids = ids.to(model.device)
        out = model.generate(
            ids,
            max_new_tokens=int(opts["max_tokens"]),
            do_sample=True,
            temperature=float(opts["temperature"]),
            top_p=float(opts["top_p"]),
        )
        text = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()
        if not text:
            raise RuntimeError("model returned an empty completion")
        return text

    return run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ComfyUI-hosted translation worker")
    ap.add_argument("--model", required=True,
                    help="absolute path to a .gguf file or a transformers dir")
    ap.add_argument("--n-threads", type=int, default=0,
                    help="llama_cpp threads (0 = all cores)")
    args = ap.parse_args(argv)

    started = time.time()
    try:
        # llama_cpp prints loader chatter ("loaded bundled OpenMP runtime…")
        # to stdout, which would corrupt the line-delimited protocol. Our own
        # events are the only thing allowed on stdout.
        with contextlib.redirect_stdout(sys.stderr):
            backend, runner = load_model(args.model, args.n_threads)
    except Exception as exc:  # noqa: BLE001 - reported to the parent
        emit({"event": "fatal", "error": f"{type(exc).__name__}: {exc}"})
        return 1
    emit({"event": "ready", "backend": backend,
          "seconds": round(time.time() - started, 2)})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            opts = {k: req.get(k, DEFAULTS[k]) for k in DEFAULTS}
            reply = runner(req.get("system") or SYSTEM_PROMPT,
                           req["user"], opts)
            emit({"id": req_id, "reply": reply})
        except Exception as exc:  # noqa: BLE001 - one bad request must not
            emit({"id": req_id, "error": f"{type(exc).__name__}: {exc}"})  # kill the daemon
    return 0


if __name__ == "__main__":
    sys.exit(main())
