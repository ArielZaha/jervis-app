"""The living-environment kit in a real Blender (blender_places / blender_props / blender_world): places and props
build with their named parts; time of day changes everything it should (windows glow pane by pane at night, not by
day; street lamps come on); fog is ONE volume, thickened or cleared; rain wets and clearing dries; water and wind are
retuned, not stacked; motion pauses and resumes; materials change only on the parts meant; cameras match a photo's
and move without ever ending inside a wall; and every thing carries its meaning."""
import json
import os
import subprocess

import pytest

from test_blender_assets_real import BLENDER, ROOT

pytestmark = pytest.mark.skipif(not os.path.exists(BLENDER), reason="Blender isn't installed here")

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
        out[label] = {"ok": True, "result": str(ns.get("RESULT", ""))[:2000]}
    except Exception as e:
        out[label] = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
    ns["RESULT"] = ""
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
S = bpy.context.scene
def names(prefix):
    return sorted(o.name for o in bpy.data.objects if o.name.startswith(prefix))
def emission(obj_name):
    o = bpy.data.objects[obj_name]
    vals = []
    for slot in o.material_slots:
        m = slot.material
        b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
        if b is None:
            continue
        power = m.node_tree.nodes.get("Jervis glow power")
        vals.append(power.inputs[1].default_value if power else b.inputs["Emission Strength"].default_value)
    return max(vals) if vals else 0.0
run("ground", "ground('Ground', size=120, kind='lawn')")
run("villa", "villa('Villa', at=(0, 20, 0), floors=2, wings=2)\ntag_semantic('Villa', 'villa', role='the main building')")
run("pool", "pool('Pool', at=(4, 6, 0), length=10, width=4)\ntag_semantic('Pool', 'swimming pool')")
run("shop", "storefront('Shop', at=(-40, 20, 0), lanterns=2)\ntag_semantic('Shop', 'shop')")
run("road", "road('Road', at=(0, -8, 0), length=80)")
run("lamp", "street_lamp('Lamp', at=(-10, -3, 0))")
run("props", "sofa('Sofa', at=(40, 0, 0))\narmchair('Chair', at=(43, 0, 0))\ncoffee_table('Table', at=(40, -1.5, 0))\n"
             "shelf('Shelf', at=(46, 0, 0))\nrug('Rug', at=(40, -1, 0))\ntv('TV', at=(40, -4, 0))\n"
             "floor_lamp('Floor Lamp', at=(37, 0, 0))\npotted_plant('Plant', at=(48, 0, 0))\n"
             "parasol('Parasol', at=(12, 6, 0))\nlantern('Lantern', at=(-12, -3, 0))\ncrate('Crate', at=(-14, -3, 0))")
run("room", "room('Room', at=(80, 0, 0))")
run("shore", "shore('Beach', at=(0, 400, 0), width=80)")
run("hills", "hills('Hills', at=(0, 0, 0), distance=300)")
run("forest", "forest('Woods', at=(60, 60, 0), width=20, depth=10, count=12)")
run("cam", "RESULT = camera_match('Camera', height=3.0, pitch=2.0, yaw=0.0, lens=28, at=(0, -40), look_distance=55)")
out["parts"] = {"villa": names("Villa "), "shop": names("Shop "), "props": names("Sofa ") + names("Floor Lamp ")}
run("day", "time_of_day('day')")
out["day_glow"] = emission("Villa Window Glass")
out["day_lamp"] = bpy.data.objects["Lamp Bulb"].data.energy
run("night", "RESULT = json.dumps(time_of_day('night'))")
glass = bpy.data.objects["Villa Window Glass"]
out["night_glow"] = emission("Villa Window Glass")
out["pane_values"] = len(set(round(v.value, 4) for v in glass.data.attributes["jervis_pane"].data)) if "jervis_pane" in glass.data.attributes else 0
out["night_lamp"] = bpy.data.objects["Lamp Bulb"].data.energy
out["night_sign"] = emission("Shop Sign")
out["night_lanterns"] = emission("Shop Lanterns")
out["night_exposure"] = S.view_settings.exposure
run("fog1", "fog('fog')")
run("fog2", "fog(factor=1.7)")
out["fogs"] = names("Jervis Fog")
out["fog_env"] = json.loads(ns["env_state"]())["set"].get("fog")
run("fog_off", "fog(remove=True)")
out["fogs_after"] = names("Jervis Fog")
run("rain", "weather('rain')")
asph = bpy.data.objects["Road Asphalt"].active_material
out["wet_rough"] = [asph.get("jervis_dry_rough"), asph.get("jervis_wet")]
out["rain_present"] = bpy.data.objects.get("Rain") is not None
run("clear", "weather('clear')")
out["dry"] = [asph.get("jervis_wet"), bpy.data.objects.get("Rain") is None]
run("water", "animate_water('Pool', 'ripples')\nwater_motion('Pool', strength_factor=2.0)\nwater_motion('Pool', strength_factor=2.0)")
out["water_state"] = json.loads(bpy.data.objects["Pool"].get("jervis_water", "{}"))
run("wind", "RESULT = str(wind_strength(1.0))\nwind_strength(factor=1.6)")
out["wind_env"] = json.loads(ns["env_state"]())["set"].get("wind_strength")
run("pause", "RESULT = str(pause_motion())")
run("resume", "RESULT = str(resume_motion())")
before_walls = [s.material.name for s in bpy.data.objects["Villa Walls"].material_slots]
before_slab = [s.material.name for s in bpy.data.objects["Villa Slabs"].material_slots]
run("mat", "RESULT = str(material_edit('Villa', 'roof', darker=0.4))\nmaterial_edit('Shop', 'walls', color='red')")
out["mat_data"] = {"walls_before": before_walls, "walls_after": [s.material.name for s in bpy.data.objects["Villa Walls"].material_slots],
              "shop_walls": list(bpy.data.objects["Shop Walls"].active_material.diffuse_color)[:3]}
run("behind", "RESULT = str(camera_edit('Camera', subject='Villa', side='behind'))")
run("check_behind", "RESULT = camera_check('Camera')")
run("closer", "RESULT = str(camera_edit('Camera', closer=0.1))")
run("check_closer", "RESULT = camera_check('Camera')")
run("cam2", "camera('Camera 2', 'Pool', 'wide', active=False)\nRESULT = switch_camera()")
run("rename", "RESULT = rename_camera('Camera 2', 'Pool Cam')")
run("render", f"RESULT = render_view(r'{OUT}', width=320, samples=4)")
out["render_exists"] = os.path.exists(OUT)
run("frames", "RESULT = thing_frames('Camera')")
run("registry", "RESULT = semantic_registry()")
run("lights", "RESULT = str(lights_set('Pool', on=True))")
out["pool_lights"] = names("Pool Light")
run("move", "RESULT = json.dumps(move_with('Villa', direction='back', distance=5))")
run("plights", "RESULT = str(path_lights('Road', spacing=10))")
run("river", "river('Stream', start=(-30, 80), end=(-30, 30), width=5)")
from mathutils import Vector
g = bpy.data.objects["Ground Surface"]
ev = g.evaluated_get(bpy.context.evaluated_depsgraph_get())
hit = ev.ray_cast(g.matrix_world.inverted() @ Vector((-30, 55, 50)), Vector((0, 0, -1)))[0]
out["ground_over_river"] = bool(hit)
run("falls", "waterfall('Falls', at=(-80, 120, 0), height=12, width=4, moss=True)")
out["falls_mats"] = [s.material.name for s in bpy.data.objects["Falls Cliff"].material_slots if s.material]
run("stones", "forest('Stones', at=(-60, 60, 0), width=10, depth=6, count=20, kind='mossy rocks')")
out["stone_count"] = len(names("Stones Tree"))
run("regrow", "rebuild_asset('Villa', width=30.0)")
out["regrown"] = [ns["asset_info"]("Villa")["params"].get("width"), json.loads(bpy.data.objects["Villa"].get("jervis_semantic", "{}")).get("kind")]
run("clouds", "time_of_day('day')\nsky_clouds(cover=0.4)")
wn = S.world.node_tree.nodes
out["cloud_day"] = list(wn["Jervis clouds tint"].inputs["B"].default_value)[:3] if "Jervis clouds tint" in wn else None
run("clouds_sunset", "time_of_day('sunset')")
out["cloud_sunset"] = list(wn["Jervis clouds tint"].inputs["B"].default_value)[:3] if "Jervis clouds tint" in wn else None
out["cloud_env"] = json.loads(ns["env_state"]())["set"].get("clouds")
run("mist", "fog('mist')")
out["mist_glow"] = bpy.data.objects["Jervis Fog"].active_material.node_tree.nodes["Jervis fog glow"].inputs[1].default_value
run("clouds_off", "sky_clouds(remove=True)")
bg = next(n for n in wn if n.type == "BACKGROUND")
out["clouds_after"] = [len([n for n in wn if n.name.startswith("Jervis clouds")]), bg.inputs["Color"].is_linked]
print("RESULT_JSON " + json.dumps(out, default=str))
'''


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    folder = tmp_path_factory.mktemp("blender_world")
    script = folder / "world_test.py"
    render = str(folder / "render.png")
    script.write_text(f"ROOT = {ROOT!r}\nimport os\nOUT = {render!r}\n" + KIT_SCRIPT, encoding="utf-8")
    env = dict(os.environ, USERPROFILE=str(folder), HOME=str(folder), TEMP=str(folder), TMP=str(folder))
    done = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=900, env=env)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    assert line, done.stdout[-3000:] + done.stderr[-2000:]
    return json.loads(line[len("RESULT_JSON "):])


def ok(kit, *labels):
    for label in labels:
        assert kit[label]["ok"], (label, kit[label])


def test_places_and_props_build_with_their_named_parts(kit):
    ok(kit, "ground", "villa", "pool", "shop", "road", "lamp", "props", "room", "shore", "hills", "forest")
    villa, shop = set(kit["parts"]["villa"]), set(kit["parts"]["shop"])
    assert {"Villa Window Glass", "Villa Slabs", "Villa Balcony Glass", "Villa Door", "Villa Terrace"} <= villa
    assert {"Shop Sign", "Shop Display Glass", "Shop Lanterns", "Shop Interior"} <= shop
    assert "Floor Lamp Bulb" in kit["parts"]["props"]


def test_night_lights_windows_pane_by_pane_signs_and_lamps_and_day_turns_them_off(kit):
    ok(kit, "day", "night")
    assert kit["day_glow"] == 0.0 and kit["day_lamp"] == 0.0
    assert kit["night_glow"] > 0.5 and kit["night_lamp"] > 50
    # lanterns glow; a sign is only lit faintly (a pale sign glowing like a lightbox went white)
    assert kit["night_lanterns"] > 0.3 and 0 < kit["night_sign"] < kit["night_lanterns"]
    assert kit["pane_values"] > 6          # every pane its own number: some lit, some not
    assert kit["night_exposure"] > 0


def test_fog_is_one_volume_thickened_then_cleared(kit):
    ok(kit, "fog1", "fog2", "fog_off")
    assert kit["fogs"] == ["Jervis Fog"]
    assert abs(kit["fog_env"]["density"] - 0.03 * 1.7) < 1e-4   # the default fog (~100 m visibility), thickened
    assert kit["fogs_after"] == []


def test_rain_wets_and_clearing_dries(kit):
    ok(kit, "rain", "clear")
    assert kit["rain_present"] and kit["wet_rough"][1] > 0.5 and kit["wet_rough"][0] is not None
    assert kit["dry"] == [0.0, True]


def test_water_and_wind_are_retuned_not_stacked(kit):
    ok(kit, "water", "wind")
    assert abs(kit["water_state"]["strength"] - 4.0) < 1e-6 and kit["water_state"]["kind"] == "ripples"
    assert abs(kit["wind_env"] - 1.6) < 1e-6


def test_motion_pauses_and_resumes(kit):
    ok(kit, "pause", "resume")
    assert int(kit["pause"]["result"]) > 0


def test_materials_change_only_on_the_parts_meant(kit):
    ok(kit, "mat")
    m = kit["mat_data"]
    assert m["walls_before"] == m["walls_after"]             # the roof changed, not the walls
    assert m["shop_walls"][0] > 0.5 and m["shop_walls"][1] < 0.3


def test_cameras_move_as_asked_and_never_end_up_inside_anything(kit):
    ok(kit, "cam", "behind", "check_behind", "closer", "check_closer", "cam2", "rename")
    for label in ("check_behind", "check_closer"):
        c = json.loads(kit[label]["result"])
        assert c["inside"] == [] and not c["below_ground"], c
    behind = json.loads(kit["check_behind"]["result"].replace("'", '"'))
    assert behind["location"][1] > 20          # it went round to the far side of the villa (front faces -y)
    assert kit["cam2"]["result"] == "Camera 2" and kit["rename"]["result"] == "Pool Cam"


def test_a_view_renders_and_things_are_seen_through_the_camera(kit):
    ok(kit, "render", "frames")
    assert kit["render_exists"]
    frames = json.loads(kit["frames"]["result"])
    assert "Villa" in frames


def test_every_thing_carries_its_meaning(kit):
    ok(kit, "registry")
    reg = {r["name"]: r for r in json.loads(kit["registry"]["result"])}
    assert reg["Villa"]["kind"] == "villa" and reg["Villa"]["role"] == "the main building"
    assert reg["Villa"]["sid"].startswith("s")


def test_lights_by_meaning_and_moving_with_what_belongs(kit):
    ok(kit, "lights", "move", "plights")
    assert kit["pool_lights"]
    moved = json.loads(kit["move"]["result"])
    assert "Villa" in moved["moved"] and abs(moved["by"][1]) > 4
    assert len(eval(kit["plights"]["result"])) >= 4


def test_rivers_cut_the_ground_cliffs_grow_moss_stones_lie_in_beds_and_places_rebuild(kit):
    # a river below ground level was invisible under an uncut lawn; a forest waterfall's cliff is mossy; a bed of
    # stones is many instanced rocks; a villa rebuilt bigger keeps what it means in the scene
    ok(kit, "river", "falls", "stones", "regrow")
    assert kit["ground_over_river"] is False
    assert any("moss" in m.lower() for m in kit["falls_mats"])
    assert kit["stone_count"] == 20
    assert kit["regrown"] == [30.0, "villa"]


def test_clouds_are_a_sky_layer_tinted_by_the_hour_and_fog_glows_with_the_sky(kit):
    ok(kit, "clouds", "clouds_sunset", "mist", "clouds_off")
    day, sunset = kit["cloud_day"], kit["cloud_sunset"]
    assert day and sunset and sunset[0] - sunset[2] > day[0] - day[2] + 0.2   # white by day, warm at sunset
    assert kit["cloud_env"] == 0.4
    assert kit["mist_glow"] > 0   # lit by the sky: mist at sunset was a dark band
    assert kit["clouds_after"] == [0, True]   # cleared, the sky still wired in
