"""What the agent has done successfully before, so a similar request is planned from a known-good example.

Only requests whose every check passed are kept (agent_core.AgentTask), so this never teaches the AI a mistake.
Stored as JSON in Jervis's data folder; the oldest entries drop off past LIMIT.
"""
import json
import os
import re
import threading
import time

import paths

LIMIT = 80
MIN_SIMILARITY = 0.4
_STOP = {"a", "an", "the", "and", "with", "of", "to", "in", "on", "for", "please", "can", "you", "could", "me", "my",
         "it", "some", "make", "create", "build", "add", "jervis", "blender", "minecraft", "then", "now", "that",
         "this", "is", "be", "i", "want", "would", "like"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in _STOP and len(w) > 1}


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


class Memory:
    def __init__(self, path: str = None):
        self.path = path or paths.data("agent_memory.json")
        self._lock = threading.Lock()
        self._entries = None

    def _load(self) -> list:
        if self._entries is None:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._entries = [e for e in json.load(f) if isinstance(e, dict) and e.get("steps")]
            except (OSError, ValueError):
                self._entries = []
        return self._entries

    def similar(self, goal: str, app: str, k: int = 1) -> list:
        with self._lock:
            scored = [(similarity(goal, e.get("goal", "")), e) for e in self._load() if e.get("app") == app]
        scored = [(s, e) for s, e in scored if s >= MIN_SIMILARITY]
        scored.sort(key=lambda pair: (-pair[0], -pair[1].get("at", 0)))
        return [e for _, e in scored[:k]]

    def remember(self, goal: str, app: str, steps: list) -> None:
        with self._lock:
            entries = [e for e in self._load() if not (e.get("app") == app and e.get("goal") == goal)]
            entries.append({"goal": goal, "app": app, "steps": steps, "at": time.time()})
            self._entries = entries[-LIMIT:]
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._entries, f, indent=1)
                os.replace(tmp, self.path)
            except OSError:
                pass
