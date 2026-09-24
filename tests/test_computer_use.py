"""The computer-control loop, on a pretend screen with a scripted AI: what reaches the mouse, and what never does."""
import json
import threading
import time
from types import SimpleNamespace

import pytest

import computer_use
from computer_use import ComputerTask, Element, Environment, Observation


class FakeScreen(Environment):
    """A tiny app: a search field, a Search button, a Send button, a password field. Records every action."""
    name = "fake"

    def __init__(self):
        self.actions = []
        self.query = ""
        self.results = False
        self.cursor_at = (500, 500)
        self.user_moves_mouse_after = None   # step number at which "the user" grabs the mouse

    def available(self):
        return True, ""

    def observe(self):
        elements = [
            Element(1, "search field", "Search", self.query, (10, 10, 300, 30)),
            Element(2, "button", "Search", rect=(320, 10, 80, 30)),
            Element(3, "button", "Send message", rect=(420, 10, 80, 30)),
            Element(4, "text field", "Password", rect=(10, 60, 300, 30), password=True),
        ]
        if self.results:
            elements.append(Element(5, "link", f"Results for {self.query}", rect=(10, 120, 400, 20)))
        return Observation(app="FakeApp", window="Fake window", elements=elements, cursor=self.cursor_at)

    def press_element(self, element):
        self.actions.append(("press", element.name))
        if element.name == "Search" and element.role == "button":
            self.results = True
        return ""

    def click(self, point, button="left", double=False):
        self.actions.append(("click", point, button, double))
        return ""

    def type_text(self, text):
        self.actions.append(("type", text))
        self.query += text
        return ""

    def press_keys(self, keys):
        self.actions.append(("keys", "+".join(keys)))
        if keys == ["enter"]:
            self.results = True
        return ""

    def scroll(self, amount, point=None):
        self.actions.append(("scroll", amount))
        return ""

    def switch_window(self, title):
        return ""


def ai(*steps):
    """An AI that answers with these tool calls in order (then keeps saying done)."""
    remaining = list(steps)
    prompts = []

    def ask(messages, tools):
        prompts.append(messages[-1]["content"])
        name, args = remaining.pop(0) if remaining else ("done", {"summary": "finished"})
        call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    ask.prompts = prompts
    return ask


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(computer_use, "SETTLE_TIMEOUT", 0.05)
    monkeypatch.setattr(computer_use, "time", SimpleNamespace(time=time.time, sleep=lambda s: None))


def test_completes_a_search_step_by_step():
    screen = FakeScreen()
    brain = ai(("type_text", {"element": 1, "text": "minecraft", "press_enter": True}),
               ("done", {"summary": "Searched for minecraft."}))
    task = ComputerTask("search for minecraft", screen, brain)
    assert task.run() == "Searched for minecraft."
    assert ("type", "minecraft") in screen.actions and ("keys", "enter") in screen.actions
    assert task.state == "completed"
    assert "Results for minecraft" in brain.prompts[-1]   # the AI saw the new result before saying done


def test_typing_replaces_a_one_line_field_but_not_a_document():
    screen = FakeScreen()
    screen.query = "old"
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "new"}))).run()
    assert screen.actions[:2] == [("press", "Search"), ("keys", "ctrl+a")]

    screen = FakeScreen()
    screen.query = "old"
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "new", "append": True}))).run()
    assert ("keys", "ctrl+a") not in screen.actions


def test_invalid_choices_never_reach_the_mouse():
    screen = FakeScreen()
    brain = ai(("click", {"element": 99}), ("teleport", {}), ("click", {"element": "the big one"}),
               ("done", {"summary": "ok"}))
    task = ComputerTask("do it", screen, brain)
    task.run()
    assert screen.actions == []
    assert "there is no element [99]" in brain.prompts[1]   # told why, so it can correct itself


def test_gives_up_after_repeated_unusable_answers():
    screen = FakeScreen()
    task = ComputerTask("do it", screen, ai(*[("nonsense", {})] * 10))
    assert "couldn't work out" in task.run()
    assert task.state == "error" and screen.actions == []


def test_never_types_into_a_password_field():
    screen = FakeScreen()
    brain = ai(("type_text", {"element": 4, "text": "hunter2"}), ("done", {"summary": "ok"}))
    ComputerTask("log in", screen, brain).run()
    assert ("type", "hunter2") not in screen.actions
    assert "password" in brain.prompts[1].lower()


def test_risky_step_waits_for_ok_and_is_skipped_on_no():
    screen = FakeScreen()
    asked = []
    task = ComputerTask("send it", screen, ai(("click", {"element": 3}), ("done", {"summary": "left it"})),
                        confirm=lambda q: asked.append(q) or False)
    task.run()
    assert asked and "Send message" in asked[0]
    assert ("press", "Send message") not in screen.actions


def test_risky_step_runs_after_ok():
    screen = FakeScreen()
    ComputerTask("send it", screen, ai(("click", {"element": 3})), confirm=lambda q: True).run()
    assert ("press", "Send message") in screen.actions


def test_emergency_stop_shortcut_is_never_pressed():
    screen = FakeScreen()
    ComputerTask("x", screen, ai(("press_keys", {"keys": "ctrl+alt+q"}), ("done", {"summary": "ok"}))).run()
    assert not any(a[0] == "keys" for a in screen.actions)


def test_stop_ends_the_task_before_the_next_action():
    screen = FakeScreen()
    task = None

    def slow_ai(messages, tools):
        task.stop()   # the user presses Stop while the AI is thinking
        call = SimpleNamespace(function=SimpleNamespace(name="click", arguments='{"element": 2}'))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    task = ComputerTask("x", screen, slow_ai)
    assert "Stopped" in task.run()
    assert screen.actions == [] and task.state == "stopped"


def test_moving_the_mouse_pauses_and_resume_continues():
    """After Jervis's step the pointer is somewhere else: the user took over, so Jervis pauses until told to go on."""
    screen = FakeScreen()
    states = []
    task = ComputerTask("x", screen, ai(("click", {"element": 2}), ("done", {"summary": "done"})),
                        report=lambda s: states.append(s["state"]))
    settle = task._settle

    def settle_then_user_moves_mouse(before):
        after = settle(before)          # Jervis notes where the pointer is after his step...
        screen.cursor_at = (1200, 900)  # ...and then the user grabs the mouse
        return after
    task._settle = settle_then_user_moves_mouse
    runner = threading.Thread(target=task.run)
    runner.start()
    for _ in range(500):
        if "paused" in states:
            break
        threading.Event().wait(0.01)
    assert "paused" in states and task.state == "paused"
    task.resume()
    runner.join(5)
    assert task.state == "completed"


def test_switching_to_another_app_pauses_before_typing():
    screen = FakeScreen()
    screen.focus_moved = lambda: True   # the user clicked into another app while the AI was thinking
    states = []
    task = ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "hello"})),
                        report=lambda s: states.append(s["state"]))
    runner = threading.Thread(target=task.run)
    runner.start()
    for _ in range(500):
        if "paused" in states:
            break
        threading.Event().wait(0.01)
    task.stop()
    runner.join(5)
    assert "paused" in states and ("type", "hello") not in screen.actions


def test_nothing_is_typed_when_the_cursor_cant_be_placed():
    screen = FakeScreen()
    screen.focus_element = lambda element: "I couldn't put the cursor in it, so nothing was typed."
    brain = ai(("type_text", {"element": 1, "text": "18"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert not any(a[0] == "type" for a in screen.actions)
    assert "nothing was typed" in brain.prompts[1]


def test_stops_after_the_step_limit():
    screen = FakeScreen()
    task = ComputerTask("x", screen, ai(*[("scroll", {"direction": "down"})] * 50), max_steps=5)
    assert "5 steps" in task.run()
    assert len([a for a in screen.actions if a[0] == "scroll"]) == 5


def test_tells_the_ai_when_nothing_changed():
    screen = FakeScreen()
    brain = ai(("scroll", {"direction": "down"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert "Nothing on screen changed" in brain.prompts[1]


def test_a_crashing_action_is_reported_not_fatal():
    screen = FakeScreen()

    def broken(amount, point=None):
        raise OSError("device gone")
    screen.scroll = broken
    brain = ai(("scroll", {"direction": "down"}), ("done", {"summary": "ok"}))
    assert ComputerTask("x", screen, brain).run() == "ok"
    assert "That action failed (OSError" in brain.prompts[1]


def test_json_text_instead_of_a_tool_call_is_understood():
    """Small local models sometimes write the call as text."""
    screen = FakeScreen()
    answers = iter(['{"name": "click", "arguments": {"element": 2}}', '{"name": "done", "arguments": {"summary": "x"}}'])

    def texty(messages, tools):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None,
                                                                                content=next(answers)))])
    assert ComputerTask("x", screen, texty).run() == "x"
    assert ("press", "Search") in screen.actions


def test_unavailable_platform_explains_itself():
    class NoScreen(Environment):
        def available(self):
            return False, "Jervis needs permission to use this Mac."
    assert ComputerTask("x", NoScreen(), ai()).run() == "Jervis needs permission to use this Mac."
