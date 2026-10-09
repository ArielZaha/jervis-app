"""A VisualScene (what a picture shows, visual_scene.py) -> a plan of verified kit steps that rebuild it in Blender
as real 3D: finished assets chosen and configured from what was seen, placed where they were measured to be, the
camera set up like the photo's, the light and weather matched, and only the natural behaviours the scene justifies
(semantics.RULES). Every step carries the checks that prove it happened; every object is tagged with what it is and
which element of the picture it rebuilds, so later edits can find "the pool" or "the left palm" by meaning.

Pure Python (no Blender): the plan is code for the bridge plus checks, run by the agent's plan -> act -> verify ->
repair loop like any other plan."""
import math
import re

import semantics
import visual_scene
from visual_scene import val

RECONSTRUCT = re.compile(
    r"\b(?:re-?create|rebuild|reconstruct|replicate|reproduce|recreate|model|build|make|create|turn|convert|copy|"
    r"generate|do)\b.{0,40}?\b(?:this|that|the|my|attached|uploaded)\s+(?:image|picture|photo|photograph|pic|scene|"
    r"reference|view|place|render)\b|\b(?:image|picture|photo|this)\s+(?:in|into|as)\s+(?:3d|blender|a 3d scene)\b|"
    r"\bfrom (?:this|the|my) (?:image|picture|photo)\b|\bin 3d\b", re.I)


def is_reconstruction_request(text: str) -> bool:
    """"Recreate this picture in Blender", "turn this photo into a 3D scene", "build what's in the image"."""
    return bool(RECONSTRUCT.search(str(text or "")))


# ---------- choosing and configuring assets ----------

_STYLE = {"modern": "modern", "contemporary": "modern", "minimal": "modern", "traditional": "cottage",
          "cottage": "cottage", "brick": "brick", "farmhouse": "farmhouse", "classical": "brick",
          "japanese": "cottage", "industrial": "modern", "commercial": "modern"}
_WALLS = {"plaster": "plaster", "concrete": "white render", "brick": "brick", "stone": "limestone", "wood": "wood slats",
          "glass": "white render", "metal": "dark metal", "tiles": "white render"}
_COLOR_WORDS = re.compile(r"\b(?:white|black|grey|gray|red|blue|green|yellow|orange|brown|beige|cream|pink|purple|"
                          r"silver|gold|tan|navy|teal|turquoise|dark brown|light brown|dark grey|light grey|charcoal)\b",
                          re.I)


def _lush(scene) -> bool:
    """Green, wet country: the picture is walled with vegetation (or a big part of it is planting) — rock there is
    mossy, the ground forest floor."""
    return any(e.get("wall") or ("vegetation" in e.get("tags", []) and e.get("area", 0) > 0.15)
               for e in scene.get("elements", []))


def _cloud_cover(scene):
    """How clouded the photo's sky is, when it shows one: measured (white and grey against the blue) where the sky
    is big enough to tell, else from what the model said of it ('partly cloudy'); None for a clear or unseen sky."""
    sky = (scene.get("measurements") or {}).get("sky") or {}
    said = str(val(scene["environment"].get("sky"), "") or "").lower()
    measured = sky.get("cloud_cover") if (sky.get("share") or 0) >= 0.3 else None
    if measured is not None and measured >= 0.12:
        return round(min(0.9, max(0.2, measured * 1.3)), 2)
    if "partly" in said or "scattered" in said:
        return 0.35
    if "cloud" in said and measured is None:
        return 0.6
    return None


def _cliff_width(falls):
    """How wide the cliff a waterfall pours over is (blender_motion._cliff: the water's width and 1.6x its height)."""
    _, kw, _ = asset_for(falls, {"environment": {}, "elements": []}, {})
    return kw["width"] + max(6.0, kw["height"] * 1.6), kw["width"]


def _colour(el, detail_key=None):
    """The colour to build with: the model's colour word when it gave a plain one, else the colour measured in the
    picture (a hex code) — but only for things big enough in the picture to measure (a thin parasol's box is mostly
    the sky and wall behind it)."""
    word = str(val(el.get("details", {}).get(detail_key), "") if detail_key else "")
    m = _COLOR_WORDS.search(word)
    if m:
        return m.group(0).lower().replace("gray", "grey")
    if el.get("area", 0) < 0.012:
        return None
    return val(el.get("color")) or None


def _n(value, default, lo=None, hi=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(default)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _rotation(el, scene):
    """Which way a thing turns, from how the picture shows it: a building seen corner-on is turned, a car facing
    left or right is turned that way (fronts face -y, the camera's side, by default)."""
    d = el.get("details", {})
    if el["kind"] in ("car", "truck", "scooter"):
        facing = str(val(d.get("facing"), "")).lower()
        return {"toward camera": -90, "away from camera": 90, "left": 180, "right": 0, "front-left": -135,
                "front-right": -45, "rear-left": 135, "rear-right": 45}.get(facing, 0)
    if el["category"] == "building":
        facing = str(val(d.get("facing"), "")).lower()
        view = str(val(scene["environment"].get("view_of_main_subject"), "")).lower() if el.get("main") else ""
        if "left corner" in facing or "front-left" in view:
            return -12
        if "right corner" in facing or "front-right" in view:
            return 12
    return 0


def asset_for(el, scene, parts_of):
    """(builder, kwargs, summary-word) to rebuild one element — or None when it's not built on its own (a part of a
    building, a person, the sky)."""
    kind, d = el["kind"], el.get("details", {})
    size = val(el.get("size"), list(semantics.typical_size(kind)))
    w, dep, h = (float(v) for v in size)
    if kind in ("house", "villa", "building") and el.get("area", 1) < 0.003 and el.get("depth_layer") == "background":
        # a speck on the horizon: a small, simple building, as big as it looks — not a detailed two-storey house
        return "house", dict(style="modern", floors=1, width=_n(w, 6, 4, 10), depth=_n(dep, 5, 4, 8), path=False), \
            "house"
    if kind in ("house", "villa", "building"):
        style = _STYLE.get(str(val(d.get("style"), "")).lower(), "cottage" if kind == "house" else "modern")
        floors = int(_n(val(d.get("floors")), 2 if kind != "house" else 1, 1, 3))
        glass = str(val(d.get("glass_share"), "")).lower()
        material = str(val(d.get("wall_material"), "")).lower()
        modern_villa = style == "modern" and (glass in ("most", "half") or val(d.get("overhangs")) or
                                              val(d.get("balconies")) or kind == "villa")
        if modern_villa:
            # a long, low block seen whole is usually a main volume and a lower wing
            wings = 2 if el.get("wings") == 2 or (w > 2.4 * max(h, 1.0) and w > 18) else 1
            return "villa", dict(floors=floors, width=_n(w, 20, 10, 40), depth=_n(dep, 11, 7, 20),
                                 wings=wings, glass=glass or "most",
                                 cladding="wood slats" if material in ("wood", "") else _WALLS.get(material, "wood slats"),
                                 walls=_colour(el, "wall_color") if _colour(el, "wall_color") in ("white", None)
                                 else "white render"), "villa"
        roof = str(val(d.get("roof"), "")).lower()
        return "house", dict(style=style, floors=floors, width=_n(w, 9, 5, 20), depth=_n(dep, 7, 4, 16),
                             walls=_WALLS.get(material) if material in ("brick", "stone", "wood") else
                             (_colour(el, "wall_color") or None),
                             roof=roof if roof in ("gable", "hip", "flat") else None,
                             roof_color=_colour(el, "roof_color")), "house"
    if el.get("fills_width"):   # a facade filling the photo's width is at least as wide as the view there
        w = max(w, el["fills_width"])
    if kind == "shop":
        lanterns = sum(1 for p in parts_of.get(el["id"], []) if p["kind"] == "lantern") or \
            int(_n(val(d.get("lanterns")), 0, 0, 8))
        signs = [p for p in parts_of.get(el["id"], []) if p["kind"] == "sign"]
        material = str(val(d.get("facade_material"), "wood")).lower()
        traditional = material in ("wood", "") or "tiled" in str(val(d.get("roof"), "")) or \
            str(val(d.get("business"), "")) in ("restaurant", "market stall")
        return "storefront", dict(width=_n(w, 8, 4, 30), depth=_n(dep, 9, 4, 25),
                                  floors=int(_n(val(d.get("floors")), 2, 1, 5)), facade=material or "wood",
                                  style="traditional" if traditional else "modern",
                                  awning=bool(val(d.get("awning"))) if val(d.get("awning")) is not None else None,
                                  signs=max(1, len(signs) or int(_n(val(d.get("signs")), 1, 1, 4))),
                                  sign_color=(signs[0]["measured"].get("color") if signs else None) or "#f1e4c4",
                                  lanterns=min(6, lanterns),
                                  display=bool(val(d.get("goods_on_display"), True)),
                                  light_color=str(val(d.get("light_color"), "warm"))), "shop"
    if kind == "garage":
        return "garage", dict(width=_n(w, 3.6, 2.8, 9), depth=_n(dep, 6.5, 4.5, 9)), "garage"
    if kind == "shed":
        return "garage", dict(width=_n(w, 3, 2.8, 5), depth=_n(dep, 4.5, 4.5, 6), height=2.4), "shed"
    if kind == "swimming pool":
        ratio = _n(val(d.get("length_to_width")), 2.2, 1.2, 5)
        length = _n(max(w, dep), 9, 4, 30)
        return "pool", dict(length=length, width=_n(min(length / ratio, max(2.5, min(w, dep))), 4, 2.5, 12),
                            deck=True), "swimming pool"
    if kind == "pond":
        return "pond", dict(size=_n(max(w, dep), 4, 2, 15)), "pond"
    if kind == "fountain":
        return "fountain", dict(size=_n(w, 3, 1, 8)), "fountain"
    if kind in ("palm tree", "pine tree", "tree"):
        t = str(val(d.get("type"), "")).lower()
        tk = "palm" if "palm" in t or kind == "palm tree" else "pine" if ("pine" in t or "conifer" in t or
                                                                         kind == "pine tree") else "oak"
        count = int(_n(val(d.get("count")), 1, 1, 60))
        if count >= 5 or (el["area"] > 0.2 and kind == "tree"):
            return "forest", dict(width=_n(w, 30, 8, 200), depth=_n(max(dep, w * 0.3), 12, 4, 80),
                                  count=min(80, max(count, int(w / 3))), kind="tropical" if tk == "palm" else
                                  "mixed" if tk == "oak" else tk), "forest"
        lean = {"strongly": 28, "slightly": 10}.get(str(val(d.get("leaning"), "")).lower(), 0)
        toward = str(val(d.get("leans_toward"), "")).lower()
        lean_dir = "left" if "left" in toward else "right" if "right" in toward else \
            "toward" if "toward" in toward else None
        # (the height seen is upright; a leaning trunk is longer to reach it)
        kw = dict(kind=tk, height=_n(h / math.cos(math.radians(lean)), 7, 2.5, 25), lean=lean or None)
        if lean and lean_dir:
            kw["lean_dir"] = lean_dir
        return "tree", kw, f"{tk} tree"
    if kind == "forest":
        return "forest", dict(width=_n(w, 40, 8, 300), depth=_n(dep, 15, 4, 120), count=int(_n(w * dep / 25, 30, 6, 90)),
                              kind="mixed"), "forest"
    if el.get("wall"):   # a wall of vegetation: a forest standing there
        setting = str(val(scene["environment"].get("setting"), "")).lower()
        t = str(val(d.get("type"), "")).lower()
        fk = "tropical" if ("palm" in t or "fern" in t or setting == "coastal") else "mixed"
        return "forest", dict(width=_n(w, 40, 10, 300), depth=_n(dep, 15, 6, 60),
                              count=int(_n(w * dep / 14, 30, 10, 120)), kind=fk), "forest"
    if kind == "bush" and (w > 8 or el["area"] > 0.12):   # a band of planting, not one bush
        return "forest", dict(width=_n(w, 30, 8, 300), depth=_n(max(dep, 6), 10, 3, 60),
                              count=int(_n(w * max(dep, 6) / 6, 30, 8, 160)), kind="shrubs"), "planting"
    if kind == "bush":
        count = int(_n(val(d.get("count")), 1, 1, 12))
        return "bush", dict(size=_n(max(w, h) / max(1, count ** 0.5), 1.2, 0.4, 3)), "bush"
    if kind == "rock" and el["area"] > 0.1:   # a bed of rocks (a stream's, a shore's): many, not one boulder
        return "forest", dict(width=_n(w, 12, 3, 80), depth=_n(dep, 8, 2, 40), count=int(_n(w * dep / 2.5, 30, 6, 160)),
                              kind="mossy rocks" if _lush(scene) else "rocks"), "rocks"
    if kind == "rock":
        return "rock", dict(size=_n(max(w, dep) / 2, 1, 0.3, 5), count=3 if w > 3 else 1, moss=_lush(scene)), "rock"
    if kind in ("car", "truck"):
        return "car", dict(color=_colour(el, "color") or "#888888", length=_n(max(w, dep), 4.4, 3.2, 5.6),
                           rotation=_rotation(el, scene)), "car"
    if kind == "scooter":
        return None
    if kind == "street lamp":
        return "street_lamp", dict(height=_n(h, 4.5, 2.5, 10)), "street lamp"
    if kind == "lantern":
        return "lantern", dict(height=_n(val(el.get("position"), [0, 0, 0])[2] + 2.6, 2.6, 1.5, 6)), "lantern"
    if kind == "umbrella":
        return "parasol", dict(size=_n(w, 2.6, 1.5, 4), color=_colour(el) or "#f1ece2"), "parasol"
    if kind == "sun lounger":
        return "lounger", dict(), "sun lounger"
    if kind == "bench":
        return "bench", dict(length=_n(w, 1.6, 1, 3)), "bench"
    if kind == "fence":
        return "fence", dict(length=_n(w, 6, 2, 40), height=_n(h, 1.2, 0.6, 2)), "fence"
    if kind == "gate":
        return "gate", dict(width=_n(w, 3.6, 1, 8), height=_n(h, 1.5, 0.8, 2.5)), "gate"
    if kind == "flag":
        return "flag", dict(height=_n(h, 5, 2, 15)), "flag"
    if kind == "campfire":
        return "fire", dict(size=_n(w, 1, 0.5, 3)), "campfire"
    if kind == "cart":
        return "crate", dict(), "crate"
    if kind == "waterfall":
        return "waterfall", dict(height=_n(h, 6, 2, 40), width=_n(w, 2.5, 0.8, 15), moss=_lush(scene)), "waterfall"
    if kind == "river":
        return "river", dict(width=_n(min(w, dep) if min(w, dep) > 1 else 4, 4, 1.5, 30), length=_n(max(w, dep), 40, 15, 200)), "river"
    if kind == "hill":
        return "hills", dict(distance=_n(val(el.get("position"), [0, 150])[1], 150, 60, 3000),
                             width=_n(w, 400, 100, 5000), height=_n(h, 30, 5, 600)), "hills"
    if kind == "chair":
        t = str(val(d.get("type"), "")).lower()
        lounge = any(w in t for w in ("arm", "lounge", "club", "easy", "recliner", "accent"))
        sitting_room = any(e["kind"] == "sofa" for e in scene.get("elements", [])) and \
            not any(e["kind"] in ("table", "desk") for e in scene.get("elements", []))
        if lounge or (not t and sitting_room):   # a chair beside sofas, with no table to sit at, is an armchair
            kind = "armchair"
    if kind in ("sofa", "armchair", "coffee table", "table", "chair", "tv", "shelf", "rug", "floor lamp",
                "potted plant", "bed"):
        builder = {"coffee table": "coffee_table", "floor lamp": "floor_lamp", "potted plant": "potted_plant",
                   "bed": "table"}.get(kind, kind)
        kw = {}
        if kind == "sofa":
            kw = dict(length=_n(w, 2.2, 1.2, 4), color=_colour(el, "color") or None)
        elif kind == "armchair":
            kw = dict(color=_colour(el, "color") or None)
        elif kind in ("coffee table",):
            kw = dict(length=_n(w, 1.2, 0.5, 2.5), top=str(val(d.get("material"), "wood")))
        elif kind == "table":
            kw = dict(length=_n(w, 1.6, 0.5, 5), width=_n(dep, 0.9, 0.4, 2.5))
        elif kind == "shelf":
            kw = dict(width=_n(w, 1.2, 0.4, 4), height=_n(h, 1.8, 0.4, 3))
        elif kind == "rug":
            kw = dict(length=_n(w, 2.4, 0.8, 5), width=_n(dep, 1.7, 0.6, 4))
        elif kind == "tv":
            kw = dict(size=_n(w, 1.3, 0.6, 3))
        elif kind == "floor lamp":
            kw = dict(height=_n(h, 1.6, 0.6, 2.4))
        return builder, kw, kind
    return None


# ---------- the layout, made consistent before anything is built ----------

def _rect(e):
    (x, y, _), (w, d, _) = val(e["position"]), val(e["size"])
    return [x - w / 2, y - d / 2, x + w / 2, y + d / 2]


def _overlap(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _set(e, x=None, y=None, w=None, d=None, note=None):
    pos, size = list(val(e["position"])), list(val(e["size"]))
    if x is not None:
        pos[0] = round(x, 2)
    if y is not None:
        pos[1] = round(y, 2)
    if w is not None:
        size[0] = round(w, 2)
    if d is not None:
        size[1] = round(d, 2)
    e["position"] = dict(e["position"], value=pos)
    e["size"] = dict(e["size"], value=size)
    if note:
        e.setdefault("layout_notes", []).append(note)


def resolve_layout(elements: list) -> None:
    """What the picture shows standing apart must not be built inside each other. The parts measured (a building's
    front, a pool's near edge) are trusted; what was only inferred (how deep a building runs, a pool's width front
    to back) gives way:
    - two buildings that overlap in plan are one complex (a villa and its wing): merged into one, two wings wide;
    - a pool, a terrace's furniture, a car in FRONT of a building (its near edge nearer than the building's front)
      keeps in front: the building's inferred depth starts behind it, never under it;
    - small things still overlapping each other are nudged apart sideways."""
    placed = [e for e in elements if e.get("position") and e["category"] not in ("ground", "sky", "part")]
    buildings = sorted([e for e in placed if e["category"] == "building" and e["kind"] != "room"],
                       key=lambda e: -val(e["size"])[0] * val(e["size"])[1])
    for i, a in enumerate(buildings):
        for b in buildings[i + 1:]:
            if b.get("merged_into") or a.get("merged_into"):
                continue
            ra, rb = _rect(a), _rect(b)
            small = min((ra[2] - ra[0]) * (ra[3] - ra[1]), (rb[2] - rb[0]) * (rb[3] - rb[1]))
            if _overlap(ra, rb) > 0.15 * small:
                lo_x, hi_x = min(ra[0], rb[0]), max(ra[2], rb[2])
                _set(a, x=(lo_x + hi_x) / 2, w=hi_x - lo_x, note=f"merged with {b['id']} (one complex, two wings)")
                a["wings"] = 2
                b["merged_into"] = a["id"]
    for b in buildings:
        if b.get("merged_into"):
            continue
        rb = _rect(b)
        front_of_b = rb[1]
        for e in placed:
            if e is b or e["category"] == "building" or e.get("merged_into"):
                continue
            re_ = _rect(e)
            if _overlap(re_, rb) <= 0:
                continue
            near_e = re_[1]
            if near_e < front_of_b + 1.0:      # it stands in front: share the overlap — it comes forward a
                ov = re_[3] + 0.6 - front_of_b  # little, the building's inferred front goes back a little
                if ov > 0:
                    ey = val(e["position"])[1]
                    _set(e, y=ey - ov * 0.6, note=f"kept in front of {b['id']}")
                    new_front = front_of_b + ov * 0.4
                    depth = max(4.0, rb[3] - new_front)
                    _set(b, y=new_front + depth / 2, d=depth, note=f"starts behind {e['id']}")
                    rb = _rect(b)
                    front_of_b = rb[1]
    for b in [e for e in buildings if e.get("merged_into")]:
        b["category"] = "part"   # built as part of the complex it merged into
    for wall in [e for e in placed if e.get("wall")]:
        rw = _rect(wall)
        blockers = [e for e in placed if e is not wall and not e.get("wall") and "vegetation" not in e["tags"]
                    and _overlap(_rect(e), rw) > 0]
        falls = [e for e in blockers if e["kind"] == "waterfall"]
        if falls:   # the forest grows over the cliff and down both its sides: it frames the falls (build_plan)
            wall["frames_falls"] = falls[0]["id"]
            continue
        if blockers:
            front = max(_rect(e)[3] for e in blockers) + 1.0
            if front > rw[1]:
                depth = max(8.0, rw[3] - front)
                _set(wall, y=front + depth / 2, d=depth, note="stands behind " + ", ".join(e["id"] for e in blockers))
    smalls = [e for e in placed if e["category"] not in ("building",) and not e.get("merged_into")
              and not e.get("wall")]
    for i, a in enumerate(smalls):
        for b in smalls[i + 1:]:
            if a["category"] in ("sunken",) or b["category"] in ("sunken",):
                continue
            ra, rb = _rect(a), _rect(b)
            if _overlap(ra, rb) > 0:
                push = (min(ra[2], rb[2]) - max(ra[0], rb[0])) / 2 + 0.2
                ax, bx = val(a["position"])[0], val(b["position"])[0]
                sign = 1 if bx >= ax else -1
                _set(a, x=ax - sign * push)
                _set(b, x=bx + sign * push)


# ---------- the plan ----------

ORDER = {"ground": 0, "building": 1, "sunken": 2, "outdoor": 4, "furniture": 5, "path": 1}
GROUND_KIND = {"grass": "lawn", "sand": "sand", "soil": "dirt", "rock": "rock", "concrete": "paving",
               "asphalt": "asphalt", "tiles": "paving", "wood floor": "oak floor", "carpet": "carpet",
               "water": "lawn"}


def _name(base, taken):
    base = base.title()
    if base not in taken:
        taken.add(base)
        return base
    k = 2
    while f"{base} {k}" in taken:
        k += 1
    taken.add(f"{base} {k}")
    return f"{base} {k}"


def _fmt(kw):
    return ", ".join(f"{k}={v!r}" for k, v in kw.items() if v is not None)


def _forest_round_falls(wall, falls, kw, ox, oy, taken):
    """The forest a waterfall stands in: along the top of its cliff, and down both sides of the face in front of it
    (clear of the plunge pool), thick undergrowth at its foot — not a stand of trees hidden behind the rock."""
    fx, fy = val(falls["position"])[0] + ox, val(falls["position"])[1] + oy
    W, w = _cliff_width(falls)
    kind = kw.get("kind", "mixed")
    lines = []
    above = _name("Trees Above", taken)
    lines.append(f"forest({above!r}, at=({fx:.2f}, {fy + 5.5:.2f}, 0), width={W + 10:.1f}, depth=7.0, "
                 f"count={int(min(140, (W + 10) * 7 / 9))}, kind={kind!r})")
    lines.append(f"tag_semantic({above!r}, 'forest', role=None, ref={wall['id']!r}, source='reference')")
    inner = max(w / 2 + 2.0, w * 0.9 + 1.0)   # clear of the falls and its pool
    side_w = W / 2 + 12.0 - inner
    for side, sx in (("Left", -1), ("Right", 1)):
        nm = _name(f"Trees {side}", taken)
        x = fx + sx * (inner + side_w / 2)
        lines.append(f"forest({nm!r}, at=({x:.2f}, {fy - 5.0:.2f}, 0), width={side_w:.1f}, depth=9.0, "
                     f"count={int(min(80, side_w * 9 / 10))}, kind={kind!r})")
        lines.append(f"tag_semantic({nm!r}, 'forest', role=None, ref={wall['id']!r}, source='inferred')")
        under = _name(f"Undergrowth {side}", taken)
        lines.append(f"forest({under!r}, at=({x - sx * 2:.2f}, {fy - 10.5:.2f}, 0), width={side_w + 4:.1f}, depth=5.0, "
                     f"count={int(min(90, side_w * 2))}, kind='shrubs')")
        lines.append(f"tag_semantic({under!r}, 'bush', role=None, ref={wall['id']!r}, source='inferred')")
    return lines


def build_plan(scene: dict, state: dict = None, offset=(0.0, 0.0)) -> dict:
    """The plan that rebuilds `scene` (a VisualScene) — {"understanding", "steps", "final_checks", "built"} — with
    `offset` added to every position (to keep clear of what's already in the scene)."""
    state = state or {"objects": []}
    taken = {o["name"] for o in state.get("objects", [])}
    ox, oy = offset
    env = scene["environment"]
    scene_type = val(env["scene_type"], "exterior")
    elements = [e for e in scene["elements"] if e.get("position") or e["kind"] == "room"]
    parts_of = {}
    for e in scene["elements"]:
        if e.get("parent"):
            parts_of.setdefault(e["parent"], []).append(e)
    main = max([e for e in elements if e["category"] == "building" and e["kind"] != "room"] or
               [e for e in elements if e["category"] not in ("ground", "sky") and not e.get("wall")] or [None],
               key=lambda e: (semantics.PRIORITY_RANK.get(e.get("priority"), 1), e["area"]) if e else (0, 0))
    if main is not None:
        main["main"] = True
    resolve_layout(elements)
    cam_hfov = math.radians(val(scene["camera"].get("hfov"), 54.0))
    for e in elements:
        t = e.get("truncated", {})
        if e["category"] == "building" and t.get("left") and t.get("right") and e.get("position"):
            front = val(e["position"])[1] - val(e["size"])[1] / 2
            e["fills_width"] = round(2 * max(1.0, front) * math.tan(cam_hfov / 2) * 1.15, 2)
    built = {}       # element id -> object name
    steps = []

    def step(title, lines, checks):
        if lines:
            steps.append({"title": title, "code": "\n".join(lines) + "\nRESULT = 'ok'", "checks": checks})

    # 1. the ground (or the room, the shore)
    lines, checks = [], []
    waterline = None
    kinds = {e["kind"] for e in elements}
    extent = max([abs(val(e["position"])[1]) + max(val(e["size"])[:2]) for e in elements if e.get("position")
                  and e["category"] not in ("ground",)] + [30.0])
    room = next((e for e in elements if e["kind"] == "room"), None)
    if scene_type == "interior" or room is not None:
        d = (room or {}).get("details", {})
        furniture = [e for e in elements if e["category"] == "furniture" and e.get("position")]
        far = max([val(e["position"])[1] + val(e["size"])[1] / 2 for e in furniture] + [3.5])
        side = max([abs(val(e["position"])[0]) + val(e["size"])[0] / 2 for e in furniture] + [2.0])
        W = _n(val(d.get("width_m")), side * 2 + 1.0, 3, 14)
        D = _n(val(d.get("depth_m")), far + 1.8, 3, 14)
        # the room the model guessed must still hold what was placed in it (a 4 m room had the sofa 5 m off,
        # through its back wall): the camera's metre behind the front wall, then the farthest piece and a gap
        D = max(D, min(14.0, far + 1.0 + 0.4))
        W = max(W, min(14.0, side * 2 + 0.6))
        Hc = _n(val(d.get("ceiling_height_m")), 2.8, 2.3, 4.5)
        windows = val(d.get("windows")) if isinstance(val(d.get("windows")), list) else [{"wall": "back"}]
        nm = _name("Room", taken)
        built["room"] = nm
        wall_col = _colour({"details": d, "color": None}, "wall_color") or "white render"
        said = str(val(d.get("floor_material"), "wood floor")).lower()
        floor = next((v for k, v in (("tile", "floor tiles"), ("wood", "oak floor"), ("parquet", "oak floor"),
                                     ("carpet", "carpet"), ("tatami", "tatami"), ("stone", "limestone"),
                                     ("marble", "limestone"), ("concrete", "paving")) if k in said), "oak floor")
        # the camera stands a metre inside the front wall
        lines.append(f"room({nm!r}, at=({ox:.2f}, {oy + D / 2 - 1.0:.2f}, 0), width={W:.2f}, depth={D:.2f}, "
                     f"height={Hc:.2f}, walls={wall_col!r}, floor={floor!r}, windows={windows!r})")
        lines.append(f"tag_semantic({nm!r}, 'room', role='the room', ref='room', source='reference')")
        checks.append({"type": "exists", "object": nm})
    else:
        ground_words = [str(g).lower() for g in val(env["ground"], [])]
        if "beach" in kinds or "ocean" in kinds and "sand" in ground_words:
            beach = next((e for e in elements if e["kind"] in ("beach", "ocean")), None)
            ocean = next((e for e in elements if e["kind"] == "ocean"), None)
            # the waterline: where the picture's sea begins — but never under the camera's feet or the things
            # standing on the sand (the sea's box often takes in the wet sand too)
            shore_y = val(ocean["position"])[1] - val(ocean["size"])[1] / 2 if ocean else 25.0
            on_sand = [val(e["position"])[1] + (0.3 if "vegetation" in e["tags"] else val(e["size"])[1] / 2 + 2.0)
                       for e in elements if e.get("position") and e["category"] in ("outdoor", "furniture", "building")
                       and val(e["position"])[1] < 40]   # (palms grow right at the water's edge)
            shore_y = max([shore_y, 6.0] + on_sand)
            waterline = shore_y
            nm = _name("Beach", taken)
            # shore(): the sand meets the water 2.5 m beyond its middle (sand_depth 30)
            sea = (ocean or {}).get("measured", {}).get("color")
            lines.append(f"shore({nm!r}, at=({ox:.2f}, {oy + shore_y - 2.5:.2f}, 0), width={max(120.0, extent * 3):.0f}, "
                         f"sand_depth=30" + (f", sea_color={sea!r}" if sea else "") + ")")
            lines.append(f"tag_semantic({nm!r}, 'beach', role='the beach and the sea', source='reference')")
            for e in elements:
                if e["kind"] in ("beach", "ocean"):
                    built[e["id"]] = nm
            checks.append({"type": "exists", "object": nm})
        else:
            gk = next((GROUND_KIND[g] for g in ground_words if g in GROUND_KIND), "lawn")
            if val(env["setting"]) in ("natural",) and gk == "lawn":
                gk = "forest floor" if any(e["kind"] in ("forest", "tree", "waterfall") for e in elements) else \
                    "wild grass"
            if val(env["setting"]) in ("natural",) and gk in ("rock", "dirt") and _lush(scene):
                gk = "forest floor"   # rocks and soil under a forest are its floor: the rocks are built as rocks
            if scene_type == "street":
                gk = "asphalt"
            nm = _name("Ground", taken)
            size = max(120.0, extent * 3)
            lines.append(f"ground({nm!r}, at=({ox:.2f}, {oy + extent * 0.6:.2f}, 0), size={size:.0f}, kind={gk!r}, "
                         f"hilly={0.0 if scene_type in ('street',) else 0.5})")
            lines.append(f"tag_semantic({nm!r}, 'terrain', role='the ground', source='reference')")
            for e in elements:
                if e["kind"] in ("lawn", "terrain"):
                    built[e["id"]] = nm
            checks.append({"type": "exists", "object": nm})
    step("Lay the ground", lines, checks)

    # 2..6: everything that stands, in dependency order (structures, water, plants, vehicles, props)
    groups = [("Build the main structures", lambda e: e["category"] == "building" and e["kind"] != "room"),
              ("Lay the roads and paths", lambda e: e["category"] == "path"),
              ("Add the water", lambda e: e["kind"] in ("swimming pool", "pond", "fountain", "waterfall", "river",
                                                         "lake") or (e["kind"] == "ocean" and e["id"] not in built)),
              ("Plant the trees and plants", lambda e: "vegetation" in e["tags"] or e["kind"] == "forest"),
              ("Place the vehicles", lambda e: "vehicle" in e["tags"]),
              ("Add the furniture and details", lambda e: True)]
    done_ids = set(built)
    for title, pick in groups:
        lines, checks = [], []
        for e in sorted(elements, key=lambda e: (-semantics.PRIORITY_RANK.get(e["priority"], 1), e["id"])):
            if e["id"] in done_ids or e["category"] in ("part", "sky", "ignore") or not pick(e):
                continue
            if e["kind"] == "lantern" and e.get("parent"):
                continue
            if e["kind"] in ("lawn", "terrain", "beach") or e["kind"] == "room":
                continue
            spec = asset_for(e, scene, parts_of)
            done_ids.add(e["id"])
            if spec is None:
                continue
            builder, kw, word = spec
            pos = val(e["position"])
            falls_ = next((f for f in elements if f["id"] == e.get("frames_falls")), None)
            if builder == "forest" and falls_ is not None:
                lines += _forest_round_falls(e, falls_, kw, ox, oy, taken)
                built[e["id"]] = "Trees Above"
                checks.append({"type": "exists", "object": "Trees Above"})
                continue
            x, y = pos[0] + ox, pos[1] + oy
            nm = _name(word if word not in ("forest",) else "Trees", taken)
            if waterline is not None and pos[1] > waterline + 3 and e["category"] in ("building", "outdoor"):
                # across the water (a far shore, a headland): land under it, a little above the sea
                size_ = max(val(e["size"])[:2]) * 2.5 + 6
                land = _name(f"{nm} Shore", taken)
                lines.append(f"ground({land!r}, at=({x:.2f}, {y:.2f}, 0.35), size={size_:.1f}, kind='sand', hilly=0.4)")
                lines.append(f"tag_semantic({land!r}, 'terrain', role='land across the water', source='inferred')")
            rot = _rotation(e, scene)
            if builder in ("house", "villa", "storefront", "garage") and rot:
                kw["rotation"] = rot
            if builder == "road":
                kw = dict(length=max(40.0, val(e["size"])[0]), width=max(5.0, val(e["size"])[1]))
            falls = next((f for f in elements if f["kind"] == "waterfall" and f.get("position")), None)
            if builder == "river" and falls is not None:
                # the stream runs out of the waterfall's pool, toward (and past) the camera
                fx, fy = val(falls["position"])[0] + ox, val(falls["position"])[1] + oy
                pool_front = fy - val(falls["size"])[1] / 2 - max(3.0, val(falls["size"])[0] * 0.8)
                lines.append(f"river({nm!r}, start=({fx:.2f}, {pool_front:.2f}), end=({ox + fx * 0.3:.2f}, "
                             f"{oy - 6.0:.2f}), width={min(kw.get('width', 4.0), max(2.0, val(falls['size'])[0])):.1f})")
            elif builder == "river":
                lines.append(f"{builder}({nm!r}, at=({x:.2f}, {y:.2f}, 0), {_fmt(kw)})")
            elif builder == "hills":
                lines.append(f"{builder}({nm!r}, at=({ox:.2f}, {oy:.2f}, 0), {_fmt(kw)})")
            else:
                lines.append(f"{builder}({nm!r}, at=({x:.2f}, {y:.2f}, 0)" + (f", {_fmt(kw)}" if kw else "") + ")")
            role = ("the main building" if e["category"] == "building" else "the main subject") if e.get("main") \
                else None
            lines.append(f"tag_semantic({nm!r}, {e['kind']!r}, role={role!r}, ref={e['id']!r}, source='reference')")
            built[e["id"]] = nm
            checks.append({"type": "exists", "object": nm})
        if title == "Lay the roads and paths":
            for e in elements:   # a road the picture shows becomes a real street
                if e["kind"] in ("road", "sidewalk") and e["id"] not in built:
                    pos = val(e["position"])
                    nm = _name("Road", taken)
                    lines.append(f"road({nm!r}, at=({pos[0] + ox:.2f}, {pos[1] + oy:.2f}, 0), "
                                 f"length={max(40.0, val(e['size'])[0] * 1.5):.1f}, width={max(6.0, min(14.0, val(e['size'])[1])):.1f})")
                    lines.append(f"tag_semantic({nm!r}, 'road', ref={e['id']!r}, source='reference')")
                    built[e["id"]] = nm
                    checks.append({"type": "exists", "object": nm})
        step(title, lines, checks)

    # 7. a backdrop where the picture shows distance (hills behind open land, a treeline behind a waterfall)
    lines = []
    if scene_type in ("exterior", "landscape") and not any(e["kind"] == "hill" for e in elements) and \
            val(env["setting"]) in ("natural", "rural", "coastal", "residential") and room is None:
        nm = _name("Hills", taken)
        lines.append(f"hills({nm!r}, at=({ox:.2f}, {oy:.2f}, 0), distance={max(140.0, extent * 4):.0f}, "
                     f"height={25.0 if val(env['setting']) != 'coastal' else 12.0})")
        lines.append(f"tag_semantic({nm!r}, 'hill', role='the distant hills', source='inferred')")
    step("Add the distance", lines, [])

    # 8. the camera, as the photo's
    cam = scene["camera"]
    focus = val(main["position"])[1] if main is not None and main.get("position") else 20.0
    steps.append({"title": "Set up the camera like the photo's",
                  "code": (f"RESULT = camera_match('Camera', height={val(cam['height_m'], 1.6):.2f}, "
                           f"pitch={val(cam['pitch_deg'], 0.0):.2f}, yaw=0.0, lens={val(cam['lens_mm'], 35.0):.1f}, "
                           f"at=({ox:.2f}, {oy:.2f}), look_distance={max(5.0, focus):.1f})"),
                  "checks": [{"type": "exists", "object": "Camera"}, {"type": "camera_safe", "object": "Camera"}]})

    # 9. light, weather, air
    tod = val(env["time_of_day"], "day")
    sun_side = val(scene["lighting"]["sun_side"])
    pool_lit = any(b["effect"] == "pool_lights" for b in scene["semantics"]["behaviours"])
    pool_lit = pool_lit and any(val(e.get("details", {}).get("lit")) for e in elements if e["kind"] == "swimming pool") \
        or (pool_lit and tod == "night")
    lines = [f"time_of_day({tod!r}" + (f", sun_side={sun_side!r}" if sun_side not in (None, "not visible") else "")
             + (", pool_lights_on=True" if pool_lit else "") + ")"]
    weather = val(env["weather"], "clear")
    if weather in ("rain", "storm", "snow", "cloudy", "overcast"):
        lines.append(f"weather({weather!r})")
    cover = _cloud_cover(scene)
    if cover is not None and weather not in ("rain", "storm", "snow", "overcast"):
        lines.append(f"sky_clouds(cover={cover:.2f})")
    atmosphere = val(env["atmosphere"], "clear")
    if atmosphere in ("fog", "mist", "haze", "smoke"):
        lines.append(f"fog({atmosphere!r})")
    steps.append({"title": f"Light it for {tod}" + (f", {weather}" if weather not in ("clear",) else ""),
                  "code": "\n".join(lines) + "\nRESULT = env_state()",
                  "checks": [{"type": "env", "path": "set.time", "op": "==", "value": tod}]})

    # 10. what moves by itself, justified by the scene
    lines, checks, said = [], [], []
    for b in scene["semantics"]["behaviours"]:
        names = [built[t] for t in b["targets"] if t in built]
        if b["effect"] == "water":
            for n in dict.fromkeys(names):
                lines.append(f"animate_water({n!r}, {b.get('mode', 'waves')!r}, strength={b.get('strength', 1.0)})")
                checks.append({"type": "animated", "object": n})
        elif b["effect"] == "sway":
            for n in dict.fromkeys(names):
                lines.append(f"sway({n!r}, strength={b.get('strength', 0.7)})" if not n.startswith("Trees")
                             else f"wind({b.get('strength', 0.7)}, things=[{n!r}])")
                checks.append({"type": "animated", "object": n})
        elif b["effect"] == "flutter":
            lines += [f"flutter({n!r})" for n in names]
        elif b["effect"] == "fire":
            lines += [f"animate_naturally({n!r}, 'fire')" for n in names]
        elif b["effect"] == "mist":
            lines.append("fog('mist', density=0.008, height=5)")
        elif b["effect"] == "add_street_lights":
            road = next((built[e["id"]] for e in elements if e["kind"] == "road" and e["id"] in built), None)
            if road:
                for k, x in enumerate((-12, 0, 12), 1):
                    nm = _name("Street Lamp", taken)
                    lines.append(f"street_lamp({nm!r}, at=({ox + x:.1f}, {oy + 4.0:.1f}, 0), on=True)")
        else:
            continue
        said.append(b["why"])
    step("Bring it to life", lines, checks)
    understanding = visual_scene.describe(scene)
    return {"understanding": understanding, "question": "", "steps": steps, "final_checks": [],
            "built": built, "behaviours": said, "reconstruction": True}


def summary(scene: dict, built: dict) -> str:
    """What was rebuilt, in words, with what was only inferred said as such."""
    by_kind = {}
    for eid, name in built.items():
        e = next((x for x in scene["elements"] if x["id"] == eid), None)
        k = (e or {}).get("kind") or "thing"
        by_kind.setdefault(k, set()).add(name)
    parts = [f"{len(v)} {k}s" if len(v) > 1 else f"the {k}" for k, v in by_kind.items() if k not in ("terrain", "lawn")]
    env = scene["environment"]
    text = (f"rebuilt the picture in 3D: {', '.join(parts[:8])}, lit for {val(env['time_of_day'])}"
            + (f" with {val(env['weather'])} weather" if val(env['weather']) not in ('clear', None) else "")
            + ", seen through a camera set up like the photo's")
    if scene.get("unknowns"):
        text += ". Not in the picture, so inferred: " + "; ".join(scene["unknowns"][:2])
    return text
