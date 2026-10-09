"""Computer control inside Jervis: which sentences start it, the permission question, and stop/pause by voice.

Runs in the sandbox (tests/sandbox.py); the task itself uses a pretend screen, so no real mouse or keyboard is touched.
"""
import threading
import time
from types import SimpleNamespace

import pytest

import sandbox
from test_computer_use import FakeScreen, ai

app = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def clean(sandboxed, monkeypatch):
    app.computer_task = None
    app.control_session = None
    app.pending_control_question = None
    app._control_questions.clear()
    while not app.announcements.empty():
        app.announcements.get_nowait()
    sent = []
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: sent.append(payload))
    # Never reach a real Blender that happens to be open on this machine (tests that need one patch it).
    monkeypatch.setattr(app.blender_control.BlenderBridge, "ping", lambda self, timeout=3: False)
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: False)
    monkeypatch.setattr(app, "computer_environment", FakeScreen)
    monkeypatch.setattr(app.computer_use, "SETTLE_TIMEOUT", 0.05)
    monkeypatch.setattr(app.computer_use, "time", SimpleNamespace(time=time.time, sleep=lambda s: None))
    yield sent
    if app.computer_task is not None:
        app.computer_task.stop()


def test_the_goal_keeps_the_users_wording():
    assert app.parse_computer_task("use my computer to set the font size in TextEdit to 18") == \
        "set the font size in TextEdit to 18"


STARTS = {
    "click the blue Save button": "click the blue save button",
    "Jervis, click on Downloads": "click on downloads",
    "can you scroll down": "scroll down",
    "please press the submit button": "press the submit button",
    "type hello world into the search box": "type hello world into the search box",
    "use my computer to turn on dark mode in chrome": "turn on dark mode in chrome",
    "take control of the mouse and sort my downloads by date": "sort my downloads by date",
    "in Settings, click Bluetooth": "in settings, click bluetooth",
    "go to the next tab": "go to the next tab",
}
NOT_CONTROL = [
    "tap water is safe to drink here",
    "type 2 diabetes in children",
    "check the box office numbers for Dune",
    "I clicked the link yesterday and it broke",
    "what does press the button mean",
    "the mouse ran under the fridge",
    "in the morning, turn on the lights",
    "in 5 minutes set a timer",
    "scroll is an old word for a book",
    "I pressed enter and nothing happened",
    "my computer is slow",
]


@pytest.mark.parametrize("text,goal", STARTS.items())
def test_plain_on_screen_requests_start_computer_control(text, goal):
    assert app.parse_computer_task(text).lower() == goal


@pytest.mark.parametrize("text", NOT_CONTROL)
def test_conversation_never_starts_computer_control(text):
    assert app.parse_computer_task(text) is None


@pytest.mark.parametrize("text", NOT_CONTROL[:4] + ["what's the weather", "tell me a joke"])
def test_the_ai_tool_is_blocked_for_conversation(text):
    assert not app.is_computer_request(text)


def test_off_setting_refuses(monkeypatch):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "off")
    assert "turned off" in app.start_computer_task("click save")
    assert app.computer_task is None


def test_asks_first_and_does_nothing_on_no(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "ask")
    reply = app.handle_direct_command("click the Search button")
    assert "Can I use your mouse and keyboard" in reply and "yes or no" in reply
    assert any(p.get("type") == "control_confirm" for p in clean)
    assert app.handle_control_voice("no") == "Okay, I won't."
    time.sleep(0.2)
    assert app.computer_task is None   # never started


def test_yes_by_voice_runs_the_task(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "ask")
    monkeypatch.setattr(app, "_ask_ai_for_control", ai(("click", {"element": 2}), ("done", {"summary": "Searched."})))
    app.handle_direct_command("click the Search button")
    assert "Move the mouse" in app.handle_control_voice("yes")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    assert app.computer_task.state == "completed"
    assert ("press", "Search") in app.computer_task.env.actions
    states = [p["data"]["state"] for p in clean if p.get("type") == "control"]
    assert states[0] == "starting" and states[-1] == "completed"
    # one click was asked for: done as soon as that click worked (see ComputerTask.finish_after)
    assert app.announcements.get(timeout=1) == "Done: click button “Search”."


def test_hey_jervis_stop_stops_a_running_task(monkeypatch):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    gate = threading.Event()

    def slow_ai(messages, tools):
        gate.wait(5)
        return ai(("click", {"element": 2}))(messages, tools)
    monkeypatch.setattr(app, "_ask_ai_for_control", slow_ai)
    assert "Okay, I'm using the computer" in app.start_computer_task("search")
    for _ in range(200):
        if app.control_active():
            break
        time.sleep(0.02)
    assert app.handle_control_voice("Hey Jervis, stop") == "Stopping. You have control."
    gate.set()
    for _ in range(200):
        if app.computer_task.state == "stopped":
            break
        time.sleep(0.02)
    assert app.computer_task.state == "stopped"
    assert app.computer_task.env.actions == []
    assert app.announcements.empty()   # "Stopping" was the answer; no second "Stopped" message


def test_stop_words_do_nothing_when_jervis_is_not_in_control():
    assert app.handle_control_voice("stop") is None
    assert app.handle_control_voice("yes") is None


def test_a_new_task_replaces_one_still_running(monkeypatch):
    """A stuck task used to answer "Still working on that" to everything said for minutes."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    gate = threading.Event()
    monkeypatch.setattr(app, "_ask_ai_for_control", lambda m, t: (gate.wait(5), ai()(m, t))[1])
    app.start_computer_task("click the first button")
    for _ in range(200):
        if app.control_active():
            break
        time.sleep(0.02)
    first = app.computer_task
    threading.Timer(0.2, gate.set).start()   # the first task is mid-AI-call; it stops as soon as that returns
    assert "Still working on that" not in app.start_computer_task("click the second button")
    assert first.state == "stopped"


def test_a_task_still_being_set_up_is_not_replaced(monkeypatch):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    app.computer_task = app._SettingUp()
    assert "Still working on that" in app.start_computer_task("click save")
    app.computer_task = None


def test_window_buttons_answer_and_stop(monkeypatch):
    ask_id = app.open_control_question("Can I click Send?")
    assert app.answer_control_question(ask_id, True)
    assert app.wait_control_answer(ask_id, timeout=1) is True


# ---------- persistent sessions: "take control" survives past one goal ----------

def test_looks_like_session_goal_guards_plain_questions():
    assert not app.looks_like_session_goal("what's the weather like")
    assert not app.looks_like_session_goal("why is the sky blue")
    assert app.looks_like_session_goal("create a chair")
    assert app.looks_like_session_goal("make it wooden")
    assert app.looks_like_session_goal("open chrome")


@pytest.mark.parametrize("phrase", [
    "stop controlling my computer", "stop computer control", "release control",
    "give me control", "give me back control", "exit computer control",
])
def test_new_stop_phrasings_are_recognized(phrase):
    assert app._CONTROL_STOP.fullmatch(phrase)


def test_bare_take_control_opens_a_session_and_replies_ready(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    assert app.handle_direct_command("Take control of my computer.") == "Sure, I'm ready."
    for _ in range(200):
        if app.session_active():
            break
        time.sleep(0.02)
    assert app.session_active()
    assert not app.control_active()   # no task running yet, just listening


@pytest.mark.parametrize("heard", ["Jargvie, stay in control on my computer.", "stay in control of my computer",
                                   "Jervis, be in control of my PC"])
def test_misheard_stay_in_control_opens_a_waiting_session_not_a_task(monkeypatch, clean, heard):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    assert app.handle_direct_command(heard) == "Sure, I'm ready."
    for _ in range(200):
        if app.session_active():
            break
        time.sleep(0.02)
    assert app.session_active() and app.computer_task is None


@pytest.mark.parametrize("goal", ["stay in control on my computer", "take control of my computer", "be in control"])
def test_the_ai_tool_with_no_real_task_never_clicks_around(monkeypatch, clean, goal):
    """The local AI turned "stay in control" into a goal and then typed/clicked at random for 8 steps."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    ai_calls = []
    monkeypatch.setattr(app, "_ask_ai_for_control", lambda m, t: ai_calls.append(1))
    assert app.tool_use_computer(goal) == "Sure, I'm ready."
    time.sleep(0.2)
    assert app.computer_task is None and not ai_calls


def test_a_blender_command_without_take_control_still_reaches_blender(monkeypatch, clean):
    """"Create a cube" with Blender open used to go to the chat AI, which only claimed to do it."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    bridge = _FakeBlenderBridge()
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: True)
    monkeypatch.setattr(app.blender_control, "ensure_bridge", lambda session, confirm: bridge)
    app.handle_direct_command("Create a cube.")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    assert type(app.computer_task).__name__ == "ScriptedTask"
    assert app.control_session.blender_objects == [{"name": "Cube", "kind": "cube"}]


def test_blender_words_do_nothing_when_blender_is_closed(monkeypatch, clean):
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: False)
    assert not app.is_blender_goal("create a cube")
    assert not app.is_blender_goal("what is a cube")


@pytest.mark.parametrize("reply", ["I've selected a cube in Blender. Scaling the cube to be twice as large...",
                                   "I've scaled the cube for you."])
def test_fake_blender_claims_are_caught(reply):
    assert app._CLAIMS_ACTION.search(reply)


def test_a_video_outro_is_not_a_skip_request():
    assert app.parse_track_skip("and I will see you in the next video") is None
    assert app.parse_track_skip("next song") == "next"


def test_a_completed_task_keeps_the_session_open_and_reports_listening(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    monkeypatch.setattr(app, "_ask_ai_for_control", ai(("click", {"element": 2}), ("done", {"summary": "Searched."})))
    app.handle_direct_command("take control of my computer and click the Search button")
    for _ in range(200):
        if app.session_active() and app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    assert app.computer_task.state == "completed"   # the task itself did finish...
    states = [p["data"]["state"] for p in clean if p.get("type") == "control"]
    assert "listening" in states and "completed" not in states   # ...but the UI never saw control as having ended


def test_a_follow_up_goal_does_not_need_take_control_again_or_reask(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "ask")
    monkeypatch.setattr(app, "_ask_ai_for_control", ai(("click", {"element": 2}), ("done", {"summary": "Searched."})))
    app.handle_direct_command("take control of my computer and click the Search button")
    assert "Move the mouse" in app.handle_control_voice("yes")
    for _ in range(200):
        if app.session_active() and app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    sent_before = len(clean)
    reply = app.handle_direct_command("click the Search button")   # no "take control" prefix this time
    assert reply == "Okay."   # no "Can I use your mouse..." — permission was already granted for the session
    assert not any(p.get("type") == "control_confirm" for p in clean[sent_before:])


def test_new_stop_phrase_ends_an_open_session(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    app.handle_direct_command("take control of my computer")
    for _ in range(200):
        if app.session_active():
            break
        time.sleep(0.02)
    assert app.handle_control_voice("stop controlling my computer") == "Stopping. You have control."
    assert not app.session_active()


def test_a_one_off_step_does_not_leave_a_lingering_session(monkeypatch, clean):
    """"click Save" out of the blue (no "take control") must keep asking every time, exactly as before — it must
    not silently open a persistent session that then skips permission for whatever comes next."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "ask")
    monkeypatch.setattr(app, "_ask_ai_for_control", ai(("click", {"element": 2}), ("done", {"summary": "ok"})))
    app.handle_direct_command("click the Search button")
    app.handle_control_voice("yes")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    assert not app.session_active()


def test_a_follow_up_said_while_busy_replaces_the_running_task(monkeypatch, clean):
    """A free-text follow-up during an active session must reach start_computer_task even while a task is running
    (not fall through to the general chat AI), and replace the running task rather than wait behind it."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    gate = threading.Event()
    monkeypatch.setattr(app, "_ask_ai_for_control", lambda m, t: (gate.wait(5), ai()(m, t))[1])
    app.handle_direct_command("take control of my computer and click the Search button")
    for _ in range(200):
        if app.control_active():
            break
        time.sleep(0.02)
    first = app.computer_task
    threading.Timer(0.2, gate.set).start()
    assert app.handle_direct_command("create a chair") == "Okay."
    assert first.state == "stopped"


@pytest.mark.parametrize("noise", ["for Blendale. Oh my god, that's a hot deal.", "Yes, it's also a chamago, you know",
                                   "and I will see you in the next video.", "I told her.", "The metal very cool."])
def test_background_speech_during_a_session_never_becomes_a_task(noise):
    assert not app.looks_like_session_goal(noise)


def test_okay_thanks_during_a_session_just_says_okay(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    app.handle_direct_command("take control of my computer")
    for _ in range(200):
        if app.session_active():
            break
        time.sleep(0.02)
    assert app.handle_direct_command("Okay, okay, okay, okay.") == "Okay."
    assert app.computer_task is None


# ---------- routing a Blender goal to BlenderComputerTask (see computer_use.BlenderComputerTask) ----------

def test_a_blender_goal_uses_blender_computer_task(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    fake_bridge = object()
    monkeypatch.setattr(app.blender_control, "ensure_bridge", lambda session, confirm: fake_bridge)
    captured = {}

    class FakeBlenderTask:
        def __init__(self, goal, env, ask_ai, bridge, session=None, **kwargs):
            captured["bridge"] = bridge
            captured["session"] = session
            self.state = "starting"

        def _report(self, *a, **k):
            pass

        def stop(self):
            pass

        def run(self):
            self.state = "completed"
            return "Built the house."
    monkeypatch.setattr(app.computer_use, "BlenderComputerTask", FakeBlenderTask)
    # A goal blender_commands.py doesn't recognize deterministically, so this exercises the free-form AI fallback.
    app.handle_direct_command("take control of my computer and build a small house in blender")
    for _ in range(200):
        if "bridge" in captured:
            break
        time.sleep(0.02)
    assert captured["bridge"] is fake_bridge
    assert captured["session"] is app.control_session


def test_blender_goal_falls_back_to_plain_task_when_the_bridge_is_unavailable(monkeypatch, clean):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    monkeypatch.setattr(app.blender_control, "ensure_bridge", lambda session, confirm: None)
    monkeypatch.setattr(app, "_ask_ai_for_control", ai(("done", {"summary": "ok"})))
    app.handle_direct_command("take control of my computer and create a cube in blender")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    assert type(app.computer_task).__name__ == "ComputerTask"


class _FakeBlenderBridge:
    """A bridge that answers deterministically for the object-creation flow — no real Blender needed."""

    def __init__(self):
        self.calls = []

    def run(self, code, timeout=15):
        self.calls.append(code)
        if "o.name + ':' + o.type" in code:
            return {"ok": True, "output": ""}
        if "primitive_cube_add" in code:
            return {"ok": True, "output": "Cube"}
        if "bpy.data.objects.get" in code and "'1' if" in code:
            return {"ok": True, "output": "1"}
        return {"ok": True, "output": "ok"}


def test_a_common_blender_command_is_handled_deterministically_without_the_ai(monkeypatch, clean):
    """"create a cube" must never reach the AI at all — see blender_commands.py."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    bridge = _FakeBlenderBridge()
    monkeypatch.setattr(app.blender_control, "ensure_bridge", lambda session, confirm: bridge)
    ai_calls = []
    monkeypatch.setattr(app, "_ask_ai_for_control", lambda m, t: ai_calls.append(1))
    app.handle_direct_command("take control of my computer and create a cube in blender")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    assert type(app.computer_task).__name__ == "ScriptedTask"
    assert not ai_calls   # the deterministic path never asked the model anything
    assert app.control_session.blender_objects == [{"name": "Cube", "kind": "cube"}]


def test_a_vague_blender_remark_asks_for_clarification_without_the_ai(monkeypatch, clean):
    """"make the cube totally" must never be handed to the AI to invent a technical fix for — see
    blender_commands.looks_concrete. (A remark with no action at all, like "it's sticky", isn't a command.)"""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    bridge = _FakeBlenderBridge()
    monkeypatch.setattr(app.blender_control, "ensure_bridge", lambda session, confirm: bridge)
    # FakeScreen (installed by the `clean` fixture) always reports "FakeApp" in front, not Blender; force the
    # "we're clearly working in Blender" signal the real app would get from the actual foreground window.
    monkeypatch.setattr(app.computer_use.ControlSession, "blender_in_front", lambda self: True)
    ai_calls = []
    monkeypatch.setattr(app, "_ask_ai_for_control", lambda m, t: ai_calls.append(1))
    app.handle_direct_command("take control of my computer and create a cube in blender")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    while not app.announcements.empty():   # drain the "created a cube" announcement before the next command
        app.announcements.get_nowait()
    assert not app.looks_like_session_goal("it's sticky")
    reply = app.handle_direct_command("Make the cube totally.")
    for _ in range(200):
        if not app.announcements.empty():
            break
        time.sleep(0.02)
    spoken = app.announcements.get(timeout=1)
    assert "not sure what you'd like" in spoken or "not sure what you'd like" in (reply or "")


def test_blender_context_survives_a_momentary_focus_steal(monkeypatch, clean):
    """A notification popup (Discord, chat, email) can steal the foreground for an instant — a follow-up like
    "move it right" must still be treated as a Blender command (and handled deterministically) because a bridge
    is already attached to this session, not redirected into whatever briefly grabbed focus. Regression test for
    the real-world failure where this happened and a generic ComputerTask started clicking around Discord."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    bridge = _FakeBlenderBridge()

    def fake_ensure_bridge(session, confirm):
        session.blender = bridge   # real ensure_bridge attaches the bridge to the session as a side effect
        return bridge
    monkeypatch.setattr(app.blender_control, "ensure_bridge", fake_ensure_bridge)
    monkeypatch.setattr(app.computer_use.ControlSession, "blender_in_front", lambda self: True)
    app.handle_direct_command("take control of my computer and create a cube in blender")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    # Now something else (a notification) has the foreground: blender_in_front() goes back to reporting False,
    # exactly like the real OS would report after a popup steals focus.
    monkeypatch.setattr(app.computer_use.ControlSession, "blender_in_front", lambda self: False)
    ai_calls = []
    monkeypatch.setattr(app, "_ask_ai_for_control", lambda m, t: ai_calls.append(1))
    app.handle_direct_command("move it right")
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state == "completed":
            break
        time.sleep(0.02)
    assert type(app.computer_task).__name__ == "ScriptedTask"   # not a plain ComputerTask clicking around elsewhere
    assert not ai_calls
    assert not ai_calls


def test_an_exception_while_setting_up_the_task_never_strands_the_session(monkeypatch, clean):
    """A Blender launch failure, a Windows file-sharing hiccup, anything unexpected before the task even starts
    running: must be reported in plain words, not crash the background thread and leave the session stuck."""
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")

    def boom(session, confirm):
        raise OSError("device gone")
    monkeypatch.setattr(app.blender_control, "ensure_bridge", boom)
    app.handle_direct_command("take control of my computer and create a cube in blender")
    for _ in range(200):
        if app.session_active() and not app.announcements.empty():
            break
        time.sleep(0.02)
    assert app.session_active()   # the crash did not end the session
    spoken = app.announcements.get(timeout=1)
    assert "That didn't work" in spoken and "OSError" in spoken
    states = [p["data"]["state"] for p in clean if p.get("type") == "control"]
    assert "listening" in states   # the overlay was told control is still active, not that it crashed
