"""The world around what was asked for. A villa, a shop, a waterfall, a cabin is the SUBJECT of a place: its ground,
what grows round it, what stands near it (a street, a shore, a driveway), what lies behind it (a treeline, hills), its
sky, light and air, what moves in it, and a camera that shows it all. Which place is decided from the request's words
and from what was built (settings and recipes are data: adding a place is adding a row); where everything goes is
measured on the real scene — around the subject, never in it, keeping its entrance and the camera's view clear.

plan(goal, state, before) -> {"setting", "steps": [{"title", "code", "checks"}], "said": [...]} or None
assess(measures) -> the problems a render of it shows (empty sky, subject cropped or lost, too dark...) and fixes.
Pure Python: the kit builders (blender_places, blender_assets, blender_world) do the building."""
import hashlib
import math
import random
import re

import semantics
import spatial

# "just a tree", "a chair on a plain plane", "no background": the object alone, as asked
OPT_OUT = re.compile(r"\b(?:no|without(?: any| a)?) (?:environment|background|scenery|surroundings|ground|world|sky)\b|"
                     r"\bon (?:a|an|the) (?:plain|empty|default|flat|white|grey|gray) (?:plane|floor|ground|background)\b|"
                     r"\b(?:isolated|standalone|on its own|by itself|alone)\b|"
                     r"\b(?:just|only) (?:a|an|the|one)\b(?!.*\b(?:scene|environment|world|landscape)\b)", re.I)
# a request that IS for a place (always gets its world, even added to a scene that has things)
SCENE_WORDS = re.compile(r"\b(?:scene|environment|landscape|world|place|setting|surroundings|location)\b", re.I)

# ---------- the places ----------
# ground: (kind, hilly) or None when a builder brings its own (a shore, an island's sea, a room)
# layers: what grows or lies around: (forest kind, zone, density per 100 m2, clumps, depth m)
#   zones: back (behind the subject), sides, ring (all round, a clearing), near (hugging its walls),
#          field (scattered over the open ground, off the view's corridor), edge (along the front's far sides)
# details: recipes (functions below) in order; clouds: sky cover; haze: density; wind: sway strength or None
SETTINGS = {
    "residential": dict(
        words=r"house|home|villa|cottage|bungalow|mansion|garage|porch|driveway|garden|yard|backyard|residence",
        kinds={"house", "villa", "garage", "gate", "pool", "fence"},
        ground=("lawn", 0.35), patches=[("wild grass", 5, 7.0), ("dirt", 2, 2.2)],
        layers=[("mixed", "back", 0.5, 4, 14.0), ("mixed", "sides", 0.35, 3, 10.0), ("shrubs", "near", 6.0, 0, 1.8),
                ("flowers", "near", 14.0, 4, 1.5), ("grass", "field", 6.0, 10, 0.0), ("flowers", "field", 0.8, 6, 0.0)],
        details=["driveway", "treeline", "hills"], clouds=0.3, haze=0.0015, wind=0.4),
    "urban": dict(
        words=r"shop|store|storefront|shopfront|caf[eé]|restaurant|bakery|bar|pub|boutique|office|apartments?|"
              r"city|town|downtown|street|urban|market|bookshop|bookstore|pharmacy|hotel|plaza",
        kinds={"storefront"},
        ground=("paving", 0.0), patches=[], layers=[],
        details=["street", "neighbours", "street_lamps", "street_trees", "parked_car", "city_backdrop"],
        clouds=0.25, haze=0.002, wind=None),
    "coastal": dict(
        words=r"beach|seaside|shore|coast(?:al|line)?|ocean|sea|surf|tropical|palms?|lighthouse|pier|bay",
        kinds=set(),
        ground=None, patches=[], layers=[("grass", "back", 3.0, 6, 6.0), ("grass", "field", 1.5, 8, 0.0),
                                         ("rocks", "field", 0.08, 4, 0.0), ("shrubs", "field", 0.06, 4, 0.0)],
        details=["shore", "palms", "beach_rocks", "headland"], clouds=0.35, haze=0.0018, wind=0.7),
    "island": dict(
        words=r"island|atoll|islet",
        kinds={"island"},
        ground=None, patches=[], layers=[], details=["open_sea", "far_islands"], clouds=0.3, haze=0.0015, wind=0.6),
    "waterfall": dict(
        words=r"waterfall|cascade|falls",
        kinds={"waterfall"},
        ground=("wild grass", 0.6), patches=[("forest floor", 8, 9.0), ("dirt", 3, 3.0)],
        layers=[("ferns", "field", 8.0, 10, 0.0), ("grass", "field", 6.0, 10, 0.0), ("shrubs", "field", 0.8, 8, 0.0),
                ("mixed", "ring", 0.9, 6, 16.0)],
        details=["falls_forest", "falls_stream", "mossy_rocks", "treeline", "hills"], clouds=0.3, haze=0.0, wind=0.3,
        mist=True),
    "forest": dict(
        words=r"forest|woods|woodland|jungle|cabin|campsite|camp|campfire|tent|trail|clearing|log cabin|lodge",
        kinds=set(),
        ground=("forest floor", 0.8), patches=[("dirt", 4, 3.0), ("wild grass", 8, 7.0)],
        layers=[("mixed", "ring", 1.3, 6, 18.0), ("shrubs", "ring", 1.2, 6, 10.0), ("ferns", "field", 8.0, 10, 0.0),
                ("grass", "field", 6.0, 10, 0.0)],
        details=["mossy_rocks", "treeline"], clouds=0.3, haze=0.004, wind=0.4),
    "waterside": dict(
        words=r"river|stream|creek|brook|lake|pond|lakeside|riverside",
        kinds={"river", "pond", "water"},
        ground=("lawn", 0.5), patches=[("wild grass", 6, 7.0)],
        layers=[("mixed", "back", 0.5, 4, 14.0), ("reeds", "near", 10.0, 6, 2.0), ("grass", "field", 6.0, 10, 0.0)],
        details=["mossy_rocks", "treeline", "hills"], clouds=0.35, haze=0.002, wind=0.4),
    "mountain": dict(
        words=r"mountains?|peak|alpine|summit|cliffs?|valley|canyon|ridge|rocky|highlands?",
        kinds=set(),
        ground=("wild grass", 2.5), patches=[("rock", 6, 5.0), ("dirt", 3, 3.0)],
        layers=[("pine", "sides", 0.4, 5, 14.0), ("rocks", "field", 0.8, 6, 0.0), ("grass", "field", 6.0, 10, 0.0)],
        details=["peaks", "boulders"], clouds=0.4, haze=0.003, wind=0.5),
    "park": dict(
        words=r"park|playground|picnic|fountain|gardens|lawn|meadow",
        kinds={"fountain", "bench"},
        ground=("lawn", 0.3), patches=[("wild grass", 4, 6.0)],
        layers=[("mixed", "sides", 0.4, 4, 12.0), ("mixed", "back", 0.4, 4, 12.0), ("flowers", "field", 1.5, 6, 0.0),
                ("grass", "field", 6.0, 10, 0.0)],
        details=["park_path", "benches", "treeline"], clouds=0.35, haze=0.0015, wind=0.4),
    "desert": dict(
        words=r"desert|dunes?|cactus|cacti|oasis|sahara|arid",
        kinds=set(),
        ground=("sand", 1.6), patches=[("dirt", 4, 6.0)], layers=[("rocks", "field", 0.4, 5, 0.0),
                                                                   ("shrubs", "field", 0.3, 4, 0.0)],
        details=["boulders", "peaks"], clouds=0.05, haze=0.003, wind=None),
    "rural": dict(
        words=r"farm|barn|field|ranch|countryside|village|windmill|orchard|vineyard|silo",
        kinds=set(),
        ground=("wild grass", 0.6), patches=[("dirt", 3, 4.0), ("lawn", 4, 6.0)],
        layers=[("mixed", "back", 0.3, 4, 14.0), ("grass", "field", 6.0, 10, 0.0), ("flowers", "field", 0.8, 6, 0.0)],
        details=["fence_line", "treeline", "hills"], clouds=0.35, haze=0.002, wind=0.4),
    "road": dict(
        words=r"road|highway|motorway|route|freeway",
        kinds={"road"},
        ground=("wild grass", 0.5), patches=[("dirt", 3, 3.0)],
        layers=[("mixed", "sides", 0.25, 4, 12.0), ("grass", "field", 6.0, 10, 0.0)],
        details=["roadside_lamps", "treeline", "hills"], clouds=0.3, haze=0.002, wind=0.3),
    "interior": dict(
        words=r"room|interior|living room|bedroom|kitchen|lounge|indoors|inside",
        kinds={"sofa", "armchair", "coffee_table", "table", "chair", "tv", "shelf", "rug", "floor_lamp", "bed"},
        ground=None, patches=[], layers=[], details=["room_around"], clouds=None, haze=0.0, wind=None),
    "meadow": dict(   # anything else outdoors: open country
        words=r"$^", kinds=set(),
        ground=("lawn", 0.5), patches=[("wild grass", 6, 7.0), ("dirt", 2, 2.0)],
        layers=[("mixed", "back", 0.35, 4, 14.0), ("mixed", "sides", 0.2, 3, 10.0), ("grass", "field", 6.0, 10, 0.0),
                ("flowers", "field", 0.8, 6, 0.0)],
        details=["treeline", "hills"], clouds=0.3, haze=0.0015, wind=0.4),
}
# a setting named in the request wins over one implied by what was built ("a cabin on a beach" is coastal)
PRIORITY = ["interior", "waterfall", "island", "coastal", "desert", "mountain", "forest", "waterside", "urban",
            "park", "rural", "road", "residential", "meadow"]


def opted_out(goal: str) -> bool:
    return bool(OPT_OUT.search(goal or ""))


def classify(goal: str, subjects: list) -> str:
    """The place: the setting the request names (its own words win), else the one its subject implies."""
    text = (goal or "").lower()
    named = [k for k in PRIORITY if re.search(rf"\b(?:{SETTINGS[k]['words']})\b", text)]
    kinds = {str(t.get("asset_type") or "") for t in subjects} | \
        {w for t in subjects for w in spatial.words_of(t["name"])}
    implied = [k for k in PRIORITY if SETTINGS[k]["kinds"] & kinds]
    # "a cabin in the woods": the woods; "a shop": the street; "a villa by the sea": the coast
    for k in PRIORITY:
        if k in named and k not in ("residential", "urban", "road") or (k in named and not implied):
            return k
    if implied:
        return implied[0]
    if named:
        return named[0]
    return "meadow"


# ---------- the subject, measured ----------

class Ctx:
    """The subject's place in the world: its centre, its front (toward the viewer), half sizes along its side (u)
    and front (v) axes, how far the world reaches (R), what must stay clear, and the names already taken."""

    def __init__(self, goal, subjects, taken, setting):
        self.goal, self.setting = goal, setting
        self.subjects = subjects
        x0 = min(t["outer"][0] for t in subjects)
        y0 = min(t["outer"][1] for t in subjects)
        x1 = max(t["outer"][2] for t in subjects)
        y1 = max(t["outer"][3] for t in subjects)
        self.rect = (x0, y0, x1, y1)
        self.c = ((x0 + x1) / 2, (y0 + y1) / 2)
        main = max(subjects, key=lambda t: (t["category"] == "building", spatial.area(t["outer"])))
        self.main = main
        fx, fy = main.get("front") or (0.0, -1.0)
        if abs(fx) > abs(fy):
            fx, fy = (1.0 if fx > 0 else -1.0), 0.0
        else:
            fx, fy = 0.0, (1.0 if fy > 0 else -1.0)
        self.f = (fx, fy)
        self.s = (-fy, fx)   # its right-hand side, seen from in front
        w, d = x1 - x0, y1 - y0
        self.hu, self.hv = (w / 2, d / 2) if fx == 0 else (d / 2, w / 2)
        self.size = max(w, d, 4.0)
        self.top = max(t["hi"][2] for t in subjects)
        self.R = max(22.0, min(90.0, self.size * 2.6))
        seed = int(hashlib.sha1((goal or "").encode("utf-8")).hexdigest()[:6], 16)
        self.rng = random.Random(seed)
        self.seed = seed % 997
        self.taken = set(taken)
        self.keep = [self.local_rect(-self.hu - 2.0, self.hu + 2.0, -self.hv - 2.0, self.hv + 2.0)]
        for t in subjects:   # its own paths and steps too: nothing grows on a front path
            self.keep += [(r[0] - 0.6, r[1] - 0.6, r[2] + 0.6, r[3] + 0.6) for r in t.get("side_parts") or []]
        # the view: the open ground in front of it, where trees would hide it (low plants may grow there)
        self.view = self.local_rect(-self.hu - self.R * 0.35, self.hu + self.R * 0.35, self.hv, self.hv + self.R * 1.1)
        self.lines, self.said, self.names = [], [], []

    def at(self, u, v):
        """World (x, y) of a point u metres to the subject's right and v in front of its centre."""
        return (self.c[0] + self.s[0] * u + self.f[0] * v, self.c[1] + self.s[1] * u + self.f[1] * v)

    def local_rect(self, u0, u1, v0, v1):
        pts = [self.at(u, v) for u in (u0, u1) for v in (v0, v1)]
        return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))

    def name(self, base):
        n, k = base, 2
        while n.lower() in self.taken:
            n, k = f"{base} {k}", k + 1
        self.taken.add(n.lower())
        self.names.append(n)
        return n

    def rotation(self):
        """Degrees turning a builder's default (facing -y, running along x) to face the subject's front."""
        return round(math.degrees(math.atan2(self.f[0], -self.f[1])), 1) % 360

    def add(self, code, said=None):
        self.lines.append(code)
        if said:
            self.said.append(said)


def _r(v):
    return round(float(v), 2)


def _rect_txt(r):
    return "(" + ", ".join(f"{v:.1f}" for v in r) + ")"


def _scatter(ctx, kind, rect, count, clumps=0, avoid=None, label=None, role_kind="forest"):
    """forest() of `kind` over a world rect (x0, y0, x1, y1), keeping off `avoid` rects."""
    x0, y0, x1, y1 = rect
    w, d = x1 - x0, y1 - y0
    if w < 1.0 or d < 1.0 or count < 1:
        return None
    nm = ctx.name(label or {"mixed": "Trees", "pine": "Pines", "shrubs": "Shrubs", "flowers": "Flowers",
                            "grass": "Grass", "ferns": "Ferns", "reeds": "Reeds", "rocks": "Rocks",
                            "mossy rocks": "Mossy Rocks", "tropical": "Palms", "palm": "Palms"}.get(kind, "Plants"))
    av = ", ".join(_rect_txt(a) for a in (avoid if avoid is not None else ctx.keep))
    what = "rock" if "rock" in kind else "forest" if kind in ("mixed", "pine", "tropical") else "bush"
    ctx.add(f"try:   # (no room left there: this planting is skipped, not the rest)\n"
            f"    forest({nm!r}, at=({_r((x0 + x1) / 2)}, {_r((y0 + y1) / 2)}, 0), width={_r(w)}, depth={_r(d)}, "
            f"count={int(count)}, kind={kind!r}, seed={ctx.rng.randint(1, 999)}, clumps={int(clumps)}, "
            f"avoid=[{av}])\n"
            f"    tag_semantic({nm!r}, {what!r}, role='surroundings', source='inferred')\n"
            f"except ValueError:\n    pass")
    return nm


# ---------- recipes: what a place has ----------

def r_ground(ctx, spec):
    kind, hilly = spec["ground"]
    size = max(220.0, ctx.R * 6)
    nm = ctx.name("Ground")
    ctx.add(f"ground({nm!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, 0), size={size:.0f}, kind={kind!r}, hilly={hilly})",
            f"{kind} ground")
    ctx.add(f"tag_semantic({nm!r}, 'terrain', role='the ground', source='inferred')")


def r_patches(ctx, spec):
    for kind, count, size in spec["patches"]:
        nm = ctx.name({"wild grass": "Wild Grass", "dirt": "Bare Earth", "rock": "Rock Ground", "lawn": "Lawn"}
                      .get(kind, kind.title()) + " Patches")
        area = ctx.R * 1.6
        av = ", ".join(_rect_txt(a) for a in ctx.keep)
        ctx.add(f"patches({nm!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, 0), area={area:.0f}, count={count}, "
                f"size={size}, kind={kind!r}, seed={ctx.rng.randint(1, 999)}, avoid=[{av}])")
        ctx.add(f"tag_semantic({nm!r}, 'terrain', role='surroundings', source='inferred')")


def r_layers(ctx, spec):
    hu, hv, R = ctx.hu, ctx.hv, ctx.R
    for kind, zone, density, clumps, depth in spec["layers"]:
        rects = []
        avoid = list(ctx.keep)
        if zone == "back":
            rects = [ctx.local_rect(-hu - R * 0.5, hu + R * 0.5, -hv - 4.0 - depth, -hv - 4.0)]
        elif zone == "sides":
            for sgn in (-1, 1):
                u_in, u_out = hu + 5.0, hu + 5.0 + depth
                rects.append(ctx.local_rect(min(sgn * u_in, sgn * u_out), max(sgn * u_in, sgn * u_out),
                                            -hv - 2.0, hv + R * 0.25))
            avoid.append(ctx.view)
        elif zone == "ring":
            ring_in = max(hu, hv) + 7.0
            rects = [ctx.local_rect(-ring_in - depth, ring_in + depth, -ring_in - depth, -ring_in),   # behind
                     ctx.local_rect(-ring_in - depth, -ring_in, -ring_in, ring_in + R * 0.4),       # left
                     ctx.local_rect(ring_in, ring_in + depth, -ring_in, ring_in + R * 0.4)]         # right
            avoid.append(ctx.view)
        elif zone == "near":   # along its walls (and round its sides), not across its door
            band = depth
            rects = [ctx.local_rect(-hu - band, hu + band, hv + 0.3, hv + 0.3 + band),
                     ctx.local_rect(-hu - band - 0.3, -hu - 0.3, -hv, hv),
                     ctx.local_rect(hu + 0.3, hu + band + 0.3, -hv, hv)]
            door = ctx.local_rect(-2.2, 2.2, hv - 0.5, hv + 12.0)
            avoid = [ctx.local_rect(-hu - 0.2, hu + 0.2, -hv - 0.2, hv + 0.2), door]
        elif zone == "field":
            rects = [ctx.local_rect(-R, R, -R * 0.8, R * 0.9)]
            # the way to its door kept clear: a narrow strip for tufts, a broad one for shrubs and stones
            door = 2.0 if kind in ("grass", "flowers", "ferns", "reeds") else max(3.0, ctx.hu * 0.7)
            avoid = list(ctx.keep) + [ctx.local_rect(-door, door, ctx.hv, ctx.hv + R)]
        for rect in rects:
            area = (rect[2] - rect[0]) * (rect[3] - rect[1])
            count = max(2, min(400, int(area / 100.0 * density)))
            _scatter(ctx, kind, rect, count, clumps, avoid)
    if any(z in ("back", "sides", "ring") for _, z, *_ in spec["layers"]):
        ctx.said.append("trees and planting round it, off its front")


def r_driveway(ctx, spec):
    end = ctx.at(ctx.hu * 0.4, ctx.hv + ctx.R * 0.7)
    nm = ctx.name("Driveway")
    ctx.add(f"walkway({nm!r}, {ctx.main['name']!r}, ({_r(end[0])}, {_r(end[1])}), width=2.6, style='gravel')",
            "a drive to its door")
    ctx.add(f"tag_semantic({nm!r}, 'path', role='surroundings', source='inferred')")
    ctx.keep.append(ctx.local_rect(-2.5, 2.5, ctx.hv, ctx.hv + ctx.R * 0.75))


def r_treeline(ctx, spec):
    """Trees closing the view: behind, and — in wild country — round the sides too (an open plain running to the
    horizon on either side of a waterfall or a cabin read as an empty brown floor)."""
    kind = "pine" if ctx.setting in ("mountain",) else "mixed"
    v0 = -ctx.hv - ctx.R * 1.3
    rect = ctx.local_rect(-ctx.R * 2.2, ctx.R * 2.2, v0 - 16.0, v0)
    _scatter(ctx, kind, rect, min(400, int(ctx.R * 1.6)), 8, [], label="Treeline")
    if ctx.setting in ("forest", "waterfall", "waterside", "mountain"):
        for sgn in (-1, 1):
            u0, u1 = sorted((sgn * ctx.R * 1.4, sgn * (ctx.R * 1.4 + 18.0)))
            side = ctx.local_rect(u0, u1, v0, ctx.hv + ctx.R * 1.6)
            _scatter(ctx, kind, side, min(400, int(ctx.R * 2.2)), 8, [], label="Treeline")
        ctx.said.append("woods all round")
    else:
        ctx.said.append("a treeline behind")


def r_hills(ctx, spec):
    nm = ctx.name("Hills")
    ctx.add(f"hills({nm!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, 0), distance={max(160.0, ctx.R * 5):.0f}, "
            f"height={max(18.0, ctx.R * 0.5):.0f})", "hills in the distance")
    ctx.add(f"tag_semantic({nm!r}, 'hill', role='the distant hills', source='inferred')")


def r_peaks(ctx, spec):
    nm = ctx.name("Mountains")
    ctx.add(f"hills({nm!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, 0), distance={max(120.0, ctx.R * 3):.0f}, "
            f"height={max(60.0, ctx.R * 1.6):.0f}, color='hazy hills')", "mountains around")
    ctx.add(f"tag_semantic({nm!r}, 'hill', role='the distant hills', source='inferred')")


def r_street(ctx, spec):
    width = 9.0
    v = ctx.hv + 4.5 + width / 2
    at = ctx.at(0.0, v)
    nm = ctx.name("Street")
    ctx.add(f"road({nm!r}, at=({_r(at[0])}, {_r(at[1])}, 0), length={max(80.0, ctx.R * 4):.0f}, width={width}, "
            f"rotation={ctx.rotation()})", "a street in front with its pavements")
    ctx.add(f"tag_semantic({nm!r}, 'road', role='surroundings', source='inferred')")
    ctx.street_v = v


def r_neighbours(ctx, spec):
    """Buildings either side along the street: other shops, each its own colour and height — a street, not a
    lone shop."""
    colours = ["#c9b79c", "#8d5b4c", "#d8d2c4", "#6f7f8c", "#b88a5a", "#a7a99a"]
    ctx.rng.shuffle(colours)
    w_main = ctx.hu * 2
    for k, sgn in enumerate((-1, 1, -1, 1)):
        step = 1 + k // 2
        width = ctx.rng.uniform(7.0, 11.0)
        u = sgn * (ctx.hu + 0.4 + (step - 1) * 11.5 + width / 2 + (0 if step == 1 else 0.4))
        if step == 2:
            u = sgn * (ctx.hu + 0.4 + 11.5 + width / 2)
        at = ctx.at(u, 0.0)
        nm = ctx.name("Neighbour Shop" if ctx.setting == "urban" else "Neighbour House")
        floors = ctx.rng.choice((2, 2, 3))
        style = ctx.rng.choice(("modern", "traditional"))
        ctx.add(f"storefront({nm!r}, at=({_r(at[0])}, {_r(at[1])}, 0), width={width:.1f}, depth={max(8.0, ctx.hv * 2):.1f}, "
                f"floors={floors}, style={style!r}, color={colours[k]!r}, rotation={ctx.rotation()})")
        ctx.add(f"tag_semantic({nm!r}, 'shop', role='surroundings', source='inferred')")
        ctx.keep.append(ctx.local_rect(u - width / 2 - 0.5, u + width / 2 + 0.5, -ctx.hv - 1, ctx.hv + 1))
    ctx.said.append("its neighbours along the street")
    del w_main


def r_street_lamps(ctx, spec):
    v = getattr(ctx, "street_v", ctx.hv + 9.0) - 9.0 / 2 - 1.2
    span = ctx.hu + 24.0
    k = 0
    u = -span
    while u <= span:
        at = ctx.at(u, v)
        nm = ctx.name("Street Lamp")
        ctx.add(f"street_lamp({nm!r}, at=({_r(at[0])}, {_r(at[1])}, 0), rotation={ctx.rotation()})")
        ctx.add(f"tag_semantic({nm!r}, 'street lamp', role='surroundings', source='inferred')")
        u += 16.0
        k += 1
    ctx.said.append("street lamps")


def r_street_trees(ctx, spec):
    v = getattr(ctx, "street_v", ctx.hv + 9.0) - 9.0 / 2 - 0.9
    for sgn in (-1, 1):
        at = ctx.at(sgn * (ctx.hu + 6.0), v)
        nm = ctx.name("Street Tree")
        ctx.add(f"tree({nm!r}, at=({_r(at[0])}, {_r(at[1])}, 0), kind='birch', height=7.5, seed={ctx.rng.randint(1, 99)})")
        ctx.add(f"tag_semantic({nm!r}, 'tree', role='surroundings', source='inferred')")


def r_parked_car(ctx, spec):
    v = getattr(ctx, "street_v", ctx.hv + 9.0) - 1.6
    at = ctx.at(-ctx.hu - 3.0, v)
    nm = ctx.name("Parked Car")
    colour = ctx.rng.choice(("#2f3a44", "#8a8f94", "#7a1f1f", "#d9d6cf"))
    ctx.add(f"car({nm!r}, at=({_r(at[0])}, {_r(at[1])}, 0), color={colour!r}, rotation={(ctx.rotation() + 90) % 360})")
    ctx.add(f"tag_semantic({nm!r}, 'car', role='surroundings', source='inferred')")


def r_city_backdrop(ctx, spec):
    """Taller buildings behind the street's, so its roofline meets more city, not an empty horizon."""
    for k in range(5):
        u = (k - 2) * 16.0 + ctx.rng.uniform(-3, 3)
        at = ctx.at(u, -ctx.hv - 14.0 - ctx.rng.uniform(0, 8))
        nm = ctx.name("Block")
        ctx.add(f"house({nm!r}, at=({_r(at[0])}, {_r(at[1])}, 0), style='modern', floors={ctx.rng.choice((3, 4, 5))}, "
                f"width={ctx.rng.uniform(11, 15):.1f}, depth=10.0, walls={ctx.rng.choice(('#b9b2a6', '#9ea4a8', '#c7bba7', '#8c8378'))!r}, "
                f"rotation={ctx.rotation()})")
        ctx.add(f"tag_semantic({nm!r}, 'building', role='surroundings', source='inferred')")
    ctx.said.append("the city behind")


def r_shore(ctx, spec):
    """Sand under it, the sea beyond it (the camera on the beach looks past the subject out to sea)."""
    # shore(): sand toward -y, the sea beyond a waterline at y = at + 2.5 (as reconstruct uses it)
    water_y = ctx.rect[3] + 10.0
    nm = ctx.name("Beach")
    ctx.add(f"shore({nm!r}, at=({_r(ctx.c[0])}, {_r(water_y - 2.5)}, 0), width={max(160.0, ctx.R * 6):.0f}, "
            f"sand_depth={max(40.0, ctx.R * 1.8):.0f})", "a beach and the sea")
    ctx.add(f"tag_semantic({nm!r}, 'beach', role='the beach and the sea', source='inferred')")
    ctx.water_y = water_y
    ctx.keep.append((ctx.c[0] - 2000.0, water_y - 2.0, ctx.c[0] + 2000.0, water_y + 2000.0))   # nothing grows in the sea


def r_palms(ctx, spec):
    """Palms on the sand round it: near enough to be in the picture with it, never in it, never in the sea."""
    placed, tries = 0, 0
    while placed < 7 and tries < 80:
        tries += 1
        sgn = -1 if placed % 2 == 0 else 1
        u = sgn * ctx.rng.uniform(ctx.hu * 0.4 + 2.0, ctx.hu + ctx.R * 0.35)
        v = ctx.rng.uniform(-ctx.hv - 4.0, ctx.hv + ctx.R * 0.3)
        x, y = ctx.at(u, v)
        if hasattr(ctx, "water_y") and y > ctx.water_y - 4:
            continue
        if any(a[0] - 1.5 <= x <= a[2] + 1.5 and a[1] - 1.5 <= y <= a[3] + 1.5 for a in ctx.keep):
            continue
        if ctx.subjects[0]["name"] != "__place" and                 ctx.view[0] <= x <= ctx.view[2] and ctx.view[1] <= y <= ctx.view[3]:
            continue   # (between the camera and it: a trunk across the picture)
        nm = ctx.name("Palm")
        lean = ctx.rng.choice((None, 8, 14, 22))
        lean_dir = "left" if sgn < 0 else "right"
        extra = f", lean={lean}, lean_dir={lean_dir!r}" if lean else ""
        ctx.add(f"tree({nm!r}, at=({_r(x)}, {_r(y)}, 0), kind='palm', height={ctx.rng.uniform(6.5, 9.5):.1f}, "
                f"seed={ctx.rng.randint(1, 99)}{extra})")
        ctx.add(f"tag_semantic({nm!r}, 'palm tree', role='surroundings', source='inferred')")
        placed += 1
    ctx.said.append("palms")


def r_beach_rocks(ctx, spec):
    y = getattr(ctx, "water_y", ctx.rect[3] + 10.0)
    for sgn in (-1, 1):
        x = ctx.c[0] + sgn * (ctx.hu + ctx.R * 0.6)
        _scatter(ctx, "rocks", (x - 5, y - 4, x + 5, y + 1), 9, 2, [], label="Shore Rocks")


def r_headland(ctx, spec):
    nm = ctx.name("Headland")
    ctx.add(f"hills({nm!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, 0), distance={max(260.0, ctx.R * 8):.0f}, height=14)")
    ctx.add(f"tag_semantic({nm!r}, 'hill', role='the distant hills', source='inferred')")


def r_open_sea(ctx, spec):
    """The ocean out to the horizon round an island (its own sea is a square that ends): a little below it."""
    nm = ctx.name("Ocean")
    ctx.add(f"water({nm!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, -0.06), size=2000, waves=0.6)", "the open sea")
    ctx.add(f"tag_semantic({nm!r}, 'ocean', role='surroundings', source='inferred')")
    ctx.add(f"animate_water({nm!r}, 'waves', strength=0.8)")


def r_far_islands(ctx, spec):
    nm = ctx.name("Far Islands")
    ctx.add(f"hills({nm!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, 0), distance={max(320.0, ctx.R * 9):.0f}, height=12)",
            "other islands on the horizon")
    ctx.add(f"tag_semantic({nm!r}, 'hill', role='the distant hills', source='inferred')")


def r_mossy_rocks(ctx, spec):
    rect = ctx.local_rect(-ctx.R * 0.8, ctx.R * 0.8, -ctx.R * 0.5, ctx.R * 0.8)
    _scatter(ctx, "mossy rocks", rect, int(ctx.R * 0.6), 6, list(ctx.keep), label="Mossy Rocks")


def r_boulders(ctx, spec):
    rect = ctx.local_rect(-ctx.R, ctx.R, -ctx.R * 0.6, ctx.R)
    _scatter(ctx, "rocks", rect, int(ctx.R * 0.5), 5, list(ctx.keep), label="Boulders")


def r_falls_forest(ctx, spec):
    """The forest a waterfall stands in: over the cliff, down its sides in front, undergrowth at its foot."""
    falls = ctx.main
    W = falls["outer"][2] - falls["outer"][0]
    fx, fy = (falls["outer"][0] + falls["outer"][2]) / 2, (falls["outer"][1] + falls["outer"][3]) / 2
    pool_w = min(W * 0.35, 12.0)
    _scatter(ctx, "mixed", (fx - W / 2 - 6, falls["outer"][3] - 6, fx + W / 2 + 6, falls["outer"][3] + 4),
             int(W * 0.9), 6, [], label="Trees Above")
    for sgn, side in ((-1, "Left"), (1, "Right")):
        x_in, x_out = fx + sgn * (pool_w + 2), fx + sgn * (W / 2 + 14)
        rect = (min(x_in, x_out), falls["outer"][1] - 10, max(x_in, x_out), falls["outer"][1] + 1)
        _scatter(ctx, "mixed", rect, int(abs(x_out - x_in) * 0.9), 5, [], label=f"Trees {side}")
        _scatter(ctx, "shrubs", (rect[0], rect[1] - 5, rect[2], rect[1] + 2), int(abs(x_out - x_in) * 2), 6, [],
                 label=f"Undergrowth {side}")
    ctx.said.append("the forest round the falls")


def r_falls_stream(ctx, spec):
    falls = ctx.main
    fx = (falls["outer"][0] + falls["outer"][2]) / 2
    y0 = falls["outer"][1]
    nm = ctx.name("Stream")
    ctx.add(f"river({nm!r}, start=({_r(fx)}, {_r(y0 - 2)}), end=({_r(fx - 4)}, {_r(y0 - ctx.R * 1.6)}), width=5.0)",
            "its stream running out toward you")
    ctx.add(f"tag_semantic({nm!r}, 'river', role='surroundings', source='inferred')")
    ctx.keep.append((fx - 6, y0 - ctx.R * 1.6, fx + 6, y0))


def r_park_path(ctx, spec):
    a = ctx.at(-ctx.R * 0.9, ctx.hv + 6)
    b = ctx.at(ctx.R * 0.9, ctx.hv + 3)
    nm = ctx.name("Park Path")
    ctx.add(f"walkway({nm!r}, ({_r(a[0])}, {_r(a[1])}), ({_r(b[0])}, {_r(b[1])}), width=2.0, style='gravel')",
            "a path through it")
    ctx.add(f"tag_semantic({nm!r}, 'path', role='surroundings', source='inferred')")


def r_benches(ctx, spec):
    for sgn in (-1, 1):
        x, y = ctx.at(sgn * (ctx.hu + 6), ctx.hv + 8.5)
        nm = ctx.name("Bench")
        ctx.add(f"bench({nm!r}, at=({_r(x)}, {_r(y)}, 0), rotation={ctx.rotation()})")
        ctx.add(f"tag_semantic({nm!r}, 'bench', role='surroundings', source='inferred')")


def r_fence_line(ctx, spec):
    v = -ctx.hv - 8.0
    x, y = ctx.at(0.0, v)
    nm = ctx.name("Field Fence")
    ctx.add(f"fence({nm!r}, at=({_r(x)}, {_r(y)}, 0), length={ctx.R * 1.6:.0f}, style='rail', "
            f"rotation={ctx.rotation()})", "a fence along the field")
    ctx.add(f"tag_semantic({nm!r}, 'fence', role='surroundings', source='inferred')")


def r_roadside_lamps(ctx, spec):
    for k in range(-2, 3):
        x, y = ctx.at(k * 22.0, ctx.hv + 1.5)
        nm = ctx.name("Road Lamp")
        ctx.add(f"street_lamp({nm!r}, at=({_r(x)}, {_r(y)}, 0), rotation={ctx.rotation()})")
        ctx.add(f"tag_semantic({nm!r}, 'street lamp', role='surroundings', source='inferred')")


def r_room_around(ctx, spec):
    """Furniture asked for alone stands in a room: walls, floor, a window, daylight."""
    x0, y0, x1, y1 = ctx.rect
    W = max(5.0, (x1 - x0) + 3.0)
    D = max(5.0, (y1 - y0) + 3.5)
    nm = ctx.name("Room")
    ctx.add(f"room({nm!r}, at=({_r(ctx.c[0])}, {_r(y0 - 2.5 + D / 2)}, 0), width={W:.1f}, depth={D:.1f}, height=2.8, "
            f"windows=[{{'wall': 'back', 'size': 'large'}}, {{'wall': 'left', 'size': 'large'}}])", "a room round it")
    ctx.add(f"tag_semantic({nm!r}, 'room', role='the room', source='inferred')")


RECIPES = {k[2:]: v for k, v in globals().items() if k.startswith("r_") and callable(v)}
# the builder a recipe makes: skipped when the scene has one already
PROVIDES = {"shore": {"shore", "island"}, "street": {"road"}, "falls_stream": {"river"}, "room_around": {"room"},
            "far_islands": set(), "headland": set()}


# ---------- the plan ----------

def subjects_of(state, before):
    """What this request made: its new things (not ground, sky or a camera)."""
    ts = spatial.things(state, before)
    return [t for t in ts if t["new"] and t["category"] not in ("ground", "sky", "path")]


def _default_cube(t) -> bool:
    """Blender's untouched startup cube: not a world the user made."""
    return t["name"] == "Cube" and not t.get("asset_type") and len(t["names"]) == 1 and \
        all(abs(abs(v) - 1.0) < 0.05 for v in list(t["lo"]) + list(t["hi"]))


def time_look(goal: str) -> str:
    m = re.search(r"\b(sunrise|dawn|morning|midday|noon|afternoon|golden hour|sunset|dusk|evening|twilight|night(?:time)?|"
                  r"midnight|overcast)\b", goal or "", re.I)
    if not m:
        return "day"
    word = m.group(1).lower()
    return {"nighttime": "night", "midnight": "night", "evening": "dusk", "twilight": "dusk", "dawn": "sunrise",
            "noon": "day", "midday": "day"}.get(word, word)


def weather_of(goal: str):
    m = re.search(r"\b(rain(?:y|ing)?|storm(?:y)?|snow(?:y|ing)?|fog(?:gy)?|mist(?:y)?|overcast|cloudy)\b",
                  goal or "", re.I)
    return m.group(1).lower() if m else None


def plan(goal: str, state: dict, before) -> dict:
    """The environment for what the request made, as steps of kit code — None when it shouldn't have one (it was
    opted out of, nothing new was made, or the scene already had its world)."""
    if opted_out(goal):
        return None
    subjects = subjects_of(state, before)
    place_itself = False
    if not subjects:   # "make a beach", "an island": what was made IS the place — it's the subject
        subjects = [t for t in spatial.things(state, before) if t["new"] and t["category"] not in ("sky",)]
        place_itself = True
        if not subjects:
            return None
    frame_box, made_names = None, []
    made_types = {str(t.get("asset_type") or "") for t in subjects}
    if place_itself:
        made_names = [t["name"] for t in subjects]
        frame_box = _land_box(subjects)
        subjects = [_focus_thing(frame_box)]
    all_things = spatial.things(state, before)
    old = [t for t in all_things if not t["new"] and t["category"] not in ("sky",)]
    if [t for t in old if not _default_cube(t)] and not SCENE_WORDS.search(goal or ""):
        return None   # adding to a scene that has its world: the new thing stands in it
    setting = classify(goal, subjects)
    spec = SETTINGS[setting]
    taken = {o["name"].lower() for o in state.get("objects", [])}
    ctx = Ctx(goal, subjects, taken, setting)
    wet = [p for t in all_things if t["new"] for p in t["parts"] if set(spatial.words_of(p["name"])) & _WET]
    if wet and setting in ("coastal", "island"):   # where its water begins: nothing is planted past it
        ctx.water_y = min(p["min"][1] for p in wet)
        ctx.keep.append((ctx.c[0] - 2000.0, ctx.water_y - 2.0, ctx.c[0] + 2000.0, ctx.water_y + 2000.0))
    for t in old:   # what was there already (Blender's default cube too) is left as it is, nothing planted on it
        r = t["outer"]
        ctx.keep.append((r[0] - 1.0, r[1] - 1.0, r[2] + 1.0, r[3] + 1.0))
    has_ground = any(t["category"] == "ground" for t in all_things)
    steps = []

    def step(title, fn):
        ctx.lines = []
        fn()
        if ctx.lines:
            steps.append({"title": title, "code": "\n".join(ctx.lines) + "\nRESULT = 'ok'", "checks": []})

    if spec["ground"] and not has_ground:
        step("Lay the ground", lambda: (r_ground(ctx, spec), r_patches(ctx, spec)))
    elif place_itself and setting == "coastal" and "shore" in made_types:
        # a beach made on its own ends where its sand ends: land runs on behind it (under the camera)
        step("Lay the land behind it", lambda: ctx.add(
            f"ground({ctx.name('Hinterland')!r}, at=({_r(ctx.c[0])}, {_r(ctx.c[1])}, -0.04), "
            f"size={max(400.0, ctx.R * 8):.0f}, kind='sand', hilly=0.15)"))
    # what's there already isn't made twice (a shore made as the subject, a road asked for, a river)
    present = {str(t.get("asset_type") or "") for t in all_things}
    details = [RECIPES[d] for d in spec["details"] if d in RECIPES and not (PROVIDES.get(d, set()) & present)]
    # what stands with it first (a street, a shore, a drive), so the planting keeps off it
    first = [d for d in details if d.__name__ in ("r_street", "r_shore", "r_driveway", "r_room_around",
                                                     "r_falls_stream", "r_park_path")]
    rest = [d for d in details if d not in first]
    if first:
        step("Set it in its place", lambda: [d(ctx, spec) for d in first])
    if spec["layers"]:
        step("Plant around it", lambda: r_layers(ctx, spec))
    if rest:
        step("Fill in the surroundings", lambda: [d(ctx, spec) for d in rest])
    look = time_look(goal)
    weather = weather_of(goal)
    if setting != "interior":
        lines = [f"time_of_day({look!r})"]
        if weather in ("rain", "rainy", "raining", "storm", "stormy", "snow", "snowy", "snowing", "overcast", "cloudy"):
            kind = {"rainy": "rain", "raining": "rain", "stormy": "storm", "snowy": "snow", "snowing": "snow"}.get(
                weather, weather)
            lines.append(f"weather({kind!r})")
        elif spec["clouds"] and look not in ("night",):
            lines.append(f"sky_clouds(cover={spec['clouds']})")
        if weather in ("fog", "foggy"):
            lines.append("fog('fog')")
        elif weather in ("mist", "misty") or spec.get("mist"):
            lines.append("fog('mist', density=0.006, height=5)")
        elif spec["haze"]:
            lines.append(f"fog('haze', density={spec['haze']})")
        steps.append({"title": f"Sky, light and air ({look})", "code": "\n".join(lines) + "\nRESULT = env_state()",
                      "checks": [{"type": "env", "path": "set.time", "op": "==", "value": look}]})
        ctx.said.append(f"a {look} sky" + (" with clouds" if spec["clouds"] and look != "night" else ""))
    else:
        steps.append({"title": "Light the room", "code": f"time_of_day({look!r})\nRESULT = env_state()",
                      "checks": []})
    if spec["wind"]:
        steps.append({"title": "A breeze through the planting",
                      "code": f"wind({spec['wind']})\nRESULT = 'ok'", "checks": []})
    return {"setting": setting, "steps": steps, "said": ctx.said, "names": ctx.names,
            "subjects": [] if place_itself else [t["name"] for t in subjects], "frame_box": frame_box,
            "place": made_names if place_itself else [],
            "front": ctx.f, "R": ctx.R}


_WET = {"water", "sea", "ocean", "surf", "foam", "waves", "lake", "pond"}


def _land_box(made: list) -> tuple:
    """(lo, hi) of the place's land — its parts that aren't water (an island's sea goes to the horizon) — at a
    size a camera can frame: a huge place (a 160 m beach) is looked at round a 24 m stretch of it, where its land
    meets its water when it has any."""
    parts = [p for t in made for p in t["parts"] if not set(spatial.words_of(p["name"])) & _WET]
    wet = [p for t in made for p in t["parts"] if set(spatial.words_of(p["name"])) & _WET]
    parts = parts or [p for t in made for p in t["parts"]]
    lo = [min(p["min"][i] for p in parts) for i in range(3)]
    hi = [max(p["max"][i] for p in parts) for i in range(3)]
    if max(hi[0] - lo[0], hi[1] - lo[1]) > 90:
        cx = (lo[0] + hi[0]) / 2
        cy = (lo[1] + hi[1]) / 2
        if wet:   # the stretch of land just before the water: where a beach is looked at
            water_y = min(p["min"][1] for p in wet)
            if lo[1] + 0.25 * (hi[1] - lo[1]) < water_y < hi[1] + 5:   # (water on one side: a sea all round
                cy = water_y - 14.0                                    #  an island isn't "beyond" it)
        lo, hi = [cx - 12.0, cy - 12.0, lo[2]], [cx + 12.0, cy + 12.0, max(lo[2] + 2.0, min(hi[2], lo[2] + 6.0))]
    return [round(v, 2) for v in lo], [round(v, 2) for v in hi]


def _focus_thing(box) -> dict:
    lo, hi = box
    return {"name": "__place", "outer": (lo[0], lo[1], hi[0], hi[1]), "lo": list(lo), "hi": list(hi),
            "category": "object", "front": (0.0, -1.0), "side_parts": [], "asset_type": None, "names": [],
            "parts": []}


# ---------- looking at it ----------

def assess(m: dict, setting: str) -> list:
    """What a render from the camera shows wrong, each with how to fix it: m = {"sky": share of the frame that is
    sky (outdoors), "frame": the subject's (x0, y0, x1, y1, visible) in the picture, "brightness", "dark_share",
    "bright_share", "lower_detail" (texture in the lower third)}. [(problem, fix)] — fixes are camera_edit/exposure
    keywords for the agent."""
    out = []
    fr = m.get("frame")
    if fr:
        x0, y0, x1, y1 = fr[:4]
        vis = fr[4] if len(fr) > 4 else 1.0
        w, h = x1 - x0, y1 - y0
        if vis < 0.85 or x0 < 0.01 or x1 > 0.99 or y0 < 0.01:
            out.append(("the subject is cut off at the frame's edge", {"farther": 1.3}))
        elif max(w, h) < 0.28:
            out.append(("the subject is lost in the frame", {"closer": 0.75}))
        elif w > 0.85:
            out.append(("the subject fills the whole frame — no world round it", {"farther": 1.25}))
        cy = (y0 + y1) / 2
        if cy > 0.68:
            out.append(("the subject sits at the very bottom", {"tilt": -4}))
    else:
        out.append(("the subject isn't in view", {"reframe": True}))
    if setting != "interior" and m.get("sky") is not None:
        if m["sky"] < 0.08:
            out.append(("no sky in view", {"tilt": 5}))
        elif m["sky"] > 0.62:
            out.append(("mostly sky", {"tilt": -5}))
    b = m.get("brightness")
    if b is not None:
        if b < 0.18:
            out.append(("too dark to read", {"exposure": 0.6}))
        elif b > 0.8:
            out.append(("washed out", {"exposure": -0.5}))
    return out
