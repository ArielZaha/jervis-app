"""A picture -> a VisualScene: what is in it, where, how big, made of what, lit how, seen from where — as data a 3D
reconstruction can be built from, every value marked with how it is known.

    IMAGE ─► global read (vision model: kind of place, time, weather, camera, the things in it)
          ─► grounding (vision model: a box for every thing, in the picture's pixels)
          ─► close-ups (vision model, on crops: the details of each important thing)
          ─► measurements (pixels: brightness, warm light, the sky line, each thing's real colour, lit windows)
          ─► fusion (model judgments checked against the pixels; contradictions resolved, confidence lowered)
          ─► camera (lens, horizon -> pitch, height from things of known size)
          ─► geometry (every grounded thing's foot projected onto the ground: metres, not pixels)
          ─► relationships (beside, in front of, behind, part of, on) and semantics (kinds, tags, behaviours)

EVIDENCE. Every value is one of:
    visible   — seen directly (a thing's box, its colour, lit windows)
    estimated — measured from what's visible, with error (a position from its foot, a size from its box)
    inferred  — not visible, reasoned (the far side of a house, a room's depth, a tree's species)
    unknown   — no basis; left to defaults and said so
with a confidence 0..1. Visible evidence always wins over assumptions, and nothing hidden is claimed as seen.

The vision calls are injectable (`asker`) so all the reasoning here is tested without a model."""
import json
import math
import os
import re
import time

import image_analysis
import semantics

VERSION = 1


def F(value, status="estimated", confidence=0.5, note=None) -> dict:
    """One fact with its evidence."""
    out = {"value": value, "status": status, "confidence": round(float(confidence), 2)}
    if note:
        out["note"] = note
    return out


def val(fact, default=None):
    """The value of a fact (or a plain value)."""
    if isinstance(fact, dict) and "value" in fact and "status" in fact:
        return fact["value"] if fact["value"] is not None else default
    return default if fact is None else fact


# ---------- prompts ----------

GLOBAL_PROMPT = """You are analysing a photo so a 3D artist can rebuild it exactly in Blender. Look carefully. Answer ONLY with this JSON:
{
 "scene_type": "exterior | interior | landscape | street",
 "setting": "residential | commercial | natural | urban | coastal | rural",
 "summary": "one factual sentence",
 "time_of_day": "morning | day | afternoon | golden hour | sunset | dusk | night",
 "sky": "clear | partly cloudy | cloudy | overcast | not visible",
 "weather": "clear | cloudy | fog | mist | rain | snow | storm",
 "wind": "none | light | strong",
 "sun_direction": "left | right | behind camera | in front of camera | above | not visible",
 "shadows": "hard | soft | none",
 "artificial_lights_on": true or false,
 "where_lights_glow": ["..."],
 "camera_height": "ground level | eye level | elevated | aerial",
 "camera_pitch": "looking up | level | slightly down | steeply down",
 "lens": "wide | normal | telephoto",
 "horizon_height": number 0-1 from the top of the image, or null if hidden,
 "main_subject": "...",
 "subject_distance_m": rough distance from the camera to the main subject in metres,
 "view_of_main_subject": "front | front-left corner | front-right corner | left side | right side | back | above",
 "things": [{"kind": "singular noun (house, swimming pool, palm tree, car, sofa, street lamp...)", "count": number, "importance": "high | medium | low"}],
 "water": ["ocean | lake | river | waterfall | pool | pond | none"],
 "atmosphere": "clear | haze | fog | mist | smoke",
 "ground": ["grass | sand | soil | rock | concrete | asphalt | tiles | wood floor | carpet | water"]
}
List every distinct kind of thing that matters to rebuild the scene in "things" — buildings, water, terrain, plants,
vehicles, furniture, lights, signs. Only describe what is visible."""

DETAIL_PROMPTS = {
    "building": """This crop shows one building ({label}) from a photo. For a 3D rebuild, answer ONLY with JSON:
{
 "style": "modern | contemporary | traditional | cottage | brick | farmhouse | japanese | classical | industrial | commercial",
 "floors": number of storeys,
 "roof": "flat | gable | hip | shed | mansard | none visible",
 "wall_material": "plaster | concrete | brick | stone | wood | glass | metal | tiles",
 "wall_color": "colour",
 "roof_color": "colour",
 "glass_share": "how much of the visible facade is glass: none | some | half | most",
 "windows_across": number of windows side by side on the facing wall (per floor),
 "door_position": "left | center | right | not visible",
 "balconies": true or false,
 "overhangs": true or false,
 "garage": true or false,
 "facing": "front faces the camera | camera sees its left corner | camera sees its right corner | side",
 "details": ["notable features: canopy, awning, columns, railings, trim, chimney, terrace, planters..."],
 "lit_windows": "none | few | half | most"
}""",
    "shop": """This crop shows a shop / storefront ({label}). For a 3D rebuild, answer ONLY with JSON:
{
 "business": "restaurant | cafe | shop | bar | market stall | bakery | other",
 "floors": number of storeys,
 "facade_material": "wood | plaster | concrete | brick | glass | metal | stone",
 "facade_color": "colour",
 "roof": "flat | gable | tiled eaves | none visible",
 "storefront": "how the ground floor looks: open front | large display windows | door and windows | shutters",
 "shop_windows": number of display windows,
 "door_position": "left | center | right",
 "awning": true or false,
 "signs": number of signs, "sign_text": "text if readable",
 "lanterns": number of hanging lanterns or lamps,
 "goods_on_display": true or false,
 "interior_visible": true or false,
 "lit": "dark | dim | bright",
 "light_color": "warm | neutral | cool",
 "details": ["..."]
}""",
    "pool": """This crop shows a swimming pool ({label}). Answer ONLY with JSON:
{"shape": "rectangle | infinity edge | kidney | round | L-shape", "water_color": "colour", "deck_material": "stone | wood | tiles | concrete",
 "deck_color": "colour", "lit": true or false, "loungers": number, "umbrellas": number, "length_to_width": number}""",
    "vehicle": """This crop shows a vehicle ({label}). Answer ONLY with JSON:
{"type": "sedan | suv | hatchback | pickup | van | sports car | truck | scooter | bicycle", "color": "colour",
 "facing": "toward camera | away from camera | left | right | front-left | front-right | rear-left | rear-right",
 "parked": true or false, "on": "driveway | road | grass | parking lot | sand | other"}""",
    "tree": """This crop shows plants ({label}). Answer ONLY with JSON:
{"type": "palm | pine | deciduous | conifer | tree fern | shrub | hedge | flowers | grass", "leaning": "upright | slightly | strongly",
 "leans_toward": "left | right | toward camera | away from camera | none",
 "foliage_color": "colour", "height_class": "small | medium | tall", "count": number of separate plants, "moving_in_wind": true or false}""",
    "water": """This crop shows water ({label}). Answer ONLY with JSON:
{"kind": "ocean | sea | lake | river | waterfall | pool | pond", "surface": "calm | rippled | waves | rough | falling | rushing",
 "color": "colour", "clarity": "clear | murky", "flow_direction": "toward camera | away | left | right | down | none", "foam": true or false}""",
    "room": """This photo shows an interior. For a 3D rebuild, answer ONLY with JSON:
{"room_type": "living room | bedroom | kitchen | dining room | office | other", "width_m": number, "depth_m": number, "ceiling_height_m": number,
 "wall_color": "colour", "wall_material": "plaster | wood | brick | concrete | tiles", "floor_material": "wood | tiles | carpet | concrete | stone",
 "floor_color": "colour", "windows": [{"wall": "back | left | right", "size": "small | large | full height"}],
 "ceiling_lights": true or false, "lamps_on": true or false, "light_from": "windows | lamps | both",
 "style": "modern | traditional | rustic | minimal | other"}""",
    "furniture": """This crop shows furniture ({label}). Answer ONLY with JSON:
{"type": "...", "material": "fabric | leather | wood | metal | glass | plastic | stone", "color": "colour",
 "facing": "toward camera | away | left | right", "seats": number or null}""",
}

DETAIL_FOR = {"house": "building", "villa": "building", "building": "building", "garage": "building",
              "shop": "shop", "swimming pool": "pool", "car": "vehicle", "truck": "vehicle", "scooter": "vehicle",
              "palm tree": "tree", "tree": "tree", "pine tree": "tree", "bush": "tree", "forest": "tree",
              "ocean": "water", "lake": "water", "river": "water", "waterfall": "water", "pond": "water",
              "sofa": "furniture", "armchair": "furniture", "table": "furniture", "coffee table": "furniture",
              "bed": "furniture", "shelf": "furniture"}

MAX_DETAIL_CROPS = 3
MAX_GROUND_KINDS = 12


class Asker:
    """The vision model, as visual_scene uses it (replaceable in tests). Its answers about a picture are kept (by
    the picture's content and the exact question), so the same picture asked again — or re-reasoned after Jervis
    is updated — costs nothing; a different picture, question or model is asked afresh."""

    def __init__(self, cache=True):
        self.cache = cache
        self._mem = {}

    def _store(self, img):
        import hashlib
        import paths
        digest = hashlib.sha1(img.tobytes()[:4_000_000] + str(img.size).encode()).hexdigest()[:20]
        folder = os.path.join(paths.DATA_DIR, "vision_cache")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f"{digest}.json")

    def _cached(self, img, key, fn):
        if not self.cache:
            return fn()
        import vision
        path = self._store(img)
        if path not in self._mem:
            try:
                with open(path, encoding="utf-8") as f:
                    self._mem[path] = json.load(f)
            except (OSError, ValueError):
                self._mem[path] = {}
        key = f"{vision.model()}|{key}"
        if key in self._mem[path]:
            return self._mem[path][key]
        value = fn()
        self._mem[path][key] = value
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._mem[path], f)
        except OSError:
            pass
        return value

    def ask_json(self, img, prompt, crop=None):
        import vision
        return self._cached(img, f"ask|{prompt}|{crop}", lambda: vision.ask_json(img, prompt, crop=crop))

    def ground(self, img, labels, crop=None):
        import vision
        return self._cached(img, f"ground|{labels}|{crop}", lambda: vision.ground(img, labels, crop=crop))


# ---------- the whole analysis ----------

def analyze(path: str, asker=None, progress=None) -> dict:
    """The VisualScene of the picture at `path`. Raises vision.VisionUnavailable when there's no vision model."""
    from PIL import Image
    asker = asker or Asker()
    say = progress or (lambda text: None)
    started = time.time()
    img = Image.open(path)
    img.load()
    img = img.convert("RGB")
    W, H = img.size
    st = image_analysis.stats(img)
    sky = image_analysis.sky_rows(img)
    say("Looking at the whole picture…")
    g = asker.ask_json(img, GLOBAL_PROMPT) or {}
    environment = fuse_environment(g, st)
    things_said = _things_list(g)
    say("Finding where everything is…")
    structures, objects = grounding_labels(things_said, environment)
    raw_boxes = []
    timings = {"global": round(time.time() - started, 1)}
    for labels in [structures] + _chunks(objects, 4):
        if labels:
            t0 = time.time()
            raw_boxes += clean_boxes(asker.ground(img, labels) or [], (W, H))
            timings.setdefault("grounding", []).append(round(time.time() - t0, 1))
    elements = build_elements(raw_boxes, things_said, (W, H), img, environment)
    elements = verify_unlisted(elements, things_said, img, asker)
    debug = {"global": g, "grounding_labels": [structures, objects], "boxes": raw_boxes}
    say("Looking closely at the main things…")
    for el in sorted(elements, key=lambda e: -_detail_order(e))[:MAX_DETAIL_CROPS]:
        prompt_key = "room" if el["kind"] == "room" else DETAIL_FOR.get(el["kind"])
        if not prompt_key or semantics.PRIORITY_RANK.get(el["priority"], 1) < 2:
            continue
        crop = None if prompt_key == "room" else _pad(el["box"], (W, H), 0.12)
        t0 = time.time()
        try:
            detail = asker.ask_json(img, DETAIL_PROMPTS[prompt_key].replace("{label}", el["label"]), crop=crop) or {}
        except ValueError:
            detail = {}
        timings.setdefault("details", []).append(round(time.time() - t0, 1))
        el["details"] = {k: F(v, "visible" if k not in ("floors", "windows_across", "width_m", "depth_m",
                                                        "ceiling_height_m", "length_to_width") else "estimated",
                              0.6) for k, v in detail.items() if v not in (None, "", [], "not visible")}
    if environment["scene_type"]["value"] == "interior" and not any(e["kind"] == "room" for e in elements):
        try:
            detail = asker.ask_json(img, DETAIL_PROMPTS["room"]) or {}
        except ValueError:
            detail = {}
        elements.append(_room_element(detail, (W, H)))
    attach_parts(elements)
    lighting = fuse_lighting(g, st, elements, img)
    reconcile_time(environment, lighting, g, elements)
    camera = estimate_camera(g, (W, H), sky, elements, exif_focal(img), environment)
    place_elements(elements, camera, (W, H), environment)
    relations = relationships(elements)
    scene = {
        "version": VERSION, "source": {"path": os.path.abspath(path), "width": W, "height": H,
                                       "seconds": round(time.time() - started, 1), "timings": timings},
        "summary": str(g.get("summary") or ""), "environment": environment, "lighting": lighting, "camera": camera,
        "elements": elements, "relationships": relations, "measurements": {"stats": st, "sky": {
            k: v for k, v in sky.items() if k != "columns"}}, "debug": debug,
    }
    scene["semantics"] = scene_semantics(scene)
    scene["unknowns"] = unknowns(scene)
    return scene


def _chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)] or [[]]


def _pad(box, size, k):
    W, H = size
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * k, (y2 - y1) * k
    return (max(0, x1 - dx), max(0, y1 - dy), min(W, x2 + dx), min(H, y2 + dy))


def _detail_order(el) -> float:
    return semantics.PRIORITY_RANK.get(el["priority"], 1) * 10 + el["area"] * 10


def exif_focal(img):
    """The lens's 35 mm-equivalent focal length from the photo's EXIF, if it has one (a fact, not a guess)."""
    try:
        exif = img.getexif()
        sub = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
        f35 = sub.get(0xA405) or exif.get(0xA405)
        return float(f35) if f35 and 8 <= float(f35) <= 800 else None
    except Exception:
        return None


# ---------- environment ----------

def _norm(value, allowed, default):
    v = str(value or "").strip().lower()
    for a in allowed:
        if v == a or v.startswith(a) or a in v:
            return a
    return default


def fuse_environment(g: dict, st: dict) -> dict:
    """Kind of place, time, weather, wind, atmosphere — the model's word, checked against the light measured."""
    scene_type = _norm(g.get("scene_type"), ("interior", "exterior", "landscape", "street"), "exterior")
    setting = _norm(g.get("setting"), ("residential", "commercial", "natural", "urban", "coastal", "rural",
                                       "industrial"), "")
    said_time = str(g.get("time_of_day") or "").lower()
    tod, conf = image_analysis.time_of_day(st, said_time)
    tod = semantics.normal_time(tod)
    tod_status = "visible" if conf >= 0.75 else "estimated"
    note = None
    if said_time and semantics.normal_time(said_time) != tod:
        note = f"the model said {said_time!r}; the light measured says {tod}"
    weather = _norm(g.get("weather"), ("storm", "rain", "snow", "fog", "mist", "cloudy", "clear"), "clear")
    sky = _norm(g.get("sky"), ("partly cloudy", "clear", "cloudy", "overcast", "not visible"), "clear")
    if weather == "clear" and sky in ("cloudy", "overcast"):
        weather = "cloudy"
    atmosphere = _norm(g.get("atmosphere"), ("fog", "mist", "haze", "smoke", "clear"), "clear")
    if weather in ("fog", "mist"):
        atmosphere = weather
        weather = "clear"
    wind = _norm(g.get("wind"), ("strong", "light", "none"), "none")
    water = [w for w in (g.get("water") or []) if isinstance(w, str) and w.lower() not in ("none", "")]
    ground = g.get("ground") if isinstance(g.get("ground"), list) else [g.get("ground")] if g.get("ground") else []
    return {
        "scene_type": F(scene_type, "visible", 0.8), "setting": F(setting or None, "estimated", 0.6),
        "time_of_day": F(tod, tod_status, conf, note), "sky": F(sky, "visible", 0.7),
        "weather": F(weather, "visible", 0.7), "wind": F(wind, "inferred" if wind == "none" else "visible", 0.5),
        "atmosphere": F(atmosphere, "visible", 0.6), "water": F(water, "visible", 0.7),
        "ground": F([str(x).lower() for x in ground if x], "visible", 0.6),
        "main_subject": F(g.get("main_subject"), "visible", 0.6),
        "view_of_main_subject": F(g.get("view_of_main_subject"), "estimated", 0.5),
    }


def fuse_lighting(g: dict, st: dict, elements: list, img) -> dict:
    """The light: sun side and height, shadow softness, warmth, which artificial lights are on — with the lit
    windows actually measured in each building."""
    tod = None
    sun = _norm(g.get("sun_direction"), ("left", "right", "behind camera", "in front of camera", "above",
                                         "not visible"), "not visible")
    shadows = _norm(g.get("shadows"), ("hard", "soft", "none"), "soft")
    lit_any = bool(g.get("artificial_lights_on"))
    glows = []
    for el in elements:
        if el["category"] == "building" and el["kind"] != "room":
            w = image_analysis.glowing_windows(img, el["box"])
            el["measured"]["lit_windows"] = w
            if w["lit_share"] > 0.02 and w["patches"] >= 2:
                glows.append(el["id"])
    return {"sun_side": F(sun, "visible" if sun != "not visible" else "unknown", 0.5),
            "shadows": F(shadows, "visible", 0.55),
            "warmth": F(round(st["warmth"], 3), "visible", 0.9),
            "brightness": F(round(st["median"], 3), "visible", 0.95),
            "artificial_on": F(bool(lit_any or glows), "visible" if glows else "estimated", 0.8 if glows else 0.5),
            "where": F([str(x) for x in (g.get("where_lights_glow") or [])], "visible", 0.5),
            "lit_buildings": glows, "time": tod}


def reconcile_time(environment: dict, lighting: dict, g: dict, elements: list) -> None:
    """The time again, now that lit windows are measured: twilight with the lights on (a villa at dusk, glowing
    inside under a still-bright sky) is dusk, not "day" — the brightness of the sky alone said otherwise."""
    tod = environment["time_of_day"]
    said = semantics.normal_time(g.get("time_of_day")) if g.get("time_of_day") else None
    lit = bool(val(lighting["artificial_on"])) or any(
        str(val(e.get("details", {}).get("lit_windows"), "none")) in ("half", "most") for e in elements)
    if lit and val(tod) in ("day", "afternoon", "morning") and said in ("sunset", "dusk", "golden hour", "night"):
        environment["time_of_day"] = F("dusk" if said != "golden hour" else "sunset", "estimated", 0.65,
                                       f"lights are on inside and the model said {said!r}")
    elif lit and val(tod) in ("day",) and lighting["warmth"]["value"] > 0.2:
        environment["time_of_day"] = F("sunset", "estimated", 0.5, "warm light with the lights on")


# ---------- things and where they are ----------

def _things_list(g: dict) -> list:
    out = []
    for t in g.get("things") or []:
        if isinstance(t, str):
            t = {"kind": t}
        if not isinstance(t, dict) or not t.get("kind"):
            continue
        kind = semantics.canonical(t["kind"])
        if kind and semantics.category(kind) in ("ignore",):
            continue
        try:
            count = max(1, min(30, int(t.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1
        out.append({"said": str(t["kind"]).strip(), "kind": kind, "count": count,
                    "importance": _norm(t.get("importance"), ("high", "medium", "low"), "medium")})
    return out


# What a scene of each kind usually holds, asked for even when the first read didn't list it (that read is shallow:
# a villa came back as "house, pool, plants" with loungers, umbrellas and trees in plain view). Things asked for
# only because of this list start less trusted (see build_elements).
CHECKLIST = {
    "residential": ["each individual tree", "each sun lounger", "each umbrella", "each car", "each staircase"],
    "commercial": ["each sign", "each lantern or lamp", "each awning", "each potted plant"],
    "street": ["each car", "each street lamp", "each individual tree", "the sidewalk"],
    "urban": ["each car", "each street lamp", "each individual tree", "the sidewalk"],
    "coastal": ["each individual palm tree", "each rock", "the beach"],
    "natural": ["each individual tree", "each rock", "the river or stream"],
    "interior": ["each sofa", "each armchair", "each table", "each lamp", "each potted plant", "each shelf or cabinet",
                 "the rug", "each window"],
}
_STRUCTURAL = {"building", "sunken", "ground", "path"}


def grounding_labels(things: list, environment: dict) -> tuple:
    """(structures, objects): what to ask the grounding passes to locate. Structures first — each separate building
    (asked that way, a villa's two wings came back as two boxes instead of one), water, ground, roads — then the
    objects, each asked for as individuals ("each individual tree": asked "every tree", the model boxed a whole
    treeline as one). The global read's own words locate best; a short checklist for the setting adds what it
    tends to leave out."""
    structures, objects, seen = [], [], set()
    scene_type = val(environment["scene_type"])
    setting = val(environment["setting"]) or ""

    def add(target, phrase, key):
        if key in seen:
            return
        seen.add(key)
        target.append(phrase)
    listed_building = any(t["kind"] and semantics.category(t["kind"]) == "building" for t in things)
    built_up = scene_type in ("exterior", "street") and setting not in ("natural", "coastal")
    if scene_type != "interior" and (listed_building or built_up):
        # (asked in a forest, the model boxed the whole gully as "a building")
        add(structures, "each separate building (every house, wing, shop or garage gets its own box)", "building")
    for t in sorted(things, key=lambda t: -semantics.PRIORITY_RANK.get(t["importance"], 1)):
        kind = t["kind"]
        if kind in ("sky", "cloud") or (kind and semantics.category(kind) == "ignore"):
            continue
        key = kind or t["said"].lower()
        word = _plain_noun(t["said"])
        if kind and semantics.category(kind) == "building" and scene_type != "interior":
            seen.add(key)   # covered by the separate-buildings question
            continue
        structural = kind and semantics.category(kind) in _STRUCTURAL
        add(structures if structural else objects, (f"the {word}" if structural or t["count"] == 1 else
                                                     f"each {word}"), key)
    for w in val(environment["water"]) or []:
        k = semantics.canonical(w)
        if k:
            add(structures, f"the {w.lower()}", k)
    if scene_type == "street":
        add(structures, "the road", "road")
    for extra in CHECKLIST.get("interior" if scene_type == "interior" else setting, []) +             (CHECKLIST["street"] if scene_type == "street" and setting != "street" else []):
        add(objects, extra, semantics.canonical(extra) or extra)
    return structures[:5], objects[:8]


def _plain_noun(said: str) -> str:
    """A thing's name as a grounding question should say it: singular ("each tree", not "each trees"), without
    vague collective words ("furniture" -> "chair", "lights" -> "lamp")."""
    word = re.sub(r"[^a-z ]+", " ", str(said).lower()).strip()
    word = {"lights": "lamp", "light": "lamp", "furniture": "chair", "plants": "plant", "greenery": "plant",
            "vegetation": "bush", "foliage": "bush", "signs": "sign", "people": "person"}.get(word, word)
    words = word.split()
    if words:
        words[-1] = semantics._singular(words[-1])
    return " ".join(words)


def clean_boxes(boxes: list, size) -> list:
    """A grounding answer cleaned of the model's runaway habits: the same box over and over, and dozens of tiny
    boxes marching down the picture under one label (a loop, not things)."""
    W, H = size
    out = []
    for b in boxes:
        if any(abs(b["box"][i] - o["box"][i]) < 3 for o in out for i in range(4)
               if all(abs(b["box"][j] - o["box"][j]) < 3 for j in range(4))):
            continue
        out.append(b)
    by_label = {}
    for b in out:
        by_label.setdefault(b["label"], []).append(b)
    keep = []
    for label, group in by_label.items():
        tiny = [b for b in group if (b["box"][2] - b["box"][0]) * (b["box"][3] - b["box"][1]) < 0.0004 * W * H]
        if len(group) > 12 and len(tiny) > 0.6 * len(group):
            continue   # a loop of specks
        keep += group[:20]
    return keep


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _inside_share(inner, outer) -> float:
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = max(1e-6, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return ix * iy / area


def build_elements(boxes: list, things: list, size, img, environment: dict) -> list:
    """One element per grounded box: its kind (from its label, else from the thing it was asked for), category,
    tags, measured colour and brightness, depth layer, priority. Duplicates (two boxes for one thing) are merged;
    people are left out (they're not part of the built scene)."""
    W, H = size
    scene_type = val(environment["scene_type"])
    elements = []
    listed = {t["kind"] for t in things}
    for b in boxes:
        label = re.sub(r"\s*\(.*$", "", str(b.get("label") or "")).strip()   # an echoed "(every house... )" dropped
        label = re.sub(r"^(?:each |every |the )?(?:individual |separate )?", "", label, flags=re.I) or label
        kind = semantics.canonical(label)
        if kind is None:
            continue
        if kind == "street lamp" and scene_type == "interior":
            kind = "floor lamp"
        if kind == "floor lamp" and scene_type != "interior":
            kind = "street lamp"
        if kind in ("house", "building") and (val(environment["setting"]) == "commercial" or any(
                t["kind"] == "shop" for t in things)):
            kind = "shop"
        if semantics.category(kind) in ("ignore", "sky"):
            continue
        box = tuple(b["box"])
        if any(e["kind"] == kind and _iou(e["box"], box) > 0.7 for e in elements):
            continue
        area = (box[2] - box[0]) * (box[3] - box[1]) / (W * H)
        if area > 0.92 and semantics.category(kind) not in ("ground", "building"):
            continue   # "the tree" boxed as the whole picture: not a placement
        elements.append({"id": f"e{len(elements) + 1}", "label": label, "kind": kind,
                         "category": semantics.category(kind), "tags": sorted(semantics.tags(kind)), "box": box,
                         "box_norm": [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4),
                                      round(box[3] / H, 4)],
                         "area": round(area, 4), "status": "visible",
                         "confidence": 0.7 if kind in listed or semantics.category(kind) == "building" else 0.5,
                         "details": {},
                         "measured": {}, "parent": None})
    for el in elements:
        region = image_analysis.region(img, el["box"])
        el["measured"].update({"color": region["color"], "brightness": round(region["brightness"], 3),
                               "glow": round(region["glow_share"], 3)})
        el["color"] = F(region["color"], "visible", 0.75)
        el["depth_layer"] = _depth_layer(el, (W, H))
        el["priority"] = semantics.priority(el["kind"], el["area"], el["depth_layer"])
        el["truncated"] = _truncated(el["box"], (W, H))
    # counts the global read gave but grounding missed are noted (the scene can still say what it doesn't know)
    for t in things:
        found = sum(1 for e in elements if e["kind"] == t["kind"])
        if t["kind"] and found < t["count"] and semantics.category(t["kind"]) not in ("ignore", "sky", "part"):
            for e in elements:
                if e["kind"] == t["kind"]:
                    e.setdefault("missing_siblings", t["count"] - found)
    return elements


VERIFY_PROMPT = """Look at this photo carefully. For each of these kinds of thing, is at least one REALLY visible in the
photo (not just possible)? Answer ONLY with JSON mapping each kind to true or false: {kinds}"""


def verify_unlisted(elements: list, things: list, img, asker) -> list:
    """Things found only because the setting's checklist asked for them (the first read never mentioned them) are
    confirmed with one yes/no question before they are believed: asked "each car", the model boxed a car on a
    villa's lawn where there was none."""
    listed = {t["kind"] for t in things}
    listed_cats = {semantics.category(k) for k in listed if k}
    unlisted = sorted({e["kind"] for e in elements if e["kind"] not in listed and e["category"] not in
                       ("ground", "part", "path") and not (e["category"] == "building" and "building" in listed_cats)})
    if not unlisted:
        return elements
    try:
        answer = asker.ask_json(img, VERIFY_PROMPT.replace("{kinds}", json.dumps(unlisted))) or {}
    except Exception:
        answer = {}
    keep = []
    for e in elements:
        if e["kind"] in unlisted:
            said = answer.get(e["kind"])
            if said is None:   # keys in the model's own words ("sun loungers")
                said = next((v for k, v in answer.items() if semantics.canonical(k) == e["kind"]), None)
            if said is False or str(said).lower() == "false":
                continue
            if said is None:
                e["confidence"] = min(e["confidence"], 0.4)
        keep.append(e)
    return keep


def _depth_layer(el, size) -> str:
    W, H = size
    bottom = el["box"][3] / H
    if el["area"] > 0.25 or bottom > 0.9:
        return "foreground"
    if bottom < 0.55 and el["area"] < 0.05:
        return "background"
    return "midground"


def _truncated(box, size) -> dict:
    W, H = size
    m = 3
    return {"left": box[0] <= m, "right": box[2] >= W - m, "top": box[1] <= m, "bottom": box[3] >= H - m}


def attach_parts(elements: list) -> None:
    """Windows, doors, balconies, signs and awnings belong to the building that holds them (the one whose box holds
    most of theirs) — they move, scale and light with it. So do lamps and lanterns seen against a building's face
    (fixtures on it, not street lamps standing on their own)."""
    buildings = [e for e in elements if e["category"] == "building"]
    for el in elements:
        if el["kind"] in ("street lamp", "lantern", "floor lamp") and buildings:
            best = max(buildings, key=lambda b: _inside_share(el["box"], b["box"]))
            if _inside_share(el["box"], best["box"]) > 0.7 and el["box"][3] < best["box"][3] - 0.02 * (
                    best["box"][3] - best["box"][1]):
                el["category"] = "part"
                el["tags"] = sorted(set(el["tags"]) | {"part_of_building"})
    for el in elements:
        if el["category"] != "part" or not buildings:
            continue
        best = max(buildings, key=lambda b: _inside_share(el["box"], b["box"]))
        if _inside_share(el["box"], best["box"]) > 0.5:
            el["parent"] = best["id"]
            best.setdefault("parts", []).append(el["id"])


def _room_element(detail: dict, size) -> dict:
    W, H = size
    return {"id": "room", "label": "room", "kind": "room", "category": "building", "tags": sorted(semantics.tags("room")),
            "box": (0, 0, W, H), "box_norm": [0, 0, 1, 1], "area": 1.0, "status": "inferred", "confidence": 0.6,
            "details": {k: F(v, "estimated", 0.5) for k, v in (detail or {}).items() if v not in (None, "", [])},
            "measured": {}, "parent": None, "depth_layer": "background", "priority": "high",
            "truncated": {"left": True, "right": True, "top": True, "bottom": True}}


# ---------- the camera ----------

LENS_HFOV = {"wide": 74.0, "normal": 54.0, "telephoto": 24.0}
HEIGHT_CLASS = {"ground level": (0.5, 0.2, 1.0), "eye level": (1.6, 1.1, 2.4), "elevated": (6.0, 2.5, 20.0),
                "aerial": (40.0, 15.0, 300.0)}
PITCH_CLASS = {"looking up": -8.0, "level": 0.0, "slightly down": 8.0, "steeply down": 35.0}


def estimate_camera(g: dict, size, sky: dict, elements: list, exif_f35=None, environment=None) -> dict:
    """Lens, horizon, pitch and height of the camera that took the picture.
    - Lens: EXIF if the photo has it (a fact), else the model's class (wide/normal/telephoto); interiors are wide.
    - Horizon: the model's line, checked against the sky line at the picture's sides, a level sea line, and the
      rule that things standing on the ground have their feet BELOW the horizon (for a camera above them).
    - Pitch: from where the horizon sits (above the middle = looking down).
    - Height: from things of known size (a door is ~2.1 m, a car ~1.45 m, a storey ~3 m): with the horizon and lens
      known, the ratio of a thing's foot and head angles gives the camera height. Their median, within the range of
      the model's height class."""
    W, H = size
    scene_type = val((environment or {}).get("scene_type"), "exterior")
    lens_class = _norm(g.get("lens"), ("wide", "normal", "telephoto"), "wide" if scene_type == "interior" else "normal")
    if exif_f35:
        hfov = math.degrees(2 * math.atan(36.0 / (2 * exif_f35))) if W >= H else \
            math.degrees(2 * math.atan(24.0 / (2 * exif_f35)))
        lens = F(round(exif_f35, 1), "visible", 0.95, "from the photo's EXIF")
    elif scene_type == "interior":
        # rooms are photographed wide (~20 mm) whatever the model calls it: read as 'normal', a room's back chairs
        # stood 15 m away
        hfov = 84.0
        lens = F(round(18.0 / math.tan(math.radians(hfov / 2)), 1), "estimated", 0.5, "a room, photographed wide")
    else:
        hfov = LENS_HFOV[lens_class]
        lens = F(round(18.0 / math.tan(math.radians(hfov / 2)), 1), "estimated", 0.45, f"a {lens_class} lens")
        measured = _lens_from_subject(g, elements, (W, H))
        if measured is not None:   # the subject's known height, seen from its distance, spans this much of the frame
            hfov = measured
            lens = F(round(18.0 / math.tan(math.radians(hfov / 2)), 1), "estimated", 0.55,
                     "from the main subject's size and distance (the model said " + lens_class + ")")
    f = (W / 2) / math.tan(math.radians(hfov / 2))
    vfov = math.degrees(2 * math.atan((H / 2) / f))

    height_class = _norm(g.get("camera_height"), tuple(HEIGHT_CLASS), "eye level")
    pitch_class = _norm(g.get("camera_pitch"), tuple(PITCH_CLASS), "level")
    if height_class == "ground level" and pitch_class != "looking up":
        # photos of streets, shops and houses are taken standing up; "ground level" from the model is far more
        # often wrong than right, and a camera half a metre up puts the scene's things far too close
        height_class = "eye level"
    candidates = []
    hz = g.get("horizon_height")
    try:
        hz = float(hz) if hz is not None else None
    except (TypeError, ValueError):
        hz = None
    if hz is not None and 0.0 <= hz <= 1.0:
        candidates.append((hz, 0.4, "model"))
    if sky.get("level_line") is not None:
        candidates.append((sky["level_line"], 0.6, "level line"))
    if sky.get("sides") is not None and sky.get("share", 0) > 0.15:
        candidates.append((sky["sides"], 0.45, "sky line"))
    # open water reaching across the picture meets the sky AT the horizon: its top edge is the best evidence there is
    for e in elements:
        if e["kind"] in ("ocean", "lake") and (e["box"][2] - e["box"][0]) > 0.55 * W and not e["truncated"]["top"]:
            candidates.append((e["box"][1] / H, 0.9, "sea line"))
            break
    from_pitch = 0.5 - math.tan(math.radians(PITCH_CLASS[pitch_class])) * f / H
    candidates.append((from_pitch, 0.25, "pitch class"))
    # With no sky to see, the things themselves say where eye level is (the camera ~h0 up):
    h0 = HEIGHT_CLASS[height_class][0]
    main = _main_element(g, elements)
    if main is not None and not main["truncated"]["bottom"] and height_class == "eye level":
        foot = main["box"][3]
        known = _known_height(main)
        if known:   # its head and foot, its known height: eye level is h0/known of the way up from its foot
            top = main["box"][1] if not main["truncated"]["top"] else 0.0
            candidates.append(((foot - (foot - top) * h0 / known) / H, 0.35 if main["truncated"]["top"] else 0.55,
                               "known height"))
        try:
            dist = float(g.get("subject_distance_m"))
        except (TypeError, ValueError):
            dist = None
        if dist and 1.0 < dist < 2000:   # its foot is h0 below eye level, seen from that far away
            candidates.append(((foot - f * h0 / dist) / H, 0.3, "subject distance"))
    horizon, spread, used = fuse_horizon(candidates)
    # feet of grounded things lie below the horizon (camera above the ground): the horizon must clear the highest
    # foot of anything standing on the ground in the mid/foreground
    feet = [e["box"][3] / H for e in elements if e["category"] in ("building", "outdoor", "furniture", "sunken")
            and not e["truncated"]["bottom"] and e["depth_layer"] != "background"
            and not set(e["tags"]) & {"hanging", "part_of_building"}]
    if feet and height_class != "ground level":
        highest_foot = min(feet)
        if horizon > highest_foot - 0.02:
            horizon = highest_foot - 0.04
            spread = max(spread, 0.1)
    horizon = max(-1.5, min(2.5, horizon))
    pitch = math.degrees(math.atan((0.5 - horizon) * H / f))
    h0, hmin, hmax = HEIGHT_CLASS[height_class]
    estimates = []
    for e in elements:
        known = _known_height(e)
        if known is None or e["truncated"]["bottom"] or e["truncated"]["top"]:
            continue
        x_mid = (e["box"][0] + e["box"][2]) / 2
        est = camera_height_from(known, e["box"][3], e["box"][1], x_mid, (W, H), f, pitch)
        # measured beats the model's height class (a villa photographed "at eye level" from 5 m down its slope):
        # only absurd values are dropped
        if est and hmin / 4 <= est <= hmax * 4:
            estimates.append(est)
    if estimates:
        estimates.sort()
        height = estimates[len(estimates) // 2]
        h_fact = F(round(height, 2), "estimated", min(0.75, 0.4 + 0.1 * len(estimates)),
                   f"from {len(estimates)} thing(s) of known size"
                   + ("" if hmin <= height <= hmax else f", not the {height_class} the model said"))
    else:
        height = h0
        h_fact = F(h0, "inferred", 0.35, f"typical for a {height_class} view")
    return {"hfov": F(round(hfov, 2), lens["status"], lens["confidence"]), "vfov": round(vfov, 2), "lens_mm": lens,
            "focal_px": round(f, 2), "horizon": F(round(horizon, 4), "estimated", max(0.25, 0.8 - spread * 2),
                                                   "; ".join(f"{n} {v:.2f}" + ("" if n in used else " (rejected)")
                                                             for v, _, n in candidates)),
            "pitch_deg": F(round(pitch, 2), "estimated", max(0.25, 0.75 - spread * 2)),
            "height_m": h_fact, "height_class": height_class, "yaw_deg": F(0.0, "inferred", 0.5),
            "image_size": [W, H]}


def _lens_from_subject(g, elements, size):
    """The field of view (degrees, horizontal) that makes the main subject — of known height, at the distance the
    model gave, seen at eye level — span as much of the picture as it does; None without those facts, or when the
    answer is implausible. (A shopfront 5 m away filling the frame from pavement to eaves is a wide lens, whatever
    the model's 'normal' said.)"""
    W, H = size
    try:
        dist = float(g.get("subject_distance_m"))
    except (TypeError, ValueError):
        return None
    main = _main_element(g, elements)
    if main is None or main["truncated"]["bottom"] or not (1.0 < dist < 300):
        return None
    known = _known_height(main)
    if not known:
        return None
    h0 = 1.6
    foot, top = main["box"][3], (0.0 if main["truncated"]["top"] else main["box"][1])
    frac = (foot - top) / H
    if frac < 0.3:
        return None   # small in the picture: its size says little about the lens
    span = math.atan(h0 / dist) + math.atan(max(0.1, known - h0) / dist)
    vfov = span / frac
    hfov = math.degrees(2 * math.atan(math.tan(vfov / 2) * W / H))
    return hfov if 20.0 <= hfov <= 100.0 else None


def _main_element(g, elements):
    """The element the picture is about: the model's main subject if it was located, else the most important,
    largest thing standing in it."""
    said = semantics.canonical(g.get("main_subject") or "")
    pool = [e for e in elements if e["category"] not in ("ground", "sky", "part", "path")]
    named = [e for e in pool if said and (e["kind"] == said or semantics.category(e["kind"]) == semantics.category(said)
                                          and semantics.category(said) == "building")]
    pool = named or pool
    if not pool:
        return None
    return max(pool, key=lambda e: (semantics.PRIORITY_RANK.get(semantics.spec(e["kind"]).get("priority", "low"), 1),
                                    e.get("area", 0.0)))


def fuse_horizon(candidates):
    """(horizon, spread, names used): a weighted median of the evidence, then the weighted mean of what agrees with
    it — one wild guess (a model's "0.8" against a sea line at 0.6 and a sky line at 0.56) is dropped, not averaged
    in."""
    ordered = sorted(candidates)
    total = sum(w for _, w, _ in ordered)
    acc, median = 0.0, ordered[0][0]
    for v, w, _ in ordered:
        acc += w
        if acc >= total / 2:
            median = v
            break
    keep = [(v, w, n) for v, w, n in ordered if abs(v - median) <= 0.12] or ordered
    horizon = sum(v * w for v, w, _ in keep) / sum(w for _, w, _ in keep)
    spread = max(abs(v - horizon) for v, _, _ in keep)
    return horizon, spread, {n for _, _, n in keep}


def _known_height(el):
    """A thing's real height when it is reliably known (doors, cars, storeys of a building), else None."""
    kind = el["kind"]
    if kind == "door":
        return 2.1
    if kind in ("car",):
        return 1.5
    if kind in ("house", "villa", "building", "shop"):
        floors = val(el.get("details", {}).get("floors"))
        try:
            floors = int(floors)
        except (TypeError, ValueError):
            return None
        if 1 <= floors <= 30:
            roof = str(val(el.get("details", {}).get("roof"), "flat"))
            return floors * 3.1 + (0.6 if roof.startswith("flat") else 2.2)
    return None


def _basis(pitch_deg):
    t = math.radians(pitch_deg)
    F_ = (0.0, math.cos(t), -math.sin(t))
    R = (1.0, 0.0, 0.0)
    U = (0.0, math.sin(t), math.cos(t))
    return R, U, F_


def ground_point(px, py, size, f, pitch_deg, height):
    """Where the picture's pixel (px, py) meets the ground (z=0) for a camera at (0, 0, height) facing +y, pitched
    down by pitch_deg: (x, y) in metres, or None above the horizon."""
    W, H = size
    u, v = px - W / 2, py - H / 2
    R, U, Fw = _basis(pitch_deg)
    d = [Fw[i] + (u / f) * R[i] - (v / f) * U[i] for i in range(3)]
    if d[2] >= -1e-6:
        return None
    t = -height / d[2]
    return (t * d[0], t * d[1])


def project(point, size, f, pitch_deg, height):
    """The pixel a world point (x, y, z) lands on, or None behind the camera."""
    W, H = size
    R, U, Fw = _basis(pitch_deg)
    V = (point[0], point[1], point[2] - height)
    xc = sum(V[i] * R[i] for i in range(3))
    yc = sum(V[i] * U[i] for i in range(3))
    zc = sum(V[i] * Fw[i] for i in range(3))
    if zc <= 1e-6:
        return None
    return (W / 2 + f * xc / zc, H / 2 - f * yc / zc)


def height_at(point_xy, py_top, size, f, pitch_deg, height):
    """How high above the ground (x, y) a thing reaches, if its top shows at pixel row py_top."""
    W, H = size
    v = py_top - H / 2
    t = math.radians(pitch_deg)
    Py = point_xy[1] * math.cos(0)   # distance along the ground (camera faces +y)
    denom = f * math.cos(t) - v * math.sin(t)
    if abs(denom) < 1e-6:
        return None
    w = -Py * (f * math.sin(t) + v * math.cos(t)) / denom
    return height + w


def camera_height_from(known_height, foot_y, top_y, x_mid, size, f, pitch_deg):
    """The camera height that makes a thing of known height, foot at row foot_y and top at row top_y, that tall."""
    p = ground_point(x_mid, foot_y, size, f, pitch_deg, 1.0)
    if p is None:
        return None
    z1 = height_at(p, top_y, size, f, pitch_deg, 1.0)   # its height, were the camera 1 m up
    if z1 is None or z1 <= 0.05:
        return None
    return known_height / z1


def place_elements(elements: list, camera: dict, size, environment: dict) -> None:
    """Every element's position and size in metres, in the camera's frame (camera at (0, 0, height) facing +y):
    standing things from their foot on the ground; things whose foot is cut off or above the horizon from their
    usual size; the far side of anything (its depth) inferred from its kind. Each value says how it was found."""
    W, H = size
    f = camera["focal_px"]
    pitch = val(camera["pitch_deg"], 0.0)
    height = val(camera["height_m"], 1.6)
    horizon_px = val(camera["horizon"], 0.5) * H
    for el in elements:
        if el["category"] == "part" or el["kind"] == "room":
            continue
        x1, y1, x2, y2 = el["box"]
        tw, td, th = semantics.typical_size(el["kind"])
        status, conf = "estimated", 0.6
        foot = None
        band = _is_band(el)
        if _is_wall(el):
            el["wall"] = True
        if (not el["truncated"]["bottom"] or band) and y2 > horizon_px + 2 and el["category"] not in ("sky",):
            foot = ground_point((x1 + x2) / 2, y2, size, f, pitch, height)
        if foot is not None and foot[1] > 0.3:
            # the box's bottom is its nearest edge on the ground; its middle is half its depth further on
            left = ground_point(x1, y2, size, f, pitch, height)
            right = ground_point(x2, y2, size, f, pitch, height)
            width = abs(right[0] - left[0]) if left and right else tw
            top = height_at(foot, y1, size, f, pitch, height)
            tall = max(0.05, top) if top is not None else th
            if el["category"] in ("ground", "path", "sunken") or band:
                tall = th
            if el["truncated"]["left"] or el["truncated"]["right"]:
                width = max(width, tw)
                conf -= 0.15
            if el["truncated"]["top"]:
                if "vegetation" in el.get("tags", []) and top is not None:
                    # a plant touching the top of the frame: its crown is mostly there (a palm's fronds at the
                    # edge) — a little beyond what shows, not its kind's full height (that put the crowns of the
                    # beach's palms out of the picture)
                    tall = max(tall, min(th, tall * 1.3))
                else:
                    tall = max(tall, th)
                conf -= 0.15
            depth = _depth_for(el["kind"], width, (tw, td, th))
            if el["category"] in ("ground", "sunken", "path") or band:
                far = ground_point((x1 + x2) / 2, max(y1, horizon_px + 3), size, f, pitch, height)
                depth = max(0.5, (far[1] - foot[1])) if far else depth
                if band and el["category"] not in ("ground", "sunken", "path"):
                    # rocks or planting reaching up to the horizon line are a foreground bed seen in perspective,
                    # not a strip running to infinity; and it widens with distance as the view does
                    depth = min(depth, 40.0)
                    width = max(width, (x2 - x1) / f * (foot[1] + depth / 2))
            cx_ = foot[0]
            if not band and left and right and el["truncated"]["right"] != el["truncated"]["left"]:
                # cut off by one side of the frame: the edge we see is where it starts, the rest lies beyond the
                # frame (centred on its visible sliver, a neighbour's house stood across the view in front of the
                # villa)
                cx_ = left[0] + width / 2 if el["truncated"]["right"] else right[0] - width / 2
            pos = (cx_, foot[1] + depth / 2)
        else:
            # cut off at the bottom, or beyond the horizon: from its usual size (how big it looks says how far)
            px_h = max(4.0, y2 - y1)
            dist = f * th / px_h
            if el["category"] in ("ground", "sky"):
                dist = max(dist, 60.0)
            cx = (x1 + x2) / 2 - W / 2
            pos = (cx / f * dist, dist)
            width = max(0.3, (x2 - x1) / f * dist)
            tall = th
            depth = _depth_for(el["kind"], width, (tw, td, th))
            status, conf = "inferred", 0.35
        if el.get("wall") and foot is not None:   # a forest wall: as wide as it looks, 15 m deep, from its foot
            depth, tall = 15.0, max(tall, 8.0)
            pos = (foot[0], foot[1] + depth / 2)
        # a size far from anything real for its kind is more likely a bad box than a giant: pull it toward usual
        if not band and not el.get("wall"):
            width, depth, tall = _plausible(el["kind"], width, depth, tall)
        el["position"] = F([round(pos[0], 2), round(pos[1], 2), 0.0], status, conf)
        el["size"] = F([round(width, 2), round(depth, 2), round(tall, 2)], status, max(0.2, conf - 0.1),
                       "depth inferred from its kind" if el["category"] not in ("ground", "sunken", "path") else None)
        el["distance_m"] = round(math.hypot(pos[0], pos[1]), 1)


def _is_band(el) -> bool:
    """A strip of planting (or grass, or rocks) running across the picture's foreground (or in from one side, under
    the camera): not one thing but an area, placed like ground. (Cut off at the top too, it's a wall of trees instead: see _is_wall.)"""
    t = el.get("truncated", {})
    across = (t.get("left") and t.get("right")) or (t.get("bottom") and (t.get("left") or t.get("right")))
    return ("vegetation" in el.get("tags", []) or el["kind"] in ("rock", "bush")) and el["area"] > 0.12 and \
        bool(across) and not t.get("top")


def _is_wall(el) -> bool:
    """Vegetation filling the picture from its top down to where it meets the ground: the forest behind a waterfall
    or around a clearing — trees standing at its foot, not ground cover running to the horizon."""
    t = el.get("truncated", {})
    return "vegetation" in el.get("tags", []) and el["area"] > 0.2 and t.get("top") and \
        (t.get("left") or t.get("right"))


def _depth_for(kind, width, typical):
    tw, td, th = typical
    if kind in ("house", "villa", "building", "shop", "garage"):
        return max(td * 0.6, min(td * 1.6, width * td / max(tw, 0.1)))
    return td * max(0.5, min(2.0, width / max(tw, 0.1)))


def _plausible(kind, width, depth, tall):
    tw, td, th = semantics.typical_size(kind)
    lo, hi = 0.35, 3.5
    if kind in ("house", "villa", "building", "shop"):
        lo, hi = 0.4, 4.0
    if kind in ("ocean", "lake", "beach", "lawn", "terrain", "hill", "forest", "road", "sidewalk", "path", "river"):
        return width, depth, tall
    def clamp(v, t):
        return max(t * lo, min(t * hi, v)) if t > 0 else v
    return clamp(width, tw), clamp(depth, td), clamp(tall, th) if th > 0 else tall


# ---------- relationships ----------

def relationships(elements: list) -> list:
    """How the things stand to each other: part_of (a window of a building), beside / left_of / right_of,
    in_front_of / behind (nearer / farther), near, on (a car on a road, a lounger by a pool), around."""
    out = []
    placed = [e for e in elements if e.get("position")]
    for e in elements:
        if e.get("parent"):
            out.append({"a": e["id"], "rel": "part_of", "b": e["parent"], "status": "visible", "confidence": 0.7})
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            if a["category"] in ("ground", "sky") or b["category"] in ("ground", "sky"):
                continue
            pa, pb = val(a["position"]), val(b["position"])
            dx, dy = pb[0] - pa[0], pb[1] - pa[1]
            dist = math.hypot(dx, dy)
            sa, sb = val(a["size"]), val(b["size"])
            reach = (max(sa[0], sa[1]) + max(sb[0], sb[1])) / 2
            if dist > reach + 12:
                continue
            if abs(dx) >= abs(dy):
                rel = "left_of" if dx > 0 else "right_of"   # a is left of b when b is to its right
            else:
                rel = "in_front_of" if dy > 0 else "behind"  # a is nearer the camera than b
            out.append({"a": a["id"], "rel": rel, "b": b["id"], "status": "estimated", "confidence": 0.55,
                        "distance": round(dist, 1)})
            if dist < reach + 3:
                out.append({"a": a["id"], "rel": "near", "b": b["id"], "status": "estimated", "confidence": 0.6})
    by_id = {e["id"]: e for e in elements}
    for e in elements:   # furniture by a pool, cars on a road/driveway
        if e["kind"] in ("sun lounger", "umbrella") and any(x["kind"] == "swimming pool" for x in elements):
            pool = next(x for x in elements if x["kind"] == "swimming pool")
            out.append({"a": e["id"], "rel": "around", "b": pool["id"], "status": "inferred", "confidence": 0.6})
        if e["kind"] in ("car", "truck"):
            for r in elements:
                if r["kind"] in ("road", "path") and _inside_share(_foot_box(e), r["box"]) > 0.5:
                    out.append({"a": e["id"], "rel": "on", "b": r["id"], "status": "visible", "confidence": 0.6})
                    break
    return [r for r in out if r["a"] in by_id and r["b"] in by_id]


def _foot_box(e):
    x1, y1, x2, y2 = e["box"]
    return (x1, y2 - (y2 - y1) * 0.15, x2, y2)


# ---------- semantics and honesty ----------

def scene_semantics(scene: dict) -> dict:
    """The scene's context and the natural behaviours it implies (semantics.RULES), from what was seen."""
    env = scene["environment"]
    things = [{"name": e["id"], "kind": e["kind"]} for e in scene["elements"]]
    setting = val(env["setting"]) or ""
    if any(e["kind"] in ("ocean", "beach") for e in scene["elements"]):
        setting = "coastal"
    ctx = semantics.context_of(things, {
        "time_of_day": val(env["time_of_day"]), "weather": val(env["weather"]), "wind": val(env["wind"]),
        "atmosphere": val(env["atmosphere"]), "setting": setting, "scene_type": val(env["scene_type"]),
        "evidence": {"lit_windows": bool(scene["lighting"]["lit_buildings"])}})
    return {"context": {k: v for k, v in ctx.items() if k not in ("kinds", "tags")},
            "kinds": ctx["kinds"], "behaviours": semantics.behaviours(ctx)}


def unknowns(scene: dict) -> list:
    """What the picture can't tell, said plainly (and filled with believable inferences, not claims)."""
    out = []
    for e in scene["elements"]:
        if e["category"] in ("building",) and e["kind"] != "room":
            out.append(f"the far side of {e['label']} (built to match its visible front)")
        if e.get("truncated", {}).get("left") or e.get("truncated", {}).get("right"):
            out.append(f"how far {e['label']} continues beyond the picture's edge")
        if e.get("missing_siblings"):
            out.append(f"{e['missing_siblings']} more {e['kind']}(s) mentioned but not located")
    if val(scene["camera"]["height_m"]) and scene["camera"]["height_m"]["status"] == "inferred":
        out.append("the exact camera height (no thing of known size to measure it by)")
    return list(dict.fromkeys(out))[:12]


def describe(scene: dict) -> str:
    """The scene in a few plain sentences, for the user — what was seen, and what is only inferred."""
    env = scene["environment"]
    kinds = {}
    for e in scene["elements"]:
        if e["category"] != "part":
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    listed = ", ".join(f"{n} {k}{'s' if n > 1 and not k.endswith('s') else ''}" if n > 1 else f"a {k}"
                       for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
    cam = scene["camera"]
    text = (f"I see {val(env['scene_type'])} at {val(env['time_of_day'])}"
            + (f" ({val(env['weather'])})" if val(env['weather']) not in ("clear", None) else "")
            + (f": {listed}." if listed else ".")
            + f" Camera about {val(cam['height_m']):.1f} m up, {abs(val(cam['pitch_deg'])):.0f}° "
            + ("down" if val(cam['pitch_deg']) >= 0 else "up") + f", {val(cam['lens_mm']):.0f} mm lens.")
    if scene.get("unknowns"):
        text += " Not visible, so inferred: " + "; ".join(scene["unknowns"][:3]) + "."
    return text
