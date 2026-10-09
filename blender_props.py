"""Finished props for Jervis's Blender kit: furniture and the small things that make a place believable — a sofa
with cushions, armchairs, tables, chairs, a TV, shelves with books, a rug, lamps that really light, potted plants,
a parasol, street lamps, paper lanterns, a crate of produce. Each is built from real parts (frames, legs,
cushions, shades) with fitting materials, sized like the real thing, front toward -y.

Runs inside Blender after blender_kit / blender_assets / blender_motion (shared names)."""
import math

try:
    import bpy
    import mathutils
    from mathutils import Vector
except ImportError:
    bpy = mathutils = Vector = None

PROPS_VERSION = 1


def _fabric(color, fallback="#7d8288"):
    return color or fallback


def sofa(name="Sofa", at=None, length=2.2, color=None, seats=3, legs="wood", rotation=0, **kw):
    """A sofa: a fabric base, `seats` seat cushions, back cushions, rounded arms and short legs. Faces -y."""
    L = max(1.2, min(4.0, float(length or 2.2)))
    seats = max(1, min(5, int(seats or 3)))
    fab = _fabric(color, "#b9b4aa")
    params = dict(length=L, color=color, seats=seats, legs=legs, rotation=rotation)
    at = _here(at)   # noqa: F821
    D, arm = 0.92, 0.2
    base, cush, back, legs_p = Parts(), Parts(), Parts(), Parts()   # noqa: F821
    base.box((0, 0.05, 0.28), (L, D, 0.3))
    for side in (-1, 1):
        base.box((side * (L / 2 - arm / 2), 0.05, 0.43), (arm, D, 0.6))
    base.box((0, D / 2 - 0.1, 0.55), (L - 2 * arm + 0.02, 0.2, 0.6))
    inner = L - 2 * arm
    for k in range(seats):
        cx = -inner / 2 + (k + 0.5) * inner / seats
        cush.box((cx, -0.04, 0.5), (inner / seats - 0.02, D - 0.28, 0.16))
        back.box((cx, D / 2 - 0.27, 0.72), (inner / seats - 0.03, 0.2, 0.42), tilt=("x", -8))
    for sx in (-1, 1):
        for sy in (-1, 1):
            legs_p.box((sx * (L / 2 - 0.08), sy * (D / 2 - 0.08) + 0.05, 0.065), (0.05, 0.05, 0.13))
    made = [base.done(f"{name} Frame", at, fab, bevel=0.05), cush.done(f"{name} Cushions", at, fab, bevel=0.06),
            back.done(f"{name} Back Cushions", at, fab, bevel=0.07),
            legs_p.done(f"{name} Legs", at, "dark wood" if legs == "wood" else "steel", bevel=0.005)]
    return _finish_asset(name, "sofa", params, made, at, rotation, f"a {seats}-seat fabric sofa {L:.1f} m long")   # noqa: F821


def armchair(name="Armchair", at=None, color=None, rotation=0, **kw):
    """An upholstered armchair with a seat cushion, a back and arms on short legs. Faces -y."""
    fab = _fabric(color, "#8c7b6a")
    at = _here(at)   # noqa: F821
    base, cush, legs_p = Parts(), Parts(), Parts()   # noqa: F821
    base.box((0, 0.02, 0.27), (0.85, 0.85, 0.28))
    for side in (-1, 1):
        base.box((side * 0.34, 0.02, 0.42), (0.17, 0.85, 0.58))
    base.box((0, 0.35, 0.6), (0.6, 0.17, 0.66), tilt=("x", -6))
    cush.box((0, -0.06, 0.47), (0.52, 0.62, 0.14))
    for sx in (-1, 1):
        for sy in (-1, 1):
            legs_p.box((sx * 0.35, sy * 0.35 + 0.02, 0.07), (0.045, 0.045, 0.14))
    made = [base.done(f"{name} Frame", at, fab, bevel=0.05), cush.done(f"{name} Cushion", at, fab, bevel=0.05),
            legs_p.done(f"{name} Legs", at, "dark wood", bevel=0.005)]
    return _finish_asset(name, "armchair", dict(color=color, rotation=rotation), made, at, rotation,   # noqa: F821
                         "an upholstered armchair")


def coffee_table(name="Coffee Table", at=None, length=1.2, top="wood", rotation=0, **kw):
    """A low table: a top (wood, glass, stone or a colour) on four legs, with a shelf below."""
    L = max(0.5, min(2.5, float(length or 1.2)))
    at = _here(at)   # noqa: F821
    t, l_ = Parts(), Parts()   # noqa: F821
    t.box((0, 0, 0.41), (L, L * 0.5, 0.04))
    l_.box((0, 0, 0.12), (L - 0.12, L * 0.5 - 0.12, 0.02))
    for sx in (-1, 1):
        for sy in (-1, 1):
            l_.box((sx * (L / 2 - 0.05), sy * (L * 0.25 - 0.05), 0.2), (0.04, 0.04, 0.4))
    top_mat = {"glass": "clear glass", "stone": "ceramic", "marble": "ceramic"}.get(str(top).lower(), top)
    made = [t.done(f"{name} Top", at, top_mat, bevel=0.008), l_.done(f"{name} Legs", at, "dark metal", bevel=0.004)]
    return _finish_asset(name, "coffee_table", dict(length=L, top=top, rotation=rotation), made, at, rotation,   # noqa: F821
                         f"a {top} coffee table")


def table(name="Table", at=None, length=1.6, width=0.9, height=0.75, top="wood", rotation=0, **kw):
    """A table (dining, desk, counter): a top on four legs."""
    L, Wd = max(0.5, min(5.0, float(length or 1.6))), max(0.4, min(2.5, float(width or 0.9)))
    Hh = max(0.4, min(1.2, float(height or 0.75)))
    at = _here(at)   # noqa: F821
    t, l_ = Parts(), Parts()   # noqa: F821
    t.box((0, 0, Hh - 0.02), (L, Wd, 0.04))
    for sx in (-1, 1):
        for sy in (-1, 1):
            l_.box((sx * (L / 2 - 0.06), sy * (Wd / 2 - 0.06), (Hh - 0.04) / 2), (0.05, 0.05, Hh - 0.04))
    made = [t.done(f"{name} Top", at, top, bevel=0.008), l_.done(f"{name} Legs", at, "dark wood", bevel=0.004)]
    return _finish_asset(name, "table", dict(length=L, width=Wd, height=Hh, top=top, rotation=rotation), made, at,   # noqa: F821
                         rotation, f"a {L:.1f} m {top} table")


def chair(name="Chair", at=None, color="wood", rotation=0, **kw):
    """A chair: a seat, a back with slats and four legs. Faces -y."""
    at = _here(at)   # noqa: F821
    p = Parts()   # noqa: F821
    p.box((0, 0, 0.45), (0.44, 0.44, 0.04))
    for sx in (-1, 1):
        for sy in (-1, 1):
            p.box((sx * 0.19, sy * 0.19, 0.22), (0.035, 0.035, 0.44))
        p.box((sx * 0.19, 0.19, 0.68), (0.035, 0.035, 0.46))
    p.box((0, 0.19, 0.86), (0.42, 0.03, 0.1))
    for k in range(3):
        p.box((-0.1 + k * 0.1, 0.19, 0.67), (0.03, 0.02, 0.3))
    made = [p.done(f"{name} Frame", at, color, bevel=0.004)]
    return _finish_asset(name, "chair", dict(color=color, rotation=rotation), made, at, rotation, "a chair")   # noqa: F821


def tv(name="TV", at=None, size=1.3, stand=True, on=False, rotation=0, **kw):
    """A flat TV (a black screen in a thin bezel) on a low media unit. Faces -y."""
    S = max(0.6, min(3.0, float(size or 1.3)))
    at = _here(at)   # noqa: F821
    unit, frame, screen = Parts(), Parts(), Parts()   # noqa: F821
    z0 = 0.0
    if stand:
        unit.box((0, 0, 0.25), (S * 1.3, 0.42, 0.5))
        z0 = 0.5
    frame.box((0, 0.05, z0 + 0.12 + S * 0.28), (S, 0.04, S * 0.56))
    frame.box((0, 0.05, z0 + 0.05), (0.3, 0.2, 0.1))
    screen.box((0, 0.028, z0 + 0.12 + S * 0.28), (S - 0.03, 0.005, S * 0.56 - 0.03))
    made = [unit.done(f"{name} Stand", at, "dark wood", bevel=0.006) if stand else None,
            frame.done(f"{name} Frame", at, "#111113", bevel=0.005),
            screen.done(f"{name} Screen", at, material("#0b1622", name="Jervis TV screen", emission=1.2 if on else 0.0))]   # noqa: F821
    return _finish_asset(name, "tv", dict(size=S, stand=stand, on=on, rotation=rotation), [m for m in made if m],   # noqa: F821
                         at, rotation, "a flat TV on a media unit")


def shelf(name="Shelf", at=None, width=1.2, height=1.8, books=True, color="wood", rotation=0, **kw):
    """A bookcase / cabinet: sides, shelves and a back, filled with books of many colours (books=True). Faces -y."""
    Wd, Hh = max(0.4, min(4.0, float(width or 1.2))), max(0.4, min(3.0, float(height or 1.8)))
    at = _here(at)   # noqa: F821
    r = rng(int(Wd * 100 + Hh * 10))   # noqa: F821
    case, book = Parts(), Parts()   # noqa: F821
    for sx in (-1, 1):
        case.box((sx * (Wd / 2 - 0.01), 0, Hh / 2), (0.02, 0.35, Hh))
    case.box((0, 0.165, Hh / 2), (Wd, 0.02, Hh))
    n = max(1, int(Hh / 0.38))
    for k in range(n + 1):
        case.box((0, 0, k * Hh / n + 0.01), (Wd, 0.35, 0.02))
    if books:
        for k in range(n):
            x = -Wd / 2 + 0.04
            while x < Wd / 2 - 0.08:
                w = r.uniform(0.025, 0.05)
                h = r.uniform(0.2, 0.3)
                if r.random() < 0.85:
                    book.box((x + w / 2, 0.02, k * Hh / n + 0.02 + h / 2), (w, 0.24, h))
                x += w + 0.003
    made = [case.done(f"{name} Case", at, color, bevel=0.003)]
    if books:
        b = book.done(f"{name} Books", at, None)
        for c in ("#7a1f1a", "#1f3a5a", "#2d5a2d", "#c9b27c", "#3b2b1a"):
            b.data.materials.append(material(c))   # noqa: F821
        for i, poly in enumerate(b.data.polygons):
            poly.material_index = (i // 6) % 5
        made.append(b)
    return _finish_asset(name, "shelf", dict(width=Wd, height=Hh, books=books, color=color, rotation=rotation),   # noqa: F821
                         made, at, rotation, "a bookcase full of books" if books else "a cabinet")


def rug(name="Rug", at=None, length=2.4, width=1.7, color="carpet", **kw):
    """A rug: a thin, soft-edged rectangle on the floor."""
    at = _here(at)   # noqa: F821
    p = Parts()   # noqa: F821
    p.box((0, 0, 0.008), (max(0.5, float(length or 2.4)), max(0.4, float(width or 1.7)), 0.016))
    return _finish_asset(name, "rug", dict(length=length, width=width, color=color), [p.done(f"{name} Pile", at, color,   # noqa: F821
                                                                                          bevel=0.006)],
                         at, 0, "a rug")


def floor_lamp(name="Floor Lamp", at=None, height=1.6, on=False, kelvin=2700, **kw):
    """A floor lamp: a weighted base, a slim pole and a fabric shade that glows, with a real warm light inside
    (off unless on=True; lights_on() brings it up)."""
    Hh = max(0.6, min(2.5, float(height or 1.6)))
    at = _here(at)   # noqa: F821
    base, shade = Parts(), Parts()   # noqa: F821
    base.cylinder((0, 0, 0), 0.16, 0.03, segments=24)
    base.cylinder((0, 0, 0.03), 0.015, Hh - 0.3, segments=10)
    shade.cylinder((0, 0, Hh - 0.32), 0.22, 0.32, segments=24, radius_top=0.16)
    made = [base.done(f"{name} Stand", at, "dark metal", smooth=True),
            shade.done(f"{name} Shade", at, material("#efe3c8", name=f"Jervis lamp shade {name}", emission=0.0),   # noqa: F821
                       smooth=True)]
    root = _finish_asset(name, "floor_lamp", dict(height=Hh, on=on, kelvin=kelvin), made, at, 0, "a floor lamp")   # noqa: F821
    lt = light(f"{name} Bulb", "point", at=(at[0], at[1], at[2] + Hh - 0.18), energy=35, color=kelvin, size=0.1,   # noqa: F821
               on=on)
    _adopt(lt, root)   # noqa: F821
    lt["jervis_light_for"] = name
    lt["jervis_glow_material"] = f"Jervis lamp shade {name}"
    return root


def potted_plant(name="Plant", at=None, height=1.1, pot="ceramic", seed=0, **kw):
    """A potted plant: a tapered pot, soil, and a leafy crown of clustered leaves."""
    Hh = max(0.3, min(3.0, float(height or 1.1)))
    at = _here(at)   # noqa: F821
    r = rng(seed)   # noqa: F821
    pot_p, leaves = Parts(), Parts()   # noqa: F821
    pr = 0.12 + Hh * 0.08
    pot_p.cylinder((0, 0, 0), pr * 0.75, Hh * 0.3, segments=20, radius_top=pr)
    for k in range(7):
        a = k * math.tau / 7 + r.uniform(-0.3, 0.3)
        d = r.uniform(0.05, pr * 1.2)
        leaves.lump((math.cos(a) * d, math.sin(a) * d, Hh * r.uniform(0.55, 0.95)), Hh * 0.22, irregularity=0.4,
                    squash=(1, 1, 0.8), detail=2, seed=seed * 7 + k)
    made = [pot_p.done(f"{name} Pot", at, pot, smooth=True), leaves.done(f"{name} Leaves", at, "leaves", smooth=True)]
    return _finish_asset(name, "potted_plant", dict(height=Hh, pot=pot, seed=seed), made, at, 0, "a potted plant")   # noqa: F821


def parasol(name="Parasol", at=None, color="#f1ece2", size=2.6, open=True, **kw):
    """A garden / pool parasol: a weighted base, a pole and an eight-panel fabric canopy with ribs."""
    S = max(1.2, min(5.0, float(size or 2.6)))
    at = _here(at)   # noqa: F821
    pole, canopy = Parts(), Parts()   # noqa: F821
    pole.cylinder((0, 0, 0), 0.25, 0.08, segments=16)
    pole.cylinder((0, 0, 0.08), 0.025, 2.35, segments=10)
    if open:
        canopy.cylinder((0, 0, 1.95), S / 2, 0.45, segments=8, radius_top=0.05)
    else:
        canopy.cylinder((0, 0, 0.9), 0.12, 1.4, segments=8, radius_top=0.04)
    made = [pole.done(f"{name} Pole", at, "light wood", smooth=True),
            canopy.done(f"{name} Canopy", at, color)]
    return _finish_asset(name, "parasol", dict(color=color, size=S, open=open), made, at, 0, "a parasol")   # noqa: F821


def street_lamp(name="Street Lamp", at=None, height=4.5, style="modern", on=False, kelvin=3000, rotation=0, **kw):
    """A street lamp: a tapered pole on a base, an arm reaching out (modern) or a lantern head (classic), a lens
    that glows, and a real light pointing down — off unless on=True (night turns street lamps on)."""
    Hh = max(2.0, min(12.0, float(height or 4.5)))
    style = "classic" if str(style).lower().startswith(("clas", "old", "victor", "tradit")) else "modern"
    at = _here(at)   # noqa: F821
    pole, head = Parts(), Parts()   # noqa: F821
    pole.cylinder((0, 0, 0), 0.14, 0.4, segments=12, radius_top=0.1)
    pole.cylinder((0, 0, 0.4), 0.08, Hh - 0.4, segments=12, radius_top=0.05)
    if style == "modern":
        pole.beam((0, 0, Hh - 0.05), (0, -1.1, Hh + 0.15), 0.06)
        head.box((0, -1.2, Hh + 0.1), (0.25, 0.55, 0.06))
        lamp_at = (at[0], at[1] - 1.2, at[2] + Hh)
    else:
        head.cylinder((0, 0, Hh - 0.05), 0.18, 0.5, segments=6, radius_top=0.24)
        head.cylinder((0, 0, Hh + 0.45), 0.26, 0.15, segments=6, radius_top=0.05)
        lamp_at = (at[0], at[1], at[2] + Hh + 0.2)
    made = [pole.done(f"{name} Pole", at, "dark metal", smooth=True),
            head.done(f"{name} Head", at, material("#fff1d0", name=f"Jervis lamp glass {name}", emission=0.0))]   # noqa: F821
    root = _finish_asset(name, "street_lamp", dict(height=Hh, style=style, on=on, kelvin=kelvin, rotation=rotation),   # noqa: F821
                         made, at, rotation, f"a {style} street lamp {Hh:.1f} m tall")
    lt = light(f"{name} Bulb", "spot" if style == "modern" else "point", at=lamp_at, energy=450 if style == "modern"   # noqa: F821
               else 250, color=kelvin, angle=120, size=0.2, aim=(lamp_at[0], lamp_at[1], 0.0), on=on)
    _adopt(lt, root)   # noqa: F821
    lt["jervis_light_for"] = name
    lt["jervis_glow_material"] = f"Jervis lamp glass {name}"
    root["jervis_tags"] = "light_source_night"
    return root


def lantern(name="Lantern", at=None, color="#f4e3c0", height=2.6, on=False, **kw):
    """A hanging paper lantern: a glowing paper body with dark caps, hung at `height`, a warm light inside."""
    at = _here(at)   # noqa: F821
    Hh = max(0.5, min(6.0, float(height or 2.6)))
    body, caps = Parts(), Parts()   # noqa: F821
    body.lump((0, 0, Hh), 0.2, irregularity=0.0, squash=(1, 1, 1.4), detail=3)
    caps.cylinder((0, 0, Hh + 0.26), 0.09, 0.05, segments=12)
    caps.cylinder((0, 0, Hh - 0.31), 0.09, 0.05, segments=12)
    caps.cylinder((0, 0, Hh + 0.31), 0.006, 0.4, segments=6)
    made = [body.done(f"{name} Paper", at, material(color, name=f"Jervis lantern paper {name}", emission=0.0),   # noqa: F821
                      smooth=True), caps.done(f"{name} Caps", at, "#1a1210")]
    root = _finish_asset(name, "lantern", dict(color=color, height=Hh, on=on), made, at, 0, "a paper lantern")   # noqa: F821
    lt = light(f"{name} Bulb", "point", at=(at[0], at[1], at[2] + Hh), energy=25, color=2400, size=0.15, on=on)   # noqa: F821
    _adopt(lt, root)   # noqa: F821
    lt["jervis_light_for"] = name
    lt["jervis_glow_material"] = f"Jervis lantern paper {name}"
    root["jervis_tags"] = "light_source_night"
    return root


def crate(name="Crate", at=None, produce=True, seed=0, **kw):
    """A wooden crate (slatted) heaped with produce of a few colours — a market stall's display."""
    at = _here(at)   # noqa: F821
    r = rng(seed)   # noqa: F821
    box_p, fruit = Parts(), Parts()   # noqa: F821
    for k in range(4):
        box_p.box((0, -0.25, 0.06 + k * 0.1), (0.6, 0.02, 0.07))
        box_p.box((0, 0.25, 0.06 + k * 0.1), (0.6, 0.02, 0.07))
        box_p.box((-0.3, 0, 0.06 + k * 0.1), (0.02, 0.5, 0.07))
        box_p.box((0.3, 0, 0.06 + k * 0.1), (0.02, 0.5, 0.07))
    box_p.box((0, 0, 0.02), (0.6, 0.5, 0.02))
    made = [box_p.done(f"{name} Box", at, "light wood", bevel=0.004)]
    if produce:
        for k in range(10):
            fruit.lump((r.uniform(-0.22, 0.22), r.uniform(-0.18, 0.18), 0.38 + r.uniform(0, 0.08)), 0.07,
                       irregularity=0.1, detail=2, seed=seed + k)
        f = fruit.done(f"{name} Produce", at, None, smooth=True)
        f.data.materials.append(material(r.choice(["#b3261e", "#e08a1e", "#5d8a2a", "#d9c23a"])))   # noqa: F821
        made.append(f)
    return _finish_asset(name, "crate", dict(produce=produce, seed=seed), made, at, 0, "a crate of produce")   # noqa: F821


PROP_BUILDERS = ("sofa", "armchair", "coffee_table", "table", "chair", "tv", "shelf", "rug", "floor_lamp",
                 "potted_plant", "parasol", "street_lamp", "lantern", "crate")
if bpy is not None:
    try:
        _KIT.update({k: globals()[k] for k in PROP_BUILDERS})   # noqa: F821
    except NameError:
        pass
