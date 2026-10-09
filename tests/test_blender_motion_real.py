"""Motion, cameras and light in a real Blender, headless and isolated: everything measured over the timeline, never
assumed — keys, easing and loops, a door on a real hinge, a car that stays on the ground and gets there, cameras
that keep their subject framed and never stand in a wall, lights that come up, a sky that turns to night, water
that ripples inside its pool, waves, wind, fire, rain, a flag — and undo that takes it all back, repairs, and the
scene's existing geometry untouched. Then the whole agent loop on a live bridge. Skipped without Blender."""
import json
import os
import subprocess

import pytest

import agent_blender
import cinema
import spatial
from test_blender_assets_real import BLENDER, ROOT
from test_blender_spatial_real import clear, live, run_task, scripted_ai, things   # noqa: F401  (live: a fixture)

pytestmark = pytest.mark.skipif(BLENDER is None, reason="Blender isn't installed here")

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
        out[label] = {"ok": True, "result": str(ns.get("RESULT", ""))[:300]}
    except Exception as e:
        out[label] = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-600:]}
    ns["RESULT"] = ""
S = bpy.context.scene
def at(f, fn):
    S.frame_set(f); bpy.context.view_layer.update(); return fn()
def world(name):
    return [round(v, 3) for v in bpy.data.objects[name].matrix_world.translation]
def box_of(name):
    lo, hi = ns["bounds"](name); return [list(lo), list(hi)]
def verts():
    return {o.name: len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH" and o.data is not None}
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
run("timeline", "RESULT = timeline(10)")
run("scene", "house('Villa', at=(0, 0, 0), style='modern')\ns = spot_near('Villa', 'beside', what='swimming pool')\n"
             "pool('Pool', at=s, rotation=s.rotation)\ntree('Oak', at=(-16, 6, 0))\nwater('Sea', at=(0, 70, 0), size=40)")
before = verts()
# keys, easing, loops
run("ease", "box('Crate', 1, at=(-10, -20, 0))\nanimate('Crate', 'location', [(0, (-10, -20, 0)), (2, (-5, -20, 0))], ease='out')")
fc = [f for f in bpy.data.objects["Crate"].animation_data.action.fcurves if f.data_path == "location"][0]
out["ease_kind"] = [fc.keyframe_points[0].interpolation, fc.keyframe_points[0].easing]
out["ease_mid"] = at(ns["sec"](1), lambda: world("Crate")[0])
run("loop", "box('Statue', 1, at=(-14, -20, 0))\nspin('Statue', 360, 'z', start=0, end=2, loop=True)")
out["loop_cycles"] = any(m.type == "CYCLES" for f in bpy.data.objects["Statue"].animation_data.action.fcurves for m in f.modifiers)
out["loop_spins_on"] = [round(at(ns["sec"](t), lambda: bpy.data.objects["Statue"].matrix_world.to_euler().z), 2) for t in (0.5, 2.5)]
# a door on a real hinge
door_closed = at(1, lambda: box_of("Villa Door"))
run("door_run", "open_door('Villa', start=1, end=3)")
door_open = at(ns["sec"](3), lambda: box_of("Villa Door"))
out["door_data"] = {"closed": door_closed, "open": door_open,
               "hinge_parent": bpy.data.objects["Villa Door Hinge"].parent.name,
               "handle_follows": bpy.data.objects["Villa Door Handle"].parent.name}
# a car that drives on the ground round the villa to the pool
run("car_run", "box('Car Body', (4.4, 1.8, 0.7), at=(-22, -22, 0.0), color='red', bevel=0.05)\n"
           "box('Car Cabin', (2.2, 1.6, 0.6), at=(-22.3, -22, 0.7), color='glass')\n"
           "drive('Car Body', 'Pool', start=0, end=8)")
car = []
for f in range(1, 242, 20):
    S.frame_set(f); bpy.context.view_layer.update()
    lo, hi = ns["bounds"]("Car")
    car.append([list(lo), list(hi), round(bpy.data.objects["Car"].matrix_world.to_euler().z, 3)])
out["car_path"] = car
out["villa_core"] = [t for t in ns["scene_things"]() if t["name"] == "Villa"][0]["core"]
out["pool_outer"] = [t for t in ns["scene_things"]() if t["name"] == "Pool"][0]["outer"]
# cameras
run("push", "camera_move('Camera', 'push_in', 'Villa', start=0, end=10)")
run("orbit", "camera_move('Orbit Cam', 'orbit', 'Pool', start=0, end=10, sweep=270, active=False)")
run("follow", "camera_move('Follow Cam', 'follow', 'Car', start=0, end=8, active=False)")
# light
run("pool_lights", "lights_on('Pool', start=5, end=6)")
run("interior", "lights_on('Villa', start=2, end=4)")
run("sky", "sky('day_to_night')")
# nature
run("ripples", "animate_naturally('Pool')")
run("waves", "animate_naturally('Sea')")
run("sway", "sway('Oak')")
run("fire", "fire('Campfire', at=(-12, -30, 0))")
run("rain", "rain('Rain')")
run("flag", "flag('Flag', at=(-6, -14, 0))")
rep = json.loads(ns["motion_report"]())
out["report"] = rep
out["after"] = verts()
out["before"] = before
pw = bpy.data.objects["Pool Water"]
mat = pw.active_material
dg = bpy.context.evaluated_depsgraph_get()
def w_at(f):
    S.frame_set(f); dg2 = bpy.context.evaluated_depsgraph_get()
    m = mat.evaluated_get(dg2) if hasattr(mat, "evaluated_get") else mat
    nz = next(n for n in m.node_tree.nodes if n.type == "TEX_NOISE")
    return round(nz.inputs["W"].default_value, 4)
out["water_W"] = [w_at(1), w_at(121)]
out["pool_water_box"] = [at(1, lambda: box_of("Pool Water")), at(121, lambda: box_of("Pool Water"))]
rain_root = bpy.data.objects["Rain Clouds"]
S.frame_set(121); dg = bpy.context.evaluated_depsgraph_get()
zs = [p.location.z for p in rain_root.evaluated_get(dg).particle_systems[0].particles if p.alive_state == "ALIVE"]
out["rain_drops"] = [len(zs), min(zs) if zs else None, max(zs) if zs else None]
# repairs
run("bad_light", "light('Lamp', 'point', at=(0, -12, 3), energy=200)\nbpy.data.objects['Lamp'].data.energy = -5\nRESULT = str(check_lights())")
out["lamp_energy"] = bpy.data.objects["Lamp"].data.energy
run("stuck_cam", "camera('Stuck', 'Pool', 'wide', active=False)\nbpy.data.objects['Stuck'].location = (0, 0, 2)\n"
                 "bpy.data.objects['Stuck'].keyframe_insert('location', frame=1)\nRESULT = str(unblock_camera('Stuck'))")
out["stuck_after"] = at(1, lambda: world("Stuck"))
# colour on a copy of the material, never on what's shared
run("shared", "box('Red A', 1, at=(20, -20, 0), color='red')\nbox('Red B', 1, at=(22, -20, 0), color='red')\n"
              "colour_to('Red A', 'blue', 0, 2)")
out["shared_mats"] = [bpy.data.objects["Red A"].active_material.name, bpy.data.objects["Red B"].active_material.name,
                 list(bpy.data.objects["Red B"].active_material.diffuse_color)[:3]]
# undo takes motion back
exec(compile(agent_blender._SNAPSHOT_CODE, "<snap>", "exec"), ns)
snap = json.loads(ns["RESULT"])
run("later", "animate('Statue', 'location', [(0, (-14, -20, 0)), (2, (-14, -10, 0))])\nwind(2.0)\ntimeline(30)")
exec(compile(agent_blender._restore_code(snap), "<restore>", "exec"), ns)
out["undo"] = {"statue_paths": sorted({f.data_path for f in bpy.data.objects["Statue"].animation_data.action.fcurves}),
               "end": S.frame_end, "camera_keys": len(bpy.data.objects["Camera"].animation_data.action.fcurves)}
# the timeline: keyed motion keeps it long enough, what moves forever doesn't, a length the user said is the length
run("keep", "RESULT = timeline(2)")
out["keep_end"] = [S.frame_end, ns["_last_key"]()]
run("exact", "RESULT = timeline(2, keep_longer=False)")
out["exact_end"] = S.frame_end
# an island's palms: wind sways each of them, a camera can film them as its subject
run("island", "island('Isle', at=(80, 80, 0), radius=12, trees=3, tree_kind='palm')")
run("island_wind", "RESULT = str(wind())")
palms = sorted(n for n in bpy.data.objects.keys() if n.startswith("Isle Palm") and n.count(" ") == 2)
out["isle"] = {"palms": palms, "swaying": sorted(n for n in palms if bpy.data.objects[n].get("jervis_motion") == "sway"),
               "terrain_still": not (bpy.data.objects["Isle Terrain"].animation_data or None)}
run("isle_cam", "camera_move('Isle Cam', 'orbit', 'palm trees', start=0, end=2, active=False)")
out["isle_cam_subject"] = json.loads(bpy.data.objects["Isle Cam"].get("jervis_subject", "[]"))
# a driveway: a garage's door lifts, a gate's leaves swing in, a car drives out forwards on turning wheels
run("timeline8", "RESULT = timeline(8, keep_longer=False)")
run("driveway", "garage('Garage', at=(-60, -60, 0))\ngate('Gate', at=(-48, -78, 0))\n"
                "car('Roadster', at=(-60, -68.5, 0), rotation=-90)")
garage_door_shut = at(1, lambda: box_of("Garage Door"))
leaves_shut = [at(1, lambda n=n: box_of(n)) for n in ("Gate Leaf 1", "Gate Leaf 2")]
car_parts = sorted(c.name for c in bpy.data.objects["Roadster"].children_recursive)
run("garage_open", "open_door('Garage', start=0, end=2)")
run("gate_open", "open_door('Gate', start=1, end=3)")
run("car_drive", "drive('Roadster', 'Gate', start_place='Garage', start=2, end=7)")
run("car_follow", "camera_move('Chase', 'follow', 'Roadster', start=2, end=7, active=False)")
def car_pose(f):
    S.frame_set(f); bpy.context.view_layer.update()
    c = bpy.data.objects["Roadster"]
    nose = c.matrix_world.to_3x3() @ mathutils.Vector((1, 0, 0))
    return {"at": [round(v, 2) for v in c.matrix_world.translation], "nose": [round(nose.x, 2), round(nose.y, 2)],
            "wheel": round(bpy.data.objects["Roadster Wheel 1"].rotation_euler.y, 2), "box": box_of("Roadster")}
out["drive_data"] = {"door_shut": garage_door_shut, "door_open": at(ns["sec"](2.5), lambda: box_of("Garage Door")),
                   "leaves_shut": leaves_shut,
                   "leaves_open": [at(ns["sec"](3.5), lambda n=n: box_of(n)) for n in ("Gate Leaf 1", "Gate Leaf 2")],
                   "car_parts": car_parts, "poses": [car_pose(ns["sec"](t)) for t in (2.0, 3.0, 4.5, 6.0, 7.0)],
                   "gate_box": box_of("Gate Posts"), "garage_box": at(1, lambda: box_of("Garage Walls"))}
out["chase_report"] = json.loads(ns["motion_report"](["Chase"]))
print("RESULT_JSON " + json.dumps(out, default=str))
'''


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    folder = tmp_path_factory.mktemp("blender_motion")
    script = folder / "motion_test.py"
    script.write_text(f"ROOT = {ROOT!r}\n" + KIT_SCRIPT, encoding="utf-8")
    env = dict(os.environ, USERPROFILE=str(folder), HOME=str(folder), TEMP=str(folder), TMP=str(folder))
    done = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=600, env=env)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    assert line, done.stdout[-2000:] + done.stderr[-2000:]
    return json.loads(line[len("RESULT_JSON "):])


def ok(kit, *labels):
    for label in labels:
        assert kit[label]["ok"], (label, kit[label])


def obj(kit, name):
    return kit["report"]["objects"][name]


def test_every_operation_runs(kit):
    ok(kit, "timeline", "scene", "ease", "loop", "door_run", "car_run", "push", "orbit", "follow", "pool_lights", "interior",
       "sky", "ripples", "waves", "sway", "fire", "rain", "flag", "bad_light", "stuck_cam", "shared", "later")
    assert kit["report"]["scene"]["end"] == 241 and kit["report"]["scene"]["fps"] == 24


def test_easing_and_looping_are_real_keyframe_settings(kit):
    assert kit["ease_kind"] == ["CUBIC", "EASE_OUT"]
    assert kit["ease_mid"] > -7.5                                # ease-out: well past halfway at half time
    assert kit["loop_cycles"]
    a, b = kit["loop_spins_on"]
    assert abs(a - b) < 0.05                                     # 0.5 s and 2.5 s: one loop apart, same angle


def test_a_door_swings_inward_on_its_own_hinge_with_its_handle(kit):
    d = kit["door_data"]
    closed_y = (d["closed"][0][1] + d["closed"][1][1]) / 2
    open_y = (d["open"][0][1] + d["open"][1][1]) / 2
    assert open_y > closed_y + 0.3                               # into the villa (it faces -y)
    assert abs(d["open"][0][0] - d["closed"][0][0]) < 0.15       # the hinge side stays put
    assert d["hinge_parent"] == "Villa" and d["handle_follows"] == "Villa Door Hinge"


def test_a_car_drives_on_the_ground_round_the_villa_to_the_pool(kit):
    core = kit["villa_core"]
    for lo, hi, yaw in kit["car_path"]:
        assert abs(lo[2]) < 0.06                                  # on the ground the whole way
        assert spatial.overlap_depth((lo[0], lo[1], hi[0], hi[1]), core) <= 0   # never through the villa
    lo, hi, _ = kit["car_path"][-1]
    assert spatial.gap((lo[0], lo[1], hi[0], hi[1]), kit["pool_outer"]) < 1.5
    yaws = [y for _, _, y in kit["car_path"]]
    assert max(yaws) - min(yaws) > 0.2                           # it turned to follow the route


@pytest.mark.parametrize("camera", ["Camera", "Orbit Cam", "Follow Cam"])
def test_cameras_keep_their_subject_framed_and_unblocked(kit, camera):
    entry = obj(kit, camera)
    views = [s["view"] for s in entry["samples"] if s.get("view")]
    assert views and all(v["visible"] >= 0.75 and v["in_front"] for v in views), views
    assert not [v for v in views if v["blocked_by"]], views
    assert cinema.moved([{k: s[k] for k in ("loc",)} for s in entry["samples"]])


def test_lights_come_up_when_asked_and_stay_valid(kit):
    pool_lights = [e for n, e in kit["report"]["objects"].items() if n.startswith("Pool Light") and e["type"] == "LIGHT"]
    inside = [e for n, e in kit["report"]["objects"].items() if n.startswith("Villa Light")]
    assert pool_lights and inside
    for e in pool_lights:
        energy = [s["energy"] for s in e["samples"]]
        assert energy[0] == 0 and energy[1] == 0 and energy[-1] > 50       # off until 5 s, on by the end
    for e in inside:
        lo = [s["lo"] for s in e["samples"]][0]
        assert spatial.contains(kit["villa_core"], lo)             # inside the villa
    assert kit["lamp_energy"] >= 0


def test_the_sky_turns_from_day_to_night(kit):
    sun = [s["energy"] for s in obj(kit, "Sun")["samples"]]
    sky_ = [w["strength"] for w in kit["report"]["world"]]
    assert sun[0] > 3 and sun[-1] < 0.5 and sky_[0] > sky_[-1]


def test_pool_water_ripples_but_stays_exactly_in_its_pool(kit):
    a, b = kit["pool_water_box"]
    assert a == b                                                # the water's shape and place never change
    w0, w1 = kit["water_W"]
    assert w1 != w0                                              # its surface pattern flows with time


def test_open_water_rolls_in_waves_within_a_metre(kit):
    sea = obj(kit, "Sea Surface")
    sigs = [s["sig"] for s in sea["samples"]]
    assert max(sigs) - min(sigs) > 0.01
    assert all(-1.0 < s["lo"][2] and s["hi"][2] < 1.0 for s in sea["samples"])


def test_wind_fire_rain_and_a_flag_move_by_themselves(kit):
    assert cinema.moved([{"rot": s["rot"]} for s in obj(kit, "Oak")["samples"]])
    assert all(abs(s["rot"][0]) < 0.06 for s in obj(kit, "Oak")["samples"])   # a sway, not a fall
    glow = [s["energy"] for s in obj(kit, "Campfire Glow")["samples"]]
    assert max(glow) - min(glow) > 1
    count, low, high = kit["rain_drops"]
    assert count > 100 and low > -2 and high < 40
    flag = [s["sig"] for s in obj(kit, "Flag Cloth")["samples"]]
    assert max(flag) - min(flag) > 0.01


def test_no_existing_geometry_was_changed_by_any_of_it(kit):
    before, after = kit["before"], kit["after"]
    assert all(after.get(n) == v for n, v in before.items()), {n: (v, after.get(n)) for n, v in before.items()
                                                               if after.get(n) != v}


def test_repairs_lift_a_stuck_camera_and_keep_shared_materials(kit):
    assert int(kit["stuck_cam"]["result"]) >= 1 and kit["stuck_after"][2] > 4
    a, b, colour = kit["shared_mats"]
    assert a != b and colour[0] > 0.5 and colour[2] < 0.2          # 'Red B' is still red


def test_undo_takes_back_keys_wind_and_the_timeline(kit):
    u = kit["undo"]
    assert u["statue_paths"] == ["rotation_euler"] and u["end"] == 241 and u["camera_keys"] > 0


def test_the_timeline_keeps_keyed_motion_but_not_endless_motion_and_obeys_a_said_length(kit):
    ok(kit, "keep", "exact")
    end, last_key = kit["keep_end"]
    assert 49 < last_key <= 241 and end == last_key   # the car's and camera's keys, not the waves' or the wind's
    assert kit["exact_end"] == 49


def test_a_garage_door_lifts_up_and_a_gates_leaves_swing_in_on_their_posts(kit):
    ok(kit, "driveway", "garage_open", "gate_open")
    d = kit["drive_data"]
    (slo, shi), (olo, ohi) = d["door_shut"], d["door_open"]
    assert olo[2] > slo[2] + 1.5                         # its foot rose under the roof...
    assert ohi[2] <= shi[2] + 0.2                        # ...and it never went up through it
    assert ohi[1] > shi[1] + 1.5 and olo[1] > slo[1] - 0.1   # it folded inside (the garage is behind it, +y)
    for (lo0, hi0), (lo1, hi1) in zip(d["leaves_shut"], d["leaves_open"]):
        assert hi1[1] - lo1[1] > 1.0                     # each leaf turned about 90 degrees...
        assert lo1[1] > lo0[1] - 0.2                     # ...toward the garage side (+y), not out into the road
    (l1, h1), (l2, h2) = d["leaves_open"]
    assert h1[0] < l2[0]                                 # on their own posts at either side: the way is open


def test_a_car_drives_out_forwards_to_the_gate_on_turning_wheels_and_the_camera_chases_it(kit):
    ok(kit, "car_drive", "car_follow")
    d = kit["drive_data"]
    assert {"Roadster Body", "Roadster Windows", "Roadster Wheel 1", "Roadster Wheel 4", "Roadster Headlights"} <= set(d["car_parts"])
    poses = d["poses"]
    for a, b in zip(poses, poses[1:]):
        step = [b["at"][0] - a["at"][0], b["at"][1] - a["at"][1]]
        if abs(step[0]) + abs(step[1]) > 0.5:            # going somewhere: nose first
            assert step[0] * a["nose"][0] + step[1] * a["nose"][1] > 0, (a, b)
    assert abs(poses[-1]["wheel"] - poses[0]["wheel"]) > 6.0   # the wheels rolled (several turns over ~20 m)
    (glo, ghi), (clo, chi) = d["gate_box"], poses[-1]["box"]
    assert clo[1] > ghi[1] - 0.1 or chi[1] < glo[1] + 0.1 or clo[0] > ghi[0] or chi[0] < glo[0]   # not in the gate
    assert all(abs(p["at"][2] - poses[0]["at"][2]) < 0.05 for p in poses)                         # on the ground
    views = [s["view"] for s in kit["chase_report"]["objects"]["Chase"]["samples"] if s.get("view")]
    assert views and all(v["in_front"] and v["visible"] >= 0.5 and not v["blocked_by"] for v in views), views


def test_wind_sways_an_islands_palms_and_a_camera_films_them(kit):
    ok(kit, "island", "island_wind", "isle_cam")
    isle = kit["isle"]
    assert len(isle["palms"]) == 3 and isle["swaying"] == isle["palms"] and isle["terrain_still"]
    assert sorted(kit["isle_cam_subject"]) == isle["palms"]


# ---------- the agent loop on a live bridge ----------

BRIEF = ("Create a 10-second cinematic where the camera approaches the villa, the pool lights turn on halfway "
         "through, and the door opens near the end.")


def build_scene(bridge):
    clear(bridge)
    adapter = agent_blender.BlenderAdapter(bridge)
    adapter.prepare()
    assert bridge.run("house('Villa', at=(0, 0, 0), style='modern')\ns = spot_near('Villa', 'beside', "
                      "what='swimming pool')\npool('Pool', at=s, rotation=s.rotation)\nRESULT = 'ok'", timeout=60).get("ok")


def no_ai(*args, **kw):
    raise AssertionError("the director should need no AI for this")


def report_of(bridge):
    return json.loads(bridge.run("RESULT = motion_report()", timeout=60)["output"])


def test_the_brief_is_directed_and_verified_without_the_ai(live):
    build_scene(live)
    task, result, state, log = run_task(live, BRIEF, no_ai)
    assert task.state == "completed", (result, log)
    assert "directed a 10-second shot at 24 fps" in result and "checks passed" in result
    rep = report_of(live)
    assert rep["scene"]["end"] - rep["scene"]["start"] == 240
    views = [s["view"] for s in rep["objects"]["Camera"]["samples"]]
    assert all(v["visible"] >= 0.75 and not v["blocked_by"] for v in views)
    pool_light = next(e for n, e in rep["objects"].items() if n.startswith("Pool Light") and e["type"] == "LIGHT")
    energy = [s["energy"] for s in pool_light["samples"]]
    assert energy[0] == 0 and energy[-1] > 0
    hinge = rep["objects"]["Villa Door Hinge"]["samples"]
    assert abs(hinge[0]["rot"][2] - hinge[-1]["rot"][2]) > 1.4    # the door ends open (~95 degrees)


def test_a_failed_step_is_rolled_back_keys_and_all_then_repaired(live):
    build_scene(live)
    assert live.run("box('Jelly', 1, at=(-12, -12, 0), color='green')\nRESULT = 'ok'").get("ok")
    plan = {"understanding": "Make the jelly wobble", "question": "", "steps": [
        {"title": "Wobble", "checks": [], "code": "animate('Jelly', 'scale', [(0, 1), (0.5, (1.2, 1.2, 0.8)), (1, 1)])\n"
                                                  "animate('Jely', 'scale', [(0, 1), (1, 1.1)])"}],
            "final_checks": [{"type": "animated", "object": "Jelly"}]}
    repair = {"diagnosis": "the second call misspelt the name", "checks_were_wrong": False,
              "code": "animate('Jelly', 'scale', [(0, 1), (0.4, (1.15, 1.15, 0.85)), (0.8, (0.95, 0.95, 1.05)), "
                      "(1.2, 1)], loop=True)"}
    task, result, state, log = run_task(live, "make the jelly wobble like jelly", scripted_ai(plan=plan, repairs=[repair]))
    assert task.state == "completed", (result, log)
    assert any("attempt 1 failed" in l and "Jely" in l for l in log)
    rep = report_of(live)
    assert rep["objects"]["Jelly"]["keys"] == 4 * 3                # only the repair's keys: the failed ones undone


def test_a_camera_the_ai_put_inside_the_villa_is_craned_out(live):
    build_scene(live)
    plan = {"understanding": "A shot of the pool", "question": "", "steps": [
        {"title": "Camera", "checks": [], "code": "camera('Camera', 'Pool', 'wide')\nmove('Camera', to=(0, 0, 2))\n"
                                                  "bpy.data.objects['Camera'].keyframe_insert('location', frame=1)"}],
            "final_checks": [{"type": "camera_frames", "object": "Camera", "other": "Pool"}]}
    task, result, state, log = run_task(live, "make a camera shot of the pool from inside the villa",
                                        scripted_ai(plan=plan))
    assert task.state == "completed", (result, log)
    assert any("auto-fix" in l and "inside something" in l for l in log)


def test_a_sea_moves_by_itself_once_built_and_says_so(live):
    clear(live)
    assets = [{"asset": "water", "options": {}, "count": 1, "understanding": "A sea", "other_things": ""}]
    task, result, state, log = run_task(live, "create a sea", scripted_ai(assets=assets))
    assert task.state == "completed", (result, log)
    assert "rolls in slow waves" in result
    rep = report_of(live)
    sea = next(e for n, e in rep["objects"].items() if n.endswith("Surface"))
    sigs = [s["sig"] for s in sea["samples"]]
    assert max(sigs) - min(sigs) > 0.01
