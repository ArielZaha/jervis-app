"""A local AI through Ollama (https://ollama.com): the backup for when the online AI can't be reached.

Ollama runs models on your own computer, free and offline, and speaks the same chat format as OpenAI, so no extra
Python package is needed: this only makes plain HTTP calls to http://localhost:11434.
"""
import os
import re
import subprocess
import threading
import time
from types import SimpleNamespace

import requests

URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def set_url(url: str) -> None:
    """Where the local AI answers. local_ai.py sets this once it has found or started one."""
    global URL
    URL = url.rstrip("/")
    _last_good["at"] = 0.0
DEFAULT_MODEL = "llama3.2"
DICTALM = "hf.co/dicta-il/dictalm2.0-instruct-GGUF:Q4_K_M"   # Hebrew (see ROLE_PREFERENCES); 4.4 GB, Apache-2.0
# The best small models for a voice assistant, in the order Jervis prefers to pick from what is installed.
PREFERRED = ["llama3.2", "llama3.1", "qwen2.5", "qwen3", "gemma3", "phi4-mini", "mistral", "llama3", "gemma2", "phi3"]


class LocalAIUnavailable(Exception):
    """Ollama isn't running, or has no model installed."""


class _Obj(SimpleNamespace):
    """Attribute access for JSON, where a missing field is None (the AI response format has many optional fields)."""
    def __getattr__(self, name):
        return None


def _wrap(value):
    if isinstance(value, dict):
        return _Obj(**{k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


_last_good = {"model": None, "at": 0.0}   # the model that last answered, so every question isn't a status check
MODEL_CACHE_SECONDS = 30


def _tags():
    """The installed models, or None if the local AI can't be reached (asked twice: Ollama has brief hiccups)."""
    for attempt in (1, 2):
        try:
            response = requests.get(f"{URL}/api/tags", timeout=2)
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", []) if m.get("name")]
        except (requests.RequestException, ValueError, KeyError):
            if attempt == 1:
                time.sleep(0.5)
    return None


def installed_models() -> list:
    return _tags() or []


def pick_model(models=None):
    """The model to use: OLLAMA_MODEL if set, else the best installed one, else None."""
    wanted = os.getenv("OLLAMA_MODEL")
    models = installed_models() if models is None else models
    if wanted:
        return wanted if any(m == wanted or m.split(":")[0] == wanted.split(":")[0] for m in models) else None
    for base in PREFERRED:
        for name in models:
            if name.split(":")[0] == base:
                return name
    return models[0] if models else None


def status() -> tuple:
    """(model or None, reason if unavailable)."""
    if _last_good["model"] and time.time() - _last_good["at"] < MODEL_CACHE_SECONDS \
            and _last_good["model"].split(":")[0] == (os.getenv("OLLAMA_MODEL") or _last_good["model"]).split(":")[0]:
        return _last_good["model"], ""
    models = _tags()
    if models is None:
        return None, "my local AI isn't running yet (it's still being set up, or it stopped)"
    model = pick_model(models)
    if not model:
        wanted = os.getenv("OLLAMA_MODEL") or DEFAULT_MODEL
        return None, f"my local AI's model ({wanted}) is still being downloaded"
    _last_good.update(model=model, at=time.time())
    return model, ""


# ---------- which model does which job ----------
# An 8 GB GPU holds one 7B model at a time (Ollama swaps them in ~4 s), so the strong model also answers chat when
# it's installed: one warm model is faster overall than a small chat model plus swaps. JERVIS_CHAT_MODEL /
# JERVIS_AGENT_MODEL override the choice.
ROLE_PREFERENCES = {
    "agent": ["qwen2.5-coder:7b", "qwen2.5-coder", "qwen2.5:7b", "qwen2.5", "llama3.1:8b", "llama3.1", "qwen3:8b",
              "qwen3", "gemma3", "mistral"],
    # Qwen2.5-VL 7B first: it can locate things (boxes), the 3B places them worse and breaks its JSON; gemma3 can't
    # locate at all (measured on real photos, see vision.py)
    "vision": ["qwen2.5vl:7b", "qwen2.5vl", "llava", "llama3.2-vision", "gemma3"],
    # Conversation in Hebrew: the agent's coder model and llama3.2 write Hebrew that is fluent-looking nonsense.
    # DictaLM 2.0 (Dicta, the Israeli NLP centre: Mistral-7B trained further on Hebrew, Apache-2.0) writes natural,
    # correct Hebrew; qwen3:8b is the next best. gemma3 often answers Hebrew in English. Only multilingual models.
    "hebrew": [DICTALM, "qwen3:8b", "qwen3:14b", "gemma3:12b", "gemma3:4b", "gemma3"],
    # Hebrew <-> English translation (language.py). Measured on spoken commands and on Jervis's replies: DictaLM kept
    # every detail and flagged garbled speech; qwen3:8b invented details ("railing", "orange trees") and the coder
    # model invented whole commands; neither writes usable Hebrew. So: DictaLM, else qwen3 (Hebrew -> English only,
    # and language.py then asks before acting on it).
    "translate": [DICTALM, "qwen3:8b", "qwen3:14b"],
}
ROLE_ENV = {"agent": "JERVIS_AGENT_MODEL", "chat": "JERVIS_CHAT_MODEL", "vision": "OLLAMA_VISION_MODEL",
            "nlu": "JERVIS_NLU_MODEL", "hebrew": "JERVIS_HEBREW_MODEL", "translate": "JERVIS_TRANSLATE_MODEL"}
# Context per role. The Hebrew model is a second model: at 16k qwen3:8b needs 7.8 GB and spills onto the CPU on an
# 8 GB card; at 8k it's 6.2 GB, all on the GPU.
ROLE_CONTEXT = {"hebrew": 8192, "translate": 8192}
# DictaLM is loaded at one size for every job (Ollama reloads a model when the size changes): 3k holds a translation
# (its shared prompt is ~1,900 tokens, plus the answer) or a Hebrew answer, and every 128 MB saved is another layer
# on the GPU next to the speech models (on this 8 GB card each layer moved to the CPU slows it noticeably).
SMALL_CONTEXT_MODELS = {"dictalm": 3072}
KEEP_ALIVE = "30m"
# Room for the agent's instructions (~4k tokens), the scene and a detailed build's code. One fixed size for every
# structured call, since Ollama reloads a model whenever the context size changes.
NUM_CTX = 16384


def _match(models, wanted):
    for name in models:
        if name == wanted or (":" not in wanted and name.split(":")[0] == wanted):
            return name
    return None


def model_for(role: str = "chat", models=None):
    """The installed model for a job: "chat" (conversation), "agent" (planning, code, computer control), "nlu"
    (reading a command as a structured intent) or "vision". None if nothing suitable is installed."""
    models = installed_models() if models is None else models
    wanted = os.getenv(ROLE_ENV.get(role, ""), "")
    if wanted:
        found = _match(models, wanted)
        if found:
            return found
    if role == "nlu":
        # The agent's model, which is already in the GPU: on 8 GB only one ~5 GB model fits, and swapping in a
        # separate understanding model costs ~4 s per command — more than it gains (see nlu_eval.py).
        return model_for("agent", models)
    if role == "chat":
        # OLLAMA_MODEL is always set — Settings fills in its default (llama3.2) — so only a different value is a
        # real choice. Otherwise chat shares the agent's model: one model stays in the GPU instead of two swapping
        # on every turn (llama3.2 also loads with a 64k context on Ollama 0.35: 10 GB, partly on the CPU).
        chosen = os.getenv("OLLAMA_MODEL", "")
        if chosen and chosen.split(":")[0] != DEFAULT_MODEL:
            return pick_model(models)
        return model_for("agent", models) or pick_model(models)
    for preferred in ROLE_PREFERENCES.get(role, []):
        found = _match(models, preferred)
        if found:
            return found
    return pick_model(models) if role == "agent" else None


_role_cache = {}


def role_model(role: str):
    cached = _role_cache.get(role)
    if cached and time.time() - cached[1] < MODEL_CACHE_SECONDS:
        return cached[0]
    model = model_for(role)
    _role_cache[role] = (model, time.time())
    return model


def _context_for(model: str, wanted: int = None) -> int:
    """The context size to ask for. Ollama reloads a model (~5 s on this GPU) whenever a request's context size
    differs from the one it's loaded with. Every call here names its size (NUM_CTX unless a role needs less), but
    something else may have loaded the model with a bigger one (Ollama's own default, another app): when it's
    already loaded with at least what's needed, keep that size instead of reloading it."""
    wanted = wanted or NUM_CTX
    for name, size in SMALL_CONTEXT_MODELS.items():
        if name in (model or "").lower():
            wanted = size
    try:
        for loaded in requests.get(f"{URL}/api/ps", timeout=2).json().get("models", []):
            if model in (loaded.get("name"), loaded.get("model")) and (loaded.get("context_length") or 0) >= wanted:
                return int(loaded["context_length"])
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        pass
    return wanted


# ---------- fitting a model into the GPU ----------
# Ollama decides how much of a model goes on the GPU from the free memory it sees, and on Windows it doesn't see the
# memory other programs use — not Jervis's own speech models (2.2 GB), not Discord, a game or the browser. It then
# loads the whole model anyway, Windows quietly moves GPU memory out to system RAM, and every answer becomes 20-50x
# slower (measured on an 8 GB RTX 4060: a 90 s translation timeout, a 2-minute chat reply). So before Ollama loads
# a model, Jervis measures what's really free (nvidia-smi sees every process), makes room by unloading his other
# model (one 7B model at a time on such a GPU), and asks for only as many layers on the GPU as fit — the rest run on
# the CPU, slower but steady (~2x for a few layers, never the 20-50x of spilling).
GPU_MARGIN_MB = int(os.getenv("JERVIS_GPU_MARGIN_MB") or 350)   # for the window, other apps growing, speech scratch
_COMPUTE_MB = 300          # the model's working buffers besides its layers and cache
_gpu_plans = {}            # model -> (num_ctx, num_gpu or None for "all"): kept while loaded, so no call reloads it
_gpu_lock = threading.Lock()
# Held from planning a load until that load has answered: two models loading at once (a warm-up and a request) each
# planned around the other's still-invisible memory, and one ended up with 3 of its 29 layers on the GPU.
_load_lock = threading.Lock()
_shapes = {}               # model -> (layers, weights MB, KV MB per 1k context)


def gpu_memory():
    """(total MB, used MB) of the NVIDIA GPU, or None (no NVIDIA GPU / no nvidia-smi)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().splitlines()
        total, used = (int(x) for x in out[0].split(","))
        return total, used
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def _shape(model: str):
    """(layers incl. the output layer, weights MB, KV-cache MB per 1024 tokens of context), from Ollama."""
    if model in _shapes:
        return _shapes[model]
    try:
        info = requests.post(f"{URL}/api/show", json={"model": model}, timeout=10).json().get("model_info") or {}
        size = next((m.get("size") for m in requests.get(f"{URL}/api/tags", timeout=5).json().get("models", [])
                     if m.get("name") == model), None)
        arch = info.get("general.architecture")
        blocks = int(info[f"{arch}.block_count"])
        heads = int(info[f"{arch}.attention.head_count"])
        kv_heads = int(info.get(f"{arch}.attention.head_count_kv") or heads)
        head_dim = int(info.get(f"{arch}.attention.key_length") or info[f"{arch}.embedding_length"] // heads)
        kv_per_k = 2 * blocks * 1024 * kv_heads * head_dim * 2 / 2 ** 20   # K and V, f16
        _shapes[model] = (blocks + 1, int(size) / 2 ** 20, kv_per_k)
    except (requests.RequestException, ValueError, KeyError, TypeError, StopIteration):
        _shapes[model] = None
    return _shapes[model]


def unload_all(wait: float = 8.0) -> list:
    """Take every model out of the GPU (they load again on their next call, a few seconds): before something else
    needs the GPU's memory — Blender rendering a scene with EEVEE beside a 6 GB vision model ran an 8 GB card out
    of memory and Blender crashed. Returns what was unloaded."""
    loaded = list(_loaded())
    for name in loaded:
        try:
            requests.post(f"{URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=10)
        except requests.RequestException:
            pass
        _gpu_plans.pop(name, None)
    deadline = time.time() + wait
    while loaded and time.time() < deadline and any(n in _loaded() for n in loaded):
        time.sleep(0.25)
    return loaded


def is_loaded(model: str) -> bool:
    """Whether Ollama has `model` in memory right now."""
    return bool(model) and model in _loaded()


def _loaded() -> dict:
    try:
        return {m.get("name"): m for m in requests.get(f"{URL}/api/ps", timeout=3).json().get("models", [])}
    except (requests.RequestException, ValueError, AttributeError):
        return {}


def gpu_options(model: str, num_ctx: int) -> dict:
    """The options a call to `model` needs so it fits in the GPU: {} when there's no NVIDIA GPU to plan for, or
    {"num_gpu": n} with the layers that fit. Planned once per load (the same options every call: no reloads)."""
    if (os.getenv("JERVIS_GPU_FIT") or "on").lower() == "off":
        return {}
    with _gpu_lock:
        loaded = _loaded()
        plan = _gpu_plans.get(model)
        if plan and plan[0] == num_ctx and model in loaded:
            return {} if plan[1] is None else {"num_gpu": plan[1]}
        memory = gpu_memory()
        shape = _shape(model)
        if memory is None or shape is None:
            return {}
        # one big model at a time on the GPU: make room by unloading the others (Ollama would only evict them by its
        # own count, which doesn't see the rest of the GPU)
        others = [name for name in loaded if name != model]
        for name in others:
            try:
                requests.post(f"{URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=10)
            except requests.RequestException:
                pass
            _gpu_plans.pop(name, None)
        freed = sum((loaded[n].get("size_vram") or 0) for n in others) / 2 ** 20
        deadline = time.time() + 8
        while others and time.time() < deadline:   # gone from Ollama's list comes before the memory is free
            now = gpu_memory()
            if not any(n in _loaded() for n in others) and (now is None or now[1] <= memory[1] - 0.8 * freed):
                break
            time.sleep(0.25)
        if model in loaded:   # loaded by something else (or with other options): it's about to be reloaded anyway
            loaded_vram = (loaded[model].get("size_vram") or 0) / 2 ** 20
        else:
            loaded_vram = 0
        total, used = gpu_memory() or memory
        layers, weights_mb, kv_per_k = shape
        need = weights_mb + kv_per_k * num_ctx / 1024
        try:   # speech recognition about to load a model (the conversation switched language): leave it room
            import stt_local
            speech_soon = stt_local.pending_gpu_mb()
        except Exception:
            speech_soon = 0
        free = total - (used - loaded_vram) - GPU_MARGIN_MB - _COMPUTE_MB - speech_soon
        if need <= free:
            n = None
        else:
            n = max(0, min(layers, int(free / (need / layers))))
        _gpu_plans[model] = (num_ctx, n)
        print(f"GPU plan for {model}: {total - used + loaded_vram:.0f} MB free, needs {need + _COMPUTE_MB:.0f} MB -> "
              f"{'all' if n is None else n}/{layers} layers on the GPU", flush=True)
        return {} if n is None else {"num_gpu": n}


# One model at a time: calls to different models take turns (first come, first served), calls to the same model run
# together. A translation that started while the coder was loading for a program task (a real session) unloaded it,
# loaded beside it, and the coder loaded again: 10-13 s loads, both models in memory and the computer short of RAM.
_turns = threading.Condition()
_calls = {}                # model -> calls to it in progress
_queue = []                # [ticket, model] of the calls waiting for their turn
_tickets = iter(range(1, 1 << 62))
TURN_WAIT = 300            # seconds a call waits for the GPU before going ahead anyway (an answer that never ended)


def _may_go(model: str, ticket: int) -> bool:
    if any(n for m, n in _calls.items() if m != model):
        return False
    return all(m == model for t, m in _queue if t < ticket)


class gpu_slot:
    """`with gpu_slot(model, num_ctx) as options:` around a call to Ollama: the options that fit the model in the
    GPU, the GPU to that model until the call has answered (others wait their turn), and — when the call is going to
    load it — no second load of it planned meanwhile."""

    def __init__(self, model: str, num_ctx: int):
        self.model, self.num_ctx, self.held, self.turn = model, num_ctx, False, False

    def __enter__(self) -> dict:
        if (os.getenv("JERVIS_GPU_FIT") or "on").lower() != "off":
            with _turns:
                ticket = next(_tickets)
                _queue.append([ticket, self.model])
                deadline = time.time() + TURN_WAIT
                while not _may_go(self.model, ticket) and time.time() < deadline:
                    _turns.wait(max(0.05, deadline - time.time()))
                _queue.remove([ticket, self.model])
                _calls[self.model] = _calls.get(self.model, 0) + 1
                self.turn = True
                _turns.notify_all()   # the next ones in line for this model can come along
        plan = _gpu_plans.get(self.model)
        if not (plan and plan[0] == self.num_ctx and self.model in _loaded()):
            _load_lock.acquire()
            self.held = True
        try:
            return gpu_options(self.model, self.num_ctx)
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *exc):
        if self.held:
            self.held = False
            _load_lock.release()
        if self.turn:
            self.turn = False
            with _turns:
                _calls[self.model] -= 1
                if not _calls[self.model]:
                    del _calls[self.model]
                _turns.notify_all()


def _timing(data: dict) -> str:
    """How an answer's time was spent, from Ollama's own numbers (a slow load or a slow generation)."""
    try:
        load = (data.get("load_duration") or 0) / 1e9
        tokens, gen = data.get("eval_count") or 0, (data.get("eval_duration") or 0) / 1e9
        prompt = (data.get("prompt_eval_duration") or 0) / 1e9
        return (f" (load {load:.1f}s, prompt {prompt:.1f}s, {tokens} tokens at "
                f"{tokens / gen if gen else 0:.0f}/s)")
    except (TypeError, ZeroDivisionError):
        return ""


def chat_json(messages, schema: dict, role: str = "agent", max_tokens: int = 1500, temperature: float = 0.2,
              timeout: float = 120, model: str = None, options: dict = None):
    """Ask for an answer that must be JSON matching `schema` (Ollama's structured output: the model can't produce
    anything else). Returns the parsed dict. The token cap matters: without one, a model can pad JSON with
    whitespace until the timeout. `options`: more Ollama sampling options (e.g. repeat_penalty)."""
    import json
    content = _ask(messages, schema, role, max_tokens, temperature, timeout, model, options)
    try:
        return json.loads(content)
    except ValueError as e:
        raise LocalAIUnavailable("the local AI's answer was cut off before it finished") from e


def chat_text(messages, role: str = "agent", max_tokens: int = 300, temperature: float = 0.0, timeout: float = 120,
              model: str = None, options: dict = None, stop: list = None) -> str:
    """A plain-text answer (no JSON): for short, fast answers like a translation, where JSON's own keys and quotes
    were most of the tokens generated (and generating under a JSON grammar is slower per token too)."""
    return _ask(messages, None, role, max_tokens, temperature, timeout, model,
                {**(options or {}), **({"stop": stop} if stop else {})}).strip()


def _ask(messages, schema, role, max_tokens, temperature, timeout, model, options) -> str:
    model = model or role_model(role)
    if not model:
        raise LocalAIUnavailable("the local AI (Ollama) isn't reachable" if _tags() is None else
                                 "no local AI model is installed yet")
    num_ctx = _context_for(model, ROLE_CONTEXT.get(role))
    started = time.time()
    with gpu_slot(model, num_ctx) as fit:
        payload = {"model": model, "messages": messages, "stream": False, "keep_alive": KEEP_ALIVE,
                   "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx, **fit,
                               **(options or {})}}
        if schema is not None:
            payload["format"] = schema
        if model.startswith("qwen3") or "thinking" in model.lower():   # (reasoning models: answer directly)
            payload["think"] = False
        try:
            response = requests.post(f"{URL}/api/chat", json=payload, timeout=timeout)
        except requests.RequestException as e:
            raise LocalAIUnavailable(f"the local AI didn't answer ({type(e).__name__})") from e
    if response.status_code != 200:
        raise LocalAIUnavailable(f"the local AI answered with an error ({response.status_code}): {response.text[:200]}")
    data = response.json()
    content = (data.get("message") or {}).get("content") or ""
    print(f"Local AI ({model}, {role}) answered in {time.time() - started:.1f}s{_timing(data)}", flush=True)
    return content


def warm_up(role: str = "agent") -> None:
    """Load a model into the GPU ahead of time (a few seconds), so the first real request doesn't wait for it."""
    model = role_model(role)
    if not model:
        return
    try:   # with the same options the real calls use: a load with others would be reloaded on first use
        num_ctx = _context_for(model, ROLE_CONTEXT.get(role))
        with gpu_slot(model, num_ctx) as fit:
            requests.post(f"{URL}/api/generate", json={"model": model, "keep_alive": KEEP_ALIVE, "options": {
                "num_ctx": num_ctx, **fit}}, timeout=90)
    except requests.RequestException:
        pass


_HEBREW_LETTERS = re.compile(r"[֐-׿]")


def _last_user_text(messages) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, list):
                return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            return str(content or "")
    return ""


def _native_messages(messages) -> list:
    """OpenAI-style messages -> Ollama's own chat format: image parts become `images`, tool-call arguments are
    objects (not JSON text), tool results lose the OpenAI-only call id."""
    import json
    out = []
    for m in messages or []:
        m = dict(m)
        content = m.get("content")
        if isinstance(content, list):
            texts, images = [], []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    texts.append(part.get("text") or "")
                elif part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url") or ""
                    if url.startswith("data:") and "," in url:
                        images.append(url.split(",", 1)[1])
            m["content"] = "\n".join(texts)
            if images:
                m["images"] = images
        if m.get("tool_calls"):
            calls = []
            for call in m["tool_calls"]:
                function = (call.get("function") if isinstance(call, dict) else None) or {}
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments) if arguments.strip() else {}
                    except ValueError:
                        arguments = {}
                calls.append({"function": {"name": function.get("name"), "arguments": arguments or {}}})
            m["tool_calls"] = calls
        m.pop("tool_call_id", None)
        if m.get("content") is None:
            m["content"] = ""
        out.append(m)
    return out


def _openai_shape(data: dict, model: str) -> dict:
    """Ollama's chat answer in the OpenAI response shape the rest of Jervis reads."""
    import json
    message = data.get("message") or {}
    calls = [{"id": f"call_{i}_{int(time.time() * 1000)}", "type": "function",
              "function": {"name": (c.get("function") or {}).get("name"),
                           "arguments": json.dumps((c.get("function") or {}).get("arguments") or {})}}
             for i, c in enumerate(message.get("tool_calls") or [])]
    finish = "tool_calls" if calls else ("length" if data.get("done_reason") == "length" else "stop")
    return {"model": model, "choices": [{"index": 0, "finish_reason": finish, "message": {
        "role": "assistant", "content": message.get("content") or "", "tool_calls": calls or None}}]}


def chat(**kwargs):
    """Same call shape as the online AI (messages, tools, max_tokens...). Returns an OpenAI-style response object.
    `role` picks the model for the job (see model_for); a conversation in Hebrew goes to the "hebrew" model when
    one is installed.

    Through Ollama's own chat API, not its OpenAI-compatible one: that one can't set the context size, so Ollama
    loads its default (32k-64k) — a different size from every other call (each switch reloads the model, ~5 s) and,
    for some models, too big for an 8 GB GPU (llama3.2 at 64k: 10 GB, 42% on the CPU)."""
    role = kwargs.pop("role", "chat")
    model, reason = status()
    if not model:
        raise LocalAIUnavailable(reason)
    if role == "chat" and _HEBREW_LETTERS.search(_last_user_text(kwargs.get("messages"))):
        hebrew = role_model("hebrew")
        if hebrew:
            role = "hebrew"
    model = role_model(role) or model
    num_ctx = _context_for(model, ROLE_CONTEXT.get(role))
    options = {"num_ctx": num_ctx}
    if kwargs.get("max_tokens") is not None:
        options["num_predict"] = kwargs["max_tokens"]
    if kwargs.get("temperature") is not None:
        options["temperature"] = kwargs["temperature"]
    messages = _native_messages(kwargs["messages"])
    if role == "hebrew":   # the long system prompt is English; said last, the language actually sticks
        messages.append({"role": "system", "content": "The user wrote in Hebrew: answer in Hebrew."})
    payload = {"model": model, "messages": messages, "stream": False, "keep_alive": KEEP_ALIVE, "options": options}
    if model.startswith("qwen3") or "thinking" in model.lower():   # (reasoning models: answer directly)
        payload["think"] = False      # its thinking is slow and was never shown to the user
    if kwargs.get("tools"):
        payload["tools"] = kwargs["tools"]
    started = time.time()
    with gpu_slot(model, num_ctx) as fit:
        options.update(fit)
        try:
            response = requests.post(f"{URL}/api/chat", json=payload, timeout=180)
            if response.status_code == 400 and "tools" in payload and "tool" in response.text.lower():
                payload.pop("tools")   # this model can't call tools: answer in words instead
                response = requests.post(f"{URL}/api/chat", json=payload, timeout=180)
        except requests.RequestException as e:
            raise LocalAIUnavailable(f"the local AI didn't answer ({type(e).__name__})") from e
    if response.status_code != 200:
        raise LocalAIUnavailable(f"the local AI answered with an error ({response.status_code}): {response.text[:200]}")
    data = response.json()
    print(f"Local AI ({model}, {role}) answered in {time.time() - started:.1f}s{_timing(data)}", flush=True)
    return _wrap(_openai_shape(data, model))
