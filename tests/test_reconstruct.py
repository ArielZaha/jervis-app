"""A VisualScene -> a verified build plan (reconstruct.py): which requests are a rebuild, finished assets chosen
and configured from what was seen, a layout made consistent before anything is built (two overlapping buildings
are one complex; a pool in front of a house stays in front), the camera set up like the photo's, the light and the
justified behaviours, every object tagged with its meaning."""
import pytest
from PIL import Image

import reconstruct
import visual_scene as vs
from test_visual_scene import FakeAsker, villa_picture
from visual_scene import val


@pytest.mark.parametrize("text,yes", [
    ("Recreate this image in Blender", True), ("turn this photo into a 3D scene", True),
    ("build what's in the picture", True), ("make this in 3D", True), ("rebuild the attached image", True),
    ("create a house", False), ("add a pool", False), ("make a cinematic shot", False),
    ("describe this image", False),
])
def test_which_requests_are_a_rebuild(text, yes):
    assert reconstruct.is_reconstruction_request(text) is yes


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    path = tmp_path_factory.mktemp("rc") / "villa.png"
    villa_picture().save(path)
    return vs.analyze(str(path), asker=FakeAsker())


def codes(plan):
    return "\n".join(s["code"] for s in plan["steps"])


def test_the_plan_builds_in_dependency_order_with_checks(scene):
    plan = reconstruct.build_plan(scene, {"objects": []})
    titles = [s["title"] for s in plan["steps"]]
    assert titles[0] == "Lay the ground"
    assert titles.index("Build the main structures") < titles.index("Add the water") < \
        titles.index("Set up the camera like the photo's") < titles.index("Bring it to life")
    for s in plan["steps"]:
        if s["title"] not in ("Add the distance",):
            assert s["checks"], s["title"]


def test_assets_are_chosen_and_configured_from_what_was_seen(scene):
    text = codes(reconstruct.build_plan(scene, {"objects": []}))
    assert "villa('Villa'" in text and "floors=2" in text          # modern, half glass, flat roof: a villa
    assert "pool('Swimming Pool'" in text
    assert text.count("tree(") == 2 and "kind='palm'" in text
    assert "car(" not in text                                     # the denied car is not built


def test_every_object_is_tagged_with_its_meaning_and_its_element(scene):
    plan = reconstruct.build_plan(scene, {"objects": []})
    text = codes(plan)
    for eid, name in plan["built"].items():
        assert f"tag_semantic({name!r}" in text
    assert "role='the main building'" in text


def test_the_camera_matches_the_photo_and_the_light_its_time(scene):
    text = codes(reconstruct.build_plan(scene, {"objects": []}))
    cam = scene["camera"]
    assert f"height={val(cam['height_m']):.2f}" in text and f"pitch={val(cam['pitch_deg']):.2f}" in text
    assert f"time_of_day({val(scene['environment']['time_of_day'])!r}" in text
    assert "sun_side='left'" in text


def test_only_justified_behaviours_are_added(scene):
    plan = reconstruct.build_plan(scene, {"objects": []})
    text = codes(plan)
    assert "animate_water('Swimming Pool', 'ripples'" in text
    assert "sway(" in text                     # wind was seen
    assert "fog(" not in text and "weather(" not in text   # clear air, clear weather: nothing invented
    assert plan["behaviours"]


def test_a_rebuild_goes_beside_what_is_already_there(scene):
    plan = reconstruct.build_plan(scene, {"objects": []}, offset=(200.0, 0.0))
    assert "camera_match('Camera'" in codes(plan) and "at=(200.00, 0.00)" in codes(plan)


def element(eid, kind, category, x, y, w, d, h=5.0, **kw):
    return dict({"id": eid, "kind": kind, "category": category, "tags": [], "label": kind, "area": 0.1,
                 "priority": "high", "details": {}, "measured": {}, "box": (0, 0, 1, 1),
                 "position": vs.F([x, y, 0.0]), "size": vs.F([w, d, h])}, **kw)


def test_two_overlapping_buildings_are_one_complex():
    a = element("e1", "house", "building", 0, 50, 30, 18)
    b = element("e2", "house", "building", 15, 52, 20, 15)
    reconstruct.resolve_layout([a, b])
    assert a["wings"] == 2 and b["merged_into"] == "e1" and b["category"] == "part"
    x, w = val(a["position"])[0], val(a["size"])[0]
    assert x - w / 2 <= -15 + 1e-6 and x + w / 2 >= 25 - 1e-6


def test_a_pool_in_front_of_a_house_stays_in_front_of_it():
    house = element("e1", "house", "building", 0, 50, 30, 18)    # front at y=41
    pool = element("e2", "swimming pool", "sunken", 5, 42, 14, 7)  # near edge 38.5: in front, overlapping
    reconstruct.resolve_layout([house, pool])
    pool_far = val(pool["position"])[1] + val(pool["size"])[1] / 2
    house_front = val(house["position"])[1] - val(house["size"])[1] / 2
    assert pool_far <= house_front + 0.05


def test_small_things_standing_in_each_other_are_set_apart():
    a = element("e1", "umbrella", "outdoor", 0, 20, 2.5, 2.5)
    b = element("e2", "umbrella", "outdoor", 1, 20, 2.5, 2.5)
    reconstruct.resolve_layout([a, b])
    gap = abs(val(b["position"])[0] - val(a["position"])[0])
    assert gap >= 2.5


@pytest.mark.parametrize("kind,details,builder,word", [
    ("shop", {"floors": vs.F(2), "facade_material": vs.F("wood"), "awning": vs.F(False)}, "storefront", "shop"),
    ("car", {"color": vs.F("red"), "facing": vs.F("left")}, "car", "car"),
    ("tree", {"type": vs.F("deciduous"), "count": vs.F(12)}, "forest", "forest"),
    ("bush", {}, "bush", "bush"),
    ("waterfall", {}, "waterfall", "waterfall"),
    ("street lamp", {}, "street_lamp", "street lamp"),
    ("sofa", {"color": vs.F("grey")}, "sofa", "sofa"),
])
def test_kinds_become_the_right_finished_assets(kind, details, builder, word):
    e = element("e1", kind, "outdoor", 0, 10, 3, 2, details=details)
    got = reconstruct.asset_for(e, {"environment": {"view_of_main_subject": vs.F("front")}}, {})
    assert got[0] == builder and got[2] == word
    if kind == "car":
        assert got[1]["color"] == "red" and got[1]["rotation"] == 180


def test_a_band_of_planting_becomes_a_field_of_shrubs():
    e = element("e1", "bush", "outdoor", 0, 8, 40, 10, area=0.3)
    e["area"] = 0.3
    builder, kw, _ = reconstruct.asset_for(e, {"environment": {}}, {})
    assert builder == "forest" and kw["kind"] == "shrubs" and kw["count"] > 20


def test_people_and_parts_are_never_built_on_their_own():
    e = element("e1", "scooter", "outdoor", 0, 10, 2, 1)
    assert reconstruct.asset_for(e, {"environment": {}}, {}) is None


def beach_scene():
    env = {"scene_type": vs.F("landscape"), "setting": vs.F("coastal"), "time_of_day": vs.F("day"),
           "weather": vs.F("clear"), "wind": vs.F("none"), "atmosphere": vs.F("clear"), "ground": vs.F(["sand"]),
           "water": vs.F(["ocean"]), "view_of_main_subject": vs.F("front")}
    els = [element("e1", "ocean", "ground", 0, 135, 200, 262, 0),
           element("e2", "palm tree", "outdoor", -1.3, 4.8, 2.2, 3, 8, details={"leaning": vs.F("strongly")}),
           element("e3", "palm tree", "outdoor", 4.7, 9.2, 6, 6, 8),
           element("e4", "house", "building", 36, 69, 6.4, 7.2, 5.6, area=0.0005, depth_layer="background")]
    els[3]["area"] = 0.0005
    els[3]["depth_layer"] = "background"
    for e in els:
        e["tags"] = sorted(__import__("semantics").tags(e["kind"]))
    return {"environment": env, "elements": els, "lighting": {"sun_side": vs.F("not visible")},
            "camera": {"height_m": vs.F(1.6), "pitch_deg": vs.F(0.0), "lens_mm": vs.F(28.0), "hfov": vs.F(65.0),
                       "vfov": 40.0},
            "semantics": {"behaviours": []}, "unknowns": []}


def test_a_beach_keeps_the_camera_and_the_palms_on_dry_sand():
    text = codes(reconstruct.build_plan(beach_scene(), {"objects": []}))
    import re
    y = float(re.search(r"shore\('Beach', at=\(0\.00, ([-\d.]+)", text).group(1))
    assert y + 2.5 >= 9.2 and y + 2.5 >= 6.0   # the waterline lies beyond the camera and at the palms' feet
    assert "lean=28" in text             # the palm the photo shows bent over the beach leans


def test_a_speck_on_the_horizon_across_the_water_is_a_small_house_on_land():
    text = codes(reconstruct.build_plan(beach_scene(), {"objects": []}))
    assert "floors=1" in text and "ground('House Shore'" in text


def test_a_room_is_deep_and_wide_enough_for_the_furniture_placed_in_it():
    env = {"scene_type": vs.F("interior"), "setting": vs.F("residential"), "time_of_day": vs.F("day"),
           "weather": vs.F("clear"), "wind": vs.F("none"), "atmosphere": vs.F("clear"), "ground": vs.F([]),
           "water": vs.F([]), "view_of_main_subject": vs.F("front")}
    room = element("room", "room", "building", 0, 0, 0, 0, details={"depth_m": vs.F(4.0), "width_m": vs.F(3.5)})
    del room["position"]
    sofa = element("e1", "sofa", "furniture", 2.4, 5.2, 2.2, 0.9, 0.8)
    scene = {"environment": env, "elements": [room, sofa], "lighting": {"sun_side": vs.F("not visible")},
             "camera": {"height_m": vs.F(1.4), "pitch_deg": vs.F(0.0), "lens_mm": vs.F(24.0), "hfov": vs.F(74.0),
                        "vfov": 50.0},
             "semantics": {"behaviours": []}, "unknowns": []}
    import re
    m = re.search(r"room\('Room', at=\(([-\d.]+), ([-\d.]+), 0\), width=([\d.]+), depth=([\d.]+)",
                  codes(reconstruct.build_plan(scene, {"objects": []})))
    x, y, w, d = map(float, m.groups())
    assert y + d / 2 >= 5.2 + 0.45 + 0.3          # the back wall lies behind the sofa
    assert x + w / 2 >= 2.4 + 1.1                  # and the side wall beside it
