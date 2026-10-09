"""The Blender adapter's direction of motion, cameras and light, against a simulated Blender (no real one): the
director turns a request into a timeline of verified kit calls on the scene's real things, motion checks are
decided by what Blender reports over the timeline (never by the code having run), bad cameras and lights are
repaired, and natural motion is only claimed when it shows."""
import json
import re

import pytest

import agent_blender
import agent_core
from test_agent_spatial import SimBridge, state_of
from test_spatial import names, o, pool_inside, villa

BRIEF = ("Create a 10-second cinematic where the camera approaches the villa, the pool lights turn on halfway "
         "through, and the door opens near the end.")


def sample(frame, loc=(0, 0, 0), lo=(0, 0, 0), hi=(1, 1, 1), **kw):
    return dict({"frame": frame, "loc": list(loc), "rot": [0, 0, 0], "scale": [1, 1, 1], "lo": list(lo),
                 "hi": list(hi), "hidden": False, "sig": 0.0}, **kw)


def report(objects, start=1, end=241, fps=24):
    return {"scene": {"fps": fps, "start": start, "end": end, "camera": "Camera", "frames": [1, 61, 121, 181, 241]},
            "objects": objects, "world": []}


class MotionBridge(SimBridge):
    def __init__(self, objects, motion=None, **kw):
        super().__init__(objects, **kw)
        self.motion = motion or report({})
        self.timeline = {"fps": 24, "start": 1, "end": 250, "frame": 1, "camera": None}

    def run(self, code, timeout=15):
        if "motion_report()" in code:
            self.calls.append(code)
            return {"ok": True, "output": json.dumps(self.motion), "error": ""}
        if "scene_state()" in code:
            self.calls.append(code)
            return {"ok": True, "output": json.dumps({"objects": self.objects, "timeline": self.timeline}),
                    "error": ""}
        return super().run(code, timeout)


def adapter_for(objects, goal="", motion=None):
    bridge = MotionBridge(objects, motion)
    adapter = agent_blender.BlenderAdapter(bridge)
    adapter.goal = goal
    adapter.intents = adapter._intents(goal)
    return adapter, bridge


def scene():
    return villa() + pool_inside(x=14)


# ---------- the director ----------

def test_the_brief_becomes_kit_calls_on_the_scenes_own_things():
    adapter, bridge = adapter_for(scene())
    plan = adapter.quick_plan(BRIEF, {"objects": bridge.objects, "timeline": bridge.timeline}, lambda *a, **k: {})
    codes = [s["code"] for s in plan["steps"]]
    assert codes[0] == "RESULT = str(timeline(10, keep_longer=False))"
    assert codes[1] == "camera_move('Camera', 'push_in', 'Villa', start=0.0, end=10.0)"
    assert codes[2] == "lights_on('Pool', start=5.0, end=5.8, ease='smooth')"
    assert codes[3] == "open_door('Villa', start=7.5, end=9.3, ease='out')"
    finals = plan["final_checks"]
    assert {"type": "timeline", "min": 10.0} in finals
    assert {"type": "camera_frames", "object": "Camera", "other": "Villa"} in finals
    assert {"type": "light_on", "object": "Pool"} in finals and {"type": "animated", "object": "Villa"} in finals


def test_directing_something_that_isnt_there_asks_first():
    adapter, bridge = adapter_for(scene())
    plan = adapter.quick_plan("make the car drive to the gate", {"objects": bridge.objects}, lambda *a, **k: {})
    assert plan["steps"] == [] and "car" in plan["question"]


def test_a_request_that_also_builds_is_two_stages_and_the_director_leaves_it_alone():
    adapter, bridge = adapter_for([])
    goal = "Create a modern villa with a pool beside it and make a 10-second cinematic where the camera orbits it"
    assert adapter.stages(goal) == ["Create a modern villa with a pool beside it",
                                    "make a 10-second cinematic, the camera orbits it"]
    assert adapter._direction_plan(goal, {"objects": []}) is None


@pytest.mark.parametrize("text,code", [
    ("the camera orbits the pool", "camera_move('Camera', 'orbit', 'Pool'"),
    ("a close-up of the door", "camera_move('Camera', 'close', 'Villa'"),
    ("make it rain", "rain('Rain', heavy=False)"),
    ("day to night over 12 seconds", "sky('day_to_night', start=0.0, end=12.0)"),
    ("at sunset", "sky('sunset')"),
    ("dramatic lighting", "lighting('dramatic', 'Villa')"),
    ("the house lights turn on gradually", "lights_on('Villa', start=0.0, end=2.5"),
    ("spin the pool 2 times", "spin('Pool', 720.0, 'z'"),
])
def test_phrases_become_the_right_kit_calls(text, code):
    adapter, bridge = adapter_for(scene())
    plan = adapter.quick_plan(text, {"objects": bridge.objects, "timeline": bridge.timeline}, lambda *a, **k: {})
    assert any(s["code"].startswith(code) for s in plan["steps"]), [s["code"] for s in plan["steps"]]


def test_the_planner_gets_the_timeline_worked_out_when_the_director_cant_take_it():
    note = agent_blender.BlenderAdapter._direction_note(
        "a 10-second shot where the camera orbits the villa and the windmill does a funny dance at 4 seconds",
        {"objects": [], "timeline": {"fps": 24, "start": 1, "end": 250}})
    assert "10 s = frames 1-241 at 24 fps" in note and "0-10 s" in note


# ---------- checks decided by what Blender shows ----------

def moving(name, frames=(1, 61, 121, 181, 241), **kw):
    return {"type": kw.pop("type", "MESH"), "keys": kw.pop("keys", 4), "samples":
            [sample(f, loc=(f / 10, 0, 0), lo=(f / 10, 0, 0), hi=(f / 10 + 1, 1, 1)) for f in frames], **kw}


def still(name, frames=(1, 61, 121, 181, 241), **kw):
    return {"type": kw.pop("type", "MESH"), "keys": kw.pop("keys", 0), "samples": [sample(f) for f in frames], **kw}


def test_animated_means_it_really_moves_not_that_it_has_keys():
    adapter, bridge = adapter_for(scene(), motion=report({"Villa Door Hinge": moving("x", parent="Villa"),
                                                          "Pool": still("x", keys=6)}))
    state = state_of(bridge)
    assert adapter.evaluate({"type": "animated", "object": "Villa"}, state)[0] is True
    ok, detail = adapter.evaluate({"type": "animated", "object": "Pool"}, state)
    assert ok is False and "doesn't actually move" in detail


def view(visible=1.0, blocked=None, centre=(0.5, 0.5)):
    return {"visible": visible, "centre": list(centre), "in_front": True, "blocked_by": blocked}


def camera(views, subject=("Villa",)):
    return {"type": "CAMERA", "keys": 8, "camera": {"subject": list(subject), "lens": 35, "move": "push_in"},
            "samples": [sample(f, loc=(10, -20, 5), view=v) for f, v in zip((1, 61, 121, 181, 241), views)]}


@pytest.mark.parametrize("views,ok", [([view()] * 5, True), ([view(0.25)] * 3 + [view()] * 2, False),
                                      ([view(blocked="Pool Coping")] * 2 + [view()] * 3, False),
                                      ([view(blocked="Pool Coping")] + [view()] * 4, True)])
def test_a_camera_must_keep_its_subject_framed_and_unblocked(views, ok):
    adapter, bridge = adapter_for(scene(), motion=report({"Camera": camera(views)}))
    assert adapter.evaluate({"type": "camera_frames", "object": "Camera", "other": "Villa"}, state_of(bridge))[0] is ok


def test_a_camera_filming_the_wrong_thing_fails():
    adapter, bridge = adapter_for(scene(), motion=report({"Camera": camera([view()] * 5, subject=("Pool",))}))
    ok, detail = adapter.evaluate({"type": "camera_frames", "object": "Camera", "other": "Villa"}, state_of(bridge))
    assert ok is False and "not 'Villa'" in detail


def light(energies, kind="SPOT", parent="Pool"):
    return {"type": "LIGHT", "keys": 2, "parent": parent, "light": {"kind": kind, "energy": energies[-1], "color": [1, 1, 1]},
            "samples": [sample(f, energy=e) for f, e in zip((1, 61, 121, 181, 241), energies)]}


def test_lights_on_means_on_at_the_end():
    adapter, bridge = adapter_for(scene(), motion=report({"Pool Light 1": light([0, 0, 120, 120, 120]),
                                                          "Pool Light 2": light([0, 0, 0, 0, 0])}))
    ok, detail = adapter.evaluate({"type": "light_on", "object": "Pool"}, state_of(bridge))
    assert ok is False and "1 of 2" in detail


def test_the_timeline_check():
    adapter, bridge = adapter_for(scene(), motion=report({}, end=241))
    assert adapter.evaluate({"type": "timeline", "min": 10}, state_of(bridge))[0] is True
    assert adapter.evaluate({"type": "timeline", "min": 12}, state_of(bridge))[0] is False


def test_moves_to_means_it_gets_there():
    car = {"type": "EMPTY", "keys": 20, "samples": [sample(1, lo=(-30, -30, 0), hi=(-26, -28, 1.5)),
                                                    sample(241, lo=(8, -5, 0), hi=(12, -3, 1.5))]}
    adapter, bridge = adapter_for(scene(), motion=report({"Car": car}))
    assert adapter.evaluate({"type": "moves_to", "object": "Car", "other": "Pool"}, state_of(bridge))[0] is True
    stuck = dict(car, samples=[car["samples"][0], sample(241, lo=(-20, -30, 0), hi=(-16, -28, 1.5))])
    adapter, bridge = adapter_for(scene(), motion=report({"Car": stuck}))
    ok, detail = adapter.evaluate({"type": "moves_to", "object": "Car", "other": "Pool"}, state_of(bridge))
    assert ok is False and "should get there" in detail


# ---------- repairs ----------

def test_a_camera_inside_the_villa_is_craned_out():
    cam = camera([view()] * 5)
    cam["samples"][2]["loc"] = [0, 0, 2]          # in the middle of the villa
    objs = scene() + [o("Camera", (0, 0, 2), (0, 0, 2), type_="CAMERA", camera={"lens": 35, "subject": '["Villa"]'},
                        animated=True)]
    adapter, bridge = adapter_for(objs, motion=report({"Camera": dict(cam, camera={"subject": ["Pool"], "lens": 35})}))
    issues = adapter._motion_issues({"Villa": 1}, state_of(bridge), "a shot of the pool")
    assert issues and issues[0][1] == "unblock_camera('Camera')"
    fixed = adapter.auto_fix({"Villa": 1}, state_of(bridge), "a shot of the pool")
    assert any("inside something" in f for f in fixed) and any("unblock_camera('Camera')" in c for c in bridge.calls)


def test_invalid_lights_are_fixed_and_missing_objects_reported():
    lamp = {"type": "LIGHT", "keys": 0, "light": {"kind": "POINT", "energy": -50, "color": [1, 1, 1]},
            "samples": [sample(1, energy=-50)]}
    objs = scene() + [o("Lamp", (0, 0, 3), (0, 0, 3), type_="LIGHT", animated=True)]
    adapter, bridge = adapter_for(objs, motion=report({"Lamp": lamp}))
    issues = adapter._motion_issues({"Villa": 1, "Old Shed": 1}, state_of(bridge), "turn on the lamp")
    texts = [t for t, _ in issues]
    assert any("Old Shed" in t for t in texts) and any("invalid settings" in t for t in texts)
    assert ("check_lights()" in [c for _, c in issues])


# ---------- natural motion ----------

def test_new_water_is_given_motion_and_only_claimed_when_it_shows():
    sea = [o("Sea", (0, 40, 0), (0, 40, 0), type_="EMPTY", asset="Sea", asset_type="water"),
           o("Sea Surface", (-20, 20, -0.1), (20, 60, 0.1), "Sea", asset="Sea", asset_type="water")]
    shows = report({"Sea Surface": {"type": "MESH", "keys": 0, "parent": "Sea",
                                    "samples": [sample(1, sig=1.0), sample(121, sig=1.4)]}})
    adapter, bridge = adapter_for(scene() + sea, motion=shows)
    touches = adapter.finishing_touches(names(scene()), "create a sea")
    assert any("animate_naturally('Sea', 'waves'" in c for c in bridge.calls)
    assert touches == ["the water rolls in slow waves (Sea)"]
    adapter, bridge = adapter_for(scene() + sea, motion=report({}))
    assert adapter.finishing_touches(names(scene()), "create a sea") == []   # didn't show: not claimed


def test_static_requests_and_static_things_get_no_motion():
    sea = [o("Sea", (0, 40, 0), (0, 40, 0), type_="EMPTY", asset="Sea", asset_type="water"),
           o("Sea Surface", (-20, 20, -0.1), (20, 60, 0.1), "Sea", asset="Sea", asset_type="water")]
    adapter, bridge = adapter_for(scene() + sea)
    assert adapter.finishing_touches(names(scene()), "create a calm, static sea") == []
    adapter, bridge = adapter_for(scene())
    assert adapter.finishing_touches(names(pool_inside(x=14)), "create a villa") == []   # the villa: no motion
    assert not any("animate_naturally" in c for c in bridge.calls)


def test_wind_in_the_request_makes_the_existing_trees_sway():
    adapter, bridge = adapter_for(scene())
    adapter.finishing_touches(names(scene()), "it's a windy day")
    assert any("wind(1.0)" in c for c in bridge.calls)


# ---------- stages in the agent loop ----------

class StageApp(agent_core.AppAdapter):
    name, label = "stage", "StageApp"

    def __init__(self, fail=None):
        self.ran, self.fail = [], fail

    def stages(self, goal):
        return ["build it", "direct it"] if goal == "build and direct it" else [goal]

    def quick_plan(self, goal, state, ask_json):
        code = "fail" if goal == self.fail else f"do {goal}"
        return {"understanding": goal, "question": "", "quick": True, "final_checks": [],
                "steps": [{"title": goal, "code": code, "checks": [], "quick": True}]}

    def execute(self, code):
        self.ran.append(code)
        return {"ok": code != "fail", "output": "", "error": "no" if code == "fail" else ""}

    def finishing_touches(self, before, goal):
        return ["the water ripples"] if goal == "direct it" else []


def test_stages_run_in_order_and_a_failed_one_stops_the_rest():
    app = StageApp()
    task = agent_core.AgentTask("build and direct it", app, ask_json=lambda *a, **k: {}, log=lambda m: None)
    result = task.run()
    assert task.state == "completed" and app.ran == ["do build it", "do direct it"]
    assert "natural motion: the water ripples" in result
    app = StageApp(fail="build it")
    task = agent_core.AgentTask("build and direct it", app, ask_json=lambda *a, **k: {}, log=lambda m: None)
    result = task.run()
    assert task.state == "error" and app.ran == ["fail"] and "didn't work" in result


@pytest.mark.parametrize("clause,subject,said", [
    ("the camera slowly pushes in on the palm trees", "palm", "palm trees"),
    ("the pool lights turn on halfway", "pool", "pool"),
    ("the car drives to the gate", "car", "car")])
def test_a_directed_subject_is_named_as_the_user_said_it(clause, subject, said):
    e = {"kind": "lights" if "lights" in clause else "camera", "subject": subject, "clause": clause}
    assert agent_blender.BlenderAdapter._subject_phrase(e) == said


def island_with_palms():
    a = dict(asset="Island", asset_type="island")
    objs = [o("Island", (0, 0, 0), (0, 0, 0), type_="EMPTY", **a),
            o("Island Terrain", (-10, -10, -1), (10, 10, 3), "Island", kind="terrain", **a),
            o("Island Sea", (-30, -30, -0.5), (30, 30, 0), "Island", kind="water", **a)]
    for i, x in enumerate((-3, 2, 5), 1):
        objs += [o(f"Island Palm {i}", (x, 1, 1), (x, 1, 1), "Island", type_="EMPTY", **a),
                 o(f"Island Palm {i} Trunk", (x - 0.2, 0.8, 1), (x + 0.2, 1.2, 8), f"Island Palm {i}", **a),
                 o(f"Island Palm {i} Fronds", (x - 2, -1, 7), (x + 2, 3, 9), f"Island Palm {i}", **a)]
    return objs


def test_the_palm_trees_of_an_island_are_its_parts_and_the_camera_films_them_all():
    adapter, bridge = adapter_for(island_with_palms())
    plan = adapter.quick_plan("make an 8-second shot where the camera orbits the palm trees",
                              {"objects": bridge.objects, "timeline": bridge.timeline}, lambda *a, **k: {})
    assert not plan["question"]
    assert plan["steps"][1]["code"] == ("camera_move('Camera', 'orbit', ['Island Palm 1', 'Island Palm 2', "
                                        "'Island Palm 3'], start=0.0, end=8.0)")
    assert plan["steps"][1]["checks"] == [{"type": "camera_frames", "object": "Camera", "other": "Island Palm 1"}]


def test_wind_moves_the_islands_palms_and_leaves_the_timeline_alone():
    adapter, bridge = adapter_for(island_with_palms())
    plan = adapter.quick_plan("make it windy", {"objects": bridge.objects, "timeline": bridge.timeline},
                              lambda *a, **k: {})
    assert [s["code"] for s in plan["steps"]] == ["RESULT = str(wind(1.0))"]   # no "10.38-second" timeline
    assert {"type": "animated", "object": "Island Palm 1"} in plan["final_checks"]
    assert adapter._directed_text() == "set it going: the wind blows"


def test_wind_with_nothing_to_blow_says_so_instead_of_claiming_it():
    adapter, bridge = adapter_for(villa())
    plan = adapter.quick_plan("make it windy", {"objects": bridge.objects, "timeline": bridge.timeline},
                              lambda *a, **k: {})
    assert plan["steps"] == [] and "nothing here the wind would move" in plan["question"]


@pytest.mark.parametrize("seconds,said", [(8, "directed an 8-second shot"), (10, "directed a 10-second shot"),
                                          (11, "directed an 11-second shot"), (18.5, "directed an 18.5-second shot"),
                                          (1.5, "directed a 1.5-second shot")])
def test_the_summary_reads_naturally(seconds, said):
    adapter, _ = adapter_for(scene())
    adapter.directed = ([], seconds, 24)
    assert adapter._directed_text().startswith(said)


def garage_scene():
    a = dict(asset="Garage", asset_type="garage")
    return villa() + [o("Garage", (20, 0, 0), (20, 0, 0), type_="EMPTY", **a),
                      o("Garage Walls", (18.2, -3.25, 0), (21.8, 3.25, 2.7), "Garage", **a),
                      o("Garage Door", (18.6, -3.25, 0), (21.4, -3.15, 2.25), "Garage", **a)]


def test_the_garage_door_is_the_garages_not_the_houses():
    adapter, bridge = adapter_for(garage_scene())
    plan = adapter.quick_plan("the garage door opens", {"objects": bridge.objects, "timeline": bridge.timeline},
                              lambda *a, **k: {})
    assert any(s["code"].startswith("open_door('Garage'") for s in plan["steps"]), plan["steps"]
    adapter.directed = (adapter.directed[0], 3, 24)
    assert "the garage door opens" in adapter._directed_text()
