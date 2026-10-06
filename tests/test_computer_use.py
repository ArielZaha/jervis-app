"""The computer-control loop, on a pretend screen with a scripted AI: what reaches the mouse, and what never does."""
import json
import sys
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


def _chat(focused_name, app="WhatsApp", role="text field"):
    return Observation(app=app, window="Dana", elements=[Element(1, role, focused_name, focused=True, rect=(0, 0, 9, 9))])


def test_enter_in_a_chat_needs_ok_even_when_the_box_just_has_focus():
    assert computer_use.risk_of({"action": "press_keys", "keys": "enter"}, None, _chat("Type a message"))
    assert computer_use.risk_of({"action": "type_text", "text": "hi", "press_enter": True}, None, _chat(""))


def test_enter_in_a_search_box_is_not_treated_as_sending():
    assert not computer_use.risk_of({"action": "type_text", "text": "invoices", "press_enter": True}, None,
                                    _chat("Search mail", app="Mail", role="search field"))
    assert not computer_use.risk_of({"action": "press_keys", "keys": "enter"}, None, _chat("Address", app="Safari"))


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
    """After Jarvis's step the pointer is somewhere else: the user took over, so Jarvis pauses until told to go on."""
    screen = FakeScreen()
    states = []
    task = ComputerTask("x", screen, ai(("click", {"element": 2}), ("done", {"summary": "done"})),
                        report=lambda s: states.append(s["state"]))
    settle = task._settle

    def settle_then_user_moves_mouse(before):
        after = settle(before)          # Jarvis notes where the pointer is after his step...
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


def test_an_action_that_keeps_changing_nothing_is_refused_then_the_task_stops():
    """Small local models loop ("click View" 20 times). Twice is allowed; after that it's refused, and then stopped."""
    screen = FakeScreen()
    brain = ai(*[("click", {"element": 1})] * 20)
    task = ComputerTask("x", screen, brain)
    assert "stuck" in task.run()
    assert screen.actions.count(("press", "Search")) == 2
    assert task.state == "error" and task.step < 10
    assert "already tried" in brain.prompts[3]


def test_many_steps_that_change_nothing_stop_the_task():
    screen = FakeScreen()
    moves = [("scroll", {"direction": d}) for d in ("up", "down")] + [("click", {"element": e}) for e in (1, 4)] \
        + [("scroll", {"direction": "down", "element": e}) for e in (1, 2, 3, 4)]
    task = ComputerTask("x", screen, ai(*moves, *moves))
    assert "stuck" in task.run()
    assert task.step == computer_use.MAX_STALE + 1   # stopped before the next step


def test_typing_only_goes_into_things_that_take_text():
    screen = FakeScreen()
    brain = ai(("type_text", {"element": 2, "text": "18"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert not any(a[0] == "type" for a in screen.actions)
    assert "doesn't take typing" in brain.prompts[1]


def test_an_ai_that_cant_be_reached_ends_the_task_in_plain_words():
    def down(messages, tools):
        raise computer_use.AIError("My local AI isn't running yet.")
    task = ComputerTask("x", FakeScreen(), down)
    assert task.run() == "My local AI isn't running yet. So I stopped. You have control again."
    assert task.state == "error"


def test_typing_that_never_arrives_is_put_in_directly():
    """Keys can get lost (a busy app, a remote desktop): the field is read back and filled in directly."""
    screen = FakeScreen()
    screen.type_text = lambda text: screen.actions.append(("lost", text)) or ""   # the keys go nowhere
    screen.read_value = lambda element: screen.query
    screen.set_value = lambda element, value: (setattr(screen, "query", value), screen.actions.append(("set", value)))[0] or ""
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "minecraft"}), ("done", {"summary": "ok"}))).run()
    assert ("set", "minecraft") in screen.actions and screen.query == "minecraft"


def test_the_direct_fallback_never_cuts_a_long_document():
    screen = FakeScreen()
    long_text = "x" * 5000
    doc = Element(1, "text area", "Document", long_text[:200], (10, 10, 600, 400), focused=True)
    screen.observe = lambda: Observation(app="Editor", window="Doc", elements=[doc])
    screen.type_text = lambda text: ""                      # the keys go nowhere
    screen.read_value = lambda element: long_text
    stored = {}
    screen.set_value = lambda element, value: stored.setdefault("value", value) and ""
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": " end"}), ("done", {"summary": "ok"}))).run()
    assert stored["value"] == long_text + " end"


def test_typing_that_arrived_is_left_alone():
    screen = FakeScreen()
    screen.read_value = lambda element: screen.query
    screen.set_value = lambda element, value: pytest.fail("set_value used although the typing arrived")
    ComputerTask("x", screen, ai(("type_text", {"element": 1, "text": "minecraft"}), ("done", {"summary": "ok"}))).run()
    assert screen.query == "minecraft"


def test_stops_after_the_step_limit():
    screen = FakeScreen()
    scroll = screen.scroll

    def scroll_and_change(amount, point=None):   # a long page: every scroll shows something new
        screen.query += "x"
        return scroll(amount, point)
    screen.scroll = scroll_and_change
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
            return False, "Jarvis needs permission to use this Mac."
    assert ComputerTask("x", NoScreen(), ai()).run() == "Jarvis needs permission to use this Mac."


def test_screenshots_go_local_when_the_local_model_is_available(monkeypatch):
    """When the local vision model is there, a screenshot goes to it, at the size it answers about — never online,
    even with an online AI key, unless the local model is unavailable AND online was explicitly turned on."""
    import images
    import screen_vision
    from PIL import Image
    sent = {}

    def local(paths, prompt, max_tokens):
        sent["size"] = Image.open(paths[0]).size
        return '{"bbox_2d": [0, 0, 20, 10]}'
    monkeypatch.setattr(images, "_local_vision_call", local)
    monkeypatch.setattr(images, "_groq_vision_call", lambda *a, **k: pytest.fail("a screenshot went to the online AI"))
    monkeypatch.setattr(screen_vision, "_local_available", lambda: True)
    point = screen_vision.ScreenVision().locate(Image.new("RGB", (2880, 1800)), "the logo", (1440, 900))
    assert max(sent["size"]) == images.LOCAL_VISION_MAX_DIMENSION
    assert point == (int(10 * 1440 / sent["size"][0]), int(5 * 900 / sent["size"][1]))


def test_screenshots_never_go_online_by_default(monkeypatch):
    """No local vision model, and online screen vision not turned on (the default): looking at the screen fails
    outright rather than silently sending a screenshot of the whole screen to an online service."""
    import images
    import screen_vision
    from PIL import Image
    monkeypatch.setattr(screen_vision, "_local_available", lambda: False)
    monkeypatch.setattr(images, "_groq_vision_call", lambda *a, **k: pytest.fail("a screenshot went to the online AI"))
    monkeypatch.delenv("JARVIS_SCREEN_VISION", raising=False)   # default: "local"
    with pytest.raises(images.ImageError):
        screen_vision.ScreenVision().locate(Image.new("RGB", (100, 100)), "the logo", (100, 100))


def test_screenshots_go_online_when_explicitly_turned_on(monkeypatch):
    """No local vision model, but the user explicitly set Settings, Computer control, "Look at the screen with" to
    online: a screenshot may go to Groq for this feature only."""
    import images
    import screen_vision
    from PIL import Image
    sent = {}

    def online(paths, prompt, max_tokens):
        sent["called"] = True
        return '{"bbox_2d": [0, 0, 20, 10]}'
    monkeypatch.setattr(screen_vision, "_local_available", lambda: False)
    monkeypatch.setattr(images, "_groq_vision_call", online)
    monkeypatch.setenv("JARVIS_SCREEN_VISION", "online")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    point = screen_vision.ScreenVision().locate(Image.new("RGB", (100, 100)), "the logo", (100, 100))
    assert sent.get("called") and point is not None


def test_scripted_steps_run_in_order_and_report_each_one():
    done, states = [], []
    task = computer_use.ScriptedTask("play it", [("Opening Spotify", lambda: done.append("open")),
                                                 ("Playing it", lambda: "Playing Jane! on Spotify.")],
                                     report=lambda s: states.append((s["state"], s["detail"])))
    assert task.run() == "Playing Jane! on Spotify."
    assert done == ["open"] and ("acting", "Opening Spotify") in states and states[-1][0] == "completed"


def test_stop_ends_a_scripted_task_before_the_next_step():
    done = []
    task = None
    task = computer_use.ScriptedTask("x", [("first", lambda: task.stop()), ("second", lambda: done.append("second"))])
    assert "Stopped" in task.run()
    assert done == [] and task.state == "stopped"


def test_moving_the_mouse_pauses_a_scripted_task():
    """Between two steps the pointer is somewhere else: the user took over, so Jarvis pauses."""
    positions = iter([(100, 100), (100, 100), (900, 700)])   # before step 1, after step 1, before step 2
    states, done = [], []
    task = computer_use.ScriptedTask("x", [("first", lambda: None), ("second", lambda: done.append("second"))],
                                     report=lambda s: states.append(s["state"]),
                                     cursor=lambda: next(positions, (900, 700)))
    runner = threading.Thread(target=task.run)
    runner.start()
    for _ in range(300):
        if "paused" in states:
            break
        threading.Event().wait(0.01)
    assert "paused" in states and done == []
    task.stop()
    runner.join(5)
    assert task.state == "stopped" and done == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation")
def test_the_screen_can_be_read_from_the_computer_control_thread():
    """Computer control runs on its own thread, and UI Automation is COM, which must be started on each thread that
    uses it: without that, every task stopped at once with "Something went wrong while using the computer (OSError)"."""
    import threading
    import screen_windows
    outcome = {}

    def look():
        try:
            outcome["observation"] = screen_windows.WindowsScreen().observe()
        except Exception as e:   # the bug: OSError [WinError -2147221008] CoInitialize has not been called
            outcome["error"] = e

    worker = threading.Thread(target=look)
    worker.start()
    worker.join(30)
    assert "error" not in outcome, outcome.get("error")
    assert outcome["observation"] is not None


class MenuScreen(FakeScreen):
    """A window with an Edit menu: clicking it opens the menu and puts the focus on its first item."""

    def __init__(self):
        super().__init__()
        self.menu_open = False

    def observe(self):
        elements = [Element(1, "menu item", "Edit", rect=(10, 10, 40, 20), focused=not self.menu_open)]
        if self.menu_open:
            elements.append(Element(2, "menu item", "Undo", rect=(10, 40, 80, 20), focused=True))
        return Observation(app="notepad", window="Notes - Notepad", elements=elements, cursor=self.cursor_at)

    def press_element(self, element):
        self.actions.append(("press", element.name))
        if element.name == "Edit":
            self.menu_open = not self.menu_open
        return ""


def test_a_one_click_goal_is_done_after_the_click_that_worked():
    """"Click the Edit menu": a small AI clicked it open, then shut, open, shut… and wandered off. One action that
    changed the screen completes a one-action goal."""
    screen = MenuScreen()
    task = ComputerTask("click the Edit menu", screen, ai(*[("click", {"element": 1})] * 6),
                        finish_after={"click", "double_click", "right_click"})
    assert task.run() == "Done: click menu item “Edit”."
    assert screen.actions == [("press", "Edit")] and screen.menu_open and task.state == "completed"


def test_typing_is_refused_when_the_focus_is_on_a_menu():
    """Letters sent to an open menu are shortcuts (in Notepad's Edit menu they start "Search with Bing")."""
    screen = MenuScreen()
    screen.menu_open = True
    brain = ai(("type_text", {"text": "Edit"}), ("done", {"summary": "ok"}))
    ComputerTask("x", screen, brain).run()
    assert not any(a[0] == "type" for a in screen.actions)


# ---------- persistent sessions (ControlSession) and Blender (BlenderComputerTask) ----------

def test_listening_is_a_recognized_state():
    """ControlSession's "idle, session open, waiting for the next command" state (see app.py)."""
    assert "listening" in computer_use.STATES


def test_tidy_summary_cleans_garbled_or_structured_text_but_keeps_plain_ones():
    # A small local model's garbled/structured output must never reach the user as-is.
    assert computer_use.tidy_summary("$$", "Done.") == "Done."
    assert computer_use.tidy_summary("---", "Done.") == "Done."
    assert computer_use.tidy_summary("", "Done.") == "Done."
    assert computer_use.tidy_summary("**Cube**\n1. (Kinematic)\n$$", "Done.") == "Cube 1. (Kinematic)"
    # Plain, even terse, text is left alone.
    assert computer_use.tidy_summary("ok", "Done.") == "ok"
    assert computer_use.tidy_summary("Created a cube at the origin.", "Done.") == "Created a cube at the origin."


def test_a_garbled_done_summary_is_cleaned_before_it_becomes_the_result():
    screen = FakeScreen()
    assert ComputerTask("x", screen, ai(("done", {"summary": "$$"}))).run() == "Done."


def test_change_description_default_matches_the_old_behavior():
    """BlenderComputerTask overrides this; plain ComputerTask must behave exactly as before the hook existed."""
    screen = FakeScreen()
    task = ComputerTask("x", screen, ai())
    before = screen.observe()
    screen.results = True
    after = screen.observe()
    assert task._change_description("click", "did it.", before, after) == \
        f"did it. {computer_use.describe_change(before, after)}".strip()


def test_control_session_tracks_blender_in_front():
    screen = FakeScreen()
    session = computer_use.ControlSession(screen)
    assert session.blender_in_front() is False
    screen.observe = lambda: Observation(app="Blender", window="Untitled.blend")
    assert session.blender_in_front() is True


def test_control_session_remembers_a_bounded_history():
    session = computer_use.ControlSession(FakeScreen())
    for i in range(10):
        session.remember(f"goal {i}", f"result {i}")
    assert len(session.history) == computer_use.ControlSession.HISTORY
    assert session.history[-1] == ("goal 9", "result 9")


class FakeBridge:
    """Stands in for blender_control.BlenderBridge: no real Blender, just records what it was asked to run."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def run(self, code, timeout=20):
        self.calls.append(code)
        if "RESULT = ('Active" in code:   # BlenderComputerTask's own scene-summary query
            return {"ok": True, "output": "Active: Cube. Objects: Cube (MESH) at (0, 0, 0)"}
        if self._responses:
            return self._responses.pop(0)
        return {"ok": True, "output": "Done."}


def test_blender_task_runs_python_then_finishes():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Created a cube."}])
    brain = ai(("run_python", {"code": "bpy.ops.mesh.primitive_cube_add()"}), ("done", {"summary": "Created a cube."}))
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, bridge)
    assert task.run() == "Created a cube."
    assert any("primitive_cube_add" in c for c in bridge.calls)


def test_blender_task_prompt_includes_scene_summary_and_session_history():
    bridge = FakeBridge()
    session = computer_use.ControlSession(FakeScreen())
    session.remember("create a chair", "Created a chair.")
    brain = ai(("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("make it wooden", FakeScreen(), brain, bridge, session=session)
    task.run()
    assert "Active: Cube" in brain.prompts[0]
    assert "create a chair -> Created a chair." in brain.prompts[0]


def test_blender_task_asks_before_running_dangerous_code():
    bridge = FakeBridge()
    asked = []

    def confirm(question):
        asked.append(question)
        return False   # the user says no
    brain = ai(("run_python", {"code": "os.remove('/etc/passwd')"}), ("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("x", FakeScreen(), brain, bridge, confirm=confirm)
    task.run()
    assert asked and "os.remove" in asked[0]
    assert not any("os.remove" in c for c in bridge.calls)   # never actually ran


def test_blender_task_error_counts_as_no_change_for_staleness():
    """Blender's accessibility tree barely reflects a script's effect, so an error must still look like "nothing
    changed" to the base class's stale/fruitless-repeat detection (the exact sentinel it checks for)."""
    bridge = FakeBridge()
    task = computer_use.BlenderComputerTask("x", FakeScreen(), ai(), bridge)
    outcome = "The script raised an error: NameError: name 'bpy' is not defined"
    before = after = FakeScreen().observe()
    assert task._change_description("run_python", outcome, before, after) == outcome + " Nothing on screen changed."
    ok_outcome = "Created a cube."
    assert task._change_description("run_python", ok_outcome, before, after) == ok_outcome


def test_blender_task_falls_back_to_gui_tools():
    """The hybrid: a plain click still works on a BlenderComputerTask for the rare step that needs the UI."""
    screen = FakeScreen()
    brain = ai(("click", {"element": 2}), ("done", {"summary": "clicked"}))
    task = computer_use.BlenderComputerTask("x", screen, brain, FakeBridge())
    assert task.run() == "clicked"
    assert ("press", "Search") in screen.actions


def test_blender_task_cannot_claim_done_without_doing_anything():
    """A small model asserting "done" with zero real actions must never be accepted as success."""
    bridge = FakeBridge()
    brain = ai(("done", {"summary": "I created a cube."}))   # claims success, never actually ran anything
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, bridge, max_steps=6)
    result = task.run()
    assert task.state == "error"   # never silently accepted as "completed"
    assert not any("primitive" in c for c in bridge.calls)


def test_blender_task_accepts_done_after_a_real_run_python_action():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Created a cube."}])
    brain = ai(("run_python", {"code": "bpy.ops.mesh.primitive_cube_add()"}), ("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, bridge)
    assert task.run() == "ok"
    assert task.state == "completed"


def test_blender_task_updates_session_object_context_from_free_form_code():
    """When the free-form AI creates something itself, "it" must still resolve to it afterward (see
    blender_commands.py's _resolve_reference, which reads session.blender_objects)."""
    session = computer_use.ControlSession(env=None)
    created = {"done": False}

    class Bridge:
        def run(self, code, timeout=15):
            if "o.name + ':' + o.type" in code:   # the object-name listing query
                return {"ok": True, "output": "Cube:MESH" if created["done"] else ""}
            if "primitive_cube_add" in code:
                created["done"] = True
                return {"ok": True, "output": "Created a cube."}
            return {"ok": True, "output": "(scene summary)"}
    brain = ai(("run_python", {"code": "bpy.ops.mesh.primitive_cube_add()"}), ("done", {"summary": "ok"}))
    task = computer_use.BlenderComputerTask("create a cube", FakeScreen(), brain, Bridge(), session=session)
    task.run()
    assert session.blender_objects == [{"name": "Cube", "kind": "mesh"}]
