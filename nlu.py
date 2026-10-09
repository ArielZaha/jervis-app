"""Language understanding: what the user means, as a structured intent — kept separate from doing it.

    utterance -> rewrite()      deterministic, instant: Hebrew / mixed Hebrew-English commands and speech-recognition
                                slips become the canonical English command Jervis's handlers already understand
              -> (the existing deterministic handlers in app.py execute and verify)
              -> understand()   only when nothing handled it and it looks like it could be a command (or it's Hebrew):
                                the local model returns ONE intent from a closed list, with slots, a confidence and
                                whether it needs to ask — as JSON that is validated here
              -> render()       the validated intent becomes a canonical English command, which goes back through the
                                SAME deterministic handlers (they do the action and check it worked)

The model never executes anything and never writes code here: an intent is a suggestion that has to survive validation
and the handlers' own checks. Unclear requests become a clarification question instead of a guess.
"""
import difflib
import json
import os
import re

# ---------------------------------------------------------------- Hebrew vocabulary

APPS_HE = {
    "בלנדר": "Blender", "ספוטיפיי": "Spotify", "ספוטיפי": "Spotify", "ספוטיפאי": "Spotify", "כרום": "Chrome",
    "גוגל כרום": "Chrome", "יוטיוב": "YouTube", "נטפליקס": "Netflix", "וורד": "Word",
    "אקסל": "Excel", "פאוורפוינט": "PowerPoint", "נוטפד": "Notepad", "פנקס רשימות": "Notepad",
    "מחשבון": "Calculator", "הגדרות": "Settings", "סייר הקבצים": "File Explorer", "סייר קבצים": "File Explorer",
    "וואטסאפ": "WhatsApp", "ווטסאפ": "WhatsApp", "דיסקורד": "Discord", "סטרימיו": "Stremio",
    "מיינקראפט": "Minecraft", "מיינקרפט": "Minecraft", "פוטושופ": "Photoshop", "זום": "Zoom", "טימס": "Teams",
    "אאוטלוק": "Outlook", "סטים": "Steam", "גוגל": "Google", "ויזואל סטודיו קוד": "VS Code", "טלגרם": "Telegram",
    "אדג'": "Edge", "פיירפוקס": "Firefox", "ג'ימייל": "Gmail", "קליפ סטודיו": "Clip Studio", "יומן": "Calendar",
}
SHAPES_HE = {"קובייה": "cube", "קוביה": "cube", "קופסה": "cube", "כדור": "sphere", "גליל": "cylinder",
             "חרוט": "cone", "מישור": "plane", "טורוס": "torus", "סופגניה": "torus", "קוף": "monkey"}
ORDINALS_HE = {"ראשונה": "first", "ראשון": "first", "שנייה": "second", "שניה": "second", "שני": "second",
               "שלישית": "third", "שלישי": "third", "רביעית": "fourth", "רביעי": "fourth", "אחרונה": "last",
               "אחרון": "last"}
NUMBERS_HE = {"שתיים": "two", "שניים": "two", "שתי": "two", "שני": "two", "שלוש": "three", "שלושה": "three",
              "ארבע": "four", "ארבעה": "four", "חמש": "five", "חמישה": "five", "עשר": "ten", "חצי": "half"}
SIZES_HE = {"גבוה": "taller", "גבוהה": "taller", "גבוהים": "taller", "נמוך": "shorter", "נמוכה": "shorter",
            "גדול": "bigger", "גדולה": "bigger", "גדולים": "bigger", "קטן": "smaller", "קטנה": "smaller",
            "קטנים": "smaller", "רחב": "wider", "רחבה": "wider", "צר": "narrower", "צרה": "narrower",
            "ארוך": "taller", "ארוכה": "taller", "עבה": "fatter", "דק": "thinner", "דקה": "thinner"}
COLORS_HE = {"אדום": "red", "אדומה": "red", "כחול": "blue", "כחולה": "blue", "ירוק": "green", "ירוקה": "green",
             "צהוב": "yellow", "צהובה": "yellow", "שחור": "black", "שחורה": "black", "לבן": "white", "לבנה": "white",
             "כתום": "orange", "כתומה": "orange", "סגול": "purple", "סגולה": "purple", "ורוד": "pink", "ורודה": "pink",
             "חום": "brown", "חומה": "brown", "אפור": "gray", "אפורה": "gray", "זהב": "gold", "כסף": "silver"}
DIRECTIONS_HE = {"ימינה": "right", "שמאלה": "left", "למעלה": "up", "למטה": "down", "קדימה": "forward",
                 "אחורה": "back"}

_HEBREW = re.compile(r"[֐-׿]")
_NIQQUD = re.compile(r"[֑-ׇ]")


def has_hebrew(text: str) -> bool:
    return bool(_HEBREW.search(text or ""))


def _clean(text: str) -> str:
    t = _NIQQUD.sub("", text or "")
    t = re.sub(r"(?<=\S)-(?=\S)", " ", t)              # "ה-cube" -> "ה cube"
    t = re.sub(r"[?!.,;:\"״׳]", " ", t)
    t = re.sub(r"(?<!\S)([הלב])\s+(?=[A-Za-z])", r"\1", t)   # "ה cube" -> "הcube": one word, prefix and all
    return " ".join(t.split())


def _strip_prefix(word: str) -> str:
    """Drop Hebrew one-letter prefixes (ה the, ל to, ב in, ו and) from a word that isn't known as it stands."""
    for _ in range(2):
        if word in APPS_HE or word in SHAPES_HE or word in ORDINALS_HE or not word or not _HEBREW.match(word[0]):
            break
        if word[0] in "הלבו" and len(word) > 2:
            word = word[1:]
        else:
            break
    return word


def _app(phrase: str):
    """An app name said in Hebrew or English ("בלנדר", "ה-Blender", "Spotify") -> its English name, or None."""
    p = " ".join(phrase.split()).strip()
    if not p:
        return None
    if p in APPS_HE:
        return APPS_HE[p]
    stripped = " ".join(_strip_prefix(w) for w in p.split())
    if stripped in APPS_HE:
        return APPS_HE[stripped]
    if not has_hebrew(p):
        return p
    english = re.sub(r"^[הלב]\s*", "", p)
    if english and not has_hebrew(english):
        return english
    return None


def _object(phrase: str):
    """A reference to a 3D object ("אותה", "את הקובייה השנייה", "ה cube", "it") -> English ("it", "the second cube")."""
    words = [w for w in phrase.split() if w not in ("את", "של")]
    if not words:
        return None
    if words[0] in ("אותה", "אותו", "זה", "זאת", "it", "that"):
        return "it"
    if words[0] in ("אותם", "אותן"):
        return "them"
    shape, ordinal = None, None
    for w in words:
        base = _strip_prefix(w)
        if base in SHAPES_HE:
            shape = SHAPES_HE[base]
        elif base.lower() in ("cube", "sphere", "ball", "cylinder", "cone", "plane", "torus", "monkey", "box"):
            shape = base.lower()
        elif base in ORDINALS_HE:
            ordinal = ORDINALS_HE[base]
        elif not has_hebrew(base) and base:
            shape = shape or base.lower()
        elif w not in ("הזה", "הזאת", "הזו", "הזאתי"):
            # a word these rules don't know ("הקובייה האדומה": the red one): leave the whole sentence to the
            # translation, rather than quietly dropping it and moving some other cube
            return None
    if not shape and not ordinal:
        return None
    return "the " + " ".join(x for x in (ordinal, shape or "one") if x)


_V_OPEN = r"(?:תפתח|פתח|תפתחי|תפתחו|פתחי)"
_V_CLOSE = r"(?:תסגור|סגור|תסגרי|תסגרו)"
_V_BACK = r"(?:תחזור|חזור|תחזרי|תעבור|עבור|תעברי)"
_V_CREATE = r"(?:תיצור|צור|תייצר|תיצרי|תוסיף|הוסף|תוסיפי|תבנה|בנה|תבני|תעשה|עשה|תעשי)"
_V_MAKE = r"(?:תעשה|עשה|תעשי|תהפוך|הפוך|תהפכי)"
_V_PAINT = r"(?:תצבע|צבע|תצבעי)"
_V_MOVE = r"(?:תזיז|הזז|תזיזי)"
_V_TURN = r"(?:תסובב|סובב|תסובבי)"
_V_DELETE = r"(?:תמחק|מחק|תמחקי)"
_V_PLAY = r"(?:תפעיל|הפעל|תפעילי|תנגן|נגן|תנגני|תשים|שים|תשימי)"
_OBJ = r"(?:אותה|אותו|אותם|אותן|זה|(?:את\s+)?ה?\S+(?:\s+ה\S+)?)"
_SIZE = "|".join(sorted(SIZES_HE, key=len, reverse=True))
_COLOR = "|".join(sorted(COLORS_HE, key=len, reverse=True))
_DIR = "|".join(DIRECTIONS_HE)
_NUM = "|".join(sorted(NUMBERS_HE, key=len, reverse=True))
_UNITS_HE = {"שניות": "seconds", "שנייה": "second", "שניה": "second", "דקות": "minutes", "דקה": "minute",
             "שעות": "hours", "שעה": "hour"}


def _times(word: str):
    if not word:
        return None
    return NUMBERS_HE.get(word, word if re.fullmatch(r"\d+(?:\.\d+)?", word) else None)


def rewrite_hebrew(text: str):
    """A Hebrew (or mixed) command -> the canonical English command, for the common command families; None when
    it isn't one of them (then the language model may still understand it)."""
    t = _clean(latin_names(text))
    if not has_hebrew(t):
        return None
    # "Jervis, תפתח בלנדר" / "בבקשה תפתח בלנדר": the address and the politeness aren't part of the command
    t = re.sub(r"^(?:(?:hey|hi|ok|okay)\s+)?(?:jervis|jarvis)\s+", "", t, flags=re.I)
    t = re.sub(r"^(?:בבקשה|אפשר|תוכל|תוכלי|יאללה|טוב|אוקיי|עכשיו)\s+", "", t)
    t = re.sub(r"\s+(?:בבקשה|תודה)$", "", t)
    # "open Spotify ותפעיל את השיר הזה": English part + Hebrew part after "ו"
    m = re.match(r"^(?P<a>.+?)\s+ו(?P<b>" + _V_PLAY[3:-1] + r"|" + _V_OPEN[3:-1] + r"|" + _V_CREATE[3:-1] + r")\s+(?P<rest>.*)$", t)
    if m:
        first = rewrite_hebrew(m.group("a")) or (m.group("a") if not has_hebrew(m.group("a")) else None)
        second = rewrite_hebrew(f"{m.group('b')} {m.group('rest')}")
        if first and second:
            return f"{first} and {second}"
    m = re.fullmatch(r"(?:תבטל|בטל|תבטלי)(?:\s+את\s+(?:זה|הפעולה(?:\s+האחרונה)?|השינוי(?:\s+האחרון)?))?", t)
    if m:
        return "undo"
    if re.fullmatch(r"(?:" + _V_MAKE + r"\s+)?(?:את\s+)?זה\s+(?:שוב|עוד\s+פעם)|שוב|עוד\s+פעם", t):
        return "do it again"
    if re.fullmatch(r"(?:תפסיק|הפסק|תפסיקי)\s+לשלוט\s+(?:ב|על\s+)?ה?מחשב(?:\s+שלי)?|(?:תעזוב|עזוב)\s+את\s+ה?מחשב", t):
        return "stop controlling my computer"
    m = re.fullmatch(r"(?:תשלוט|שלוט|תשלטי|תיקח\s+שליטה|קח\s+שליטה)\s+(?:ב|על\s+)ה?מחשב(?:\s+שלי)?(?:\s+ו(?P<rest>.+))?", t)
    if m:
        rest = m.group("rest")
        if rest:
            tail = rewrite_hebrew(rest)
            return f"take control of my computer and {tail}" if tail else None
        return "take control of my computer"
    if re.fullmatch(r"(?:תעצור|עצור|תעצרי|תפסיק|הפסק|די)", t):
        return "stop"
    if re.fullmatch(r"(?:תשהה|השהה|תעצור|עצור)\s+את\s+ה?(?:שיר|מוזיקה|מוסיקה)", t):
        return "pause the music"
    if re.fullmatch(r"(?:" + _V_PLAY + r"\s+)?(?:את\s+)?ה?שיר\s+ה?בא|(?:תעביר|העבר|דלג|תדלג)(?:\s+(?:ל)?שיר)?(?:\s+ה?בא)?", t):
        return "next song"
    m = re.fullmatch(_V_OPEN + r"\s+(?:את\s+)?(?:ה)?(?P<app>.+)", t)
    if m:
        app = _app(m.group("app"))
        return f"open {app}" if app else None
    m = re.fullmatch(_V_CLOSE + r"\s+(?:את\s+)?(?P<app>.+)", t)
    if m:
        app = _app(m.group("app"))
        return f"close {app}" if app else None
    m = re.fullmatch(_V_BACK + r"\s+(?:ל|אל\s+)\s*(?P<app>.+)", t)
    if m:
        app = _app(m.group("app"))
        if app:
            return "go back to blender" if app.lower() == "blender" else f"open {app}"   # brings it to the front
        return None
    m = re.fullmatch(_V_PLAY + r"\s+(?:את\s+)?(?:ה)?(?:שיר|מוזיקה|מוסיקה)(?:\s+(?:הזה|הזאת))?", t)
    if m:
        return "resume the music"
    m = re.fullmatch(_V_PLAY + r"\s+(?:את\s+)?(?:השיר\s+)?(?P<q>.+?)\s+(?:ב|על\s+)(?:ספוטיפיי|ספוטיפי|spotify)", t)
    if m:
        return f"play {m.group('q')} on Spotify"
    # "תנגן לי את סוזי תזוזי": playing music, the title kept exactly as said (never translated word by word)
    m = re.fullmatch(r"(?:תנגן|נגן|תנגני|תשמיע|השמע|תשמיעי)\s+(?:לי\s+)?(?:את\s+)?(?:ה?שיר\s+)?(?P<q>.+)", t)
    if m and not re.fullmatch(r"(?:ה)?(?:שיר|מוזיקה|מוסיקה)(?:\s+(?:הזה|הזאת))?", m.group("q")):
        return f"play {m.group('q')} on Spotify"
    m = re.fullmatch(r"(?:תכוון|כוון|תשים|שים|תפעיל|הפעל|תעשה)\s+(?:לי\s+)?טיימר\s+(?:ל|של\s+|על\s+)?\s*(?P<n>\S+)\s+(?P<u>"
                     + "|".join(_UNITS_HE) + r")", t)
    if m:
        n = _times(m.group("n")) or m.group("n")
        return f"set a timer for {n} {_UNITS_HE[m.group('u')]}"
    loudness = r"\s+ה?(?:ווליום|עוצמה|עוצמת\s+הקול|קול|סאונד|מוזיקה)"
    if re.fullmatch(r"(?:תגביר|הגבר|תגבירי)(?:\s+את)?(?:" + loudness + ")?", t) or \
            re.fullmatch(r"(?:תעלה|העלה|תעלי)(?:\s+את)?" + loudness, t):      # "raise" needs what: the volume
        return "volume up"
    if re.fullmatch(r"(?:תנמיך|הנמך|תנמיכי)(?:\s+את)?(?:" + loudness + ")?", t) or \
            re.fullmatch(r"(?:תוריד|הורד|תורידי)(?:\s+את)?" + loudness, t):
        return "volume down"
    # 3D objects
    m = re.fullmatch(_V_CREATE + r"\s+(?:לי\s+)?(?P<another>עוד\s+)?(?:(?:אחד|אחת)\s+)?(?P<thing>\S+)(?:\s+(?:עוד|נוספת|נוסף))?", t)
    if m:
        base = _strip_prefix(m.group("thing"))
        shape = SHAPES_HE.get(base) or (base.lower() if base.lower() in ("cube", "sphere", "cylinder", "cone", "plane",
                                                                          "torus", "monkey", "box", "ball") else None)
        if shape:
            return f"create {'another' if m.group('another') else 'a'} {shape}"
        if base in ("אחת", "אחד") and m.group("another"):
            return "create another one"
    m = re.fullmatch(_V_CREATE + r"\s+(?:לי\s+)?עוד\s+(?:אחת|אחד)", t)
    if m:
        return "do it again"
    m = re.fullmatch(_V_MAKE + r"\s+(?P<obj>" + _OBJ + r")\s+(?:פי\s+(?P<n>" + _NUM + r"|\d+(?:\.\d+)?)\s+)?(?:יותר\s+)?"
                     r"(?P<size>" + _SIZE + r")(?:\s+יותר)?(?:\s+פי\s+(?P<n2>" + _NUM + r"|\d+(?:\.\d+)?))?", t)
    if m:
        ref = _object(m.group("obj"))
        n = _times(m.group("n") or m.group("n2"))
        size = SIZES_HE[m.group("size")]
        if ref:
            if n == "half":
                return f"make {ref} half the size"
            return f"make {ref} {n + ' times ' if n else ''}{size}"
    m = re.fullmatch(r"(?:" + _V_MAKE + r"|" + _V_PAINT + r")\s+(?P<obj>" + _OBJ + r")\s+(?:ב|ל|בצבע\s+)?(?P<color>"
                     + _COLOR + r")", t)
    if m:
        ref = _object(m.group("obj"))
        if ref:
            return f"make {ref} {COLORS_HE[m.group('color')]}"
    m = re.fullmatch(_V_MOVE + r"\s+(?P<obj>" + _OBJ + r")\s+(?:ליד|לצד|ל?יד)\s+(?P<target>.+)", t)
    if m:
        ref, target = _object(m.group("obj")), _object(m.group("target"))
        if ref and target:
            return f"move {ref} next to {target}"
    m = re.fullmatch(_V_MOVE + r"\s+(?P<obj>" + _OBJ + r")\s+(?P<dir>" + _DIR + r")", t)
    if m:
        ref = _object(m.group("obj"))
        if ref:
            return f"move {ref} {DIRECTIONS_HE[m.group('dir')]}"
    m = re.fullmatch(_V_TURN + r"\s+(?P<obj>" + _OBJ + r")(?:\s+(?P<deg>\d+)\s+(?:מעלות|מעלה))?", t)
    if m:
        ref = _object(m.group("obj"))
        if ref:
            return f"rotate {ref}" + (f" {m.group('deg')} degrees" if m.group("deg") else "")
    m = re.fullmatch(_V_DELETE + r"\s+(?P<obj>" + _OBJ + r")", t)
    if m:
        ref = _object(m.group("obj"))
        if ref:
            return f"delete {ref}"
    return None


# ---------------------------------------------------------------- speech-recognition slips (English)

_STT_PHRASES = [
    (re.compile(r"\bspot (?:if|a|the|of|e)\s?(?:i|eye|y|fi|fy|ai)\b", re.I), "spotify"),
    (re.compile(r"\bspot if(?:y|i)\b", re.I), "spotify"),
    (re.compile(r"\b(stay|be|keep) (?:in )?control\b(?! (?:of|on|over)\b)", re.I), r"\1 in control of my computer"),
    # "make it bigger" heard as "make it girl/bigga/digger" — only right after make/scale <thing>.
    (re.compile(r"\b((?:make|scale) (?:it|that|this|the \w+(?: \w+)?)) (?:girl|bigga|digger|bigga?r|beaker)\b",
                re.I), r"\1 bigger"),
]


# (Whisper also hears the name as ג'רמיס / ג'רמיז, and people wake him in the feminine too: "קומי")
_JERVIS_HE = re.compile(r"(?<!\w)(?:(?:היי|הי|הֵי|הלו|תתעורר|קום|קומי|תתעוררי)\s+)?[גצ]['׳]?א?ר(?:ב|ו|וו|מ)י[סז](?!\w)")
_GREETING_HE = {"היי": "hey", "הי": "hey", "הֵי": "hey", "הלו": "hello", "תתעורר": "wake up", "קום": "wake up",
                "קומי": "wake up", "תתעוררי": "wake up"}


def latin_names(text: str) -> str:
    """Hebrew speech recognition spells "Jervis" in Hebrew letters (ג'רביס, ג'רוויס): write it in English, with
    the greeting before it, so wake phrases and "Jervis, ..." work whatever language was heard."""
    def fix(m):
        greeting = m.group(0).split()[0] if len(m.group(0).split()) > 1 else ""
        return (_GREETING_HE.get(greeting, "") + " Jervis").strip()
    return _JERVIS_HE.sub(fix, text or "") if has_hebrew(text or "") else (text or "")


def fix_speech(text: str) -> str:
    """Common recognizer slips Jervis has seen that a name-based fix can't catch ("open spot if I")."""
    t = text or ""
    for pattern, fix in _STT_PHRASES:
        t = pattern.sub(fix, t)
    return t


def rewrite(text: str):
    """The canonical command for `text` when a deterministic rule recognises it (Hebrew/mixed, or a known speech
    slip), else None. Instant — no model."""
    hebrew = rewrite_hebrew(text)
    if hebrew:
        return hebrew
    fixed = fix_speech(text)
    return fixed if fixed != (text or "") else None


# ---------------------------------------------------------------- the model's part: a structured intent

INTENTS = {
    "open_app": "open or bring up an application or website (app)",
    "close_app": "close an application (app)",
    "switch_app": "go back / switch to an app that is already open (app)",
    "blender_create": "add a simple shape in Blender (shape: cube/sphere/cylinder/cone/plane/torus/monkey)",
    "blender_build": "build/model something more complex in Blender (description, in English)",
    "object_resize": "make an object bigger/smaller/taller/shorter/wider/narrower (target, change, times)",
    "object_color": "change an object's colour (target, color)",
    "object_move": "move an object in a direction (target, direction) or next to another one (target, next_to)",
    "object_rotate": "rotate an object (target, degrees)",
    "object_delete": "delete an object (target)",
    "undo": "undo the last change", "repeat": "do the last action again",
    "music_play": "play music, a song, artist or playlist (query, service: spotify/youtube; query empty = resume)",
    "music_pause": "pause/stop the music", "music_next": "next song", "music_previous": "previous song",
    "volume": "change the volume (direction: up/down)",
    "timer": "set a timer (duration, in English words like '5 minutes')",
    "web_search": "search the web (query, in the user's words)",
    "control_start": "let Jervis use the mouse and keyboard (goal: what to do, in English, may be empty)",
    "control_stop": "stop Jervis using the computer",
    "screen_task": "do something on screen in the current app (goal, in English)",
    "chat": "a question, conversation or anything that isn't a command for Jervis to do",
    "ignore": "background noise, speech not meant for Jervis, or fragments",
    "clarify": "a command that is genuinely unclear: ask ONE short question (question)",
}
_SLOTS = ("app", "shape", "description", "target", "change", "times", "color", "direction", "next_to", "degrees",
          "query", "service", "duration", "goal", "question")
SCHEMA = {"type": "object", "properties": {
    "intent": {"type": "string", "enum": list(INTENTS)},
    "confidence": {"type": "number"},
    **{slot: {"type": "string"} for slot in _SLOTS}},
    # Every detail is required (empty when it doesn't apply): small models otherwise leave out exactly the detail
    # the command needs ({"intent": "open_app"} with no app).
    "required": ["intent", "confidence", *_SLOTS]}

# The details each intent needs. The compact schema allows, per intent, exactly these (all required): the model
# can't leave out the one detail the command needs, and doesn't spend ~90 tokens (~2 s) writing empty ones.
INTENT_SLOTS = {
    "open_app": ("app",), "close_app": ("app",), "switch_app": ("app",), "blender_create": ("shape",),
    "blender_build": ("description",), "object_resize": ("target", "change", "times"),
    "object_color": ("target", "color"), "object_move": ("target", "direction", "next_to"),
    "object_rotate": ("target", "degrees"), "object_delete": ("target",), "music_play": ("query", "service"),
    "volume": ("direction",), "timer": ("duration",), "web_search": ("query",), "control_start": ("goal",),
    "screen_task": ("goal",), "clarify": ("question",),
}
SCHEMA_COMPACT = {"anyOf": [
    {"type": "object",
     "properties": {"intent": {"type": "string", "enum": [name]}, "confidence": {"type": "number"},
                    **{slot: {"type": "string"} for slot in INTENT_SLOTS.get(name, ())}},
     "required": ["intent", "confidence", *INTENT_SLOTS.get(name, ())]}
    for name in INTENTS]}
COMPACT = os.getenv("JERVIS_NLU_SCHEMA", "compact") != "full"
if COMPACT:
    SCHEMA = SCHEMA_COMPACT

PROMPT ="""You understand what the user of Jervis, a voice assistant on their PC, means. Their words come from \
speech recognition (so names may be misheard: "blend ever" = Blender, "spot if I" = Spotify, "make the cube girl" = \
bigger) or are typed, in English, Hebrew, or a mix. Reply with JSON: one intent and its details, in English \
(translate Hebrew; keep song/artist names and search queries as said).
Intents:
""" + "\n".join(f"- {k}: {v}" for k, v in INTENTS.items()) + """
Use the context to resolve "it", "that", "the second one", "the same again", "go back".
Targets are short English references: "it", "the cube", "the second cube", "the roof".
change is one of bigger, smaller, taller, shorter, wider, narrower; times is a number ("2"), or empty.
""" + ("Give every detail the intent needs (\"\" only when it truly wasn't said).\n" if COMPACT else
        "Fill every field: the ones the intent needs, and \"\" for the rest.\n") + """confidence: 0-1, how sure you are this is what they meant. Fix an obvious speech-recognition slip when context makes \
it clear; but when the words don't clearly say what to do (e.g. "take it to a level"), use clarify and ask. Never \
invent a command from chit-chat or background talk: that's chat or ignore. Only use the slots the intent needs."""

def _example(intent, confidence, **slots):
    names = INTENT_SLOTS.get(intent, ()) if COMPACT else _SLOTS
    return {"intent": intent, "confidence": confidence, **{slot: slots.get(slot, "") for slot in names}}


EXAMPLES = [
    ("Open blend ever", {}, _example("open_app", 0.9, app="Blender")),
    ("תעשה אותה פי שלוש יותר רחבה", {"blender_focus": "Cube"},
     _example("object_resize", 0.95, target="it", change="wider", times="3")),
    ("put the ball beside the first box", {"blender_objects": ["Cube", "Sphere"]},
     _example("object_move", 0.9, target="the ball", next_to="the first cube")),
    ("take it to a level", {}, _example("clarify", 0.3, question="What should I take to which level?")),
    ("I think the weather's nice today", {}, _example("chat", 0.8)),
]


def _messages(text: str, context: dict) -> list:
    shots = []
    for said, ctx, answer in EXAMPLES:
        shots += [{"role": "user", "content": json.dumps({"context": ctx, "said": said}, ensure_ascii=False)},
                  {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}]
    return ([{"role": "system", "content": PROMPT}] + shots +
            [{"role": "user", "content": json.dumps({"context": context or {}, "said": text}, ensure_ascii=False)}])


def _slot(value, limit=120) -> str:
    value = " ".join(str(value or "").split())
    value = re.sub(r"[\x00-\x1f`]", "", value)
    return value[:limit]


def validate(raw) -> dict:
    """The model's answer, reduced to a known intent with clean slots (or a 'chat' fallback)."""
    if not isinstance(raw, dict) or raw.get("intent") not in INTENTS:
        return {"intent": "chat", "confidence": 0.0}
    out = {"intent": raw["intent"]}
    try:
        out["confidence"] = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        out["confidence"] = 0.5
    for slot in _SLOTS:
        if raw.get(slot) not in (None, ""):
            out[slot] = _slot(raw[slot])
    return out


_CHANGES = {"bigger", "smaller", "taller", "shorter", "wider", "narrower", "larger", "thinner", "fatter"}
_DIRECTIONS = {"left", "right", "up", "down", "forward", "back", "backward", "forwards", "backwards"}
_SHAPES = {"cube", "sphere", "cylinder", "cone", "plane", "torus", "monkey", "box", "ball"}
# The colours Jervis's Blender commands know (blender_commands._COLORS): anything else isn't a colour command.
_COLOR_NAMES = {"red", "green", "blue", "yellow", "orange", "purple", "pink", "white", "black", "gray", "grey",
                "brown", "gold", "silver", "cyan"}
MIN_CONFIDENCE = 0.55


def render(intent: dict):
    """A validated intent -> the canonical English command Jervis's deterministic handlers understand, or None when
    it isn't a command (chat), can't be made safe, or isn't confident enough to act on."""
    kind = intent.get("intent")
    g = intent.get
    if kind in ("chat", "ignore", "clarify") or intent.get("confidence", 0) < MIN_CONFIDENCE:
        return None
    target = (g("target") or "it").lower()
    if not re.fullmatch(r"[a-z0-9 '\-]{1,40}", target):
        target = "it"
    if kind == "open_app" and g("app"):
        return f"open {g('app')}"
    if kind == "close_app" and g("app"):
        return f"close {g('app')}"
    if kind == "switch_app" and g("app"):
        return "go back to blender" if g("app").lower() == "blender" else f"open {g('app')}"   # brings it forward
    if kind == "blender_create" and (g("shape") or "").lower() in _SHAPES:
        return f"create a {g('shape').lower()}"
    plain = re.sub(r"^(?:(?:add|create|make|build)\s+)?(?:an?|one|the)\s+", "",
                   (g("description") or g("shape") or "").lower().strip(" ."))
    if kind == "blender_build" and plain in _SHAPES:
        return f"create a {plain}"           # "add a sphere" is the simple shape, not a modelling job
    if kind == "blender_build" and g("description"):
        description = re.sub(r"\s+in blender\.?$", "", g("description"), flags=re.I)
        if not re.match(r"(?:build|make|model|create|add|design|sculpt)\b", description, re.I):
            description = "build " + description
        return f"in Blender, {description}"
    if kind == "object_resize" and (g("change") or "").lower() in _CHANGES:
        times = g("times") or ""
        times = times if re.fullmatch(r"\d+(?:\.\d+)?|two|three|four|five|ten", times.lower()) else ""
        return f"make {target} {times + ' times ' if times else ''}{g('change').lower()}"
    if kind == "object_color" and (g("color") or "").lower() in _COLOR_NAMES:   # never "make it nicer"
        return f"make {target} {g('color').lower()}"
    if kind == "object_move":
        if (g("direction") or "").lower() in _DIRECTIONS:
            return f"move {target} {g('direction').lower()}"
        if g("next_to") and re.fullmatch(r"[a-z0-9 '\-]{1,40}", g("next_to").lower()):
            return f"move {target} next to {g('next_to').lower()}"
    if kind == "object_rotate":
        deg = g("degrees") or ""
        return f"rotate {target}" + (f" {deg} degrees" if re.fullmatch(r"-?\d+(?:\.\d+)?", deg) else "")
    if kind == "object_delete":
        return f"delete {target}"
    if kind == "undo":
        return "undo"
    if kind == "repeat":
        return "do it again"
    if kind == "music_play":
        service = (g("service") or "").lower()
        query = g("query")
        if not query:
            return "resume the music"
        return f"play {query} on YouTube" if service == "youtube" else f"play {query} on Spotify"
    if kind == "music_pause":
        return "pause the music"
    if kind == "music_next":
        return "next song"
    if kind == "music_previous":
        return "previous song"
    way = {"up": "up", "louder": "up", "higher": "up", "increase": "up", "down": "down", "lower": "down",
           "quieter": "down", "softer": "down", "decrease": "down"}.get((g("direction") or g("change") or "").lower())
    if kind == "volume" and way:
        return f"volume {way}"
    duration = g("duration") or g("query") or ""      # models sometimes put "5 minutes" in query
    if kind == "timer" and re.fullmatch(r"[\w .]{1,30}", duration) and re.search(r"\d|minute|second|hour", duration):
        return f"set a timer for {duration}"
    if kind == "web_search" and g("query"):
        return f"search Google for {g('query')}"
    if kind == "control_start":
        return "take control of my computer" + (f" and {g('goal')}" if g("goal") else "")
    if kind == "control_stop":
        return "stop controlling my computer"
    if kind == "screen_task" and g("goal"):
        return f"use my computer to {g('goal')}"
    return None


# What makes an utterance worth asking the model about once nothing else handled it: Hebrew, or English that reads
# like an instruction. Plain questions and chat go straight to the chat model, as before (no extra call).
_COMMANDISH = re.compile(r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis)[, ]+)?(?:please |can you |could you |would you |"
                         r"go ahead and |now |then |and )*(?:open|close|launch|start|stop|pause|play|resume|make|"
                         r"create|add|build|put|move|turn|rotate|spin|delete|remove|undo|redo|do|go|switch|bring|"
                         r"take|set|show|search|find|type|click|scroll|color|colour|paint|scale|resize|duplicate|"
                         r"copy|skip|next|mute|unmute|use|control|give|shrink|grow|enlarge|widen|stretch|raise|"
                         r"lower|place|hide|quit|exit|kill|reset|save|increase|decrease|select|launch|fire up|"
                         r"bring up|pull up|get rid of|change|swap)\b", re.I)
_QUESTION = re.compile(r"^(?:what|why|how|when|who|where|which|is|are|do you|does|did|can you tell|tell me)\b", re.I)
# Hebrew questions ("what time is it…", "how do I…", "is it…") are conversation, like English ones.
_QUESTION_HE = re.compile(r"^(?:מה|מי|מתי|איפה|איך|למה|כמה|האם|איזה|איזו|אילו|מאיפה|לאן|תגיד(?:י)? לי|"
                          r"אתה יודע|את יודעת|ספר(?:י)? לי)(?=\s|$)")
# web_search is only for an explicit "search"/"google"/"look up" — a question the model wants to look up is chat.
_SEARCH_WORDS = re.compile(r"search|google|look up|lookup|find (?:me )?(?:info|out)|חפש|תחפש|תחפשי|גוגל|תבדוק", re.I)


def worth_understanding(text: str) -> bool:
    t = " ".join((text or "").split())
    if not t or len(t) > 300:
        return False
    if has_hebrew(t):
        return not _QUESTION_HE.match(t) and not t.endswith("?")
    return bool(_COMMANDISH.match(t)) and not _QUESTION.match(t)


def understand(text: str, context: dict, ask_json) -> dict:
    """The model's reading of `text` as a validated intent. ask_json(messages, schema, **options) -> dict."""
    raw = ask_json(_messages(text, context), SCHEMA, role="nlu", max_tokens=200, temperature=0.0, timeout=30)
    return validate(raw)


_ASK_FOR = {   # what to ask when the model saw an action but not enough to do it safely
    "object_resize": "Bigger or smaller, and which way: taller, wider?", "object_color": "Which colour?",
    "object_move": "Move it where?", "open_app": "Which app should I open?", "close_app": "Which app should I close?",
    "switch_app": "Which app should I go back to?", "blender_create": "What should I create?",
    "blender_build": "What should I build?", "timer": "For how long?", "screen_task": "What should I do on screen?",
    "volume": "Up or down?",
}


_NEEDS_WORDS = {
    "undo": re.compile(r"undo|revert|cancel|take (?:it|that) back|go back a step|בטל|תבטל|תחזיר", re.I),
    "repeat": re.compile(r"again|repeat|one more|same|another|once more|שוב|עוד פעם|עוד אחד|עוד אחת|תחזור על", re.I),
    "control_stop": re.compile(r"stop|quit|enough|release|give (?:me )?(?:back )?(?:the )?control|let go|hands off|"
                               r"תפסיק|תפסיקי|די|עצור|תעצור|תעזוב|שחרר", re.I),
    "control_start": re.compile(r"control|take over|use (?:my|the) (?:computer|mouse|pc|keyboard)|mouse|keyboard|"
                                r"שליטה|תשלוט|תשתלט|במחשב", re.I),
}


_SIZE_WORDS = re.compile(r"size|big|small|tall|short|wide|narrow|grow|shrink|scale|enlarge|double|twice|half|large|"
                         r"thick|thin|fat|high|low|tiny|huge|girl|bigga|digger|גדול|גדולה|קטן|קטנה|גבוה|גבוהה|נמוך|"
                         r"נמוכה|רחב|רחבה|צר|צרה|תגדיל|הגדל|תקטין|הקטן|כפול|פי|חצי|גודל", re.I)


def _colour_said(colour: str, text: str) -> bool:
    """The colour (or a near-miss of it: "make it blew") is in the words, in English or Hebrew."""
    said = (text or "").lower()
    colour = colour.lower()
    if colour in said or any(he in said and en == colour for he, en in COLORS_HE.items()):
        return True
    return any(difflib.SequenceMatcher(None, w, colour).ratio() >= 0.75 for w in re.findall(r"[a-z]+", said))


def _mentioned(app: str, text: str) -> bool:
    """Was `app` said (in English, in Hebrew, or misheard closely enough: "blunder" for Blender)?"""
    app_low, said = app.lower(), (text or "").lower()
    if app_low in said or any(he in said and en.lower() == app_low for he, en in APPS_HE.items()):
        return True
    words = re.findall(r"[a-z]+", said)
    pieces = words + [a + b for a, b in zip(words, words[1:])]
    return any(difflib.SequenceMatcher(None, p, app_low.replace(" ", "")).ratio() >= 0.75 for p in pieces)


def interpret(text: str, context: dict, ask_json):
    """What to do with `text` that no deterministic rule recognised:
        ("command", canonical English command)   run it through Jervis's normal command handling
        ("clarify", question)                    ask: it looks like a command, but it's unclear
        ("ignore", None)                         background speech: say nothing
        ("chat", None)                           conversation: answer it as before
    Never an action from chit-chat; never a guess at an action from an unclear command."""
    return decide(text, understand(text, context, ask_json))


def decide(text: str, intent: dict):
    """interpret()'s decision for an intent the model already gave."""
    kind = intent.get("intent")
    if kind == "chat" or (kind == "web_search" and not _SEARCH_WORDS.search(text or "")):
        return "chat", None
    if kind == "ignore":
        return ("ignore", None) if intent.get("confidence", 0) >= MIN_CONFIDENCE else ("chat", None)
    if kind == "clarify":
        return "clarify", intent.get("question") or "Sorry, what exactly should I do?"
    # Actions the words must actually ask for — a model reading "do the thing" as "repeat", or "close Chrome" as
    # "close Spotify", would otherwise act on a guess.
    if kind in _NEEDS_WORDS and not _NEEDS_WORDS[kind].search(text or ""):
        return "clarify", "Sorry, what exactly should I do?"
    # The app must have been said: the context names the window in front, and "make it" once became "open Visual
    # Studio Code" from that alone.
    if kind in ("open_app", "close_app", "switch_app") and intent.get("app") and not _mentioned(intent["app"], text):
        return "clarify", _ASK_FOR[kind]
    # Likewise a colour or a size change has to be in the words — "make it" once became "make it yellow", copied
    # from the previous command in the context.
    if (kind == "object_color" and intent.get("color") and not _colour_said(intent["color"], text)) or \
            (kind == "object_resize" and not _SIZE_WORDS.search(text or "")):
        return "clarify", "What should I change about it?"   # the guess was the model's, so no "Which colour?"
    canonical = render(intent)
    if canonical:
        return "command", canonical
    if intent.get("confidence", 0) < MIN_CONFIDENCE:
        return "clarify", "Sorry, I'm not sure what you meant. Can you say it another way?"
    return "clarify", _ASK_FOR.get(kind, "Sorry, what exactly should I do?")
