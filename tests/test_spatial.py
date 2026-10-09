"""Spatial reasoning (spatial.py) on hand-made scene states: what the things are, where buildings face, what "beside",
"in front of", "behind" mean in metres, free spots, path routing, and the checks that catch a pool inside a villa,
things standing inside each other, sunk or disconnected things — each with its repair. No Blender."""
import pytest

import spatial


def o(name, mn, mx, parent=None, type_="MESH", **kw):
    return dict(name=name, type=type_, min=list(mn), max=list(mx), parent=parent,
                size=[b - a for a, b in zip(mn, mx)], location=list(mn), **kw)


def villa(name="Villa", x=0.0, y=0.0, rotation=0.0, w=12.0, d=9.0):
    """A finished house asset: front (door, steps, its own stepping-stone path) toward -y unless rotated."""
    hx, hy = w / 2, d / 2
    a = dict(asset=name, asset_type="house")
    return [o(name, (x, y, 0), (x, y, 0), type_="EMPTY", rotation=[0, 0, rotation], **a),
            o(f"{name} Walls", (x - hx, y - hy, 0.25), (x + hx, y + hy, 6.5), name, **a),
            o(f"{name} Roof", (x - hx - 0.2, y - hy - 0.2, 6.4), (x + hx + 0.2, y + hy + 0.2, 6.8), name, **a),
            o(f"{name} Floors", (x - hx + 0.3, y - hy + 0.3, 0.25), (x + hx - 0.3, y + hy - 0.3, 0.35), name, **a),
            o(f"{name} Door", (x - 0.5, y - hy - 0.1, 0.3), (x + 0.5, y - hy + 0.1, 2.4), name, **a),
            o(f"{name} Door Handle", (x + 0.3, y - hy - 0.2, 1.0), (x + 0.35, y - hy - 0.1, 1.1), name, **a),
            o(f"{name} Steps", (x - 0.8, y - hy - 0.9, 0), (x + 0.8, y - hy - 0.1, 0.25), name, **a),
            o(f"{name} Path", (x - 0.5, y - hy - 5.0, 0), (x + 0.5, y - hy - 1.0, 0.05), name, **a)]


def pool_inside(name="Pool", x=0.0, y=0.0):
    return [o(name, (x, y, 0), (x, y, 0), type_="EMPTY"),
            o(f"{name} Water", (x - 4, y - 2, -1.5), (x + 4, y + 2, 0.05), name)]


def names(objs):
    return {x["name"] for x in objs}


def thing(ts, name):
    return next(t for t in ts if t["name"] == name)


# ---------- what's in the scene ----------

def test_things_group_assemblies_assets_and_loose_parts():
    state = {"objects": villa() + pool_inside(x=30) + [o("Bench Seat", (40, 0, 0.45), (41.5, 0.4, 0.5)),
                                                         o("Bench Leg 1", (40, 0, 0), (40.1, 0.1, 0.45)),
                                                         o("Camera", (5, 5, 5), (5, 5, 5), type_="CAMERA")]}
    ts = {t["name"]: t for t in spatial.things(state)}
    assert set(ts) == {"Villa", "Pool", "Bench"}
    assert ts["Villa"]["category"] == "building" and ts["Pool"]["category"] == "sunken"
    assert ts["Bench"]["category"] == "furniture"
    assert len(ts["Bench"]["names"]) == 2


@pytest.mark.parametrize("name,category", [
    ("Villa", "building"), ("House Path", "path"), ("Tree House", "building"), ("Swimming Pool 2", "sunken"),
    ("Palm Tree 3", "outdoor"), ("Lamp Post", "outdoor"), ("Sofa", "furniture"), ("Patio", "surface"),
    ("Island", "ground"), ("Robot", "object"), ("Driveway", "path"), ("Garden Shed", "building")])
def test_categories_come_from_the_head_noun(name, category):
    assert spatial.category_of(name) == category


def test_a_building_is_recognised_by_walls_and_roof_whatever_its_name():
    state = {"objects": [o("Thing Walls", (0, 0, 0), (4, 4, 3)), o("Thing Roof", (0, 0, 3), (4, 4, 4))]}
    assert spatial.things(state)[0]["category"] == "building"


def test_a_house_core_footprint_leaves_out_its_path_and_steps():
    t = spatial.things({"objects": villa()})[0]
    assert t["core"] == (-6.2, -4.7, 6.2, 4.7)           # walls + roof overhang
    assert t["rect"][1] < -9                              # the whole thing reaches down its path
    assert t["door"] == (0.0, -4.5)


@pytest.mark.parametrize("rotation,front", [(0, (0.0, -1.0)), (90, (1.0, 0.0)), (180, (0.0, 1.0)),
                                            (-90, (-1.0, 0.0))])
def test_a_rotated_house_faces_where_its_rotation_says(rotation, front):
    t = spatial.things({"objects": villa(rotation=rotation)})[0]
    assert t["front"] == front


def test_without_a_rotation_the_door_says_where_the_front_is():
    objs = [o("Shed Walls", (0, 0, 0), (3, 3, 2.5)), o("Shed Roof", (0, 0, 2.5), (3, 3, 3.2)),
            o("Shed Door", (2.9, 1, 0), (3.05, 2, 2))]       # the door is in the +x wall
    t = spatial.things({"objects": objs})[0]
    assert t["front"] == (1.0, 0.0)
    ex, ey = spatial.entrance(t)
    assert ex > 3 and 1 <= ey <= 2


def test_the_ground_floor_is_the_floor_slab_not_the_foundation():
    t = spatial.things({"objects": villa()})[0]
    assert spatial.floor_level(t) == pytest.approx(0.35)


def test_new_things_are_told_apart_from_what_was_there():
    state = {"objects": villa() + pool_inside()}
    ts = {t["name"]: t for t in spatial.things(state, before=names(villa()))}
    assert ts["Pool"]["new"] and not ts["Villa"]["new"]


def test_objects_with_broken_bounds_are_ignored():
    state = {"objects": villa() + [o("Leg", (0, 0, float("nan")), (1, 1, 1))]}
    assert [t["name"] for t in spatial.things(state)] == ["Villa"]


# ---------- placement ----------

@pytest.mark.parametrize("relation,side", [("beside", "right"), ("next to", "right"), ("in front of", "front"),
                                           ("behind", "back"), ("left of", "left"), ("to the right of", "right"),
                                           ("near", "right")])
def test_a_pool_placed_by_a_villa_is_always_outside_it_on_the_side_asked(relation, side):
    ts = spatial.things({"objects": villa()})
    v = ts[0]
    spot = spatial.place_relative(v, relation, (11, 7), ts, "sunken")
    assert spot["side"] == side
    assert spatial.overlap_depth(spot["rect"], v["core"]) <= 0          # never inside the footprint
    assert spatial.overlap_depth(spot["rect"], spatial.entrance_zone(v)) <= 0   # the entrance stays free
    for r in v["side_parts"]:
        assert spatial.overlap_depth(spot["rect"], r) <= 0                # nor on its path


def test_beside_turns_a_long_pool_to_run_along_the_facade():
    ts = spatial.things({"objects": villa()})
    spot = spatial.place_relative(ts[0], "beside", (11, 7), ts, "sunken")
    assert spot["rotation"] == 90                       # right side of the house: the long side runs along y
    assert spot["rect"][3] - spot["rect"][1] > spot["rect"][2] - spot["rect"][0]


def test_relations_follow_a_rotated_house():
    ts = spatial.things({"objects": villa(rotation=90)})   # front faces +x
    spot = spatial.place_relative(ts[0], "in front of", (3, 3), ts, "outdoor")
    assert spot["x"] > ts[0]["core"][2]


def test_placement_avoids_whatever_else_is_there():
    objs = villa() + [o("Garage Walls", (8, -5, 0), (14, 5, 3)), o("Garage Roof", (8, -5, 3), (14, 5, 3.5))]
    ts = spatial.things({"objects": objs})
    spot = spatial.place_relative(thing(ts, "Villa"), "beside", (11, 7), ts, "sunken")
    assert spot["side"] == "left" or spot["rect"][0] > 14     # the right side is taken by the garage
    for t in ts:
        assert spatial.overlap_depth(spot["rect"], t["outer"]) <= 0


def test_two_trees_behind_a_house_stand_side_by_side_not_in_a_queue():
    ts = spatial.things({"objects": villa()})
    v = ts[0]
    first = spatial.place_relative(v, "behind", (4.5, 4.5), ts, "outdoor")
    ts2 = ts + [spatial.virtual_thing("Tree 1", first["rect"], "outdoor")]
    second = spatial.place_relative(v, "behind", (4.5, 4.5), ts2, "outdoor")
    assert abs(first["y"] - second["y"]) < 1.0 and abs(first["x"] - second["x"]) > 4.5
    for spot in (first, second):
        t = spatial.virtual_thing("T", spot["rect"], "outdoor")
        assert spatial.check_relation(t, "behind", v)[0]


def test_a_spot_inside_a_house_is_on_its_floor_and_clear_of_the_walls():
    ts = spatial.things({"objects": villa()})
    spot = spatial.place_relative(ts[0], "inside", (2.2, 0.95), ts, "furniture")
    assert spot["z"] == pytest.approx(0.35)
    core = ts[0]["core"]
    assert core[0] < spot["rect"][0] and spot["rect"][2] < core[2]


def test_a_free_spot_is_found_near_where_it_was_wanted():
    ts = spatial.things({"objects": villa()})
    spot = spatial.place_free(0, 0, (2, 2), ts)       # the middle of the villa is taken
    assert all(spatial.overlap_depth(spot["rect"], r) <= 0 for t in ts for r in spatial.footprints(t))


def test_size_estimates_for_planning():
    assert spatial.estimate_size("a swimming pool") == spatial.FOOTPRINTS["pool"]
    assert spatial.estimate_size("Oak Tree 2") == spatial.FOOTPRINTS["tree"]     # the head noun decides
    assert spatial.estimate_size("Pine 2") == spatial.FOOTPRINTS["pine"]
    assert spatial.estimate_size("something odd", default=(1, 1)) == (1, 1)


# ---------- what a request says ----------

def test_the_villa_request_is_understood_spatially():
    rels = spatial.parse_relations("a modern villa with a swimming pool beside it and a path from the entrance to the "
                                   "pool")
    assert {"subject": "pool", "relation": "beside", "anchor": "villa", "to": None} in rels
    assert {"subject": "path", "relation": "connects", "anchor": "entrance", "to": "pool"} in rels


@pytest.mark.parametrize("text,expected", [
    ("put a bench next to the pool", ("bench", "beside", "pool")),
    ("a tree in front of the house", ("tree", "front", "house")),
    ("a fountain behind the villa", ("fountain", "behind", "villa")),
    ("a garage to the left of the house", ("garage", "left", "house")),
    ("trees around the house", ("tree", "near", "house")),
    ("a lamp on the table", ("lamp", "on", "table")),
    ("a sofa in the living room", ("sofa", "inside", "building")),
    ("add a lamp post by the path", ("lamppost", "beside", "path")),
])
def test_relations_in_requests(text, expected):
    rel = spatial.parse_relations(text)[0]
    assert (rel["subject"], rel["relation"], rel["anchor"]) == expected


@pytest.mark.parametrize("text,ends", [("a path to the pool", ("entrance", "pool")),
                                       ("a path between the house and the garage", ("house", "garage")),
                                       ("a walkway connecting the shed and the pool", ("shed", "pool"))])
def test_paths_in_requests(text, ends):
    rel = spatial.parse_relations(text)[0]
    assert rel["relation"] == "connects" and (rel["anchor"], rel["to"]) == ends


@pytest.mark.parametrize("text", ["a house in the forest", "build it in red", "a path next to the villa"])
def test_no_false_relations(text):
    assert all(r["relation"] != "connects" and r["relation"] != "inside" for r in spatial.parse_relations(text))


# ---------- checking relations ----------

def test_a_pool_inside_the_villa_is_not_beside_it():
    ts = spatial.things({"objects": villa() + pool_inside()})
    ok, why = spatial.check_relation(thing(ts, "Pool"), "beside", thing(ts, "Villa"))
    assert not ok and "footprint" in why


def test_a_pool_just_outside_is_beside_but_one_far_away_is_not():
    near = spatial.things({"objects": villa() + pool_inside(x=12)})
    assert spatial.check_relation(thing(near, "Pool"), "beside", thing(near, "Villa"))[0]
    far = spatial.things({"objects": villa() + pool_inside(x=40)})
    ok, why = spatial.check_relation(thing(far, "Pool"), "beside", thing(far, "Villa"))
    assert not ok and "too far" in why


def test_in_front_and_behind_follow_the_buildings_front():
    front = spatial.things({"objects": villa() + pool_inside(y=-14)})
    assert spatial.check_relation(thing(front, "Pool"), "front", thing(front, "Villa"))[0]
    assert not spatial.check_relation(thing(front, "Pool"), "behind", thing(front, "Villa"))[0]
    turned = spatial.things({"objects": villa(rotation=180) + pool_inside(y=-14)})   # now that's its back
    assert spatial.check_relation(thing(turned, "Pool"), "behind", thing(turned, "Villa"))[0]


# ---------- paths ----------

def path_parts(name, rects, parent=None):
    return [o(f"{name} Stone {i + 1}", (r[0], r[1], 0), (r[2], r[3], 0.05), parent) for i, r in enumerate(rects)]


def test_a_path_from_the_door_to_the_pool_connects_them():
    objs = villa() + pool_inside(x=14) + path_parts("Walk", [(-0.5, -6.5, 0.5, -5.6), (-0.5, -7.2, 9.6, -6.4),
                                                             (9.1, -7.0, 10.1, -2.0)])
    ts = spatial.things({"objects": objs})
    ok, problems = spatial.check_path(thing(ts, "Walk"), thing(ts, "Villa"), thing(ts, "Pool"), ts)
    assert ok, problems


def test_a_path_that_stops_short_or_goes_through_the_house_is_caught():
    short = spatial.things({"objects": villa() + pool_inside(x=14) + path_parts("Walk", [(-0.5, -6.5, 0.5, -5.6)])})
    ok, problems = spatial.check_path(thing(short, "Walk"), thing(short, "Villa"), thing(short, "Pool"), short)
    assert not ok and any("doesn't reach 'Pool'" in p for p in problems)
    through = spatial.things({"objects": villa() + pool_inside(x=14) + path_parts(
        "Walk", [(-0.5, -6.5, 0.5, -5.6), (-0.5, -5.6, 0.5, 0.5), (0, -0.5, 9.9, 0.5)])})
    ok, problems = spatial.check_path(thing(through, "Walk"), thing(through, "Villa"), thing(through, "Pool"), through)
    assert not ok and any("through the building" in p for p in problems)


def test_a_path_with_a_gap_is_caught():
    ts = spatial.things({"objects": villa() + pool_inside(x=14) + path_parts(
        "Walk", [(-0.5, -6.5, 0.5, -5.6), (8.0, -7.0, 9.95, -6.0)])})
    ok, problems = spatial.check_path(thing(ts, "Walk"), thing(ts, "Villa"), thing(ts, "Pool"), ts)
    assert not ok


def test_routing_goes_round_the_building_never_through_it():
    ts = spatial.things({"objects": villa() + pool_inside(y=16)})   # the pool is BEHIND the villa
    v, p = thing(ts, "Villa"), thing(ts, "Pool")
    start, sdir, end, edir = spatial.path_ends(v, p)
    pts = spatial.route(start, end, ts, width=1.2, start_dir=sdir, end_dir=edir)
    assert pts[0] == pytest.approx(spatial.entrance(v)) and pts[-1] == pytest.approx(end)
    assert pts[1][1] < pts[0][1]                                    # leaves the door square-on (toward -y)
    core = spatial.grow(v["core"], 0.5)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        for k in range(21):
            x, y = x0 + (x1 - x0) * k / 20, y0 + (y1 - y0) * k / 20
            assert not (core[0] < x < core[2] and core[1] < y < core[3]), (x, y)


def test_a_route_never_doubles_back_on_itself():
    # a pond right beside the door: "walk straight out, then come back" would make a spike in the path
    objs = villa() + [o("Pond Water", (-6.5, -8.0, -0.5), (-1.6, -4.9, 0.0))]
    ts = spatial.things({"objects": objs})
    v, p = thing(ts, "Villa"), thing(ts, "Pond")
    start, sdir, end, edir = spatial.path_ends(v, p)
    pts = spatial.route(start, end, ts, start_dir=sdir, end_dir=edir)
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        cos = (v1[0] * v2[0] + v1[1] * v2[1]) / ((v1[0] ** 2 + v1[1] ** 2) ** 0.5 * (v2[0] ** 2 + v2[1] ** 2) ** 0.5)
        assert cos > -0.35, pts
    assert pts[0] == pytest.approx(start) and pts[-1] == pytest.approx(end)


def test_new_things_keep_room_to_walk_round_a_building():
    ts = spatial.things({"objects": villa()})
    spot = spatial.place_free(0, -5, (3, 3), ts)
    assert spatial.gap(spot["rect"], thing(ts, "Villa")["outer"]) >= 1.0


def test_two_trees_fit_behind_even_a_narrow_cabin():
    ts = spatial.things({"objects": villa(name="Cabin", w=5.0, d=4.0)})
    cabin = thing(ts, "Cabin")
    first = spatial.place_relative(cabin, "behind", (3.5, 3.5), ts, "outdoor")
    second = spatial.place_relative(cabin, "behind", (3.5, 3.5), ts + [spatial.virtual_thing("T1", first["rect"])],
                                    "outdoor")
    assert abs(first["y"] - second["y"]) < 1.0           # side by side, not one behind the other
    assert spatial.check_relation(spatial.virtual_thing("T2", second["rect"]), "behind", cabin)[0]


def test_routing_fails_honestly_when_walled_in():
    wall = [o("Wall A", (-20, 5, 0), (20, 6, 3)), o("Wall B", (-20, -6, 0), (20, -5, 3)),
            o("Wall C", (-21, -6, 0), (-20, 6, 3)), o("Wall D", (20, -6, 0), (21, 6, 3))]
    ts = spatial.things({"objects": wall})
    with pytest.raises(ValueError, match="no clear way"):
        spatial.route((0, 0), (0, 30), ts)


# ---------- validating what was built, with repairs ----------

def test_validation_moves_a_pool_out_of_the_villa_to_beside_it():
    state = {"objects": villa() + pool_inside()}
    intents = spatial.parse_relations("a modern villa with a swimming pool beside it")
    issues = spatial.validate(state, before=names(villa()), intents=intents)
    assert len(issues) == 1 and issues[0]["kind"] == "relation" and issues[0]["thing"] == "Pool"
    dx, dy = issues[0]["fix"]["move"]
    moved = [dict(x, min=[x["min"][0] + dx, x["min"][1] + dy, x["min"][2]],
                  max=[x["max"][0] + dx, x["max"][1] + dy, x["max"][2]]) if x["name"].startswith("Pool") else x
             for x in state["objects"]]
    assert spatial.validate({"objects": moved}, before=names(villa()), intents=intents) == []


def test_an_outdoor_thing_inside_a_building_is_caught_even_unasked():
    state = {"objects": villa() + [o("Oak Trunk", (1, 1, 0), (1.4, 1.4, 4)), o("Oak Leaves", (-1, -1, 3), (3, 3, 7))]}
    issues = spatial.validate(state, before=names(villa()))
    assert issues[0]["kind"] == "inside_building" and issues[0]["fix"]["move"]


def test_furniture_inside_a_house_is_fine():
    state = {"objects": villa() + [o("Sofa Base", (1, 1, 0.35), (3.2, 2, 0.8))]}
    assert spatial.validate(state, before=names(villa())) == []


def test_an_outdoor_part_built_into_the_building_is_caught():
    state = {"objects": villa() + [o("Villa Pool", (-3, -2, -1.5), (3, 2, 0.05), "Villa")]}
    issues = spatial.validate(state, before=names(villa()))
    assert issues and issues[0]["kind"] == "inside_building" and issues[0]["thing"] == "Villa Pool"


def test_new_things_standing_inside_each_other_are_separated():
    state = {"objects": [o("Fountain Basin", (0, 0, 0), (3, 3, 1)), o("Statue Body", (1, 1, 0), (2.5, 2.5, 2))]}
    issues = spatial.validate(state, before=set())
    assert issues and issues[0]["kind"] == "intersection" and issues[0]["fix"]["move"]


def test_something_on_a_path_is_moved_off_it_not_the_path():
    path = path_parts("Walk", [(0, 0, 10, 1.2)])
    state = {"objects": path + [o("Bench Seat", (4, 0, 0), (5.8, 0.7, 0.9))]}
    issues = spatial.validate(state, before=names(path))
    assert issues and issues[0]["thing"] == "Bench"


def test_a_thing_built_too_low_is_lifted_but_sunken_ones_are_left():
    state = {"objects": [o("Crate Body", (0, 0, -0.4), (1, 1, 0.6))] + pool_inside(x=10)}
    issues = spatial.validate(state, before=set())
    assert [(i["kind"], i["thing"], i["fix"]) for i in issues] == [("below_ground", "Crate", {"lift": 0.4})]


def test_validation_of_a_correct_scene_is_silent():
    state = {"objects": villa() + pool_inside(x=13) + path_parts("Walk", [(-0.5, -6.5, 0.5, -5.6),
                                                                         (-0.5, -7.2, 9.0, -6.4),
                                                                         (8.5, -7.0, 9.6, -1.0)])}
    intents = spatial.parse_relations("a villa with a pool beside it and a path from the entrance to the pool")
    assert spatial.validate(state, before=set(), intents=intents) == []


def test_a_disconnected_new_path_gets_a_reroute_fix():
    state = {"objects": villa() + pool_inside(x=13) + path_parts("Walk", [(20, 20, 21, 21)])}
    intents = [{"subject": "path", "relation": "connects", "anchor": "entrance", "to": "pool"}]
    issues = spatial.validate(state, before=names(villa() + pool_inside(x=13)), intents=intents)
    assert issues[0]["kind"] == "path" and issues[0]["fix"] == {"route": ("Walk", "Villa", "Pool")}


def palm(name, x, y, crown_dx=0.0):
    a = dict(asset=name, asset_type="tree")
    return [o(name, (x, y, 0), (x, y, 0), type_="EMPTY", **a),
            o(f"{name} Trunk", (x - 0.2, y - 0.2, 0), (x + 0.2, y + 0.2, 7.5), name, **a),
            o(f"{name} Fronds", (x + crown_dx - 3, y - 3, 6.5), (x + crown_dx + 3, y + 3, 8.5), name, **a)]


def test_trees_whose_crowns_meet_are_a_grove_not_a_collision():
    # a leaning palm's crown over its neighbour's (the beach photo): their trunks stand 2.5 m apart
    state = {"objects": palm("Palm Tree", -1.3, 4.8, crown_dx=2.5) + palm("Palm Tree 2", 0.2, 6.8)}
    assert [i for i in spatial.validate(state, before=set()) if i["kind"] == "intersection"] == []
    # but two trunks in one spot do clash
    state = {"objects": palm("Palm Tree", 0, 5) + palm("Palm Tree 2", 0.1, 5.1)}
    assert any(i["kind"] == "intersection" for i in spatial.validate(state, before=set()))
