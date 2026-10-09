"""Hebrew (and mixed Hebrew-English) around Jervis's English pipeline: language.py, the bilingual speech recognizer
(stt_local.py), the Hebrew voice (osal.py) and how app.py puts them together.

These run sandboxed with a fake translation model, so they're fast and deterministic; the same cases with the real
models are in test_language_real.py. The letters A-P name the cases the Hebrew support was specified with.
"""
import os
import time

import pytest

import language
import local_llm
import sandbox
import stt_local


@pytest.fixture
def fake_translator(monkeypatch):
    """language.py with a fake DictaLM: `answers` maps what's sent (the last user message) to the JSON it returns."""
    answers, sent = {}, []

    def chat_json(messages, schema, **options):
        said = messages[-1]["content"]
        if said.startswith("TO "):   # the job ("TO ENGLISH:" / "TO HEBREW:") is the first line
            said = said.split("\n", 1)[1]
        sent.append(said)
        if "english" in schema["properties"]:
            text = said.split("\n")[-1]
            return answers.get(text, {"real_words": True, "english": f"<{text}>"})
        return {"text": answers.get(said, "תשובה בעברית")}

    def chat_text(messages, **options):   # the same answers, in plain text (language.PLAIN, the default)
        to_english = messages[-1]["content"].startswith("TO ENGLISH:")
        answer = chat_json(messages, {"properties": {"english": {}} if to_english else {}})
        if to_english:
            return answer["english"] if answer.get("real_words", True) else language.GARBLED
        return answer["text"]
    monkeypatch.setattr(language.local_llm, "chat_json", chat_json)
    monkeypatch.setattr(language.local_llm, "chat_text", chat_text)
    monkeypatch.setattr(language, "translator", lambda: local_llm.DICTALM)
    language._cache.clear()
    yield answers, sent
    language._cache.clear()


# ---------------------------------------------------------------- which language

@pytest.mark.parametrize("text, code, mixed", [
    ("Open Blender and create a detailed house", "en", False),
    ("תפתח את בלנדר", "he", False),
    ("תפתח Blender", "he", True),
    ("hey Jervis תפתח את בלנדר", "he", False),     # the wake phrase isn't English speech
    ("", "", False),
    ("42", "", False),
])
def test_detect(text, code, mixed):
    assert language.detect(text) == (code, mixed)


@pytest.mark.parametrize("text, switch", [
    ("תעשה את הגג אדום", "he"),
    ("make the roof red", "en"),
    ("OK", ""),            # a Hebrew speaker's "OK" doesn't switch Jervis to English
    ("hey Jervis", ""),
    ("yes", ""),
])
def test_turn_language(text, switch):
    assert language.turn_language(text) == switch


# ---------------------------------------------------------------- A. English is untouched

def test_a_english_passes_through_without_any_model(fake_translator):
    _answers, sent = fake_translator
    heard = language.to_english("make the roof red", previous="create a house")
    assert (heard.status, heard.english, heard.translated) == ("same", "make the roof red", False)
    assert sent == []


def test_a_replies_stay_english_for_an_english_speaker(fake_translator):
    _answers, sent = fake_translator
    assert language.to_user_language("Done — I opened Blender.", "en") == "Done — I opened Blender."
    assert sent == []


# ---------------------------------------------------------------- B, C. Hebrew and mixed

def test_b_hebrew_is_translated_by_the_model(fake_translator):
    answers, sent = fake_translator
    answers["תיצור לי בית מפורט"] = {"real_words": True, "english": "Create a detailed house"}
    heard = language.to_english("תיצור לי בית מפורט")
    assert (heard.status, heard.method, heard.english) == ("ok", "model", "Create a detailed house")
    assert heard.original == "תיצור לי בית מפורט"   # the words as said are kept (shown, and logged)


def test_b_everyday_commands_use_the_rules_without_a_model(fake_translator):
    _answers, sent = fake_translator
    heard = language.to_english("תפתח את בלנדר")
    assert (heard.method, heard.english) == ("rules", "open Blender") and sent == []


def test_c_mixed_speech_must_keep_its_english_words(fake_translator):
    answers, _sent = fake_translator
    answers["תיצור לי detailed house ב-Blender"] = {"real_words": True, "english": "Create a house in Blender"}
    heard = language.to_english("תיצור לי detailed house ב-Blender")
    assert heard.mixed and heard.status == "confirm"          # "detailed" was lost: asked, never just done
    assert any("lost detailed" in p for p in heard.problems)


# ---------------------------------------------------------------- D, E, F, O. follow-ups, corrections, context

def test_d_the_previous_request_goes_along_as_context(fake_translator):
    answers, sent = fake_translator
    answers["תוסיף לו ארובה"] = {"real_words": True, "english": "Add a chimney to it"}
    language.to_english("תוסיף לו ארובה", previous="Create a detailed house")
    assert sent[-1] == "(previous request: Create a detailed house)\nתוסיף לו ארובה"


@pytest.mark.parametrize("english, previous, result", [
    ("I didn't mean the windows", "Make the roof red", "No, I meant the windows"),     # comma lost in speech
    ("No, I didn't mean the windows.", "Make the roof red", "No, I meant the windows"),
    ("I didn't mean the roof", "Make the roof red", "I didn't mean the roof"),         # about that very thing
    ("I didn't mean to delete it", "Make the roof red", "I didn't mean to delete it"),  # an action, not a thing
    ("I didn't mean the windows", "", "I didn't mean the windows"),                    # nothing to correct
])
def test_e_a_spoken_correction_is_read_as_one(english, previous, result):
    assert language._spoken_correction(english, previous) == result


@pytest.mark.parametrize("english, said, result", [
    ("Make the red roof", "תעשה את הגג האדום", "Make the roof red"),   # the ה is barely said
    ("Make the red roof", "תבנה גג אדום", "Make the red roof"),        # building one is something else
    ("Make the roof red", "תעשה את הגג אדום", "Make the roof red"),
])
def test_e_make_the_thing_a_colour(english, said, result):
    assert language._spoken_article(english, said) == result


def test_e_a_correction_keeps_its_no(fake_translator):
    answers, _sent = fake_translator
    answers["לא, משמאל לבית"] = {"real_words": True, "english": "To the left of the house"}
    assert language.to_english("לא, משמאל לבית").english == "No, to the left of the house"


def test_o_reply_language_is_remembered_across_restarts(monkeypatch):
    monkeypatch.delenv("JERVIS_REPLY_LANGUAGE", raising=False)
    language.set_reply_language("he")
    language._state["reply"] = None          # as after a restart
    assert language.reply_language() == "he"
    language.set_reply_language("en")
    assert language.reply_language() == "en"


def test_o_settings_can_fix_the_reply_language(monkeypatch):
    monkeypatch.setenv("JERVIS_REPLY_LANGUAGE", "he")
    language.set_reply_language("en")
    assert language.reply_language() == "he"


# ---------------------------------------------------------------- G. technical terms

def test_g_paths_files_and_code_never_reach_the_model(fake_translator):
    answers, sent = fake_translator
    answers["תריץ את [1] ותפתח את [2]"] = {"real_words": True, "english": "Run [1] and open [2]"}
    heard = language.to_english(r"תריץ את test_app.py ותפתח את C:\Users\me\notes.txt")
    assert heard.english == r"Run test_app.py and open C:\Users\me\notes.txt"
    assert "test_app" not in sent[-1]


def test_g_a_lost_file_name_is_never_used(fake_translator):
    answers, _sent = fake_translator
    answers["תמחק את [1]"] = {"real_words": True, "english": "Delete the file"}
    heard = language.to_english("תמחק את report.txt")
    assert heard.status == "unclear" and heard.english == ""


def test_g_a_hebrew_prefix_stays_outside_the_file_name():
    masked, kept = language.protect("תשנה את שם הקובץ ל-final_report.txt")
    assert kept == ["final_report.txt"] and masked.endswith("ל-[1]")


def test_g_a_sentence_full_stop_stays_outside_a_path():
    _masked, kept = language.protect(r"Saved to C:\Users\me\scene.blend.")
    assert kept == [r"C:\Users\me\scene.blend"]


# ---------------------------------------------------------------- N. uncertain or failed translations

@pytest.mark.parametrize("english, problem", [
    ("Delete the window", "a delete/close/send/cancel word appeared"),   # the Hebrew said nothing of the sort
    ("Close the browser", "a delete/close/send/cancel word appeared"),
    ("Make it bigger", "a negation disappeared"),                          # "don't" was lost
])
def test_n_meaning_changes_are_asked_about(fake_translator, english, problem):
    answers, _sent = fake_translator
    said = "אל תגדיל את זה" if "negation" in problem else "תצבע את החלון"
    answers[said] = {"real_words": True, "english": english}
    heard = language.to_english(said)
    assert heard.status == "confirm" and problem in heard.problems


def test_n_a_dont_that_stays_a_dont_is_fine(fake_translator):
    answers, _sent = fake_translator
    answers["אל תמחק את הקובץ"] = {"real_words": True, "english": "Don't delete the file"}
    assert language.to_english("אל תמחק את הקובץ").status == "ok"


def test_n_gibberish_is_not_guessed(fake_translator):
    answers, _sent = fake_translator
    answers["פלורגנים מנוגבים בקרזל"] = {"real_words": False, "english": ""}
    assert language.to_english("פלורגנים מנוגבים בקרזל").status == "unclear"


def test_n_an_invented_name_is_asked_about(fake_translator):
    answers, _sent = fake_translator
    answers["תיצור לי דיטייל דאוס בטבילין דיאר"] = {"real_words": True,
                                                   "english": "Create a detailed house in Tbilisi, Georgia"}
    heard = language.to_english("תיצור לי דיטייל דאוס בטבילין דיאר")
    # noted, but a harmless request isn't held up by a "did I understand you?" (names are what transliteration
    # makes: every Hebrew song title asked that question)
    assert heard.status == "ok" and any("Tbilisi" in p for p in heard.problems)


def test_n_an_invented_name_in_a_risky_request_is_asked_about(fake_translator):
    answers, _sent = fake_translator
    answers["תמחק את הקובץ דוח"] = {"real_words": True, "english": "Delete the file Report"}
    heard = language.to_english("תמחק את הקובץ דוח")
    assert heard.status == "confirm"


def test_n_hebrew_left_in_the_translation_is_rejected(fake_translator):
    answers, _sent = fake_translator
    answers["תשנה את שם הקובץ"] = {"real_words": True, "english": "Rename הקובץ"}
    assert language.to_english("תשנה את שם הקובץ").status == "unclear"


def test_n_a_model_that_isnt_a_checked_translator_is_noted_not_asked(fake_translator, monkeypatch):
    answers, _sent = fake_translator
    monkeypatch.setattr(language, "translator", lambda: "qwen3:8b")
    answers["תעשה את הגג אדום"] = {"real_words": True, "english": "Make the roof red"}
    heard = language.to_english("תעשה את הגג אדום")
    assert heard.status == "ok" and any("not a checked translator" in p for p in heard.problems)


def test_n_no_translator_leaves_the_words_as_they_were(monkeypatch):
    language._cache.clear()
    monkeypatch.setattr(language, "translator", lambda: None)
    heard = language.to_english("תכתוב לי שיר על הים")
    assert heard.status == "unavailable" and not heard.translated


def test_n_a_translator_that_fails_leaves_the_words_as_they_were(monkeypatch):
    language._cache.clear()
    monkeypatch.setattr(language, "translator", lambda: local_llm.DICTALM)

    def broken(*a, **k):
        raise local_llm.LocalAIUnavailable("the local AI didn't answer")
    monkeypatch.setattr(language.local_llm, "chat_json", broken)
    monkeypatch.setattr(language.local_llm, "chat_text", broken)
    assert language.to_english("תכתוב לי שיר על הים").status == "unavailable"


# ---------------------------------------------------------------- P. answering in the user's language

def test_p_fixed_phrases_and_greetings_need_no_model(fake_translator):
    _answers, sent = fake_translator
    assert language.to_user_language("On it.", "he") == "אני על זה."
    assert language.to_user_language("Okay.", "he") == "בסדר."
    assert language.to_user_language("Good evening, Sir. How can I help you today?", "he") == \
        "ערב טוב, אדוני. במה אוכל לעזור היום?"
    assert sent == []


def test_p_code_blocks_are_never_translated(fake_translator):
    answers, sent = fake_translator
    answers["Here it is:"] = "הנה זה:"
    out = language.to_user_language("Here it is:\n\n```python\nprint('hi')\n```", "he")
    assert out == "הנה זה:\n\n```python\nprint('hi')\n```"
    assert all("print" not in s for s in sent)


def test_p_list_items_keep_their_markers(fake_translator):
    answers, _sent = fake_translator
    answers["first thing"], answers["second thing"] = "דבר ראשון", "דבר שני"
    assert language.to_user_language("- first thing\n- second thing", "he") == "- דבר ראשון\n- דבר שני"


def test_p_a_bad_reply_translation_keeps_the_english(fake_translator):
    answers, _sent = fake_translator
    answers["It's [1]."] = "השעה."           # dropped the time
    reply = "It's 14:32 in report_1432.txt."
    answers["It's 14:32 in [1]."] = "השעה."   # lost the number and the file
    assert language.to_user_language(reply, "he") == reply


def test_p_an_unchecked_model_never_writes_the_reply(fake_translator, monkeypatch):
    monkeypatch.setattr(language, "translator", lambda: "qwen3:8b")
    assert language.to_user_language("Done — I opened Blender.", "he") == "Done — I opened Blender."


def test_p_the_confirmation_question_says_the_meaning_back(fake_translator):
    answers, _sent = fake_translator
    answers["Lower the chimney"] = "תנמיך את הארובה"
    heard = language.Understanding("תוריד את הארובה", "he", False, "Lower the chimney", "confirm")
    shown, spoken = language.confirm_question(heard)
    assert "תנמיך את הארובה" in shown and "Lower the chimney" in shown
    assert "(כן / לא)" not in spoken


# ---------------------------------------------------------------- the speech recognizer

@pytest.mark.parametrize("probabilities, language_", [
    ({"en": 0.98, "he": 0.01}, "en"),
    ({"en": 0.80, "he": 0.30}, "he"),     # sure-ish, but Hebrew is too likely: Hebrew writes mixed speech too
    ({"en": 0.40, "he": 0.20}, "he"),     # mixed speech splits the vote
    ({"he": 0.99}, "he"),
])
def test_language_decision(probabilities, language_):
    assert stt_local.choose_language(probabilities) == language_


def _fake_models(monkeypatch, present, gpu):
    monkeypatch.setattr(stt_local, "has", lambda name: name in present)
    monkeypatch.setattr(stt_local, "gpu_possible", lambda: gpu)
    monkeypatch.setattr(stt_local, "BILINGUAL", True)


def test_setup_gpu_pair(monkeypatch):
    _fake_models(monkeypatch, {"turbo", "ivrit-turbo"}, True)
    assert stt_local.setup() == stt_local.Setup("turbo", "turbo", "ivrit-turbo", "cuda")


def test_setup_english_keeps_working_while_the_hebrew_models_download(monkeypatch):
    _fake_models(monkeypatch, {"base.en"}, True)
    assert stt_local.setup() == stt_local.Setup(None, "base.en", None, "cpu")
    assert stt_local.ready() is stt_local.available()


def test_setup_cpu(monkeypatch):
    _fake_models(monkeypatch, {"small", "base.en"}, False)
    assert stt_local.setup() == stt_local.Setup("small", "base.en", "small", "cpu")


def test_setup_gpu_failure_uses_what_is_on_disk(monkeypatch):
    _fake_models(monkeypatch, {"turbo", "ivrit-turbo", "base.en"}, False)
    s = stt_local.setup()
    assert s.device == "cpu" and s.hebrew == "ivrit-turbo" and s.english == "base.en"


def test_english_only_setting(monkeypatch):
    monkeypatch.setattr(stt_local, "BILINGUAL", False)
    assert stt_local.plan() == ("base.en",)


def test_invisible_right_to_left_marks_are_removed():
    assert "\u202bתודה רבה.".translate(stt_local._INVISIBLE) == "תודה רבה."


# ---------------------------------------------------------------- local models and setup

def test_translation_uses_dictalm_when_installed():
    models = ["qwen2.5-coder:7b", local_llm.DICTALM, "qwen3:8b"]
    assert local_llm.model_for("translate", models) == local_llm.DICTALM
    assert local_llm.model_for("hebrew", models) == local_llm.DICTALM
    assert local_llm.model_for("agent", models) == "qwen2.5-coder:7b"   # the agent keeps its model


def test_dictalm_is_loaded_small_enough_to_share_the_gpu(monkeypatch):
    def unreachable(*a, **k):
        raise local_llm.requests.RequestException("no")
    monkeypatch.setattr(local_llm.requests, "get", unreachable)
    assert local_llm._context_for(local_llm.DICTALM, 8192) == local_llm.SMALL_CONTEXT_MODELS["dictalm"] <= 4096
    assert local_llm._context_for("qwen2.5-coder:7b") == local_llm.NUM_CTX


def test_setup_has_a_hebrew_step_that_never_blocks_the_rest(monkeypatch):
    import local_ai
    manager = local_ai.LocalAI()
    assert "language" in [sid for sid, _label in manager.STEPS]
    monkeypatch.setattr(local_ai, "wants_hebrew", lambda: True)
    monkeypatch.setattr(manager, "_installed", lambda: [])
    monkeypatch.setattr(manager, "_check_disk", lambda need: None)

    def failing_pull(model, label, step="models"):
        raise local_ai.SetupError("no internet", "try later")
    monkeypatch.setattr(manager, "_pull", failing_pull)
    import hebrew_voice
    monkeypatch.setattr(hebrew_voice, "downloaded", lambda: False)

    def offline(progress=None):   # (a test never downloads the real voice)
        raise OSError("no internet")
    monkeypatch.setattr(hebrew_voice, "ensure", offline)
    manager._ensure_hebrew()   # doesn't raise: English works without it
    step = next(s for s in manager.state["steps"] if s["id"] == "language")
    assert step["state"] == "skipped"


def test_settings_offer_the_languages():
    import settings
    keys = {s["key"]: s for s in settings.SCHEMA}
    assert [c[0] for c in keys["JERVIS_STT_LANGUAGE"]["choices"]] == ["auto", "en"]
    assert keys["JERVIS_STT_LANGUAGE"]["default"] == "auto"
    assert [c[0] for c in keys["JERVIS_REPLY_LANGUAGE"]["choices"]] == ["auto", "en", "he"]


def test_hebrew_speech_uses_the_natural_voice_when_it_is_there(monkeypatch):
    import hebrew_voice
    import osal
    said = []
    monkeypatch.setattr(osal, "IS_WIN", True)
    monkeypatch.setattr(osal, "IS_MAC", False)
    monkeypatch.delenv("JERVIS_SPEECH_OUT", raising=False)
    monkeypatch.setattr(hebrew_voice, "available", lambda: True)
    monkeypatch.setattr(hebrew_voice, "speak",
                        lambda text, volume, out_path=None: said.append((text, volume)) or "playing")
    assert osal.speech_process("סיימתי — פתחתי את Blender.", 40) == "playing"
    assert said == [("סיימתי — פתחתי את Blender.", 40)]


def test_hebrew_voice_can_be_cut_off_mid_sentence(monkeypatch):
    """"Stop" (or talking over him) cuts the Hebrew voice off at once, not when the sentence ends — Windows can't
    stop a sound played synchronously from memory, so it plays from a file, asynchronously."""
    import io
    import sys
    import time
    import types
    import wave
    import hebrew_voice
    calls = []
    fake = types.SimpleNamespace(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4,
                                 PlaySound=lambda sound, flags: calls.append((sound, flags)))
    monkeypatch.setitem(sys.modules, "winsound", fake)   # nothing is played
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(22050)
        w.writeframes(bytes(2 * 22050 * 30))   # 30 seconds
    playing = hebrew_voice.Playing(buf.getvalue())
    assert abs(playing.duration - 30) < 0.01 and playing.poll() is None
    started = time.time()
    playing.terminate()
    assert playing.wait(timeout=5) == 0 and time.time() - started < 1
    assert calls[0][1] == 1 | 2 | 4 and calls[-1] == (None, 0)
    assert not os.path.exists(calls[0][0])   # the temporary file is gone


def test_hebrew_voice_reads_its_tokenizer_from_disk_not_the_internet(monkeypatch, tmp_path):
    import phonikud_onnx.model as model
    import tokenizers
    import hebrew_voice
    monkeypatch.setattr(hebrew_voice, "folder", lambda: str(tmp_path))
    read = []
    monkeypatch.setattr(tokenizers.Tokenizer, "from_file", staticmethod(lambda path: read.append(path) or "local"))
    online = model.Tokenizer

    class FakePhonikud:
        def __init__(self, path):
            self.tokenizer = model.Tokenizer.from_pretrained("dicta-il/dictabert-large-char-menaked")

    assert hebrew_voice._diacritizer(FakePhonikud).tokenizer == "local"
    assert read == [os.path.join(str(tmp_path), "tokenizer.json")] and "tokenizer.json" in hebrew_voice.FILES
    assert model.Tokenizer is online   # put back


def test_hebrew_voice_says_file_names_not_paths_and_not_minus():
    import hebrew_voice
    assert hebrew_voice.spoken_form(r"שמרתי ב-C:\Users\me\Documents\scene.blend.") == "שמרתי בscene."
    assert hebrew_voice.spoken_form("היום ה-6 באוקטובר") == "היום ה6 באוקטובר"   # not "minus six"
    assert hebrew_voice.spoken_form("כתבתי את hello_world.py.") == "כתבתי את hello world."


def test_hebrew_speech_goes_to_windows_voice_without_the_natural_one(monkeypatch):
    import hebrew_voice
    import osal
    monkeypatch.setattr(hebrew_voice, "available", lambda: False)
    started = []
    monkeypatch.setattr(osal, "IS_WIN", True)
    monkeypatch.setattr(osal, "IS_MAC", False)
    monkeypatch.setattr(osal.subprocess, "Popen", lambda cmd, **kw: started.append(kw["env"]) or object())
    osal.speech_process("סיימתי — פתחתי את Blender.", 40)
    osal.speech_process("Done.", 40)
    assert started[0]["JERVIS_HEBREW"] == "1" and started[0]["JERVIS_VOLUME"] == "40"
    assert started[1]["JERVIS_HEBREW"] == "0"
    assert "Windows.Media.SpeechSynthesis" in osal._WIN_SPEECH and "AudioVolume" in osal._WIN_SPEECH


# ---------------------------------------------------------------- through the app (sandboxed)

app = None


@pytest.fixture(scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture
def hebrew_app(sandboxed, monkeypatch, fake_translator):
    monkeypatch.delenv("JERVIS_REPLY_LANGUAGE", raising=False)
    shown, spoken = [], []
    monkeypatch.setattr(app, "broadcast", lambda sender, text="", **k: shown.append(str(app.localized(text))))
    monkeypatch.setattr(app, "speak", lambda text: spoken.append(text))
    app.pending_translation = None
    app.last_request.update(text="", at=0.0)
    language.set_reply_language("en")
    sandbox.reset()
    yield fake_translator, shown, spoken
    language.set_reply_language("en")


def test_a_english_reaches_the_pipeline_unchanged(hebrew_app):
    (_answers, sent), shown, _spoken = hebrew_app
    assert app.understand_language("make the roof red") == "make the roof red"
    assert sent == [] and shown == [] and language.reply_language() == "en"


def test_b_hebrew_reaches_the_pipeline_in_english_and_switches_the_replies(hebrew_app):
    (answers, _sent), _shown, _spoken = hebrew_app
    answers["תעשה את הגג אדום"] = {"real_words": True, "english": "Make the roof red"}
    assert app.understand_language("תעשה את הגג אדום") == "Make the roof red"
    assert language.reply_language() == "he"
    assert app.last_request["text"] == "Make the roof red"   # what the next follow-up is read against


def test_h_the_kind_of_input_survives_translation(hebrew_app):
    (answers, _sent), _shown, _spoken = hebrew_app
    answers["תאר את התמונה"] = {"real_words": True, "english": "Describe the picture"}
    out = app.understand_language(app.ImageCaption("תאר את התמונה"))
    assert isinstance(out, app.ImageCaption) and out == "Describe the picture"
    answers["תפתח את הקובץ"] = {"real_words": True, "english": "Open the file"}
    phone = app.understand_language(app.PhoneVoiceInput("תפתח את הקובץ", "session-1"))
    assert isinstance(phone, app.PhoneVoiceInput) and phone.session_id == "session-1"


def test_n_an_unsure_translation_is_asked_about_and_yes_runs_it(hebrew_app):
    (answers, _sent), shown, spoken = hebrew_app
    answers["תוריד את הארובה"] = {"real_words": True, "english": "Lower the chimney"}
    answers["Lower the chimney"] = "תנמיך את הארובה"
    assert app.understand_language("תוריד את הארובה") is None      # nothing runs yet
    assert "תנמיך את הארובה" in shown[-1] and spoken
    assert app.understand_language("כן") == "Lower the chimney"


def test_n_no_cancels_the_unsure_translation(hebrew_app):
    (answers, _sent), shown, _spoken = hebrew_app
    answers["תוריד את הארובה"] = {"real_words": True, "english": "Lower the chimney"}
    assert app.understand_language("תוריד את הארובה") is None
    assert app.understand_language("לא") is None
    assert "לא עשיתי כלום" in shown[-1]
    assert app.pending_translation is None


def test_n_something_else_after_the_question_is_a_new_request(hebrew_app):
    (answers, _sent), _shown, _spoken = hebrew_app
    answers["תוריד את הארובה"] = {"real_words": True, "english": "Lower the chimney"}
    answers["תעשה את הדלת כחולה"] = {"real_words": True, "english": "Make the door blue"}
    app.understand_language("תוריד את הארובה")
    assert app.understand_language("תעשה את הדלת כחולה") == "Make the door blue"


def test_n_unclear_speech_asks_to_hear_it_again(hebrew_app):
    (answers, _sent), shown, _spoken = hebrew_app
    answers["פלורגנים מנוגבים"] = {"real_words": False, "english": ""}
    assert app.understand_language("פלורגנים מנוגבים") is None
    assert "תוכל להגיד את זה שוב" in shown[-1]


def test_l_a_bug_in_the_language_layer_never_loses_the_request(hebrew_app, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("bug")
    monkeypatch.setattr(app.language, "to_english", broken)
    assert app.understand_language("תעשה את הגג אדום") == "תעשה את הגג אדום"


def test_p_replies_are_shown_in_hebrew_keeping_their_kind(hebrew_app):
    (answers, _sent), _shown, _spoken = hebrew_app
    language.set_reply_language("he")
    answers["Here are your messages."] = "הנה ההודעות שלך."
    private = app.localized(app.PrivateReply("Here are your messages."))
    assert isinstance(private, app.PrivateReply) and private == "הנה ההודעות שלך."
    both = app.SpokenReply("Done, all 2 parts.")
    both.spoken = "Done."
    answers["Done, all 2 parts."] = "סיימתי, את שני החלקים."
    out = app.localized(both)
    assert isinstance(out, app.SpokenReply) and out.spoken == "סיימתי."


def test_p_english_replies_are_the_same_object(hebrew_app):
    reply = app.PrivateReply("Here are your messages.")
    assert app.localized(reply) is reply


def test_p_the_spoken_notes_follow_the_reply_language():
    assert app._note("I've put the details on your screen.", "הנה המתכון") == "שמתי את הפרטים על המסך."
    assert app._note("I've put the details on your screen.", "Here's the recipe") == \
        "I've put the details on your screen."
    assert app._say_math("x = 10") == "x equals 10"
    assert app._say_math("התשובה היא x = 10") == "התשובה היא x שווה 10"


def test_i_a_program_request_right_after_blender_is_for_the_code_agent(sandboxed, monkeypatch):
    monkeypatch.setattr(app, "blender_last_used", time.time())
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: True)
    said = "Create a Python program that prints 'Hello World'"
    assert not app.is_blender_goal(app.blender_commands.normalize(said), said=said)
    said = "create a cube in Blender"
    assert app.is_blender_goal(app.blender_commands.normalize(said), said=said)


@pytest.mark.parametrize("heard, passive, dropped", [
    ("תודה שצפיתם!", False, True),
    ("תרגום: פלוני", False, True),
    ("תודה רבה.", True, True),      # asleep: the room's noise
    ("תודה רבה.", False, False),    # awake: a real "thank you"
    ("תעשה את הגג אדום", True, False),
    ("Thanks for watching!", False, True),
    ("תרגום לאנגלית של המשפט הזה בבקשה", False, False),   # a real request that starts with "translation"
])
def test_m_hebrew_whisper_hallucinations(sandboxed, heard, passive, dropped):
    assert app.is_whisper_hallucination(heard, passive) is dropped


def test_m_empty_speech_is_nothing(fake_translator):
    assert language.to_english("").status == "same" and language.to_english("   ").english == ""


def test_the_agent_warm_up_doesnt_evict_the_translator(sandboxed, monkeypatch):
    primed = []
    monkeypatch.setattr(app.agent_core.AgentTask, "prime", lambda self: primed.append(1))
    monkeypatch.setattr(app.language, "translator", lambda: local_llm.DICTALM)
    monkeypatch.delenv("JERVIS_REPLY_LANGUAGE", raising=False)
    language.set_reply_language("he")
    app.prime_blender_agent()
    language.set_reply_language("en")
    app.prime_blender_agent()
    assert primed == [1]


# ---------------------------------------------------------------- which speech model stays on the GPU

@pytest.fixture
def resident(monkeypatch):
    """stt_local with the GPU trio on disk, nothing really loaded (fake models), and switches recorded."""
    monkeypatch.setattr(stt_local, "has", lambda name: name in {"small", "turbo", "ivrit-large"})
    monkeypatch.setattr(stt_local, "gpu_possible", lambda: True)
    monkeypatch.setattr(stt_local, "BILINGUAL", True)
    monkeypatch.setattr(stt_local, "HEBREW_MODEL", "ivrit-large")
    monkeypatch.setattr(stt_local, "_models", {})
    switches = []
    monkeypatch.setattr(stt_local, "_switch", lambda: switches.append(stt_local._conversation))
    monkeypatch.setattr(stt_local, "_conversation", "en")
    yield switches


def test_the_gpu_holds_the_detector_and_the_spoken_languages_model(resident):
    s = stt_local.setup()
    assert (s.detector, s.english, s.hebrew) == ("small", "turbo", "ivrit-large")


def test_a_few_english_words_in_a_hebrew_conversation_switch_nothing(resident):
    stt_local._conversation = "he"
    stt_local._models.update({("small", "cuda"): 1, ("ivrit-large", "cuda"): 1})
    assert stt_local._speaking_models(stt_local.setup(), "en") == ("small", "ivrit-large")
    assert resident == []


def test_hebrew_in_an_english_conversation_is_written_now_and_ivrit_comes_after(resident):
    stt_local._models.update({("small", "cuda"): 1, ("turbo", "cuda"): 1})
    english, hebrew = stt_local._speaking_models(stt_local.setup(), "he")
    assert (english, hebrew) == ("turbo", "turbo")   # this sentence: no waiting for a model to load
    assert resident == ["he"]                         # ivrit.ai loads in the background for the next ones


def test_the_ai_model_leaves_room_for_the_speech_model_about_to_load(resident):
    stt_local._models.update({("small", "cuda"): 1, ("turbo", "cuda"): 1})
    assert stt_local.pending_gpu_mb() == 0
    stt_local._conversation = "he"   # switching: ivrit.ai (1.7 GB) replaces turbo (1.1 GB)
    assert stt_local.pending_gpu_mb() == stt_local.GPU_MB["ivrit-large"] - stt_local.GPU_MB["turbo"]


@pytest.mark.parametrize("text, switch", [
    ("Wake up, Jarvis.", ""),             # a Hebrew speaker waking him in English: still Hebrew
    ("open Blender", ""),                 # two English words: not a change of language
    ("can you open Blender please", "en"),
    ("תפתח את בלנדר", "he"),
])
def test_switching_the_conversation_language_takes_real_english(text, switch):
    assert language.turn_language(text) == switch
