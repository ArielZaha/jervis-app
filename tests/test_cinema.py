"""Cinematic direction (cinema.py) on its own: what requests say about time, cameras, lights and motion; turning it
into a timeline in seconds and frames; easing; camera shots and moves planned on scene geometry (framed, outside
buildings, unblocked); light by time of day; what moves by nature. No Blender."""
import math

import pytest

import cinema
import spatial
from test_spatial import o, pool_inside, villa

BRIEF = ("Create a 10-second cinematic where the camera approaches the villa, the pool lights turn on halfway "
         "through, and the door opens near the end.")


# ---------- time ----------

@pytest.mark.parametrize("text,seconds", [
    ("a 10-second cinematic", 10), ("make it 12 seconds long", 12), ("a 1-minute fly-through", 60),
    ("an animation of 240 frames", 10), ("day to night over 12 seconds", 12), ("a five second clip", 5),
    ("after 3 seconds the door opens", None), ("the lights come on at 4 seconds", None)])
def test_how_long_the_whole_thing_is(text, seconds):
    assert cinema.parse_duration(text, fps=24) == (float(seconds) if seconds else None)


@pytest.mark.parametrize("clause,start,end", [
    ("the door opens near the end", 7.5, None), ("the pool lights turn on halfway through", 5.0, None),
    ("at 3 seconds the car starts", 3.0, None), ("from 2 to 6 seconds the camera orbits", 2.0, 6.0),
    ("in the last 2 seconds it fades", 8.0, 10.0), ("in the first 3 seconds", 0.0, 3.0),
    ("at the start the camera is wide", 0.0, None), ("throughout, the flag waves", 0.0, 10.0),
    ("after 2 seconds the door opens for 3 seconds", 2.0, 5.0), ("at frame 48", 2.0, None)])
def test_when_a_clause_happens(clause, start, end):
    s, e, explicit = cinema.clause_time(clause, 10.0, fps=24)
    assert (s, e, explicit) == (start, end, True)


def test_fps_from_the_request():
    assert cinema.parse_fps("a 10 second video at 30 fps") == 30 and cinema.parse_fps("a video") is None


@pytest.mark.parametrize("kind", ["smooth", "linear", "in", "out", "back", "bounce", "smoother"])
def test_easing_starts_at_zero_and_ends_at_one(kind):
    assert cinema.ease(0, kind) == pytest.approx(0, abs=1e-9) and cinema.ease(1, kind) == pytest.approx(1)
    if kind in ("smooth", "linear", "in", "out", "smoother"):
        values = [cinema.ease(t / 20, kind) for t in range(21)]
        assert values == sorted(values)                      # never goes backwards
    assert cinema.ease(0.5, "in") < 0.5 < cinema.ease(0.5, "out")


@pytest.mark.parametrize("text,ease", [("the door slams open suddenly", "constant"), ("the ball bounces", "bounce"),
                                       ("the car accelerates away", "in"), ("it slows to a stop", "out"),
                                       ("it moves at a steady speed", "linear"), ("the door opens", "smooth")])
def test_easing_from_words(text, ease):
    assert cinema.ease_of(text) == ease


# ---------- direction ----------

def test_the_brief_becomes_a_coordinated_timeline():
    d = cinema.parse_direction(BRIEF, fps=24)
    assert d["duration"] == 10 and d["understood"]
    events, D = cinema.schedule(d)
    got = [(e["kind"], e["move"], e["subject"], e["start"], e["end"]) for e in events]
    assert got == [("camera", "push_in", "villa", 0.0, 10.0), ("lights", "on", "pool", 5.0, 5.8),
                   ("action", "open", "door", 7.5, 9.3)]
    assert [cinema.to_frame(e["start"], 24) for e in events] == [1, 121, 181]


@pytest.mark.parametrize("text,expected", [
    ("make the car drive from the garage to the gate", ("action", "travel", "car", {"from": "garage", "to": "gate"})),
    ("make the tree sway in the wind", ("action", "sway", "tree", {})),
    ("make the door open naturally", ("action", "open", "door", {})),
    ("orbit the camera around the fountain", ("camera", "orbit", "fountain", {"shot": None})),
    ("the camera does a full orbit around the villa", ("camera", "orbit", "villa", {"shot": None, "sweep": 360.0})),
    ("a close-up of the door", ("shot", "close", "door", {})),
    ("an establishing shot of the island", ("shot", "establishing", "island", {})),
    ("the camera pans from the pool to the villa", ("camera", "pan", "pool", {"shot": None, "from": "pool",
                                                                              "to": "villa"})),
    ("the camera tilts up the tower", ("camera", "tilt", "tower", {"shot": None, "direction": "up"})),
    ("the camera follows the car", ("camera", "follow", "car", {"shot": None})),
    ("a slow pull back from the fountain", ("camera", "pull_out", "fountain", {"shot": None})),
    ("spin the statue twice", None),
    ("spin the statue 2 times", ("action", "spin", "statue", {"degrees": 720.0, "axis": "z"})),
    ("make it rain", ("weather", "rain", None, {"heavy": False})),
    ("day to night", ("sky", "day_to_night", None, {})),
    ("at sunset", ("sky", "sunset", None, {})),
])
def test_what_each_phrase_directs(text, expected):
    d = cinema.parse_direction(text)
    if expected is None:
        assert all(e["move"] != "spin" or e["params"]["degrees"] == 360.0 for e in d["events"])
        return
    e = d["events"][0]
    assert (e["kind"], e["move"], e["subject"], e["params"]) == expected


@pytest.mark.parametrize("text,on", [("make the lights turn on gradually", True), ("turn on the pool lights", True),
                                     ("the house lights come on", True), ("switch off the lamps", False),
                                     ("the lights fade out at the end", False)])
def test_lights_on_and_off(text, on):
    e = next(e for e in cinema.parse_direction(text)["events"] if e["kind"] == "lights")
    assert e["move"] == ("on" if on else "off")


def test_gradual_lights_take_longer():
    quick, _ = cinema.schedule(cinema.parse_direction("the lights turn on at 2 seconds"), 10)
    slow, _ = cinema.schedule(cinema.parse_direction("the lights turn on gradually at 2 seconds"), 10)
    assert slow[0]["end"] - slow[0]["start"] > quick[0]["end"] - quick[0]["start"]


def test_it_means_the_last_subject():
    d = cinema.parse_direction("make the car drive from the garage to the gate and the camera follows it")
    assert [(e["kind"], e["subject"]) for e in d["events"]] == [("action", "car"), ("camera", "car")]


def test_actions_follow_one_another_and_never_overrun():
    events, D = cinema.schedule(cinema.parse_direction(
        "a 4-second clip, the door opens, then the lights turn on, then the statue spins"))
    starts = [e["start"] for e in events]
    assert starts == sorted(starts) and all(e["end"] <= D for e in events)


def test_with_no_length_the_whole_fits_what_was_timed():
    _, D = cinema.schedule(cinema.parse_direction("orbit the camera around the fountain for 6 seconds"))
    assert D == 6.0


@pytest.mark.parametrize("text,static", [("create a calm still ocean", True), ("a static flag", True),
                                         ("create an ocean", False)])
def test_static_requests(text, static):
    assert cinema.is_static(text) is static


@pytest.mark.parametrize("text,stages", [
    ("Create a modern villa with a swimming pool beside it and make a 10-second cinematic where the camera "
     "approaches the villa", ["Create a modern villa with a swimming pool beside it",
                              "make a 10-second cinematic, the camera approaches the villa"]),
    ("Create a 10-second cinematic of a modern villa where the camera orbits the villa",
     ["Create a modern villa", "a 10-second cinematic, the camera orbits the villa"]),
    ("create a villa at night", ["create a villa", "with a night sky"]),
    ("build a cabin and make it snow", ["build a cabin", "make it snow"]),
    # what's still being described stays with the build; "a windy environment" is weather, not a thing to model
    ("create a small beach with a few palm trees in a windy environment and the ocean beside it",
     ["create a small beach with a few palm trees and the ocean beside it", "make it windy"]),
    ("create a house on a windy day", ["create a house", "make it windy"]),
    ("create an ocean", None), ("make the door open", None), ("the camera orbits the villa", None)])
def test_building_and_directing_are_separate_stages(text, stages):
    assert cinema.split_stages(text) == stages


# ---------- cameras ----------

def scene():
    return spatial.things({"objects": villa() + pool_inside(x=14)})


def thing(ts, name):
    return next(t for t in ts if t["name"] == name)


@pytest.mark.parametrize("shot,fill", [("establishing", 0.42), ("wide", 0.62), ("medium", 0.78)])
def test_a_shot_frames_its_subject_as_the_shot_type_wants(shot, fill):
    ts = scene()
    v = thing(ts, "Villa")
    plan = cinema.plan_shot(ts, v, shot)
    lo, hi = cinema.subject_box(v)
    f = cinema.framing(plan["location"], plan["aim"], plan["lens"], lo, hi)
    assert f["visible"] == 1.0 and abs(f["center"][0]) < 0.05 and abs(f["center"][1]) < 0.05
    assert fill * 0.75 <= f["size"] <= fill * 1.1


def test_a_camera_never_stands_inside_a_building_and_sees_past_them():
    ts = scene()
    pool = thing(ts, "Pool")
    for shot in ("establishing", "wide", "medium", "close", "low"):
        plan = cinema.plan_shot(ts, pool, shot, azimuth=180.0)   # asked to look from behind the villa
        boxes = cinema.obstacles_3d(ts, exclude={"Pool"})
        free, seen = cinema.clear_view(plan["location"], plan["aim"], boxes)
        assert free and seen == 1, (shot, plan)


def test_a_three_quarter_view_from_the_front_of_a_building():
    ts = scene()
    v = thing(ts, "Villa")
    plan = cinema.plan_shot(ts, v, "wide")
    assert plan["location"][1] < v["core"][1]                  # in front (the villa faces -y)
    assert abs(plan["location"][0]) > 3                        # and off to one side


def test_a_push_in_gets_closer_and_never_leaves_its_line():
    ts = scene()
    keys = cinema.camera_path(ts, thing(ts, "Villa"), "push_in")
    c = keys[0][2]
    dists = [math.dist(cam, c) for _, cam, _, _ in keys]
    assert dists == sorted(dists, reverse=True) and dists[-1] < dists[0] * 0.8
    assert [p for p, *_ in keys] == sorted(p for p, *_ in keys) and keys[0][0] == 0 and keys[-1][0] == 1


def test_a_pull_out_is_a_push_in_backwards():
    ts = scene()
    keys = cinema.camera_path(ts, thing(ts, "Villa"), "pull_out")
    c = keys[0][2]
    assert math.dist(keys[0][1], c) < math.dist(keys[-1][1], c)


def test_an_orbit_sweeps_round_its_subject_at_one_distance_and_stays_clear():
    ts = scene()
    pool = thing(ts, "Pool")
    keys = cinema.camera_path(ts, pool, "orbit", sweep=360)
    c = keys[0][2]
    angles = [math.degrees(math.atan2(cam[1] - c[1], cam[0] - c[0])) for _, cam, _, _ in keys]
    span = sum(abs(math.remainder(math.radians(b - a), 2 * math.pi)) for a, b in zip(angles, angles[1:]))
    assert math.degrees(span) > 300
    boxes = cinema.obstacles_3d(ts, exclude={"Pool"})
    for _, cam, aim, _ in keys:
        assert cinema.clear_view(cam, aim, boxes)[0]


def test_following_a_moving_subject_stays_behind_it():
    ts = scene()
    motion = [(k / 4, (k * 5.0, -20.0, 0.0), (1.0, 0.0)) for k in range(5)]   # driving along +x
    car = spatial.virtual_thing("Car", (-2.2, -20.9, 2.2, -19.1), "outdoor", 1.5)
    keys = cinema.camera_path(ts + [car], car, "follow", motion=motion)
    for (_, pos, _), (_, cam, aim, _) in zip(motion[1:-1], keys[1:-1]):
        assert cam[0] < pos[0] and cam[2] > 1.0 and aim[0] > cam[0]


def test_a_follow_camera_swings_round_a_building_in_the_way_instead_of_losing_the_car():
    # the car drives away from a garage it just left: straight behind it is the garage itself
    garage = spatial.virtual_thing("Garage", (-2.0, -4.0, 2.0, 3.0), "building", 2.8)
    car = spatial.virtual_thing("Car", (-0.9, -8.2, 0.9, -3.8), "outdoor", 1.4)
    ts = [garage, car]
    motion = [(k / 4, (0.0, -6.0 - k * 4.0, 0.0), (0.0, -1.0)) for k in range(5)]   # driving off along -y
    keys = cinema.camera_path(ts, car, "follow", motion=motion)
    boxes = cinema.obstacles_3d(ts, exclude={"Car"})
    for _, cam, aim, _ in keys:
        assert not any(cinema._inside_box(cam, lo, hi, 0.3) for _, lo, hi in boxes)
        assert cinema.clear_view(cam, aim, boxes)[0]
    assert all(math.dist(a[1], b[1]) < 9 for a, b in zip(keys, keys[1:]))   # no jumps between keys


@pytest.mark.parametrize("move", ["crane", "reveal", "pan", "tilt", "overhead", "flyover", "fly_through"])
def test_every_move_gives_keys_from_start_to_end(move):
    ts = scene()
    keys = cinema.camera_path(ts, [thing(ts, "Villa"), thing(ts, "Pool")] if move.startswith("fly") else
                              thing(ts, "Villa"), move)
    assert len(keys) >= 2 and keys[0][0] == 0 and keys[-1][0] == 1
    assert all(len(cam) == 3 and len(aim) == 3 and lens > 0 for _, cam, aim, lens in keys)


def test_a_blocked_camera_is_lifted_until_it_sees():
    boxes = [("Wall", [-1, -1, 0], [1, 1, 5])]
    cam = cinema.clear_position((0, -10, 1.5), (0, 10, 1.5), boxes)
    assert cam[2] > 5 and not any(cinema._seg_hits_box(cam, (0, 10, 1.5), lo, hi) for _, lo, hi in boxes)


def test_projection_puts_the_aim_point_in_the_middle():
    x, y, depth = cinema.project((0, 0, 0), (10, -10, 5), (0, 0, 0), 35)
    assert abs(x) < 1e-6 and abs(y) < 1e-6 and depth > 0


# ---------- light ----------

@pytest.mark.parametrize("k,warm", [(2000, True), (9000, False)])
def test_colour_temperature(k, warm):
    r, g, b = cinema.kelvin(k)
    assert (r > b) is warm and all(0 <= c <= 1 for c in (r, g, b))


def test_day_to_night_passes_through_sunset_and_dusk():
    keys = cinema.sky_keys("day_to_night")
    assert [k["name"] for _, k in keys] == ["day", "sunset", "dusk", "night"]
    assert keys[0][1]["strength"] > keys[-1][1]["strength"] and keys[0][1]["sky_strength"] > keys[-1][1]["sky_strength"]


def test_ceiling_lights_are_inside_the_building_under_its_ceiling():
    v = spatial.things({"objects": villa()})[0]
    pts = cinema.light_spots_inside(v)
    assert pts and all(v["core"][0] < x < v["core"][2] and v["core"][1] < y < v["core"][3] for x, y, z in pts)
    assert all(spatial.floor_level(v) + 2 <= z < v["hi"][2] for x, y, z in pts)


def test_pool_lights_are_under_the_water_on_its_walls_facing_in():
    spots = cinema.pool_light_spots((-4, -2, -1.5), (4, 2, -0.1))
    assert len(spots) >= 2
    for (x, y, z), (fx, fy) in spots:
        assert -1.5 < z < -0.1 and -4 <= x <= 4 and -2 <= y <= 2
        assert (fy > 0) == (y < 0) if fx == 0 else (fx > 0) == (x < 0)


# ---------- what moves by itself ----------

@pytest.mark.parametrize("name,asset,text,motion", [
    ("Sea", "water", "create a sea", "waves"), ("Ocean", None, "an ocean", "waves"),
    ("Pool", "pool", "a pool", "ripples"), ("Garden Pond", "pond", "", "ripples"), ("River", "river", "", "flow"),
    ("Waterfall", "waterfall", "", "falls"), ("Campfire", "fire", "", "fire"), ("Rain", "rain", "", "rain"),
    ("Cloud", "cloud", "", "drift"), ("Flag", "flag", "", "flutter"), ("Windmill", None, "", "spin"),
    ("Oak", "tree", "create an oak", None), ("Oak", "tree", "trees in a windy valley", "sway"),
    ("Sea", "water", "a calm still sea, static", None), ("House", "house", "a house in the wind", None),
    ("Bench", "bench", "", None)])
def test_what_moves_by_nature(name, asset, text, motion):
    t = {"name": name, "asset_type": asset}
    assert cinema.natural_motion(t, text) == motion


def test_motion_is_measured_not_assumed():
    still = [{"frame": f, "loc": [1, 2, 3], "sig": 5.0} for f in (1, 50, 100)]
    assert not cinema.moved(still)
    assert cinema.moved(still[:2] + [{"frame": 100, "loc": [1, 2, 3.2], "sig": 5.0}])
    assert cinema.moved(still[:2] + [{"frame": 100, "loc": [1, 2, 3], "sig": 5.5}])


@pytest.mark.parametrize("text,owner", [("the garage door opens", "garage"), ("the door of the shed opens", "shed"),
                                        ("the villa's front door opens near the end", "villa"),
                                        ("the front door of the house opens", "house"), ("the door opens", None)])
def test_whose_door_opens_is_understood(text, owner):
    e = cinema.parse_direction(text)["events"][0]
    assert e["move"] == "open" and e["params"].get("of") == owner
