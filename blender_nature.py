"""The small, many things a place is covered in, for Jervis's Blender kit: tufts of grass, wild flowers, reeds and
ferns (real blades, each tuft its own; forest() repeats them as cheap instances, clumped as plants grow), and patches
of other ground (wild grass, bare earth, rock) with ragged natural edges laid over the ground — so a lawn isn't one
flat colour from the door to the horizon.

Runs inside Blender after blender_kit.py, blender_assets.py and blender_places.py (their names are shared: Parts,
_here, _finish_asset, material, ground_height...)."""
import math

try:
    import bpy
    import bmesh
    import mathutils
    from mathutils import Vector
except ImportError:   # imported outside Blender (tests)
    bpy = bmesh = mathutils = Vector = None

NATURE_VERSION = 1

# blade count, height range (m), blade width (m), how far they lean (0..1), colours (a palette each tuft picks from)
_TUFTS = {
    "grass": dict(blades=16, height=(0.22, 0.48), width=0.022, lean=0.35, spread=0.14,
                  colors=["#5f8a32", "#6f9a3c", "#7c9a45", "#58792e", "#8a9a50"]),
    "flowers": dict(blades=11, height=(0.2, 0.42), width=0.02, lean=0.3, spread=0.12,
                    colors=["#5f8a32", "#6b9038"], heads=["#f4f1e6", "#f2cf3a", "#b07ad6", "#e8789a", "#f4f1e6"]),
    "reeds": dict(blades=12, height=(0.9, 1.7), width=0.018, lean=0.12, spread=0.18,
                  colors=["#7c8a46", "#8f9150", "#6e7d3c"]),
    "ferns": dict(blades=9, height=(0.45, 0.8), width=0.075, lean=0.85, spread=0.05,
                  colors=["#3f6b2a", "#4b7a2e", "#365e24"]),
}


def _blade(p, base, height, width, lean_dir, lean, r, segments=4):
    """One blade (or frond): a strip tapering to a point, bending over as it rises."""
    pts = []
    for k in range(segments + 1):
        t = k / segments
        bend = lean * t * t
        x = base[0] + lean_dir[0] * height * bend
        y = base[1] + lean_dir[1] * height * bend
        z = base[2] + height * (t - 0.45 * bend * t)
        w = width * (1.0 - t) ** 0.8
        pts.append((x, y, z, w))
    side = (-lean_dir[1], lean_dir[0])
    rows = []
    for x, y, z, w in pts:
        rows.append((p.bm.verts.new((x - side[0] * w / 2, y - side[1] * w / 2, z)),
                     p.bm.verts.new((x + side[0] * w / 2, y + side[1] * w / 2, z))))
    for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
        if (b0.co - b1.co).length < 1e-5:
            p.bm.faces.new((a0, a1, b0))
        else:
            p.bm.faces.new((a0, a1, b1, b0))
    return Vector(pts[-1][:3])


def tuft(name="Grass Tuft", at=None, kind="grass", size=1.0, seed=0, rotation=0, **kw):
    """A tuft of `kind`: 'grass' | 'flowers' (grass with wild flowers in it) | 'reeds' (tall, for water's edge) |
    'ferns' (arching fronds, for forest floors). size scales it."""
    kind = str(kind or "grass").lower()
    spec = _TUFTS.get(kind, _TUFTS["grass"])
    size = max(0.2, min(4.0, float(size or 1.0)))
    params = dict(kind=kind, size=size, seed=seed, rotation=rotation)
    at = _here(at)   # noqa: F821
    r = rng(seed * 31 + 7)   # noqa: F821
    blades, heads = Parts(), Parts()   # noqa: F821
    tips = []
    for i in range(spec["blades"]):
        a = r.uniform(0, math.tau)
        d = spec["spread"] * size * math.sqrt(r.uniform(0, 1))
        base = (math.cos(a) * d, math.sin(a) * d, -0.02)
        out = r.uniform(0, math.tau) if kind != "ferns" else a + r.uniform(-0.3, 0.3)
        h = r.uniform(*spec["height"]) * size
        tip = _blade(blades, base, h, spec["width"] * size, (math.cos(out), math.sin(out)),
                     spec["lean"] * r.uniform(0.6, 1.2), r)
        tips.append(tip)
    made = [blades.done(f"{name} Blades", at, r.choice(spec["colors"]), smooth=True)]
    if spec.get("heads"):
        colour = r.choice(spec["heads"])
        for tip in tips[: max(2, len(tips) // 3)]:
            heads.lump(tuple(tip + Vector((0, 0, 0.02 * size))), 0.028 * size, irregularity=0.2, detail=1,
                       seed=int(r.uniform(0, 999)))
        made.append(heads.done(f"{name} Flowers", at, colour, smooth=True))
    return _finish_asset(name, "tuft", params, made, at, rotation,   # noqa: F821
                         {"grass": "a tuft of grass", "flowers": "a tuft of grass with wild flowers",
                          "reeds": "a clump of reeds", "ferns": "a fern"}.get(kind, "a tuft"))


def _in_rects(x, y, rects, pad=0.0):
    return any(a[0] - pad <= x <= a[2] + pad and a[1] - pad <= y <= a[3] + pad for a in rects)


def patches(name="Patches", at=None, area=60.0, count=5, size=5.0, kind="wild grass", seed=0, avoid=None, **kw):
    """Patches of `kind` ground ('wild grass', 'dirt', 'rock', 'lawn', 'sand' or any material) over the ground in an
    area x area square round `at`: `count` of them, about `size` m across each, ragged-edged, following the ground's
    rise and fall — kept off the `avoid` rects [(x0, y0, x1, y1)]."""
    area = max(4.0, float(area or 60.0))
    count = max(1, min(60, int(count or 5)))
    size = max(0.5, min(40.0, float(size or 5.0)))
    avoid = [tuple(map(float, a)) for a in (avoid or [])]
    params = dict(area=area, count=count, size=size, kind=kind, seed=seed, avoid=[list(a) for a in avoid])
    at = _here(at)   # noqa: F821
    r = rng(seed * 17 + 5)   # noqa: F821
    p = Parts()   # noqa: F821
    off = Vector((r.uniform(0, 90), r.uniform(0, 90), 0))
    placed = 0
    for _ in range(count * 12):
        if placed >= count:
            break
        cx = at[0] + r.uniform(-area / 2, area / 2)
        cy = at[1] + r.uniform(-area / 2, area / 2)
        rad = size / 2 * r.uniform(0.6, 1.4)
        if _in_rects(cx, cy, avoid, pad=rad * 0.8):
            continue
        n = 28
        rings = []
        for scale in (0.0, 0.55, 1.0):
            ring = []
            for k in range(n if scale else 1):
                a = k / n * math.tau
                wob = 1.0 + 0.38 * mathutils.noise.noise(Vector((math.cos(a) * 1.7, math.sin(a) * 1.7, placed * 3.1)) + off)
                rr = rad * scale * wob
                x, y = cx + math.cos(a) * rr, cy + math.sin(a) * rr
                z = ground_height(x, y, default=at[2]) + 0.025 - at[2]   # noqa: F821
                ring.append(p.bm.verts.new((x - at[0], y - at[1], z)))
            rings.append(ring)
        c = rings[0][0]
        for k in range(n):
            p.bm.faces.new((c, rings[1][k], rings[1][(k + 1) % n]))
            p.bm.faces.new((rings[1][k], rings[2][k], rings[2][(k + 1) % n], rings[1][(k + 1) % n]))
        placed += 1
    obj = p.done(f"{name} Surface", at, None, smooth="all")
    if obj is None:
        raise ValueError(f"No room for {kind} patches there: everything's to be kept clear.")
    mat = material(kind, hint="ground")   # noqa: F821
    try:
        _natural_variation(mat, kind)   # noqa: F821
    except NameError:
        pass
    obj.data.materials.append(mat)
    try:
        obj.visible_shadow = False
    except AttributeError:
        pass
    root = _finish_asset(name, "patches", params, [obj], at, 0,   # noqa: F821
                         f"{placed} patches of {kind} over the ground")
    root["jervis_role"] = "ground"
    return root


NATURE_BUILDERS = ("tuft", "patches")
if bpy is not None:
    try:   # kit names too (see blender_kit._KIT)
        _KIT.update({k: globals()[k] for k in NATURE_BUILDERS + ("_blade", "_in_rects", "_TUFTS")})   # noqa: F821
    except NameError:
        pass
