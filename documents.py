"""Put written text into a new document: Microsoft Word, Pages, TextEdit, Notes or Google Docs."""
import html
import os
import platform
import re
import subprocess

import google_accounts
import osal
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

APP_NAMES = {
    "word": "Word", "pages": "Pages", "textedit": "Notepad" if osal.IS_WIN else "TextEdit", "notes": "Notes",
    "gdocs": "Google Docs",
}
DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents")  # where Notepad files go on Windows

_WRITE = re.compile(
    r"\b(write|type|draft|compose|generate|jot down)\b|"
    r"\bmake (?:me )?(?:a|an) (?:short |long |quick )?(?:story|poem|essay|letter|list|summary|report|note|speech|email|article)\b"
)
_APPS = [
    ("gdocs", re.compile(r"\bgoogle (?:docs?|documents?|drive)\b|\b(?:in|into|on|open|to) (?:the )?docs\b")),
    ("word", re.compile(r"\bmicrosoft(?: office)? word\b|\bms word\b|\bword (?:document|doc|app)\b|"
                        r"\b(?:in|into|on|using|with|open|launch) (?:the )?word\b")),
    ("pages", re.compile(r"\bapple pages\b|\b(?:in|into|open|using|on) pages\b")),
    ("textedit", re.compile(r"\btext ?edit\b|\bnotepad\b|\btext editor\b")),
    ("notes", re.compile(r"\bnotes app\b|\b(?:in|into|open|using|to|on) (?:the |my )?notes\b")),
]

_WORD = '''on run argv
    set docText to item 1 of argv
    tell application "Microsoft Word"
        activate
        set newDoc to make new document
        set content of text object of newDoc to docText
        return name of newDoc
    end tell
end run'''
_PAGES = '''on run argv
    set docText to item 1 of argv
    tell application "Pages"
        activate
        set d to make new document
        set body text of d to docText
        return name of d
    end tell
end run'''
_TEXTEDIT = '''on run argv
    set docText to item 1 of argv
    tell application "TextEdit"
        activate
        set d to make new document with properties {text:docText}
        return name of d
    end tell
end run'''
_NOTES = '''on run argv
    set noteTitle to item 1 of argv
    set noteBody to item 2 of argv
    tell application "Notes"
        activate
        set n to make new note with properties {name:noteTitle, body:noteBody}
        return id of n
    end tell
end run'''


_WORD_UPDATE = '''on run argv
    set docName to item 1 of argv
    set docText to item 2 of argv
    tell application "Microsoft Word"
        activate
        set content of text object of document docName to docText
    end tell
end run'''
_PAGES_UPDATE = '''on run argv
    set docName to item 1 of argv
    set docText to item 2 of argv
    tell application "Pages"
        activate
        set body text of document docName to docText
    end tell
end run'''
_TEXTEDIT_UPDATE = '''on run argv
    set docName to item 1 of argv
    set docText to item 2 of argv
    tell application "TextEdit"
        activate
        set text of document docName to docText
    end tell
end run'''
_NOTES_UPDATE = '''on run argv
    set noteId to item 1 of argv
    set noteBody to item 2 of argv
    tell application "Notes"
        activate
        set body of (first note whose id is noteId) to noteBody
    end tell
end run'''
_GDOCS_REPLACE = '''tell application "Google Chrome" to activate
delay 0.4
tell application "System Events"
    keystroke "a" using command down
    delay 0.2
    keystroke "v" using command down
end tell'''


def detect_app(text: str):
    """Which document app the sentence names ("in Word", "Google Drive document", "Pages"), or None."""
    n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    for key, pattern in _APPS:
        if pattern.search(n):
            return key
    return None


_BLANK_VERBS = re.compile(r"\b(open|create|make|start|new|begin|launch)\b")
_DOC_NOUN = re.compile(r"\b(document|documents|doc|file|blank page|new page)\b")  # not "docs": "open Google Docs" just opens the site
_TRANSFER_VERBS = re.compile(r"\b(put|save|copy|paste|add|insert|write|type|send|export|move|place|drop)\b")
_TRANSFER_THING = re.compile(
    r"\b(this|that|these|those|it|the list|this list|that list|the answer|the response|the reply|the text|"
    r"the above|what you said|what you just said|your answer|your last answer)\b")


def is_blank_request(text: str) -> bool:
    """"Open a document on Google Drive" / "create a new Word document": a blank document, nothing to write."""
    n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    return bool(_BLANK_VERBS.search(n) and _DOC_NOUN.search(n) and detect_app(n)
                and not _WRITE.search(n) and not _TRANSFER_VERBS.search(n.replace("open", "")))


def is_transfer_request(text: str) -> bool:
    """"Put this list in a Google Doc", "save that in Word": move the last answer into a document."""
    n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    return bool(_TRANSFER_VERBS.search(n) and _TRANSFER_THING.search(n) and (detect_app(n) or _DOC_NOUN.search(n)))


def create_blank(app_key: str, context: str = "") -> str:
    """Open an empty document in the chosen app. Returns a reference like insert() does."""
    if app_key == "notes":
        return insert("notes", "New note", "")
    if app_key == "gdocs":
        google_accounts.open_page("https://docs.google.com/document/create", context)
        return ""
    return insert(app_key, "", "")


def reply_to_document(reply: str):
    """Turn a Markdown chat reply into (title, plain-text body) for a document."""
    lines = [ln.rstrip() for ln in (reply or "").strip().splitlines()]
    out = []
    for ln in lines:
        if re.fullmatch(r"\s*\|?[\s:|-]+\|[\s:|-]*", ln) and "-" in ln:
            continue  # table separator row
        if ln.strip().startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            ln = " - ".join(c for c in cells if c)
        ln = re.sub(r"^\s*[-*\u2022]\s+", "\u2022 ", ln)
        ln = re.sub(r"^#{1,6}\s*", "", ln)
        ln = re.sub(r"\*\*|__|`|~~", "", ln)
        ln = re.sub(r"(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", ln)
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    if len(out) > 2 and out[-1].strip().endswith("?") and not out[-1].lstrip().startswith("\u2022"):
        out.pop()  # the chat's closing follow-up question does not belong in the document
    text = "\n".join(out).strip()
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "Notes")
    if len(text.splitlines()) > 1 and len(first) <= 70 and not first.startswith("\u2022") and not re.match(r"\d+[.)]\s", first):
        title = first.rstrip(":.!")
        body = "\n".join(text.splitlines()[1:]).strip()
    else:
        title, body = "Notes", text
    return title, body or text


def detect_request(text: str):
    """Return the app key when the sentence asks to write something into a document app, else None."""
    n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    if not _WRITE.search(n):
        return None
    for key, pattern in _APPS:
        if pattern.search(n):
            return key
    return None


def split_title(text: str):
    """The generated text starts with a title line. Returns (title, body)."""
    lines = (text or "").strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return "Untitled", ""
    title = re.sub(r"^[#*\s]+|[*\s]+$", "", lines[0]).strip()[:80] or "Untitled"
    body = "\n".join(lines[1:]).strip()
    return title, body or title


def _run(script: str, *args: str) -> str:
    result = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "osascript failed")
    return result.stdout.strip()


_WIN_WORD_CREATE = r"""
$w = New-Object -ComObject Word.Application
$w.Visible = $true
$d = $w.Documents.Add()
$d.Content.Text = $env:JERVIS_TEXT
$w.Activate()
$d.Name
"""
_WIN_WORD_UPDATE = r"""
$w = [Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application')
$d = $w.Documents.Item($env:JERVIS_REF)
$d.Content.Text = $env:JERVIS_TEXT
$w.Activate()
"""


def _win_word(script: str, text: str, ref: str = "") -> str:
    code, out, err = osal.run_powershell(script, {"JERVIS_TEXT": text, "JERVIS_REF": ref}, timeout=90)
    if code != 0:
        if "80040154" in err or "class not registered" in err.lower():
            raise RuntimeError("Microsoft Word isn't installed on this PC.")
        raise RuntimeError(err.splitlines()[0] if err else "Word could not be controlled.")
    return out


def _win_notepad_file(title: str) -> str:
    os.makedirs(DOCS_DIR, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|]+', " ", title).strip()[:50] or "Jervis note"
    path = os.path.join(DOCS_DIR, f"{name}.txt")
    n = 2
    while os.path.exists(path):
        path = os.path.join(DOCS_DIR, f"{name} {n}.txt")
        n += 1
    return path


def _notes_html(title: str, body: str) -> str:
    paragraphs = "".join(f"<div>{html.escape(line) or '<br>'}</div>" for line in body.splitlines())
    return f"<div><h1>{html.escape(title)}</h1></div>{paragraphs}"


def insert(app_key: str, title: str, body: str, context: str = "") -> str:
    """Create the document and return a reference to it (used later to edit it). Raises RuntimeError on failure."""
    if platform.system() not in ("Darwin", "Windows"):
        raise RuntimeError("Writing into documents only works on macOS and Windows for now.")
    full = f"{title}\n\n{body}"
    if osal.IS_WIN:
        if app_key == "word":
            return _win_word(_WIN_WORD_CREATE, full.replace("\n", "\r"))
        if app_key == "textedit":
            path = _win_notepad_file(title)
            with open(path, "w", encoding="utf-8-sig") as f:  # the BOM lets Notepad show Hebrew and other scripts
                f.write(full)
            os.startfile(path)  # type: ignore[attr-defined]
            return path
        if app_key in ("pages", "notes"):
            raise RuntimeError(f"{APP_NAMES[app_key]} is a Mac app. Try Word, Notepad or Google Docs.")
    if app_key == "word":
        return _run(_WORD, full.replace("\n", "\r"))
    if app_key == "pages":
        return _run(_PAGES, full.replace("\n", "\r"))
    if app_key == "textedit":
        return _run(_TEXTEDIT, full)
    if app_key == "notes":
        return _run(_NOTES, title, _notes_html(title, body))
    if app_key == "gdocs":
        # Google prefills a new document from these URL parameters. The text is also copied, as a fallback.
        osal.set_clipboard(full)
        google_accounts.open_page(f"https://docs.google.com/document/create?title={quote(title)}&body={quote(body)}",
                                  context or f"{title} {body[:200]}")
        return ""
    raise RuntimeError(f"I don't know how to write into {app_key}.")


def update(app_key: str, ref: str, title: str, body: str) -> str:
    """Replace the text of the document created earlier. Raises RuntimeError if it can't be reached."""
    full = f"{title}\n\n{body}"
    if osal.IS_WIN and app_key == "word":
        _win_word(_WIN_WORD_UPDATE, full.replace("\n", "\r"), ref)
    elif osal.IS_WIN and app_key == "textedit":
        with open(ref, "w", encoding="utf-8-sig") as f:
            f.write(full)
        os.startfile(ref)  # type: ignore[attr-defined]
    elif osal.IS_WIN and app_key in ("pages", "notes"):
        raise RuntimeError(f"{APP_NAMES[app_key]} is a Mac app.")
    elif app_key == "word":
        _run(_WORD_UPDATE, ref, full.replace("\n", "\r"))
    elif app_key == "pages":
        _run(_PAGES_UPDATE, ref, full.replace("\n", "\r"))
    elif app_key == "textedit":
        _run(_TEXTEDIT_UPDATE, ref, full)
    elif app_key == "notes":
        _run(_NOTES_UPDATE, ref, _notes_html(title, body))
    elif app_key == "gdocs":
        # Google Docs has no scripting interface: focus its tab and paste over the whole document body.
        from youtube_browser import focus_tab
        osal.set_clipboard(body)
        if not focus_tab("docs.google.com/document"):
            raise RuntimeError("I couldn't find the Google Doc tab. The new text is on your clipboard.")
        try:
            if osal.IS_WIN:
                import winctl
                winctl.press("ctrl", "a")
                winctl.press("ctrl", "v")
            else:
                _run(_GDOCS_REPLACE)
        except RuntimeError:
            raise RuntimeError("I couldn't type into Google Docs (macOS needs Accessibility permission for this). "
                               "The new text is on your clipboard: click into the document, select all, then paste.")
    else:
        raise RuntimeError(f"I don't know how to edit {app_key}.")
    return APP_NAMES[app_key]


_EDIT_VERBS = re.compile(
    r"\b(make|change|edit|shorten|lengthen|extend|add|remove|delete|rewrite|replace|translate|fix|improve|expand|"
    r"continue|update|modify|revise|rephrase|summarize|shorter|longer|correct|append|insert|cut|trim)\b")
_EDIT_TARGETS = re.compile(
    r"\b(it|this|that|story|poem|document|doc|text|letter|essay|note|title|paragraph|paragraphs|ending|beginning|"
    r"intro|introduction|conclusion|sentence|sentences|list|email|speech|article|report|grammar|spelling|wording|"
    r"tone|content|words|everything)\b")
_NOT_AN_EDIT = re.compile(r"\b(music|song|songs|video|volume|sound|episode|season|netflix|youtube|stremio|spotify|tab|window)\b")


def is_edit_request(text: str) -> bool:
    """"Make the story shorter", "add a paragraph about a dragon", "change the title to X" (needs a document in play)."""
    n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    return bool(_EDIT_VERBS.search(n) and _EDIT_TARGETS.search(n) and not _NOT_AN_EDIT.search(n))
