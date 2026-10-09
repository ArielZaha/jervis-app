"""A picture -> a VisualScene (visual_scene.py), with the vision model replaced by canned answers: the camera
geometry (a point projected and found again; a camera height recovered from a thing of known size), the horizon
weighed from its evidence, things placed in metres, parts attached to their building, relationships, behaviours,
and honesty — what is seen, estimated, inferred or unknown."""
import math

import pytest
from PIL import Image, ImageDraw

import visual_scene as vs
from visual_scene import val


# ---------- geometry ----------

@pytest.mark.parametrize("pitch,height", [(0.0, 1.6), (8.0, 5.0), (-3.0, 4.0)])
def test_a_ground_point_and_its_projection_agree(pitch, height):
    size, f = (1280, 853), 1256.0
    for px, py in ((640, 700), (200, 600), (1100, 820)):
        p = vs.ground_point(px, py, size, f, pitch, height)
        if p is None:
            continue
        back = vs.project((p[0], p[1], 0.0), size, f, pitch, height)
        assert abs(back[0] - px) < 0.5 and abs(back[1] - py) < 0.5


def test_a_camera_height_is_recovered_from_a_thing_of_known_height():
    size, f, pitch, true_h = (1280, 853), 1000.0, 2.0, 4.5
    # a 2.1 m door standing 20 m away: where its foot and head appear for a camera 4.5 m up
    foot = vs.project((1.0, 20.0, 0.0), size, f, pitch, true_h)
    head = vs.project((1.0, 20.0, 2.1), size, f, pitch, true_h)
    got = vs.camera_height_from(2.1, foot[1], head[1], foot[0], size, f, pitch)
    assert abs(got - true_h) < 0.05


def test_the_horizon_drops_a_wild_guess_instead_of_averaging_it_in():
    horizon, spread, used = vs.fuse_horizon([(0.80, 0.4, "model"), (0.62, 0.6, "level line"),
                                             (0.56, 0.45, "sky line"), (0.50, 0.25, "pitch class")])
    assert "model" not in used and 0.55 < horizon < 0.62


def test_the_sea_line_sets_the_horizon():
    els = [{"kind": "ocean", "box": (0, 400, 1280, 520), "truncated": {"top": False}, "category": "ground",
            "tags": [], "depth_layer": "midground"}]
    cam = vs.estimate_camera({"horizon_height": 0.2, "lens": "normal", "camera_height": "eye level",
                              "camera_pitch": "level"}, (1280, 853), {"share": 0.3, "sides": 0.25}, els)
    assert abs(val(cam["horizon"]) - 400 / 853) < 0.04
    assert "sea line" in cam["horizon"]["note"]


def test_the_horizon_stays_above_the_feet_of_things_on_the_ground():
    els = [{"kind": "house", "box": (300, 200, 900, 380), "truncated": {"bottom": False, "top": False},
            "category": "building", "tags": [], "depth_layer": "midground", "details": {}}]
    cam = vs.estimate_camera({"horizon_height": 0.6, "lens": "normal", "camera_height": "eye level",
                              "camera_pitch": "level"}, (1280, 853), {}, els)
    assert val(cam["horizon"]) < 380 / 853


def test_hanging_lanterns_never_drag_the_horizon_up():
    els = [{"kind": "lantern", "box": (300, 40, 340, 110), "truncated": {"bottom": False, "top": False},
            "category": "outdoor", "tags": ["hanging"], "depth_layer": "midground", "details": {}}]
    cam = vs.estimate_camera({"horizon_height": 0.5, "lens": "normal", "camera_height": "eye level",
                              "camera_pitch": "level"}, (1280, 853), {}, els)
    assert val(cam["horizon"]) > 0.4


def test_exif_focal_length_is_a_fact():
    cam = vs.estimate_camera({}, (1280, 853), {}, [], exif_f35=24.0)
    assert cam["lens_mm"]["status"] == "visible" and abs(val(cam["hfov"]) - 73.7) < 0.5


# ---------- the whole analysis, with canned answers ----------

class FakeAsker:
    """Answers like the vision model would about villa_picture()."""

    def __init__(self, unlisted_false=("car",)):
        self.calls = []
        self.unlisted_false = unlisted_false

    def ask_json(self, img, prompt, crop=None):
        self.calls.append(("ask", prompt[:40], crop))
        if prompt.startswith(vs.GLOBAL_PROMPT[:40]):
            return {"scene_type": "exterior", "setting": "residential", "summary": "A house with a pool at dusk.",
                    "time_of_day": "golden hour", "sky": "clear", "weather": "clear", "wind": "light",
                    "sun_direction": "left", "shadows": "soft", "artificial_lights_on": True,
                    "camera_height": "eye level", "camera_pitch": "level", "lens": "normal",
                    "horizon_height": 0.9, "main_subject": "house", "view_of_main_subject": "front",
                    "things": [{"kind": "house", "count": 1, "importance": "high"},
                               {"kind": "swimming pool", "count": 1, "importance": "high"},
                               {"kind": "palm trees", "count": 2, "importance": "medium"},
                               {"kind": "person", "count": 1, "importance": "low"}],
                    "water": ["pool"], "atmosphere": "clear", "ground": ["grass"]}
        if "Is at least one" in prompt or "REALLY visible" in prompt:
            return {k: k not in self.unlisted_false for k in ("car", "sun lounger", "umbrella", "staircase", "tree")}
        if "one building" in prompt:
            return {"style": "modern", "floors": 2, "roof": "flat", "wall_material": "plaster", "wall_color": "white",
                    "glass_share": "half", "windows_across": 4, "door_position": "center", "facing":
                    "front faces the camera", "lit_windows": "few"}
        if "swimming pool" in prompt:
            return {"shape": "rectangle", "water_color": "turquoise", "length_to_width": 2.5, "lit": True}
        if "plants" in prompt:
            return {"type": "palm", "leaning": "slightly", "count": 1}
        return {}

    def ground(self, img, labels, crop=None):
        self.calls.append(("ground", tuple(labels)))
        text = " ".join(labels)
        out = []
        if "building" in text:
            out.append({"label": "house", "box": (380, 300, 900, 560)})
        if "swimming pool" in text:
            out.append({"label": "swimming pool", "box": (450, 600, 850, 650)})
        if "palm" in text:
            out += [{"label": "palm tree", "box": (150, 250, 300, 640)}, {"label": "palm tree", "box": (1000, 260, 1130, 630)}]
        if "car" in text:
            out.append({"label": "car", "box": (100, 700, 260, 780)})   # a car that isn't there
        if "person" in text:
            out.append({"label": "person", "box": (600, 580, 620, 640)})
        return out


def villa_picture():
    img = Image.new("RGB", (1280, 853), (120, 160, 210))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 470, 1280, 853), fill=(60, 110, 50))
    d.rectangle((380, 300, 900, 560), fill=(230, 228, 222))
    for x in (420, 560, 700, 820):
        d.rectangle((x, 380, x + 60, 470), fill=(255, 190, 110))
    d.rectangle((450, 600, 850, 650), fill=(60, 200, 210))
    return img


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    path = tmp_path_factory.mktemp("vs") / "villa.png"
    villa_picture().save(path)
    asker = FakeAsker()
    sc = vs.analyze(str(path), asker=asker)
    sc["_asker"] = asker
    return sc


def by_kind(scene, kind):
    return [e for e in scene["elements"] if e["kind"] == kind]


def test_what_was_seen_is_listed_and_people_are_left_out(scene):
    kinds = sorted(e["kind"] for e in scene["elements"])
    assert kinds.count("palm tree") == 2 and "house" in kinds and "swimming pool" in kinds
    assert "person" not in kinds


def test_a_checklist_find_the_model_then_denies_is_dropped(scene):
    assert not by_kind(scene, "car")


def test_the_measured_light_overrules_and_the_lights_say_dusk(scene):
    tod = scene["environment"]["time_of_day"]
    assert val(tod) in ("dusk", "sunset", "golden hour") and tod["status"] in ("visible", "estimated")


def test_every_value_says_how_it_is_known(scene):
    house = by_kind(scene, "house")[0]
    assert house["position"]["status"] in ("estimated", "inferred") and 0 < house["position"]["confidence"] <= 1
    assert house["color"]["status"] == "visible" and house["color"]["value"].startswith("#")
    assert val(house["details"]["floors"]) == 2
    assert any("far side" in u for u in scene["unknowns"])


def test_things_are_placed_in_metres_where_the_picture_has_them(scene):
    house = by_kind(scene, "house")[0]
    pool = by_kind(scene, "swimming pool")[0]
    palms = sorted(by_kind(scene, "palm tree"), key=lambda e: val(e["position"])[0])
    assert val(pool["position"])[1] < val(house["position"])[1]          # the pool is nearer than the house
    assert val(palms[0]["position"])[0] < 0 < val(palms[1]["position"])[0]  # one palm left, one right
    w, d, h = val(house["size"])
    assert 4 < w < 40 and 3 < h < 20


def test_relationships_follow_the_layout(scene):
    rels = {(r["a"], r["rel"], r["b"]) for r in scene["relationships"]}
    house = by_kind(scene, "house")[0]["id"]
    pool = by_kind(scene, "swimming pool")[0]["id"]
    assert (house, "behind", pool) in rels or (pool, "in_front_of", house) in rels


def test_the_scene_knows_what_naturally_happens_in_it(scene):
    effects = {(b["effect"], b.get("mode")) for b in scene["semantics"]["behaviours"]}
    assert ("water", "ripples") in effects                   # the pool
    assert ("sway", None) in effects                         # light wind said: the palms move


def test_the_description_says_what_was_seen_and_what_is_inferred(scene):
    text = vs.describe(scene)
    assert "palm tree" in text and "inferred" in text


def test_grounding_asks_for_each_building_and_plain_singular_things():
    structures, objects = vs.grounding_labels(
        [{"said": "lights", "kind": None, "count": 6, "importance": "low"},
         {"said": "palm trees", "kind": "palm tree", "count": 3, "importance": "medium"},
         {"said": "house", "kind": "house", "count": 1, "importance": "high"}],
        {"scene_type": vs.F("exterior"), "setting": vs.F("residential"), "water": vs.F([])})
    assert structures[0].startswith("each separate building")
    assert "each palm tree" in objects and "each lamp" in objects
    assert not any("lights" in o or "trees" in o for o in objects)


def test_a_runaway_list_of_specks_is_thrown_away():
    specks = [{"label": "lights", "box": (90, 400 + 12 * k, 98, 410 + 12 * k)} for k in range(30)]
    real = [{"label": "tree", "box": (100, 100, 300, 500)}]
    out = vs.clean_boxes(specks + real + real, (1280, 853))
    assert out == real


def test_a_lamp_on_a_facade_belongs_to_the_building():
    els = [{"id": "e1", "kind": "house", "category": "building", "box": (100, 100, 600, 500), "tags": []},
           {"id": "e2", "kind": "street lamp", "category": "outdoor", "box": (200, 200, 220, 240), "tags": []},
           {"id": "e3", "kind": "street lamp", "category": "outdoor", "box": (700, 100, 720, 520), "tags": []}]
    vs.attach_parts(els)
    assert els[1]["category"] == "part" and els[1]["parent"] == "e1"
    assert els[2]["category"] == "outdoor"
