"""Which requests reach the agent (and which app's), the model each job uses, and that Blender work through its
bridge needs no mouse permission. The agent itself is faked here (see test_agent_core.py for the loop)."""
import threading
import time

import pytest

import local_llm
import sandbox

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
    app.blender_last_used = 0.0
    app.blender_launch = None
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: None)
    # Never reach a real Blender that happens to be open on this machine (tests that need one patch it).
    monkeypatch.setattr(app.blender_control.BlenderBridge, "ping", lambda self, timeout=3: False)
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: False)
    yield
    if app.computer_task is not None:
        app.computer_task.stop()


def blender(monkeypatch, running=True, front=False):
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: running)
    monkeypatch.setattr(app, "app_in_front", lambda name: front and name == "blender")


@pytest.mark.parametrize("said", ["create a small house with a red roof", "make a car with black wheels",
                                  "build a snowman", "add a tree next to the house"])
def test_build_requests_go_to_blender_when_it_is_in_front(monkeypatch, said):
    blender(monkeypatch, front=True)
    assert app.is_blender_goal(app.blender_commands.normalize(said), said=said)


def test_build_requests_dont_go_to_a_blender_that_is_merely_open_somewhere(monkeypatch):
    blender(monkeypatch, front=False)
    for said in ("make a list of groceries", "create a new playlist", "build a snowman"):
        assert not app.is_blender_goal(app.blender_commands.normalize(said), said=said)


def test_build_requests_follow_recent_blender_work(monkeypatch):
    blender(monkeypatch, front=False)
    app.blender_last_used = time.time()
    assert app.is_blender_goal("build a snowman", said="build a snowman")


def test_naming_blender_is_enough(monkeypatch):
    blender(monkeypatch, running=False)
    said = "in Blender, create a small house with a red roof"
    assert app.is_blender_goal(app.blender_commands.normalize(said), said=said)


def test_questions_and_chatter_never_reach_the_agent(monkeypatch):
    blender(monkeypatch, front=True)
    for said in ("what is a house", "that's a hot deal", "why is the roof red"):
        assert not app.is_blender_goal(app.blender_commands.normalize(said), said=said)


def test_open_blender_and_build_opens_it_and_hands_the_build_to_the_agent(monkeypatch):
    opened, started = [], []
    monkeypatch.setattr(app, "resolve_app", lambda name: ("ok", "Blender 4.5") if "blender" in name.lower()
                        else ("missing", None))
    monkeypatch.setattr(app, "open_blender_in_background", lambda: (opened.append(1),
                                                                    setattr(app, "blender_launch", _alive())))
    monkeypatch.setattr(app, "start_computer_task", lambda goal, **kw: started.append((goal, kw)) or "On it.")
    reply = app.handle_direct_command("open Blender and create a small house with a red roof")
    assert opened and started and started[0][1].get("blender") is True
    assert "house" in started[0][0] and reply.startswith("Opening Blender 4.5.")


def _alive():
    """A stand-in for the Blender launch thread, still running."""
    done = threading.Event()
    thread = threading.Thread(target=done.wait, args=(5,), daemon=True)
    thread.start()
    thread.done = done
    return thread


def test_blender_agent_work_asks_no_mouse_permission(monkeypatch):
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "ask")
    monkeypatch.setattr(app.blender_control.BlenderBridge, "ping", lambda self, timeout=3: True)
    monkeypatch.setattr(app, "computer_environment", lambda: type("Env", (), {"available": lambda s: (True, "")})())
    started = threading.Event()

    class FakeAgent:
        def __init__(self, goal, adapter, **kw):
            self.state, self.adapter = "starting", adapter
            started.set()

        def _report(self, *a, **k): pass
        def stop(self): self.state = "stopped"

        def run(self):
            self.state = "completed"
            return "Done: built it."
    monkeypatch.setattr(app.agent_core, "AgentTask", FakeAgent)
    monkeypatch.setattr(app.local_llm, "role_model", lambda role: "qwen2.5-coder:7b")
    monkeypatch.setattr(app.blender_control, "ensure_bridge", lambda session, confirm: object())
    monkeypatch.setattr(app.blender_commands, "steps_for", lambda goal, session, bridge: None)
    reply = app.start_computer_task("create a small house with a red roof", persistent=True, blender=True)
    assert reply == "On it."                          # no "Can I use your mouse and keyboard…?"
    assert started.wait(5)
    assert type(app.computer_task.adapter).__name__ == "BlenderAdapter"


def test_minecraft_requests_go_to_the_minecraft_agent_while_playing(monkeypatch):
    started = []
    monkeypatch.setattr(app, "app_in_front", lambda name: name == "minecraft")
    monkeypatch.setattr(app.app_launcher, "app_windows", lambda name: [(1, "Minecraft 1.21.4")])
    monkeypatch.setattr(app, "start_computer_task", lambda goal, **kw: started.append((goal, kw)) or "Okay.")
    assert app.handle_minecraft_command("build a small stone tower") == "Okay."
    assert started[0][1]["agent_adapter"] is app.agent_minecraft.MinecraftAdapter
    assert app.handle_minecraft_command("what is a creeper") is None


def test_minecraft_named_but_not_running_says_so(monkeypatch):
    monkeypatch.setattr(app, "app_in_front", lambda name: False)
    monkeypatch.setattr(app.app_launcher, "app_windows", lambda name: [])
    assert "isn't open" in app.handle_minecraft_command("in Minecraft, build a house")


# ---------- which local model does which job ----------
MODELS = ["llama3.2:latest", "qwen2.5-coder:7b", "qwen2.5vl:3b", "qwen3:8b"]


def test_roles_pick_the_strong_model_for_agent_work_and_the_vision_model_for_screens(monkeypatch):
    for var in ("JERVIS_CHAT_MODEL", "JERVIS_AGENT_MODEL", "OLLAMA_MODEL", "OLLAMA_VISION_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert local_llm.model_for("agent", MODELS) == "qwen2.5-coder:7b"
    assert local_llm.model_for("chat", MODELS) == "qwen2.5-coder:7b"     # one warm model: no swapping on an 8 GB GPU
    assert local_llm.model_for("vision", MODELS) == "qwen2.5vl:3b"
    assert local_llm.model_for("agent", ["llama3.2:latest"]) == "llama3.2:latest"


def test_the_settings_default_chat_model_is_not_a_choice(monkeypatch):
    """Settings always fills in OLLAMA_MODEL=llama3.2: that default must not split chat onto a second model."""
    for var in ("JERVIS_CHAT_MODEL", "JERVIS_AGENT_MODEL", "JERVIS_HEBREW_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    assert local_llm.model_for("chat", MODELS) == "qwen2.5-coder:7b"
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")             # a real choice is kept
    assert local_llm.model_for("chat", MODELS) == "qwen3:8b"
    assert local_llm.model_for("hebrew", MODELS) == "qwen3:8b"
    assert local_llm.model_for("hebrew", ["llama3.2:latest", "qwen2.5-coder:7b"]) is None   # no Hebrew model: chat


def test_roles_can_be_overridden(monkeypatch):
    monkeypatch.setenv("JERVIS_CHAT_MODEL", "llama3.2")
    assert local_llm.model_for("chat", MODELS) == "llama3.2:latest"
    monkeypatch.setenv("JERVIS_AGENT_MODEL", "qwen3:8b")
    assert local_llm.model_for("agent", MODELS) == "qwen3:8b"


@pytest.mark.parametrize("said", ["open Blender and build a small house with a red roof",
                                  "open Blender and create a snowman", "open Blender then add a tree"])
def test_open_blender_and_any_build_verb(monkeypatch, said):
    opened, started = [], []
    monkeypatch.setattr(app, "resolve_app", lambda name: ("ok", "Blender 4.5") if "blender" in name.lower()
                        else ("missing", None))
    monkeypatch.setattr(app, "open_blender_in_background", lambda: (opened.append(1),
                                                                    setattr(app, "blender_launch", _alive())))
    monkeypatch.setattr(app, "start_computer_task", lambda goal, **kw: started.append((goal, kw)) or "On it.")
    app.handle_direct_command(said)
    assert opened and started and started[0][1].get("blender") is True


def test_undo_right_after_blender_work_goes_to_blender(monkeypatch):
    blender(monkeypatch, front=False)
    assert not app.is_blender_goal("undo", said="undo")            # nothing done in Blender lately
    app.blender_last_used = time.time()
    assert app.is_blender_goal("undo", said="undo")
    assert app.is_blender_goal("do it again", said="do it again")
