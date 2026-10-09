"""What keeps a Hebrew (or any) request quick on an 8 GB GPU, found from a real installed session where one sentence
took two minutes: the local model has to fit next to the speech models (local_llm.gpu_options), the two
translation directions share a cached prompt, plain Hebrew talk is answered in one call, a failing translator is
reported at once instead of queuing more calls, and every request leaves one timing line in the log."""
import time

import pytest

import language
import local_llm
import sandbox


# ---------------------------------------------------------------- fitting a model into the GPU

@pytest.fixture
def gpu(monkeypatch):
    state = {"loaded": {}, "memory": (8188, 3200), "unloaded": [], "measured": 0}

    def memory():
        state["measured"] += 1
        return state["memory"]

    def post(url, json=None, timeout=None):
        if url.endswith("/api/generate") and json.get("keep_alive") == 0:
            state["unloaded"].append(json["model"])
            gone = state["loaded"].pop(json["model"], None)
            if gone:   # its memory comes back
                total, used = state["memory"]
                state["memory"] = (total, used - int(gone["size_vram"] / 2 ** 20))
        return None
    monkeypatch.setattr(local_llm, "gpu_memory", memory)
    monkeypatch.setattr(local_llm, "_loaded", lambda: dict(state["loaded"]))
    monkeypatch.setattr(local_llm, "_shape", lambda model: (33, 4100.0, 128.0))   # DictaLM-like: 33 layers
    monkeypatch.setattr(local_llm.requests, "post", post)
    monkeypatch.setenv("JERVIS_GPU_FIT", "on")
    local_llm._gpu_plans.clear()
    yield state
    local_llm._gpu_plans.clear()


def test_a_model_that_fits_goes_entirely_on_the_gpu(gpu):
    gpu["memory"] = (8188, 1100)          # only the desktop: 7 GB free
    assert local_llm.gpu_options("dicta", 4096) == {}


def test_a_model_that_doesnt_fit_gets_only_the_layers_that_do(gpu):
    gpu["memory"] = (8188, 3700)          # desktop + speech models + another app: ~4.5 GB free
    options = local_llm.gpu_options("dicta", 4096)
    need = 4100 + 128 * 4                 # weights + 4k of cache
    free = 8188 - 3700 - local_llm.GPU_MARGIN_MB - local_llm._COMPUTE_MB
    assert options == {"num_gpu": int(free / (need / 33))}
    assert 0 < options["num_gpu"] < 33


def test_the_plan_is_kept_while_the_model_stays_loaded(gpu):
    gpu["memory"] = (8188, 3700)
    first = local_llm.gpu_options("dicta", 4096)
    gpu["loaded"]["dicta"] = {"size_vram": 3.5e9}
    gpu["memory"] = (8188, 7500)          # the model itself now fills the GPU: no re-plan, no reload
    measured = gpu["measured"]
    assert local_llm.gpu_options("dicta", 4096) == first
    assert gpu["measured"] == measured


def test_loading_a_model_unloads_the_other_one_first(gpu):
    gpu["loaded"]["coder"] = {"size_vram": 5e9}
    local_llm.gpu_options("dicta", 4096)
    assert gpu["unloaded"] == ["coder"]


def test_a_load_has_the_gpu_to_itself_but_a_loaded_model_doesnt_wait(gpu):
    slot = local_llm.gpu_slot("dicta", 4096)
    with slot:
        assert slot.held and local_llm._load_lock.locked()   # loading: nothing else loads meanwhile
    assert not local_llm._load_lock.locked()
    gpu["loaded"]["dicta"] = {"size_vram": 4.6e9}
    slot = local_llm.gpu_slot("dicta", 4096)
    with slot:
        assert not slot.held                                  # already loaded with its plan: no waiting


def _enter_in_thread(model, entered):
    import threading
    slot = local_llm.gpu_slot(model, 4096)
    release = threading.Event()

    def run():
        with slot:
            entered.append(model)
            release.wait(5)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return release, thread


def _settle():
    time.sleep(0.15)


def test_a_call_to_another_model_waits_its_turn_but_the_same_model_doesnt(gpu):
    """The real session: a translation started while the coder was loading for a program; both loaded at once
    (10-13 s loads, both models in memory, the computer short of RAM)."""
    gpu["loaded"]["coder"] = {"size_vram": 5e9}
    entered = []
    coder_done, coder = _enter_in_thread("coder", entered)
    _settle()
    dicta_done, dicta = _enter_in_thread("dicta", entered)
    second_done, second = _enter_in_thread("coder", [])
    _settle()
    assert entered == ["coder"]                       # the translation waits for the coder's answer
    coder_done.set(), coder.join(2)
    _settle()
    assert entered == ["coder", "dicta"]              # ...and goes next: the later coder call doesn't jump the line
    dicta_done.set(), dicta.join(2), second_done.set(), second.join(2)
    assert not local_llm._calls and not local_llm._queue


def test_calls_to_one_model_run_together(gpu):
    gpu["loaded"]["dicta"] = {"size_vram": 4.6e9}
    local_llm._gpu_plans["dicta"] = (4096, None)
    entered = []
    first_done, first = _enter_in_thread("dicta", entered)
    second_done, second = _enter_in_thread("dicta", entered)
    _settle()
    assert entered == ["dicta", "dicta"]
    first_done.set(), second_done.set(), first.join(2), second.join(2)
    assert not local_llm._calls


def test_a_failed_plan_gives_the_gpu_back(gpu, monkeypatch):
    def broken(model, num_ctx):
        raise RuntimeError("nvidia-smi hung")
    monkeypatch.setattr(local_llm, "gpu_options", broken)
    with pytest.raises(RuntimeError):
        with local_llm.gpu_slot("dicta", 4096):
            pass
    assert not local_llm._calls and not local_llm._load_lock.locked()


def test_no_nvidia_gpu_means_no_plan(gpu, monkeypatch):
    monkeypatch.setattr(local_llm, "gpu_memory", lambda: None)
    assert local_llm.gpu_options("dicta", 4096) == {}


def test_the_fit_can_be_switched_off(gpu, monkeypatch):
    monkeypatch.setenv("JERVIS_GPU_FIT", "off")
    gpu["memory"] = (8188, 7000)
    assert local_llm.gpu_options("dicta", 4096) == {}


def test_ollamas_timings_are_logged():
    line = local_llm._timing({"load_duration": 4.2e9, "prompt_eval_duration": 0.3e9, "eval_count": 20,
                              "eval_duration": 0.5e9})
    assert line == " (load 4.2s, prompt 0.3s, 20 tokens at 40/s)"


# ---------------------------------------------------------------- translation: one cached prompt, exact numbers

def test_both_directions_share_everything_but_the_last_message():
    there = language._to_english_messages(language.HEBREW, "תעשה את הגג אדום", "")
    back = language._messages(language.HEBREW, "TO HEBREW", "Done.")
    assert there[:-1] == back[:-1]
    assert there[-1]["content"].startswith("TO ENGLISH:") and back[-1]["content"].startswith("TO HEBREW:")


def test_numbers_in_replies_travel_as_markers():
    masked, kept = language.protect(r"I built 8 windows at 14:32, saved to C:\x\a.blend.", numbers=True)
    assert masked == "I built [1] windows at [2], saved to [3]." and kept == ["8", "14:32", r"C:\x\a.blend"]
    assert language.protect("8 windows")[1] == []   # requests keep their numbers in the text


def test_a_failing_translator_is_an_error_not_a_missing_one(monkeypatch):
    language._cache.clear()
    monkeypatch.setattr(language, "translator", lambda: local_llm.DICTALM)

    def slow(*a, **k):
        raise local_llm.LocalAIUnavailable("the local AI didn't answer (ReadTimeout)")
    monkeypatch.setattr(language.local_llm, "chat_json", slow)
    monkeypatch.setattr(language.local_llm, "chat_text", slow)
    heard = language.to_english("תכתוב לי שיר על הים")
    assert heard.status == "unavailable" and "ReadTimeout" in heard.error
    monkeypatch.setattr(language, "translator", lambda: None)
    language._cache.clear()
    assert language.to_english("תכתוב לי שיר על הים").error == ""


def test_the_translation_timeout_is_interactive():
    assert language.TIMEOUT <= 60


# ---------------------------------------------------------------- the app

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
def turn(sandboxed, monkeypatch):
    monkeypatch.setattr(app, "local_llm_only", lambda: True)
    monkeypatch.setattr(app.local_llm, "role_model", lambda role: local_llm.DICTALM)
    app.current_turn.update(language="he", original="מה שלומך היום?", translated=True)
    asked = []

    class Reply:
        def __init__(self, text):
            self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]

    def chat(**kwargs):
        asked.append(kwargs)
        return Reply("אני מצוין, תודה!")
    monkeypatch.setattr(app.local_llm, "chat", chat)
    yield asked
    app.current_turn.update(language="en", original="", translated=False)


def test_hebrew_talk_is_answered_in_hebrew_in_one_call(turn):
    reply = app.answer_in_users_language([{"role": "system", "content": "x"}, {"role": "user", "content": "How are you"}],
                                         "How are you today?")
    assert reply == "אני מצוין, תודה!"
    assert len(turn) == 1 and turn[0]["role"] == "hebrew"
    assert turn[0]["messages"][-1]["content"] == "מה שלומך היום?"   # the words as said, not the translation


@pytest.mark.parametrize("english", ["Play Bohemian Rhapsody on Spotify", "What is 7 times 8?",
                                     "Google the weather in Tel Aviv"])
def test_tools_and_numbers_keep_the_english_path(turn, english):
    assert app.answer_in_users_language([{"role": "system", "content": "x"}], english) is None
    assert turn == []


def test_english_turns_and_the_online_ai_keep_the_english_path(turn, monkeypatch):
    app.current_turn.update(translated=False)
    assert app.answer_in_users_language([{"role": "system", "content": "x"}], "How are you today?") is None
    app.current_turn.update(translated=True)
    monkeypatch.setattr(app, "local_llm_only", lambda: False)
    assert app.answer_in_users_language([{"role": "system", "content": "x"}], "How are you today?") is None
    assert turn == []


def test_english_talk_uses_the_loaded_bilingual_model_instead_of_swapping(turn, monkeypatch):
    app.current_turn.update(language="en", original="Tell me a short joke.", translated=False)
    monkeypatch.setattr(app.local_llm, "role_model",
                        lambda role: "qwen2.5-coder:7b" if role == "chat" else local_llm.DICTALM)
    loaded = {local_llm.DICTALM}
    monkeypatch.setattr(app.local_llm, "is_loaded", lambda model: model in loaded)

    class Reply:
        choices = [type("C", (), {"message": type("M", (), {"content": "Why did the robot cross the road?"})()})()]
    monkeypatch.setattr(app.local_llm, "chat", lambda **kwargs: turn.append(kwargs) or Reply())
    assert app.answer_in_users_language([{"role": "system", "content": "x"}], "Tell me a short joke.") ==         "Why did the robot cross the road?"
    assert turn[-1]["role"] == "translate" and turn[-1]["messages"][-1]["content"] == "Tell me a short joke."
    loaded.add("qwen2.5-coder:7b")   # the chat model is loaded: it answers, as before
    assert app.answer_in_users_language([{"role": "system", "content": "x"}], "Tell me a short joke.") is None


def test_a_failing_translator_is_answered_at_once_without_more_calls(sandboxed, monkeypatch):
    shown = []
    monkeypatch.setattr(app, "broadcast", lambda sender, text="", **k: shown.append(str(text)))
    monkeypatch.setattr(app, "speak", lambda text: None)
    failed = language.Understanding("תכתוב לי שיר", "he", False, "", "unavailable", error="ReadTimeout")
    monkeypatch.setattr(app.language, "to_english", lambda text, previous="": failed)
    handled = []
    monkeypatch.setattr(app, "handle_command", lambda *a, **k: handled.append(a))
    app.pending_translation = None
    assert app.understand_language("תכתוב לי שיר") is None
    assert handled == [] and "לא ענתה בזמן" in shown[-1]


def test_every_request_leaves_one_timing_line_without_its_words(sandboxed, capsys):
    timer = app.TurnTimer()
    timer.start("spoken", time.time() - 2.0)
    timer.mark("stt", 0.8, "Local Whisper")
    with timer.timed("command"):
        pass
    timer.finish()
    timer.finish()   # once only
    out = capsys.readouterr().out.strip().splitlines()
    lines = [line for line in out if line.startswith("Turn 1")]
    assert len(lines) == 1 and "stt 0.8s (Local Whisper)" in lines[0] and "total 2." in lines[0]


def test_the_first_model_warmed_is_the_one_the_conversation_needs(monkeypatch):
    import local_ai
    monkeypatch.setattr(local_ai.local_llm, "role_model", lambda role: local_llm.DICTALM)
    monkeypatch.delenv("JERVIS_REPLY_LANGUAGE", raising=False)
    language.set_reply_language("he")
    assert local_ai.first_role() == "translate"
    language.set_reply_language("en")
    assert local_ai.first_role() == "chat"
