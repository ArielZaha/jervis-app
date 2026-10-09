"""The world round a subject, built for real in Blender (environment.py's plan run on the kit) and looked at from
its camera: a villa in its garden, a shop in its street, a cabin in its woods, a waterfall in its forest. Every step
runs; nothing planted stands in the subject or across its door; the camera sees the whole subject with sky above it;
the render isn't empty, black or blown out."""
import json
import os
import subprocess

import pytest

from test_blender_assets_real import BLENDER, ROOT

pytestmark = pytest.mark.skipif(not os.path.exists(BLENDER), reason="Blender isn't installed here")

SCRIPT = r'''
import json, sys, traceback
import bpy, bmesh, mathutils
sys.path.insert(0, ROOT)
import agent_blender, environment
ns = {"__name__": "jervis_blender", "bpy": bpy, "bmesh": bmesh, "mathutils": mathutils}
exec(compile(agent_blender.kit_source(), "<kit>", "exec"), ns)
ns.update(X=0.0, Y=0.0, SALT=3, NAME_HINT="", r=ns["rng"](3))
out = {}
SCENES = [
    ("villa", "Make a villa", "villa('Villa', at=(0, 0, 0))"),
    ("shop", "Make a little bakery", "storefront('Bakery', at=(0, 0, 0), width=8, floors=2)"),
    ("cabin", "A cabin in the woods", "house('Cabin', at=(0, 0, 0), style='cabin')"),
    ("falls", "Create a waterfall", "waterfall('Waterfall', at=(0, 0, 0), height=14, width=5, moss=True)"),
]
for label, goal, build in SCENES:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    if bpy.context.scene.world is not None:
        bpy.data.worlds.remove(bpy.context.scene.world)
    res = {"steps": {}}
    try:
        exec(build, ns)
        state = json.loads(ns["scene_state"]())
        plan = environment.plan(goal, state, set())
        res["setting"] = plan["setting"]
        for st in plan["steps"]:
            ns["step_begin"]()
            try:
                exec(compile(st["code"], "<env>", "exec"), ns)
                res["steps"][st["title"]] = "ok"
            except Exception as e:
                res["steps"][st["title"]] = f"{type(e).__name__}: {e}"
        ns["camera"]("Camera", plan["subjects"], "wide")
        path = OUT + f"/{label}.png"
        ns["render_view"](path, width=480, samples=6)
        res["render"] = path
        res["frames"] = json.loads(ns["thing_frames"]())
        res["subjects"] = plan["subjects"]
        # where every planted instance stands, against the subject's own box
        subj = bpy.data.objects[plan["subjects"][0]]
        core = [c for c in subj.children_recursive if c.name.endswith(("Walls", "Body"))] or [subj]
        lo, hi = ns["bounds"](core[0])   # its walls: what stands beside its path is outside it
        inside = []
        for o in bpy.data.objects:
            if o.instance_type == "COLLECTION" and o.users_collection and o.parent is not None:
                x, y = o.matrix_world.translation.x, o.matrix_world.translation.y
                if lo[0] + 0.3 < x < hi[0] - 0.3 and lo[1] + 0.3 < y < hi[1] - 0.3:
                    inside.append(o.name)
        res["inside"] = inside[:10]
        res["clouds"] = json.loads(ns["env_state"]())["set"].get("clouds")
    except Exception:
        res["error"] = traceback.format_exc()[-1500:]
    out[label] = res
print("RESULT_JSON " + json.dumps(out, default=str))
'''


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    folder = tmp_path_factory.mktemp("environment")
    script = folder / "env_test.py"
    script.write_text(f"ROOT = {ROOT!r}\nOUT = {str(folder)!r}\n" + SCRIPT, encoding="utf-8")
    env = dict(os.environ, USERPROFILE=str(folder), HOME=str(folder), TEMP=str(folder), TMP=str(folder))
    done = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=1500, env=env)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    assert line, done.stdout[-3000:] + done.stderr[-2000:]
    return json.loads(line[len("RESULT_JSON "):])


@pytest.mark.parametrize("label,setting", [("villa", "residential"), ("shop", "urban"), ("cabin", "forest"),
                                           ("falls", "waterfall")])
def test_each_subject_gets_its_world_and_every_step_builds(worlds, label, setting):
    res = worlds[label]
    assert "error" not in res, res.get("error")
    assert res["setting"] == setting
    assert res["steps"] and all(v == "ok" for v in res["steps"].values()), res["steps"]


@pytest.mark.parametrize("label", ["villa", "shop", "cabin"])
def test_nothing_grows_inside_the_subject(worlds, label):
    assert worlds[label]["inside"] == []


@pytest.mark.parametrize("label", ["villa", "shop", "cabin", "falls"])
def test_the_camera_shows_the_whole_subject_under_a_sky_in_a_readable_light(worlds, label):
    from PIL import Image
    import image_analysis
    res = worlds[label]
    frame = res["frames"].get(res["subjects"][0])
    assert frame, "the subject isn't in view"
    assert frame[4] > 0.8 and frame[0] > 0.0 and frame[2] < 1.0, frame   # whole, not cropped
    img = Image.open(res["render"]).convert("RGB")
    st = image_analysis.stats(img)
    assert 0.15 < st["mean"] < 0.85, st["mean"]
    sky = image_analysis.sky_rows(img)
    assert sky["share"] > 0.3, sky   # sky above it
    assert st["contrast"] > 0.2, st["contrast"]   # not one flat colour
