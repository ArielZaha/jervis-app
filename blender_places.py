"""Finished places for Jervis's Blender kit: the bigger things a picture or a request is made of — a modern villa,
a storefront, a room, a road, a shoreline, ground, distant hills, a forest. Real geometry with real thickness, glass,
frames, trims and materials, named by role ('<Name> Window Glass', '<Name> Sign') so lighting, editing and the scene's
semantic memory can find each part.

Runs inside Blender after blender_kit.py and blender_assets.py (their names are shared: Parts, _here,
_finish_asset, material...). Plain data (PLACE_TYPES) is readable without Blender."""
import math

try:
    import bpy
    import bmesh
    import mathutils
    from mathutils import Vector
except ImportError:   # imported outside Blender (tests, the agent reading PLACE_TYPES)
    bpy = bmesh = mathutils = Vector = None

PLACES_VERSION = 1

_PLACE_PRESETS = {
    "asphalt": dict(colors=[(0.045, 0.045, 0.048), (0.09, 0.09, 0.095)], pattern="noise", scale=30.0, bump=0.4,
                    rough=0.85),
    "wet asphalt": dict(colors=[(0.02, 0.02, 0.022), (0.05, 0.05, 0.055)], pattern="noise", scale=30.0, bump=0.2,
                        rough=0.12),
    "paving": dict(colors=[(0.4, 0.39, 0.37), (0.55, 0.54, 0.51)], mortar=(0.25, 0.25, 0.24), pattern="tiles",
                   scale=2.0, bump=0.3, rough=0.85, row_height=0.5, brick_width=0.5, mortar_size=0.02),
    "kerb": dict(colors=[(0.5, 0.5, 0.48), (0.62, 0.62, 0.6)], pattern="noise", scale=10.0, bump=0.2, rough=0.8),
    "white render": dict(colors=[(0.86, 0.85, 0.82), (0.93, 0.92, 0.9)], pattern="noise", scale=4.0, bump=0.08,
                         rough=0.75),
    "wood slats": dict(colors=[(0.36, 0.22, 0.12), (0.5, 0.33, 0.19)], mortar=(0.1, 0.06, 0.03), pattern="tiles",
                       scale=1.0, bump=0.4, rough=0.6, row_height=40.0, brick_width=0.12, mortar_size=0.06),
    "limestone": dict(colors=[(0.62, 0.58, 0.5), (0.78, 0.74, 0.66)], mortar=(0.5, 0.47, 0.42), pattern="brick",
                      scale=1.5, bump=0.35, rough=0.8),
    "dark metal": dict(colors=[(0.03, 0.03, 0.033), (0.06, 0.06, 0.065)], pattern="noise", scale=20.0, bump=0.03,
                       rough=0.35, metallic=0.9),
    "clear glass": dict(colors=[(0.75, 0.85, 0.88), (0.8, 0.9, 0.92)], pattern="none", rough=0.02, transmission=1.0),
    "paper": dict(colors=[(0.95, 0.9, 0.78), (0.98, 0.94, 0.85)], pattern="noise", scale=30.0, bump=0.1, rough=0.9),
    "oak floor": dict(colors=[(0.42, 0.28, 0.16), (0.55, 0.39, 0.24)], mortar=(0.25, 0.16, 0.09), pattern="tiles",
                      scale=1.0, bump=0.15, rough=0.45, row_height=0.18, brick_width=1.2, mortar_size=0.01),
    "floor tiles": dict(colors=[(0.7, 0.68, 0.64), (0.78, 0.76, 0.72)], mortar=(0.55, 0.53, 0.5), pattern="tiles",
                        scale=1.0, bump=0.1, rough=0.3, row_height=0.6, brick_width=0.6, mortar_size=0.008),
    "carpet": dict(colors=[(0.45, 0.42, 0.38), (0.52, 0.49, 0.45)], pattern="noise", scale=80.0, bump=0.4, rough=1.0),
    "wild grass": dict(colors=[(0.12, 0.13, 0.05), (0.32, 0.3, 0.14)], pattern="noise", scale=6.0, bump=0.8,
                       rough=0.95),
    "lawn": dict(colors=[(0.05, 0.2, 0.03), (0.13, 0.36, 0.05)], pattern="noise", scale=14.0, bump=0.3, rough=0.85),
    "forest floor": dict(colors=[(0.06, 0.05, 0.02), (0.16, 0.13, 0.06)], pattern="noise", scale=8.0, bump=0.7,
                         rough=1.0),
    "hazy hills": dict(colors=[(0.28, 0.33, 0.3), (0.36, 0.42, 0.38)], pattern="noise", scale=0.08, bump=0.2,
                       rough=1.0),
    "tatami": dict(colors=[(0.55, 0.5, 0.3), (0.65, 0.6, 0.38)], pattern="streaks", scale=12.0, bump=0.2, rough=0.9),
}


def _install_place_presets():
    for key, spec in _PLACE_PRESETS.items():
        PRESETS.setdefault(key, spec)   # noqa: F821  (the kit's, in the shared namespace)
    _PRESET_ALIASES.update({"tarmac": "asphalt", "road": "asphalt", "pavement": "paving", "sidewalk": "paving",   # noqa: F821
                            "render": "white render", "stucco white": "white render", "wood cladding": "wood slats",
                            "timber cladding": "wood slats", "parquet": "oak floor", "hardwood": "oak floor",
                            "wood floor": "oak floor", "tiled floor": "floor tiles", "rug": "carpet",
                            "meadow": "wild grass", "grassland": "wild grass"})


if bpy is not None:
    try:
        _install_place_presets()
    except NameError:
        pass


def _glass_panels(glass, frames, a, b, z0, z1, axis, out, mullion=1.6, frame=0.05):
    """A floor-to-ceiling glass wall from a to b (along x if axis == 'x' at y=out, else along y at x=out): panes
    with thin frames and mullions every `mullion` metres."""
    length = abs(b - a)
    n = max(1, int(round(length / mullion)))
    step = (b - a) / n
    h = z1 - z0
    for i in range(n + 1):
        u = a + step * i
        if axis == "x":
            frames.box((u, out, (z0 + z1) / 2), (frame, frame * 1.6, h))
        else:
            frames.box((out, u, (z0 + z1) / 2), (frame * 1.6, frame, h))
    for z in (z0 + frame / 2, z1 - frame / 2):
        if axis == "x":
            frames.box(((a + b) / 2, out, z), (length, frame * 1.6, frame))
        else:
            frames.box((out, (a + b) / 2, z), (frame * 1.6, length, frame))
    for i in range(n):   # one pane per bay (so each window can be lit, or not, on its own)
        u0 = a + step * i
        if axis == "x":
            glass.box((u0 + step / 2, out, (z0 + z1) / 2), (abs(step) - frame * 0.5, 0.02, h - frame))
        else:
            glass.box((out, u0 + step / 2, (z0 + z1) / 2), (0.02, abs(step) - frame * 0.5, h - frame))


# ---------- a modern villa ----------

def villa(name="Villa", at=None, floors=2, width=20.0, depth=11.0, wings=2, glass="most", cladding="wood slats",
          walls="white render", stone="limestone", overhang=1.8, terrace=True, rotation=0, seed=0, **kw):
    """A modern luxury villa: stacked, offset volumes under thin white slabs that cantilever out (deep overhangs
    with downlights in their soffits), floor-to-ceiling glass on the front between dark mullions, wood-slat and stone
    wall panels, glass balustrades on the upper terraces, a second lower wing (wings=2), a stone terrace in front.
    Front faces -y (rotation turns it). glass: 'most' | 'half' | 'some'."""
    floors = max(1, min(3, int(floors or 2)))
    W = max(10.0, min(40.0, float(width or 20.0)))
    D = max(7.0, min(20.0, float(depth or 11.0)))
    wings = max(1, min(2, int(wings or 1)))
    share = {"most": 0.8, "half": 0.55, "some": 0.3, "none": 0.15}.get(str(glass).lower(), 0.7)
    ov = max(0.6, min(3.5, float(overhang or 1.8)))
    params = dict(floors=floors, width=W, depth=D, wings=wings, glass=glass, cladding=cladding, walls=walls,
                  stone=stone, overhang=ov, terrace=terrace, rotation=rotation, seed=seed)
    at = _here(at)   # noqa: F821
    r = rng(seed)   # noqa: F821
    FH, SL = 3.3, 0.35            # floor height, slab thickness
    made = []
    slabs, solid, clad, stone_p, glass_p, frames, rails, rail_glass, floors_p, lights_p, interior = (
        Parts(), Parts(), Parts(), Parts(), Parts(), Parts(), Parts(), Parts(), Parts(), Parts(), Parts())   # noqa: F821

    # The main block: each floor a volume, the upper ones shifted and narrower, every slab cantilevering out.
    main_w = W * (0.62 if wings == 2 else 1.0)
    cx_main = -W / 2 + main_w / 2
    volumes = []
    for f in range(floors):
        shift = (-0.06 * main_w * f) if f else 0.0
        w_f = main_w * (1.0 - 0.08 * f)
        d_f = D * (1.0 - 0.05 * f)
        x0 = cx_main + shift
        z0 = f * FH
        volumes.append((x0, w_f, d_f, z0, z0 + FH - SL))
    if wings == 2:   # a lower second wing to the right, set back a little
        w2 = W * 0.38 - 1.0
        x2 = W / 2 - w2 / 2
        for f in range(max(1, floors - 1)):
            volumes.append((x2, w2, D * 0.85, f * FH, f * FH + FH - SL))

    for vi, (x0, w_f, d_f, z0, z1) in enumerate(volumes):
        y_front, y_back = -d_f / 2, d_f / 2
        # floor slab (with its cantilever) and the slab above (the roof of the top volume)
        floors_p.box((x0, 0, z0 + 0.06), (w_f - 0.3, d_f - 0.3, 0.12))
        top_ov = ov * (1.0 if z1 + SL >= (floors * FH - 0.5) or vi >= floors else 0.7)
        slabs.box((x0 - 0.15 * ov, -top_ov * 0.25, z1 + SL / 2), (w_f + 2 * top_ov * 0.6, d_f + top_ov * 1.25, SL))
        for k in range(max(2, int(w_f / 3.0))):   # downlights in the soffit
            lx = x0 - w_f / 2 + (k + 0.5) * w_f / max(2, int(w_f / 3.0))
            lights_p.cylinder((lx, y_front - top_ov * 0.45, z1 - 0.02), 0.07, 0.02, segments=12)
        # the front: glass between solid panels (a stone or wood panel at one or both ends)
        solid_left = w_f * (1 - share) * (0.6 if vi % 2 == 0 else 0.4)
        solid_right = w_f * (1 - share) - solid_left
        a, b = x0 - w_f / 2 + solid_left, x0 + w_f / 2 - solid_right
        if solid_left > 0.3:
            (stone_p if vi % 2 == 0 else clad).box((x0 - w_f / 2 + solid_left / 2, y_front + 0.12, (z0 + z1) / 2),
                                                   (solid_left, 0.3, z1 - z0))
        if solid_right > 0.3:
            (clad if vi % 2 == 0 else stone_p).box((x0 + w_f / 2 - solid_right / 2, y_front + 0.12, (z0 + z1) / 2),
                                                   (solid_right, 0.3, z1 - z0))
        _glass_panels(glass_p, frames, a, b, z0 + 0.12, z1, "x", y_front + 0.2, mullion=1.7 + r.uniform(-0.2, 0.2))
        # sides: glass at the front half, solid behind; back: solid with a band of windows
        for side in (-1, 1):
            xs = x0 + side * w_f / 2
            solid.box((xs - side * 0.12, 0.18 * d_f, (z0 + z1) / 2), (0.25, d_f * 0.64, z1 - z0))
            _glass_panels(glass_p, frames, y_front + 0.2, y_front + d_f * 0.36, z0 + 0.12, z1, "y", xs - side * 0.2,
                          mullion=1.8)
        solid.box((x0, y_back - 0.12, (z0 + z1) / 2), (w_f, 0.25, z1 - z0))
        _glass_panels(glass_p, frames, x0 - w_f * 0.3, x0 + w_f * 0.3, z0 + 1.0, z1 - 0.3, "x", y_back - 0.26,
                      mullion=1.5)
        # inside, seen through the glass: a warm back wall and a few partitions
        interior.box((x0, y_back - 0.6, (z0 + z1) / 2), (w_f - 0.6, 0.1, z1 - z0 - 0.15))
        for k in range(1, max(2, int(w_f / 6))):
            interior.box((x0 - w_f / 2 + k * w_f / max(2, int(w_f / 6)), y_back - d_f * 0.3, (z0 + z1) / 2),
                         (0.1, d_f * 0.5, z1 - z0 - 0.15))
        # an upper floor's terrace: the slab below cantilevers in front of it, with a glass balustrade
        if z0 > 0:
            y_edge = y_front - ov * 0.9
            rail_glass.box((x0, y_edge, z0 + 0.55), (w_f + ov, 0.02, 1.0))
            rails.box((x0, y_edge, z0 + 1.06), (w_f + ov, 0.06, 0.04))
            for k in range(int((w_f + ov) / 2.5) + 1):
                rails.box((x0 - (w_f + ov) / 2 + k * (w_f + ov) / max(1, int((w_f + ov) / 2.5)), y_edge, z0 + 0.5),
                          (0.04, 0.04, 1.0))
    # entrance door in the stone panel of the ground floor, left
    door = Parts()   # noqa: F821
    x0, w_f, d_f = volumes[0][0], volumes[0][1], volumes[0][2]
    door_x = x0 - w_f / 2 + max(0.9, w_f * (1 - share) * 0.3)
    door.box((door_x, -d_f / 2 - 0.05, 1.3), (1.3, 0.08, 2.6))
    handle = Parts()   # noqa: F821
    handle.box((door_x + 0.45, -d_f / 2 - 0.12, 1.2), (0.04, 0.04, 0.9))
    terrace_p = Parts()   # noqa: F821
    if terrace:   # a stone terrace across the front, a step down to the garden
        terrace_p.box((0, -D / 2 - 2.6, -0.1), (W + 1.0, 5.2, 0.24))
    made += [slabs.done(f"{name} Slabs", at, walls, bevel=0.02),
             solid.done(f"{name} Walls", at, walls),
             clad.done(f"{name} Cladding", at, cladding),
             stone_p.done(f"{name} Stone Walls", at, stone),
             frames.done(f"{name} Windows", at, "dark metal", bevel=0.004),
             glass_p.done(f"{name} Window Glass", at, "window glass"),
             rails.done(f"{name} Railings", at, "dark metal"),
             rail_glass.done(f"{name} Balcony Glass", at, "clear glass"),
             floors_p.done(f"{name} Floors", at, "travertine", bevel=0.01),
             terrace_p.done(f"{name} Terrace", at, "travertine", bevel=0.01),
             interior.done(f"{name} Interior", at, "#d9cbb8"),
             lights_p.done(f"{name} Downlights", at, material("#fff1d6", name="Jervis downlight", emission=0.0)),   # noqa: F821
             door.done(f"{name} Door", at, "dark wood", bevel=0.01),
             handle.done(f"{name} Door Handle", at, "steel")]
    root = _finish_asset(name, "villa", params, made, at, rotation,   # noqa: F821
                         f"a modern {floors}-storey villa{' with two wings' if wings == 2 else ''}: cantilevered white "
                         f"slabs with downlit soffits, floor-to-ceiling glass, {cladding} and stone panels, glass "
                         "balconies" + (" and a stone terrace" if terrace else ""))
    return root


# ---------- a storefront ----------

def storefront(name="Shop", at=None, width=8.0, depth=9.0, floors=2, facade="wood", color=None, style="traditional",
               awning=None, sign_color="#f4e9cf", signs=1, lanterns=2, display=True, light_color="warm", rotation=0,
               seed=0, **kw):
    """A shop / restaurant front: a ground floor of big display windows and a glazed door, the inside visible
    (warm walls, a counter, shelves, goods), a sign board over the front, an awning (modern) or a tiled eave
    (traditional, as on a Japanese street) between the floors, hanging paper lanterns, upper floors with framed
    windows, and a roof. Front faces -y. style: 'traditional' | 'modern'."""
    W = max(4.0, min(30.0, float(width or 8.0)))
    D = max(4.0, min(25.0, float(depth or 9.0)))
    floors = max(1, min(5, int(floors or 2)))
    style = "modern" if str(style).lower().startswith(("mod", "contemp", "glass")) else "traditional"
    with_awning = (style == "modern") if awning is None else bool(awning)
    params = dict(width=W, depth=D, floors=floors, facade=facade, color=color, style=style, awning=with_awning,
                  sign_color=sign_color, signs=signs, lanterns=lanterns, display=display, light_color=light_color,
                  rotation=rotation, seed=seed)
    at = _here(at)   # noqa: F821
    r = rng(seed)   # noqa: F821
    GF, UF, T = 3.6, 3.0, 0.25
    H = GF + (floors - 1) * UF
    wall_mat = color or ({"wood": "dark wood" if style == "traditional" else "wood slats", "plaster": "plaster",
                          "concrete": "concrete", "brick": "brick", "stone": "limestone", "glass": "white render",
                          "metal": "dark metal"}.get(str(facade).lower(), "dark wood"))
    made = []
    shell = Parts()   # noqa: F821
    shell.ring(W, D, T, 0.0, H)
    walls_obj = shell.done(f"{name} Walls", at, wall_mat)
    # the shop front: most of the ground floor open (display windows + door), upper windows in a row
    shopfront_w = W - 1.2
    cuts = [((0, -D / 2, 0.15 + (GF - 0.75) / 2), (shopfront_w, T * 3, GF - 0.75))]
    up_cols = max(1, int((W - 1.0) // 2.2))
    for f in range(1, floors):
        z0 = GF + (f - 1) * UF
        for k in range(up_cols):
            u = -W / 2 + 0.5 + (k + 0.5) * (W - 1.0) / up_cols
            cuts.append(((u, -D / 2, z0 + 0.9 + 0.75), (1.3, T * 3, 1.5)))
    _cut_boxes(walls_obj, cuts)   # noqa: F821
    made.append(walls_obj)
    frames, glass, door, inside, goods, sign, eave, lant, roof = (Parts(), Parts(), Parts(), Parts(), Parts(),   # noqa: F821
                                                                 Parts(), Parts(), Parts(), Parts())   # noqa: F821
    display_glass = Parts()   # noqa: F821  (clear: the lit shop shows through it)
    y_f = -D / 2
    z_top = GF - 0.6
    # display windows either side of a central glazed door
    door_w = 1.2
    door_x = -shopfront_w / 2 + shopfront_w * (0.5 if style == "modern" else 0.32)
    segments = [(-shopfront_w / 2, door_x - door_w / 2), (door_x + door_w / 2, shopfront_w / 2)]
    for a, b in segments:
        if b - a < 0.4:
            continue
        frames.box(((a + b) / 2, y_f + 0.05, 0.3), (b - a, 0.18, 0.6))   # a stall riser under the window
        _glass_panels(display_glass, frames, a, b, 0.6, z_top, "x", y_f + 0.08,
                      mullion=1.4 if style == "traditional" else 2.2, frame=0.07 if style == "traditional" else 0.05)
    door.box((door_x, y_f + 0.1, (z_top + 0.05) / 2), (door_w, 0.05, z_top - 0.05))
    glass.box((door_x, y_f + 0.06, z_top * 0.55), (door_w - 0.3, 0.02, z_top * 0.6))
    if style == "traditional":   # a lattice over the upper part of the display windows, and a noren-like curtain
        for a, b in segments:
            for k in range(int((b - a) / 0.18)):
                frames.box((a + (k + 0.5) * 0.18, y_f + 0.02, z_top - 0.35), (0.03, 0.04, 0.7))
        sign.box((door_x, y_f - 0.02, z_top - 0.45), (door_w + 0.2, 0.02, 0.85))   # the curtain (bright fabric)
    # inside: warm back and side walls, a counter, shelves of goods (what glows through the glass at night)
    inside.box((0, D / 2 - 0.4, GF / 2), (W - 0.6, 0.1, GF - 0.1))
    inside.box((0, D / 2 - 2.0, 0.5), (W * 0.5, 0.6, 1.0))   # the counter
    for k in range(3):
        inside.box((0, D / 2 - 0.55, 0.6 + k * 0.6), (W - 1.0, 0.3, 0.04))
    inside.box((0, 0, GF - 0.05), (W - 0.6, D - 0.6, 0.1))   # the ceiling of the shop
    if display:
        palette = [(0.75, 0.15, 0.08), (0.9, 0.55, 0.1), (0.3, 0.5, 0.12), (0.85, 0.75, 0.3), (0.6, 0.12, 0.25)]
        for k in range(int(shopfront_w / 0.5)):
            gx = -shopfront_w / 2 + 0.3 + k * 0.5
            if abs(gx - door_x) < door_w / 2 + 0.2:
                continue
            goods.lump((gx, y_f - 0.45, 0.82), 0.18, irregularity=0.3, squash=(1.2, 1, 0.6), detail=2, seed=k)
        crates = Parts()   # noqa: F821
        for k, gx in enumerate((door_x - door_w - 0.6, door_x + door_w + 0.6)):
            crates.box((gx, y_f - 0.45, 0.32), (0.9, 0.6, 0.64))
        made.append(crates.done(f"{name} Display", at, "light wood", bevel=0.01))
        goods_obj = goods.done(f"{name} Goods", at, None, smooth=True)
        goods_obj.data.materials.append(material(palette[r.randrange(len(palette))], name="Jervis produce"))   # noqa: F821
        made.append(goods_obj)
    # the sign over the front, and an awning or a tiled eave between the floors
    sign.box((0, y_f - 0.12, GF - 0.32), (shopfront_w * 0.8, 0.12, 0.55))
    for k in range(max(0, int(signs) - 1)):   # extra signs: vertical boards at the side
        sign.box((W / 2 - 0.4, y_f - 0.35, GF + 0.8 - k * 0.2), (0.12, 0.6, 1.6))
    if with_awning:
        eave.prism([(y_f - 1.4, GF - 0.9), (y_f, GF - 0.35), (y_f, GF - 0.3), (y_f - 1.4, GF - 0.85)],
                   -shopfront_w / 2, shopfront_w / 2, axis="x")
    else:   # traditional: a tiled pent roof between the floors
        eave.prism([(y_f - 1.1, GF + 0.05), (y_f + 0.05, GF + 0.6), (y_f + 0.05, GF + 0.72), (y_f - 1.15, GF + 0.15)],
                   -W / 2 - 0.2, W / 2 + 0.2, axis="x")
    # lanterns hanging under the eave
    for k in range(max(0, int(lanterns))):
        lx = -shopfront_w / 2 + 0.8 + k * (shopfront_w - 1.6) / max(1, int(lanterns) - 1) if int(lanterns) > 1 else 0
        lant.lump((lx, y_f - 0.75, GF - 0.85), 0.22, irregularity=0.0, squash=(1, 1, 1.35), detail=2)
    # upper floors: framed windows with glass, and a roof
    for f in range(1, floors):
        z0 = GF + (f - 1) * UF
        for k in range(up_cols):
            u = -W / 2 + 0.5 + (k + 0.5) * (W - 1.0) / up_cols
            _glass_panels(glass, frames, u - 0.65, u + 0.65, z0 + 0.9, z0 + 2.4, "x", y_f + 0.1, mullion=0.65)
    if style == "traditional":
        pitch = 0.6
        roof.prism([(y_f - 0.8, H), (0, H + D / 2 * pitch), (D / 2 + 0.8, H), (D / 2 + 0.8, H - 0.15), (0, H + D / 2 *
                    pitch - 0.15), (y_f - 0.8, H - 0.15)], -W / 2 - 0.3, W / 2 + 0.3, axis="x")
    else:
        roof.box((0, 0, H + 0.15), (W + 0.2, D + 0.2, 0.3))
        roof.box((0, y_f - 0.05, H + 0.55), (W + 0.2, 0.2, 0.6))
    made += [frames.done(f"{name} Windows", at, "dark wood" if style == "traditional" else "dark metal",
                         bevel=0.004),
             glass.done(f"{name} Window Glass", at, "window glass"),
             display_glass.done(f"{name} Display Glass", at, "clear glass"),
             door.done(f"{name} Door", at, "dark wood" if style == "traditional" else "dark metal", bevel=0.005),
             inside.done(f"{name} Interior", at, "#e9d5b3"),
             sign.done(f"{name} Sign", at, material(sign_color, name=f"Jervis sign {name}", emission=0.0)),   # noqa: F821
             eave.done(f"{name} Awning" if with_awning else f"{name} Eaves", at,
                       "#7a2a22" if with_awning else "slate", bevel=0.01),
             lant.done(f"{name} Lanterns", at, material("#f2e6c8", name=f"Jervis lantern {name}", emission=0.0),   # noqa: F821
                       smooth=True),
             roof.done(f"{name} Roof", at, "slate" if style == "traditional" else "concrete", bevel=0.01)]
    root = _finish_asset(name, "storefront", params, [m for m in made if m is not None], at, rotation,   # noqa: F821
                         f"a {floors}-storey {style} shopfront with display windows, a glazed door, a sign, "
                         f"{'an awning' if with_awning else 'a tiled eave'}"
                         + (f", {int(lanterns)} hanging lanterns" if int(lanterns) else "")
                         + " and a lit interior behind the glass")
    root["jervis_light_color"] = str(light_color)
    return root


# ---------- a room ----------

def room(name="Room", at=None, width=6.0, depth=5.0, height=2.8, walls="white render", floor="oak floor",
         windows=None, ceiling_light=True, door=True, rotation=0, **kw):
    """An interior: a floor, four walls with real thickness and a ceiling, window openings with frames, glass and
    a bright view outside, skirting boards, a door, a ceiling light. windows: [{'wall': 'back'|'left'|'right',
    'size': 'small'|'large'|'full height'}] (default: one large window in the back wall). Its open side for
    looking in is the front (-y): the camera stands inside, near it."""
    W = max(2.5, min(20.0, float(width or 6.0)))
    D = max(2.5, min(20.0, float(depth or 5.0)))
    H = max(2.2, min(6.0, float(height or 2.8)))
    windows = windows or [{"wall": "back", "size": "large"}]
    params = dict(width=W, depth=D, height=H, walls=walls, floor=floor, windows=windows,
                  ceiling_light=ceiling_light, door=door, rotation=rotation)
    at = _here(at)   # noqa: F821
    T = 0.2
    shell = Parts()   # noqa: F821
    shell.ring(W + 2 * T, D + 2 * T, T, 0.0, H)
    walls_obj = shell.done(f"{name} Walls", at, walls)
    cuts, frames, glass, view = [], Parts(), Parts(), Parts()   # noqa: F821
    sizes = {"small": (1.0, 1.1, 1.0), "large": (2.4, 1.6, 0.7), "full height": (2.8, H - 0.4, 0.15)}
    per_wall = {}
    for wdef in windows:
        if not isinstance(wdef, dict):
            continue
        wall = str(wdef.get("wall") or "back").lower()
        wall = wall if wall in ("back", "left", "right") else "back"
        per_wall.setdefault(wall, []).append(sizes.get(str(wdef.get("size") or "large").lower(), sizes["large"]))
    for wall, items in per_wall.items():
        length = W if wall == "back" else D
        for k, (ww, wh, sill) in enumerate(items):
            ww = min(ww, length / len(items) - 0.6)
            u = -length / 2 + (k + 0.5) * length / len(items)
            zc = sill + wh / 2
            if wall == "back":
                c, size_ = (u, D / 2 + T / 2, zc), (ww, T * 3, wh)
                _glass_panels(glass, frames, u - ww / 2, u + ww / 2, sill, sill + wh, "x", D / 2 + T / 2,
                              mullion=1.2)
                # (wide: seen at a slant from inside, a window-sized view ended and the outside showed black)
                view.box((u, D / 2 + 6.0, zc + 0.5), (max(ww * 4, W * 3), 0.1, wh * 4))
            else:
                side = -1 if wall == "left" else 1
                c, size_ = (side * (W / 2 + T / 2), u, zc), (T * 3, ww, wh)
                _glass_panels(glass, frames, u - ww / 2, u + ww / 2, sill, sill + wh, "y", side * (W / 2 + T / 2),
                              mullion=1.2)
                view.box((side * (W / 2 + 6.0), u, zc + 0.5), (0.1, max(ww * 4, D * 3), wh * 4))
            cuts.append((c, size_))
    if door:
        cuts.append(((-W / 2 - T / 2, -D / 2 + 1.2, 1.05), (T * 3, 0.95, 2.1)))
    _cut_boxes(walls_obj, cuts)   # noqa: F821
    floor_p, ceil, skirt, door_p, fix = Parts(), Parts(), Parts(), Parts(), Parts()   # noqa: F821
    floor_p.box((0, 0, -0.05), (W + 2 * T, D + 2 * T, 0.1))
    ceil.box((0, 0, H + 0.05), (W + 2 * T, D + 2 * T, 0.1))
    for (cx, cy, sx, sy) in ((0, D / 2 - 0.01, W, 0.02), (0, -D / 2 + 0.01, W, 0.02), (-W / 2 + 0.01, 0, 0.02, D),
                             (W / 2 - 0.01, 0, 0.02, D)):
        skirt.box((cx, cy, 0.05), (sx, sy, 0.1))
    if door:
        door_p.box((-W / 2 - 0.02, -D / 2 + 1.2, 1.03), (0.05, 0.9, 2.05))
    if ceiling_light:
        fix.cylinder((0, 0, H - 0.06), 0.25, 0.05, segments=24)
    made = [walls_obj, floor_p.done(f"{name} Floor", at, floor), ceil.done(f"{name} Ceiling", at, "white render"),
            skirt.done(f"{name} Skirting", at, "#f2f0ea"), frames.done(f"{name} Windows", at, "#f4f4f2", bevel=0.004),
            glass.done(f"{name} Window Glass", at, "clear glass"),
            view.done(f"{name} View", at, material("#cfe3f0", name="Jervis daylight view", emission=1.5)),   # noqa: F821
            door_p.done(f"{name} Door", at, "light wood", bevel=0.005),
            fix.done(f"{name} Ceiling Light", at, material("#fff6e5", name="Jervis ceiling light", emission=0.0))]   # noqa: F821
    root = _finish_asset(name, "room", params, [m for m in made if m is not None], at, rotation,   # noqa: F821
                         f"a {W:.1f} by {D:.1f} m room with {sum(len(v) for v in per_wall.values())} window(s), "
                         f"a {floor} floor and {walls} walls")
    root["jervis_role"] = "room"
    return root


# ---------- ground, roads, shore, hills, forest ----------

def ground(name="Ground", at=None, size=80.0, kind="lawn", hilly=0.0, depth=None, slope=0.0, **kw):
    """The ground: a broad surface of `kind` ('lawn', 'wild grass', 'sand', 'dirt', 'paving', 'asphalt', 'forest
    floor', 'snow', or any material), gently uneven when hilly > 0 (metres of variation), sloping up away from the
    viewer by `slope` (rise per metre). Things built on it stand on its surface."""
    S = max(4.0, min(2000.0, float(size or 80.0)))
    Dp = max(4.0, min(2000.0, float(depth or S)))
    params = dict(size=S, kind=kind, hilly=hilly, depth=Dp, slope=slope)
    if at is None:
        at = (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)
    at = tuple(_vec3(at))   # noqa: F821
    p = Parts()   # noqa: F821
    n = 48 if (hilly or slope) else 8
    bmesh.ops.create_grid(p.bm, x_segments=n, y_segments=n, size=0.5)
    off = Vector((3.7, 9.1, 0))
    for v in p.bm.verts:
        v.co.x *= S
        v.co.y *= Dp
        z = float(slope) * (v.co.y + Dp / 2)
        if hilly:
            z += float(hilly) * mathutils.noise.noise(Vector((v.co.x, v.co.y, 0)) / 25.0 + off)
            # flat where things stand (the middle), uneven toward the edges
            fade = min(1.0, (abs(v.co.x) / (S / 2)) ** 2 + (abs(v.co.y) / (Dp / 2)) ** 2)
            z = z * fade + float(slope) * (v.co.y + Dp / 2) * (1 - fade)
        v.co.z = z
    obj = p.done(f"{name} Surface", at, None, smooth="all", kind="terrain")
    mat = material(kind, hint="ground")   # noqa: F821
    _natural_variation(mat, kind)
    obj.data.materials.append(mat)
    return _finish_asset(name, "ground", params, [obj], at, 0, f"{_a(round(S))} {round(S)} m ground of {kind}")   # noqa: F821


# natural ground varies over metres, not only centimetres: drier and lusher, darker and lighter areas (a material
# that only varies at its own fine scale averages to one flat colour from any distance — a green plane)
_NATURAL_GROUND = {"lawn": ((0.72, 0.78, 0.6), (1.2, 1.12, 0.78)), "wild grass": ((0.7, 0.72, 0.62), (1.22, 1.15, 0.85)),
                   "forest floor": ((0.62, 0.66, 0.55), (1.25, 1.15, 0.95)), "sand": ((0.86, 0.84, 0.8), (1.08, 1.06, 1.0)),
                   "dirt": ((0.7, 0.68, 0.62), (1.2, 1.15, 1.05)), "snow": ((0.92, 0.94, 0.98), (1.04, 1.04, 1.04)),
                   "rock": ((0.75, 0.75, 0.72), (1.18, 1.15, 1.1))}


def _natural_variation(mat, kind):
    """Tone the material over a few metres (two scales of noise): the ground of a real place, not one colour."""
    tones = _NATURAL_GROUND.get(str(kind).lower())
    if tones is None or mat is None or not mat.use_nodes or mat.node_tree.nodes.get("Jervis ground variation"):
        return
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return
    base = bsdf.inputs["Base Color"]
    src = base.links[0].from_socket if base.is_linked else None
    coords = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.045   # patches ~20 m across...
    noise.inputs["Detail"].default_value = 4.0    # ...with smaller ones in them
    noise.inputs["Roughness"].default_value = 0.6
    nt.links.new(coords.outputs["Object"], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.35, 0.68
    ramp.color_ramp.elements[0].color = (*tones[0], 1.0)
    ramp.color_ramp.elements[1].color = (*tones[1], 1.0)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.name = "Jervis ground variation"
    mix.inputs["Factor"].default_value = 1.0
    if src is not None:
        nt.links.new(src, mix.inputs["A"])
    else:
        mix.inputs["A"].default_value = tuple(base.default_value)
    nt.links.new(ramp.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], base)


def road(name="Road", at=None, length=40.0, width=7.0, sidewalks=True, markings=True, wet=False, rotation=0, **kw):
    """A street: an asphalt carriageway with a dashed centre line, kerbs, and paved sidewalks either side. Runs
    along x (rotation turns it). wet=True: dark, reflective asphalt."""
    L = max(4.0, min(500.0, float(length or 40.0)))
    Wd = max(3.0, min(30.0, float(width or 7.0)))
    params = dict(length=L, width=Wd, sidewalks=sidewalks, markings=markings, wet=wet, rotation=rotation)
    at = _here(at)   # noqa: F821
    tar, lines, kerbs, walks = Parts(), Parts(), Parts(), Parts()   # noqa: F821
    tar.box((0, 0, 0.01), (L, Wd, 0.02))
    if markings:
        k = 0.0
        while k < L - 3:
            lines.box((-L / 2 + k + 1.5, 0, 0.022), (3.0, 0.15, 0.005))
            k += 6.0
    if sidewalks:
        for side in (-1, 1):
            kerbs.box((0, side * (Wd / 2 + 0.1), 0.075), (L, 0.2, 0.15))
            walks.box((0, side * (Wd / 2 + 0.2 + 1.5), 0.07), (L, 3.0, 0.14))
    made = [tar.done(f"{name} Asphalt", at, "wet asphalt" if wet else "asphalt"),
            lines.done(f"{name} Markings", at, "#e9e6dc"), kerbs.done(f"{name} Kerbs", at, "kerb", bevel=0.01),
            walks.done(f"{name} Sidewalks", at, "paving")]
    root = _finish_asset(name, "road", params, [m for m in made if m is not None], at, rotation,   # noqa: F821
                         f"{_a(round(L))} {round(L)} m street with a dashed centre line"   # noqa: F821
                         + (", kerbs and paved sidewalks" if sidewalks else ""))
    root["jervis_role"] = "path"
    return root


def shore(name="Beach", at=None, width=120.0, sand_depth=30.0, sea_depth=400.0, waves=0.5, sand="sand",
          sea_color=None, foam=True, **kw):
    """A shoreline: a wide sand beach sloping gently down into the sea, wet and darker where the water reaches,
    a line of surf, and open sea out to the horizon (rolling, reflective). The beach is at -y (nearer the
    viewer), the sea toward +y."""
    Wd = max(20.0, min(2000.0, float(width or 120.0)))
    SD = max(6.0, min(500.0, float(sand_depth or 30.0)))
    SeaD = max(30.0, min(5000.0, float(sea_depth or 400.0)))
    params = dict(width=Wd, sand_depth=SD, sea_depth=SeaD, waves=waves, sand=sand, sea_color=sea_color, foam=foam)
    if at is None:
        at = (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)
    at = tuple(_vec3(at))   # noqa: F821
    beach = Parts()   # noqa: F821
    bmesh.ops.create_grid(beach.bm, x_segments=64, y_segments=32, size=0.5)
    off = Vector((1.3, 4.4, 0))
    for v in beach.bm.verts:
        x, y = v.co.x * Wd, v.co.y * (SD + 12.0) - 6.0   # the sand runs 6 m on under the water
        t = (y + SD / 2) / SD
        v.co.x, v.co.y = x, y
        v.co.z = 0.6 * (1 - t) - 0.25 + 0.12 * mathutils.noise.noise(Vector((x / 9.0, y / 5.0, 0)) + off)
    sand_obj = beach.done(f"{name} Sand", at, None, smooth="all", kind="terrain")
    sand_obj.data.materials.append(material(sand, hint="sand"))   # noqa: F821
    sea = Parts()   # noqa: F821
    bmesh.ops.create_grid(sea.bm, x_segments=80, y_segments=80, size=0.5)
    for v in sea.bm.verts:
        v.co.x *= max(Wd * 3, SeaD)
        v.co.y = v.co.y * SeaD + SeaD / 2 + SD / 2 - 8.0
    sea_obj = sea.done(f"{name} Sea", at, None, smooth="all", kind="water")
    sea_obj.data.materials.append(_water_material(sea_color))   # noqa: F821
    made = [sand_obj, sea_obj]
    if foam:
        surf = Parts()   # noqa: F821
        for k in range(int(Wd / 3)):
            x = -Wd / 2 + (k + 0.5) * Wd / int(Wd / 3)
            y = SD / 2 - 3.0 + 1.2 * mathutils.noise.noise(Vector((x / 7.0, 0.3, 0)))
            surf.box((x, y, 0.02), (3.2, 0.35 + 0.25 * abs(mathutils.noise.noise(Vector((x / 3.0, 1.1, 0)))), 0.02))
        made.append(surf.done(f"{name} Surf", at, material("#eef4f2", name="Jervis surf", roughness=0.6)))   # noqa: F821
    root = _finish_asset(name, "shore", params, made, at, 0,   # noqa: F821
                         f"a {round(Wd)} m sandy beach sloping into the sea, with surf along the shore and open water "
                         "to the horizon")
    return root


def hills(name="Hills", at=None, distance=180.0, width=500.0, height=30.0, color="hazy hills", seed=0, **kw):
    """Distant hills (a backdrop ridge) `distance` metres away toward +y, `height` high — far enough that the
    atmosphere softens them (fog() makes them fade)."""
    Dist = max(30.0, min(5000.0, float(distance or 180.0)))
    Wd = max(50.0, min(10000.0, float(width or 500.0)))
    Hh = max(2.0, min(800.0, float(height or 30.0)))
    params = dict(distance=Dist, width=Wd, height=Hh, color=color, seed=seed)
    if at is None:
        at = (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)
    at = tuple(_vec3(at))   # noqa: F821
    p = Parts()   # noqa: F821
    bmesh.ops.create_grid(p.bm, x_segments=90, y_segments=12, size=0.5)
    off = Vector((seed * 1.7 + 0.3, seed * 0.9 + 5.1, 0))
    for v in p.bm.verts:
        x, t = v.co.x * Wd, v.co.y + 0.5
        ridge = Hh * (0.55 + 0.45 * mathutils.noise.noise(Vector((x / (Wd * 0.18), 0, 0)) + off))
        v.co.x, v.co.y = x, Dist + t * Hh * 3
        v.co.z = ridge * math.sin(min(1.0, t * 1.6) * math.pi / 2)
    obj = p.done(f"{name} Ridge", at, None, smooth="all", kind="terrain")
    obj.data.materials.append(material(color, hint="hills"))   # noqa: F821
    root = _finish_asset(name, "hills", params, [obj], at, 0, f"a ridge of hills about {round(Dist)} m away")   # noqa: F821
    root["jervis_role"] = "backdrop"
    return root


def forest(name="Forest", at=None, width=40.0, depth=15.0, count=30, kind="oak", seed=0, clumps=0, avoid=None,
           **kw):
    """A stand of trees `width` x `depth` metres (toward +y): a few real tree models, repeated as linked copies
    (instances: cheap however many there are), each turned and sized a little differently. kind: 'oak' | 'pine' |
    'palm' | 'mixed' | 'tropical' | 'shrubs' | 'rocks' | 'mossy rocks' (a bed of stones) | 'grass' | 'flowers' |
    'reeds' | 'ferns' (tufts). clumps: grown in that many groups (as plants seed), not evenly; avoid: areas
    [(x0, y0, x1, y1)] kept clear (a house, its door, the view of it)."""
    Wd, Dp = max(1.0, float(width or 40.0)), max(1.0, float(depth or 15.0))
    count = max(1, min(400, int(count or 30)))
    clumps = max(0, min(40, int(clumps or 0)))
    avoid = [tuple(map(float, a)) for a in (avoid or [])]
    params = dict(width=Wd, depth=Dp, count=count, kind=kind, seed=seed, clumps=clumps, avoid=[list(a) for a in avoid])
    at = _here(at)   # noqa: F821
    r = rng(seed)   # noqa: F821
    kinds = {"mixed": ["oak", "pine", "birch"], "tropical": ["palm", "oak"],
             "shrubs": ["bush", "bush", "bush"], "bush": ["bush", "bush", "bush"],
             "meadow": ["bush", "bush", "bush"], "rocks": ["rock", "rock", "rock"],
             "mossy rocks": ["mossy rock", "mossy rock", "mossy rock"], "grass": ["grass", "grass", "grass"],
             "flowers": ["flowers", "grass", "flowers"], "reeds": ["reeds", "reeds", "reeds"],
             "ferns": ["ferns", "ferns", "ferns"]}.get(str(kind).lower(), [str(kind).lower()])
    lib = _library()   # noqa: F821  (the hidden collection particles draw from)
    models = []
    for k, kd in enumerate(kinds * (3 // len(kinds) or 1)):
        lib_name = f"{name} Library {k + 1}"   # (not the tree's own name: an asset makes a collection of that name)
        coll = bpy.data.collections.get(lib_name)
        if coll is None:
            if kd in ("grass", "flowers", "reeds", "ferns"):   # tufts: the small plants a ground is covered in
                root = tuft(f"{name} Model {k + 1}", at=(0, -9000 - 30 * k, 0), kind=kd,   # noqa: F821
                            size=(0.9, 1.15, 1.35)[k % 3], seed=seed * 13 + k)
            elif kd in ("rock", "mossy rock"):   # a bed of stones: boulders and cobbles
                root = rock(f"{name} Model {k + 1}", at=(0, -9000 - 30 * k, 0), size=(0.35, 0.6, 1.0)[k % 3],   # noqa: F821
                            moss=kd == "mossy rock", seed=seed * 13 + k)
            elif kd == "bush":
                root = bush(f"{name} Model {k + 1}", at=(0, -9000 - 30 * k, 0), size=1.0 + 0.4 * k,   # noqa: F821
                            seed=seed * 13 + k)
            else:
                root = tree(f"{name} Model {k + 1}", at=(0, -9000 - 30 * k, 0), kind=kd, seed=seed * 13 + k)   # noqa: F821
            coll = bpy.data.collections.new(lib_name)
            lib.children.link(coll)
            for o in [root] + list(root.children_recursive):
                for c in list(o.users_collection):
                    c.objects.unlink(o)
                coll.objects.link(o)
                o["jervis_role"] = "library"
            root.location = (0, 0, 0)
            coll.instance_offset = (0, 0, 0)
        models.append(coll)
    spots = []
    centres = [(at[0] + r.uniform(-Wd / 2, Wd / 2), at[1] + r.uniform(-Dp / 2, Dp / 2)) for _ in range(clumps)]
    spread = max(0.8, min(Wd, Dp) / (1.5 + clumps ** 0.5)) if clumps else 0.0
    for _ in range(count * 40):
        if len(spots) >= count:
            break
        if centres:   # around a parent plant, thinning out from it
            cx, cy = centres[int(r.uniform(0, len(centres))) % len(centres)]
            x, y = cx + r.gauss(0, spread), cy + r.gauss(0, spread)
            if not (abs(x - at[0]) <= Wd / 2 and abs(y - at[1]) <= Dp / 2):
                continue
        else:
            x = at[0] + r.uniform(-Wd / 2, Wd / 2)
            y = at[1] + r.uniform(-Dp / 2, Dp / 2)
        if any(a[0] <= x <= a[2] and a[1] <= y <= a[3] for a in avoid):
            continue
        spots.append((x, y))
    if not spots:
        raise ValueError(f"No room for {name!r} there: all of it is to be kept clear.")
    small = str(kind).lower() in ("grass", "flowers", "reeds", "ferns")
    made = []
    for i, (x, y) in enumerate(spots):
        inst = bpy.data.objects.new(f"{name} Tree {i + 1}", None)
        inst.instance_type = "COLLECTION"
        inst.instance_collection = models[i % len(models)]
        inst.location = (x, y, ground_height(x, y, default=at[2]))   # noqa: F821
        inst.rotation_euler = (0, 0, r.uniform(0, math.tau))
        s_ = r.uniform(0.7, 1.4) if small else r.uniform(0.8, 1.25)
        inst.scale = (s_, s_, s_)
        _scene().collection.objects.link(inst)   # noqa: F821
        made.append(inst)
    root = assemble(name, [o.name for o in made], at=at)   # noqa: F821
    _remember(root, "forest", params)   # noqa: F821
    root["jervis_summary"] = f"a stand of {count} trees ({'/'.join(kinds)})"
    root["jervis_role"] = "backdrop"
    return root


PLACE_BUILDERS = ("villa", "storefront", "room", "ground", "road", "shore", "hills", "forest")
if bpy is not None:
    try:   # kit names too (see blender_kit._KIT)
        _KIT.update({k: globals()[k] for k in PLACE_BUILDERS + ("_glass_panels",)})   # noqa: F821
    except NameError:
        pass
