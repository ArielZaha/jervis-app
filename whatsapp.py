"""Read the user's own WhatsApp chats (macOS WhatsApp Desktop): who has unread messages, and what they say.

Everything happens on this Mac. WhatsApp Desktop keeps its chats in a local database, which is opened READ-ONLY here:
nothing is sent anywhere, nothing can be changed, and nothing can be sent or marked as read from here. The text of messages
is only ever spoken or shown to the user; callers must never hand it to the online AI or write it to logs.
"""
import difflib
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import osal

_GROUP_FOLDERS = ("group.net.whatsapp.WhatsApp.shared", "group.net.whatsapp.WhatsAppSMB.shared")
_CORE_DATA_EPOCH = datetime(2001, 1, 1)
CHAT_TYPES = (0, 1)  # 0 = a person, 1 = a group (status updates, broadcasts and channels are left out)
MEDIA = {1: "a photo", 2: "a video", 3: "a voice message", 4: "a contact", 5: "a location", 8: "a document",
         11: "a GIF", 14: "a deleted message", 15: "a sticker"}


def enabled() -> bool:
    return (os.getenv("WHATSAPP_READING") or "on").strip().lower() not in ("off", "0", "false", "no")


def database_path():
    if not osal.IS_MAC:
        return None
    for folder in _GROUP_FOLDERS:
        path = os.path.expanduser(f"~/Library/Group Containers/{folder}/ChatStorage.sqlite")
        if os.path.exists(path):
            return path
    return None


def _connect() -> sqlite3.Connection:
    path = database_path()
    if not path:
        raise FileNotFoundError("WhatsApp's chat database was not found")
    connection = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=3)
    connection.execute("PRAGMA query_only = ON")  # belt and braces: this connection cannot write
    connection.row_factory = sqlite3.Row
    return connection


def data_age_minutes():
    """How many minutes ago WhatsApp last wrote its data. Recent changes go to the "-wal" side file first, so that counts too."""
    path = database_path()
    if not path:
        return None
    newest = max((os.path.getmtime(p) for p in (path, path + "-wal", path + "-shm") if os.path.exists(p)), default=None)
    return int((time.time() - newest) // 60) if newest else None


def is_running() -> bool:
    """True while WhatsApp Desktop is open (only then does it keep its data up to date)."""
    import subprocess
    try:
        return subprocess.run(["pgrep", "-x", "WhatsApp"], capture_output=True, timeout=3).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return True  # can't tell: don't raise a false alarm


def _when(core_data_seconds):
    try:  # Core Data counts seconds from 2001-01-01 UTC; show the time in the user's own time zone
        return datetime.fromtimestamp(float(core_data_seconds) + 978307200)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def describe(text, message_type) -> str:
    """What to say for one message: its text, or what kind of media it was."""
    if text and text.strip():
        return " ".join(text.split())
    return MEDIA.get(message_type, "a message I can't read")


def unread_chats(limit: int = 15) -> list:
    """Chats with unread messages, newest first: [{"id", "name", "unread", "group"}]."""
    with _connect() as db:
        rows = db.execute(
            f"""SELECT Z_PK AS id, ZPARTNERNAME AS name, ZUNREADCOUNT AS unread, ZSESSIONTYPE AS type
                FROM ZWACHATSESSION
                WHERE ZUNREADCOUNT != 0 AND ZSESSIONTYPE IN ({",".join(map(str, CHAT_TYPES))})
                  AND COALESCE(ZREMOVED, 0) = 0
                ORDER BY ZLASTMESSAGEDATE DESC LIMIT ?""", (limit,)).fetchall()
    return [{"id": r["id"], "name": (r["name"] or "someone").strip(), "unread": max(1, r["unread"]), "group": r["type"] == 1}
            for r in rows]


def messages(chat_id: int, count: int = 3, from_others_only: bool = True) -> list:
    """The latest messages of a chat, oldest first: [{"who", "text", "when"}]. `who` is empty in one-to-one chats."""
    with _connect() as db:
        rows = db.execute(
            f"""SELECT m.ZTEXT AS text, m.ZMESSAGETYPE AS type, m.ZISFROMME AS mine, m.ZMESSAGEDATE AS date,
                       m.ZPUSHNAME AS push, g.ZCONTACTNAME AS member
                FROM ZWAMESSAGE m LEFT JOIN ZWAGROUPMEMBER g ON g.Z_PK = m.ZGROUPMEMBER
                WHERE m.ZCHATSESSION = ? {"AND m.ZISFROMME = 0" if from_others_only else ""}
                  AND m.ZMESSAGETYPE NOT IN (6, 10, 46, 59, 66)
                ORDER BY m.ZSORT DESC, m.ZMESSAGEDATE DESC LIMIT ?""", (chat_id, count)).fetchall()
        is_group = db.execute("SELECT ZSESSIONTYPE FROM ZWACHATSESSION WHERE Z_PK = ?", (chat_id,)).fetchone()
    group = bool(is_group and is_group[0] == 1)
    out = [{"who": ((r["member"] or r["push"] or "someone") if group else ""), "text": describe(r["text"], r["type"]),
            "when": _when(r["date"]), "mine": bool(r["mine"])} for r in rows]
    return list(reversed(out))


def find_chat_confidence(spoken_name: str) -> float:
    """How sure find_chat is (0 to 1): 1 for an exact name, lower for a fuzzy guess."""
    wanted = " ".join(re.sub(r"\b(?:the|my|group|chat|with)\b", " ", (spoken_name or "").lower()).split())
    if not wanted:
        return 0.0
    with _connect() as db:
        rows = db.execute(f"SELECT ZPARTNERNAME FROM ZWACHATSESSION WHERE ZPARTNERNAME IS NOT NULL AND ZSESSIONTYPE IN ({','.join(map(str, CHAT_TYPES))}) AND COALESCE(ZREMOVED, 0) = 0").fetchall()
    best = 0.0
    for (raw,) in rows:
        name = " ".join((raw or "").lower().split())
        if name:
            best = max(best, 1.0 if name == wanted else 0.92 if wanted in name.split() or name.startswith(wanted)
                       else 0.85 if wanted in name else difflib.SequenceMatcher(None, wanted, name).ratio())
    return best


def find_chat(spoken_name: str):
    """The chat that best matches a spoken name ("dana", "mom", "the family group"), or None."""
    wanted = re.sub(r"\b(?:the|my|group|chat|with)\b", " ", (spoken_name or "").lower())
    wanted = " ".join(wanted.split())
    if not wanted:
        return None
    with _connect() as db:
        rows = db.execute(
            f"""SELECT Z_PK AS id, ZPARTNERNAME AS name, ZSESSIONTYPE AS type FROM ZWACHATSESSION
                WHERE ZPARTNERNAME IS NOT NULL AND ZSESSIONTYPE IN ({",".join(map(str, CHAT_TYPES))}) AND COALESCE(ZREMOVED, 0) = 0
                ORDER BY ZLASTMESSAGEDATE DESC""").fetchall()  # most recent first, so ties go to the chat you use most
    best, best_score = None, 0.0
    for r in rows:
        name = " ".join((r["name"] or "").lower().split())
        if not name:
            continue
        score = (1.0 if name == wanted else 0.92 if wanted in name.split() or name.startswith(wanted)
                 else 0.85 if wanted in name else difflib.SequenceMatcher(None, wanted, name).ratio())
        if score > best_score:
            best, best_score = r, score
    if best is not None and best_score >= 0.62:
        return {"id": best["id"], "name": best["name"].strip(), "group": best["type"] == 1}
    return None


def refresh(wait: float = 12.0) -> bool:
    """WhatsApp only updates its data while it runs. If it is closed, start it hidden in the background and wait a few
    seconds for it to catch up. Returns True if it had to be started."""
    import subprocess
    if is_running() or not osal.IS_MAC:
        return False
    path = database_path()
    before = max((os.path.getmtime(p) for p in (path, path + "-wal") if path and os.path.exists(p)), default=0)
    try:
        subprocess.run(["open", "-g", "-j", "-a", "WhatsApp"], capture_output=True, timeout=10)  # background + hidden
    except (subprocess.SubprocessError, OSError):
        return False
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1)
        now = max((os.path.getmtime(p) for p in (path, path + "-wal") if os.path.exists(p)), default=0)
        if now > before:
            time.sleep(2)  # let it finish writing what it just received
            break
    return True


def status() -> tuple:
    """(ok, reason). Why reading isn't possible right now, in words for the user."""
    if not osal.IS_MAC:
        return False, "Reading WhatsApp only works on a Mac for now."
    if not enabled():
        return False, "WhatsApp reading is turned off in the settings."
    if not database_path():
        return False, "I can't find WhatsApp on this Mac. Is the WhatsApp desktop app installed?"
    try:
        with _connect() as db:
            db.execute("SELECT 1 FROM ZWACHATSESSION LIMIT 1")
    except (sqlite3.Error, OSError) as e:
        if "unable to open" in str(e).lower() or "not permitted" in str(e).lower() or "authorization" in str(e).lower():
            return False, ("macOS is blocking me from WhatsApp's data. Open System Settings, Privacy and Security, "
                           "Full Disk Access, and allow the app that runs Jervis (Terminal or VS Code).")
        return False, "I couldn't open WhatsApp's data right now. Try again in a moment."
    return True, ""


# ---------- what Jervis says ----------
def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _stale_note() -> str:
    """WhatsApp only refreshes its data while the app is open; say so if what we read may be old."""
    age = data_age_minutes()
    if age is None:
        return ""
    ago = f"{age // 60} hours" if age >= 90 else f"{age} minutes"
    if not is_running() and age >= 2:
        return f" (WhatsApp is closed on this Mac, so this is only what it had {ago} ago. Open WhatsApp to update it.)"
    if age >= 30:
        return f" (That is as of {ago} ago.)"
    return ""


def _label(chat: dict) -> str:
    return f"in {chat['name']}" if chat["group"] else f"from {chat['name']}"


def unread_summary() -> str:
    chats = unread_chats()
    if not chats:
        return "You have no unread messages on WhatsApp." + _stale_note()
    total = sum(c["unread"] for c in chats)
    parts = [f"{c['unread']} {_label(c)}" for c in chats[:4]]
    more = len(chats) - 4
    listing = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    if more > 0:
        listing += f", and {_plural(more, 'more chat')}"
    return f"You have {_plural(total, 'unread message')} on WhatsApp: {listing}. Say read them to hear them." + _stale_note()


def _line(chat: dict, items: list) -> str:
    said = " ".join(f"{i['who'] + ': ' if i['who'] else ''}{i['text']}" for i in items)
    return f"{chat['name']}: {said}"


def read_unread(max_chats: int = 3, per_chat: int = 3) -> str:
    chats = unread_chats(max_chats)
    if not chats:
        return "You have no unread messages on WhatsApp." + _stale_note()
    lines = []
    for chat in chats:
        items = messages(chat["id"], min(chat["unread"], per_chat))
        if items:
            lines.append(_line(chat, items))
    return "\n".join(lines) + _stale_note() if lines else "I couldn't read those messages."


def read_from(spoken_name: str, count: int = 3) -> str:
    chat = find_chat(spoken_name)
    if not chat:
        return f"I couldn't find a WhatsApp chat called {spoken_name}."
    items = messages(chat["id"], count)
    if not items:
        return f"There are no messages from {chat['name']} to read."
    latest = items[-1]["when"]
    when = f" at {latest.strftime('%I:%M %p').lstrip('0')}" if latest else ""
    return f"{_line(chat, items)}\n(latest{when})" + _stale_note()
