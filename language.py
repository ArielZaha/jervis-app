"""Languages other than English, around Jervis's English pipeline (Hebrew today; built so more can be added).

    speech -> stt_local (hears English or Hebrew, writes it) -> to_english() -> Jervis's English pipeline, unchanged
    (commands, Blender, programs, chat and its tools, context, corrections) -> English reply -> to_user_language()
    -> shown and spoken in the language the user is speaking.

Why translate rather than teach every part Hebrew: everything that acts (the command handlers, the Blender agent,
the code agent, the tool gates) is built and tested on English, and the local model that drives them (a coder
model) understands Hebrew badly. A model that is good at Hebrew (DictaLM 2.0, from Dicta, the Israeli NLP centre)
translates the request, and the proven English path does the work. Measured on spoken commands it kept every detail
(numbers, colours, materials, names, file names, corrections, "it"/"the second one") in ~0.4 s.

Safety: a translation is checked before anything acts on it. Garbled speech is not guessed at (the model says when
it can't tell); a translation that lost an English word, a number, a negation, or that deletes / closes / sends when
the Hebrew didn't say so (or the other way round), is read back to the user to confirm instead of being done.
The original words are always what the window shows and what the log keeps.

Adding a language: a Language entry (its script, prompt examples, fixed phrases, the risky verbs and negations).
"""
import collections
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field

import local_llm
import nlu
import paths


@dataclass(frozen=True)
class Language:
    code: str
    name: str                   # in English, for prompts
    letters: str                # a regex character class of its script
    to_english_examples: tuple  # (said, previous request or "", English; None = too garbled to translate)
    from_english_examples: tuple  # (English reply, translation)
    phrases: dict               # fixed short replies Jervis says often: a model gets these wrong out of context
    answers: dict               # short answers to a question ("yes", "no", "thanks") -> English
    risky: str                  # regex: words that delete, close, send... (checked against the English)
    negation: str               # regex: "not", "don't"...
    greeting: callable = None   # (part of day, name) -> the greeting
    confirm: str = 'Just to check: "{meaning}". Should I do that?'   # asked before acting on an unsure translation


# (Only the senses that act: "clear water", "close to the house", "an empty room", "in JSON format" don't count.)
ENGLISH_RISKY = re.compile(
    r"\b(?:delete|deleting|remove|removing|erase|wipe|uninstall|quit|exit|shut ?down|turn off|switch off|kill|send|"
    r"overwrite|discard|cancel|undo|reset|restart|reboot|get rid of|throw away|close(?! to\b| by\b| up\b)|"
    r"clear (?:the|my|all|everything|it|that|this)\b|empty (?:the|my)\b|format (?:the|my|it|this|that)\b)", re.I)
ENGLISH_NEGATION = re.compile(r"\b(?:no|not|never|nothing|none|without|cannot|nor)\b|n't\b", re.I)

_HE_PARTS_OF_DAY = {"morning": "בוקר טוב", "noon": "צהריים טובים", "afternoon": "אחר צהריים טובים",
                    "evening": "ערב טוב"}

HEBREW = Language(
    code="he", name="Hebrew", letters="\u0590-\u05ff\ufb1d-\ufb4f",
    to_english_examples=(
        ("תבנה לי גשר עץ ארוך מעל הנהר", "", "Build a long wooden bridge over the river"),
        ("תיצור קובייה ב-בלנדר ותצבע אותה בירוק בהיר", "", "Create a cube in Blender and color it light green"),
        ("לא, התכוונתי לכיסא השני", "Make the chair taller", "No, I meant the second chair"),
        ("שים את זה מתחת לשולחן", "", "Put it under the table"),
        ("תעשה את ה-tower פי שניים יותר רחב", "", "Make the tower twice as wide"),
        ("מה ההבדל בין רשימה למילון בפייתון?", "", "What's the difference between a list and a dictionary in Python?"),
        ("תריץ את [1] ותגיד לי מה יצא", "", "Run [1] and tell me what it printed"),
        ("אל תסגור את הדפדפן", "", "Don't close the browser"),
        ("תכתוב לבוס שלי שאני אאחר קצת", "", "Write to my boss that I'll be a little late"),
        ("תסתכל על המסך ותגיד לי מה כתוב", "", "Look at the screen and tell me what it says"),
        ("תכתוב הודעה למנהל שאני לא מגיע היום", "", "Write a message to my manager that I'm not coming in today"),
        ("תשלח לאחי שאני אגיע בעוד עשרים דקות", "", "Send my brother a message that I'll be there in 20 minutes"),
        ("תפרגל את הסמבוליט בקרנוז", "", None),   # garbled speech: no guessing
    ),
    from_english_examples=(
        ("Done — I opened Spotify.", "סיימתי — פתחתי את Spotify."),
        ("Opened Blender 4.5. On it.", "פתחתי את Blender 4.5. אני על זה."),
        ("I built a cabin with log walls, [1] square windows, a porch and a chimney.",
         "בניתי בקתה עם קירות מבולי עץ, [1] חלונות מרובעים, מרפסת וארובה."),
        ("I couldn't find [1] in Blender's scene, so I didn't change anything.",
         "לא מצאתי את [1] בסצנה של Blender, אז לא שיניתי כלום."),
        ("Done — saved to [1].", "סיימתי — שמרתי ב-[1]."),
        ("Which colour?", "איזה צבע?"),
        ("It's 14:32.", "השעה 14:32."),
        ("Done: Make the door blue. I checked it in Blender: 2 of 2 checks passed.",
         "סיימתי: הדלת כחולה עכשיו. בדקתי ב-Blender: 2 מתוך 2 בדיקות עברו."),
    ),
    phrases={
        "On it.": "אני על זה.",
        "Okay.": "בסדר.",
        "Ok.": "בסדר.",
        "Sure.": "בטח.",
        "Done.": "סיימתי.",
        "I'm here.": "אני כאן.",
        "Continuing.": "ממשיך.",
        "Okay, cancelled.": "בסדר, ביטלתי.",
        "Okay, I won't.": "בסדר, לא אעשה את זה.",
        "Sure, I'm ready.": "בטח, אני מוכן.",
        "Disconnected.": "התנתקתי.",
        "Time's up.": "הזמן נגמר.",
        "Paused playback.": "עצרתי את הניגון.",
        "Resuming the music.": "ממשיך את המוזיקה.",
        "Skipped to the next song.": "עברתי לשיר הבא.",
        "Which colour?": "איזה צבע?",
        "Which color?": "איזה צבע?",
        "Which way?": "לאיזה כיוון?",
        "Which app should I open?": "איזו אפליקציה לפתוח?",
        "What should I search for?": "מה לחפש?",
        "How long should I set it for?": "לכמה זמן לכוון?",
        "Still working on that — one moment.": "עדיין עובד על זה — רגע אחד.",
        "I'm still working on the last program — one moment.": "אני עדיין עובד על התוכנית הקודמת — רגע אחד.",
        # a program task starting: said while the coder loads for it, so never a translator call (a model swap)
        "On it — I'll write it, run it, and check it works before I tell you it's done.":
            "אני על זה — אכתוב אותה, אריץ אותה ואבדוק שהיא עובדת לפני שאגיד לך שסיימתי.",
        "On it — I'll change it, run it and check it.": "אני על זה — אשנה אותה, אריץ אותה ואבדוק אותה.",
        "Running it again and checking it.": "מריץ אותה שוב ובודק אותה.",
        "Starting the song over.": "מתחיל את השיר מההתחלה.",
        "Your phone is connected.": "הטלפון שלך מחובר.",
        "Connection cancelled.": "החיבור בוטל.",
        "I'm listening. How can I help?": "אני מקשיב. במה אוכל לעזור?",
        "Sorry, something went wrong. Please try again.": "סליחה, משהו השתבש. נסה שוב בבקשה.",
        "Sorry, something went wrong with that command.": "סליחה, משהו השתבש בפקודה הזאת.",
        "I've put the details on your screen.": "שמתי את הפרטים על המסך.",
        "Here's what I found.": "הנה מה שמצאתי.",
        "Going to sleep. Say Hey Jervis when you want me.": "הולך לישון. תגיד היי ג'רביס כשתצטרך אותי.",
        "Say yes or no.": "תגיד כן או לא.",
        "(yes / no)": "(כן / לא)",
        # what this module itself says
        "Sorry, I didn't catch that. Could you say it again?": "סליחה, לא הבנתי. תוכל להגיד את זה שוב?",
        "Okay, I didn't do anything. Say it again in other words?": "בסדר, לא עשיתי כלום. תגיד את זה שוב במילים אחרות?",
        "Sorry, my local AI didn't answer in time. Please try again in a moment.":
            "סליחה, הבינה המלאכותית המקומית שלי לא ענתה בזמן. נסה שוב בעוד רגע.",
    },
    answers={
        "כן": "yes", "כן כן": "yes", "כן בבקשה": "yes please", "בטח": "sure", "בסדר": "okay", "אוקיי": "okay",
        "סבבה": "okay", "יאללה": "okay", "קדימה": "go ahead", "תעשה את זה": "do it", "נכון": "yes", "מאשר": "yes",
        "לא": "no", "לא לא": "no", "לא תודה": "no thanks", "ממש לא": "no", "אל תעשה את זה": "don't do it",
        "עזוב": "never mind", "תודה": "thank you", "תודה רבה": "thank you very much",
    },
    # Verbs (the forms people say) that delete, remove, close, turn off, send, clear, cancel, reset.
    risky=(r"(?<![\u0590-\u05ff])[ושה]?(?:ת?מח[וי]?ק|למחוק|מחיקה|ת?הסר|תסיר|להסיר|הסרה|תוריד|הורד|להוריד|תעיף|"
           r"העף|להעיף|ת?זרוק|לזרוק|תיפטר|להיפטר|ת?סגור|תסגר|לסגור|ת?כבה|תכב|לכבות|ת?שלח|לשלוח|ת?נקה|לנקות|"
           r"ת?רוקן|לרוקן|ת?דרוס|לדרוס|ת?בטל|לבטל|ת?אפס|לאפס|ת?פרמט|ת?הרוג|תחסל|ת?אתחל|תצא|צא)(?:[יו]|ו?ת)?"
           r"(?![\u0590-\u05ff])"),
    # "אל" is also "to" ("אל הבית"): only "don't" when a verb follows ("אל תסגור").
    negation=r"(?<![\u0590-\u05ff])(?:לא|אסור|בלי|אין|אף פעם|שום|אל(?=\s+[תי])(?!\s+תוך))(?![\u0590-\u05ff])",
    greeting=lambda part, who: f"{_HE_PARTS_OF_DAY.get(part, 'שלום')}, {'אדוני' if who == 'Sir' else who}. "
                               "במה אוכל לעזור היום?",
    confirm='רק לוודא שהבנתי: "{meaning}". לעשות את זה? (כן / לא)',
)


def confirm_question(heard: "Understanding") -> tuple:
    """(shown, spoken): Jervis asks whether he understood `heard` right — its meaning said back in the user's
    language (translated back from the English, so a misreading shows), and the English it would act on."""
    lang = LANGUAGES.get(heard.language)
    if not lang:
        question = f'Just to check: "{heard.english}". Should I do that?'
        return question, question
    meaning = to_user_language(heard.english, lang.code)
    if not _letters(lang).search(meaning):   # couldn't say it back in that language: the English itself
        meaning = heard.english
    spoken = re.sub(r"\s*\([^)]*\)\s*$", "", lang.confirm.format(meaning=meaning))   # "(yes / no)" is for the eye
    return f"{lang.confirm.format(meaning=meaning)}\n\n_({heard.english})_", spoken

LANGUAGES = {"he": HEBREW}
_FOREIGN_SCRIPTS = re.compile(r"[\u0400-\u04ff\u0600-\u06ff\u0e00-\u0e7f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_'+#-]*")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _letters(lang: Language) -> re.Pattern:
    return re.compile(f"[{lang.letters}]")


# ---------------------------------------------------------------- which language is this?

def detect(text: str) -> tuple:
    """(language code, mixed): ("he", False) for Hebrew, ("he", True) for Hebrew with English words in it,
    ("en", False) for English, ("", False) when there are no words at all."""
    text = text or ""
    latin = bool(_LATIN_WORD.search(re.sub(r"\b(?:hey|hi|ok|okay)?\s*j[ae]rvis\b", "", text, flags=re.I)))
    for code, lang in LANGUAGES.items():
        if _letters(lang).search(text):
            return code, latin
    return ("en", False) if _LATIN_WORD.search(text) else ("", False)


_NOT_A_LANGUAGE = re.compile(r"\b(?:hey|hi|hello|ok|okay|yes|yeah|no|thanks|thank you|jervis|jarvis|bye|wake up|"
                             r"good morning|good night)\b", re.I)
# Three real English words switch the conversation to English: a Hebrew speaker's "Wake up, Jarvis" or "open
# Blender" doesn't (each switch moves speech models on the GPU, see stt_local.prefer).
ENGLISH_SWITCH_WORDS = 3


def turn_language(text: str) -> str:
    """The language a request switches Jervis's answers to: Hebrew (or mixed) -> "he"; English -> "en" only when
    it's really English — not a lone "OK", "yes" or "hey Jervis" from someone speaking Hebrew. "" = no change."""
    code, _mixed = detect(text)
    if code in LANGUAGES:
        return code
    if code == "en" and len(_LATIN_WORD.findall(_NOT_A_LANGUAGE.sub(" ", text or ""))) >= ENGLISH_SWITCH_WORDS:
        return "en"
    return ""


# ---------------------------------------------------------------- the user's language (what Jervis answers in)

_STATE_FILE = "language.json"
_state = {"reply": None}
_state_lock = threading.Lock()


def reply_language() -> str:
    """What Jervis answers in: the language of the user's last request (Settings can fix it: JERVIS_REPLY_LANGUAGE)."""
    fixed = (os.getenv("JERVIS_REPLY_LANGUAGE") or "auto").strip().lower()
    if fixed in LANGUAGES or fixed == "en":
        return fixed
    with _state_lock:
        if _state["reply"] is None:
            try:
                with open(paths.data(_STATE_FILE), encoding="utf-8") as f:
                    saved = json.load(f).get("reply")
            except (OSError, ValueError, AttributeError):
                saved = None
            _state["reply"] = saved if saved in LANGUAGES or saved == "en" else "en"
        return _state["reply"]


def set_reply_language(code: str) -> None:
    """Remembered across restarts, so a Hebrew speaker is greeted in Hebrew next time too."""
    if code not in LANGUAGES and code != "en":
        return
    with _state_lock:
        changed = _state["reply"] != code
        _state["reply"] = code
    if changed:
        try:
            with open(paths.data(_STATE_FILE), "w", encoding="utf-8") as f:
                json.dump({"reply": code}, f)
        except OSError:
            pass


# ---------------------------------------------------------------- the user's words -> English

@dataclass
class Understanding:
    original: str
    language: str = "en"      # "en", "he"...
    mixed: bool = False
    english: str = ""         # what the English pipeline gets
    status: str = "same"      # same (already English) | ok | confirm (ask first) | unclear | unavailable
    method: str = ""          # answer | rules | cache | model
    model: str = ""
    seconds: float = 0.0
    problems: list = field(default_factory=list)
    error: str = ""           # the translator failed (stopped, timed out) — as opposed to there being none

    @property
    def translated(self) -> bool:
        return self.status in ("ok", "confirm")

    def log_line(self) -> str:
        why = f" [{'; '.join(self.problems)}]" if self.problems else ""
        return (f"Heard ({self.language}{', mixed' if self.mixed else ''}): {self.original!r} -> {self.english!r} "
                f"({self.status}, {self.method}{' ' + self.model if self.model else ''}, {self.seconds:.2f}s){why}")


_cache = collections.OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 500


def _cached(key):
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def _remember(key, value):
    with _cache_lock:
        _cache[key] = value
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


# Paths, URLs, file names and code are never translated: they're replaced by markers ([1]) the model copies through.
_PROTECT = re.compile(
    r"```.*?```|`[^`\n]+`|\$\$.+?\$\$|(?<![\w$])\$[^$\n]+\$(?![\w$])|\[[^\]\n]+\]\([^)\s]+\)|https?://\S+|"
    r"(?:[A-Za-z]:\\|\\\\)[^\s,;\"'<>|]*[^\s,;\"'<>|.]|(?<![\w.])(?:~|\.{1,2})?/[\w.~-]+(?:/[\w.~-]*)+|"
    r"(?<![A-Za-z0-9_.])[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:py|pyw|js|ts|tsx|jsx|json|blend|txt|csv|md|html|css|png|jpe?g|gif|webp|svg|exe|bat|ps1|sh|wav|"
    r"mp3|mp4|pdf|docx?|xlsx?|pptx?|zip|c|cpp|h|cs|java|go|rs|rb|php|ipynb|yaml|yml|toml|ini|log|obj|fbx|glb|stl)\b",
    re.S)
_MARKER = re.compile(r"\[(\d+)\]")


# Numbers too, in replies: a model translating into Hebrew tends to write "8" as a word, and the check then has to
# throw the whole sentence away. As markers they come through exactly as they were.
_PROTECT_WITH_NUMBERS = re.compile(_PROTECT.pattern + r"|(?<![\w.\[])\d+(?:[.,:]\d+)*(?![\w\]])", re.S)


# Words in quotes — a song's title, a name, a phrase to search for — stay exactly as said (a Hebrew title
# translated word by word is another song: "סוזי תזוזי" became something Spotify played "WW3" for).
_QUOTED = re.compile(r'(?<!\S)(?:"[^"\n]{1,80}"|“[^”\n]{1,80}”|„[^“”\n]{1,80}[“”]|״[^״\n]{1,80}״)(?!\S)')


def protect(text: str, numbers: bool = False, quotes: bool = False) -> tuple:
    kept = []

    def keep(m):
        kept.append(m.group(0))
        return f"[{len(kept)}]"
    if quotes:
        text = _QUOTED.sub(keep, text)
    return (_PROTECT_WITH_NUMBERS if numbers else _PROTECT).sub(keep, text), kept


def restore(text: str, kept: list) -> str:
    return _MARKER.sub(lambda m: kept[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(kept) else m.group(0),
                       text)


def _markers_intact(text: str, kept: list) -> bool:
    return all(text.count(f"[{i}]") == 1 for i in range(1, len(kept) + 1))


TRANSLATION_PROMPT = """Jervis is a voice assistant on the user's PC: he opens apps, builds 3D models in Blender, writes and runs code and plays music. You do two translation jobs for him; each message starts with which one.

"TO ENGLISH:" - what the user said to Jervis, in {name} (often mixed with English), into natural English, exactly as the user would have said it in English.
- Translate EVERY word that carries meaning: never drop an adjective, material, size, colour, number, place, name or step ("ממש מפורט" = "really detailed", "גג רעפים" = "tiled roof", "עץ" may be wood or a tree: read the sentence).
- A command stays a command, a question stays a question, a correction stays a correction ("No, I meant ..."). "Don't" stays "don't".
- Write numbers as digits, the way speech recognition writes English: "תשעים מעלות" = "90 degrees", "פי שלוש" = "3 times", "עשר דקות" = "10 minutes".
- Copy English words, names, code, file names, paths and URLs exactly as written. Copy every marker like [1] as it is.
- English words spelled in {name} letters get their English spelling (בלנדר = Blender, ספוטיפיי = Spotify, פייתון = Python, דיטייל = detail, פרויקט = project).
- The user speaks about himself or herself ("I", "me", "my": אני, לי, שלי) and to Jervis ("you": אתה). Keep who is who: "לאמא" is "to Mom", "המסך" is "the screen", never "your" unless the user said "שלך".
- Keep references as references ("it", "that", "the roof", "the windows"): never guess what they refer to. The previous request, when given, is only there to help you read the words: never translate it or copy from it.
- Never add anything that wasn't said, never answer it, never explain. "לי" ("for me") is usually dropped.
- The words come from speech recognition, which sometimes mishears a word as a similar-sounding one (often an English word said inside {name}, written in {name} letters). When a word is clearly a mishearing and the similar-sounding word makes the sentence a sensible request to Jervis, translate what was meant ("תצאו" said as a command is "תיצור", "דיטייל האוס" is "detailed house"). When you can't tell what was meant, never invent a meaning.
- {to_english_format}

"TO {upper}:" - Jervis's English reply into natural spoken {name}. Jervis speaks about himself in the masculine first person and addresses the user. Translate exactly what is written - add no greeting, no question and no comment of your own. Keep names of apps, products, people, songs, films and code as they are. Keep every number in digits exactly as written ("8 windows" = "8 חלונות"). Copy every marker like [1] exactly as it is, and keep Markdown (**, #, -) where it is. {to_user_format}"""
# (Measured: asked this way, DictaLM marks gibberish; an optional "unclear" flag it never set.)
# Plain text (the default) or JSON answers. Plain: the answer is the sentence itself, on one line — a JSON answer's
# own keys and quotes were most of the tokens generated (18 for "Make the roof red", vs 5), and generating under a
# JSON grammar is slower per token too. JERVIS_TRANSLATE_FORMAT=json goes back to JSON.
PLAIN = (os.getenv("JERVIS_TRANSLATE_FORMAT") or "plain").strip().lower() != "json"
GARBLED = "???"
# Without JSON, DictaLM doesn't end its turn by itself: it goes on writing the next turn of its chat template.
_STOP = ["\n", "[INST]", "</s>"]
_FORMATS = {
    True: {"to_english_format": "Answer with only the English, on one line. When the words aren't real {name} (or "
                                "English) words, or the sentence makes no sense as something a person would say, "
                                f"answer only {GARBLED} - never invent a meaning.",
           "to_user_format": "Answer with only the translation, on one line."},
    False: {"to_english_format": 'First answer "real_words": are all the words real {name} (or English) words, and '
                                 'does the sentence make sense as something a person would say? Then "english". '
                                 'Reply as JSON: {{"real_words": true, "english": "..."}}',
            "to_user_format": 'Reply as JSON: {{"text": "..."}}'},
}
_TO_ENGLISH_SCHEMA = {"type": "object", "properties": {"real_words": {"type": "boolean"}, "english": {"type": "string"}},
                      "required": ["real_words", "english"]}
_OPTIONS = {"repeat_penalty": 1.05}
# Loading the model takes up to ~15 s and a translation a few seconds: past this, something is wrong (the GPU is
# overloaded, Ollama is stuck), and waiting longer only makes the user wait longer for the same failure.
TIMEOUT = 45


def _said(text: str, previous: str) -> str:
    return f"(previous request: {previous})\n{text}" if previous else text


def _messages(lang: Language, task: str, text: str) -> list:
    """Both jobs share one prompt and one set of examples, so the model's cache of everything before the last message
    stays valid from one call to the next: a turn translates the request in, then the answer out, and with separate
    prompts each call re-read ~1,100 tokens (2-2.5 s whenever part of the model runs on the CPU, measured)."""
    messages = [{"role": "system", "content": TRANSLATION_PROMPT.format(name=lang.name, upper=lang.name.upper(),
                                                                         **{k: v.format(name=lang.name) for k, v in _FORMATS[PLAIN].items()})}]
    for said, before, english in lang.to_english_examples:
        messages.append({"role": "user", "content": "TO ENGLISH:\n" + _said(said, before)})
        messages.append({"role": "assistant", "content": (english or GARBLED) if PLAIN else json.dumps({"real_words": english is not None,
                                                                     "english": english or ""})})
    for english, translated in lang.from_english_examples:
        messages.append({"role": "user", "content": f"TO {lang.name.upper()}:\n{english}"})
        messages.append({"role": "assistant", "content": translated if PLAIN else
                         json.dumps({"text": translated}, ensure_ascii=False)})
    messages.append({"role": "user", "content": f"{task}:\n{text}"})
    return messages


def _to_english_messages(lang: Language, masked: str, previous: str) -> list:
    return _messages(lang, "TO ENGLISH", _said(masked, previous))


def translator() -> str:
    """The local model that translates (None when none is installed or the local AI isn't running)."""
    try:
        return local_llm.role_model("translate")
    except Exception:
        return None


def _trusted(model: str) -> bool:
    """A model measured to translate faithfully. Any other one (a fallback) is used, but asked about before acting."""
    return "dictalm" in (model or "").lower()


KNOWN_NAMES = {n.lower() for n in nlu.APPS_HE.values()} | {
    "i", "jervis", "blender", "python", "javascript", "windows", "mac", "linux", "spotify", "youtube", "google",
    "chrome", "whatsapp", "excel", "word", "powerpoint", "notepad", "minecraft", "mom", "dad", "hello", "world",
    "english", "hebrew", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january",
    "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "downloads", "documents", "desktop", "pictures", "music", "videos", "settings", "github", "gmail", "html", "css"}


_QUESTION = re.compile(r"^(?:what|why|how|when|who|where|which|is|are|do|does|did|can|could|would|should|will|tell me|"
                       r"explain)\b|\?\s*$", re.I)


_english_words = None


def _is_english_word(word: str) -> bool:
    """In the CMU Pronouncing Dictionary (134k English words; it comes with the Hebrew voice, hebrew_voice.py) —
    with plurals and the usual endings. Without the dictionary every word passes (the check is just skipped)."""
    global _english_words
    if not _english_words:   # (an empty load isn't kept: the dictionary may arrive with the voice later)
        words = set()
        try:
            import hebrew_voice
            with open(os.path.join(hebrew_voice.folder(), "cmudict.dict"), encoding="utf-8", errors="replace") as f:
                for line in f:
                    words.add(line.split(" ", 1)[0].split("(")[0].lower())
        except OSError:
            pass
        _english_words = words or None
    if not _english_words:
        return True
    w = word.lower()
    stems = {w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith(("es", "ed")) else w,
             w[:-3] if w.endswith("ing") else w, w[:-2] if w.endswith("ly") else w}
    return any(s in _english_words for s in stems)


def check_english(lang: Language, source: str, english: str, kept: list, model: str) -> tuple:
    """Problems with a translation: (fatal, worth_asking). Fatal ones mean it can't be used at all."""
    fatal, ask = [], []
    if not english.strip():
        fatal.append("empty")
    if _letters(lang).search(english):
        fatal.append(f"{lang.name} left untranslated")
    if _FOREIGN_SCRIPTS.search(english):
        fatal.append("another script appeared")
    if not _markers_intact(english, kept):
        fatal.append("a file name/path/code was lost")
    plain_source = _MARKER.sub(" ", source)
    lower = english.lower()
    lost = [w for w in _LATIN_WORD.findall(plain_source)
            if len(w) > 1 and w.lower() not in lower and w.lower() not in ("jervis", "jarvis")]
    if lost:
        ask.append(f"lost {', '.join(lost[:4])}")
    numbers = [n for n in _NUMBER.findall(plain_source) if n not in english]
    if numbers:
        ask.append(f"lost the number {', '.join(numbers[:3])}")
    # Words that don't exist ("Flourgans brushed with carrots"): misheard speech the model translated anyway.
    made_up = [w for w in re.findall(r"(?<![\w'])[A-Za-z]{4,}(?![\w'])", english)
               if w.lower() not in plain_source.lower() and w.lower() not in KNOWN_NAMES and not _is_english_word(w)]
    if made_up:
        ask.append(f"not English words: {', '.join(made_up[:3])}")
    # A name nobody said ("Create a detail drawing in Tbilisi, Georgia" from misheard English words): ask.
    invented = [w for w in re.findall(r"(?<![^\s\"'(])[A-Z][A-Za-z]+", english)
                if w.lower() not in plain_source.lower() and w.lower() not in KNOWN_NAMES
                and not re.search(rf"(?:^|[.!?:]\s+|[\"'(]){w}\b", english)]   # (a sentence's first word)
    if invented:
        ask.append(f"new name {', '.join(invented[:3])}")
    said, written = len(source.split()), len(english.split())
    if written > 3 * said + 5 or written < max(1, said // 3):
        ask.append(f"length {said} -> {written} words")
    safety = []
    risky_source = bool(re.search(lang.risky, source)) or bool(ENGLISH_RISKY.search(plain_source))
    if bool(ENGLISH_RISKY.search(english)) != risky_source:
        safety.append("a delete/close/send/cancel word " + ("appeared" if not risky_source else "disappeared"))
    negative_source = bool(re.search(lang.negation, source)) or bool(ENGLISH_NEGATION.search(plain_source))
    if bool(ENGLISH_NEGATION.search(english)) != negative_source:
        safety.append("a negation " + ("appeared" if not negative_source else "disappeared"))
    if not _trusted(model):
        ask.append(f"{model} is not a checked translator")
    # Asking only matters before acting: a plain question is fine unless the meaning itself (safety) changed.
    if _QUESTION.search(english.strip()) and not safety:
        ask = []
    return fatal, ask + safety


def to_english(text: str, previous: str = "") -> Understanding:
    """The user's words in English, for Jervis's English pipeline, with how sure that is. `previous`: the request
    before this one (in English), which helps read a follow-up or a correction."""
    started = time.time()
    original = (text or "").strip()
    code, mixed = detect(original)
    if code in ("", "en"):
        return Understanding(original, "en", False, original, "same")
    lang = LANGUAGES[code]
    result = Understanding(original, code, mixed)
    bare = " ".join(re.sub(r"[?!.,;:\"״׳]", " ", nlu._NIQQUD.sub("", original)).split())
    # The rule grammar for the everyday commands (open/close apps, colours, sizes, undo, music): instant and exact,
    # and no model has to be swapped into the GPU for them.
    # (Not with a path, file name or code in it: the grammar drops punctuation, which those need.)
    ruled = (nlu.rewrite_hebrew(original) if code == "he" and bare not in lang.answers and not protect(original)[1]
             else None)
    if bare in lang.answers:
        result.english, result.status, result.method = lang.answers[bare], "ok", "answer"
    elif code == "he" and mixed and _ENGLISH_FRAME.match(original) and not re.search(lang.risky, original):
        # "play סוזי תזוזי on spotify", "search for מתכון לעוגה", "call אמא": the command is English already and
        # the Hebrew is what it's about — a title, a search, a name — which must reach it exactly as said
        result.english, result.status, result.method = original, "ok", "names"
    elif ruled:
        result.english, result.status, result.method = ruled, "ok", "rules"
    else:
        key = (code, original, previous)
        hit = _cached(key)
        if hit:
            result.english, result.status, result.model, result.problems = hit
            result.method = "cache"
        else:
            _model_to_english(lang, original, previous, result)
            if result.status in ("ok", "confirm", "unclear"):
                _remember(key, (result.english, result.status, result.model, list(result.problems)))
    result.seconds = time.time() - started
    return result


_ENGLISH_FRAME = re.compile(
    r"^\s*(?:(?:hey|hi|ok|okay)\s+)?(?:j[ae]rvis[\s,]+)?(?:(?:please|can you|could you)\s+)?"
    r"(?:play|put on|listen to|search(?:\s+for)?|look up|google|find|show me|call|text|message|navigate to|"
    r"directions to|open)\s+(?=\S)", re.I)


_DIDNT_MEAN = re.compile(r"^(?:no,?\s+)?i did(?:n't| not) mean (?P<ref>(?:the|that|this) [a-z][a-z ]{0,40}?)[.!]?$",
                         re.I)


def _spoken_correction(english: str, previous: str) -> str:
    """Speech recognition drops the comma of "No, I meant the windows" (in Hebrew "לא, התכוונתי לחלונות" becomes
    "I didn't mean the windows"). Right after a request that wasn't about that thing, only the correction makes
    sense; about the very thing just asked for ("I didn't mean the roof" after "make the roof red"), it stays as said.
    Only a thing ("the ..."), never an action: "I didn't mean to delete it" is left alone."""
    m = _DIDNT_MEAN.match(english or "")
    if not m or not previous:
        return english
    ref = m.group("ref")
    noun = ref.split(" ", 1)[1].lower()
    if re.search(rf"\b{re.escape(noun.rstrip('s'))}", previous.lower()):
        return english
    return f"No, I meant {ref}"


_MAKE_THE_COLOUR = re.compile(r"^make the (?P<colour>" + "|".join(sorted(nlu._COLOR_NAMES, key=len, reverse=True))
                              + r") (?P<thing>[a-z][a-z ]{0,30}?)[.!]?$", re.I)
_MAKE_THE_HE = re.compile(r"^(?:ו)?(?:תעשה|תעשי|עשה|עשי|תהפוך|הפוך)\s+את\s+ה")


def _spoken_article(english: str, source: str) -> str:
    """"תעשה את הגג אדום" (make the roof red) and "תעשה את הגג האדום" (make the red roof) sound the same — the ה
    is barely said — and speech recognition writes either. Said about a thing that's already there ("את ה..."),
    it's the change that's meant: "Make the red roof" -> "Make the roof red"."""
    m = _MAKE_THE_COLOUR.match(english or "")
    if m and _MAKE_THE_HE.match(source.strip()):
        return f"Make the {m.group('thing')} {m.group('colour').lower()}"
    return english


def _model_to_english(lang: Language, original: str, previous: str, result: Understanding) -> None:
    model = translator()
    if not model:
        result.status, result.problems = "unavailable", ["no translation model installed or running"]
        return
    masked, kept = protect(original, quotes=True)
    try:
        messages = _to_english_messages(lang, masked, previous)
        if PLAIN:
            text = local_llm.chat_text(messages, role="translate", model=model, temperature=0.0,
                                       max_tokens=min(300, 30 + 5 * len(masked.split())), timeout=TIMEOUT,
                                       options=_OPTIONS, stop=_STOP)
            garbled = not text or text.startswith(GARBLED)
            answer = {"real_words": not garbled, "english": "" if garbled else text}
        else:
            answer = local_llm.chat_json(messages, _TO_ENGLISH_SCHEMA, role="translate", model=model,
                                         temperature=0.0, max_tokens=min(600, 60 + 6 * len(masked.split())),
                                         timeout=TIMEOUT, options=_OPTIONS)
    except Exception as e:   # the local AI stopped, ran out of memory, took too long...
        result.status, result.model, result.problems = "unavailable", model, [f"{type(e).__name__}: {str(e)[:120]}"]
        result.error = str(e)[:120]
        return
    english = _spoken_correction(" ".join(str(answer.get("english") or "").split()), previous)
    if lang.code == "he":
        english = _spoken_article(english, original)
        if re.match(r"^\s*לא\s*,", original) and english and not re.match(r"^\s*no\b", english, re.I):
            english = "No, " + english[0].lower() + english[1:]   # "לא, ..." starts a correction: keep its "No,"
    fatal, ask = check_english(lang, masked, english, kept, model)
    result.model, result.method = model, "model"
    result.english = restore(english, kept) if not fatal else ""
    result.problems = fatal + ask
    result.status = status_for(fatal, ask, english, answer.get("real_words") is not False)


def status_for(fatal: list, ask: list, english: str, real_words: bool = True) -> str:
    """Whether to act on a translation, ask first, or say it wasn't caught. Asking ("just to make sure: ... ?") is
    only worth it before something that can't be taken back — deleting, closing, sending, cancelling — or when the
    meaning itself flipped (a "not" or a "delete" appeared or vanished). A clear, harmless command ("play X", "open
    Y") with a name the translator spelled its own way is simply done; a misheard one is quickly undone by the next
    request (an invented name or an unchecked translator is logged, not asked about). Speech the translator
    couldn't make out at all is said to be unclear, not guessed at."""
    if fatal:
        return "unclear"
    # the meaning flipped, or words the user said themselves (an English word, a number) were dropped
    meaning_changed = any(p.startswith(("a delete/close/send/cancel word", "a negation", "lost ")) for p in ask)
    risky = bool(ENGLISH_RISKY.search(english or ""))
    if meaning_changed or (risky and (ask or not real_words)):
        return "confirm"
    if not real_words and any(p.startswith("not English words") for p in ask):
        return "unclear"
    return "ok"


# ---------------------------------------------------------------- Jervis's English replies -> the user's language

_FROM_ENGLISH_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
_STRUCTURE = re.compile(r"^(\s*(?:#{1,6}\s+|[-*•]\s+|\d+[.)]\s+|>\s?)?)(.*)$")
_GREETING = re.compile(r"^Good (morning|noon|afternoon|evening), (.+?)\. How can I help you today\?$")


def phrase(english: str, code: str = None) -> str:
    """A fixed sentence Jervis says, in the user's language when there's a translation for it."""
    code = code or reply_language()
    lang = LANGUAGES.get(code)
    return lang.phrases.get(english, english) if lang else english


def _needs_translation(text: str, lang: Language) -> bool:
    masked, _ = protect(text)
    words = _LATIN_WORD.findall(masked)
    return bool(words) and not _letters(lang).search(masked) and \
        not (len(words) == 1 and len(masked.strip(" .!?:-—")) == len(words[0]))   # a lone name: "Blender"


def to_user_language(text: str, code: str = None, allow_model: bool = True) -> str:
    """`text` (an English reply) in the language the user speaks; unchanged when that's English, when it's already
    in that language, or when it can't be translated reliably (then the English is better than a wrong sentence).
    Code blocks, formulas, paths and file names are never changed."""
    code = code or reply_language()
    lang = LANGUAGES.get(code)
    raw = str(text or "")
    if not lang or not raw.strip():
        return raw
    stripped = raw.strip()
    if stripped in lang.phrases:
        return lang.phrases[stripped]
    if not _needs_translation(raw, lang):
        return raw
    greeting = _GREETING.match(stripped)
    if greeting and lang.greeting:
        return lang.greeting(greeting.group(1), greeting.group(2))
    key = (code, "out", raw)
    hit = _cached(key)
    if hit is not None:
        return hit
    if not allow_model:
        return raw
    model = translator()
    if not model or not _trusted(model):   # only a checked translator writes what the user reads and hears
        return raw
    started = time.time()
    out, failed = _translate_reply(lang, raw, model)
    print(f"Reply in {lang.name} ({time.time() - started:.2f}s{', parts kept in English' if failed else ''}).",
          flush=True)
    _remember(key, out)
    return out


def _translate_reply(lang: Language, raw: str, model: str) -> tuple:
    """Paragraph by paragraph (list items and headings one by one, Markdown markers kept), code blocks untouched."""
    pieces, failed = [], 0
    for chunk in re.split(r"(```.*?```)", raw, flags=re.S):
        if chunk.startswith("```"):
            pieces.append(chunk)
            continue
        out_lines = []
        for block in re.split(r"(\n\s*\n)", chunk):
            if not block.strip() or re.fullmatch(r"\n\s*\n", block):
                out_lines.append(block)
                continue
            lines = block.split("\n")
            structured = len(lines) > 1 and any(_STRUCTURE.match(ln).group(1).strip() or ln.lstrip().startswith("|")
                                               for ln in lines)
            units = lines if structured else [block]
            if len(units) == 1 and len(block) > 160 and "\n" not in block.strip():
                # a long paragraph sentence by sentence: in one piece, details (a count, a name) got dropped
                units = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", block.strip())
                done = []
                for unit in units:
                    translated, ok = _translate_unit(lang, unit, model)
                    failed += not ok
                    done.append(translated)
                out_lines.append(" ".join(done))
                continue
            done = []
            for unit in units:
                translated, ok = _translate_unit(lang, unit, model)
                failed += not ok
                done.append(translated)
            out_lines.append("\n".join(done))
        pieces.append("".join(out_lines))
    return "".join(pieces), failed


def _translate_unit(lang: Language, unit: str, model: str) -> tuple:
    marker, body = _STRUCTURE.match(unit).groups()
    if body.strip() in lang.phrases:
        return marker + lang.phrases[body.strip()], True
    if re.fullmatch(r"\s*\|?[\s:|-]*\|?\s*", unit) or not _needs_translation(unit, lang):   # table rule, code-only
        return unit, True
    masked, kept = protect(body.replace('"', "”"), numbers=True)   # (a bare " inside the JSON cut DictaLM short)
    if not _needs_translation(masked, lang):
        return unit, True
    masked = " ".join(masked.split()) if PLAIN else masked   # one line: the plain answer stops at a line break
    messages = _messages(lang, f"TO {lang.name.upper()}", masked)
    try:
        if PLAIN:
            answer = {"text": local_llm.chat_text(messages, role="translate", model=model, temperature=0.0,
                                                  max_tokens=min(1500, 40 + 2 * len(masked)), timeout=TIMEOUT,
                                                  options=_OPTIONS, stop=_STOP)}
        else:
            answer = local_llm.chat_json(messages, _FROM_ENGLISH_SCHEMA, role="translate", model=model,
                                         temperature=0.0, max_tokens=min(2000, 80 + 3 * len(masked)),
                                         timeout=TIMEOUT, options=_OPTIONS)
    except Exception as e:
        print(f"Couldn't translate a reply ({type(e).__name__}: {str(e)[:100]}); kept it in English.", flush=True)
        return unit, False
    out = str(answer.get("text") or "").strip()
    problems = check_reply(lang, masked, out, kept)
    if problems:
        print(f"A reply translation was rejected ({'; '.join(problems)}): {out[:120]!r}", flush=True)
        return unit, False
    return marker + restore(out, kept), True


def check_reply(lang: Language, english: str, translated: str, kept: list) -> list:
    problems = []
    if not _letters(lang).search(translated):
        problems.append(f"no {lang.name}")
    if _FOREIGN_SCRIPTS.search(translated):
        problems.append("another script appeared")
    if not _markers_intact(translated, kept):
        problems.append("a file name/path/code was lost")
    lost = [n for n in _NUMBER.findall(_MARKER.sub(" ", english)) if n not in translated]
    if lost:
        problems.append(f"lost the number {', '.join(lost[:3])}")
    ratio = len(translated) / max(1, len(english))
    if ratio < 0.3 or ratio > 2.5:
        problems.append(f"length ratio {ratio:.1f}")
    return problems
