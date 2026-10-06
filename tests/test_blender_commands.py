"""The deterministic Blender command layer: recognized phrasings, object-reference resolution, execute-then-verify
behavior, and the "never invent a vague instruction" guard. No real Blender — a fake bridge stands in."""
import pytest

import computer_use
import blender_commands as bc


class FakeBridge:
    """Mimics blender_control.BlenderBridge: tracks every script it was asked to run, and lets a test script a
    canned {"ok", "output", "error"} response per call."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def run(self, code, timeout=15):
        self.calls.append(code)
        if self._responses:
            return self._responses.pop(0)
        return {"ok": True, "output": "ok"}


def new_session():
    return computer_use.ControlSession(env=None)


# ---------- recognizing phrasings ----------

@pytest.mark.parametrize("text", ["create a cube", "Create another cube.", "add a second cube", "build a sphere",
                                  "make a cylinder", "create a monkey"])
def test_create_phrasings_are_recognized(text):
    assert bc.steps_for(text, new_session(), FakeBridge()) is not None


@pytest.mark.parametrize("text", ["make it taller", "make the second one wider", "Make the cube bigger."])
def test_resize_phrasings_are_recognized(text):
    assert bc.steps_for(text, new_session(), FakeBridge()) is not None


@pytest.mark.parametrize("text", ["move it left", "move it right", "move the first one up"])
def test_move_direction_phrasings_are_recognized(text):
    assert bc.steps_for(text, new_session(), FakeBridge()) is not None


def test_move_next_to_is_recognized():
    assert bc.steps_for("move it next to the first one", new_session(), FakeBridge()) is not None


@pytest.mark.parametrize("text,kind", [("undo", "undo"), ("undo that", "undo"), ("redo", "redo")])
def test_undo_redo_are_recognized(text, kind):
    assert bc.steps_for(text, new_session(), FakeBridge()) is not None


@pytest.mark.parametrize("text", ["save", "save it", "save the project", "save the project as my_scene.blend"])
def test_save_phrasings_are_recognized(text):
    assert bc.steps_for(text, new_session(), FakeBridge()) is not None


@pytest.mark.parametrize("text", ["build a simple house", "what's the weather", "it's sticky", "hello there"])
def test_unrelated_text_is_not_recognized(text):
    assert bc.steps_for(text, new_session(), FakeBridge()) is None


# ---------- create: executes, verifies, and tracks the object ----------

def test_create_executes_and_verifies_before_reporting_success():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"}, {"ok": True, "output": "1"}])
    session = new_session()
    steps = bc.steps_for("create a cube", session, bridge)
    result = steps[0][1]()
    assert "Done" in result and "Cube" in result
    assert session.blender_objects == [{"name": "Cube", "kind": "cube"}]
    assert any("primitive_cube_add" in c for c in bridge.calls)
    assert len(bridge.calls) == 2   # the create call, then a separate verification query


def test_create_does_not_claim_success_when_verification_fails():
    """Blender ran the command without error, but the object isn't actually there — must not be reported as done."""
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"}, {"ok": True, "output": "0"}])
    session = new_session()
    steps = bc.steps_for("create a cube", session, bridge)
    with pytest.raises(RuntimeError, match="doesn't actually"):
        steps[0][1]()
    assert session.blender_objects == []   # never recorded as if it worked


def test_create_does_not_claim_success_on_a_blender_error():
    bridge = FakeBridge(responses=[{"ok": False, "output": "", "error": "NameError: bpy not defined"}])
    session = new_session()
    steps = bc.steps_for("create a cube", session, bridge)
    with pytest.raises(RuntimeError, match="NameError"):
        steps[0][1]()


def test_second_cube_is_offset_from_the_first():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"}, {"ok": True, "output": "1"},
                                   {"ok": True, "output": "Cube.001"}, {"ok": True, "output": "1"}])
    session = new_session()
    bc.steps_for("create a cube", session, bridge)[0][1]()
    bc.steps_for("create a second cube", session, bridge)[0][1]()
    create_calls = [c for c in bridge.calls if "primitive_cube_add" in c]
    assert "location=(0.0, 0, 0)" in create_calls[0]
    assert "location=(3.0, 0, 0)" in create_calls[1]


# ---------- object reference resolution ("it", "the second one", "the cube") ----------

def test_reference_resolution_it_means_most_recently_created():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    session.remember_blender_object("Cube.001", "cube")
    assert bc._resolve_reference("it", session) == "Cube.001"


def test_reference_resolution_by_ordinal():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    session.remember_blender_object("Cube.001", "cube")
    assert bc._resolve_reference("the first one", session) == "Cube"
    assert bc._resolve_reference("the second one", session) == "Cube.001"


def test_reference_resolution_by_kind():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    session.remember_blender_object("Sphere", "sphere")
    assert bc._resolve_reference("the cube", session) == "Cube"
    assert bc._resolve_reference("the sphere", session) == "Sphere"


def test_resize_fails_cleanly_when_nothing_exists_yet():
    session = new_session()
    bridge = FakeBridge(responses=[{"ok": True, "output": ""}])   # the scene has no matching object either
    steps = bc.steps_for("make it taller", session, bridge)
    with pytest.raises(RuntimeError, match="couldn't find"):
        steps[0][1]()
    assert len(bridge.calls) == 1   # asked the scene, never ran a resize


def test_resize_finds_blenders_default_cube_in_the_scene():
    """Blender opens with a "Cube" Jarvis never created: "make the cube bigger" must still reach it."""
    session = new_session()
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"},
                                   {"ok": True, "output": "(1.0, 1.0, 1.0)|(2.0, 2.0, 2.0)"}])
    result = bc.steps_for("Make the cube two times bigger.", session, bridge)[0][1]()
    assert "Cube" in result and "2 times bigger" in result
    assert "obj.scale[0]*2.0" in bridge.calls[1]
    assert session.last_blender_object == "Cube"


@pytest.mark.parametrize("heard,meant", [
    ("Okay, make the cube be girl.", "make the cube bigger"),
    ("blender you have a cube selected. Make the cube two times bigger.", "Make the cube two times bigger"),
    ("Create a cube.", "Create a cube"),
])
def test_normalize_finds_the_instruction_in_what_was_heard(heard, meant):
    assert bc.normalize(heard) == meant


@pytest.mark.parametrize("text", ["Create a cube.", "Okay, make the cube be girl.", "make it twice as big",
                                  "blender you have a cube selected. Make the cube two times bigger."])
def test_everyday_object_commands_are_recognized(text):
    assert bc.is_command(text)


@pytest.mark.parametrize("text", ["undo", "save it", "what's the weather", "make me a sandwich"])
def test_ambiguous_or_unrelated_text_is_not_an_object_command(text):
    assert not bc.is_command(text)


def test_resize_does_not_claim_success_when_scale_did_not_change():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "(1.0, 1.0, 1.0)|(1.0, 1.0, 1.0)"}])
    steps = bc.steps_for("make it taller", session, bridge)
    with pytest.raises(RuntimeError, match="didn't actually change"):
        steps[0][1]()


def test_move_next_to_resolves_both_objects_and_verifies_location_changed():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    session.remember_blender_object("Cube.001", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "(3.0, 0, 0)|(3.0, 0, 0)|(0, 0, 0)"}])
    # first object ("it" -> Cube.001), moved relative to the other ("the first one" -> Cube)
    steps = bc.steps_for("move it next to the first one", session, bridge)
    bridge._responses = [{"ok": True, "output": "(3.0, 0, 0)|(0.0, 0.0, 0.0)"}]
    result = steps[0][1]()
    assert "Done" in result


# ---------- "do that again" repeats the last recognized command ----------

def test_do_that_again_repeats_the_last_command():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "undone"}])
    bc.steps_for("undo that", session, bridge)
    assert session.last_deterministic_text == "undo that"
    again = bc.steps_for("do that again", session, bridge)
    assert again is not None
    assert "Undoing" in again[0][0]


def test_do_that_again_with_nothing_prior_is_not_recognized():
    assert bc.steps_for("do that again", new_session(), FakeBridge()) is None


# ---------- undo reverses Jarvis's own last action (bpy.ops.ed.undo's poll() rejects calls from a script context,
# confirmed against a real Blender even with temp_override, so this tracks and reverses the change directly) ----------

def test_create_then_undo_removes_the_object_it_created():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"}, {"ok": True, "output": "1"}])
    session = new_session()
    bc.steps_for("create a cube", session, bridge)[0][1]()
    assert session.last_undo is not None
    undo_steps = bc.steps_for("undo that", session, bridge)
    result = undo_steps[0][1]()
    assert "Done" in result
    assert any("bpy.data.objects.remove" in c for c in bridge.calls)
    assert session.last_undo is None   # consumed — can't undo the same thing twice


def test_resize_then_undo_restores_the_previous_scale():
    bridge = FakeBridge(responses=[{"ok": True, "output": "(1.0, 1.0, 1.0)|(1.0, 1.0, 1.4)"}])
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    bc.steps_for("make it taller", session, bridge)[0][1]()
    assert session.last_undo["code"].count("(1.0, 1.0, 1.0)") == 1
    bridge._responses = [{"ok": True, "output": "restored"}]
    result = bc.steps_for("undo that", session, bridge)[0][1]()
    assert "Done" in result


def test_undo_with_nothing_done_yet_fails_cleanly():
    steps = bc.steps_for("undo that", new_session(), FakeBridge())
    with pytest.raises(RuntimeError, match="nothing I've done"):
        steps[0][1]()


def test_undo_is_not_available_twice_in_a_row():
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"}, {"ok": True, "output": "1"},
                                   {"ok": True, "output": "removed"}])
    session = new_session()
    bc.steps_for("create a cube", session, bridge)[0][1]()
    bc.steps_for("undo that", session, bridge)[0][1]()
    steps = bc.steps_for("undo that", session, bridge)
    with pytest.raises(RuntimeError, match="nothing I've done"):
        steps[0][1]()


def test_redo_is_an_honest_no_op():
    steps = bc.steps_for("redo", new_session(), FakeBridge())
    result = steps[0][1]()
    assert "nothing to redo" in result.lower()


# ---------- "go back to Blender" / "switch to Blender": a plain window-focus action, no bpy needed ----------

@pytest.mark.parametrize("text", ["go back to Blender", "go to Blender", "switch to Blender", "bring Blender",
                                  "focus on Blender"])
def test_focus_blender_phrasings_are_recognized(text, monkeypatch):
    import app_launcher
    import winctl
    monkeypatch.setattr(app_launcher, "app_windows", lambda name: [(123, "Blender")])
    focused = []
    monkeypatch.setattr(winctl, "focus", lambda hwnd: focused.append(hwnd))
    steps = bc.steps_for(text, new_session(), FakeBridge())
    assert steps is not None
    assert "Done" in steps[0][1]()
    assert focused == [123]


def test_focus_blender_fails_cleanly_when_blender_is_not_open(monkeypatch):
    import app_launcher
    monkeypatch.setattr(app_launcher, "app_windows", lambda name: [])
    steps = bc.steps_for("go back to Blender", new_session(), FakeBridge())
    with pytest.raises(RuntimeError, match="doesn't seem to be open"):
        steps[0][1]()


# ---------- move-next-to: already being there is honest success, not a reported failure ----------

def test_move_next_to_reports_honest_success_when_already_there():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    session.remember_blender_object("Cube.001", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "(3.0, 0, 0)|(3.0, 0, 0)"}])
    steps = bc.steps_for("move it next to the first one", session, bridge)
    result = steps[0][1]()
    assert "already" in result.lower() and "Done" in result


# ---------- never invent a technical interpretation of vague/incomplete language ----------

@pytest.mark.parametrize("text", ["it's sticky", "that's weird", "Take it to a level.", "Make the cube totally."])
def test_vague_or_incomplete_text_is_not_concrete(text):
    assert not bc.looks_concrete(text)


@pytest.mark.parametrize("text", ["create a cube", "make it taller", "build a simple house", "delete the cube",
                                  "change its color to red", "go back to Blender", "switch to Blender"])
def test_concrete_instructions_are_recognized_as_concrete(text):
    assert bc.looks_concrete(text)
