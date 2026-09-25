"""A local AI through Ollama (https://ollama.com): the backup for when the online AI can't be reached.

Ollama runs models on your own computer, free and offline, and speaks the same chat format as OpenAI, so no extra
Python package is needed: this only makes plain HTTP calls to http://localhost:11434.
"""
import os
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


def chat(**kwargs):
    """Same call shape as the online AI (messages, tools, max_tokens...). Returns an OpenAI-style response object."""
    model, reason = status()
    if not model:
        raise LocalAIUnavailable(reason)
    payload = {"model": model, "messages": kwargs["messages"], "stream": False}
    for key in ("tools", "tool_choice", "max_tokens", "temperature"):
        if kwargs.get(key) is not None:
            payload[key] = kwargs[key]
    started = time.time()
    response = requests.post(f"{URL}/v1/chat/completions", json=payload, timeout=180)
    if response.status_code == 400 and "tools" in payload and "tool" in response.text.lower():
        payload.pop("tools"), payload.pop("tool_choice", None)  # this model can't call tools: answer in words instead
        response = requests.post(f"{URL}/v1/chat/completions", json=payload, timeout=180)
    if response.status_code != 200:
        raise LocalAIUnavailable(f"the local AI answered with an error ({response.status_code}): {response.text[:200]}")
    print(f"Local AI ({model}) answered in {time.time() - started:.1f}s", flush=True)
    return _wrap(response.json())
