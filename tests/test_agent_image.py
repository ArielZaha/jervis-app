"""The Blender adapter with pictures and scene edits (no real Blender, no model): a rebuild request with a picture
becomes the reconstruction plan; no picture or no vision model is said plainly; an edit of the scene that's there
is routed before the director, a timed shot to the director; the new checks (the environment, a camera's safety)
read Blender's answers; summaries say what changed — and nothing of the old flows breaks."""
import json

import pytest

import agent_blender
import agent_core
import scene_state
from test_scene_state import current as base_current


class EditBridge:
    """A bridge that answers the scene-state, environment and camera queries like the kit would."""

    def __init__(self, current=None, env=None, camera_check=None):
        self.current = current if current is not None else base_current()
        self.env = env or {"set": {"time": "night", "fog": {"kind": "fog", "density": 0.07}},
                           "live": {"fog_density": 0.07, "lights_on": 3}}
        self.cam = camera_check or {"camera": "Camera", "inside": [], "blocked_by": [], "below_ground": False}
        self.calls = []

    def ping(self, timeout=3):
        return True

    def run(self, code, timeout=15):
        self.calls.append(code)
        if "semantic_registry()" in code:
            return {"ok": True, "output": json.dumps(dict(self.current, env=self.env)), "error": ""}
        if code.strip() == "RESULT = env_state()":
            return {"ok": True, "output": json.dumps(self.env), "error": ""}
        if "camera_check(" in code:
            return {"ok": True, "output": json.dumps(self.cam), "error": ""}
        if "scene_state()" in code:
            return {"ok": True, "output": json.dumps({"objects": []}), "error": ""}
        return {"ok": True, "output": "ok", "error": ""}


def adapter(bridge=None):
    a = agent_blender.BlenderAdapter(bridge or EditBridge())
    a.goal = ""
    a.intents = []
    return a


def no_ai(*a, **k):
    raise AssertionError("the AI planner should not be needed")


def test_an_edit_is_planned_against_the_scene_that_is_there():
    a = adapter()
    plan = a.quick_plan("Make the fog thicker", {"objects": []}, no_ai)
    assert plan["steps"][0]["code"] == "RESULT = fog(factor=1.7)"
    assert a.edit is not None


def test_a_timed_shot_still_goes_to_the_director():
    from test_spatial import villa
    a = adapter()
    a.quick_plan("make a 10-second cinematic where the camera orbits the villa", {"objects": villa()}, no_ai)
    assert a.edit is None and a.directed is not None


def test_a_gradual_change_is_the_directors_too():
    from test_spatial import villa
    a = adapter()
    plan = a.quick_plan("the house lights turn on gradually", {"objects": villa()}, no_ai)
    assert a.edit is None
    assert any("lights_on(" in s["code"] for s in plan["steps"])


def test_without_a_scene_to_read_nothing_is_hijacked():
    class Old:   # an old bridge that knows nothing of the new kit
        def ping(self, timeout=3): return True
        def run(self, code, timeout=15): return {"ok": True, "output": "ok", "error": ""}
    a = adapter(Old())
    assert a._edit_plan("make the fog thicker") is None


def test_the_environment_check_reads_blender():
    a = adapter()
    assert a.evaluate({"type": "env", "path": "live.fog_density", "op": ">", "value": 0.05}, {})[0] is True
    assert a.evaluate({"type": "env", "path": "set.time", "op": "==", "value": "day"}, {})[0] is False


def test_a_camera_inside_a_wall_fails_its_check():
    good = adapter()
    assert good.evaluate({"type": "camera_safe", "object": "Camera"}, {})[0] is True
    bad = adapter(EditBridge(camera_check={"camera": "Camera", "inside": ["Villa"], "blocked_by": [],
                                           "below_ground": False}))
    ok, detail = bad.evaluate({"type": "camera_safe", "object": "Camera"}, {})
    assert ok is False and "inside Villa" in detail


def test_a_rebuild_needs_a_picture(monkeypatch):
    a = adapter()
    monkeypatch.setattr(agent_blender.BlenderAdapter, "_latest_image", staticmethod(lambda: None))
    plan = a.quick_plan("Recreate this image in Blender", {"objects": []}, no_ai)
    assert plan["steps"] == [] and "Attach" in plan["question"]


def test_no_vision_model_is_said_plainly(monkeypatch, tmp_path):
    import vision
    import visual_scene
    img = tmp_path / "p.png"
    from PIL import Image
    Image.new("RGB", (64, 64)).save(img)
    a = adapter()
    a.reference_image = str(img)

    def blind(*args, **kw):
        raise vision.VisionUnavailable("there's no vision model on this computer")
    monkeypatch.setattr(visual_scene, "analyze", blind)
    plan = a.quick_plan("Recreate this image in Blender", {"objects": []}, no_ai)
    assert plan["steps"] == [] and "no vision model" in plan["question"]


def test_a_rebuild_is_planned_from_what_the_picture_shows(monkeypatch, tmp_path):
    import visual_scene
    from test_visual_scene import FakeAsker, villa_picture
    path = tmp_path / "villa.png"
    villa_picture().save(path)
    scene = visual_scene.analyze(str(path), asker=FakeAsker())
    monkeypatch.setattr(visual_scene, "analyze", lambda image, progress=None: scene)
    said = []
    a = adapter()
    a.reference_image = str(path)
    a.set_progress(said.append)
    plan = a.quick_plan("Recreate this image in Blender", {"objects": []}, no_ai)
    assert plan["reconstruction"] and any("villa(" in s["code"] for s in plan["steps"])
    assert a.reconstruction["image"] == str(path) and said
    text = a.describe_made(None, {"objects": []})
    assert text.startswith("rebuilt the picture in 3D")


def test_an_edits_summary_says_what_changed_not_every_part():
    a = adapter()
    a.quick_plan("Make it sunrise", {"objects": []}, no_ai)
    assert a.describe_made(None, {"objects": [{"name": f"P{i}"} for i in range(40)]}).startswith("changed")


def test_the_resolver_remembers_across_requests():
    bridge = EditBridge()
    first = agent_blender.BlenderAdapter(bridge)
    first.quick_plan("Turn off the pool lights", {"objects": []}, no_ai)
    second = agent_blender.BlenderAdapter(bridge)
    assert second._resolver() is first._resolver()
    assert second._resolver().last == ["Swimming Pool"]


def test_more_like_the_photo_uses_the_kept_reference_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_state, "STORE", str(tmp_path))
    img = tmp_path / "ref.png"
    img.write_bytes(b"x")
    sid = scene_state.save_reference({"elements": []}, {"e1": "Villa"}, str(img))
    bridge = EditBridge()
    bridge.current = dict(bridge.current, scene_id=sid)
    a = adapter(bridge)
    plan = a.quick_plan("make it look more like the photo", {"objects": []}, no_ai)
    assert plan["reconstruction"] and a.reconstruction["again"] and a.reconstruction["image"] == str(img)
    a.reconstruction["critique"] = {"fixes": ["matched the sky to the photo's"]}
    assert a.describe_made(None, {}).startswith("changed the scene to look more like its photo")
    # an edit of the same scene never brings the reference back by itself
    b = adapter(bridge)
    assert b.quick_plan("Make it sunrise", {"objects": []}, no_ai)["steps"][0]["code"].startswith(
        "RESULT = str(time_of_day('sunrise'))") and b.reconstruction is None


@pytest.mark.parametrize("text,params,want", [
    ("Make the house bigger", {"width": 10.0, "depth": 8.0, "floors": 2}, {"width": 13.0, "depth": 10.4}),
    ("make the shop taller", {"width": 10.0, "floors": 1}, {"floors": 2}),
    ("make the forest smaller", {"width": 40.0, "depth": 15.0, "count": 30}, {"width": 30.77, "depth": 11.54}),
    ("make the villa twice as wide", {"width": 20.0}, {"width": 40.0}),
    ("paint the villa red", {"width": 20.0}, None),
])
def test_a_rebuilt_place_can_be_resized_in_words(text, params, want):
    # a villa, storefront or forest (a place-scale asset, outside the asset catalogue) grows or shrinks — rebuilt
    # with its sizes changed — instead of failing on its unknown kind (it was a KeyError: 'ground')
    assert agent_blender._size_change(text, params) == want
    assert agent_blender._asset_words("villa").search("make the house bigger")
    assert agent_blender._asset_words("ground").search("make the house bigger") is None
