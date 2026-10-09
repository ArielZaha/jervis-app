"""Finished assets in the agent (agent_blender.quick_plan): a request for a house, a tree or an island becomes one
call of the asset with only the options the user's words support; "add more trees to the island" changes the island
that's there instead of building a second one; "a cabin on the island" stands on the island; "... and save it" is
never dropped. No Blender: a fake bridge and a fake AI."""
import json

import pytest

import agent_blender
import agent_core


class Bridge:
    def __init__(self, params=None):
        self.calls = []
        self.params = params or {}

    def run(self, code, timeout=15):
        self.calls.append(code)
        if "asset_info(" in code:
            root = code.split("asset_info(")[1].split(")")[0].strip("'\"")
            return {"ok": True, "output": json.dumps({"type": "x", "params": self.params.get(root, {}), "root": root})}
        return {"ok": True, "output": ""}


def ai(answer):
    seen = []

    def ask(messages, schema, **kw):
        seen.append(messages[-1]["content"])
        return answer
    ask.seen = seen
    return ask


def part(name, asset=None, asset_type=None, kind="asset", mn=(0, 0, 0), mx=(1, 1, 1), type_="MESH"):
    return {"name": name, "type": type_, "asset": asset, "asset_type": asset_type, "kind": kind, "min": list(mn),
            "max": list(mx), "location": list(mn), "size": [1, 1, 1]}


EMPTY = {"objects": []}
ISLAND = {"objects": [part("Island", "Island", "island", type_="EMPTY"),
                      part("Island Terrain", "Island", "island", kind="terrain", mn=(-30, -30, -6), mx=(30, 30, 4))]}
HOUSE = {"objects": [part("House", "House", "house", type_="EMPTY"),
                     part("House Walls", "House", "house", mn=(-4, -3, 0), mx=(4, 3, 3.4))]}


def plan(goal, answer, state=EMPTY, bridge=None):
    adapter = agent_blender.BlenderAdapter(bridge or Bridge())
    return adapter.quick_plan(goal, state, ai(answer))


def test_a_detailed_house_is_one_asset_call_not_invented_geometry():
    p = plan("create a detailed house", {"asset": "house", "options": {}, "count": 1,
                                         "understanding": "Build a detailed house", "other_things": ""})
    assert p["quick"] and len(p["steps"]) == 1
    assert p["steps"][0]["code"].startswith("house('House'")
    assert {"type": "exists", "object": "House Walls"} in p["final_checks"]


def test_only_options_the_user_said_are_kept():
    p = plan("create a detailed two story brick house", {
        "asset": "house", "count": 1, "understanding": "Build a brick house", "other_things": "",
        "options": {"floors": 2, "walls": "brick", "roof_color": "grey", "door_color": "brown", "path": False,
                    "window_scale": 1.2, "chimney": True, "rotation": 0}})
    code = p["steps"][0]["code"]
    assert "floors=2" in code and "style='brick'" in code
    for invented in ("grey", "brown", "path=", "window_scale", "chimney", "rotation"):
        assert invented not in code, invented


def test_a_palm_tree_never_gets_autumn_leaves_nobody_asked_for():
    p = plan("add a palm tree", {"asset": "tree", "count": 1, "understanding": "Add a palm tree", "other_things": "",
                                 "options": {"kind": "palm", "leaves": "autumn leaves", "height": 10}})
    code = p["steps"][0]["code"]
    assert "kind='palm'" in code and "autumn" not in code and "height" not in code


def test_a_cabin_is_the_cabin_style_and_small_means_small():
    p = plan("build a small cabin", {"asset": "house", "count": 1, "understanding": "Build a cabin",
                                     "other_things": "", "options": {}})
    code = p["steps"][0]["code"]
    assert "style='cabin'" in code and "width=5.6" in code


def test_several_trees_get_their_own_names_spots_and_seeds():
    p = plan("plant three oak trees", {"asset": "tree", "count": 3, "understanding": "Plant three oaks",
                                       "other_things": "", "options": {"kind": "oak"}})
    lines = p["steps"][0]["code"].splitlines()
    assert len(lines) == 3 and len({l.split("at=")[1].split(")")[0] for l in lines}) == 3
    assert len({l.split("seed=")[1] for l in lines}) == 3


def test_something_that_is_not_an_asset_goes_to_the_planner():
    assert plan("build a castle", {"asset": "none", "options": {}, "count": 1, "understanding": "",
                                   "other_things": ""}) is None


def test_the_ai_cannot_turn_a_castle_into_a_house():
    # the request must itself name the asset the AI chose
    assert plan("build a castle", {"asset": "house", "options": {}, "count": 1, "understanding": "",
                                   "other_things": ""}) is None


def test_something_extra_alongside_the_asset_goes_to_the_planner():
    assert plan("build a house with a swimming pool", {
        "asset": "house", "options": {}, "count": 1, "understanding": "", "other_things": "a swimming pool"}) is None


def test_more_trees_on_the_island_change_that_island_not_build_a_second():
    bridge = Bridge(params={"Island": {"radius": 15, "trees": 6, "tree_kind": "palm"}})
    adapter = agent_blender.BlenderAdapter(bridge)
    answers = iter([{"asset": "tree", "options": {}, "count": 3, "understanding": "Add trees", "other_things": ""},
                    {"fits": True, "changes": {"trees": 10}, "understanding": "Add more trees to the island"}])
    p = adapter.quick_plan("add more trees to the island", ISLAND, lambda m, s, **kw: next(answers))
    assert p["steps"][0]["code"] == "rebuild_asset('Island', trees=10)"


def test_a_cabin_on_the_island_stands_on_free_level_ground_there():
    p = plan("add a small cabin on the island", {"asset": "house", "options": {}, "count": 1,
                                                 "understanding": "Build a cabin", "other_things": ""}, ISLAND)
    code = p["steps"][0]["code"]
    assert "scatter_on('Island Terrain'" in code and "at=spots[0]" in code
    assert "not enough free, level ground" in code


def test_the_ai_only_hears_what_to_build_not_where():
    ask = ai({"asset": "house", "options": {}, "count": 1, "understanding": "Build a cabin", "other_things": ""})
    agent_blender.BlenderAdapter(Bridge()).quick_plan("add a small cabin on the island", ISLAND, ask)
    assert "island" not in ask.seen[0].lower()


def test_next_to_the_house_is_beside_its_footprint():
    p = plan("put a fence next to the house", {"asset": "fence", "options": {}, "count": 1,
                                               "understanding": "Build a fence", "other_things": ""}, HOUSE)
    x = float(p["steps"][0]["code"].split("at=(")[1].split(",")[0])
    assert x > 4 + 1   # clear of the house's walls (they end at x = 4)


def test_save_it_at_the_end_is_never_dropped():
    adapter = agent_blender.BlenderAdapter(Bridge())
    p = {"steps": [{"title": "Build", "code": "house('House')"}]}
    extra = adapter.closing_steps("create a detailed tropical island with palm trees and save it", p)
    assert extra and "save_file(None)" in extra[0]["code"] and extra[0]["quick"]
    named = adapter.closing_steps("build a cabin, then save it as my cabin", p)
    assert "save_file('my cabin')" in named[0]["code"]
    assert adapter.closing_steps("build a cabin", p) == []


def test_a_bigger_windows_change_rebuilds_the_house():
    bridge = Bridge(params={"House": {"style": "cottage", "window_scale": 1.0}})
    adapter = agent_blender.BlenderAdapter(bridge)
    answer = {"fits": True, "changes": {"window_scale": 1.35, "roof_color": "green"},
              "understanding": "Make the windows bigger"}
    p = adapter.quick_plan("make the windows on the house bigger", HOUSE, lambda m, s, **kw: answer)
    assert p["steps"][0]["code"] == "rebuild_asset('House', window_scale=1.35)"   # (no green roof was asked for)


def test_a_change_no_option_covers_goes_to_the_planner():
    bridge = Bridge(params={"House": {"style": "cottage"}})
    adapter = agent_blender.BlenderAdapter(bridge)
    p = adapter.quick_plan("put a satellite dish on the house roof", HOUSE,
                           lambda m, s, **kw: {"fits": False, "changes": {}, "understanding": ""})
    assert p is None


def test_assets_are_not_judged_by_the_blockout_heuristics():
    adapter = agent_blender.BlenderAdapter(Bridge())
    state = {"objects": [part("Palm", "Palm", "tree", type_="EMPTY"),
                         part("Palm Trunk", "Palm", "tree", mn=(0, 0, -0.15), mx=(1, 1, 8)),
                         part("Palm Coconuts", "Palm", "tree", mn=(0, 0, 7), mx=(1, 1, 7.5))]}
    assert adapter.extra_failures({}, state, "add a palm tree") == []
    assert adapter.quality_issues({}, state, "add a palm tree", "high") == []


def test_a_failed_asset_step_is_not_handed_to_the_ai_to_rewrite():
    class Adapter(agent_core.AppAdapter):
        def execute(self, code):
            return {"ok": False, "output": "", "error": "ValueError: There is not enough free, level ground"}

    asked = []
    task = agent_core.AgentTask("x", Adapter(), ask_json=lambda *a, **k: asked.append(1) or {})
    outcome = task._run_step({"title": "Build a cabin", "code": "house('Cabin')", "checks": [], "quick": True})
    assert not outcome.ok and outcome.attempts == 1 and not asked
    assert agent_core.plain_error(outcome.detail) == "There is not enough free, level ground"


def test_blender_that_stops_answering_stops_the_task_with_a_plain_reason():
    class Dead:
        def run(self, code, timeout=15):
            return {"ok": False, "output": "", "error": "Blender didn't answer in time."}

        def ping(self, timeout=3):
            return False

    adapter = agent_blender.BlenderAdapter(Dead())
    with pytest.raises(agent_core.AppGone, match="stopped answering"):
        adapter.execute("house('House')")


def test_improve_the_water_after_trees_were_added_still_means_the_islands_sea():
    state = {"objects": ISLAND["objects"] + [
        dict(part("Island Palm 1", "Island Palm 1", "tree", type_="EMPTY"), parent="Island"),
        part("Island Palm 1 Trunk", "Island Palm 1", "tree")]}
    bridge = Bridge(params={"Island": {"waves": 0.35, "foam": False, "trees": 4}})
    p = agent_blender.BlenderAdapter(bridge).quick_plan("improve the water", state, ai({}))
    assert p["steps"][0]["code"] == "rebuild_asset('Island', waves=0.65, foam=True)"


def test_add_trees_to_the_island_adds_them_to_it():
    bridge = Bridge(params={"Island": {"trees": 6}})
    p = agent_blender.BlenderAdapter(bridge).quick_plan(
        "add three palm trees on the island", ISLAND,
        ai({"asset": "tree", "options": {"kind": "palm"}, "count": 3, "understanding": "", "other_things": ""}))
    assert p["steps"][0]["code"] == "rebuild_asset('Island', trees=9, tree_kind='palm')"


def test_the_reply_never_describes_options_that_were_not_built():
    p = plan("create a detailed brick house", {
        "asset": "house", "count": 1, "other_things": "", "options": {"style": "brick", "roof_color": "red"},
        "understanding": "Build a brick house with a red roof, rotated 45 degrees"})
    assert "red" not in p["understanding"] and "45" not in p["understanding"]
    assert "red" not in p["steps"][0]["code"]
