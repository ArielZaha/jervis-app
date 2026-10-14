"""A structured record of every command Jarvis actually ran and what happened — separate from the casual
conversation transcript (session_file in app.py, which mixes commands in with ordinary chit-chat), so it can be
skimmed to answer "did that work" instead of read start to end. One JSON object per line, oldest first, in
logs/actions.jsonl: {"at": unix time, "kind": "direct"/"tool:<name>", "request": what was asked, "outcome": what
Jarvis actually returned or did}. `kind` and `outcome` are exactly what the command handler itself already decided,
not a separate guess at whether it "worked" — the outcome text itself says that.
"""
import json
import os
import time

import paths

_PATH = os.path.join(paths.logs_dir(), "actions.jsonl")


def log_action(kind: str, request: str, outcome) -> None:
    try:
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.time(), "kind": kind, "request": str(request)[:300],
                                "outcome": str(outcome)[:500]}) + "\n")
    except OSError:
        pass   # a log write failing must never break the action it's logging
