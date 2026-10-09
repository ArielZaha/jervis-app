"""Seeing a picture: the vision client's handling of the model's answers (boxes in the right pixels however the
model scaled them, JSON that was cut off), and the measurements taken straight from the pixels (night vs day, warm
glowing windows, a region's real colour, how alike two pictures are) — no model needed."""
import json

import pytest
from PIL import Image, ImageDraw

import image_analysis as ia
import vision


# ---------- the model's answers ----------

def test_boxes_come_back_in_the_original_pictures_pixels():
    # the picture was sent at 1288x868 and was originally 2576x1736: everything doubles back
    text = '[{"bbox_2d": [100, 200, 300, 400], "label": "house"}]'
    out = vision.boxes_from(text, (1288, 868), (0, 0, 2.0, 2.0), (2576, 1736))
    assert out == [{"label": "house", "box": (200.0, 400.0, 600.0, 800.0)}]


def test_a_crop_maps_back_to_where_it_was_taken():
    text = '[{"bbox_2d": [0, 0, 100, 50], "label": "door"}]'
    out = vision.boxes_from(text, (1288, 868), (500, 300, 0.5, 0.5), (3000, 2000))
    assert out[0]["box"] == (500.0, 300.0, 550.0, 325.0)


def test_boxes_from_a_scaled_up_frame_are_scaled_back():
    # Ollama upscaled an 896-wide picture: the model answered as if it were 1120 wide (every box 1.25x too big)
    text = ('[{"bbox_2d": [65, 242, 670, 530], "label": "main house"}, '
            '{"bbox_2d": [657, 395, 1120, 525], "label": "second house"}]')
    out = vision.boxes_from(text, (896, 588), (0, 0, 1.0, 1.0), (896, 588))
    main = out[0]["box"]
    assert abs(main[0] - 52) < 2 and abs(main[2] - 536) < 3
    assert all(b["box"][2] <= 896 for b in out)


def test_broken_grounding_json_still_yields_its_boxes():
    text = ('```json\n[{"bbox_2d": [10, 10, 50, 60], "label": "tree"} {"bbox_2d": [70, 10, 90, 40], "label": "tree"},'
            '\n {"bbox_2d": [5, 5')
    out = vision.boxes_from(text, (100, 100), (0, 0, 1, 1), (100, 100))
    assert [b["box"] for b in out] == [(10.0, 10.0, 50.0, 60.0), (70.0, 10.0, 90.0, 40.0)]


def test_degenerate_and_out_of_picture_boxes_are_dropped_or_clamped():
    text = '[{"bbox_2d": [10, 10, 11, 11], "label": "x"}, {"bbox_2d": [-20, 50, 80, 103], "label": "y"}]'
    out = vision.boxes_from(text, (100, 100), (0, 0, 1, 1), (100, 100))
    assert out == [{"label": "y", "box": (0.0, 50.0, 80.0, 100.0)}]   # a few pixels over the edge: clamped


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('Here you go:\n```json\n{"a": [1, 2]}\n```', {"a": [1, 2]}),
    ('{"scene_type": "exterior", "things": [{"kind": "house", "count": 1}, {"kind": "po', None),
    ("no json at all", {}),
])
def test_json_answers_are_read_even_when_cut_off(text, expected):
    out = vision.parse_json(text)
    if expected is None:   # cut off mid-list: what was complete survives
        assert out["scene_type"] == "exterior" and out["things"][0] == {"kind": "house", "count": 1}
    else:
        assert out == expected


def test_pictures_are_sent_at_about_a_megapixel_on_the_patch_grid():
    img = Image.new("RGB", (4000, 3000), "white")
    b64, (w, h), (x0, y0, sx, sy) = vision.prepare(img)
    assert w % 28 == 0 and h % 28 == 0 and max(w, h) <= 1300 and 0.9e6 < w * h < 1.4e6
    assert abs(sx * w - 4000) < 30 and abs(sy * h - 3000) < 30
    small = Image.new("RGB", (640, 427), "white")
    _, (w2, h2), _ = vision.prepare(small)
    assert max(w2, h2) >= 1260   # small pictures are sent big: Ollama would upscale them anyway, and skew the boxes


def test_the_best_installed_vision_model_is_chosen(monkeypatch):
    import local_llm
    monkeypatch.delenv("OLLAMA_VISION_MODEL", raising=False)
    monkeypatch.setattr(local_llm, "installed_models", lambda: ["qwen2.5-coder:7b", "qwen2.5vl:3b", "qwen2.5vl:7b"])
    assert vision.model() == "qwen2.5vl:7b"
    monkeypatch.setattr(local_llm, "installed_models", lambda: ["qwen2.5-coder:7b", "qwen2.5vl:3b"])
    assert vision.model() == "qwen2.5vl:3b"
    monkeypatch.setattr(local_llm, "installed_models", lambda: ["qwen2.5-coder:7b", "llama3.2:latest"])
    assert vision.model() is None   # never a text-only model pretending to see


def test_no_vision_model_is_said_plainly(monkeypatch):
    import local_llm
    monkeypatch.setattr(local_llm, "installed_models", lambda: ["qwen2.5-coder:7b"])
    with pytest.raises(vision.VisionUnavailable):
        vision.ask_json(Image.new("RGB", (64, 64)), "what is this?")


# ---------- measuring pixels ----------

def night_shopfront():
    img = Image.new("RGB", (640, 420), (18, 16, 22))
    d = ImageDraw.Draw(img)
    for x in (80, 260, 440):
        d.rectangle((x, 180, x + 120, 330), fill=(255, 196, 110))   # warm lit windows
    d.rectangle((60, 120, 600, 160), fill=(240, 220, 170))
    return img


def daylight_street():
    img = Image.new("RGB", (640, 420), (120, 170, 230))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 250, 640, 420), fill=(150, 150, 145))
    d.rectangle((100, 120, 300, 300), fill=(210, 200, 190))
    return img


def test_night_is_told_from_day_by_the_light_itself():
    night = ia.stats(night_shopfront())
    day = ia.stats(daylight_street())
    assert night["night_score"] > 0.5 > day["night_score"]
    assert ia.time_of_day(night, "golden hour")[0] in ("night", "dusk")   # the model said golden hour: overruled
    assert ia.time_of_day(day, "night")[0] != "night"                    # a bright picture isn't night
    assert ia.time_of_day(day, "morning") == ("morning", 0.75)           # a plausible word is kept


def test_a_regions_colour_is_its_dominant_colour_not_a_muddy_average():
    img = Image.new("RGB", (100, 100), (200, 30, 30))
    ImageDraw.Draw(img).rectangle((0, 0, 100, 30), fill=(20, 20, 200))
    r = ia.region(img, (0, 0, 100, 100), inner=0.0)
    assert r["color"].startswith("#c8") and r["rgb"][2] < 0.2


def test_a_box_beyond_the_picture_is_still_measured():
    img = daylight_street()
    r = ia.region(img, (700, 500, 650, 450))
    assert r["color"].startswith("#")


def test_lit_windows_are_counted_and_their_variety_measured():
    lit = ia.glowing_windows(night_shopfront(), (40, 100, 620, 360))
    dark = ia.glowing_windows(daylight_street(), (100, 120, 300, 300))
    assert lit["patches"] >= 3 and lit["lit_share"] > 0.1
    assert dark["patches"] == 0


def test_the_sky_line_and_a_level_sea_line_are_found():
    img = Image.new("RGB", (400, 300), (110, 160, 225))
    ImageDraw.Draw(img).rectangle((0, 150, 400, 300), fill=(20, 70, 110))   # the sea, from the middle down
    sky = ia.sky_rows(img)
    assert abs(sky["level_line"] - 0.5) < 0.03
    assert sky["share"] > 0.9


def test_comparing_pictures_scores_the_same_picture_highest():
    a = daylight_street()
    b = night_shopfront()
    same = ia.compare(a, a)
    other = ia.compare(a, b)
    assert same["score"] > 0.95 and same["color_distance"] < 1e-6
    assert other["score"] < same["score"] and other["worst_cells"]
