"""Scene generation in a real Blender, headless and isolated (its own temp folder, its own bridge files — never the
user's Blender): the kit's robustness (bad colours, shaping a group, failed or empty operations, grouping), the
pool and walkway assets, and the whole agent loop — plan -> act -> verify -> repair — with a scripted AI that makes
the mistakes a small model makes (a pool inside the villa, a path through the house, an object that was never
created). Skipped where Blender isn't installed."""
import json
import os
import subprocess
import time

import pytest

import agent_blender
import agent_core
import blender_bridge
import blender_control
import spatial
from test_blender_assets_real import BLENDER, ROOT

pytestmark = pytest.mark.skipif(BLENDER is None, reason="Blender isn't installed here")


# ---------- the kit on its own ----------

KIT_SCRIPT = r'''
import json, sys, traceback
import bpy, bmesh, mathutils
sys.path.insert(0, ROOT)
import agent_blender
ns = {"__name__": "jervis_blender", "bpy": bpy, "bmesh": bmesh, "mathutils": mathutils}
exec(compile(agent_blender.kit_source(), "<kit>", "exec"), ns)
ns.update(X=0.0, Y=0.0, SALT=3, NAME_HINT="", r=ns["rng"](3))
out = {}
def run(label, code):
    ns["step_begin"]()
    try:
        exec(compile(code, "<test>", "exec"), ns)
        out[label] = {"ok": True, "made": list(ns["STEP"]["made"]), "warnings": list(ns["STEP"]["warnings"])}
    except Exception as e:
        out[label] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
def world(name):
    bpy.context.view_layer.update()
    return [round(v, 3) for v in bpy.data.objects[name].matrix_world.translation]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
run("colour_number", "box('Crate', 1, at=(30, 0, 0), color=4)")
run("colour_words", "box('Crate 2', 1, at=(32, 0, 0), color='color 4')")
run("colour_by_name", "box('Pool Water 2', 1, at=(34, 0, 0), color=(1, 2))")
out["crate_material"] = bpy.data.objects["Crate"].active_material.name
run("group", "box('Thing A', 1, at=(40, 0, 0))\nbox('Thing B', 1, at=(40, 0, 1))\nassemble('Thing')")
run("roughen_group", "roughen('Thing', 0.02)\ndensify('Thing', 1)\nbevel('Thing', 0.02)\ncolor('Thing', 'red')")
out["group_colours"] = sorted(o.active_material.name for o in bpy.data.objects["Thing"].children)
run("taper_group", "taper('Thing', 0.3)")
run("regroup", "box('Thing C', 0.5, at=(42, 0, 0))\nassemble('Thing')")
out["thing_a_after_regroup"] = world("Thing A")
out["thing_children"] = sorted(o.name for o in bpy.data.objects["Thing"].children)
run("rebuild_part", "box('Thing A', 1, at=(40, 0, 0), color='wood')")
out["thing_a_after_rebuild"] = world("Thing A")
run("move_part", "move('Thing A', to=(41, 0, 0))")
out["thing_a_after_move"] = world("Thing A")
run("shape_named_like_group", "box('Thing', 0.3, at=(45, 0, 0))")
out["thing_body_parent"] = bpy.data.objects["Thing Body"].parent.name
run("group_bounds", "RESULT = (bounds('Thing'), size('Thing'))")
out["group_size"] = [round(v, 2) for v in ns["RESULT"][1]]
run("duplicate_group", "duplicate('Thing', 'Other Thing', at=(50, 0, 0))")
out["copy_parts"] = sorted(o.name for o in bpy.data.objects["Other Thing"].children)
out["copy_body_offset"] = [round(a - b, 2) for a, b in zip(world("Other Thing Body"), world("Thing Body"))]
out["copy_root_offset"] = [round(a - b, 2) for a, b in zip(world("Other Thing"), world("Thing"))]
run("delete_group", "delete('Other Thing')")
out["copy_left"] = [o.name for o in bpy.data.objects if o.name.startswith("Other Thing") and o.users_collection]
run("cut_misses", "box('Wall', (3, 0.2, 2), at=(60, 0, 0))\nopening('Wall', 1, 1, at=(80, 0, 0))")
run("cut_everything", "box('Wall 2', (1, 0.2, 1), at=(62, 0, 0))\ncut('Wall 2', box('__jervis_cutter', 5, at=(62, 0, -1)))")
out["wall_2_vertices"] = len(bpy.data.objects["Wall 2"].data.vertices)
run("nan", "box('Leg', (0.1, 0.1, 1), at=(0, 0, float('nan')))")
out["nan_left_behind"] = "Leg" in bpy.data.objects
run("missing_then_dependent", "box('Seat', (1, 1, 0.1), at=(70, 0, 0.45))\nlegs_under('Seet')")
run("not_a_name", "move(None, to=(0, 0, 0))")
run("villa", "house('Villa', at=(0, 0, 0), style='modern')")
run("pool", "s = spot_near('Villa', 'beside', what='swimming pool')\npool('Pool', at=s, rotation=s.rotation)")
run("path", "walkway('Path', 'Villa', 'Pool')")
run("pond", "s = spot_near('Villa', 'behind', what='pond')\npond('Pond', at=s, size=4)")
run("furniture", "bench('Bench', at=(-30, 0, 0))\nbench('Garden Bench', at=(-30, 4, 0), style='garden')\n"
    "lounger('Sun Lounger', at=(-30, 8, 0), rotation=90)")
run("fountain", "fountain('Fountain', at=(-40, 0, 0), size=3)")
out["fountain_size"] = [round(v, 2) for v in ns["size"]("Fountain")] if out["fountain"]["ok"] else None
out["bench_size"] = [round(v, 2) for v in ns["size"]("Bench")]
out["lounger_size"] = [round(v, 2) for v in ns["size"]("Sun Lounger")]
# undoing a step that regrouped a thing brings back exactly what was there (the same group object, parts in place)
run("bench", "box('Bench Seat', (1.5, 0.45, 0.05), at=(-20, 0, 0.45))\nlegs_under('Bench Seat')\nassemble('Bench')")
exec(compile(agent_blender._SNAPSHOT_CODE, "<snap>", "exec"), ns)
snap = json.loads(ns["RESULT"])
before_uid = bpy.data.objects["Bench"].session_uid
before_seat = world("Bench Seat")
before_body = world("Thing Body")    # a part whose parent inverse isn't identity, elsewhere in the scene
run("regroup_then_fail", "box('Bench Back', (1.5, 0.05, 0.4), at=(-20, 0.2, 0.6))\nassemble('Bench')\n"
    "move('Bench', by=(3, 0, 0))")
exec(compile(agent_blender._restore_code(snap), "<restore>", "exec"), ns)
out["bench_seat_restored"] = world("Bench Seat") == before_seat
out["bench_same_group"] = bpy.data.objects["Bench"].session_uid == before_uid and \
    bpy.data.objects["Bench Seat"].parent == bpy.data.objects["Bench"]
out["bench_back_gone"] = "Bench Back" not in [o.name for o in bpy.data.objects if o.users_collection]
out["other_parts_untouched"] = world("Thing Body") == before_body
# a pool dug into a lawn: the lawn opens over it, the hole follows the pool, goes when it's deleted, comes back on undo
def ray(x, y):
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    r = bpy.context.scene.ray_cast(dg, mathutils.Vector((x, y, 50)), mathutils.Vector((0, 0, -1)))
    return r[4].name if r[0] else None
run("lawn_pool", "plane('Lawn', 30, at=(120, 0, 0), color='grass')\npool('Lawn Pool', at=(120, 0, 0))")
out["lawn_hole"] = [ray(120, 0), ray(132, 0)]
run("lawn_pool_move", "move('Lawn Pool', by=(0, 6, 0))")
out["lawn_hole_moved"] = [ray(120, 0), ray(120, 6)]
exec(compile(agent_blender._SNAPSHOT_CODE, "<snap>", "exec"), ns)
pool_snap = json.loads(ns["RESULT"])
run("lawn_pool_delete", "delete('Lawn Pool')")
out["lawn_after_delete"] = ray(120, 6)
exec(compile(agent_blender._restore_code(pool_snap), "<restore>", "exec"), ns)
out["lawn_after_undo"] = ray(120, 6)
run("inside", "RESULT = tuple(spot_near('Villa', 'inside', what='sofa'))")
out["inside_spot"] = list(ns["RESULT"])
run("front", "RESULT = tuple(spot_near('Villa', 'in front of', size=(2, 2)))")
out["front_spot"] = list(ns["RESULT"])
state = json.loads(ns["scene_state"]())
out["validate"] = ns["spatial"].validate(state, intents=ns["spatial"].parse_relations(
    "a modern villa with a swimming pool beside it and a path from the entrance to the pool"))
ts = {t["name"]: t for t in ns["spatial"].things(state)}
out["villa_core"] = ts["Villa"]["core"]
out["pool_rect"] = ts["Pool"]["rect"]
out["pool_parts"] = sorted(n for n in ts["Pool"]["names"])
out["path_parts"] = sorted(n for n in ts["Path"]["names"])
out["pond_rect"] = ts["Pond"]["rect"]
out["pond_category"] = ts["Pond"]["category"]
print("RESULT_JSON " + json.dumps(out, default=str))
'''


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    folder = tmp_path_factory.mktemp("blender_kit")
    script = folder / "kit_test.py"
    script.write_text(f"ROOT = {ROOT!r}\n" + KIT_SCRIPT, encoding="utf-8")
    env = dict(os.environ, USERPROFILE=str(folder), HOME=str(folder), TEMP=str(folder), TMP=str(folder))
    done = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300, env=env)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    assert line, done.stdout[-2000:] + done.stderr[-2000:]
    return json.loads(line[len("RESULT_JSON "):])


def test_invalid_colours_never_crash_a_build(kit):
    assert kit["colour_number"]["ok"] and "Unknown color 4" in kit["colour_number"]["warnings"][0]
    assert kit["colour_words"]["ok"] and kit["colour_words"]["warnings"]
    assert kit["colour_by_name"]["ok"] and "used water" in kit["colour_by_name"]["warnings"][0]
    assert kit["crate_material"] == "Jervis light grey"


def test_shaping_a_group_works_on_its_parts_instead_of_crashing(kit):
    # roughen('Thing') on an assembly's empty once raised "'NoneType' object has no attribute 'vertices'"
    assert kit["roughen_group"]["ok"], kit["roughen_group"]
    assert kit["group_colours"] == ["Jervis red", "Jervis red"]
    assert not kit["taper_group"]["ok"] and "group of 2 parts" in kit["taper_group"]["error"]


def test_regrouping_and_rebuilding_never_move_a_part(kit):
    assert kit["thing_a_after_regroup"] == [40.0, 0.0, 0.0]
    assert kit["thing_children"] == ["Thing A", "Thing B", "Thing C"]
    assert kit["thing_a_after_rebuild"] == [40.0, 0.0, 0.0]     # a world position, not relative to the group
    assert kit["thing_a_after_move"] == [41.0, 0.0, 0.0]


def test_groups_act_as_wholes(kit):
    assert kit["thing_body_parent"] == "Thing"
    assert kit["group_size"][0] > 4                          # the whole group, not an empty's zero size
    assert kit["copy_parts"] == ["Other Thing A", "Other Thing B", "Other Thing Body", "Other Thing C"]
    assert kit["copy_left"] == []                            # deleting the group took every part
    assert kit["copy_body_offset"] == kit["copy_root_offset"]   # a copy's parts keep their places in it


def test_failed_operations_are_failures_not_silent_successes(kit):
    assert not kit["cut_misses"]["ok"] and "misses" in kit["cut_misses"]["error"]
    assert not kit["cut_everything"]["ok"] and kit["wall_2_vertices"] == 8   # left as it was
    assert not kit["nan"]["ok"] and not kit["nan_left_behind"]
    assert not kit["missing_then_dependent"]["ok"] and "no object named 'Seet'" in kit["missing_then_dependent"]["error"]
    assert not kit["not_a_name"]["ok"]


def test_a_villa_pool_and_path_built_with_the_kit_stand_right(kit):
    assert kit["villa"]["ok"] and kit["pool"]["ok"] and kit["path"]["ok"], (kit["villa"], kit["pool"], kit["path"])
    assert spatial.overlap_depth(kit["pool_rect"], kit["villa_core"]) <= 0
    assert {"Pool Water", "Pool Basin", "Pool Coping", "Pool Deck", "Pool Ladder"} <= set(kit["pool_parts"])
    assert {"Path Bed", "Path Pavers", "Path Edging"} <= set(kit["path_parts"])
    assert kit["validate"] == []
    assert kit["inside_spot"][2] > 0.3                       # on the villa's floor, not the ground under it
    assert kit["front_spot"][1] < kit["villa_core"][1]


def test_a_pond_is_a_finished_sunken_asset_behind_the_villa(kit):
    assert kit["pond"]["ok"], kit["pond"]
    assert {"Pond Bed", "Pond Water", "Pond Stones", "Pond Reeds"} <= set(kit["pond"]["made"])
    assert kit["pond_rect"][1] > kit["villa_core"][3]        # behind it (the villa faces -y)
    assert kit["pond_category"] == "sunken"


def test_bench_and_lounger_assets_have_real_world_sizes(kit):
    assert kit["furniture"]["ok"], kit["furniture"]
    assert {"Bench Seat", "Bench Frame", "Garden Bench Seat", "Sun Lounger Bed", "Sun Lounger Cushion",
            "Sun Lounger Wheels"} <= set(kit["furniture"]["made"])
    length, depth, height = kit["bench_size"]
    assert 1.5 <= length <= 1.8 and 0.4 <= depth <= 0.7 and 0.8 <= height <= 1.0
    x, y, z = kit["lounger_size"]                             # turned 90 degrees: its length runs along x
    assert 1.8 <= x <= 2.2 and 0.6 <= y <= 0.85 and 0.5 <= z <= 1.0


def test_a_pool_opens_the_lawn_it_is_dug_into_and_the_hole_goes_with_it(kit):
    assert kit["lawn_pool"]["ok"], kit["lawn_pool"]
    assert kit["lawn_hole"] == ["Lawn Pool Water", "Lawn"]          # water seen through the lawn; lawn elsewhere
    assert kit["lawn_hole_moved"] == ["Lawn", "Lawn Pool Water"]    # the hole moved with the pool
    assert kit["lawn_after_delete"] == "Lawn"                       # deleted: the lawn is whole again
    assert kit["lawn_after_undo"] == "Lawn Pool Water"              # undone: the pool and its hole are back


def test_a_fountain_is_a_finished_asset(kit):
    assert kit["fountain"]["ok"], kit["fountain"]
    assert {"Fountain Basin", "Fountain Bowl 1", "Fountain Pedestal", "Fountain Water", "Fountain Jet"} <=         set(kit["fountain"]["made"])
    w, d, h = kit["fountain_size"]
    assert 2.9 <= w <= 3.3 and 2.9 <= d <= 3.3 and 1.2 <= h <= 2.5


def test_undoing_a_regroup_restores_the_same_group_with_its_parts_in_place(kit):
    assert kit["regroup_then_fail"]["ok"]
    assert kit["bench_seat_restored"] and kit["bench_same_group"] and kit["bench_back_gone"]
    assert kit["other_parts_untouched"]           # undo never moves what it didn't change


# ---------- the whole agent loop, through a live bridge ----------

LOOP_SCRIPT = r'''
import os, sys, time
import bpy, bmesh, mathutils
sys.path.insert(0, ROOT)
import blender_bridge
blender_bridge._namespace.update(bpy=bpy, bmesh=bmesh, mathutils=mathutils)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
stop = os.path.join(blender_bridge.BRIDGE_DIR, "stop")
os.makedirs(blender_bridge.BRIDGE_DIR, exist_ok=True)
deadline = time.time() + 600
while time.time() < deadline and not os.path.exists(stop):
    blender_bridge.poll()
    time.sleep(0.02)
'''


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """A headless Blender running the real bridge on a private folder, and a BlenderBridge talking to it."""
    folder = tmp_path_factory.mktemp("blender_live")
    script = folder / "loop.py"
    script.write_text(f"ROOT = {ROOT!r}\n" + LOOP_SCRIPT, encoding="utf-8")
    bridge_dir = os.path.join(str(folder), "jervis_blender_bridge")
    saved = (blender_bridge.BRIDGE_DIR, blender_bridge.REQUEST_FILE, blender_bridge.RESPONSE_FILE)
    blender_bridge.BRIDGE_DIR = bridge_dir     # this process talks to that Blender only, never the user's
    blender_bridge.REQUEST_FILE = os.path.join(bridge_dir, "request.json")
    blender_bridge.RESPONSE_FILE = os.path.join(bridge_dir, "response.json")
    env = dict(os.environ, USERPROFILE=str(folder), HOME=str(folder), TEMP=str(folder), TMP=str(folder))
    proc = subprocess.Popen([BLENDER, "-b", "--factory-startup", "--python", str(script)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bridge = blender_control.BlenderBridge()
    try:
        deadline = time.time() + 90
        while time.time() < deadline and not bridge.ping(timeout=2):
            time.sleep(0.5)
        assert bridge.ping(timeout=5), "the test Blender never answered"
        yield bridge
    finally:
        os.makedirs(bridge_dir, exist_ok=True)
        open(os.path.join(bridge_dir, "stop"), "w").close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        blender_bridge.BRIDGE_DIR, blender_bridge.REQUEST_FILE, blender_bridge.RESPONSE_FILE = saved


def clear(bridge):
    assert bridge.run("for o in list(bpy.data.objects):\n    bpy.data.objects.remove(o, do_unlink=True)\n"
                      "RESULT = 'clear'", timeout=20).get("ok")


def scripted_ai(plan=None, layout=None, assets=(), repairs=()):
    """A stand-in for the local model: answers each kind of question from a script, recording what it was asked."""
    assets, repairs = list(assets), list(repairs)
    asked = []

    def ask(messages, schema, **kw):
        props = schema.get("properties", {})
        asked.append((sorted(props), messages[-1]["content"]))
        if "asset" in props:
            return assets.pop(0) if assets else {"asset": "none", "options": {}, "count": 1, "understanding": "",
                                                  "other_things": "more"}
        if "separate_things" in props:
            return layout or {"separate_things": False, "things": []}
        if "steps" in props:
            return plan
        if "diagnosis" in props:
            return repairs.pop(0) if repairs else {"diagnosis": "nothing to add", "code": "",
                                                   "checks_were_wrong": False}
        return {}
    ask.asked = asked
    return ask


def run_task(bridge, goal, ask):
    adapter = agent_blender.BlenderAdapter(bridge)
    log = []
    task = agent_core.AgentTask(goal, adapter, ask_json=ask, log=log.append)
    result = task.run()
    state = adapter.observe()
    return task, result, state, log


def things(state):
    return {t["name"]: t for t in spatial.things(state)}


GOAL = "a modern villa with a swimming pool beside it and a path from the entrance to the pool"


def test_a_pool_built_inside_the_villa_and_a_path_through_it_are_repaired(live):
    clear(live)
    # The plan a small model once made: the pool at the villa's own spot, a path straight through the house.
    plan = {"understanding": "Build a modern villa with a pool and a path", "question": "", "steps": [
        {"title": "Build the villa", "code": "house('Villa', style='modern', at=(X, Y, 0))", "checks": []},
        {"title": "Add the pool", "code": "pool('Pool', at=(X, Y, 0))", "checks": []},
        {"title": "Lay the path", "code": "for i in range(8):\n    box(f'Path Slab {i + 1}', (1.2, 0.6, 0.05), "
                                          "at=(X, Y - 6 + i * 1.5, 0), color='stone')", "checks": []}],
        "final_checks": [{"type": "exists", "object": "Villa Walls"}, {"type": "exists", "object": "Pool Water"}]}
    task, result, state, log = run_task(live, GOAL, scripted_ai(plan=plan))
    ts = things(state)
    assert task.state == "completed", (result, log)
    assert spatial.check_relation(ts["Pool"], "beside", ts["Villa"])[0]
    ok, problems = spatial.check_path(ts["Path"], ts["Villa"], ts["Pool"], list(ts.values()))
    assert ok, (problems, log)
    assert spatial.validate(state, before=set(), intents=spatial.parse_relations(GOAL)) == []
    assert any("auto-fix" in line and "'Pool'" in line for line in log)


def test_a_scene_is_laid_out_by_relations_and_built_in_order(live):
    clear(live)
    layout = {"separate_things": True, "things": [
        {"name": "Path", "request": "a stone path", "relation": "connects", "anchor": "the entrance", "to": "Pool",
         "x": 0, "y": 0},
        {"name": "Pool", "request": "a swimming pool", "relation": "beside", "anchor": "Villa", "x": 0, "y": 0,
         "width": 11, "depth": 7},
        {"name": "Villa", "request": "a modern villa", "x": 0, "y": 0, "width": 12, "depth": 9}]}
    assets = [{"asset": "house", "options": {"style": "modern"}, "count": 1, "understanding": "x", "other_things": ""},
              {"asset": "pool", "options": {}, "count": 1, "understanding": "x", "other_things": ""}]
    task, result, state, log = run_task(live, GOAL, scripted_ai(layout=layout, assets=assets))
    ts = things(state)
    assert task.state == "completed", (result, log)
    assert {"Villa", "Pool", "Path"} <= set(ts)
    assert ts["Villa"]["asset_type"] == "house" and ts["Pool"]["asset_type"] == "pool"
    assert spatial.check_relation(ts["Pool"], "beside", ts["Villa"])[0]
    assert spatial.check_path(ts["Path"], ts["Villa"], ts["Pool"], list(ts.values()))[0]
    assert spatial.validate(state, before=set(), intents=spatial.parse_relations(GOAL)) == []
    # each thing is one group: "move it" / "delete it" take the whole of it
    by_name = {o["name"]: o for o in state["objects"]}
    for name in ("Villa", "Pool", "Path"):
        assert by_name[name]["type"] == "EMPTY" and not by_name[name]["parent"]
        assert all(by_name[n]["parent"] for n in ts[name]["names"] if n != name)


def test_a_dependent_step_after_a_failed_creation_is_rolled_back_and_repaired(live):
    clear(live)
    plan = {"understanding": "Build a stool", "question": "", "steps": [
        {"title": "Build the stool", "checks": [],
         "code": "box('Stool Seat', (0.4, 0.4, 0.05), at=(X, Y, 0.45), color='color 4', bevel=0.01)\n"
                 "legs_under('Chair Seat', count=3)"}],     # a part that was never made
        "final_checks": [{"type": "exists", "object": "Stool Seat"}]}
    repair = {"diagnosis": "the legs named a seat that doesn't exist", "checks_were_wrong": False,
              "code": "box('Stool Seat', (0.4, 0.4, 0.05), at=(X, Y, 0.45), color='color 4', bevel=0.01)\n"
                      "legs_under('Stool Seat', count=3, thickness=0.04)\nassemble('Stool')"}
    task, result, state, log = run_task(live, "build a simple stool", scripted_ai(plan=plan, repairs=[repair]))
    assert task.state == "completed", (result, log)
    assert any("attempt 1 failed" in line and "Chair Seat" in line for line in log)
    names_ = {o["name"] for o in state["objects"]}
    assert {"Stool Seat", "Stool Leg 1", "Stool Leg 2", "Stool Leg 3", "Stool"} <= names_
    assert "Stool Seat.001" not in names_                       # the failed attempt was undone, not left behind


def test_a_step_that_builds_nothing_is_not_counted_as_done(live):
    clear(live)
    plan = {"understanding": "Build a crate", "question": "", "steps": [
        {"title": "Build the crate", "checks": [],
         "code": "def make():\n    box('Crate', 1, at=(X, Y, 0), color='wood')"}],   # defined, never called
        "final_checks": []}
    repair = {"diagnosis": "the function was never called", "checks_were_wrong": False,
              "code": "box('Crate', 1, at=(X, Y, 0), color='wood', bevel=0.02)"}
    task, result, state, log = run_task(live, "build a crate", scripted_ai(plan=plan, repairs=[repair]))
    assert any("built nothing" in line for line in log)
    assert task.state == "completed" and "Crate" in {o["name"] for o in state["objects"]}
