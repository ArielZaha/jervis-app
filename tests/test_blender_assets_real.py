"""The finished assets (blender_assets.py) built in a real Blender, headless (no window, nothing on screen): each one
builds without an error and has the parts it promises, things put on an island stand on its surface, and rebuilding
an asset with new options can be undone back to the very same objects. Skipped where Blender isn't installed."""
import glob
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _blender():
    found = sorted(glob.glob(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Blender Foundation",
                                          "Blender *", "blender.exe")))
    return found[-1] if found else None


BLENDER = _blender()
pytestmark = pytest.mark.skipif(BLENDER is None, reason="Blender isn't installed here")

SCRIPT = r'''
import json, os, sys, traceback
import bpy, bmesh, mathutils
sys.path.insert(0, ROOT)
import agent_blender
ns = {"__name__": "jervis_blender", "bpy": bpy, "bmesh": bmesh, "mathutils": mathutils}
exec(compile(agent_blender.kit_source(), "<kit>", "exec"), ns)
ns.update(X=0.0, Y=0.0, SALT=3, NAME_HINT="", r=ns["rng"](3))
out = {}
def run(code):
    exec(compile(code, "<test>", "exec"), ns)
def state():
    return {o["name"]: o for o in json.loads(ns["scene_state"]())["objects"]}
try:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    run("house('House', at=(0, 0, 0), style='brick', floors=2)")
    run("tree('Oak', at=(20, 0, 0), kind='oak'); tree('Pine', at=(26, 0, 0), kind='pine')")
    run("tree('Palm', at=(32, 0, 0), kind='palm'); tree('Birch', at=(38, 0, 0), kind='birch')")
    run("rock('Rocks', at=(44, 0, 0), count=4, moss=True); bush('Bush', at=(50, 0, 0), flowers='pink')")
    run("fence('Fence', at=(58, 0, 0), length=6); water('Pond', at=(0, 40, 0), size=10)")
    run("island('Island', at=(0, -80, 0), radius=12, trees=4)")
    s = state()
    out["names"] = sorted(s)
    out["house_parts"] = sorted(n for n, o in s.items() if o.get("asset") == "House")
    out["island_trees"] = sorted(n for n, o in s.items() if o["type"] == "EMPTY" and n.startswith("Island Palm"))
    run("spot = scatter_on('Island Terrain', 1, min_height=0.6, seed=2)[0]\nhouse('Hut', at=spot, style='cabin', width=5, depth=4.5)")
    s = state()
    hut = [o for o in s.values() if o.get("asset") == "Hut" and o["type"] == "MESH"]
    out["hut_bottom"] = min(o["min"][2] for o in hut)
    out["ground_under_hut"] = ns["ground_height"](s["Hut"]["location"][0], s["Hut"]["location"][1])
    # rebuild with bigger windows, then undo with the agent's own snapshot/restore code
    snap = json.loads(exec(compile(agent_blender._SNAPSHOT_CODE, "<snap>", "exec"), ns) or ns["RESULT"])
    walls_uid = bpy.data.objects["House Walls"].session_uid
    run("rebuild_asset('House', window_scale=1.5)")
    out["rebuilt_scale"] = ns["asset_info"]("House")["params"]["window_scale"]
    out["new_walls_is_new_object"] = bpy.data.objects["House Walls"].session_uid != walls_uid
    run(agent_blender._restore_code(snap))
    out["undone_scale"] = ns["asset_info"]("House")["params"]["window_scale"]
    out["walls_back"] = bpy.data.objects["House Walls"].session_uid == walls_uid
    out["leftovers"] = sorted(o.name for o in bpy.data.objects if o.users_collection and o.name.startswith("__"))
except Exception:
    out["error"] = traceback.format_exc()
print("RESULT_JSON " + json.dumps(out))
'''


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    folder = tmp_path_factory.mktemp("blender")
    script = folder / "assets_test.py"
    script.write_text(f"ROOT = {ROOT!r}\n" + SCRIPT, encoding="utf-8")
    env = dict(os.environ, USERPROFILE=str(folder), HOME=str(folder), TEMP=str(folder), TMP=str(folder))
    done = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=240, env=env)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    assert line, done.stdout[-2000:] + done.stderr[-2000:]
    data = json.loads(line[len("RESULT_JSON "):])
    assert "error" not in data, data.get("error")
    return data


def test_every_asset_builds_with_its_parts(result):
    names = set(result["names"])
    for part in ("House Walls", "House Roof", "House Windows", "House Window Glass", "House Door", "House Chimney",
                 "Oak Trunk", "Oak Leaves", "Pine Needles", "Palm Fronds", "Palm Coconuts", "Birch Leaves",
                 "Rocks Stone", "Bush Leaves", "Bush Flowers", "Fence Boards", "Pond Surface", "Island Terrain",
                 "Island Sea", "Island Rocks"):
        assert part in names, part


def test_a_house_is_a_model_not_a_blockout(result):
    assert len(result["house_parts"]) >= 15


def test_an_island_grows_the_trees_asked_for(result):
    assert len(result["island_trees"]) == 4


def test_a_hut_put_on_the_island_stands_on_its_surface(result):
    # its foundation reaches the ground under it (never floating above it)
    assert result["hut_bottom"] <= result["ground_under_hut"] + 0.05


def test_rebuilding_an_asset_can_be_undone_to_the_same_objects(result):
    assert result["rebuilt_scale"] == 1.5 and result["new_walls_is_new_object"]
    assert result["undone_scale"] == 1.0 and result["walls_back"]
    assert not result["leftovers"]
