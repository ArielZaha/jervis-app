"""Write where the cursor is: "write me a story about a secret island" with the cursor in a document, an email, a
chat box or a code editor — Jervis writes it and types it in right there, then reads the field back to check it's
really there.

    request -> TARGET (the window the user is working in, remembered at once, and its focused text control)
            -> WRITE  (the local AI writes exactly the text asked for: no preamble, no Markdown unless it's code)
            -> INSERT (bring that window back — the app restores its own caret — check the focused control is still
                       an editable, non-password text control; type short text, paste long text or code, then put
                       the user's clipboard back)
            -> VERIFY (read the control's text back through UI Automation: the inserted text must be there)

When is a request "write it here" rather than "show me"? An explicit "here" / "where my cursor is" / "in this field"
always is. A plain "write me a story" is only when an editable text control of another app has the keyboard focus —
spoken while working in a document. Typed into Jervis's own window, it's a chat answer as before.

Typing goes through the same computer-control task as everything else (app.py: start_computer_task with scripted
steps), so it respects the permission setting, shows the overlay, and Stop works.
"""
import re
import time
from dataclasses import dataclass

import documents

EXPLICIT = re.compile(
    r"\b(?:write|type|put|paste|insert|enter|fill in|draft|compose)\b.*?\b(?:(?:right )?here|in(?:to)? (?:this|the "
    r"(?:current|open|selected)) (?:field|box|text ?box|document|doc|page|window|chat|email|message|editor|file|form|"
    r"cell)|where (?:my|the) (?:cursor|caret|mouse) is|at (?:my|the) (?:cursor|caret)|for me in (?:this|the) "
    r"(?:field|box|document|editor))\b", re.I)
OWN_PROCESSES = {"jervis.exe", "electron.exe", "jervis-backend.exe"}
EDITABLE_TYPES = {"EditControl", "DocumentControl", "ComboBoxControl", "CustomControl", "PaneControl",
                  "GroupControl", "TextControl"}
PASTE_OVER = 280          # characters: longer text (or any code) is pasted, not typed key by key
# Apps whose window is mostly a place to type: with Jervis's own window just woken in front of one, a spoken "write me
# a story" is meant for it (the caret is restored when it comes back to the front, and checked then).
TEXT_APPS = {"notepad", "wordpad", "winword", "code", "notepad++", "sublime_text", "onenote", "outlook", "obsidian",
             "typora", "soffice", "swriter", "pycharm64", "idea64", "devenv", "notion", "joplin", "word"}
CODE_APPS = re.compile(r"\b(?:code|visual studio|pycharm|intellij|notepad\+\+|sublime|vim|cursor|android studio|"
                       r"rider|webstorm|jupyter|terminal|powershell|cmd)\b", re.I)


@dataclass
class Target:
    hwnd: int
    app: str = ""            # process name without .exe ("notepad", "winword", "chrome")
    title: str = ""          # the window's title ("Untitled - Notepad", "Inbox - Outlook")
    control: str = ""        # the focused control's type, when it could be read at request time
    editable: object = False  # True: an editable text control had the focus; None: probably (a text app behind
                              # Jervis's window — checked once it's back in front); False: no
    password: bool = False


# An instruction to produce text ("write me...", "can you type...", "I need you to draft..."), not a sentence that only
# mentions writing ("what did you write?", "I wrote it yesterday").
_INSTRUCTION = re.compile(
    r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis)[,!]?\s+)?(?:(?:please|now|and|also|then|ok|okay|so)[,]?\s+)*"
    r"(?:(?:can|could|would|will) you\s+(?:please\s+)?|i (?:want|need) you to\s+|i'?d like you to\s+|go ahead and\s+)?"
    r"(?:write|type|draft|compose|jot down|make (?:me )?(?:a|an) (?:short |long |"
    r"quick )?(?:story|poem|essay|letter|list|summary|report|note|speech|email|article|message|reply))\b", re.I)
# ("put", "paste", "insert" only count with an explicit place — EXPLICIT: "put a palm tree next to the house" is
# about Blender, not text.)


def is_write_request(text: str) -> bool:
    return bool(_INSTRUCTION.search(" ".join((text or "").split())))


def wants_here(text: str, target, spoken: bool = True) -> bool:
    """Should this request be typed where the user's cursor is? (Typed into Jervis's own window, a plain "write me
    a story" is a chat answer; spoken while working in a text app, it's meant for that app.)"""
    if not text or documents.detect_app(text.lower()):
        return False   # an app named ("in Word", "in Google Docs"): the document handlers make a new document
    if target is None or target.password:
        return False
    if EXPLICIT.search(text):
        return True
    if not is_write_request(text):
        return False
    return target.editable is True or (target.editable is None and spoken)


def writing_prompt(target) -> str:
    where = f" They are typing in {target.app or 'an app'} (window: “{(target.title or '')[:80]}”)." if target else ""
    code = bool(target and CODE_APPS.search(f"{target.app} {target.title}"))
    return ("You write text that will be typed straight into the user's document, exactly where their cursor is."
            f"{where} Write exactly what they asked for and nothing else: no greeting, no 'Here is...', no notes "
            "after it, no title unless they asked for one, and no Markdown symbols (#, **, -) unless it's code. "
            + ("They are in a code editor: if they ask for code, write only the code, with comments where useful, and "
               "no ``` fences. " if code else "")
            + "Use plain paragraphs separated by one blank line. Write in the language of the request.")


def clean(text: str) -> str:
    """The AI's answer as it should land in the document: no code fences, no 'Here is your story:' lead-in."""
    body = (text or "").strip()
    body = re.sub(r"^```[\w+-]*\s*\n?|\n?```\s*$", "", body).strip()
    body = re.sub(r"^(?:sure[,!.]?\s*|of course[,!.]?\s*|certainly[,!.]?\s*)?(?:here(?:'s| is)[^\n:]{0,80}:\s*\n+)",
                  "", body, flags=re.I).strip()
    return body.replace("\r\n", "\n")


def _normal(text: str) -> str:
    return " ".join((text or "").replace(" ", " ").split()).lower()


def landed(before, after, body: str):
    """Did `body` really land in the control? True / False, or None when the control's text can't be read."""
    if after is None:
        return None
    tail = _normal(body)[-60:]
    head = _normal(body)[:40]
    now = _normal(after)
    return bool(tail and tail in now and head in now and len(now) >= len(_normal(before or "")))


# ---------- Windows ----------

def find_target():
    """The window the user is working in right now (not Jervis's own) and what has its keyboard focus. None when
    there's no such window (or this isn't Windows)."""
    try:
        import winctl
        if not winctl.IS_WIN:
            return None
        front = winctl.foreground_window()
        hwnd = front if front and winctl.window_process_name(front) not in OWN_PROCESSES else None
        if hwnd is None:   # Jervis's own window is in front (just woken): the window right behind it
            for h, _title in winctl.list_windows():
                if winctl.window_process_name(h) not in OWN_PROCESSES:
                    hwnd = h
                    break
        if not hwnd:
            return None
        target = Target(hwnd=hwnd, app=(winctl.window_process_name(hwnd) or "").removesuffix(".exe"),
                        title=dict(winctl.list_windows()).get(hwnd, ""))
        if hwnd == front:   # the focus is only readable in the window that's in front
            control = _focused_control()
            if control is not None:
                target.control = control.ControlTypeName
                target.password = bool(getattr(control.Element, "CurrentIsPassword", False))
                target.editable = _editable(control)
        elif target.app.lower() in TEXT_APPS:
            target.editable = None
        return target
    except Exception as e:
        print(f"Couldn't read where the cursor is: {e}", flush=True)
        return None


def _focused_control():
    import screen_windows
    screen_windows._ensure_com()
    import uiautomation as auto
    try:
        return auto.GetFocusedControl()
    except Exception:
        return None


def _editable(control) -> bool:
    import uiautomation as auto
    if control is None or control.ControlTypeName not in EDITABLE_TYPES:
        return False
    try:
        value = control.GetPattern(auto.PatternId.ValuePattern)
        if value is not None:
            return not value.IsReadOnly
        return control.GetPattern(auto.PatternId.TextPattern) is not None and control.ControlTypeName in (
            "DocumentControl", "EditControl")
    except Exception:
        return False


def _read(control):
    """The control's whole text, or None if it can't be read."""
    import uiautomation as auto
    try:
        text = control.GetPattern(auto.PatternId.TextPattern)
        if text is not None:
            return text.DocumentRange.GetText(-1)
    except Exception:
        pass
    try:
        value = control.GetPattern(auto.PatternId.ValuePattern)
        if value is not None:
            return value.Value
    except Exception:
        pass
    return None


def insert(target, body: str) -> str:
    """Put `body` where the cursor is in the target window, and check it. Returns what to tell the user; raises
    RuntimeError (in plain words) when it can't safely type there."""
    import osal
    import winctl
    if not winctl.focus(target.hwnd):
        raise RuntimeError(f"I couldn't bring “{target.title or target.app}” back to the front, so I didn't type "
                           "anything.")
    time.sleep(0.35)   # the app puts its own caret back where it was
    control = _focused_control()
    if control is None or not _editable(control):
        raise RuntimeError("Your cursor isn't in a text field I can type into any more, so I didn't type anything. "
                           "Click where you want it and ask again.")
    if bool(getattr(control.Element, "CurrentIsPassword", False)):
        raise RuntimeError("That's a password field — I never type into those.")
    before = _read(control)
    code = bool(CODE_APPS.search(f"{target.app} {target.title}"))
    if len(body) > PASTE_OVER or code or "\n" in body:
        # Pasting keeps code and paragraphs exactly as written (typing them, an editor auto-indents and closes
        # brackets by itself), and is instant. The user's own clipboard is put back afterwards.
        saved = osal.get_clipboard() if hasattr(osal, "get_clipboard") else None
        osal.set_clipboard(body.replace("\n", "\r\n"))
        time.sleep(0.1)
        winctl.press("ctrl", "v", strict=True)
        time.sleep(0.4)
        if saved is not None:
            osal.set_clipboard(saved)
    else:
        winctl.type_text(body, strict=True)
    time.sleep(0.3)
    after = _read(_focused_control() or control)
    ok = landed(before, after, body)
    words = len(body.split())
    where = target.title or target.app or "the window you're in"
    if ok is True:
        return f"Done — I wrote it where your cursor is in “{where[:60]}” ({words} words), and checked it's there."
    if ok is None:
        return (f"I typed it where your cursor is in “{where[:60]}” ({words} words). That app doesn't let me read "
                "its text back, so I couldn't double-check it.")
    raise RuntimeError("I typed it, but when I read the field back the text wasn't there — the app may have "
                       "blocked it. Nothing else was changed.")
