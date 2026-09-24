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
    app.pending_control_question = None
    app._control_questions.clear()
    while not app.announcements.empty():
        app.announcements.get_nowait()
    sent = []
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: sent.append(payload))
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
    assert app.announcements.get(timeout=1) == "Searched."


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


def test_a_second_task_waits_for_the_first(monkeypatch):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    gate = threading.Event()
    monkeypatch.setattr(app, "_ask_ai_for_control", lambda m, t: (gate.wait(5), ai()(m, t))[1])
    app.start_computer_task("first")
    for _ in range(200):
        if app.control_active():
            break
        time.sleep(0.02)
    assert "already using the computer" in app.start_computer_task("second")
    app.computer_task.stop()
    gate.set()


def test_window_buttons_answer_and_stop(monkeypatch):
    ask_id = app.open_control_question("Can I click Send?")
    assert app.answer_control_question(ask_id, True)
    assert app.wait_control_answer(ask_id, timeout=1) is True
    assert not app.answer_control_question("q-unknown", True)
