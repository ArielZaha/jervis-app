"""The Blender adapter's spatial understanding, against a simulated Blender (no real one): it finds where a new
thing goes from the request's words, repairs a pool built inside a villa by moving it, re-lays broken paths, never
counts a step that built nothing as done, stops when a failed step can't be undone, groups loose parts, and lays a
scene out in dependency order. Also the kit's colour parsing outside Blender."""
import json
import re

import pytest

import agent_blender
import agent_core
import blender_kit
import spatial
from agent_core import AppGone
from test_spatial import names, o, pool_inside, villa


class SimBridge:
    """A stand-in for Blender's bridge holding a scene state: answers scene_state(), carries out shift_thing()
    moves on it, reports the last step's record, and records every script it was sent."""

    def __init__(self, objects, step=None, fail=()):
        self.objects = [dict(x) for x in objects]
        self.calls = []
        self.step = step if step is not None else {"made": ["Something"], "warnings": []}
        self.fail = fail          # substrings of code that should fail

    def ping(self, timeout=3):
        return True

    def run(self, code, timeout=15):
        self.calls.append(code)
        if any(f in code for f in self.fail):
            return {"ok": False, "output": "", "error": "Traceback...\nValueError: it broke"}
        if "scene_state()" in code:
            return {"ok": True, "output": json.dumps({"objects": self.objects}), "error": ""}
        if "json.dumps(STEP)" in code:
            return {"ok": True, "output": json.dumps(self.step), "error": ""}
        m = re.search(r"shift_thing\((.*)\)", code)
        if m:
            moved, dx, dy, dz = eval("f(" + m.group(1) + ")", {"f": lambda n, dx=0, dy=0, dz=0, reground=True:
                                                                 (n, dx, dy, dz)})
            for x in self.objects:
                if x["name"] in moved:
                    x["min"] = [x["min"][0] + dx, x["min"][1] + dy, x["min"][2] + dz]
                    x["max"] = [x["max"][0] + dx, x["max"][1] + dy, x["max"][2] + dz]
            return {"ok": True, "output": "ok", "error": ""}
        return {"ok": True, "output": "ok", "error": ""}


def adapter_for(objects, goal, **kw):
    bridge = SimBridge(objects, **kw)
    adapter = agent_blender.BlenderAdapter(bridge)
    adapter.goal = goal
    adapter.intents = adapter._intents(goal)
    return adapter, bridge


def state_of(bridge):
    return {"objects": bridge.objects}


def thing(state, name):
    return next(t for t in spatial.things(state) if t["name"] == name)


# ---------- repairs ----------

def test_a_pool_built_inside_the_villa_is_moved_beside_it():
    adapter, bridge = adapter_for(villa() + pool_inside(), "add a swimming pool beside the villa")
    fixed = adapter.auto_fix(names(villa()), state_of(bridge), adapter.goal)
    assert any("'Pool'" in f and "moved it" in f for f in fixed)
    assert any("shift_thing(" in c and "'Pool Water'" in c for c in bridge.calls)
    after = state_of(bridge)
    ok, why = spatial.check_relation(thing(after, "Pool"), "beside", thing(after, "Villa"))
    assert ok, why
    assert adapter.extra_failures(names(villa()), after, adapter.goal) == []


def test_an_outdoor_thing_inside_a_building_is_moved_out_even_when_nothing_was_said():
    tree = [o("Tree Trunk", (1, 1, 0), (1.4, 1.4, 4)), o("Tree Leaves", (-1, -1, 3), (3, 3, 7))]
    adapter, bridge = adapter_for(villa() + tree, "add a tree")
    fixed = adapter.auto_fix(names(villa()), state_of(bridge), adapter.goal)
    assert any("inside the building" in f for f in fixed)
    assert spatial.overlap_depth(thing(state_of(bridge), "Tree")["rect"], thing(state_of(bridge), "Villa")["core"]) <= 0


def test_a_repair_that_cant_be_made_is_reported_not_hidden():
    adapter, bridge = adapter_for(villa() + pool_inside(), "add a swimming pool beside the villa", fail=("shift_thing(",))
    assert adapter.auto_fix(names(villa()), state_of(bridge), adapter.goal) == []
    failures = adapter.extra_failures(names(villa()), state_of(bridge), adapter.goal)
    assert failures and "'Pool'" in failures[0] and "footprint" in failures[0]


def test_a_broken_new_path_is_re_laid_with_walkway():
    walk = [o("Walk Stone 1", (20, 20, 0), (21, 21, 0.05))]
    adapter, bridge = adapter_for(villa() + pool_inside(x=13) + walk, "add a path from the villa to the pool")
    adapter.auto_fix(names(villa() + pool_inside(x=13)), state_of(bridge), adapter.goal)
    relaid = [c for c in bridge.calls if "walkway(" in c]
    assert relaid and "delete(" in relaid[0] and "'Walk', 'Villa', 'Pool'" in relaid[0]


def test_moving_an_existing_thing_is_checked_but_a_recolour_never_is():
    # the pool was already there (inside the villa): "colour the pool blue" is not about where it stands
    adapter, bridge = adapter_for(villa() + pool_inside(), "colour the pool beside the villa blue")
    assert adapter.extra_failures(names(villa() + pool_inside()), state_of(bridge), adapter.goal) == []


# ---------- steps that fail without an error ----------

def test_a_step_meant_to_build_that_built_nothing_has_failed():
    adapter, bridge = adapter_for([], "build a bench", step={"made": [], "warnings": []})
    result = adapter.execute("for i in []:\n    box(f'Bench Leg {i}', 0.1)")
    assert not result["ok"] and "built nothing" in result["error"]


def test_a_step_that_only_changes_things_needs_no_new_objects():
    adapter, bridge = adapter_for([], "make it red", step={"made": [], "warnings": []})
    assert adapter.execute("color('Bench', 'red')  # not box('x')")["ok"]


def test_kit_warnings_reach_the_step_output():
    adapter, bridge = adapter_for([], "build a crate", step={"made": ["Crate"], "warnings": [
        "Unknown color 4 for 'Crate': used light grey instead"]})
    result = adapter.execute("box('Crate', 1, color=4)")
    assert result["ok"] and "Unknown color 4" in result["output"]
    assert adapter.notes == ["Unknown color 4 for 'Crate': used light grey instead"]


def test_an_unreadable_step_record_never_fails_a_step():
    adapter, bridge = adapter_for([], "build a bench", step="nonsense")
    assert adapter.execute("box('Bench Seat', 1)")["ok"]


def test_a_failed_undo_stops_the_task_instead_of_building_on_a_dirty_scene():
    adapter, bridge = adapter_for([], "build a bench", fail=("snap = json.loads",))
    with pytest.raises(AppGone, match="couldn't undo"):
        adapter.rollback({"Cube": [[0, 0, 0], [0, 0, 0], [1, 1, 1], None, None, 1]})


def test_a_failed_setup_stops_before_anything_is_built():
    adapter, bridge = adapter_for([], "build a bench", fail=("RESULT = 'ready'",))
    with pytest.raises(RuntimeError, match="couldn't get ready"):
        adapter.prepare()


# ---------- where a new thing goes ----------

def test_the_build_spot_for_something_behind_the_villa_is_behind_it():
    adapter, bridge = adapter_for(villa(), "add a fountain behind the villa")
    adapter.prepare()
    setup = next(c for c in bridge.calls if "RESULT = 'ready'" in c)
    x, y = map(float, re.search(r"X, Y = (-?[\d.]+), (-?[\d.]+)", setup).groups())
    assert y > thing(state_of(bridge), "Villa")["core"][3]
    assert "behind 'Villa'" in adapter.describe(state_of(bridge))


def test_a_pool_asset_beside_the_villa_is_placed_and_turned_on_the_real_scene():
    asked = []

    def ask(messages, schema, **kw):
        asked.append(messages[-1]["content"])
        return {"asset": "pool", "options": {}, "count": 1, "understanding": "A pool", "other_things": ""}
    adapter, bridge = adapter_for(villa(), "add a swimming pool beside the villa")
    plan = adapter.quick_plan(adapter.goal, state_of(bridge), ask)
    assert asked == ["Request: add a swimming pool"]          # the AI chooses WHAT; where is measured
    code = plan["steps"][0]["code"]
    x = float(re.search(r"at=\((-?[\d.]+),", code).group(1))
    assert x > thing(state_of(bridge), "Villa")["core"][2] and "rotation=90" in code
    assert plan["final_checks"][0] == {"type": "exists", "object": "Pool Water"}


def test_a_path_between_two_things_is_a_routed_walkway():
    adapter, bridge = adapter_for(villa() + pool_inside(x=14), "add a stone path from the villa to the pool")
    plan = adapter.quick_plan(adapter.goal, state_of(bridge), lambda *a, **k: {})
    assert plan["steps"][0]["code"].startswith("walkway('Path', 'Villa', 'Pool'")
    assert {"type": "connects", "object": "Path", "other": "Villa", "value": "Pool"} in plan["final_checks"]


def test_a_path_to_something_that_isnt_there_is_left_to_the_planner():
    adapter, bridge = adapter_for(villa(), "add a path to the pool")
    assert adapter._path_plan(adapter.goal, adapter.goal, state_of(bridge)) is None


@pytest.mark.parametrize("check,expected", [
    ({"type": "beside", "object": "Pool", "other": "Villa"}, True),
    ({"type": "outside", "object": "Pool", "other": "Villa"}, True),
    ({"type": "in_front_of", "object": "Pool", "other": "Villa"}, False),
    ({"type": "beside", "object": "Pool Water", "other": "Villa Walls"}, True),   # parts stand for their things
    ({"type": "beside", "object": "Pool", "other": "Garage"}, False),
])
def test_spatial_checks(check, expected):
    adapter, bridge = adapter_for(villa() + pool_inside(x=12), "")
    assert adapter.evaluate(check, state_of(bridge))[0] is expected


# ---------- scenes ----------

def test_a_scene_thing_is_placed_by_what_it_stands_beside():
    adapter, bridge = adapter_for(villa(), "")
    placed = adapter.place_thing({"name": "Pool", "request": "a swimming pool", "relation": "beside",
                                  "anchor": "Villa", "x": 0, "y": 0}, state_of(bridge))
    assert placed["x"] > thing(state_of(bridge), "Villa")["core"][2]
    assert placed["placed"].startswith("standing beside 'Villa'") and "rotation=90" in placed["placed"]


def test_a_scene_path_runs_between_its_ends_and_a_loose_thing_gets_a_free_spot():
    adapter, bridge = adapter_for(villa() + pool_inside(x=14), "")
    path = adapter.place_thing({"name": "Path", "request": "a path", "relation": "connects", "anchor": "Villa",
                                "to": "Pool", "x": 0, "y": 0}, state_of(bridge))
    assert path["placed"] == "running from 'Villa' to 'Pool'"
    rock = adapter.place_thing({"name": "Rock", "request": "a rock", "x": 0, "y": 0}, state_of(bridge))
    assert spatial.overlap_depth((rock["x"] - 0.8, rock["y"] - 0.8, rock["x"] + 0.8, rock["y"] + 0.8),
                                 thing(state_of(bridge), "Villa")["core"]) <= 0


def test_the_whole_scene_is_checked_and_corrected_at_the_end():
    adapter, bridge = adapter_for(villa() + pool_inside(), "")
    fixed, wrong = adapter.scene_fix(set(), state_of(bridge), "a villa with a pool",
                                     [{"name": "Villa"}, {"name": "Pool", "relation": "beside", "anchor": "Villa"}])
    assert fixed and wrong == []


def test_loose_parts_are_grouped_so_it_means_the_whole_thing():
    parts = [o("Bench Seat", (0, 0, 0.45), (1.5, 0.4, 0.5)), o("Bench Leg 1", (0, 0, 0), (0.1, 0.1, 0.45))]
    adapter, bridge = adapter_for(parts, "build a bench")
    adapter._group_loose(set(), state_of(bridge))
    assert any(c.startswith("RESULT = assemble('Bench', ['Bench Seat', 'Bench Leg 1'])") for c in bridge.calls)


def test_a_part_added_after_assembling_joins_its_group():
    parts = [o("Bench", (0, 0, 0), (0, 0, 0), type_="EMPTY"), o("Bench Seat", (0, 0, 0.45), (1.5, 0.4, 0.5), "Bench"),
             o("Bench Cushion", (0, 0, 0.5), (1.5, 0.4, 0.6))]
    adapter, bridge = adapter_for(parts, "build a bench")
    adapter._group_loose(set(), state_of(bridge))
    assert any(c.startswith("RESULT = assemble('Bench', ['Bench Cushion'])") for c in bridge.calls)


# ---------- planning a scene ----------

@pytest.mark.parametrize("goal,known,scene", [
    ("a modern villa with a swimming pool beside it", (), True),
    ("add a swimming pool beside the villa", ("Villa", "Villa Walls"), False),
    ("add a swimming pool beside the house", ("Villa",), False),   # it's the building that's there
    ("a red chair", (), False),
])
def test_relations_between_new_things_make_a_scene(goal, known, scene):
    assert agent_core.looks_like_scene(goal, known) is scene


def test_things_are_built_after_what_they_stand_by_and_paths_last():
    things = [{"name": "Path", "relation": "connects", "anchor": "Villa", "to": "Pool"},
              {"name": "Pool", "relation": "beside", "anchor": "Villa"},
              {"name": "Lounger", "relation": "beside", "anchor": "Pool"},
              {"name": "Villa", "relation": ""}]
    assert [t["name"] for t in agent_core.order_things(things)] == ["Villa", "Pool", "Lounger", "Path"]


def test_layout_anchors_are_resolved_to_the_things_names():
    things = agent_core._resolve_names([
        {"name": "Villa", "request": "a modern villa"}, {"name": "Pool", "request": "a pool", "anchor": "the villa"},
        {"name": "Path", "request": "a path", "relation": "connects", "anchor": "the entrance", "to": "the pool"}])
    assert things[1]["anchor"] == "Villa" and (things[2]["anchor"], things[2]["to"]) == ("Villa", "Pool")


class SceneApp(agent_core.AppAdapter):
    """Records the order things are built in, and fails the ones it's told to."""
    name, label, scene_layout = "scene", "SceneApp", True

    def __init__(self, failing=()):
        self.built, self.failing, self.placed = [], set(failing), []

    def quick_plan(self, goal, state, ask_json):
        hint = re.search(r"name its parts '([^']+) \.\.\.'", goal)
        if hint is None:
            return None   # the whole request: laid out as a scene
        name = hint.group(1)
        code = "fail" if name in self.failing else f"make {name}"
        return {"understanding": goal, "question": "", "quick": True, "final_checks": [],
                "steps": [{"title": name, "code": code, "checks": [], "quick": True}]}

    def execute(self, code):
        if code == "fail":
            return {"ok": False, "output": "", "error": "no room"}
        self.built.append(code.split()[1])
        return {"ok": True, "output": "", "error": ""}

    def place_thing(self, thing, state):
        self.placed.append(thing["name"])
        return dict(thing, placed=f"standing beside '{thing['anchor']}'" if thing.get("anchor") else "")

    def scene_fix(self, before, state, goal, things):
        return ["moved Pool"], []


def test_a_scene_is_built_in_order_and_nothing_is_built_on_a_failed_thing():
    layout = {"separate_things": True, "things": [
        {"name": "Path", "request": "a path", "relation": "connects", "anchor": "Villa", "to": "Pool", "x": 0, "y": 0},
        {"name": "Pool", "request": "a pool", "relation": "beside", "anchor": "Villa", "x": 0, "y": 0},
        {"name": "Villa", "request": "a villa", "x": 0, "y": 0}]}
    app = SceneApp(failing={"Pool"})
    task = agent_core.AgentTask("a villa with a pool beside it and a path to the pool", app,
                                ask_json=lambda *a, **k: layout, log=lambda m: None)
    result = task.run()
    assert app.built == ["Villa"] and app.placed == ["Villa", "Pool"]
    assert task.state == "error" and "a pool didn't work" in result and "a path didn't work" in result


def test_a_scene_reports_the_placements_it_corrected():
    layout = {"separate_things": True, "things": [
        {"name": "Villa", "request": "a villa", "x": 0, "y": 0},
        {"name": "Pool", "request": "a pool", "relation": "beside", "anchor": "Villa", "x": 0, "y": 0}]}
    app = SceneApp()
    task = agent_core.AgentTask("a villa with a pool beside it", app, ask_json=lambda *a, **k: layout,
                                log=lambda m: None)
    result = task.run()
    assert task.state == "completed" and app.built == ["Villa", "Pool"] and "corrected 1 placement" in result


# ---------- colours (pure Python: the kit's parsing) ----------

@pytest.mark.parametrize("value,family", [("#f00", "red"), ("ff0000", "red"), ("rgb(0, 0, 255)", "blue"),
                                          ("0.05, 0.5, 0.05", "green"), ((1, 0, 0, 1), "red"),
                                          ((255, 128, 0), "orange"), ("grren", "green"), ("bright red tiles", "red")])
def test_colour_values_in_every_form(value, family):
    assert blender_kit.color_name(blender_kit.rgb_of(value)) == family


@pytest.mark.parametrize("value", [4, 4.5, "color 4", "4", (1, 2), "blurple", True, (float("nan"), 0, 0)])
def test_things_that_arent_colours_are_rejected_clearly(value):
    with pytest.raises(ValueError):
        blender_kit.rgb_of(value)


def test_a_part_name_suggests_its_material_when_the_colour_is_junk():
    assert blender_kit._guess_material("Pool Water") == "water"
    assert blender_kit._guess_material("House Roof") == "roof tiles"
    assert blender_kit._guess_material("Bench Leg 2") == "wood"
    assert blender_kit._guess_material("Thing") is None


@pytest.mark.parametrize("check,code,guess", [
    ({"type": "exists", "object": "Bench Seat Legs 1"}, "box('Bench Seat', 1)\nlegs_under('Bench Seat')", True),
    ({"type": "exists", "object": "Bench Seat"}, "box('Bench Seat', 1)", False),
    ({"type": "exists", "object": "Tree Leaves 3"}, "for i in range(5):\n    blob(f'Tree Leaves {i}', 1)", False),
    ({"type": "color", "object": "Roof", "color": "red"}, "box('Wall', 1)", False),
])
def test_an_ais_guess_about_names_never_fails_a_working_step(check, code, guess):
    assert agent_blender.BlenderAdapter(None).check_is_guess(check, code) is guess


def test_a_scene_things_oddly_named_parts_are_one_thing_never_torn_apart():
    # what a small model once built for 'Tree 2': parts named every which way, overlapping each other
    parts = [o("Tree 2 Trunk 2", (0, 10, 0), (0.4, 10.4, 4)), o("Tree 2 2", (-1, 9, 3), (1.5, 11.5, 6)),
             o("Pine Needles", (-1.2, 8.8, 2.5), (1.6, 11.6, 6.5))]
    goal = "a pine tree — name its parts 'Tree 2 ...', build it at x=0, y=10 (X, Y), standing behind 'Cabin' and finish"
    adapter, bridge = adapter_for(villa(name="Cabin") + parts, goal)
    fixed = adapter.auto_fix(names(villa(name="Cabin")), state_of(bridge), goal)
    assert not any("inside each other" in f for f in fixed)
    moves = [c for c in bridge.calls if "shift_thing(" in c]
    assert all(all(p in c for p in ("'Tree 2 Trunk 2'", "'Tree 2 2'", "'Pine Needles'")) for c in moves)


def test_two_counted_things_in_a_layout_build_one_each():
    things = agent_core._one_each([{"name": "Tree 1", "request": "two pine trees behind it"},
                                   {"name": "Tree 2", "request": "two pine trees behind it"},
                                   {"name": "Rocks", "request": "three mossy rocks"}])
    assert [t["request"] for t in things] == ["a pine tree behind it", "a pine tree behind it", "three mossy rocks"]


def test_a_scene_things_request_reaches_the_asset_chooser_without_its_placement():
    asked = []

    def ask(messages, schema, **kw):
        asked.append(messages[-1]["content"])
        return {"asset": "tree", "options": {"kind": "pine"}, "count": 2, "understanding": "x", "other_things": ""}
    goal = "a pine tree behind it — name its parts 'Tree 2 ...', build it at x=0, y=9 (X, Y) and finish"
    adapter, bridge = adapter_for(villa(name="Cabin"), goal)
    plan = adapter.quick_plan(goal, state_of(bridge), ask)
    assert asked == ["Request: a pine tree"]
    assert plan["steps"][0]["code"].count("tree(") == 1          # one tree, whatever the count said


def test_variables_named_like_kit_functions_are_renamed_before_running():
    code = ("color = 'wood'\ntop = 2.5\nbox('Bench Seat', (1.5, 0.4, 0.05), at=(X, Y, top), color=color)\n"
            "color('Bench Seat', color)\nz = top('Bench Seat') + 0.1\nsize = 3")
    out = agent_blender.BlenderAdapter(None).sanitize(code, "build a bench")
    assert "color_value = 'wood'" in out and "color=color_value)" in out and "color('Bench Seat', color_value)" in out
    assert "at=(X, Y, top_value)" in out and "z = top('Bench Seat')" in out
    assert "size = 3" in out                                 # never called: left alone
    plain = "box('A', 1, color='red')\nmove('A', to=(1, 2, 0))"
    assert agent_blender.BlenderAdapter(None).sanitize(plain, "x") == plain


def test_a_path_meets_a_round_pond_near_the_middle_of_its_side():
    ts = spatial.things({"objects": villa() + [o("Pond Water", (-8, -16, -0.5), (-2, -12, 0))]})
    start, sdir, end, edir = spatial.path_ends(thing({"objects": villa()}, "Villa"), thing(
        {"objects": villa() + [o("Pond Water", (-8, -16, -0.5), (-2, -12, 0))]}, "Pond"))
    assert -6.5 <= end[0] <= -3.5                            # the central half of the pond's top side


@pytest.mark.parametrize("relation,turn", [("in front of", 0), ("behind", 180), ("right of", 90), ("left of", 270)])
def test_a_bench_by_a_house_sits_with_its_back_to_it(relation, turn):
    def ask(messages, schema, **kw):
        return {"asset": "bench", "options": {}, "count": 1, "understanding": "x", "other_things": ""}
    goal = f"put a park bench {relation} the villa"
    adapter, bridge = adapter_for(villa(), goal)
    code = adapter.quick_plan(goal, state_of(bridge), ask)["steps"][0]["code"]
    assert code.startswith("bench('Park Bench'") and (f"rotation={turn}" in code if turn else "rotation" not in code)


def test_a_lounger_beside_a_pool_points_its_foot_at_the_pool():
    def ask(messages, schema, **kw):
        return {"asset": "lounger", "options": {}, "count": 1, "understanding": "x", "other_things": ""}
    goal = "add a sun lounger next to the pool"
    adapter, bridge = adapter_for(villa() + pool_inside(x=14), goal)
    code = adapter.quick_plan(goal, state_of(bridge), ask)["steps"][0]["code"]
    x = float(re.search(r"at=\((-?[\d.]+),", code).group(1))
    assert x > 18 and "rotation=270" in code                  # right of the pool, its foot pointing back at it (-x)


def test_layout_relations_come_from_the_request_when_the_model_leaves_them_out():
    goal = "a small park with a fountain in the middle, two benches near the fountain and three trees around it"
    things = agent_core._resolve_names(agent_core._relations_from_goal(goal, [
        {"name": "Fountain", "request": "a small fountain"}, {"name": "Bench 1", "request": "a bench near the fountain"},
        {"name": "Tree 1", "request": "a tree around the fountain"}]))
    assert [(t["name"], t.get("relation"), t.get("anchor")) for t in things] == [
        ("Fountain", None, None), ("Bench 1", "near", "Fountain"), ("Tree 1", "near", "Fountain")]


def test_a_scene_thing_is_sized_as_itself_not_as_what_it_stands_by():
    adapter, bridge = adapter_for(villa(), "")
    placed = adapter.place_thing({"name": "Rock", "request": "a rock beside the villa", "relation": "beside",
                                  "anchor": "Villa", "x": 0, "y": 0}, state_of(bridge))
    core = thing(state_of(bridge), "Villa")["core"]
    assert placed["x"] - core[2] < 5                         # a rock's room, not a villa's


def test_a_bench_by_a_fountain_looks_at_it():
    def ask(messages, schema, **kw):
        return {"asset": "bench", "options": {}, "count": 1, "understanding": "x", "other_things": ""}
    fountain = [o("Fountain", (0, 0, 0), (0, 0, 0), type_="EMPTY", asset="Fountain", asset_type="fountain"),
                o("Fountain Basin", (-1.5, -1.5, 0), (1.5, 1.5, 0.5), "Fountain", asset="Fountain",
                  asset_type="fountain")]
    goal = "put a bench next to the fountain"
    adapter, bridge = adapter_for(fountain, goal)
    code = adapter.quick_plan(goal, state_of(bridge), ask)["steps"][0]["code"]
    x = float(re.search(r"at=\((-?[\d.]+),", code).group(1))
    assert x > 1.5 and "rotation=270" in code        # to its right, the seat's front turned to -x: toward it


def test_a_path_in_a_layout_always_connects_whatever_the_model_said():
    goal = "a modern villa with a swimming pool beside it and a path from the entrance to the pool"
    things = agent_core._resolve_names(agent_core._relations_from_goal(goal, [
        {"name": "Villa", "request": "a modern villa"}, {"name": "Pool", "request": "a swimming pool"},
        {"name": "Path", "request": "a path from the entrance to the pool", "relation": "beside", "anchor": "Villa"}]))
    assert (things[2]["relation"], things[2]["anchor"], things[2]["to"]) == ("connects", "Villa", "Pool")


def test_a_path_is_never_moved_by_a_relation_repair():
    walk = [o("Walk Stone 1", (20, 20, 0), (21, 21, 0.05))]
    issues = spatial.validate({"objects": villa() + walk}, before=names(villa()),
                              intents=[{"subject": "path", "relation": "beside", "anchor": "villa", "to": None}])
    assert all(i["fix"] is None for i in issues if i["thing"] == "Walk")
