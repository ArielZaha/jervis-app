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
        if "in scene.objects else '0'" in code:   # "is this tracked object still there?": yes, unless a test says
            return {"ok": True, "output": "1"}
        if "# scene names" in code:                 # the scene's object names: none beyond what a test tracks
            return {"ok": True, "output": ""}
        if "asset_info(" in code and "rebuild_asset(" not in code:   # "part of a finished asset?": no, unless a
            return {"ok": True, "output": getattr(self, "asset_part", "")}   # test says so
        if "# colour targets" in code:              # nothing beyond what was named, unless a test says so
            return {"ok": True, "output": getattr(self, "colour_targets", "[]")}
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


def test_them_means_what_was_just_worked_on():
    # "make the roof red" ... "no, I meant the windows" ... "now make them bigger": them = the windows
    session = new_session()
    for name in ("House Walls", "House Roof", "House Windows"):
        session.remember_blender_object(name, "")
    assert bc._resolve_reference("the windows", session) == "House Windows"
    for pronoun in ("them", "those", "these"):
        assert bc._resolve_reference(pronoun, session) == "House Windows"


@pytest.mark.parametrize("said, means", [
    ("now increase them", "make them bigger"), ("enlarge it", "make it bigger"),
    ("grow the tree a bit", "make the tree bigger"), ("shrink it", "make it smaller"),
    ("decrease the roof", "make the roof smaller"), ("increase the size of the door", "make the door bigger"),
])
def test_resize_verbs_mean_bigger_or_smaller(said, means):
    assert bc.normalize(said) == means and bc.is_command(said)


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
    assert not any("obj.scale" in c for c in bridge.calls)   # asked the scene, never ran a resize


def test_resize_finds_blenders_default_cube_in_the_scene():
    """Blender opens with a "Cube" Jervis never created: "make the cube bigger" must still reach it."""
    session = new_session()
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"},
                                   {"ok": True, "output": "(1.0, 1.0, 1.0)|(2.0, 2.0, 2.0)"}])
    result = bc.steps_for("Make the cube two times bigger.", session, bridge)[0][1]()
    assert "Cube" in result and "2 times bigger" in result
    assert "obj.scale[0]*2.0" in bridge.calls[-1]
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
    # Blender reports every top-level object whose place changed (the whole group, when a group moves)
    bridge._responses = [{"ok": True, "output": '{"Cube.001": [0.0, 0.0, 0.0]}'}]
    result = steps[0][1]()
    assert "Done" in result and "already" not in result
    assert "Cube.001" in session.last_undo["code"]


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


# ---------- undo reverses Jervis's own last action (bpy.ops.ed.undo's poll() rejects calls from a script context,
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
    bridge = FakeBridge(responses=[{"ok": True, "output": "{}"}])
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


# ---------- more everyday commands, chained commands, and what the user actually said ----------

@pytest.mark.parametrize("text", ["make it red", "color the cube blue", "change the color of the cube to green",
                                  "paint it pink", "rotate it 45 degrees", "rotate the cube 30 degrees around x",
                                  "spin it", "delete the cube", "remove it", "duplicate it", "copy the cube",
                                  "select the cube", "scale it by 3", "scale the cube up by two", "double the cube",
                                  "make it half the size", "make it twice as big",
                                  "Select the cube and make it size 2 times bigger.",
                                  "So, make the cube two times the big hill.",
                                  "In Blender, create a cube.", "create a sphere and make it red",
                                  "create a cube then move it left and rotate it 90 degrees"])
def test_everyday_commands_are_recognized_without_the_ai(text):
    assert bc.is_command(text), text
    assert bc.steps_for(text, new_session(), FakeBridge()) is not None


@pytest.mark.parametrize("text", ["remove the timer", "copy that link to the clipboard and send it",
                                  "rotate the tires on my car", "turn on the lights", "create a cube and a house",
                                  "make me a sandwich"])
def test_things_that_are_not_blender_object_commands(text):
    assert not bc.is_command(text)


def test_select_then_resize_works_on_the_selected_object():
    session = new_session()
    bridge = FakeBridge(responses=[{"ok": True, "output": "Cube"},                  # scene: "the cube" -> Cube
                                   {"ok": True, "output": "Cube"},                  # selected
                                   {"ok": True, "output": "(1.0, 1.0, 1.0)|(2.0, 2.0, 2.0)"}])
    steps = bc.steps_for("Select the cube and make it size 2 times bigger.", session, bridge)
    assert [d for d, _ in steps] == ["Selecting the cube", "Making it bigger"]
    results = [action() for _, action in steps]
    assert "Cube is selected" in results[0] and "2 times bigger" in results[1]
    assert "obj.scale[0]*2.0" in bridge.calls[-1]


@pytest.mark.parametrize("shape,arg", [("sphere", "radius=1"), ("cylinder", "depth=2"), ("torus", "major_radius"),
                                       ("cube", "size=2")])
def test_each_shape_gets_the_size_argument_its_operator_accepts(shape, arg):
    bridge = FakeBridge(responses=[{"ok": True, "output": shape.title()}, {"ok": True, "output": "1"}])
    bc.steps_for(f"create a {shape}", new_session(), bridge)[0][1]()
    assert arg in bridge.calls[0]
    if shape != "cube":
        assert "size=2" not in bridge.calls[0]


def test_color_verifies_the_material_and_can_be_undone():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "Material|Jervis red"}])
    assert "red" in bc.steps_for("make it red", session, bridge)[0][1]()
    assert "Material" in session.last_undo["code"]


def test_color_does_not_claim_success_when_the_material_did_not_change():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "Material|Material"}])
    with pytest.raises(RuntimeError, match="won't claim"):
        bc.steps_for("make it red", session, bridge)[0][1]()


def test_delete_forgets_the_object_and_undo_relinks_it():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "Collection|Cube|1"}])
    assert "deleted Cube" in bc.steps_for("delete it", session, bridge)[0][1]()
    assert session.blender_objects == []
    assert "objects.link" in session.last_undo["code"]


def test_rotate_defaults_to_90_degrees_around_z():
    session = new_session()
    session.remember_blender_object("Cube", "cube")
    bridge = FakeBridge(responses=[{"ok": True, "output": "(0, 0, 0)|(0, 0, 1.57)"}])
    result = bc.steps_for("rotate it", session, bridge)[0][1]()
    assert "90 degrees around Z" in result and "rotation_euler[2]" in bridge.calls[-1]


def test_a_tracked_object_deleted_by_hand_is_looked_up_in_the_scene_instead():
    session = new_session()
    session.remember_blender_object("Cube.001", "cube")

    class Bridge(FakeBridge):
        def run(self, code, timeout=15):
            self.calls.append(code)
            if "in scene.objects else '0'" in code:
                return {"ok": True, "output": "0"}            # Cube.001 is gone
            if "pick = " in code:
                return {"ok": True, "output": "Cube"}         # the scene still has Blender's own Cube
            return {"ok": True, "output": "(1, 1, 1)|(2, 2, 2)"}
    result = bc.steps_for("make the cube bigger", session, Bridge())[0][1]()
    assert "Cube bigger" in result and session.blender_objects == [{"name": "Cube", "kind": ""}]


# ---------- "it" after a multi-part build means the whole build ----------

def test_it_after_a_multi_part_build_means_every_part():
    import json
    session = new_session()
    session.remember_blender_object("Tree Trunk", "")
    session.remember_blender_object("Tree Crown", "")
    session.blender_focus, session.blender_focus_group = "Tree Crown", ["Tree Trunk", "Tree Crown"]
    before = {"Tree Trunk": [[0, 0, 0], [0, 0, 0], [1, 1, 1], None], "Tree Crown": [[0, 0, 2], [0, 0, 0], [1, 1, 1], None]}
    after = {"Tree Trunk": [[0, 0, 0], [0, 0, 0], [2, 2, 2], None], "Tree Crown": [[0, 0, 4], [0, 0, 0], [2, 2, 2], None]}
    bridge = FakeBridge(responses=[{"ok": True, "output": json.dumps([before, after])}])
    result = bc.steps_for("make it two times bigger", session, bridge)[0][1]()
    assert "all 2 parts" in result
    assert "'Tree Trunk', 'Tree Crown'" in bridge.calls[0] and "Matrix.Diagonal((2.0, 2.0, 2.0" in bridge.calls[0]
    assert "Tree Crown" in session.last_undo["code"]


def test_naming_one_part_narrows_it_back_to_that_part():
    session = new_session()
    session.remember_blender_object("Tree Trunk", "")
    session.blender_focus_group = ["Tree Trunk", "Tree Crown"]
    bridge = FakeBridge(responses=[{"ok": True, "output": "(1, 1, 1)|(2, 2, 2)"}])   # resolved from memory
    bc.steps_for("make the tree trunk bigger", session, bridge)[0][1]()
    assert session.blender_focus_group is None


def test_a_build_that_changes_nothing_is_not_claimed():
    import json
    session = new_session()
    session.blender_focus_group = ["A", "B"]
    same = {"A": [[0, 0, 0], [0, 0, 0], [1, 1, 1], None]}
    bridge = FakeBridge(responses=[{"ok": True, "output": json.dumps([same, same])}])
    with pytest.raises(RuntimeError, match="won't claim"):
        bc.steps_for("move it left", session, bridge)[0][1]()


@pytest.mark.parametrize("text", ["put a bench next to the tree", "place an apple next to the bowl",
                                  "put two chairs next to the table"])
def test_putting_a_new_thing_somewhere_is_a_build_not_a_move(text):
    assert not bc.is_command(text)


def test_the_car_means_every_part_of_the_car():
    import json
    session = new_session()
    for name in ("House Walls", "Car Body", "Car Cabin", "Car Wheel 1", "Car Wheel 2"):
        session.remember_blender_object(name, "")
    before = {"Car Body": [[0, 0, 0], [0, 0, 0], [1, 1, 1], None]}
    after = {"Car Body": [[0, 0, 0], [0, 0, 0], [2, 2, 2], None]}
    bridge = FakeBridge(responses=[{"ok": True, "output": json.dumps([before, after])}])
    result = bc.steps_for("make the car two times bigger", session, bridge)[0][1]()
    assert "all 4 parts" in result and "House Walls" not in bridge.calls[0]


def test_one_named_part_is_still_just_that_part():
    session = new_session()
    for name in ("House Walls", "House Roof"):
        session.remember_blender_object(name, "")
    assert bc._focus_group("the roof", session) is None
    assert bc._focus_group("the house", session) == ["House Walls", "House Roof"]


def test_ball_and_box_find_the_sphere_and_cube_jervis_made():
    from types import SimpleNamespace
    session = SimpleNamespace(blender_objects=[{"name": "Cube.001", "kind": "cube"}, {"name": "Sphere", "kind": "sphere"}],
                              blender_focus=None, last_blender_object="Sphere")
    assert bc._resolve_tracked("the ball", session) == "Sphere"
    assert bc._resolve_tracked("the box", session) == "Cube.001"


# ---------- parts of finished assets (blender_assets: a house's windows share the house's origin) ----------

def _house_part_bridge():
    import json
    bridge = FakeBridge()
    bridge.asset_part = json.dumps({"root": "House", "type": "house", "params": {"window_scale": 1.0, "style": "cottage"}})
    return bridge


def test_bigger_windows_on_a_house_rebuild_it_with_bigger_windows_instead_of_scaling_the_frames():
    import json
    session = new_session()
    session.remember_blender_object("House Window Frames", "")
    bridge = _house_part_bridge()
    bridge._responses = [{"ok": True, "output": json.dumps({"House": [[0, 0, 0], [0, 0, 0], [1, 1, 1], None, None, 7]})},
                         {"ok": True, "output": json.dumps({"window_scale": 1.4, "style": "cottage"})}]
    steps = bc.steps_for("make the windows bigger", session, bridge)
    result = steps[0][1]()
    rebuild = next(c for c in bridge.calls if "rebuild_asset(" in c)
    assert "window_scale=1.4" in rebuild   # one "bigger" step (RESIZE_FACTOR)
    assert not any("obj.scale = (" in c for c in bridge.calls)   # the frames object itself was never scaled
    assert "windows" in result
    assert session.last_undo and "session_uid" in session.last_undo["code"]   # undo brings the old house back


def test_a_rebuild_that_did_not_take_is_never_reported_as_done():
    import json
    session = new_session()
    session.remember_blender_object("House Window Frames", "")
    bridge = _house_part_bridge()
    bridge._responses = [{"ok": True, "output": "{}"},
                         {"ok": True, "output": json.dumps({"window_scale": 1.0})}]   # unchanged
    steps = bc.steps_for("make the windows bigger", session, bridge)
    with pytest.raises(RuntimeError):
        steps[0][1]()


def test_another_asset_part_grows_from_its_own_base_not_the_assets_origin():
    import json
    session = new_session()
    session.remember_blender_object("House Chimney", "")
    bridge = _house_part_bridge()
    bridge._responses = [{"ok": True, "output": json.dumps([{"House Chimney": [[0, 0, 0], [0, 0, 0], [1, 1, 1], None]},
                                                            {"House Chimney": [[0, 0, 0], [0, 0, 0], [1, 1, 1.5], None]}])}]
    steps = bc.steps_for("make the chimney taller", session, bridge)
    steps[0][1]()
    assert any("pivot" in c and "House Chimney" in c for c in bridge.calls)


# ---------- corrections: "no, the roof" / "the door too" ----------

def test_no_the_roof_undoes_the_last_change_and_does_it_to_the_roof():
    session = new_session()
    session.remember_blender_object("House Roof", "")
    session.last_deterministic_text = "make it bigger"
    session.last_undo = {"description": "made it bigger", "code": "RESULT = 'restored'"}
    steps = bc.steps_for("no, the roof", session, FakeBridge())
    assert [d for d, _ in steps][0] == "Undoing that"
    assert len(steps) == 2
    assert session.last_deterministic_text == "make the roof bigger"


def test_the_door_too_does_it_again_without_undoing():
    session = new_session()
    session.remember_blender_object("House Shutters", "")
    session.remember_blender_object("House Door", "")
    session.last_deterministic_text = "make the shutters red"
    session.last_undo = {"description": "colored it red", "code": "RESULT = 'restored'"}
    steps = bc.steps_for("the door too", session, FakeBridge())
    assert len(steps) == 1 and "Undoing" not in steps[0][0]
    assert session.last_deterministic_text == "make the door red"


def test_a_correction_with_nothing_to_correct_is_left_to_the_slower_paths():
    assert bc.steps_for("no, the roof", new_session(), FakeBridge()) is None


@pytest.mark.parametrize("text", ["no", "not that one", "the shutters blue", "no thanks I'm fine with it now"])
def test_not_every_no_is_a_correction(text):
    assert bc.correction(text) is None
