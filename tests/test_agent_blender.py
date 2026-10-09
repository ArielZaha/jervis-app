"""The Blender adapter's checks, auto-fixes and error handling, against hand-made scene states (no Blender)."""
import pytest

import agent_blender
import blender_kit


def obj(name, mn, mx, color=None, kind="MESH"):
    return {"name": name, "type": kind, "min": list(mn), "max": list(mx), "location": list(mn),
            "size": [b - a for a, b in zip(mn, mx)], "color_name": color}


HOUSE = {"objects": [obj("House Walls", (-2, -1.5, 0), (2, 1.5, 2.5), "orange"),
                     obj("House Roof", (-2.2, -1.7, 2.5), (2.2, 1.7, 4), "red"),
                     obj("Door", (-0.45, -1.6, 0), (0.45, -1.5, 1.9), "brown"),
                     obj("Window 1", (-1.6, -1.6, 1.1), (-0.8, -1.5, 1.9), "blue"),
                     obj("Window 2", (0.8, -1.6, 1.1), (1.6, -1.5, 1.9), "blue"),
                     obj("Camera", (7, -7, 5), (7, -7, 5), kind="CAMERA")]}
adapter = agent_blender.BlenderAdapter(bridge=None)


@pytest.mark.parametrize("check,expected", [
    ({"type": "exists", "object": "House Roof"}, True),
    ({"type": "exists", "object": "house roof"}, True),              # case-insensitive
    ({"type": "exists", "object": "Chimney"}, False),
    ({"type": "absent", "object": "Chimney"}, True),
    ({"type": "color", "object": "House Roof", "color": "red"}, True),
    ({"type": "color", "object": "House Roof", "color": "dark red"}, True),   # same family
    ({"type": "color", "object": "House Roof", "color": "blue"}, False),
    ({"type": "above", "object": "House Roof", "other": "House Walls"}, True),
    ({"type": "above", "object": "Door", "other": "House Walls"}, False),
    ({"type": "on_top", "object": "House Roof", "other": "House Walls"}, True),
    ({"type": "touching", "object": "Door", "other": "House Walls"}, True),
    ({"type": "count", "object": "Window", "min": 2}, True),
    ({"type": "count", "object": "Window", "min": 3}, False),
    ({"type": "near", "object": "Door", "other": "Window 1", "max": 1}, True),
    ({"type": "size", "object": "House Walls", "min": 3, "max": 5}, True),
])
def test_checks_against_the_real_scene_state(check, expected):
    passed, detail = adapter.evaluate(check, HOUSE)
    assert passed is expected, detail


def test_failed_checks_explain_what_is_actually_there():
    passed, detail = adapter.evaluate({"type": "color", "object": "House Roof", "color": "blue"}, HOUSE)
    assert not passed and "red" in detail
    passed, detail = adapter.evaluate({"type": "above", "object": "Door", "other": "House Walls"}, HOUSE)
    assert "z=0" in detail and "2.5" in detail


def test_unknown_color_cant_be_verified_rather_than_failing():
    assert adapter.evaluate({"type": "color", "object": "Door", "color": "blurple"}, HOUSE)[0] is None


@pytest.mark.parametrize("rgb,family", [((0.8, 0.03, 0.03), "red"), ((0.25, 0.1, 0.03), "brown"),
                                        ((0.9, 0.3, 0.02), "orange"), ((0.05, 0.5, 0.05), "green"),
                                        ((0.02, 0.1, 0.8), "blue"), ((0.9, 0.9, 0.9), "white"),
                                        ((0.01, 0.01, 0.01), "black"), ((0.9, 0.3, 0.5), "pink")])
def test_color_families(rgb, family):
    assert blender_kit.color_name(rgb) == family


def test_auto_checks_come_from_the_names_the_code_builds():
    code = ("box('Table Top', (1, 1, 0.1), at=(0, 0, 0.7))\nfor i in range(4):\n    box(f'Leg {i}', 0.1)\n"
            "duplicate('Table Top', 'Table Top 2', at=(3, 0, 0.7))")
    names = {c["object"] for c in adapter.auto_checks(code)}
    assert names == {"Table Top", "Table Top 2"}            # f-string names can't be checked literally


def test_size_checks_are_dropped_unless_the_user_talked_about_size():
    checks = [{"type": "size", "object": "Ball", "min": 0.4, "max": 0.6}, {"type": "exists", "object": "Ball"},
              {"type": "exists", "object": "Ball"}, {"type": "teleport"}]
    assert adapter.usable_checks(checks, "build a snowman") == [{"type": "exists", "object": "Ball"}]
    assert len(adapter.usable_checks(checks, "a 2 metre tall snowman")) == 2


def test_new_floating_objects_are_flagged_but_attached_or_grounded_ones_are_not():
    state = {"objects": [obj("Trunk", (0, 0, 1), (0.2, 0.2, 3)),                  # floats: nothing under it
                         obj("Crown", (-0.5, -0.5, 2.9), (0.7, 0.7, 4)),          # touches the trunk: fine
                         obj("Ground Box", (5, 5, 0), (6, 6, 1)),
                         obj("Eye", (5.4, 4.95, 0.6), (5.5, 5.0, 0.7))]}          # on the box's side: attached
    problems = adapter.extra_failures(before={}, state=state, goal="add a tree")
    floating = [p for p in problems if "floats in the air" in p]
    assert len(floating) == 1 and "'Trunk' (and 1 part(s) attached to it) floats" in floating[0]
    assert any("trunk doesn't stand on the ground" in p for p in problems)      # the anatomy rule sees it too
    assert not any("floats in the air" in p for p in adapter.extra_failures(before={}, state=state,
                                                                             goal="add a flying saucer"))


def test_settling_drops_a_floating_group_onto_what_is_below_it():
    state = {"objects": [obj("Base", (-0.6, -0.6, 0), (0.6, 0.6, 1.2)),
                         obj("Middle", (-0.4, -0.4, 1.5), (0.4, 0.4, 2.3)),              # 0.3 m above Base
                         obj("Button", (-0.05, -0.45, 1.8), (0.05, -0.38, 1.9))]}       # stuck on Middle
    names, drop, onto = agent_blender.BlenderAdapter._settle_once(before={"Base": 1}, state=state)
    assert names == ["Middle", "Button"] and drop == pytest.approx(0.3) and onto == "'Base'"


def test_settling_leaves_grounded_and_supported_things_alone():
    state = {"objects": [obj("Base", (-0.6, -0.6, 0), (0.6, 0.6, 1.2)),
                         obj("Middle", (-0.4, -0.4, 1.2), (0.4, 0.4, 2.0))]}
    assert agent_blender.BlenderAdapter._settle_once(before={}, state=state) is None


def test_errors_point_at_the_ais_code_and_suggest_the_kit_for_invented_helpers():
    traceback_text = ('Traceback (most recent call last):\n  File "bridge.py", line 42, in process_one\n'
                      '  File "<jervis>", line 3, in <module>\nNameError: name \'door\' is not defined')
    message = adapter._short_error({"error": traceback_text})
    assert "line 3 of your code" in message and "no door() in the kit" in message


def test_restore_code_is_valid_python_for_any_names():
    code = agent_blender._restore_code({"Roof 'A'": [[0, 0, 0], [0, 0, 0], [1, 1, 1], None, None]})
    compile(code, "<restore>", "exec")


def test_the_kit_is_importable_outside_blender_and_knows_its_colors():
    assert blender_kit.bpy is None
    assert blender_kit.rgb_of("#ff0000") == (1.0, 0.0, 0.0)
    assert blender_kit.rgb_of("bright red roof") == blender_kit.COLORS["red"]
    with pytest.raises(ValueError):
        blender_kit.rgb_of("blurple")


@pytest.mark.parametrize("code,goal,refused", [
    ("clear_scene()\nbox('Car', 1)", "build a car", True),
    ("clear_scene()\nbox('Car', 1)", "clear everything and build a car", False),
    ("clear_scene()", "start over with an empty scene", False),
    ("delete('Cube')\nbox('Car', 1)", "build a car", True),
    ("delete('Cube')", "remove the cube", False),
    ("box('Roof', 1)", "build a roof", False),
])
def test_destroying_what_the_user_didnt_ask_to_touch_is_refused(code, goal, refused):
    assert bool(adapter.guard(code, goal)) is refused


def test_a_refused_step_goes_back_to_the_ai_as_an_error_and_is_never_run():
    import agent_core

    class Recorder(agent_blender.BlenderAdapter):
        def __init__(self):
            super().__init__(bridge=None)
            self.ran = []

        def available(self): return True, ""
        def prepare(self): pass
        def finished(self, before, success, goal): pass
        def snapshot(self): return {}
        def rollback(self, snap): pass
        def observe(self): return {"objects": [obj("Robot", (0, 0, 0), (1, 1, 1))] if self.ran else []}
        def execute(self, code):
            self.ran.append(code)
            return {"ok": True, "output": "", "error": ""}

    answers = iter([{"understanding": "Build a robot.", "question": "", "final_checks": [],
                     "steps": [{"title": "Robot", "code": "delete('Cube')\nbox('Robot', 1)"}]},
                    {"diagnosis": "don't clear", "code": "box('Robot', 1)", "checks_were_wrong": False}])
    seen = []

    def ask(messages, schema, **kw):
        seen.append(messages[-1]["content"])
        return next(answers)
    app_adapter = Recorder()
    task = agent_core.AgentTask("build a robot", app_adapter, ask_json=ask, log=lambda m: None)
    task.run()
    assert app_adapter.ran == ["box('Robot', 1)"]            # the clearing code never reached Blender
    assert "the user didn't ask to remove anything" in seen[1]


def test_an_unrequested_clear_scene_line_is_dropped_but_a_requested_one_kept():
    assert adapter.sanitize("clear_scene()\nbox('Car', 1)", "build a car") == "box('Car', 1)"
    assert adapter.sanitize("clear_scene()", "build a car") == ""
    assert adapter.sanitize("clear_scene()\nbox('Car', 1)", "start over and build a car").startswith("clear_scene")


def test_brushing_the_side_of_something_doesnt_hold_a_bench_up():
    state = {"objects": [obj("Tree Trunk", (2.9, -0.1, 0), (3.1, 0.1, 3)),
                         obj("Bench Seat", (3.1, -0.2, 0.5), (3.9, 0.2, 0.6)),
                         obj("Bench Leg", (3.1, -0.2, 0.6), (3.15, -0.15, 1.0))]}
    floating = agent_blender.BlenderAdapter._floating_groups(before={"Tree Trunk": 1}, state=state)
    assert floating and floating[0][0][0] == "Bench Seat" and floating[0][3] == "the ground"


def test_a_thin_window_on_a_wall_is_attached_not_floating():
    state = {"objects": [obj("Wall", (-2, -0.1, 0), (2, 0.1, 3)),
                         obj("Window", (-0.5, -0.15, 1.2), (0.5, -0.1, 2.0))]}
    assert agent_blender.BlenderAdapter._floating_groups(before={"Wall": 1}, state=state) == []


def test_a_new_thing_built_inside_an_existing_one_is_moved_beside_it():
    state = {"objects": [obj("Bench Seat", (3.1, -0.2, 0.4), (3.9, 0.2, 0.6)),
                         obj("Car Body", (3.5, -0.6, 0.3), (6.0, 0.6, 1.2))]}
    names, other, (dx, dy) = agent_blender.BlenderAdapter._collision(before={"Bench Seat": 1}, state=state)
    assert names == ["Car Body"] and other == "Bench Seat"
    assert (dx, dy) == (1.0, 0)                         # the nearest shift that clears it, with room to spare


def test_a_collision_is_resolved_against_everything_at_once_not_one_obstacle_at_a_time():
    state = {"objects": [obj("House", (2, -2, 0), (6, 2, 3)), obj("Tree", (-1.5, -0.3, 0), (-0.9, 0.3, 3)),
                         obj("Car", (-1, -0.8, 0), (2.5, 0.8, 1.5))]}
    names, other, (dx, dy) = agent_blender.BlenderAdapter._collision(before={"House": 1, "Tree": 1}, state=state)
    moved = obj("Car", (-1 + dx, -0.8 + dy, 0), (2.5 + dx, 0.8 + dy, 1.5))
    for p in state["objects"][:2]:
        assert min(min(moved["max"][i], p["max"][i]) - max(moved["min"][i], p["min"][i]) for i in range(3)) <= 0.1


def test_resting_on_top_or_set_into_a_wall_is_not_a_collision():
    lamp = {"objects": [obj("Table", (-1, -0.5, 0), (1, 0.5, 0.75)), obj("Lamp", (0, 0, 0.7), (0.3, 0.3, 1.2))]}
    assert agent_blender.BlenderAdapter._collision(before={"Table": 1}, state=lamp) is None
    door = {"objects": [obj("Wall", (-2, -0.1, 0), (2, 0.1, 3)), obj("Door", (-0.45, -0.12, 0), (0.45, 0.0, 2))]}
    assert agent_blender.BlenderAdapter._collision(before={"Wall": 1}, state=door) is None


def test_only_self_contained_builds_are_good_examples():
    steps = [{"title": "Snowman", "code": "sphere('Snowball 1', 0.5, at=(0, 0, top('House Roof')), color='white')"}]
    assert not adapter.self_contained(steps, ["Snowball 1"])
    steps = [{"title": "Snowman", "code": "sphere('Snowball 1', 0.5, color='white')\n"
                                          "sphere('Snowball 2', 0.3, at=(0, 0, top('Snowball 1')))"}]
    assert adapter.self_contained(steps, ["Snowball 1", "Snowball 2"])
    assert not adapter.self_contained([{"title": "c", "code": "color('Tree Leaf 1', 'green')"}], [])


def test_a_free_spot_is_offered_beside_whats_already_there():
    assert agent_blender.free_spot({"objects": []}) == (0, 0)
    assert agent_blender.free_spot(HOUSE) == (6, 0)          # the house reaches x=2.2; 4 m on
    assert "Free space for something new: around x=6, y=0" in adapter.describe(HOUSE)


def test_a_crown_sinking_into_its_trunk_is_still_above_it():
    state = {"objects": [obj("Trunk", (-0.2, -0.2, 0), (0.2, 0.2, 2.5)), obj("Crown", (-1.3, -1.3, 2.0), (1.3, 1.3, 4.6))]}
    assert adapter.evaluate({"type": "above", "object": "Crown", "other": "Trunk"}, state)[0] is True



def test_anatomy_catches_a_bench_built_upside_down():
    bench = {"objects": [obj("Bench Seat", (-0.7, -0.2, 0), (0.7, 0.2, 0.06)),
                         obj("Bench Leg 1", (-0.7, -0.2, 0.06), (-0.64, -0.14, 0.5)),
                         obj("Bench Leg 2", (0.64, -0.2, 0.06), (0.7, -0.14, 0.5))]}
    problems = adapter.extra_failures(before={}, state=bench, goal="build a bench")
    assert any("don't reach the ground" in p for p in problems)
    assert any("must rest ON the legs" in p for p in problems)


def test_a_well_built_bench_has_no_structural_problems():
    bench = {"objects": [obj(f"Bench Leg {i}", (x, y, 0), (x + 0.06, y + 0.06, 0.42))
                         for i, (x, y) in enumerate([(-0.7, -0.2), (0.64, -0.2), (-0.7, 0.14), (0.64, 0.14)], 1)]
             + [obj("Bench Seat", (-0.7, -0.2, 0.42), (0.7, 0.2, 0.48)),
                obj("Bench Backrest", (-0.7, 0.15, 0.48), (0.7, 0.2, 0.9))]}
    assert adapter.extra_failures(before={}, state=bench, goal="build a bench") == []


def test_a_chair_on_two_diagonal_legs_would_tip_over():
    chair = {"objects": [obj("Chair Leg 1", (-0.22, -0.21, 0), (-0.18, -0.17, 0.45)),
                         obj("Chair Leg 2", (0.18, 0.17, 0), (0.22, 0.21, 0.45)),
                         obj("Chair Seat", (-0.23, -0.22, 0.45), (0.23, 0.22, 0.49))]}
    assert any("tip over" in p for p in adapter.extra_failures(before={}, state=chair, goal="build a chair"))


def test_quality_critic_on_a_primitive_tree():
    tree = {"objects": [dict(obj("Tree Trunk", (-0.2, -0.2, 0), (0.2, 0.2, 2.5)), kind="cylinder", material="m"),
                        dict(obj("Tree Crown", (-1.3, -1.3, 2.0), (1.3, 1.3, 4.6)), kind="sphere", material="m")]}
    issues = adapter.quality_issues({}, tree, "add a tree", "normal")
    assert any("bare primitives" in i for i in issues)
    assert any("Only 2 part" in i for i in issues)
    assert any("flat colours" in i for i in issues)


def test_quality_critic_is_happy_with_a_modelled_tree():
    parts = [dict(obj("Tree Trunk", (-0.3, -0.3, 0), (0.3, 0.3, 2.6)), kind="tube", shaped=True, material="b",
                  textured=True)]
    parts += [dict(obj(f"Tree Leaves {i}", (i * 0.3, 0, 2.2 + i * 0.05), (i * 0.3 + 0.8 + i * 0.07, 0.9, 3.0 + i * 0.1)),
                   kind="blob", shaped=True, material="l", textured=True) for i in range(1, 8)]
    assert adapter.quality_issues({}, {"objects": parts}, "add a tree", "normal") == []


def test_nothing_new_means_nothing_to_critique():
    assert adapter.quality_issues({"House Roof": 1}, {"objects": [obj("House Roof", (0, 0, 2), (1, 1, 3))]},
                                  "make the roof blue", "normal") == []


def test_scene_things_get_names_not_already_in_the_scene():
    state = {"objects": [obj("Bench Seat", (0, 0, 0), (1, 1, 1)), obj("Tree 1 Trunk", (3, 0, 0), (4, 1, 3))]}
    placed = adapter.place_scene([{"name": "Bench", "request": "b", "x": 0, "y": 0},
                                  {"name": "Tree 1", "request": "t", "x": 4, "y": 0},
                                  {"name": "Rocks", "request": "r", "x": 0, "y": 0, "radius": 1}], state)
    names = [t["name"] for t in placed]
    assert names[0] == "Bench 2" and names[1] == "Tree 2" and names[2] == "Rocks"
    (x0, y0), (x2, y2) = (placed[0]["x"], placed[0]["y"]), (placed[2]["x"], placed[2]["y"])
    assert ((x0 - x2) ** 2 + (y0 - y2) ** 2) ** 0.5 > 2.0        # two things at the same spot were pushed apart


def test_legs_underground_and_off_to_the_side_are_caught():
    bench = {"objects": [obj("Bench Seat", (4.65, -0.1, 0), (5.35, 0.1, 0.05)),
                         obj("Bench Leg 1", (4.63, -0.42, -0.4), (4.67, -0.38, 0)),
                         obj("Bench Leg 2", (5.33, -0.42, -0.4), (5.37, -0.38, 0))]}
    problems = adapter.extra_failures(before={}, state=bench, goal="build a wooden park bench")
    assert any("below the ground" in p for p in problems) and any("aren't under the seat" in p for p in problems)


def test_a_build_far_from_real_world_size_is_rescaled_but_asked_sizes_are_respected():
    tiny = [obj("Bench Seat", (0, 0, 0.1), (0.4, 0.12, 0.13)), obj("Bench Leg 1", (0, 0, 0), (0.02, 0.02, 0.1))]
    factor, why = agent_blender._rescale_for("a wooden park bench", tiny)
    assert 3 < factor < 5 and "bench" in why
    assert agent_blender._rescale_for("a tiny bench", tiny) is None                 # the user chose the size
    assert agent_blender._rescale_for("a bench and a tree", tiny) is None           # two things: can't tell
    assert agent_blender._rescale_for("build a bench", [obj("Bench Seat", (0, 0, 0.45), (1.5, 0.42, 0.5))]) is None


def test_scene_naming_instructions_dont_hide_the_thing_being_built():
    tiny = [obj("Bench Seat", (0, 0, 0.1), (0.4, 0.12, 0.13)), obj("Bench Leg 1", (0, 0, 0), (0.02, 0.02, 0.1))]
    goal = "a wooden park bench — name its parts 'Bench ...', build it at x=6.0, y=0.0 (X, Y) and finish with assemble('Bench')"
    assert agent_blender._rescale_for(goal, tiny) is not None


def test_a_chair_shaped_bench_is_a_proportion_problem_not_a_rescale():
    chairlike = [obj("Bench Seat", (0, 0, 0), (0.46, 0.44, 0.98))]
    verdict = agent_blender._size_verdict("a wooden park bench", chairlike)
    assert verdict[0] == "issue" and "proportions" in verdict[1]
    assert agent_blender._rescale_for("a wooden park bench", chairlike) is None
    assert any("proportions" in i for i in adapter.quality_issues({}, {"objects": [dict(chairlike[0], kind="box",
               material="m", textured=True, modifiers=["BEVEL"])]}, "a wooden park bench", "normal"))


def test_a_group_is_measured_by_its_parts_not_its_empty_root():
    # a built asset's root is an empty: "make the house bigger" checked 'House' and read 0.00 m across
    root = dict(obj("House", (0, 0, 0), (0, 0, 0), kind="EMPTY"), size=[0, 0, 0])
    walls = dict(obj("House Walls", (-6, -4, 0), (6, 4, 6)), parent="House")
    roof = dict(obj("House Roof", (-6.5, -4.5, 6), (6.5, 4.5, 8)), parent="House")
    passed, detail = adapter.evaluate({"type": "size", "object": "House", "min": 12, "max": 14},
                                      {"objects": [root, walls, roof]})
    assert passed, detail
