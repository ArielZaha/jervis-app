"""The world round what was asked for (environment.py), no Blender: which place a request is (its own words first,
then what was built), the steps that make it — ground, planting kept off the subject, its entrance and the view,
what stands with it (a street, a shore, a drive), sky, light, air and a breeze — and nothing for a request that
opts out or adds to a scene that already has its world. And how a render of it is judged."""
import re

import pytest

import environment


def o(name, mn, mx, parent=None, type_="MESH", **kw):
    return dict(name=name, type=type_, min=list(mn), max=list(mx), parent=parent,
                size=[b - a for a, b in zip(mn, mx)], location=list(mn), **kw)


def house(name="Villa", kind="house", x=0.0, y=0.0, w=12.0, d=9.0):
    a = dict(asset=name, asset_type=kind)
    hx, hy = w / 2, d / 2
    return [o(name, (x, y, 0), (x, y, 0), type_="EMPTY", rotation=[0, 0, 0], **a),
            o(f"{name} Walls", (x - hx, y - hy, 0.2), (x + hx, y + hy, 6.5), name, **a),
            o(f"{name} Roof", (x - hx - 0.2, y - hy - 0.2, 6.4), (x + hx + 0.2, y + hy + 0.2, 7.5), name, **a),
            o(f"{name} Door", (x - 0.5, y - hy - 0.1, 0.3), (x + 0.5, y - hy + 0.1, 2.4), name, **a)]


def thing(name, kind, mn, mx):
    a = dict(asset=name, asset_type=kind)
    return [o(name, mn, mn, type_="EMPTY", **a), o(f"{name} Body", mn, mx, name, **a)]


@pytest.mark.parametrize("goal,objs,setting", [
    ("Make a villa", house(), "residential"),
    ("Build a modern house with a big garden", house("House"), "residential"),
    ("A cabin in the woods", house("Cabin"), "forest"),
    ("A villa by the sea", house(), "coastal"),
    ("Make a coffee shop", thing("Shop", "storefront", (-4, -4.5, 0), (4, 4.5, 8)), "urban"),
    ("Create a waterfall", thing("Waterfall", "waterfall", (-15, -3, 0), (15, 3, 20)), "waterfall"),
    ("Make a tropical island", thing("Island", "island", (-15, -15, -2), (15, 15, 4)), "island"),
    ("Put a sofa", thing("Sofa", "sofa", (-1, -0.5, 0), (1, 0.5, 0.9)), "interior"),
    ("A lighthouse", thing("Lighthouse", None, (-2, -2, 0), (2, 2, 20)), "coastal"),
    ("A stone tower", thing("Tower", None, (-2, -2, 0), (2, 2, 20)), "meadow"),
    ("A barn on a farm", house("Barn"), "rural"),
    ("A cabin in the mountains", house("Cabin"), "mountain"),
])
def test_the_place_comes_from_the_request_then_from_what_was_built(goal, objs, setting):
    subjects = environment.subjects_of({"objects": objs}, before=set())
    assert environment.classify(goal, subjects) == setting


def plan_for(goal, objs, before=None, extra=()):
    return environment.plan(goal, {"objects": list(objs) + list(extra)}, before if before is not None else
                            {x["name"] for x in extra})


def forests(code):
    """[(name, kind, rect, avoid rects)] of every forest() call in the plan."""
    out = []
    for m in re.finditer(r"forest\('([^']+)', at=\(([-\d.]+), ([-\d.]+), 0\), width=([\d.]+), depth=([\d.]+), "
                         r"count=(\d+), kind='([^']+)'.*?avoid=\[(.*?)\]\)", code):
        x, y, w, d = map(float, m.group(2, 3, 4, 5))
        avoid = [tuple(map(float, a.split(","))) for a in re.findall(r"\(([^()]*)\)", m.group(8))]
        out.append((m.group(1), m.group(7), (x - w / 2, y - d / 2, x + w / 2, y + d / 2), avoid))
    return out


def test_a_villa_gets_its_whole_world_and_nothing_grows_in_it():
    p = plan_for("Make a villa", house())
    code = "\n".join(s["code"] for s in p["steps"])
    assert p["setting"] == "residential"
    assert "ground('Ground'" in code and "kind='lawn'" in code and "patches(" in code
    assert "walkway('Driveway', 'Villa'" in code
    assert "time_of_day('day')" in code and "sky_clouds(" in code and "fog('haze'" in code and "wind(" in code
    assert "hills(" in code and "Treeline" in code
    villa = (-6.0, -4.5, 6.0, 4.5)
    trees = [f for f in forests(code) if f[1] in ("mixed", "pine")]
    assert trees
    for name, kind, rect, avoid in forests(code):
        # every planting keeps off the villa: its area doesn't cover it, or it is told to avoid it
        covers = rect[0] < villa[2] and rect[2] > villa[0] and rect[1] < villa[3] and rect[3] > villa[1]
        assert not covers or any(a[0] <= villa[0] and a[2] >= villa[2] and a[1] <= villa[1] and a[3] >= villa[3]
                                 for a in avoid), name
    for name, kind, rect, avoid in trees:   # trees never stand between the camera's side (-y) and the villa
        if name != "Treeline":
            assert rect[1] >= -4.5 - 1e-6 - 30 and (rect[3] <= 4.5 + 1e-6 or rect[1] > -4.5 or
                                                    any(a[1] <= -5 and a[3] >= -5 for a in avoid)), name


def test_a_shop_stands_in_a_street_with_neighbours_and_lamps():
    shop = thing("Shop", "storefront", (-4, -4.5, 0), (4, 4.5, 8))
    code = "\n".join(s["code"] for s in plan_for("Make a little bakery", shop)["steps"])
    assert "road('Street'" in code and code.count("storefront('Neighbour Shop") == 4
    assert code.count("street_lamp(") >= 3 and "car('Parked Car'" in code and "kind='paving'" in code
    # the neighbours stand beside it, not in it
    for m in re.finditer(r"storefront\('Neighbour Shop[^']*', at=\(([-\d.]+), ([-\d.]+), 0\), width=([\d.]+)", code):
        x, w = float(m.group(1)), float(m.group(3))
        assert x - w / 2 >= 4.0 or x + w / 2 <= -4.0


def test_a_waterfall_stands_in_its_forest_with_a_stream_and_mist():
    falls = thing("Waterfall", "waterfall", (-15, -3, 0), (15, 3, 20))
    code = "\n".join(s["code"] for s in plan_for("Create a waterfall", falls)["steps"])
    assert "Trees Above" in code and "Trees Left" in code and "Trees Right" in code
    assert "river('Stream'" in code and "fog('mist'" in code and "Mossy Rocks" in code
    assert "kind='forest floor'" in code


def test_a_beach_scene_has_its_shore_palms_and_sea_and_no_extra_ground():
    hut = house("Beach Hut", w=5, d=4)
    code = "\n".join(s["code"] for s in plan_for("A beach hut on a tropical beach", hut)["steps"])
    assert "shore('Beach'" in code and "kind='palm'" in code and "ground('Ground'" not in code


def test_furniture_alone_is_put_in_a_room():
    sofa = thing("Sofa", "sofa", (-1, -0.5, 0), (1, 0.5, 0.9))
    p = plan_for("Make a sofa", sofa)
    code = "\n".join(s["code"] for s in p["steps"])
    assert "room('Room'" in code and "sky_clouds" not in code and "ground(" not in code


@pytest.mark.parametrize("goal", ["Make just a villa", "A villa on a plain plane", "A villa with no background",
                                  "Make a villa on its own"])
def test_a_request_for_the_object_alone_gets_no_world(goal):
    assert plan_for(goal, house()) is None


def test_a_thing_added_to_a_scene_with_its_world_gets_none_of_its_own():
    old = thing("Old Tree", "tree", (20, 20, 0), (22, 22, 7))
    assert plan_for("Make a villa", house(), extra=old) is None
    # unless the request is for a scene
    assert plan_for("Make a villa scene", house(), extra=old) is not None


def test_the_same_request_builds_the_same_world():
    a = plan_for("Make a villa", house())
    b = plan_for("Make a villa", house())
    assert [s["code"] for s in a["steps"]] == [s["code"] for s in b["steps"]]


@pytest.mark.parametrize("goal,look,extra", [("A villa at sunset", "sunset", "sky_clouds"),
                                             ("A villa at night", "night", None),
                                             ("A villa on a rainy day", "day", "weather('rain')"),
                                             ("A misty forest cabin", "day", "fog('mist'")])
def test_the_time_and_weather_asked_for_light_it(goal, look, extra):
    code = "\n".join(s["code"] for s in plan_for(goal, house())["steps"])
    assert f"time_of_day({look!r})" in code
    if extra:
        assert extra in code
    if look == "night":
        assert "sky_clouds" not in code


@pytest.mark.parametrize("m,problem", [
    ({"frame": (0.3, 0.3, 0.7, 0.7, 1.0), "sky": 0.3, "brightness": 0.5}, None),
    ({"frame": (0.0, 0.2, 0.6, 0.8, 0.7), "sky": 0.3, "brightness": 0.5}, "cut off"),
    ({"frame": (0.45, 0.45, 0.55, 0.55, 1.0), "sky": 0.3, "brightness": 0.5}, "lost"),
    ({"frame": (0.05, 0.1, 0.95, 0.9, 1.0), "sky": 0.3, "brightness": 0.5}, "fills"),
    ({"frame": (0.3, 0.3, 0.7, 0.7, 1.0), "sky": 0.02, "brightness": 0.5}, "no sky"),
    ({"frame": (0.3, 0.3, 0.7, 0.7, 1.0), "sky": 0.3, "brightness": 0.1}, "dark"),
    ({"frame": None, "sky": 0.3, "brightness": 0.5}, "isn't in view"),
])
def test_a_render_is_judged_by_what_it_shows(m, problem):
    found = environment.assess(m, "residential")
    if problem is None:
        assert found == []
    else:
        assert any(problem in p for p, _ in found), found


def test_blenders_startup_cube_doesnt_stop_the_world_but_nothing_grows_on_it():
    cube = [o("Cube", (19, -1, -1), (21, 1, 1))]
    cube[0]["min"], cube[0]["max"] = [-1, -1, -1], [1, 1, 1]
    p = plan_for("Make a villa", house(x=20.0), extra=cube)
    assert p is not None
    for name, kind, rect, avoid in forests("\n".join(s["code"] for s in p["steps"])):
        covers = rect[0] < 1 and rect[2] > -1 and rect[1] < 1 and rect[3] > -1
        assert not covers or any(a[0] <= -1 and a[2] >= 1 and a[1] <= -1 and a[3] >= 1 for a in avoid), name


def test_a_place_asked_for_is_its_own_subject_and_isnt_built_twice():
    island = [o("Island", (0, 0, 0), (0, 0, 0), type_="EMPTY", asset="Island", asset_type="island"),
              o("Island Terrain", (-18, -18, -2), (18, 18, 4), "Island", asset="Island", asset_type="island")]
    p = plan_for("Make a tropical island", island)
    assert p is not None and p["setting"] == "island" and p["frame_box"] == ([-18, -18, -2], [18, 18, 4])
    code = "\n".join(s["code"] for s in p["steps"])
    assert "Far Islands" in code and "shore(" not in code and "sky_clouds(" in code


@pytest.mark.parametrize("what,want", [
    ("a little bakery", ("storefront", "bakery")), ("a red coffee shop", ("storefront", "coffee shop")),
    ("a modern villa", ("villa", "villa")), ("a beach at sunset", ("shore", "beach")),
    ("a beach hut", None), ("a bar stool", None), ("a villa with a pool", None), ("two shops", None),
    ("a tropical island", None),
])
def test_a_place_asked_for_by_name_is_its_finished_builder(what, want):
    # never a blockout of boxes: a shop is a storefront(), a villa a villa(), a beach a shore()
    import agent_blender
    assert agent_blender.place_request(what) == want


def test_the_place_plan_builds_it_with_options_from_the_words():
    import agent_blender
    adapter = agent_blender.BlenderAdapter(bridge=None)
    plan = adapter._place_build_plan("Make a little red bakery", "a little red bakery", {"objects": []})
    code = plan["steps"][0]["code"]
    assert code.startswith("storefront('Bakery', at=(X, Y, 0)") and "color='red'" in code and "floors=1" in code
    assert "tag_semantic('Bakery', 'shop', role='the main building'" in code
