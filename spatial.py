"""Spatial reasoning for Jervis's 3D scenes: what the things in a scene are, where they stand, which way they face, and
what "beside the house", "in front of it" or "a path from the door to the pool" mean in metres.

Why: a small model asked for "a pool beside the villa" picks coordinates by itself, and sometimes puts the pool inside
the building. Relations are geometry, not guesswork: this module turns them into footprints and free spots, routes
paths around buildings, and checks the finished scene (intersections, outdoor things inside buildings, floating or
sunk things, broken paths, wrong relative placement, odd sizes) with a concrete repair for each problem it can fix.

Pure Python, no bpy: Jervis uses it outside Blender to plan and verify, and the building kit loads the very same code
inside Blender (agent_blender.kit_source) so spot_near()/walkway() there and Jervis's checks agree to the centimetre.

Space: metres, z up, the ground is z = 0, x left(-)/right(+), y front(-)/back(+) — the camera looks from the front.
A footprint is an axis-aligned rectangle (x0, y0, x1, y1). The input is scene_state()'s list of objects
({"name", "type", "min", "max", "parent", "asset", "asset_type", "rotation", "role"...}).
"""
import heapq
import math
import re

# ---------- words ----------

BUILDING = {"house", "home", "villa", "cottage", "cabin", "bungalow", "mansion", "building", "shed", "garage", "barn",
            "hut", "kiosk", "church", "chapel", "tower", "castle", "office", "shop", "store", "school", "hotel",
            "apartment", "warehouse", "chalet", "farmhouse", "townhouse", "gazebo", "pavilion", "greenhouse", "cafe",
            "restaurant", "temple", "palace", "lighthouse", "station", "hangar", "stable", "outhouse", "shack",
            "lodge", "factory", "museum", "library", "hospital", "skyscraper", "dwelling", "residence", "bunker"}
GROUND = {"terrain", "island", "sea", "ocean", "lake", "ground", "lawn", "grass", "field", "meadow", "landscape",
          "sand", "beach", "desert", "floor", "seabed", "backdrop"}
SURFACE = {"patio", "deck", "terrace", "platform", "plaza", "courtyard", "rug", "carpet", "mat", "stage", "pad",
           "slab", "decking"}
PATH = {"path", "pathway", "walkway", "walk", "driveway", "sidewalk", "footpath", "trail", "road", "street",
        "pavement", "paving", "paver", "boardwalk", "lane", "steppingstone"}
SUNKEN = {"pool", "pond", "basin", "pit", "trench", "moat", "hole", "ditch", "jacuzzi", "spa", "hottub"}
FURNITURE = {"sofa", "couch", "bed", "table", "desk", "chair", "armchair", "stool", "bookshelf", "bookcase", "shelf",
             "wardrobe", "cabinet", "dresser", "nightstand", "lamp", "tv", "television", "fridge", "refrigerator",
             "stove", "oven", "bathtub", "toilet", "sink", "piano", "cupboard", "bench", "ottoman", "sideboard",
             "counter", "island_counter", "crib", "vase", "plant"}
OUTDOOR = {"tree", "palm", "pine", "oak", "birch", "maple", "willow", "bush", "shrub", "hedge", "rock", "boulder",
           "fountain", "car", "truck", "van", "bus", "bicycle", "bike", "motorcycle", "fence", "gate", "mailbox",
           "lamppost", "streetlight", "streetlamp", "swing", "slide", "playground", "tent", "campfire", "bonfire",
           "flowerbed", "lounger", "sunbed", "parasol", "hammock", "well", "windmill", "barbecue", "bbq", "grill",
           "trampoline", "sandbox", "birdbath", "doghouse", "kennel", "boat", "dock", "pier", "bridge", "flagpole",
           "haystack", "scarecrow", "signpost", "snowman", "garden", "cactus", "stump", "tractor", "wagon", "cart",
           "umbrella", "statue", "sculpture", "flag", "flagpole", "banner", "bollard", "hydrant", "pergola", "arbor", "gardenlamp", "sunlounger",
           "birdhouse"}
_OUTDOOR_PHRASES = re.compile(r"\b(?:lamp ?posts?|street ?lamps?|street ?lights?|garden lamps?|sun ?loungers?|"
                              r"deck ?chairs?|beach ?chairs?|picnic tables?|park benches?|flower ?beds?|dog ?houses?|"
                              r"bird ?houses?|hot ?tubs?)\b", re.I)
ROOMS = {"room", "kitchen", "bedroom", "bathroom", "hall", "hallway", "interior", "inside", "lobby", "attic",
         "basement", "studio", "lounge"}
DOOR_WORDS = {"door", "entrance", "entry", "doorway", "frontdoor", "porch"}
TREE_KINDS = {"tree", "palm", "pine", "oak", "birch", "maple", "willow", "fir", "spruce", "conifer", "cypress"}
_BUILDING_SIDE_PARTS = {"path", "step", "stair", "walkway", "driveway", "garden", "fence", "lawn", "mailbox", "yard",
                        # what reaches out from the walls without being inside them: a terrace, a cantilevered slab,
                        # a balcony and its railing, an awning or eave, an apron in front of a garage door
                        "terrace", "deck", "patio", "slab", "slabs", "overhang", "canopy", "balcony", "railing",
                        "railings", "awning", "eaves", "downlight", "downlights", "apron"}
VOCAB = BUILDING | GROUND | SURFACE | PATH | SUNKEN | FURNITURE | OUTDOOR

# Rough footprints (width x depth, metres) to plan room for a thing before it exists.
FOOTPRINTS = {
    "pool": (11.4, 7.4), "pond": (5.2, 4.0), "jacuzzi": (2.6, 2.6), "spa": (2.6, 2.6), "house": (10, 8),
    "villa": (12, 9), "cottage": (9, 7), "cabin": (7, 6), "mansion": (16, 12), "building": (10, 8),
    "shed": (3, 2.5), "garage": (6.5, 6), "barn": (10, 8), "hut": (4, 4), "gazebo": (4, 4), "pavilion": (5, 5),
    "greenhouse": (5, 3), "kiosk": (3, 3), "tree": (6.5, 6.5), "palm": (6.3, 6.3), "pine": (4.9, 4.9),
    "oak": (6.6, 6.6), "birch": (4.2, 4.2), "bush": (1.4, 1.4), "shrub": (1.6, 1.6), "hedge": (4, 1), "rock": (1.6, 1.6),
    "boulder": (2.5, 2.5), "bench": (1.8, 0.7), "table": (1.6, 1.0), "chair": (0.6, 0.6), "car": (4.6, 1.9),
    "truck": (7, 2.5), "bicycle": (1.8, 0.6), "fountain": (3.2, 3.2), "fence": (6, 0.3), "lounger": (2.0, 0.8),
    "sunbed": (2.0, 0.8), "parasol": (2.6, 2.6), "umbrella": (2.6, 2.6), "statue": (1.2, 1.2), "lamppost": (0.5, 0.5),
    "streetlight": (0.5, 0.5), "mailbox": (0.5, 0.5), "swing": (3.0, 2.0), "slide": (3.5, 1.2), "tent": (3, 3),
    "boat": (5, 2), "playground": (8, 6), "garden": (6, 4), "flowerbed": (3, 1.2), "patio": (6, 4), "deck": (6, 4),
    "terrace": (6, 4), "barbecue": (1.2, 0.8), "bbq": (1.2, 0.8), "grill": (1.2, 0.8), "hammock": (3.5, 1.2),
    "sofa": (2.2, 0.95), "couch": (2.2, 0.95), "sunlounger": (2.2, 2.2), "deckchair": (1.6, 1.6), "bed": (2.1, 1.7), "desk": (1.4, 0.7), "wardrobe": (1.2, 0.6),
    "bookshelf": (1.0, 0.35), "tv": (1.3, 0.4), "piano": (1.6, 1.5), "well": (2, 2), "windmill": (6, 6),
    "trampoline": (3.6, 3.6), "sandbox": (2, 2), "doghouse": (1.2, 1.0), "snowman": (1.2, 1.2), "cart": (2, 1.2),
    "pergola": (4, 3), "lamp": (0.5, 0.5), "armchair": (0.9, 0.9), "stool": (0.45, 0.45), "campfire": (1.5, 1.5),
}

RELATION_WORDS = [  # (pattern, normalised relation) — longest first
    (r"in front of|across from|opposite(?: to)?|facing", "front"),
    (r"behind|in back of|at the back of|to the back of|at the rear of", "behind"),
    (r"(?:to|on|at) the left(?: side)? of|left of", "left"),
    (r"(?:to|on|at) the right(?: side)? of|right of", "right"),
    (r"next to|beside|alongside|adjacent to|by the side of|by(?= (?:the|a|an|my|our|its)\b)", "beside"),
    (r"near|close to|nearby|around", "near"),
    (r"on top of|onto|atop|on", "on"),
    (r"inside|within|into|in", "inside"),
    (r"between", "between"),
]
_REL_RE = re.compile(r"\b(?P<rel>" + "|".join(p for p, _ in RELATION_WORDS) + r")\b", re.I)
_PRONOUN = {"it", "its", "them", "that", "this", "these", "those", "him", "her"}
_CONNECT_RE = re.compile(
    r"(?:\bfrom\s+(?P<a>[\w' -]+?)\s+(?:to|into|towards?|up to|down to)\s+(?P<b>[\w' -]+?)(?=$|[,.;!?]|\s+(?:and|with|then|which|that)\b)"
    r"|\bbetween\s+(?P<c>[\w' -]+?)\s+and\s+(?P<d>[\w' -]+?)(?=$|[,.;!?]|\s+(?:with|then|which|that)\b)"
    r"|\b(?:connect(?:s|ing|ed)?|link(?:s|ing|ed)?|join(?:s|ing)?)\s+(?P<e>[\w' -]+?)\s+(?:and|to|with)\s+"
    r"(?P<f>[\w' -]+?)(?=$|[,.;!?]|\s+(?:with|then|which|that)\b)"
    r"|(?<!next )(?<!close )(?<!right )(?<!left )(?<!up )\bto\s+(?P<g>(?:the|a|an|its|my)\s+[\w' -]+?)"
    r"(?=$|[,.;!?]|\s+(?:and|with|then|which|that)\b))", re.I)


def singular(word: str) -> str:
    w = str(word or "").lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def words_of(text) -> list:
    """Lower-case singular words, in order ("Swimming Pool 2" -> ['swimming', 'pool'])."""
    text = re.sub(r"\.\d+\b", "", str(text or ""))
    joined = _OUTDOOR_PHRASES.sub(lambda m: m.group(0).replace(" ", ""), text.lower())
    return [singular(w) for w in re.findall(r"[a-z]+", joined)]


def head_noun(text) -> str:
    """The word that says what something is: the last known thing-word ("House Path" is a path, "Tree House" a
    house), else the last word."""
    ws = words_of(text)
    for w in reversed(ws):
        if w in VOCAB or w in FOOTPRINTS:
            return w
    return ws[-1] if ws else ""


def category_of(name: str, asset_type: str = None, part_names=()) -> str:
    """building / ground / path / sunken / surface / outdoor / furniture / object."""
    if asset_type in ("island", "water"):
        return "ground"
    if asset_type in ("house", "garage", "villa", "storefront"):
        return "building"
    if asset_type in ("ground", "shore", "hills"):
        return "ground"
    if asset_type == "road":
        return "path"
    if asset_type == "room":
        return "surface"   # an enclosure the camera stands inside: never an obstacle to it
    if asset_type in ("sofa", "armchair", "coffee_table", "table", "chair", "tv", "shelf", "rug", "floor_lamp",
                      "potted_plant"):
        return "furniture"
    if asset_type in ("parasol", "street_lamp", "lantern", "crate", "forest"):
        return "outdoor"
    if asset_type in ("pool", "pond"):
        return "sunken"
    if asset_type == "path":
        return "path"
    if asset_type in ("rain", "snow", "cloud"):
        return "sky"
    if asset_type in ("tree", "rock", "bush", "fence", "bench", "lounger", "fountain", "flag", "waterfall", "car",
                      "gate"):
        return "outdoor"
    ws = words_of(name)
    order = ([head_noun(name)] if head_noun(name) else []) + list(reversed(ws))
    for w in order:
        for cat, vocab in (("building", BUILDING), ("path", PATH), ("sunken", SUNKEN), ("ground", GROUND),
                           ("surface", SURFACE), ("outdoor", OUTDOOR), ("furniture", FURNITURE)):
            if w in vocab:
                return cat
    parts = [set(words_of(p)) for p in part_names]
    if any(p & {"wall", "walls"} for p in parts) and any("roof" in p for p in parts):
        return "building"
    return "object"


# ---------- rectangles ----------

def rect_of(lo, hi) -> tuple:
    return (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))


def grow(r, d) -> tuple:
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def overlap_depth(a, b) -> float:
    """How far two rectangles overlap (the smaller of the x and y overlaps; <= 0: they don't)."""
    return min(min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1]))


def overlap_area(a, b) -> float:
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0.0


def area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def gap(a, b) -> float:
    """The distance between two rectangles (0 when they touch or overlap)."""
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    return math.hypot(dx, dy)


def center(r) -> tuple:
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


def contains(r, p, margin=0.0) -> bool:
    return r[0] - margin <= p[0] <= r[2] + margin and r[1] - margin <= p[1] <= r[3] + margin


def point_rect_gap(p, r) -> float:
    return gap((p[0], p[1], p[0], p[1]), r)


def _snap_axis(vx, vy) -> tuple:
    if abs(vx) < 1e-9 and abs(vy) < 1e-9:
        return (0.0, -1.0)
    return (math.copysign(1.0, vx), 0.0) if abs(vx) > abs(vy) else (0.0, math.copysign(1.0, vy))


def side_vectors(front) -> dict:
    """The four sides of something facing `front`, as seen by a viewer standing in front of it."""
    fx, fy = front
    return {"front": (fx, fy), "back": (-fx, -fy), "right": (-fy, fx), "left": (fy, -fx)}


# ---------- things ----------

_GEOMETRY = ("MESH", "CURVE", "SURFACE", "META", "FONT")


def _prefix(name: str, roots) -> str:
    low = name.lower()
    best = ""
    for root in roots:
        if (low == root.lower() or low.startswith(root.lower() + " ")) and len(root) > len(best):
            best = root
    if best:
        return best
    tokens = re.sub(r"\.\d+$", "", name).split()
    if len(tokens) >= 3 and tokens[1].isdigit():
        return " ".join(tokens[:2])
    if len(tokens) >= 4 and tokens[2].isdigit():
        return " ".join(tokens[:3])
    return tokens[0] if tokens else name


def things(state, before=None) -> list:
    """The separate things in a scene: each assembly / finished asset with all its parts, or loose parts grouped by
    their name ('Bench Seat', 'Bench Leg 1' -> 'Bench'). Each thing is a dict:
      name, parts (object dicts), names (every object's name), rect (whole footprint), core (the footprint proper:
      a building without its path and steps), lo, hi (3D bounds), category, asset_type, front (axis unit vector),
      door (x, y) or None, new (made since `before`), new_parts (names of its parts made since `before`), role."""
    objs = [o for o in (state or {}).get("objects", []) if o.get("type") in _GEOMETRY + ("EMPTY",)
            and not str(o.get("name", "")).startswith("__") and o.get("role") not in ("library", "cutter")]
    by = {o["name"]: o for o in objs}
    has_child = {o.get("parent") for o in objs if o.get("parent")}

    def root_of(o):
        seen = set()
        while o.get("parent") in by and o["name"] not in seen:
            seen.add(o["name"])
            o = by[o["parent"]]
        return o

    groups, roots = {}, []
    for o in objs:
        r = root_of(o)
        if r is not o or o["name"] in has_child or o.get("type") == "EMPTY":
            groups.setdefault(r["name"], []).append(o)
            if r["name"] not in roots:
                roots.append(r["name"])
    def near_group(o, key):
        mine = [p for p in groups.get(key, []) if p.get("type") in _GEOMETRY and p.get("min")]
        if not mine or not o.get("min"):
            return True
        r = rect_of([min(p["min"][i] for p in mine) for i in range(2)], [max(p["max"][i] for p in mine) for i in range(2)])
        return gap(rect_of(o["min"], o["max"]), r) <= 2.0

    for o in objs:
        r = root_of(o)
        if r is o and o["name"] not in has_child and o.get("type") != "EMPTY":
            key = _prefix(o["name"], roots)
            if key in roots and not near_group(o, key):
                key = o["name"]   # named like a group but standing far from it: a thing of its own
            groups.setdefault(key, []).append(o)
    before = set(before or ())
    out = []
    for key, members in groups.items():
        parts = [o for o in members if o.get("type") in _GEOMETRY and o.get("min") and o.get("max")
                 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in list(o["min"]) + list(o["max"]))]
        if not parts:
            continue
        root = by.get(key)
        asset_type = root.get("asset_type") if root is not None and root.get("asset") == key else None
        lo = [min(p["min"][i] for p in parts) for i in range(3)]
        hi = [max(p["max"][i] for p in parts) for i in range(3)]
        names = [o["name"] for o in members]
        category = category_of(key, asset_type, [p["name"] for p in parts])
        role = (root or {}).get("role") or next((p.get("role") for p in parts if p.get("role")), None)
        if role in ("path", "sunken", "surface", "ground", "sky") and category in ("object", "outdoor", "furniture"):
            category = role
        if role == "backdrop":   # a stand of trees, a field of tufts or stones: the place itself, laid out round
            category = "backdrop"   # what's in it (environment.py), never an obstacle to placing or filming it
        rel = lambda p: [w for w in words_of(p["name"][len(key):] if p["name"].lower().startswith(key.lower())
                                             else p["name"])]
        core_parts = parts
        if category == "building":
            core_parts = [p for p in parts if not set(rel(p)) & (_BUILDING_SIDE_PARTS | OUTDOOR | SUNKEN)
                          or set(rel(p)) & {"wall", "roof", "foundation"}] or parts
        side_parts = [p for p in parts if set(rel(p)) & PATH]
        outer_parts = [p for p in parts if p not in side_parts] or parts
        core = rect_of([min(p["min"][i] for p in core_parts) for i in range(2)],
                       [max(p["max"][i] for p in core_parts) for i in range(2)])
        outer = rect_of([min(p["min"][i] for p in outer_parts) for i in range(2)],
                        [max(p["max"][i] for p in outer_parts) for i in range(2)])
        doors = [p for p in parts if set(rel(p)) & DOOR_WORDS and not set(rel(p)) & {"handle", "knob", "frame",
                                                                                      "step", "steps", "light"}]
        door = None
        if doors:
            d = doors[0]
            door = ((d["min"][0] + d["max"][0]) / 2, (d["min"][1] + d["max"][1]) / 2)
        if asset_type in ("house", "garage", "gate") and root is not None and root.get("rotation"):
            rot = math.radians(float(root["rotation"][2]))
            front = _snap_axis(math.sin(rot), -math.cos(rot))
        elif asset_type in ("villa", "storefront", "car", "bench") and root is not None:
            # built facing -y, turned by their rotation: a villa's door at one end of its long front still faces
            # front, not sideways
            rot = math.radians(float((root.get("rotation") or [0, 0, 0])[2]))
            front = _snap_axis(math.sin(rot), -math.cos(rot))
        elif door is not None:
            c = center(core)
            front = _snap_axis(door[0] - c[0], door[1] - c[1])
        else:
            front = (0.0, -1.0)
        new_parts = [n for n in names if n not in before] if before else list(names)
        pieces = []   # a path's ground, piece by piece (its bounding box would claim the whole corner it turns)
        route_info = (root or {}).get("route")
        path_ends_ = [e for e in ((root or {}).get("path_from"), (root or {}).get("path_to")) if e]
        if route_info and len(route_info) >= 2:
            half = float((root or {}).get("width") or 1.2) / 2 + 0.1
            for (x0, y0), (x1, y1) in zip(route_info, route_info[1:]):
                n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 1.0))
                for k in range(n):
                    ax, ay = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
                    bx, by_ = x0 + (x1 - x0) * (k + 1) / n, y0 + (y1 - y0) * (k + 1) / n
                    pieces.append((min(ax, bx) - half, min(ay, by_) - half, max(ax, bx) + half, max(ay, by_) + half))
        elif category == "path" and len(parts) > 1:
            pieces = [rect_of(p["min"], p["max"]) for p in parts]
        out.append({"name": key, "parts": parts, "names": names, "rect": rect_of(lo, hi), "core": core,
                    "outer": outer, "lo": lo, "hi": hi, "category": category, "asset_type": asset_type,
                    "front": front, "door": door, "role": role,
                    "new": bool(before is not None and all(n not in before for n in names)) if before else True,
                    "new_parts": new_parts, "side_parts": [rect_of(p["min"], p["max"]) for p in side_parts],
                    "pieces": pieces, "ends": path_ends_,
                    # a tree's trunk: where it really stands (its crown may lean over, or into the next tree's)
                    "trunk": next((rect_of(p["min"], p["max"]) for p in parts if "trunk" in rel(p)), None)})
    return out


def merge(group, name=None) -> dict:
    """Several things as one (all the parts one request built for 'Tree 2', however the AI named them)."""
    if len(group) == 1 and (name is None or group[0]["name"] == name):
        return group[0]
    first = max(group, key=lambda t: area(t["outer"]))
    name = name or first["name"]
    lo = [min(t["lo"][i] for t in group) for i in range(3)]
    hi = [max(t["hi"][i] for t in group) for i in range(3)]
    union = lambda key: (min(t[key][0] for t in group), min(t[key][1] for t in group),
                         max(t[key][2] for t in group), max(t[key][3] for t in group))
    category = category_of(name)
    return dict(first, name=name, parts=[p for t in group for p in t["parts"]],
                names=[n for t in group for n in t["names"]], rect=rect_of(lo, hi), lo=lo, hi=hi,
                core=union("core"), outer=union("outer"),
                category=first["category"] if category == "object" else category,
                new=all(t["new"] for t in group), new_parts=[n for t in group for n in t["new_parts"]],
                side_parts=[r for t in group for r in t["side_parts"]],
                pieces=[r for t in group for r in t["pieces"]] if all(t.get("pieces") for t in group) else [],
                ends=[e for t in group for e in t.get("ends") or []])


def merge_new(ts, hint=None) -> list:
    """What a request built is never torn apart by its own checks: with a name hint (one thing of a scene), ALL its
    new parts are that one thing; otherwise new loose parts that share their first word are one thing ('Tree 2',
    'Tree 2 Trunk 2' and 'Tree Leaves' of one request are one tree, not three trees inside each other)."""
    new = [t for t in ts if t["new"]]
    old = [t for t in ts if not t["new"]]
    if not new:
        return ts
    if hint:
        return old + [merge(new, str(hint).strip("'\""))]
    groups = {}
    for t in new:
        rooted = any(p.get("parent") for p in t["parts"]) or t["asset_type"]
        key = t["name"] if rooted else (words_of(t["name"]) or [t["name"]])[0]
        groups.setdefault(key, []).append(t)
    merged = []
    for key, group in groups.items():
        loose = [t for t in group if not (any(p.get("parent") for p in t["parts"]) or t["asset_type"])]
        merged += [t for t in group if t not in loose]
        if loose:
            merged.append(merge(loose, min((t["name"] for t in loose), key=len)))
    return old + merged


def virtual_thing(name, rect, category="object", height=2.0) -> dict:
    """A thing that isn't built yet but whose ground is spoken for (planning several things one after another)."""
    rect = tuple(rect)
    return {"name": name, "parts": [], "names": [name], "rect": rect, "core": rect, "outer": rect,
            "lo": [rect[0], rect[1], 0.0], "hi": [rect[2], rect[3], height], "category": category,
            "asset_type": None, "front": (0.0, -1.0), "door": None, "role": None, "new": True, "new_parts": [name],
            "side_parts": [], "pieces": []}


def find_thing(ts, ref, prefer_new=True, exclude=()):
    """The thing `ref` means: an exact name ('Villa'), or what it is ("villa", "house", "swimming pool", "the
    entrance" = the building it belongs to). Newly made things win over old ones when both fit."""
    if ref is None:
        return None
    if isinstance(ref, dict):
        return ref
    text = str(ref).strip().strip("'\"")
    cands = [t for t in ts if t["name"] not in exclude]
    for t in cands:
        if t["name"].lower() == text.lower():
            return t
    for t in cands:   # a part's name ('Villa Door' -> the villa)
        if any(n.lower() == text.lower() for n in t["names"]):
            return t
    head = head_noun(text)
    ws = set(words_of(text))
    ordered = sorted(cands, key=lambda t: (not t["new"]) if prefer_new else t["new"])
    if text[:1].isupper() or str(ref).startswith(("'", '"')):
        # An object's name ('Garage'): only a thing really called that — never "some building" by its kind.
        return next((t for t in ordered if head and head in words_of(t["name"])), None)
    if head in DOOR_WORDS or ws & DOOR_WORDS or head in ROOMS:
        hits = [t for t in ordered if t["category"] == "building"]
        return hits[0] if hits else None
    for t in ordered:
        if head and head in words_of(t["name"]):
            return t
    synonyms = [("building", BUILDING), ("sunken", SUNKEN), ("path", PATH), ("surface", SURFACE)]
    for cat, vocab in synonyms:
        if head in vocab:
            hits = [t for t in ordered if t["category"] == cat]
            if hits:
                return hits[0]
    for t in ordered:
        if ws & set(words_of(t["name"])) - {"the", "a", "an"}:
            return t
    return None


def find_parts(ts, ref, exclude=()) -> list:
    """The parts of things that `ref` means when no whole thing does — "the palm trees" of an island, "the
    lamps" of a garden: the outermost part named for it (never its trunk and fronds separately), as
    [(thing, part name)], in name order."""
    if not ref or isinstance(ref, dict):
        return []
    ws = set(words_of(str(ref).strip().strip("'\""))) - {"the", "a", "an", "all", "some", "few", "of"}
    if not ws:
        return []
    if ws & {"tree", "trees"}:   # "the trees" are its palms and pines too; "the palm trees" only its palms
        ws = ws - {"tree", "trees"} if ws & (TREE_KINDS - {"tree"}) else ws | TREE_KINDS
    found = []
    for t in ts:
        if t["name"] in exclude or ws & set(words_of(t["name"])):
            continue   # (a thing that is one itself: its trunk and leaves aren't more of them)
        hits = [n for n in t["names"] if n != t["name"] and ws & set(words_of(n))]
        hits = [n for n in hits if not any(n.startswith(m + " ") for m in hits if m != n)]
        found += [(t, n) for n in sorted(hits)]
    return found


def entrance(t) -> tuple:
    """Where you walk out of a thing: just outside its front door (or the middle of its front side)."""
    fx, fy = t["front"]
    r = t["outer"]
    door = t["door"] or center(t["core"])
    if fx == 0:
        return (door[0], (r[1] - 0.15) if fy < 0 else (r[3] + 0.15))
    return ((r[0] - 0.15) if fx < 0 else (r[2] + 0.15), door[1])


def entrance_zone(t, width=2.6, depth=3.0) -> tuple:
    """The ground in front of a building's door that must stay free (so its entrance isn't blocked)."""
    ex, ey = entrance(t)
    fx, fy = t["front"]
    if fx == 0:
        y0, y1 = (ey - depth, ey) if fy < 0 else (ey, ey + depth)
        return (ex - width / 2, y0, ex + width / 2, y1)
    x0, x1 = (ex - depth, ex) if fx < 0 else (ex, ex + depth)
    return (x0, ey - width / 2, x1, ey + width / 2)


def floor_level(t) -> float:
    """The height of a building's ground floor (where furniture inside it stands)."""
    floors = [p["min"][2] + min(0.12, p["max"][2] - p["min"][2]) for p in t["parts"]
              if set(words_of(p["name"])) & {"floor", "floors"}]
    if floors:
        return round(min(floors), 3)
    bases = [p["max"][2] for p in t["parts"] if set(words_of(p["name"])) & {"foundation", "plinth", "slab"}
             and p["max"][2] - t["lo"][2] < 1.5]
    return round(max(bases) if bases else max(0.0, t["lo"][2]), 3)


def estimate_size(name_or_words, default=(2.0, 2.0)) -> tuple:
    head = head_noun(name_or_words)
    if head in FOOTPRINTS:
        return FOOTPRINTS[head]
    for w in reversed(words_of(name_or_words)):
        if w in FOOTPRINTS:
            return FOOTPRINTS[w]
    return default


# ---------- placement ----------

_SIDES = {   # relation -> {side: penalty}; buildings keep their front (the entrance) free unless asked
    "beside": ({"right": 0, "left": 0.4, "back": 2.5, "front": 5.0}, {"right": 0, "left": 0.2, "front": 0.8, "back": 0.8}),
    "near": ({"right": 0, "left": 0.2, "back": 0.6, "front": 3.0}, {"right": 0, "left": 0.2, "front": 0.5, "back": 0.5}),
    "front": ({"front": 0}, {"front": 0}), "behind": ({"back": 0}, {"back": 0}),
    "left": ({"left": 0}, {"left": 0}), "right": ({"right": 0}, {"right": 0}),
}
_EXTRA = [0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25]


def default_gap(anchor, size, subject_category="object") -> float:
    big = max(size)
    g = max(1.0, min(3.0, 0.8 + 0.15 * big))
    if anchor and anchor["category"] == "building":
        g += 1.0 if subject_category in ("sunken", "building", "outdoor") else 0.5
    if subject_category in ("furniture",) and anchor and anchor["category"] in ("furniture", "object"):
        g = 0.4
    return round(g, 2)


def obstacles(ts, subject_category="object", ignore=()) -> list:
    """[(name, rect)] that something new must keep clear of: every thing's footprint (a building's paths and steps
    on their own, so the ground beside a path is still usable), and building entrances. Ground, terrain and
    walkable surfaces are never obstacles; paths are, except for another path."""
    out = []
    for t in ts:
        if t["name"] in ignore or t["category"] in ("ground", "surface", "sky", "backdrop"):
            continue
        if t["category"] == "path" and subject_category == "path":
            continue
        if t.get("pieces"):
            out += [(t["name"], r) for r in t["pieces"]]
        else:
            margin = 1.0 if t["category"] == "building" and subject_category != "path" else 0.0
            out.append((t["name"], grow(t["outer"], margin)))   # room to walk round a building
            out += [(t["name"], r) for r in t["side_parts"]] if subject_category != "path" else []
        if t["category"] == "building" and subject_category != "path":
            out.append((t["name"] + " entrance", entrance_zone(t)))
    return out


def _free(rect, blocks, clearance) -> bool:
    return all(overlap_depth(rect, grow(b, clearance)) <= 1e-6 for _, b in blocks)


def place_relative(anchor, relation, size, ts, subject_category="object", gap_=None, ignore=(), orient=True,
                   clearance=0.4) -> dict:
    """A spot for something `size` = (width, depth) metres that stands `relation` the anchor thing ("beside",
    "near", "front", "behind", "left", "right", "inside", "on"), clear of everything else. Returns {"x", "y",
    "rotation" (0 or 90: long side along the facade), "side", "rect"} or None when there is no room."""
    relation = normalize_relation(relation) or "beside"
    if relation == "inside":
        return place_inside(anchor, size, ts, ignore=ignore)
    if relation == "on":
        r = anchor["outer"]
        c = center(r)
        w, d = size
        return {"x": c[0], "y": c[1], "z": anchor["hi"][2], "rotation": 0, "side": "on",
                "rect": (c[0] - w / 2, c[1] - d / 2, c[0] + w / 2, c[1] + d / 2)}
    building = anchor["category"] == "building"
    sides = _SIDES.get(relation, _SIDES["beside"])[0 if building else 1]
    g = default_gap(anchor, size, subject_category) if gap_ is None else float(gap_)
    blocks = obstacles(ts, subject_category, ignore=set(ignore))
    vec = side_vectors(anchor["front"])
    a = anchor["outer"]
    acx, acy = center(a)
    hx, hy = (a[2] - a[0]) / 2, (a[3] - a[1]) / 2
    best = None
    w, d = float(size[0]), float(size[1])
    for side, penalty in sides.items():
        sx, sy = vec[side]
        along_x = sx != 0                   # the subject sits off the anchor's x side (left/right in world)
        rot = 0
        if orient and abs(w - d) > 0.3 and anchor["category"] in ("building", "sunken"):
            facade_along_x = not along_x
            rot = 0 if (w >= d) == facade_along_x else 90
        ex, ey = (w, d) if rot == 0 else (d, w)
        lateral_half = hy if along_x else hx
        sub_lateral = ey if along_x else ex
        # beside/near: anywhere along that side; in front/behind/left/right: still facing that side (overlapping it
        # by at least half a metre), so two trees "behind the house" stand side by side, not one behind the other
        limit = lateral_half + (sub_lateral / 2 if relation in ("near", "beside") else _side_reach(sub_lateral))
        limit = max(0.0, limit)
        offsets = [0.0]
        k = 0.5
        while k <= limit + 1e-9:
            offsets += [k, -k]
            k += 0.5
        for extra in _EXTRA:
            if best is not None and extra * 1.0 + penalty * 4 > best[0]:
                break
            for off in offsets:
                if along_x:
                    x = acx + sx * (hx + g + ex / 2 + extra)
                    y = acy + off
                else:
                    x = acx + off
                    y = acy + sy * (hy + g + ey / 2 + extra)
                rect = (x - ex / 2, y - ey / 2, x + ex / 2, y + ey / 2)
                score = penalty * 4 + extra * 1.0 + abs(off) * 0.35
                if best is not None and score >= best[0]:
                    continue
                if _free(rect, blocks, clearance):
                    best = (score, {"x": round(x, 2), "y": round(y, 2), "rotation": rot, "side": side,
                                    "away": (sx, sy), "rect": tuple(round(v, 3) for v in rect)})
    return best[1] if best else None


def place_inside(anchor, size, ts, ignore=()) -> dict:
    """A free spot inside a building (on its ground floor, clear of the walls and what's already inside)."""
    core = grow(anchor["core"], -0.45)
    if core[2] - core[0] < 0.5 or core[3] - core[1] < 0.5:
        return None
    w, d = size
    inside = [(t["name"], t["outer"]) for t in ts if t["name"] != anchor["name"] and t["name"] not in ignore
              and t["category"] not in ("ground", "surface", "sky", "backdrop")
              and overlap_depth(t["outer"], anchor["core"]) > 0]
    cx, cy = center(core)
    best = None
    step = 0.25
    nx = int((core[2] - core[0]) / step) + 1
    ny = int((core[3] - core[1]) / step) + 1
    for i in range(nx):
        for j in range(ny):
            x, y = core[0] + w / 2 + i * step, core[1] + d / 2 + j * step
            rect = (x - w / 2, y - d / 2, x + w / 2, y + d / 2)
            if rect[2] > core[2] + 1e-6 or rect[3] > core[3] + 1e-6:
                continue
            if not _free(rect, inside, 0.3):
                continue
            score = math.hypot(x - cx, y - cy)
            if best is None or score < best[0]:
                best = (score, {"x": round(x, 2), "y": round(y, 2), "z": floor_level(anchor), "rotation": 0,
                                "side": "inside", "rect": rect})
    return best[1] if best else None


def place_free(x, y, size, ts, subject_category="object", ignore=(), clearance=0.4, max_radius=60.0) -> dict:
    """The free spot nearest to (x, y) for something `size` = (width, depth): spiralling outward."""
    blocks = obstacles(ts, subject_category, ignore=set(ignore))
    w, d = size
    r = 0.0
    while r <= max_radius:
        n = 1 if r == 0 else max(8, int(2 * math.pi * r / 0.5))
        for k in range(n):
            a = 2 * math.pi * k / n
            px, py = x + r * math.cos(a), y + r * math.sin(a)
            rect = (px - w / 2, py - d / 2, px + w / 2, py + d / 2)
            if _free(rect, blocks, clearance):
                return {"x": round(px, 2), "y": round(py, 2), "rotation": 0, "side": "free", "rect": rect}
        r += 0.5
    return None


# ---------- relations ----------

def normalize_relation(text) -> str:
    t = " ".join(str(text or "").lower().replace("_", " ").split())
    if t in ("front", "behind", "left", "right", "beside", "near", "on", "inside", "between", "connects", "around"):
        return "near" if t == "around" else t
    if t in ("back", "rear"):
        return "behind"
    if t in ("by", "next", "side", "adjacent"):
        return "beside"
    if t in ("connect", "connecting", "from", "path", "to"):
        return "connects"
    for pattern, rel in RELATION_WORDS:
        if re.fullmatch(pattern, t):
            return rel
    return ""


def near_limit(a, b) -> float:
    dims = [a["rect"][2] - a["rect"][0], a["rect"][3] - a["rect"][1], b["outer"][2] - b["outer"][0],
            b["outer"][3] - b["outer"][1]]
    return max(4.0, 0.6 * max(dims)) + (1.5 if b["category"] == "building" else 0.0)


def check_relation(sub, relation, anchor, ts=()) -> tuple:
    """(True / False, a sentence) for "sub stands `relation` anchor", measured on their footprints."""
    relation = normalize_relation(relation)
    s, a = sub["rect"], anchor["outer"]
    core = anchor["core"]
    name, other = sub["name"], anchor["name"]
    if relation == "inside":
        inner = overlap_area(s, core) / max(1e-6, area(s))
        ok = inner >= 0.7 and contains(core, center(s))
        return ok, f"'{name}' is {'inside' if ok else 'not inside'} '{other}'"
    if relation == "on":
        over = overlap_depth(s, a) > 0.02
        ok = over and abs(sub["lo"][2] - anchor["hi"][2]) <= 0.2
        return ok, (f"'{name}' rests on '{other}'" if ok else f"'{name}' isn't resting on '{other}' (its bottom "
                    f"z={round(sub['lo'][2], 2)}, the top of '{other}' z={round(anchor['hi'][2], 2)})")
    inside = overlap_depth(s, core) > 0.05 and sub["category"] not in ("path",)
    if inside:
        return False, (f"'{name}' should be {_phrase(relation)} '{other}' but it overlaps its footprint "
                       f"(x {core[0]:.1f}..{core[2]:.1f}, y {core[1]:.1f}..{core[3]:.1f})")
    if relation in ("beside", "near", ""):
        limit = near_limit(sub, anchor) * (1.3 if relation == "near" else 1.0)
        g = gap(s, a)
        ok = g <= limit
        return ok, (f"'{name}' is {g:.1f} m from '{other}'" + ("" if ok else f": too far to be {_phrase(relation)} "
                                                                             f"it (at most {limit:.1f} m)"))
    side = {"front": "front", "behind": "back", "left": "left", "right": "right"}.get(relation)
    if side is None:
        return True, ""
    vx, vy = side_vectors(anchor["front"])[side]
    sc, ac = center(s), center(a)
    # how far past the anchor's side its near edge is, and how far off to the side it is
    if vx:
        past = (s[0] - a[2]) if vx > 0 else (a[0] - s[2])
        lateral_ok = abs((s[1] + s[3]) / 2 - (a[1] + a[3]) / 2) <= (a[3] - a[1]) / 2 + _side_reach(s[3] - s[1]) + 0.05
    else:
        past = (s[1] - a[3]) if vy > 0 else (a[1] - s[3])
        lateral_ok = abs((s[0] + s[2]) / 2 - (a[0] + a[2]) / 2) <= (a[2] - a[0]) / 2 + _side_reach(s[2] - s[0]) + 0.05
    far = past > near_limit(sub, anchor) * 2.5
    ok = past >= -0.3 and lateral_ok and not far
    where = "too far away" if far else "off to one side" if not lateral_ok else "on the wrong side"
    return ok, (f"'{name}' is {_phrase(relation)} '{other}'" if ok else
                f"'{name}' should be {_phrase(relation)} '{other}' (whose front faces {_facing(anchor['front'])}) but "
                f"it is {where} (centre {sc[0]:.1f}, {sc[1]:.1f}; '{other}' centre {ac[0]:.1f}, {ac[1]:.1f})")


def _side_reach(size) -> float:
    """How far past a building's corner something "behind" (in front of, left / right of) it may stand: its centre
    up to a quarter of its own size plus a metre beyond the corner — still on that side, diagonally at most."""
    return size * 0.25 + 1.0


def _phrase(relation) -> str:
    return {"front": "in front of", "behind": "behind", "left": "to the left of", "right": "to the right of",
            "beside": "beside", "near": "near", "inside": "inside", "on": "on", "": "next to"}.get(relation, relation)


def _facing(front) -> str:
    return {(0.0, -1.0): "-y (the front)", (0.0, 1.0): "+y (the back)", (1.0, 0.0): "+x (right)",
            (-1.0, 0.0): "-x (left)"}.get(tuple(front), str(front))


def check_path(path_t, start_t, end_t, ts) -> tuple:
    """(ok, problems) for a path that should run from start_t (its entrance) to end_t: it reaches both, its pieces
    are continuous, and it never goes through a building."""
    pieces = list(path_t.get("pieces") or []) or [rect_of(p["min"], p["max"]) for p in path_t["parts"]]
    problems = []
    start = entrance(start_t) if start_t["category"] == "building" else None
    if start is not None:
        reach_a = min(point_rect_gap(start, r) for r in pieces)
        first_ok = reach_a <= 1.0
    else:
        reach_a = min(gap(r, start_t["outer"]) for r in pieces)
        first_ok = reach_a <= 0.8
    reach_b = min(gap(r, end_t["outer"]) for r in pieces)
    if not first_ok:
        problems.append(f"'{path_t['name']}' doesn't start at '{start_t['name']}'"
                        + (" entrance" if start is not None else "") + f" (nearest piece {reach_a:.1f} m away)")
    if reach_b > 0.6:   # a path ends AT its target, not somewhere near it
        problems.append(f"'{path_t['name']}' doesn't reach '{end_t['name']}' (nearest piece {reach_b:.1f} m away)")
    # continuity: the pieces near each end belong to one connected chain
    parent = list(range(len(pieces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            if gap(pieces[i], pieces[j]) <= 0.9:
                parent[find(i)] = find(j)
    if pieces and not problems:
        a_i = min(range(len(pieces)), key=lambda i: point_rect_gap(start, pieces[i]) if start is not None
                  else gap(pieces[i], start_t["outer"]))
        b_i = min(range(len(pieces)), key=lambda i: gap(pieces[i], end_t["outer"]))
        if find(a_i) != find(b_i):
            problems.append(f"'{path_t['name']}' has a gap: its pieces don't join up from '{start_t['name']}' to "
                            f"'{end_t['name']}'")
    for t in ts:
        if t["category"] != "building" or t["name"] == path_t["name"]:
            continue
        core = grow(t["core"], -0.2)
        through = [r for r in pieces if overlap_depth(r, core) > 0.15
                   and not (t["name"] == start_t["name"] and point_rect_gap(entrance(t), r) < 1.0)]
        if through:
            problems.append(f"'{path_t['name']}' runs through the building '{t['name']}'")
    return not problems, problems


# ---------- routing ----------

def route(start, end, ts, width=1.2, ignore=(), start_dir=None, end_dir=None, cell=0.5) -> list:
    """Waypoints for a path from `start` to `end` that keeps clear of everything (see _route_once); when the
    roomy way is blocked, it tries again without the square-on approach and then with less room either side,
    before saying there's no way through."""
    tries = [(width / 2 + 0.25, start_dir, end_dir), (width / 2 + 0.25, None, None), (width / 2 + 0.05, None, None)]
    for k, (margin, sdir, edir) in enumerate(tries):
        try:
            return _route_once(start, end, ts, width, ignore, sdir, edir, cell, margin)
        except ValueError:
            if k == len(tries) - 1:
                raise


def _route_once(start, end, ts, width, ignore, start_dir, end_dir, cell, margin) -> list:
    """Waypoints for a path from `start` to `end` (x, y) that keeps clear of every thing's footprint (and the
    building it leaves, except at its door): A* on a grid, then straightened. start_dir/end_dir (unit vectors)
    make it leave a door and arrive at a target square-on. Raises ValueError when there's no way through."""
    blocks = [r for name, r in obstacles(ts, "path", ignore=set(ignore))]
    pts_s = [tuple(start)]
    if start_dir:
        pts_s.append((start[0] + start_dir[0] * 1.2, start[1] + start_dir[1] * 1.2))
    pts_e = [tuple(end)]
    if end_dir:
        pts_e.append((end[0] - end_dir[0] * 1.2, end[1] - end_dir[1] * 1.2))
    a, b = pts_s[-1], pts_e[-1]
    xs = [a[0], b[0]] + [r[0] for r in blocks] + [r[2] for r in blocks]
    ys = [a[1], b[1]] + [r[1] for r in blocks] + [r[3] for r in blocks]
    x0 = max(min(xs), min(a[0], b[0]) - 40) - 4
    x1 = min(max(xs), max(a[0], b[0]) + 40) + 4
    y0 = max(min(ys), min(a[1], b[1]) - 40) - 4
    y1 = min(max(ys), max(a[1], b[1]) + 40) + 4
    cell = max(cell, (x1 - x0) / 220, (y1 - y0) / 220)
    nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    grown = [grow(r, margin) for r in blocks]

    def blocked_pt(x, y):
        return any(r[0] < x < r[2] and r[1] < y < r[3] for r in grown)

    def to_cell(p):
        return (min(nx - 1, max(0, int(round((p[0] - x0) / cell)))), min(ny - 1, max(0, int(round((p[1] - y0) / cell)))))

    def to_pt(c):
        return (x0 + c[0] * cell, y0 + c[1] * cell)
    sc, ec = to_cell(a), to_cell(b)
    free = 0.9 if margin < 1.0 else margin + 0.35   # a wide vehicle needs room to arrive next to its target
    free_near = lambda c: math.hypot(*(u - v for u, v in zip(to_pt(c), a))) < free or \
        math.hypot(*(u - v for u, v in zip(to_pt(c), b))) < free

    def blocked(c):
        return blocked_pt(*to_pt(c)) and not free_near(c)
    if _clear_line(a, b, grown, free):
        line = [a, b]
    else:
        openq = [(0.0, sc)]
        came, cost = {sc: None}, {sc: 0.0}
        found = False
        steps = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
        while openq:
            _, cur = heapq.heappop(openq)
            if cur == ec:
                found = True
                break
            for dx, dy in steps:
                nxt = (cur[0] + dx, cur[1] + dy)
                if not (0 <= nxt[0] < nx and 0 <= nxt[1] < ny) or blocked(nxt):
                    continue
                c = cost[cur] + (1.4142 if dx and dy else 1.0)
                if c < cost.get(nxt, 1e18):
                    cost[nxt] = c
                    came[nxt] = cur
                    heapq.heappush(openq, (c + math.hypot(nxt[0] - ec[0], nxt[1] - ec[1]), nxt))
        if not found:
            raise ValueError("There's no clear way for a path between those two places: something blocks it.")
        cells = []
        cur = ec
        while cur is not None:
            cells.append(cur)
            cur = came[cur]
        cells.reverse()
        pts = [a] + [to_pt(c) for c in cells[1:-1]] + [b]
        line = [pts[0]]          # string-pulling: keep only the turns the obstacles force
        i = 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not _clear_line(pts[i], pts[j], grown, free):
                j -= 1
            line.append(pts[j])
            i = j
    out = pts_s[:-1] + line + list(reversed(pts_e[:-1]))
    cleaned = [out[0]]
    for p in out[1:]:
        if math.hypot(p[0] - cleaned[-1][0], p[1] - cleaned[-1][1]) > 0.05:
            cleaned.append(p)
    return [(round(x, 3), round(y, 3)) for x, y in _no_doubling_back(cleaned)]


def _no_doubling_back(pts) -> list:
    """A walkable line: no bend sharper than ~110 degrees (a path that walks out of a door and straight back in
    makes a spike), no stubs shorter than 0.3 m. The two ends always stay."""
    pts = list(pts)
    changed = True
    while changed and len(pts) > 2:
        changed = False
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
            l1, l2 = math.hypot(*v1), math.hypot(*v2)
            if l1 < 0.3 or l2 < 0.3 or (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2) < -0.34:
                del pts[i]
                changed = True
                break
    return pts


def _clear_line(p, q, grown, free=0.9) -> bool:
    n = max(2, int(math.hypot(q[0] - p[0], q[1] - p[1]) / 0.2))
    for k in range(1, n):
        t = k / n
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        if math.hypot(x - p[0], y - p[1]) < free or math.hypot(x - q[0], y - q[1]) < free:
            continue
        if any(r[0] < x < r[2] and r[1] < y < r[3] for r in grown):
            return False
    return True


def path_ends(a_t, b_t) -> tuple:
    """(start, start direction, end, end direction) for a path from thing a (its entrance, if it has one) to the
    nearest point of thing b's edge."""
    if a_t["category"] == "building" or a_t["door"] is not None:
        start, sdir = entrance(a_t), a_t["front"]
    else:
        start, sdir = _edge_point(a_t["outer"], center(b_t["outer"]))
    end, edir = _edge_point(b_t["outer"], start)
    return start, sdir, end, (-edir[0], -edir[1])


def _edge_point(r, toward) -> tuple:
    """The point on rectangle r's edge facing `toward`, just outside it, with the outward direction."""
    cx, cy = center(r)
    dx, dy = toward[0] - cx, toward[1] - cy
    hx, hy = (r[2] - r[0]) / 2, (r[3] - r[1]) / 2
    # Toward the middle of that side (its central half): a round pond or a fountain only touches its bounding box
    # there, and a path that meets a pool square-on near its middle looks intended.
    if abs(dx) * hy >= abs(dy) * hx:   # leaves through the left/right side
        side = (math.copysign(1, dx), 0.0)
        y = min(cy + hy * 0.5, max(cy - hy * 0.5, toward[1]))
        return ((r[2] + 0.1) if dx > 0 else (r[0] - 0.1), y), side
    side = (0.0, math.copysign(1, dy))
    x = min(cx + hx * 0.5, max(cx - hx * 0.5, toward[0]))
    return (x, (r[3] + 0.1) if dy > 0 else (r[1] - 0.1)), side


# ---------- what a request says about where things go ----------

_ARTICLES = r"(?:the|a|an|my|our|its|this|that|some|two|three|four|five|\d+)"


def _nouns(text) -> list:
    """[(position, word)] of the thing-words in `text`, plus quoted names (exact names) — in order."""
    out = []
    for m in re.finditer(r"'([^']+)'|\"([^\"]+)\"", text):
        out.append((m.start(), "'" + (m.group(1) or m.group(2)) + "'"))
    spans = [(m.start(), m.end()) for m in re.finditer(r"'[^']+'|\"[^\"]+\"", text)]
    joined = _OUTDOOR_PHRASES.sub(lambda m: m.group(0).replace(" ", "").ljust(len(m.group(0))), text)
    for m in re.finditer(r"[A-Za-z]+", joined):
        if any(a <= m.start() < b for a, b in spans):
            continue
        w = singular(m.group(0))
        if w in VOCAB or w in FOOTPRINTS or w in DOOR_WORDS or w in ROOMS or w.lower() in _PRONOUN:
            out.append((m.start(), w.lower()))
    return sorted(out)


def parse_relations(text) -> list:
    """Where the request says things go: [{"subject", "relation", "anchor", "to"}] with nouns or 'quoted names'
    ("it" resolved to the request's main thing). "a modern villa with a pool beside it and a path from the
    entrance to the pool" -> pool beside villa; path connects entrance (the villa) -> pool."""
    text = " ".join(str(text or "").split())
    nouns = _nouns(text)
    if not nouns:
        return []
    main = next((w for _, w in nouns if w not in _PRONOUN), None)
    out = []
    for m in _CONNECT_RE.finditer(text):
        a = m.group("a") or m.group("c") or m.group("e")
        b = m.group("b") or m.group("d") or m.group("f") or m.group("g")
        before = [w for p, w in nouns if p < m.start() and w not in _PRONOUN]
        subject = next((w for w in reversed(before) if w in PATH), None)
        if subject is None:
            continue
        a_noun = _first_noun(a) if a else None
        b_noun = _first_noun(b)
        if not b_noun or (a and not a_noun):
            continue
        if a_noun in _PRONOUN:
            a_noun = main
        if b_noun in _PRONOUN:
            b_noun = main
        out.append({"subject": subject, "relation": "connects", "anchor": a_noun or "entrance", "to": b_noun})
    for m in _REL_RE.finditer(text):
        rel = normalize_relation(m.group("rel"))
        before = [(p, w) for p, w in nouns if p < m.start()]
        after = [(p, w) for p, w in nouns if p >= m.end()]
        clause = re.split(r"[,.;!?]|\band\b|\bwith\b", text[:m.start()])[-1]
        subject = next((w for p, w in reversed(before) if w not in _PRONOUN and p >= m.start() - len(clause) - 1),
                       None)
        if subject is None or not after:
            continue
        gap_text = text[m.end():after[0][0]]
        if len(gap_text.split()) > 3 or re.search(r"[,.;]", gap_text):
            continue
        anchor = after[0][1]
        if anchor in _PRONOUN:
            anchor = main
        if not anchor or anchor == subject:
            continue
        if subject in PATH and any(r["subject"] == subject and r["relation"] == "connects" for r in out):
            continue
        if rel == "between":
            second = next((w for p, w in after[1:] if w not in _PRONOUN), None)
            if second:
                out.append({"subject": subject, "relation": "between", "anchor": anchor, "to": second})
            continue
        if rel == "inside" and not (anchor in BUILDING or anchor in ROOMS or anchor in SUNKEN or anchor.startswith("'")):
            continue   # "a house in the forest", "in red"
        if rel == "on" and anchor in GROUND:
            continue   # standing on the ground / an island is handled where things are placed
        if rel == "inside" and anchor in ROOMS:
            anchor = next((w for w in (main,) if w in BUILDING), "building")
        out.append({"subject": subject, "relation": rel, "anchor": anchor, "to": None})
    return out


def _first_noun(text) -> str:
    found = _nouns(str(text or ""))
    return found[0][1] if found else None


# ---------- verifying a built scene ----------

def validate(state, before=None, intents=(), floating_ok=False, underground_ok=False, inside_ok=False,
             sized=False, subject_hint=None, existing_ok=True) -> list:
    """Spatial problems with what was made since `before` (all things when before is None), each with a concrete
    repair where one exists: [{"kind", "thing", "other", "text", "fix"}]. fix: {"move": (dx, dy)}, {"lift": dz},
    {"route": (path name, from name, to name)} or None.
    kinds: relation, inside_building, intersection, below_ground, path."""
    ts = merge_new(things(state, before), subject_hint)
    by = {t["name"]: t for t in ts}
    new = [t for t in ts if t["new"]]
    issues = []
    handled = set()
    for intent in intents or ():
        # whose place a relation binds: what this request made — or, when it moves things, what's there
        pool_ = new if (new or not existing_ok) else ts
        sub = find_thing(pool_, subject_hint if subject_hint and intent.get("subject") in (None, "it") else
                         intent.get("subject"))
        if sub is None and subject_hint:
            sub = find_thing(pool_, subject_hint)
        if sub is None:
            continue
        rel = normalize_relation(intent.get("relation"))
        anchor = find_thing(ts, intent.get("anchor"), exclude=(sub["name"],))
        if rel == "connects":
            end = find_thing(ts, intent.get("to"), exclude=(sub["name"],))
            if sub["category"] != "path" or anchor is None or end is None or anchor is end:
                continue
            ok, problems = check_path(sub, anchor, end, ts)
            if not ok:
                handled.add(sub["name"])
                issues.append({"kind": "path", "thing": sub["name"], "other": end["name"], "text": "; ".join(problems),
                               "fix": {"route": (sub["name"], anchor["name"], end["name"])} if sub["new"] else None})
            continue
        if anchor is None or rel in ("between", ""):
            continue
        ok, why = check_relation(sub, rel, anchor, ts)
        if ok:
            continue
        handled.add(sub["name"])
        fix = None
        if (sub["new"] or subject_hint) and sub["category"] != "path":   # a path is re-laid, never moved
            size = (sub["rect"][2] - sub["rect"][0], sub["rect"][3] - sub["rect"][1])
            spot = place_relative(anchor, rel, size, ts, sub["category"], ignore=(sub["name"],), orient=False)
            if spot is not None:
                c = center(sub["rect"])
                fix = {"move": (round(spot["x"] - c[0], 3), round(spot["y"] - c[1], 3)),
                       "z": spot.get("z")}
        issues.append({"kind": "relation", "thing": sub["name"], "other": anchor["name"], "text": why, "fix": fix})
    buildings = [t for t in ts if t["category"] == "building"]
    if not inside_ok:
        for t in new:
            if t["name"] in handled or t["category"] not in ("outdoor", "sunken", "building"):
                continue
            for b in buildings:
                if b is t:
                    continue
                inner = overlap_area(t["rect"], b["core"]) / max(1e-6, min(area(t["rect"]), area(b["core"])))
                if inner > 0.25 or (contains(b["core"], center(t["rect"])) and overlap_depth(t["rect"], b["core"]) > 0.3):
                    size = (t["rect"][2] - t["rect"][0], t["rect"][3] - t["rect"][1])
                    spot = place_relative(b, "beside", size, ts, t["category"], ignore=(t["name"],), orient=False)
                    c = center(t["rect"])
                    fix = {"move": (round(spot["x"] - c[0], 3), round(spot["y"] - c[1], 3))} if spot else None
                    issues.append({"kind": "inside_building", "thing": t["name"], "other": b["name"],
                                   "text": f"'{t['name']}' ({t['category']}) is inside the building '{b['name']}' — "
                                           f"it belongs outside, clear of its footprint", "fix": fix})
                    handled.add(t["name"])
                    break
        # a pool or a tree made as a PART of a building ('Villa Pool') that ended up inside it
        for b in buildings:
            for p in b["parts"]:
                if p["name"] not in b["new_parts"]:
                    continue
                rest = p["name"][len(b["name"]):] if p["name"].lower().startswith(b["name"].lower()) else p["name"]
                ws = set(words_of(rest))
                if not ws & (SUNKEN | OUTDOOR) or ws & {"wall", "roof", "window", "door"}:
                    continue
                r = rect_of(p["min"], p["max"])
                if contains(b["core"], center(r)) and overlap_depth(r, b["core"]) > 0.3:
                    issues.append({"kind": "inside_building", "thing": p["name"], "other": b["name"],
                                   "text": f"'{p['name']}' is inside the building '{b['name']}': an outdoor thing "
                                           "belongs outside its walls", "fix": None})
    # things standing inside each other (a tree in the pool, a bench on the path, two houses in one spot)
    ends = {t["name"]: set(t.get("ends") or ()) for t in ts if t["category"] == "path"}
    for intent in intents or ():
        if normalize_relation(intent.get("relation")) != "connects":
            continue
        p = find_thing(ts, subject_hint if subject_hint and intent.get("subject") in (None, "it")
                       else intent.get("subject"))
        if p is not None and p["category"] == "path":
            for ref in (intent.get("anchor"), intent.get("to")):
                e = find_thing(ts, ref, exclude=(p["name"],))
                if e is not None:
                    ends.setdefault(p["name"], set()).add(e["name"])
    for i, t in enumerate(ts):
        if t["category"] in ("ground", "surface", "sky", "backdrop"):
            continue
        for u in ts[i + 1:]:
            if u["category"] in ("ground", "surface", "sky", "backdrop") or not (t["new"] or u["new"]):
                continue
            if t["name"] in handled or u["name"] in handled:
                continue
            cats = (t["category"], u["category"])
            if cats == ("path", "path") or ("path" in cats and "building" in cats):
                continue   # paths meet each other, and a building at its door: checked as paths
            if inside_ok and "building" in cats:
                continue
            if t["category"] == "building" and u["category"] in ("furniture", "object") or \
                    u["category"] == "building" and t["category"] in ("furniture", "object"):
                continue   # furniture inside a house is where it belongs
            if "path" in cats:
                path_t, other = (t, u) if t["category"] == "path" else (u, t)
                if other["name"] in ends.get(path_t["name"], ()):
                    continue   # a path is meant to reach its own two ends
            if t.get("trunk") and u.get("trunk"):
                # two trees: crowns interleave in any grove (a leaning palm over its neighbour); only trunks clash
                if overlap_area(t["trunk"], u["trunk"]) <= 0 and gap(t["trunk"], u["trunk"]) > 0.3:
                    continue
            elif not _footprints_clash(t, u, path_rule="path" in cats):
                continue
            if "path" in cats:   # something standing on a path: it's the thing that moves, never the path
                mover, fixed_one = (u, t) if t["category"] == "path" else (t, u)
                if not mover["new"]:
                    continue
            else:
                mover, fixed_one = (u, t) if (u["new"] and (not t["new"] or area(u["rect"]) <= area(t["rect"]))) \
                    else (t, u)
            size = (mover["rect"][2] - mover["rect"][0], mover["rect"][3] - mover["rect"][1])
            c = center(mover["rect"])
            spot = place_free(c[0], c[1], size, ts, mover["category"], ignore=(mover["name"],))
            fix = {"move": (round(spot["x"] - c[0], 3), round(spot["y"] - c[1], 3))} if spot and mover["new"] else None
            issues.append({"kind": "intersection", "thing": mover["name"], "other": fixed_one["name"],
                           "text": f"'{mover['name']}' and '{fixed_one['name']}' stand inside each other", "fix": fix})
            handled.add(mover["name"])
    if not underground_ok:
        for t in new:
            if t["category"] in ("sunken", "ground", "path", "surface", "sky", "backdrop") or t["name"] in handled:
                continue
            if t["asset_type"] or any(p.get("asset") for p in t["parts"]):
                continue   # finished assets ground themselves (a palm's roots reach below the ground on purpose)
            low = t["lo"][2]
            if low >= -0.08:
                continue
            bottoms = [p["min"][2] for p in t["parts"]]
            sunk = [b for b in bottoms if b < 0.05]
            if sunk and max(sunk) - min(sunk) <= 0.06:   # the whole thing was built too low, not one long part
                issues.append({"kind": "below_ground", "thing": t["name"], "other": "the ground",
                               "text": f"'{t['name']}' is sunk {abs(low):.2f} m below the ground",
                               "fix": {"lift": round(-low, 3)}})
    for issue in issues:   # the very objects each repair must move (a merged thing has no single root)
        t = by.get(issue["thing"])
        issue["names"] = list(t["names"]) if t else [issue["thing"]]
        issue["lo_z"] = t["lo"][2] if t else 0.0
    return issues


def footprints(t) -> list:
    """A thing's footprint as rectangles: its body, and each path of its own separately (so the ground beside a
    house's front path is still free ground, not 'inside the house'); a path, piece by piece along its route."""
    if t.get("pieces"):
        return list(t["pieces"])
    return [t["outer"]] + list(t["side_parts"])


def _footprints_clash(t, u, path_rule=False) -> bool:
    """Do two things really stand inside each other: their bodies overlap in height and, seen from above, by more
    than a sliver (15 % of the smaller one; for something on a path, 30 % of it)?"""
    pen_z = min(t["hi"][2], u["hi"][2]) - max(t["lo"][2], u["lo"][2])
    if path_rule:   # a path is a few centimetres thick: what stands on it is "in" it whatever the height overlap
        flat, other = (t, u) if t["category"] == "path" else (u, t)
        if other["lo"][2] > flat["hi"][2] + 0.3 or other["hi"][2] < flat["lo"][2]:
            return False
    elif pen_z <= 0.15:
        return False
    for a in footprints(t):
        for b in footprints(u):
            if min(a[2] - a[0], a[3] - a[1]) < 0.15 or min(b[2] - b[0], b[3] - b[1]) < 0.15:
                continue   # a panel or a sign set against something
            if overlap_depth(a, b) <= 0.15:
                continue
            small = min(area(a), area(b))
            if overlap_area(a, b) >= (0.3 if path_rule else 0.15) * small:
                return True
    return False


def describe(ts, limit=24) -> list:
    """The scene's things as lines for the AI: what each is, its footprint, which way a building faces."""
    lines = []
    for t in ts[:limit]:
        r = t["outer"]
        extra = ""
        if t["category"] == "building":
            e = entrance(t)
            extra = f", front faces {_facing(t['front'])}, entrance at ({e[0]:.1f}, {e[1]:.1f})"
        lines.append(f"- '{t['name']}' ({t['category']}{', ' + t['asset_type'] if t['asset_type'] else ''}): "
                     f"footprint x {r[0]:.1f}..{r[2]:.1f}, y {r[1]:.1f}..{r[3]:.1f}, z {t['lo'][2]:.1f}..{t['hi'][2]:.1f}"
                     f"{extra}")
    return lines
