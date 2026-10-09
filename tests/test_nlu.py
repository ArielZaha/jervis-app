"""Language understanding (nlu.py): Hebrew / mixed / misheard commands become the canonical English ones the command
handlers know; the model's structured intent is validated before anything runs; unclear commands get a question,
chit-chat never becomes an action. The app tests run in the sandbox (tests/sandbox.py) with a fake model.
"""
import time

import pytest

import nlu
import sandbox
import speech_fixes


@pytest.mark.parametrize("said, canonical", [
    ("תפתח בלנדר", "open Blender"),
    ("Jervis תפתח בלנדר", "open Blender"),
    ("ג'רביס, תיצור קובייה בבקשה", "create a cube"),
    ("תיצור קובייה", "create a cube"),
    ("תיצור cube", "create a cube"),
    ("תיצור עוד אחת", "create another one"),
    ("תעשה אותה פי שתיים יותר גבוהה", "make it two times taller"),
    ("תעשה את ה-cube יותר גדול", "make the cube bigger"),
    ("תזיז את הקובייה השנייה ליד הראשונה", "move the second cube next to the first one"),
    ("תזיז אותה ימינה", "move it right"),
    ("תצבע את הקובייה בכחול", "make the cube blue"),
    ("תסובב אותה 90 מעלות", "rotate it 90 degrees"),
    ("תמחק את הכדור", "delete the sphere"),
    ("תבטל את זה", "undo"),
    ("תעשה את זה שוב", "do it again"),
    ("תפסיק לשלוט במחשב", "stop controlling my computer"),
    ("תפתח ספוטיפיי", "open Spotify"),
    ("תפעיל את השיר הזה", "resume the music"),
    ("תחזור לבלנדר", "go back to blender"),
    ("תחזור ל-Blender", "go back to blender"),
    ("תכוון טיימר לחמש דקות", "set a timer for five minutes"),
    ("תוריד את הווליום", "volume down"),
    ("תגביר", "volume up"),
    ("open Spotify ותפעיל את השיר הזה", "open Spotify and resume the music"),
    ("open spot if I", "open spotify"),
    ("Jervis stay control", "Jervis stay in control of my computer"),
    ("make the cube girl", "make the cube bigger"),
])
def test_deterministic_rewrites(said, canonical):
    assert nlu.rewrite(said) == canonical


@pytest.mark.parametrize("said", ["Open Spotify.", "Create a cube.", "I spotted a bird", "what's the capital of Japan",
                                  "make it", "", "שלום מה שלומך"])
def test_no_rewrite_for_what_needs_none(said):
    assert nlu.rewrite(said) is None


@pytest.mark.parametrize("heard, fixed", [
    ("Open blend ever", "open blender"),
    ("open blender", "open blender"),
    ("blender is open", "blender is open"),
    ("open spotifi", "open spotify"),
    ("i spotted a bird", "i spotted a bird"),
])
def test_speech_name_fixes(heard, fixed):
    assert speech_fixes.fix_names(heard) == fixed


def test_hebrew_spelling_of_jervis_becomes_the_wake_phrase():
    assert nlu.latin_names("היי ג'רביס") == "hey Jervis"
    assert nlu.latin_names("תתעורר ג׳רוויס") == "wake up Jervis"
    assert nlu.latin_names("שלום עולם") == "שלום עולם"
    assert nlu.latin_names("hello there") == "hello there"


@pytest.mark.parametrize("said, worth", [
    ("make it", True), ("put the ball next to the box", True), ("תעשה משהו", True),
    ("what is this", False), ("מה השעה עכשיו בניו יורק?", False), ("איך מכינים פיצה", False),
    ("I installed Chrome yesterday", False), ("and I will see you in the next video", False),
])
def test_only_commands_and_hebrew_reach_the_model(said, worth):
    assert nlu.worth_understanding(said) is worth


def test_validate_drops_unknown_intents_and_cleans_slots():
    assert nlu.validate({"intent": "format_disk"}) == {"intent": "chat", "confidence": 0.0}
    assert nlu.validate("not json")["intent"] == "chat"
    got = nlu.validate({"intent": "open_app", "app": "Blen`der\n", "confidence": 7, "shape": ""})
    assert got == {"intent": "open_app", "app": "Blender", "confidence": 1.0}


@pytest.mark.parametrize("intent, command", [
    ({"intent": "open_app", "app": "Blender"}, "open Blender"),
    ({"intent": "object_resize", "target": "it", "change": "taller", "times": "2"}, "make it 2 times taller"),
    ({"intent": "object_resize", "target": "it; import os", "change": "bigger"}, "make it bigger"),
    ({"intent": "object_move", "target": "the second cube", "next_to": "the first cube"},
     "move the second cube next to the first cube"),
    ({"intent": "object_color", "target": "the cube", "color": "red"}, "make the cube red"),
    ({"intent": "music_play", "query": ""}, "resume the music"),
    ({"intent": "music_play", "query": "Bohemian Rhapsody", "service": "spotify"}, "play Bohemian Rhapsody on Spotify"),
    ({"intent": "timer", "query": "5 minutes"}, "set a timer for 5 minutes"),
    ({"intent": "blender_build", "description": "a small wooden house in Blender"},
     "in Blender, build a small wooden house"),
    ({"intent": "undo"}, "undo"),
    ({"intent": "object_color", "target": "it", "color": "nicer"}, None),     # not a colour
    ({"intent": "volume", "change": "quieter"}, "volume down"),
    ({"intent": "chat"}, None),
    ({"intent": "object_resize", "target": "it"}, None),                     # no change: nothing safe to do
    ({"intent": "open_app", "app": "Blender", "confidence": 0.3}, None),     # not sure enough
])
def test_render(intent, command):
    assert nlu.render({"confidence": 0.9, **intent}) == command


@pytest.mark.parametrize("said, intent, decision", [
    ("make it", {"intent": "object_resize", "target": "it", "confidence": 0.9}, "clarify"),
    ("take it to a level", {"intent": "clarify", "question": "Which level?", "confidence": 0.3}, "clarify"),
    ("what's the capital of Japan", {"intent": "web_search", "query": "capital of Japan", "confidence": 0.9}, "chat"),
    ("search Google for cats", {"intent": "web_search", "query": "cats", "confidence": 0.9}, "command"),
    ("and see you next video", {"intent": "ignore", "confidence": 0.9}, "ignore"),
    ("hmm", {"intent": "ignore", "confidence": 0.2}, "chat"),
    ("open blend ever", {"intent": "open_app", "app": "Blender", "confidence": 0.9}, "command"),
    ("open the thing", {"intent": "open_app", "app": "", "confidence": 0.4}, "clarify"),
    ("do the thing", {"intent": "repeat", "confidence": 0.9}, "clarify"),          # nothing said "again"
    ("do that one more time", {"intent": "repeat", "confidence": 0.9}, "command"),
    ("get rid of the last bit", {"intent": "undo", "confidence": 0.9}, "clarify"),
    ("תסגור את כרום", {"intent": "close_app", "app": "Spotify", "confidence": 0.9}, "clarify"),   # never said
    ("close blunder", {"intent": "close_app", "app": "Blender", "confidence": 0.9}, "command"),   # misheard
    ("make it", {"intent": "open_app", "app": "Visual Studio Code", "confidence": 0.9}, "clarify"),  # from context
    ("make it", {"intent": "object_color", "target": "it", "color": "yellow", "confidence": 0.9}, "clarify"),
    ("make it", {"intent": "object_resize", "target": "it", "change": "taller", "confidence": 0.9}, "clarify"),
    ("make it blew", {"intent": "object_color", "target": "it", "color": "blue", "confidence": 0.9}, "command"),
    ("תצבע אותה בירוק", {"intent": "object_color", "target": "it", "color": "green", "confidence": 0.9}, "command"),
    ("put more size on the cube", {"intent": "object_resize", "target": "the cube", "change": "bigger",
                                   "confidence": 0.9}, "command"),
    ("תפתח את הדפדפן כרום", {"intent": "open_app", "app": "Chrome", "confidence": 0.9}, "command"),
    ("add a sphere", {"intent": "blender_build", "shape": "sphere", "confidence": 0.9}, "command"),
    ("add a sphere", {"intent": "blender_build", "description": "a sphere", "confidence": 0.9}, "command"),
    ("turn the music down", {"intent": "volume", "change": "down", "confidence": 0.9}, "command"),
])
def test_decide(said, intent, decision):
    assert nlu.decide(said, nlu.validate(intent))[0] == decision


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
def quiet_app(sandboxed, monkeypatch):
    monkeypatch.setattr(app.blender_control.BlenderBridge, "ping", lambda self, timeout=3: False)
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: False)
    monkeypatch.setattr(app.app_launcher, "front_app_window", lambda: None)
    app.pending_clarify = None
    app.control_session = None
    app.last_command.update(text=None, at=0.0)
    monkeypatch.setattr(app, "blender_last_used", 0.0)
    sandbox.reset()
    asked = []

    def model(answer):
        def ask_json(messages, schema, **options):
            asked.append(messages[-1]["content"])
            return answer() if callable(answer) else answer
        monkeypatch.setattr(app.local_llm, "chat_json", ask_json)
    yield model, asked


def test_hebrew_open_app_never_calls_the_model(quiet_app, monkeypatch):
    model, asked = quiet_app
    model({"intent": "chat"})
    opened = []
    monkeypatch.setattr(app, "handle_direct_command", lambda t: opened.append(t) or ("Opening Blender." if
                        t == "open Blender" else None))
    assert app.handle_command("תפתח בלנדר") == "Opening Blender."
    assert opened == ["open Blender"] and asked == []


def test_model_intent_runs_through_the_normal_handlers(quiet_app, monkeypatch):
    model, asked = quiet_app
    model({"intent": "object_resize", "target": "the cube", "change": "bigger", "confidence": 0.9})
    ran = []
    monkeypatch.setattr(app, "handle_direct_command",
                        lambda t: ran.append(t) or ("Made it bigger." if t == "make the cube bigger" else None))
    assert app.handle_command("put more size on the cube") == "Made it bigger."
    assert ran[-1] == "make the cube bigger" and len(asked) == 1
    assert app.last_command["text"] == "make the cube bigger"


def test_unclear_command_asks_and_the_answer_completes_it(quiet_app, monkeypatch):
    model, asked = quiet_app
    model({"intent": "object_resize", "target": "it", "confidence": 0.9})
    ran = []
    monkeypatch.setattr(app, "handle_direct_command",
                        lambda t: ran.append(t) or ("Made it taller." if t == "make it taller" else None))
    question = app.handle_command("make it")
    assert question.endswith("?") and app.pending_clarify["said"] == "make it"
    assert app.handle_command("taller") == "Made it taller."
    assert app.pending_clarify is None


def test_chit_chat_is_never_an_action(quiet_app, monkeypatch):
    model, asked = quiet_app
    model({"intent": "open_app", "app": "Chrome", "confidence": 0.9})
    monkeypatch.setattr(app, "handle_direct_command", lambda t: None)
    assert app.handle_command("I installed Chrome yesterday") is None    # chat model answers; no model call
    assert asked == [] and sandbox.actions == []


def test_background_speech_is_ignored_only_when_spoken(quiet_app, monkeypatch):
    model, asked = quiet_app
    model({"intent": "ignore", "confidence": 0.9})
    monkeypatch.setattr(app, "handle_direct_command", lambda t: None)
    assert app.handle_command("put them over there guys") is app.SAY_NOTHING
    assert app.handle_command("put them over there guys", typed=True) is None


def test_english_computer_control_stays_with_the_chat_model(quiet_app, monkeypatch):
    model, asked = quiet_app
    model({"intent": "screen_task", "goal": "send a WhatsApp to mom", "confidence": 0.9})
    ran = []
    monkeypatch.setattr(app, "handle_direct_command", lambda t: ran.append(t) and None)
    assert app.handle_command("go and message mom on whatsapp") is None
    assert not any(t.startswith("use my computer") for t in ran)


def test_no_local_ai_falls_back_to_chat(quiet_app, monkeypatch):
    model, asked = quiet_app

    def down():
        raise app.local_llm.LocalAIUnavailable("Ollama isn't running")
    model(down)
    monkeypatch.setattr(app, "handle_direct_command", lambda t: None)
    assert app.handle_command("make the roof steeper") is None


def test_context_carries_blender_objects_and_last_command(quiet_app, monkeypatch):
    from types import SimpleNamespace
    model, asked = quiet_app
    monkeypatch.setattr(app, "blender_session", SimpleNamespace(
        blender_objects=[{"name": "Cube", "kind": "cube"}, {"name": "Cube.001", "kind": "cube"}],
        blender_focus="Cube.001"))
    app.last_command.update(text="create a cube", at=time.time())
    context = app.language_context()
    assert context["blender_objects"] == ["Cube", "Cube.001"]
    assert context["blender_focus"] == "Cube.001" and context["last_command"] == "create a cube"


# ---------------------------------------------------------------- the local chat call (Ollama's own API)

def test_chat_speaks_ollamas_format_and_answers_in_openais(monkeypatch):
    import json
    import local_llm
    sent = []

    class Response:
        status_code = 200
        text = ""

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    def post(url, json=None, timeout=None):
        sent.append((url, json))
        return Response({"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "get_weather", "arguments": {"city": "Tel Aviv"}}}]}, "done_reason": "stop"})
    monkeypatch.setattr(local_llm.requests, "post", post)
    monkeypatch.setattr(local_llm, "status", lambda: ("qwen2.5-coder:7b", ""))
    monkeypatch.setattr(local_llm, "role_model", lambda role: {"chat": "qwen2.5-coder:7b", "hebrew": "qwen3:8b"}[role])
    monkeypatch.setattr(local_llm, "_context_for", lambda model, wanted=None: wanted or local_llm.NUM_CTX)
    history = [{"role": "user", "content": [{"type": "text", "text": "what's this"},
                                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
               {"role": "assistant", "content": None, "tool_calls": [
                   {"id": "1", "type": "function", "function": {"name": "analyze_image", "arguments": "{\"q\": 1}"}}]},
               {"role": "tool", "tool_call_id": "1", "content": "a cat"},
               {"role": "user", "content": "and the weather?"}]
    reply = local_llm.chat(messages=history, tools=[{"type": "function", "function": {"name": "get_weather"}}],
                           max_tokens=50)
    url, payload = sent[-1]
    assert url.endswith("/api/chat") and payload["options"] == {"num_ctx": local_llm.NUM_CTX, "num_predict": 50}
    assert payload["messages"][0] == {"role": "user", "content": "what's this", "images": ["QUJD"]}
    assert payload["messages"][1]["tool_calls"] == [{"function": {"name": "analyze_image", "arguments": {"q": 1}}}]
    assert "tool_call_id" not in payload["messages"][2]
    call = reply.choices[0].message.tool_calls[0]
    assert call.function.name == "get_weather" and json.loads(call.function.arguments) == {"city": "Tel Aviv"}
    assert call.id and reply.choices[0].finish_reason == "tool_calls"

    local_llm.chat(messages=[{"role": "user", "content": "מה בירת צרפת?"}])      # Hebrew: the Hebrew model
    url, payload = sent[-1]
    assert payload["model"] == "qwen3:8b" and payload["think"] is False and payload["options"]["num_ctx"] == 8192


@pytest.mark.parametrize("said, model_says, expected", [
    ("put more size on the cube", {"intent": "object_resize", "target": "the cube", "change": "bigger",
                                   "confidence": 0.9}, "Made it bigger."),          # the quick command, not a build
    ("make it", {"intent": "object_resize", "target": "it", "confidence": 0.9}, "?"),   # unclear: ask
    ("make it nicer", {"intent": "object_color", "target": "it", "color": "nicer", "confidence": 0.9}, "On it."),
    ("build a tall tree", {"intent": "blender_build", "description": "a tall tree", "confidence": 0.9}, "On it."),
])
def test_unrecognised_blender_edits_are_understood_before_the_agent(quiet_app, monkeypatch, said, model_says,
                                                                    expected):
    model, asked = quiet_app
    model(model_says)
    monkeypatch.setattr(app, "is_blender_goal", lambda goal, said=None: True)
    monkeypatch.setattr(app, "run_blender_directly",
                        lambda goal: "Made it bigger." if goal == "make the cube bigger" else None)
    monkeypatch.setattr(app, "start_computer_task", lambda goal, **k: "On it.")
    reply = app.handle_blender_command(said)
    assert reply.endswith(expected)


@pytest.mark.parametrize("reply, claims", [
    ("Done — Cube.002 is taller now.", True),
    ("The cube is now bigger.", True),
    ("I've made it red.", True),
    ("The universe is bigger than we can imagine.", False),
    ("A mesh in Blender is a collection of vertices, edges and faces.", False),
])
def test_chat_claims_of_blender_changes_are_caught(sandboxed, reply, claims):
    assert bool(app._CLAIMS_ACTION.search(reply)) is claims


def test_a_bare_follow_up_in_blender_is_understood_not_chatted(quiet_app, monkeypatch):
    model, asked = quiet_app
    model({"intent": "object_resize", "target": "it", "change": "taller", "confidence": 0.9})
    monkeypatch.setattr(app, "blender_last_used", time.time())
    monkeypatch.setattr(app, "handle_direct_command",
                        lambda t: "Done — I made Cube taller." if t == "make it taller" else None)
    assert app.handle_command("taller") == "Done — I made Cube taller."
    monkeypatch.setattr(app, "blender_last_used", 0.0)        # not working in Blender: plain chat, no model call
    asked.clear()
    assert app.handle_command("taller") is None and asked == []
