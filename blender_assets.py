"""Finished, detailed assets for Blender: house(), tree(), island(), water(), rock(), bush(), fence().

Why this exists: asked for "a detailed house", the local 7B model writing geometry code itself produced a box, a
door and a roof — every check passed (the parts existed), and it looked like a blockout. A small model is good at
choosing *what* to build and with which options; it is bad at inventing hundreds of correct coordinates. So each
asset here is modelled once, properly, by hand: real proportions, the parts a real one has (foundation, framed and
glazed windows with sills and lintels, a panelled door, fascia, gutters, a roof with real thickness and courses of
tiles, a chimney with a cap...), fitting materials, and seeded variation. The AI calls house('House', style='brick',
floors=2) and gets a finished model; it can still add to it with the kit.

Every asset:
  - is parametric, and remembers its parameters on its root object ("jervis_asset"), so a later "make the windows
    bigger" or "give it a red roof" rebuilds it with one option changed (rebuild_asset) instead of hacking at parts;
  - groups its parts by role, one object each ('House Walls', 'House Window Frames', 'House Roof'...), so a request
    can still name and change a part ("color the roof green", "make the door red");
  - stands on the ground, or on the terrain under it when there is one (an island);
  - is assembled under one parent, so it moves, turns and scales as one thing.

Loaded into the Blender bridge's namespace right after blender_kit.py (it uses the kit's own functions: _finish,
bevel, material, assemble...), and importable outside Blender for its catalogue (ASSET_TYPES).
"""
import json
import math

try:
    import bmesh
    import bpy
    import mathutils
    from mathutils import Matrix, Vector
except ImportError:   # imported by Jervis itself, for the catalogue only
    bpy = bmesh = mathutils = Matrix = Vector = None

ASSETS_VERSION = 1

# What Jervis (outside Blender) needs to know about each asset: the words that ask for it, and the options the AI may
# set. Kept as plain data so agent_blender.py can import it without Blender.
ASSET_TYPES = {
    "house": {
        "words": r"house|home|cottage|cabin|bungalow|villa|farmhouse|chalet|hut|shack|dwelling|mansion|townhouse",
        "options": {
            "style": ["cottage", "brick", "modern", "farmhouse", "cabin"],
            "floors": "1-3", "width": "metres (5-16)", "depth": "metres (4-12)",
            "walls": "material or colour", "roof_color": "material or colour", "trim": "colour",
            "door_color": "material or colour", "shutter_color": "colour",
            "roof": ["gable", "hip", "flat"], "window_scale": "0.6-1.6", "chimney": "bool", "porch": "bool",
            "shutters": "bool", "path": "bool", "rotation": "degrees"},
    },
    "tree": {
        "words": r"tree|oak|maple|pine|fir|spruce|conifer|palm|birch|willow",
        "options": {"kind": ["oak", "pine", "palm", "birch"], "height": "metres (2-20)",
                    "leaves": "material or colour (e.g. 'autumn leaves')", "seed": "integer",
                    "lean": "degrees it leans (0-35), a palm bent over a beach",
                    "lean_dir": ["left", "right", "toward", "away"]},
    },
    "island": {
        "words": r"island|islet|atoll|beach(?! ?(?:chair|umbrella|towel|ball|hut|house|bar|bag))",
        "options": {"radius": "metres (5-60)", "height": "metres (1-20)", "seed": "integer", "water": "bool",
                    "rocks": "bool", "trees": "0-30 trees growing on it", "tree_kind": ["palm", "pine", "oak", "birch"],
                    "waves": "0-1 how rough the sea is (0.3 calm, 0.8 lively)", "sea_color": "colour of the sea",
                    "foam": "bool: white surf along the shore"},
    },
    "water": {
        "words": r"water|ocean|sea|lake",
        "options": {"size": "metres", "color": "colour", "waves": "0-1"},
    },
    "rock": {
        "words": r"rock|boulder|stone",
        "options": {"size": "metres (0.2-5)", "moss": "bool", "seed": "integer", "count": "1-12 (a cluster)"},
    },
    "bush": {
        "words": r"bush|shrub|hedge",
        "options": {"size": "metres (0.4-3)", "flowers": "colour or none", "seed": "integer"},
    },
    "fence": {
        "words": r"fence|picket fence|railing",
        "options": {"length": "metres", "height": "metres (0.6-2)", "color": "material or colour",
                    "style": ["picket", "rail"], "rotation": "degrees"},
    },
    "bench": {
        "words": r"bench|park bench|garden bench",
        "options": {"length": "metres (1-3)", "style": ["park", "garden"], "color": "material or colour of the seat",
                    "frame_color": "material or colour of the frame", "rotation": "degrees"},
    },
    "lounger": {
        "words": r"sun lounger|lounger|sunbed|sun bed|sun lounge|deck chair|deckchair|chaise longue|chaise lounge",
        "options": {"color": "material or colour of the frame", "cushion": "colour of the cushion",
                    "rotation": "degrees"},
    },
    "car": {
        "words": r"car|sedan|automobile|hatchback|saloon car|family car",
        "options": {"color": "colour of the paint", "length": "metres (3.2-5.6)", "rotation": "degrees (0: nose to +x)"},
    },
    "garage": {
        "words": r"garage|carport",
        "options": {"width": "metres (2.8-9; 3.6 one car, 6 two)", "depth": "metres (4.5-9)", "height": "metres",
                    "walls": "material or colour", "door_color": "colour", "rotation": "degrees"},
    },
    "gate": {
        "words": r"gate|driveway gate|garden gate|front gate",
        "options": {"width": "metres (1-8), the opening", "height": "metres (0.8-2.5)", "color": "colour",
                    "style": ["bars", "boards"], "rotation": "degrees"},
    },
    "fire": {
        "words": r"campfire|camp fire|bonfire|fire pit|firepit|fire",
        "options": {"size": "metres (0.5-3)", "logs": "bool", "stones": "bool"},
    },
    "flag": {
        "words": r"flag|flagpole|flag pole|banner",
        "options": {"height": "metres (2-20), the pole", "size": "metres, the flag's width", "color": "colour"},
    },
    "waterfall": {
        "words": r"waterfall|cascade",
        "options": {"height": "metres (1-30)", "width": "metres (0.5-15)", "moss": "bool (a mossy cliff)"},
    },
    "river": {
        "words": r"river|stream|creek|brook",
        "options": {"length": "metres (10-200)", "width": "metres (1-30)", "color": "colour of the water"},
    },
    "cloud": {
        "words": r"cloud|clouds",
        "options": {"size": "metres (2-40)", "count": "1-8"},
    },
    "smoke": {
        "words": r"smoke|plume of smoke",
        "options": {"size": "metres"},
    },
    "fountain": {
        "words": r"fountain|water fountain|garden fountain",
        "options": {"size": "metres (1-8), the basin's width", "tiers": "1-3", "color": "material or colour",
                    "water_color": "colour of the water"},
    },
    "pond": {
        "words": r"pond|garden pond|koi pond|fish pond|lily pond",
        "options": {"size": "metres (1.5-20), its length", "depth": "metres (0.3-1.5)", "rocks": "bool: stones round it",
                    "reeds": "bool", "water_color": "colour of the water", "seed": "integer"},
    },
    "pool": {
        "words": r"pool|swimming pool|swimming-pool|lap pool|plunge pool",
        "options": {"length": "metres (3-25), its long side", "width": "metres (2-12)", "depth": "metres (0.8-3)",
                    "deck": "bool: paved deck around it", "ladder": "bool", "water_color": "colour of the water",
                    "tiles": "colour or material of the basin", "rotation": "degrees"},
    },
}


# ---------- materials the assets need beyond the kit's presets ----------
_EXTRA_PRESETS = {
    "siding": dict(colors=[(0.62, 0.6, 0.55), (0.7, 0.68, 0.62)], mortar=(0.35, 0.34, 0.31), pattern="tiles",
                   scale=1.0, bump=0.5, rough=0.7, row_height=0.2, brick_width=40.0, mortar_size=0.02),
    "slate": dict(colors=[(0.07, 0.075, 0.085), (0.15, 0.155, 0.17)], mortar=(0.03, 0.03, 0.035), pattern="tiles",
                  scale=2.6, bump=0.6, rough=0.55),
    "shingles": dict(colors=[(0.2, 0.12, 0.07), (0.33, 0.21, 0.12)], mortar=(0.08, 0.05, 0.03), pattern="tiles",
                     scale=3.0, bump=0.7, rough=0.85),
    "metal roof": dict(colors=[(0.22, 0.26, 0.28), (0.27, 0.31, 0.33)], mortar=(0.15, 0.17, 0.18), pattern="tiles",
                       scale=1.0, bump=0.3, rough=0.4, metallic=0.6, row_height=60.0, brick_width=0.3, mortar_size=0.03),
    "logs": dict(colors=[(0.2, 0.1, 0.045), (0.32, 0.18, 0.08)], mortar=(0.1, 0.06, 0.03), pattern="tiles",
                 scale=1.0, bump=0.9, rough=0.8, row_height=0.28, brick_width=40.0, mortar_size=0.04),
    "birch bark": dict(colors=[(0.75, 0.73, 0.68), (0.88, 0.87, 0.83)], pattern="streaks", scale=6.0, bump=0.4,
                       rough=0.8),
    "palm bark": dict(colors=[(0.22, 0.16, 0.1), (0.38, 0.29, 0.18)], pattern="streaks", scale=8.0, bump=0.8,
                      rough=0.9),
    "pine needles": dict(colors=[(0.01, 0.05, 0.025), (0.04, 0.13, 0.05)], pattern="noise", scale=14.0, bump=0.8,
                         rough=0.75),
    "palm leaves": dict(colors=[(0.06, 0.2, 0.03), (0.16, 0.38, 0.06)], pattern="noise", scale=10.0, bump=0.4,
                        rough=0.55),
    "terracotta": dict(colors=[(0.45, 0.16, 0.07), (0.6, 0.25, 0.11)], pattern="noise", scale=8.0, bump=0.3, rough=0.8),
    "window glass": dict(colors=[(0.045, 0.06, 0.075), (0.05, 0.065, 0.08)], pattern="none", rough=0.04),
    "brass": dict(colors=[(0.6, 0.42, 0.13), (0.75, 0.55, 0.2)], pattern="noise", scale=20.0, bump=0.02, rough=0.25,
                  metallic=1.0),
    "pool tiles": dict(colors=[(0.25, 0.62, 0.72), (0.35, 0.72, 0.8)], mortar=(0.85, 0.9, 0.9), pattern="tiles",
                       scale=6.0, bump=0.2, rough=0.15, row_height=0.5, brick_width=0.5, mortar_size=0.04),
    "travertine": dict(colors=[(0.68, 0.62, 0.52), (0.82, 0.77, 0.68)], pattern="noise", scale=5.0, bump=0.25,
                       rough=0.75),
    "gravel": dict(colors=[(0.3, 0.28, 0.25), (0.55, 0.52, 0.47)], pattern="cells", scale=18.0, bump=0.8, rough=0.95),
    "pavers": dict(colors=[(0.42, 0.4, 0.37), (0.56, 0.53, 0.49)], pattern="noise", scale=7.0, bump=0.3, rough=0.85),
}


def _install_presets():
    for key, spec in _EXTRA_PRESETS.items():
        PRESETS.setdefault(key, spec)   # noqa: F821  (the kit's, in the shared namespace)
    _PRESET_ALIASES.update({"wood siding": "siding", "clapboard": "siding", "weatherboard": "siding",  # noqa: F821
                            "slate tiles": "slate", "log": "logs", "log walls": "logs", "white bark": "birch bark",
                            "needles": "pine needles", "fronds": "palm leaves", "clay": "terracotta",
                            "tin roof": "metal roof", "corrugated metal": "metal roof", "copper roof": "copper"})


if bpy is not None and "PRESETS" in globals():   # loaded into the kit's namespace (not merely imported)
    _install_presets()


# ---------- building many pieces into one object ----------

class Parts:
    """Collects many pieces (boxes, prisms, cylinders, lumps) into ONE mesh, so a whole role of a model — all its
    window frames, every board of a deck — is one tidy object instead of dozens. Coordinates are relative to the
    asset's own origin; done() places it."""

    def __init__(self):
        self.bm = bmesh.new()

    def empty(self):
        return not self.bm.verts

    def box(self, center, size, rot=0.0, tilt=None):
        """An axis-aligned box (rot: degrees about z around its centre; tilt=(axis, degrees) about x or y)."""
        verts = bmesh.ops.create_cube(self.bm, size=1.0)["verts"]
        bmesh.ops.scale(self.bm, vec=tuple(max(1e-4, s) for s in size), verts=verts)
        if tilt:
            bmesh.ops.rotate(self.bm, verts=verts, cent=(0, 0, 0),
                             matrix=Matrix.Rotation(math.radians(tilt[1]), 4, tilt[0].upper()))
        if rot:
            bmesh.ops.rotate(self.bm, verts=verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(rot), 4, "Z"))
        bmesh.ops.translate(self.bm, vec=center, verts=verts)
        return verts

    def ring(self, width, depth, thickness, z0, z1):
        """A closed rectangular ring of walls (outer size width x depth, centred on 0, 0), as ONE watertight solid:
        separate wall slabs that merely touch at the corners make boolean cuts drop whole walls."""
        hw, hd, t = width / 2, depth / 2, thickness
        outer = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
        inner = [(-hw + t, -hd + t), (hw - t, -hd + t), (hw - t, hd - t), (-hw + t, hd - t)]
        ob = [self.bm.verts.new((x, y, z0)) for x, y in outer]
        ot = [self.bm.verts.new((x, y, z1)) for x, y in outer]
        ib = [self.bm.verts.new((x, y, z0)) for x, y in inner]
        it = [self.bm.verts.new((x, y, z1)) for x, y in inner]
        for i in range(4):
            j = (i + 1) % 4
            self.bm.faces.new((ob[i], ob[j], ot[j], ot[i]))      # outside
            self.bm.faces.new((ib[j], ib[i], it[i], it[j]))      # inside
            self.bm.faces.new((ot[i], ot[j], it[j], it[i]))      # top
            self.bm.faces.new((ob[j], ob[i], ib[i], ib[j]))      # bottom
        return ob + ot + ib + it

    def beam(self, a, b, width, height=None):
        """A square beam from point a to point b (rafters, rake boards, braces, railings)."""
        a, b = Vector(a), Vector(b)
        d = b - a
        length = d.length
        verts = bmesh.ops.create_cube(self.bm, size=1.0)["verts"]
        bmesh.ops.scale(self.bm, vec=(length, width, height or width), verts=verts)
        rot = d.to_track_quat("X", "Z").to_matrix().to_4x4()
        bmesh.ops.rotate(self.bm, verts=verts, cent=(0, 0, 0), matrix=rot)
        bmesh.ops.translate(self.bm, vec=(a + b) / 2, verts=verts)
        return verts

    def cylinder(self, base, radius, height, segments=12, radius_top=None, axis="z"):
        verts = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segments, radius1=radius,
                                      radius2=radius if radius_top is None else radius_top, depth=height)["verts"]
        bmesh.ops.translate(self.bm, vec=(0, 0, height / 2), verts=verts)
        if axis != "z":
            bmesh.ops.rotate(self.bm, verts=verts, cent=(0, 0, 0),
                             matrix=Matrix.Rotation(math.radians(90), 4, "Y" if axis == "x" else "X"))
        bmesh.ops.translate(self.bm, vec=base, verts=verts)
        return verts

    def prism(self, profile, start, end, axis="x"):
        """A solid whose cross-section is `profile` [(u, z), ...] (any polygon), running along x (or y) from start to
        end: roof slabs, gables, a bevelled board, a ridge cap."""
        rings = []
        for at_ in (start, end):
            if axis == "x":
                rings.append([self.bm.verts.new((at_, u, z)) for u, z in profile])
            else:
                rings.append([self.bm.verts.new((u, at_, z)) for u, z in profile])
        n = len(profile)
        faces = [self.bm.faces.new(rings[0]), self.bm.faces.new(list(reversed(rings[1])))]
        for i in range(n):
            faces.append(self.bm.faces.new((rings[0][i], rings[0][(i + 1) % n], rings[1][(i + 1) % n], rings[1][i])))
        return [v for ring in rings for v in ring]

    def lump(self, center, radius, irregularity=0.25, squash=(1, 1, 1), detail=3, seed=0, flat_bottom=None):
        """An organic lump like the kit's blob(), added to this mesh: foliage clusters, rocks, bushes."""
        verts = bmesh.ops.create_icosphere(self.bm, subdivisions=max(1, min(5, int(detail))), radius=1.0)["verts"]
        off = Vector(((seed * 12.9898) % 97, (seed * 78.233) % 89, (seed * 37.719) % 83))
        noise = mathutils.noise.noise
        sx, sy, sz = squash
        for v in verts:
            d = v.co.normalized()
            n = noise(d * 1.2 + off) + 0.35 * noise(d * 2.7 + off * 1.3) + 0.12 * noise(d * 6.0 + off * 0.7)
            k = max(0.3, 1 + irregularity * n)
            v.co = Vector((d.x * k * sx, d.y * k * sy, d.z * k * sz)) * radius
        if flat_bottom is not None:
            for v in verts:
                v.co.z = max(v.co.z, -radius * sz * (1 - flat_bottom))
        bmesh.ops.translate(self.bm, vec=center, verts=verts)
        return verts

    def add_tube(self, points, radius, radius_end=None, sides=10, radius_fn=None):
        """A tapering tube through world-relative points (smoothly curved): trunks, branches, pipes, palm fronds'
        spines. radius_fn(t) multiplies the radius along it (rings on a palm trunk)."""
        pts = [Vector(p) for p in points]
        if len(pts) > 2:
            pts = _spline(pts, 4)   # noqa: F821  (the kit's Catmull-Rom)
        r1 = radius if radius_end is None else radius_end
        n = len(pts)
        normal = previous = None
        rings = []
        for i, p in enumerate(pts):
            t = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            if normal is None:
                helper = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
                normal = t.cross(helper).normalized()
            else:
                normal = previous.rotation_difference(t) @ normal
                normal = (normal - t * normal.dot(t)).normalized()
            previous = t
            side = t.cross(normal)
            f = i / (n - 1)
            rr = max(1e-4, (radius + (r1 - radius) * f) * (radius_fn(f) if radius_fn else 1.0))
            rings.append([self.bm.verts.new(p + (normal * math.cos(a) + side * math.sin(a)) * rr)
                          for a in (2 * math.pi * k / sides for k in range(sides))])
        for i in range(n - 1):
            for k in range(sides):
                self.bm.faces.new((rings[i][k], rings[i][(k + 1) % sides], rings[i + 1][(k + 1) % sides],
                                   rings[i + 1][k]))
        self.bm.faces.new(rings[0])
        self.bm.faces.new(list(reversed(rings[-1])))
        return rings

    def done(self, name, at, color=None, bevel=0.0, smooth=None, kind="asset", segments=2):
        """Make the object (replacing this request's earlier one of the same name), or None if nothing was added."""
        if self.empty():
            self.bm.free()
            return None
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        if kind in ("terrain", "water"):   # an open sheet: recalculating can't tell up from down, so face it up
            self.bm.normal_update()
            if sum(f.normal.z for f in self.bm.faces) < 0:
                bmesh.ops.reverse_faces(self.bm, faces=self.bm.faces)
        kw = {}
        if smooth:
            kw["smooth"] = smooth
        obj = _finish(self.bm, name, tuple(at), color, 0, kw, kind)   # noqa: F821
        obj["jervis_shaped"] = True
        if kind == "water":   # water casts no shadow (a sea's shadow map made EEVEE hang; see animate_water)
            try:
                obj.visible_shadow = False
            except AttributeError:
                pass
        if bevel:
            globals()["bevel"](obj, bevel, segments)
        return obj


def _cut_boxes(obj, boxes):
    """Carve every (center, size) box out of `obj` in ONE boolean (window and door openings): fast, and the result is
    a clean wall with real holes."""
    if not boxes:
        return obj
    cutter = Parts()
    for center, size in boxes:
        cutter.box(center, size)
    cut_obj = cutter.done("__jervis_cutter", tuple(obj.location), kind="cutter")
    return cut(obj, cut_obj)   # noqa: F821


def _here(at):
    """Where an asset stands: `at`, or the request's preset spot (X, Y); on the terrain under it if there is one."""
    g = globals()
    if at is None:
        x, y, z = g.get("X", 0.0), g.get("Y", 0.0), None
    else:
        vals = list(_vec3(at))   # noqa: F821
        x, y, z = vals[0], vals[1], (vals[2] if len(list(at)) > 2 else None)
    if z is None or abs(z) < 1e-6:
        z = ground_height(x, y)
    return (float(x), float(y), float(z))


def ground_height(x, y, default=0.0):
    """The height of the terrain (an island, a hill) under (x, y), or `default` where there is none."""
    best = None
    deps = bpy.context.evaluated_depsgraph_get()
    for o in _scene().objects:   # noqa: F821
        if o.type != "MESH" or o.get("jervis_kind") != "terrain":
            continue
        from mathutils.bvhtree import BVHTree
        tree_ = BVHTree.FromObject(o, deps)
        inv = o.matrix_world.inverted()
        origin = inv @ Vector((x, y, 1000.0))
        direction = (inv.to_3x3() @ Vector((0, 0, -1))).normalized()
        hit = tree_.ray_cast(origin, direction)
        if hit and hit[0] is not None:
            z = (o.matrix_world @ hit[0]).z
            best = z if best is None else max(best, z)
    return default if best is None else best


def _remember(root, kind, params):
    root["jervis_asset"] = json.dumps({"type": kind, "params": params})
    root["jervis_kind"] = "asset"
    return root


def _finish_asset(name, kind, params, parts, at, rotation=0.0, summary=""):
    names = [p.name for p in parts if p is not None]
    root = assemble(name, names, at=at)   # noqa: F821
    if rotation:
        root.rotation_euler = (0, 0, math.radians(float(rotation)))
    _remember(root, kind, params)
    root["jervis_summary"] = summary or f"a {kind}"   # what Jervis tells the user he built
    _select(root)   # noqa: F821
    return root


def _a(number) -> str:
    """'an' before a number said with a vowel sound (8, 11, 18, 80...), else 'a'."""
    n = str(number)
    return "an" if n.startswith("8") or n in ("11", "18") or (len(n) in (5, 6) and n[:2] in ("11", "18")) else "a"


def _rgb(value, fallback):
    try:
        return rgb_of(value) if value is not None else fallback   # noqa: F821
    except ValueError:
        return fallback


# ---------- house ----------

_HOUSE_STYLES = {
    #            walls        roof          trim                    roof style  pitch shutters porch chimney  plinth
    "cottage":   ("plaster",  "roof tiles", (0.92, 0.9, 0.85),      "gable",    40,   True,    False, True,   "stone"),
    "brick":     ("brick",    "slate",      (0.9, 0.9, 0.88),       "gable",    38,   False,   False, True,   "concrete"),
    "modern":    ("#e8e6e1",  "concrete",   (0.06, 0.06, 0.065),    "flat",     0,    False,   False, False,  "concrete"),
    "farmhouse": ("siding",   "metal roof", (0.93, 0.93, 0.9),      "gable",    42,   False,   True,  True,   "stone"),
    "cabin":     ("logs",     "shingles",   (0.16, 0.09, 0.04),     "gable",    40,   False,   True,  True,   "stone"),
}


def house(name="House", at=None, style="cottage", floors=1, width=None, depth=None, walls=None, roof_color=None,
          trim=None, door_color=None, shutter_color=None, roof=None, window_scale=1.0, chimney=None, porch=None,
          shutters=None, path=True, rotation=0, seed=0, **kw):
    """A finished, detailed house. style: 'cottage' (plaster, tiled gable roof, shutters, chimney), 'brick' (brick,
    slate, white trim), 'modern' (flat roof, big dark-framed windows), 'farmhouse' (siding, metal roof, porch) or
    'cabin' (logs, shingles, porch). Any option overrides the style: floors=2, walls='brick', roof_color='red',
    window_scale=1.3, porch=True... Its front (with the door) faces -y; rotation turns it."""
    style = str(style or "cottage").lower()
    if style not in _HOUSE_STYLES:
        style = {"stone": "cottage", "wooden": "cabin", "wood": "cabin", "log": "cabin", "contemporary": "modern",
                 "minimal": "modern", "barn": "farmhouse", "country": "farmhouse"}.get(style, "cottage")
    s_walls, s_roof, s_trim, s_roof_style, pitch, s_shutters, s_porch, s_chimney, s_plinth = _HOUSE_STYLES[style]
    floors = max(1, min(3, int(floors or 1)))
    roof_style = str(roof or s_roof_style).lower()
    if roof_style not in ("gable", "hip", "flat"):
        roof_style = "gable"
    W = float(width or (9.0 if style == "modern" else 8.0 if floors > 1 else 7.5))
    D = float(depth or (7.0 if style == "modern" else 6.2))
    W, D = max(4.0, min(20.0, W)), max(3.5, min(16.0, D))
    ws = max(0.5, min(1.8, float(window_scale or 1.0)))
    params = dict(style=style, floors=floors, width=W, depth=D, walls=walls, roof_color=roof_color, trim=trim,
                  door_color=door_color, shutter_color=shutter_color, roof=roof_style, window_scale=ws,
                  chimney=chimney, porch=porch, shutters=shutters, path=path, rotation=rotation, seed=seed)
    walls_mat = walls or s_walls
    roof_mat = roof_color or s_roof
    trim_rgb = _rgb(trim, s_trim)
    trim_mat = trim if trim is not None else "#%02x%02x%02x" % tuple(int(c * 255) for c in trim_rgb)
    door_mat = door_color or ("dark wood" if style in ("cabin", "modern") else "#2c4a3a" if style == "cottage"
                              else "#7a1f1a" if style == "brick" else "wood")
    shutter_mat = shutter_color or "#33503f"
    with_shutters = s_shutters if shutters is None else bool(shutters)
    with_porch = s_porch if porch is None else bool(porch)
    with_chimney = s_chimney if chimney is None else bool(chimney)
    if roof_style == "flat":
        with_chimney = with_chimney and chimney is not None

    at = _here(at)
    # On sloping ground (an island, a hill) the house stands level on its highest corner and its foundation reaches
    # down to the lowest one, so no corner floats and none is buried.
    corners_z = [ground_height(at[0] + dx, at[1] + dy, default=at[2]) for dx in (-W / 2, W / 2) for dy in (-D / 2, D / 2)]
    drop = max(0.0, max(corners_z) - min(corners_z))
    at = (at[0], at[1], max(corners_z + [at[2]]))
    T = 0.25                                 # wall thickness
    P = 0.45 if style != "modern" else 0.25  # plinth height
    FH = 2.9 if style != "modern" else 3.1   # floor height
    H = P + floors * FH                      # top of the walls
    r = rng(seed)   # noqa: F821
    made = []

    # Foundation / plinth, slightly wider than the walls.
    plinth = Parts()
    plinth.box((0, 0, (P - drop - 0.1) / 2), (W + 0.24, D + 0.24, P + drop + 0.1))
    made.append(plinth.done(f"{name} Foundation", at, s_plinth, bevel=0.03))

    # Walls: one watertight ring, openings cut afterwards.
    shell = Parts()
    shell.ring(W, D, T, P, H)
    walls_obj = shell.done(f"{name} Walls", at, walls_mat)

    # Floors inside (seen through the windows) and the upper floors' slabs.
    inside = Parts()
    for f in range(floors):
        inside.box((0, 0, P + f * FH + 0.05), (W - 2 * T, D - 2 * T, 0.1))
    made.append(inside.done(f"{name} Floors", at, "dark wood"))

    # ----- where the windows and the door go -----
    win_w, win_h = 1.05 * ws, 1.35 * ws
    if style == "modern":
        win_w, win_h = 1.9 * ws, 2.1 * ws
    sill_h = 0.9 if style != "modern" else 0.5
    door_w, door_h = 1.0, 2.15

    def columns(length, gap, odd=False):
        """Evenly spaced window positions along a wall (an odd number on the front, so the door is centred)."""
        span = length - 1.2
        n = max(1, int(span // gap))
        if odd and n % 2 == 0:
            n = n + 1 if span / (n + 1) >= 1.6 else n - 1
        step = span / max(1, n)
        return [-span / 2 + step * (i + 0.5) for i in range(max(1, n))]

    # facade: (outward normal axis sign, axis, length). Front = -y.
    facades = {"front": ("y", -1, W), "back": ("y", 1, W), "left": ("x", -1, D), "right": ("x", 1, D)}
    openings = []        # (facade, u, z_bottom, w, h, kind)
    front_cols = columns(W, 2.3 if style != "modern" else 3.2, odd=True)
    door_u = min(front_cols, key=abs)
    for fname, (axis, sign, length) in facades.items():
        cols = front_cols if fname == "front" else columns(length, 2.4 if style != "modern" else 3.4)
        for f in range(floors):
            z0 = P + f * FH
            for u in cols:
                if fname == "front" and f == 0 and abs(u - door_u) < 1e-6:
                    openings.append((fname, u, z0 + 0.02, door_w, door_h, "door"))
                    continue
                openings.append((fname, u, z0 + sill_h, win_w, win_h, "window"))
    if not any(o[5] == "door" for o in openings):
        openings.append(("front", 0.0, P + 0.02, door_w, door_h, "door"))

    def place(fname, u, out, z):
        """A point on a facade: u along it, `out` metres outward from its outer face, at height z."""
        axis, sign, _ = facades[fname]
        if axis == "y":
            return (u, sign * (D / 2 + out), z)
        return (sign * (W / 2 + out), u, z)

    def size_on(fname, su, sn, sz):
        """A box's size on a facade: su along it, sn through it, sz up."""
        return (su, sn, sz) if facades[fname][0] == "y" else (sn, su, sz)

    cut_list = []
    for fname, u, zb, w_, h_, kind in openings:
        cut_list.append((place(fname, u, -T / 2, zb + h_ / 2), size_on(fname, w_, T * 3, h_)))
    _cut_boxes(walls_obj, cut_list)
    made.append(walls_obj)

    frames, glass, sills, trims, shut, door, hardware, steps = Parts(), Parts(), Parts(), Parts(), Parts(), Parts(), \
        Parts(), Parts()
    fb = 0.075                       # frame border
    for fname, u, zb, w_, h_, kind in openings:
        if kind == "door":
            # frame, a panelled door set back in the opening, a knob, and stone steps up to it
            for du, dz, su, sz in ((-(w_ / 2 + fb / 2), h_ / 2, fb, h_ + fb), ((w_ / 2 + fb / 2), h_ / 2, fb, h_ + fb),
                                   (0, h_ + fb / 2, w_ + 2 * fb, fb)):
                frames.box(place(fname, u + du, 0.02, zb + dz), size_on(fname, su, 0.14, sz))
            slab_out = -0.09
            door.box(place(fname, u, slab_out, zb + h_ / 2), size_on(fname, w_ - 0.04, 0.05, h_ - 0.02))
            for row in range(3):
                ph = (h_ - 0.5) / 3 - 0.08
                pz = zb + 0.22 + row * ((h_ - 0.5) / 3 + 0.03) + ph / 2
                for side in (-1, 1):
                    door.box(place(fname, u + side * (w_ / 4 - 0.02), slab_out + 0.035, pz),
                             size_on(fname, w_ / 2 - 0.16, 0.025, ph))
            knob_at = place(fname, u + w_ / 2 - 0.13, slab_out + 0.06, zb + 1.0)
            hardware.lump(knob_at, 0.035, irregularity=0.0, detail=2)
            hardware.box(place(fname, u + w_ / 2 - 0.13, slab_out + 0.035, zb + 1.0), size_on(fname, 0.05, 0.02, 0.16))
            if P > 0.15:   # steps up to the door, or up to the porch in front of it
                n_steps = max(1, int(round(P / 0.17)))
                front = 2.0 if with_porch else 0.0
                for i in range(n_steps):
                    rise = P * (i + 1) / n_steps
                    steps.box(place(fname, u, front + (n_steps - 1 - i) * 0.3 + 0.15, rise / 2),
                              size_on(fname, w_ + 0.6, 0.3 + 0.001 * i, rise))
            # a small canopy over the door (unless a porch covers it, or the eaves are too low for one)
            eave_z = H - 0.45 * math.tan(math.radians(pitch)) if roof_style != "flat" else H
            if not with_porch and style != "modern" and (fname != "front" or eave_z - (zb + h_) > 0.75
                                                         or floors > 1):
                c_at = place(fname, u, 0.45, zb + h_ + 0.32)
                trims.box(c_at, size_on(fname, w_ + 0.7, 0.9, 0.08))
                for side in (-1, 1):
                    trims.beam(place(fname, u + side * (w_ / 2 + 0.25), 0.0, zb + h_ - 0.15),
                               place(fname, u + side * (w_ / 2 + 0.25), 0.7, zb + h_ + 0.3), 0.07)
            elif style == "modern":
                trims.box(place(fname, u, 0.6, zb + h_ + 0.25), size_on(fname, w_ + 1.6, 1.2, 0.12))
            continue
        # window: frame with glazing bars, recessed glass, a sill below and a lintel above
        mid = 0.0
        for du, dz, su, sz in ((-(w_ - fb) / 2, h_ / 2, fb, h_), ((w_ - fb) / 2, h_ / 2, fb, h_),
                               (0, fb / 2, w_, fb), (0, h_ - fb / 2, w_, fb)):
            frames.box(place(fname, u + du, mid - 0.08, zb + dz), size_on(fname, su, 0.12, sz))
        if style != "modern":
            frames.box(place(fname, u, mid - 0.08, zb + h_ / 2), size_on(fname, 0.045, 0.08, h_ - 2 * fb))
            frames.box(place(fname, u, mid - 0.08, zb + h_ * 0.58), size_on(fname, w_ - 2 * fb, 0.08, 0.045))
        else:
            frames.box(place(fname, u, mid - 0.08, zb + h_ / 2), size_on(fname, 0.05, 0.08, h_ - 2 * fb))
        glass.box(place(fname, u, mid - 0.1, zb + h_ / 2), size_on(fname, w_ - 2 * fb + 0.02, 0.015, h_ - 2 * fb + 0.02))
        if style == "modern":
            sills.box(place(fname, u, 0.02, zb - 0.03), size_on(fname, w_ + 0.1, 0.12, 0.05))
        else:
            sills.box(place(fname, u, 0.06, zb - 0.035), size_on(fname, w_ + 0.22, 0.2, 0.07))
            lintel_mat_box = place(fname, u, 0.015, zb + h_ + 0.08)
            trims.box(lintel_mat_box, size_on(fname, w_ + 0.24, 0.05, 0.16))
        if with_shutters:
            sw = w_ / 2 + 0.02
            for side in (-1, 1):
                cu = u + side * (w_ / 2 + 0.08 + sw / 2)
                shut.box(place(fname, cu, 0.025, zb + h_ / 2), size_on(fname, sw, 0.04, h_))
                for k in range(int(h_ / 0.11)):
                    shut.box(place(fname, cu, 0.05, zb + 0.08 + k * 0.11), size_on(fname, sw - 0.08, 0.02, 0.05),
                             tilt=None)
    made.append(frames.done(f"{name} Windows", at, trim_mat, bevel=0.008))   # the frames: "the windows"
    made.append(glass.done(f"{name} Window Glass", at, "window glass"))
    made.append(sills.done(f"{name} Window Sills", at, "stone" if style in ("cottage", "brick") else trim_mat,
                           bevel=0.01))
    made.append(door.done(f"{name} Door", at, door_mat, bevel=0.006))
    made.append(hardware.done(f"{name} Door Handle", at, "brass"))
    made.append(steps.done(f"{name} Steps", at, "stone", bevel=0.015))
    made.append(shut.done(f"{name} Shutters", at, shutter_mat, bevel=0.005))

    # ----- trim: corner boards, a band between floors, a frieze under the eaves -----
    if style != "modern":
        for sx_ in (-1, 1):
            for sy_ in (-1, 1):
                trims.box((sx_ * (W / 2 + 0.005), sy_ * (D / 2 + 0.005), P + (H - P) / 2), (0.16, 0.16, H - P))
        for f in range(1, floors):
            z = P + f * FH
            trims.box((0, -D / 2 - 0.02, z), (W + 0.04, 0.06, 0.16))
            trims.box((0, D / 2 + 0.02, z), (W + 0.04, 0.06, 0.16))
            trims.box((-W / 2 - 0.02, 0, z), (0.06, D + 0.04, 0.16))
            trims.box((W / 2 + 0.02, 0, z), (0.06, D + 0.04, 0.16))
        trims.box((0, -D / 2 - 0.02, H - 0.12), (W + 0.04, 0.05, 0.24))
        trims.box((0, D / 2 + 0.02, H - 0.12), (W + 0.04, 0.05, 0.24))
    made.append(trims.done(f"{name} Trim", at, trim_mat, bevel=0.008))

    # ----- roof -----
    made += _house_roof(name, at, roof_style, W, D, H, pitch, roof_mat, walls_mat, trim_mat, style)

    # ----- chimney -----
    if with_chimney:
        ch = Parts()
        cx, cy = W * 0.28, D * 0.18
        rise = (D / 2) * math.tan(math.radians(pitch)) if roof_style != "flat" else 0.0
        top_z = (H + rise + 0.75) if roof_style != "flat" else H + 1.2
        ch.box((cx, cy, (H - 0.8 + top_z) / 2), (0.7, 0.6, top_z - (H - 0.8)))
        made.append(ch.done(f"{name} Chimney", at, "brick", bevel=0.01))
        cap = Parts()
        cap.box((cx, cy, top_z + 0.05), (0.84, 0.74, 0.1))
        cap.cylinder((cx - 0.12, cy, top_z + 0.1), 0.09, 0.32, segments=14, radius_top=0.08)
        cap.cylinder((cx + 0.14, cy, top_z + 0.1), 0.09, 0.26, segments=14, radius_top=0.08)
        made.append(cap.done(f"{name} Chimney Cap", at, "terracotta" if style == "cottage" else "concrete",
                             bevel=0.01))

    # ----- porch -----
    if with_porch:
        made += _house_porch(name, at, W, D, P, H, door_u, roof_mat, trim_mat, style)

    # ----- a stepping-stone path to the door -----
    if path:
        stones = Parts()
        n = 6
        start = -D / 2 - 0.3 - (max(1, int(round(P / 0.17))) * 0.3 if P > 0.15 else 0.0) - (2.0 if with_porch else 0.0)
        for i in range(n):
            y = start - 0.55 - i * 0.62
            x = door_u + r.uniform(-0.12, 0.12)
            stones.lump((x, y, 0.0), r.uniform(0.27, 0.36), irregularity=0.3, squash=(r.uniform(1.0, 1.3), 0.85, 0.1),
                        detail=2, seed=seed * 31 + i, flat_bottom=0.5)
        made.append(stones.done(f"{name} Path", at, "stone"))

    n_windows = sum(1 for o in openings if o[5] == "window")
    wall_words = {"plaster": "plastered", "brick": "brick", "siding": "clapboard", "logs": "log"}.get(
        str(walls_mat), str(walls_mat))
    if wall_words.startswith("#"):   # a colour code is said as its colour ("#e8e6e1" -> "white")
        wall_words = color_name(_rgb(wall_words, (0.9, 0.9, 0.9)))   # noqa: F821
    roof_words = {"roof tiles": "tiled", "slate": "slate", "shingles": "shingled", "metal roof": "metal",
                  "concrete": "concrete"}.get(str(roof_mat), str(roof_mat))
    extras = [x for x, on in (("a chimney", with_chimney), ("a porch", with_porch), ("shutters", with_shutters),
                              ("a stone path", path)) if on]
    summary = (f"a {'two-storey ' if floors == 2 else 'three-storey ' if floors == 3 else ''}{style} house with "
               f"{wall_words} walls, {n_windows} framed glass windows, a panelled door, a {roof_words} "
               f"{roof_style} roof" + (f", {', '.join(extras[:-1])} and {extras[-1]}" if len(extras) > 1 else
                                       f" and {extras[0]}" if extras else ""))
    return _finish_asset(name, "house", params, made, at, rotation, summary)


def _house_roof(name, at, roof_style, W, D, H, pitch, roof_mat, walls_mat, trim_mat, style):
    made = []
    ov = 0.45            # eave overhang
    og = 0.3             # gable overhang
    t = 0.16             # roof thickness
    if roof_style == "flat":
        slab = Parts()
        slab.box((0, 0, H + 0.12), (W + 0.3, D + 0.3, 0.24))
        made.append(slab.done(f"{name} Roof", at, roof_mat if roof_mat not in ("roof tiles", "slate") else "concrete",
                              bevel=0.01))
        parapet = Parts()
        for sx_ in (-1, 1):
            parapet.box((sx_ * (W / 2 + 0.1), 0, H + 0.42), (0.2, D + 0.4, 0.36))
        for sy_ in (-1, 1):
            parapet.box((0, sy_ * (D / 2 + 0.1), H + 0.42), (W + 0.4, 0.2, 0.36))
        parapet.box((W * 0.2, D * 0.15, H + 0.24 + 0.3), (1.4, 1.0, 0.6))   # a rooftop unit
        made.append(parapet.done(f"{name} Parapet", at, trim_mat, bevel=0.01))
        return made
    rise = (D / 2) * math.tan(math.radians(pitch))
    slope = math.atan2(rise, D / 2)
    run = (D / 2 + ov) / math.cos(slope)
    if roof_style == "hip":
        made.append(_hip_roof(name, at, W, D, H, rise, ov, t, roof_mat))
    else:
        roof_p = Parts()
        courses = max(4, int(run / 0.32))
        lip = 0.035
        for sign in (-1, 1):
            # Cross-section in (y, z), ridge to eave: a slab whose top is stepped into courses, each course's
            # lower edge lying proud over the course below it (the way tiles and shingles overlap).
            outline = []
            for k in range(courses + 1):
                f = k / courses
                y = sign * f * run * math.cos(slope)
                z = H + rise - f * run * math.sin(slope) + t
                if k > 0:
                    outline.append((y, z + lip))
                if k < courses:
                    outline.append((y, z))
            eave_y, eave_z = sign * run * math.cos(slope), H + rise - run * math.sin(slope)
            outline += [(eave_y, eave_z), (0.0, H + rise)]
            roof_p.prism(outline, -W / 2 - og, W / 2 + og, axis="x")
        made.append(roof_p.done(f"{name} Roof", at, roof_mat))
        # ridge cap
        ridge = Parts()
        ridge.cylinder((-W / 2 - og - 0.02, 0, H + rise + t + 0.02), 0.11, W + 2 * og + 0.04, segments=10, axis="x")
        made.append(ridge.done(f"{name} Roof Ridge", at, roof_mat, smooth=True))
        # gable walls (the triangles under the roof at each end), in the walls' material
        gables = Parts()
        for sx_ in (-1, 1):
            x = sx_ * (W / 2 - 0.125)
            tri = [(-D / 2, H), (D / 2, H), (0, H + rise)]
            gables.prism(tri if sx_ < 0 else tri, x - 0.125, x + 0.125, axis="x")
        made.append(gables.done(f"{name} Gables", at, walls_mat))
        # fascia along the eaves, barge boards along the gable edges, a small attic vent in each gable
        fascia = Parts()
        ez = H + rise - run * math.sin(slope)
        for sign in (-1, 1):
            ey = sign * run * math.cos(slope)
            fascia.box((0, ey + sign * 0.02, ez + t / 2 - 0.02), (W + 2 * og + 0.06, 0.05, t + 0.12))
            for sx_ in (-1, 1):
                fascia.beam((sx_ * (W / 2 + og + 0.02), 0, H + rise + t),
                            (sx_ * (W / 2 + og + 0.02), ey, ez + t * 0.6), 0.05, 0.22)
        for sx_ in (-1, 1):
            vent_z = H + rise * 0.45
            fascia.box((sx_ * (W / 2 + 0.01), 0, vent_z), (0.06, 0.7, 0.5))
        made.append(fascia.done(f"{name} Fascia", at, trim_mat, bevel=0.006))
        vents = Parts()
        for sx_ in (-1, 1):
            for k in range(4):
                vents.box((sx_ * (W / 2 + 0.045), 0, H + rise * 0.45 - 0.17 + k * 0.11), (0.02, 0.56, 0.05),
                          tilt=("y", 0))
        made.append(vents.done(f"{name} Attic Vents", at, "dark gray"))
        # gutters and downspouts
        gut = Parts()
        for sign in (-1, 1):
            ey = sign * (run * math.cos(slope) + 0.09)
            gut.cylinder((-W / 2 - og, ey, ez - 0.02), 0.075, W + 2 * og, segments=10, axis="x")
            for sx_ in (-1, 1):
                x = sx_ * (W / 2 + 0.05)
                gut.add_tube([(x, ey, ez - 0.02), (x, ey, ez - 0.25), (x, sign * (D / 2 + 0.07), ez - 0.5),
                              (x, sign * (D / 2 + 0.07), 0.15)], 0.045, sides=8)
        made.append(gut.done(f"{name} Gutters", at, "metal", smooth=True))
    return made


def _hip_roof(name, at, W, D, H, rise, ov, t, roof_mat):
    """A hip roof: four sloped faces meeting at a short ridge, with real thickness."""
    w, d = W / 2 + ov, D / 2 + ov
    drop = ov * math.tan(math.atan2(rise, D / 2))
    z0 = H - drop
    ridge_half = max(0.0, (W - D) / 2)
    z1 = H + rise
    bm_parts = Parts()
    bm = bm_parts.bm
    bottom = [bm.verts.new(p) for p in ((-w, -d, z0), (w, -d, z0), (w, d, z0), (-w, d, z0))]
    top = [bm.verts.new(p) for p in ((-w, -d, z0 + t), (w, -d, z0 + t), (w, d, z0 + t), (-w, d, z0 + t))]
    rb = [bm.verts.new(p) for p in ((-ridge_half, 0, z1), (ridge_half, 0, z1))]
    rt = [bm.verts.new(p) for p in ((-ridge_half, 0, z1 + t), (ridge_half, 0, z1 + t))]
    for loop_, ridge_ in ((top, rt),):
        bm.faces.new((loop_[0], loop_[1], ridge_[1], ridge_[0]))
        bm.faces.new((loop_[1], loop_[2], ridge_[1]))
        bm.faces.new((loop_[2], loop_[3], ridge_[0], ridge_[1]))
        bm.faces.new((loop_[3], loop_[0], ridge_[0]))
    bm.faces.new((bottom[1], bottom[0], rb[0], rb[1]))
    bm.faces.new((bottom[2], bottom[1], rb[1]))
    bm.faces.new((bottom[3], bottom[2], rb[1], rb[0]))
    bm.faces.new((bottom[0], bottom[3], rb[0]))
    for i in range(4):
        bm.faces.new((bottom[i], bottom[(i + 1) % 4], top[(i + 1) % 4], top[i]))
    return bm_parts.done(f"{name} Roof", at, roof_mat, bevel=0.02)


def _house_porch(name, at, W, D, P, H, door_u, roof_mat, trim_mat, style):
    made = []
    pw = min(W - 0.4, max(3.2, W * 0.62))
    pd = 2.0
    y0 = -D / 2
    deck = Parts()
    boards = int(pw / 0.14)
    for i in range(boards):
        x = door_u - pw / 2 + (i + 0.5) * pw / boards
        deck.box((x, y0 - pd / 2, P - 0.03), (pw / boards - 0.012, pd, 0.05))
    deck.box((door_u, y0 - pd / 2, (P - 0.06) / 2), (pw, pd, max(0.05, P - 0.06)))
    made.append(deck.done(f"{name} Porch Deck", at, "wood" if style != "cabin" else "dark wood", bevel=0.004))
    posts = Parts()
    ph = 2.55
    post_xs = [door_u - pw / 2 + 0.12, door_u - pw / 6, door_u + pw / 6, door_u + pw / 2 - 0.12]
    for x in post_xs:
        y = y0 - pd + 0.12
        posts.box((x, y, P + 0.08), (0.22, 0.22, 0.16))
        posts.box((x, y, P + ph / 2), (0.14, 0.14, ph))
        posts.box((x, y, P + ph - 0.06), (0.2, 0.2, 0.12))
    posts.box((door_u, y0 - pd + 0.12, P + ph + 0.1), (pw, 0.16, 0.2))
    # railings between the posts, leaving the middle (the way in) open
    for a, b in ((post_xs[0], post_xs[1]), (post_xs[2], post_xs[3])):
        y = y0 - pd + 0.12
        posts.box(((a + b) / 2, y, P + 0.9), (b - a, 0.07, 0.07))
        posts.box(((a + b) / 2, y, P + 0.12), (b - a, 0.07, 0.05))
        n = int((b - a) / 0.14)
        for k in range(1, n):
            posts.box((a + (b - a) * k / n, y, P + 0.5), (0.035, 0.035, 0.78))
    made.append(posts.done(f"{name} Porch Posts", at, trim_mat, bevel=0.006))
    roof_p = Parts()
    z_wall = min(H - 0.2, P + ph + 0.85)
    z_front = P + ph + 0.2
    prof = [(y0 + 0.02, z_wall), (y0 - pd - 0.35, z_front), (y0 - pd - 0.35, z_front + 0.12), (y0 + 0.02, z_wall + 0.12)]
    roof_p.prism(prof, door_u - pw / 2 - 0.25, door_u + pw / 2 + 0.25, axis="x")
    made.append(roof_p.done(f"{name} Porch Roof", at, roof_mat, bevel=0.01))
    return made


# ---------- trees ----------

def _leaf_material(leaves, kind):
    if leaves:
        return leaves
    return {"pine": "pine needles", "palm": "palm leaves"}.get(kind, "leaves")


def tree(name="Tree", at=None, kind="oak", height=None, leaves=None, seed=0, rotation=0, lean=None, lean_dir=None,
         **kw):
    """A finished tree. kind: 'oak' (broad, branching crown), 'pine' (a conifer with drooping tiers), 'palm'
    (curved ringed trunk, arching fronds, coconuts) or 'birch' (slender, white bark). height in metres;
    leaves='autumn leaves' or any colour; a different seed is a different tree. lean: degrees it tilts from its
    base, toward lean_dir 'left' | 'right' | 'toward' (-y) | 'away' (+y, the default)."""
    kind = str(kind or "oak").lower()
    kind = {"maple": "oak", "deciduous": "oak", "apple": "oak", "fir": "pine", "spruce": "pine", "conifer": "pine",
            "christmas": "pine", "coconut": "palm", "tropical": "palm", "aspen": "birch", "willow": "oak"}.get(kind, kind)
    if kind not in ("oak", "pine", "palm", "birch"):
        kind = "oak"
    default_h = {"oak": 6.5, "pine": 9.0, "palm": 7.5, "birch": 8.0}[kind]
    h = max(1.5, min(30.0, float(height or default_h)))
    params = dict(kind=kind, height=h, leaves=leaves, seed=seed, rotation=rotation, lean=lean, lean_dir=lean_dir)
    at = _here(at)
    r = rng(seed * 7 + 11)   # noqa: F821
    made = {"oak": _oak, "birch": _oak, "pine": _pine, "palm": _palm}[kind](name, at, h, r, seed, kind, leaves)
    look = {"oak": "a branching trunk, roots and a full leafy crown", "birch": "a slender white trunk and an airy crown",
            "pine": "a tapering trunk and drooping tiers of needles", "palm": "a curved ringed trunk, arching fronds and "
                                                                                "coconuts"}[kind]
    root = _finish_asset(name, "tree", params, made, at, rotation, f"{_a(round(h))} {round(h)} m {kind} tree with {look}")
    if lean:   # a palm bent over a beach: the whole tree tilts from its base (by default away from the viewer)
        a = math.radians(float(lean))
        tilt = {"left": (0.0, -a), "right": (0.0, a), "toward": (a, 0.0)}.get(str(lean_dir or "away").lower(),
                                                                              (-a, 0.0))
        root.rotation_euler = (tilt[0], tilt[1], root.rotation_euler[2])
        root["jervis_summary"] += f", leaning {round(float(lean))} degrees"
    return root


def _oak(name, at, h, r, seed, kind, leaves):
    birch = kind == "birch"
    wood = Parts()
    trunk_r = h * (0.045 if not birch else 0.028)
    split = h * (0.42 if not birch else 0.35)
    lean = Vector((r.uniform(-0.25, 0.25), r.uniform(-0.25, 0.25), 0)) * h * 0.04
    crown_top = Vector((0, 0, h * (0.62 if not birch else 0.8))) + lean
    wood.add_tube([(0, 0, -0.15), (lean.x * 0.3, lean.y * 0.3, split * 0.5), (lean.x, lean.y, split),
                   tuple(crown_top)], trunk_r * 1.15, trunk_r * 0.45, sides=14)
    roots = 5 if not birch else 3
    for i in range(roots):   # roots flaring into the ground
        a = 2 * math.pi * i / roots + r.uniform(-0.3, 0.3)
        out = Vector((math.cos(a), math.sin(a), 0))
        wood.add_tube([tuple(out * trunk_r * 0.2 + Vector((0, 0, trunk_r * 1.6))),
                       tuple(out * trunk_r * 1.8 + Vector((0, 0, trunk_r * 0.3))),
                       tuple(out * trunk_r * 3.0 + Vector((0, 0, -0.1)))], trunk_r * 0.45, trunk_r * 0.12, sides=8)
    tips = []
    limbs = 4 if not birch else 9
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(limbs):
        if birch:   # a tall, airy crown: limbs all the way up the trunk, spiralling round it, rising steeply
            a = golden * i * 2 + r.uniform(-0.3, 0.3)
            z = h * (0.33 + 0.5 * i / (limbs - 1))
            start = Vector((lean.x * z / crown_top.z, lean.y * z / crown_top.z, z))
            reach = h * r.uniform(0.09, 0.15) * (1.15 - 0.5 * i / limbs)
            end = start + Vector((math.cos(a) * reach, math.sin(a) * reach, h * r.uniform(0.07, 0.14)))
        else:
            a = 2 * math.pi * i / limbs + r.uniform(-0.35, 0.35)
            t0 = r.uniform(0.5, 0.95)
            start = Vector((lean.x * t0, lean.y * t0, split + (crown_top.z - split) * (t0 - 0.5) * 0.9))
            reach = h * r.uniform(0.2, 0.3)
            end = start + Vector((math.cos(a) * reach, math.sin(a) * reach, h * r.uniform(0.15, 0.28)))
        mid = (start + end) / 2 + Vector((0, 0, h * 0.04))
        wood.add_tube([tuple(start), tuple(mid), tuple(end)], trunk_r * 0.55, trunk_r * 0.18, sides=10)
        tips.append(end)
        for j in range(2):   # secondary branches off each limb
            f = r.uniform(0.45, 0.8)
            base = start.lerp(end, f)
            b = a + r.choice((-1, 1)) * r.uniform(0.5, 1.0)
            twig_end = base + Vector((math.cos(b), math.sin(b), r.uniform(0.4, 0.9))) * reach * 0.55
            wood.add_tube([tuple(base), tuple(twig_end)], trunk_r * 0.22, trunk_r * 0.07, sides=6)
            tips.append(twig_end)
    tips.append(crown_top)
    trunk_obj = wood.done(f"{name} Trunk", at, "birch bark" if birch else "bark", smooth=True)
    foliage = Parts()
    k = 0
    cluster = h * (0.13 if not birch else 0.065)
    for tip in tips:
        for j in range(4 if not birch else 3):
            k += 1
            off = Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-0.35, 0.7))) * cluster * 0.8
            foliage.lump(tuple(tip + off), cluster * r.uniform(0.75, 1.15), irregularity=0.32 if not birch else 0.4,
                         squash=(1.0, 1.0, 0.82) if not birch else (0.9, 0.9, 1.2), detail=3, seed=seed * 101 + k)
    leaf_obj = foliage.done(f"{name} Leaves", at, _leaf_material(leaves, kind), smooth=True)
    return [trunk_obj, leaf_obj]


def _pine(name, at, h, r, seed, kind, leaves):
    wood = Parts()
    trunk_r = h * 0.03
    wood.add_tube([(0, 0, -0.15), (0, 0, h * 0.5), (r.uniform(-0.05, 0.05), r.uniform(-0.05, 0.05), h * 0.97)],
                  trunk_r * 1.2, trunk_r * 0.15, sides=12)
    for i in range(4):
        a = 2 * math.pi * i / 4 + r.uniform(-0.3, 0.3)
        out = Vector((math.cos(a), math.sin(a), 0))
        wood.add_tube([tuple(Vector((0, 0, trunk_r * 1.2))), tuple(out * trunk_r * 2.6 + Vector((0, 0, -0.08)))],
                      trunk_r * 0.5, trunk_r * 0.15, sides=6)
    trunk_obj = wood.done(f"{name} Trunk", at, "bark", smooth=True)
    needles = Parts()
    bm = needles.bm
    tiers = max(5, int(h / 1.1))
    bottom = h * 0.18
    spikes = 14
    for i in range(tiers):
        f = i / (tiers - 1)
        z = bottom + (h * 0.94 - bottom) * f
        radius = h * 0.24 * (1 - f) ** 0.85 + 0.25
        tier_h = (h - bottom) / tiers * 1.9
        apex = bm.verts.new((0, 0, z + tier_h))
        rim, inner = [], []
        phase = r.uniform(0, 2 * math.pi)
        for k in range(spikes * 2):
            a = phase + math.pi * k / spikes
            rr = radius * (1.0 if k % 2 == 0 else 0.72) * r.uniform(0.9, 1.08)
            droop = -radius * 0.28 if k % 2 == 0 else -radius * 0.12
            rim.append(bm.verts.new((math.cos(a) * rr, math.sin(a) * rr, z + droop)))
            inner.append(bm.verts.new((math.cos(a) * rr * 0.55, math.sin(a) * rr * 0.55, z + tier_h * 0.18)))
        n = len(rim)
        for k in range(n):
            bm.faces.new((rim[k], rim[(k + 1) % n], apex))
            bm.faces.new((inner[(k + 1) % n], inner[k], rim[k], rim[(k + 1) % n]))
            bm.faces.new((apex, inner[(k + 1) % n], inner[k]))
    leaf_obj = needles.done(f"{name} Needles", at, _leaf_material(leaves, "pine"))
    return [trunk_obj, leaf_obj]


def _palm(name, at, h, r, seed, kind, leaves):
    wood = Parts()
    a = r.uniform(0, 2 * math.pi)
    lean_dir = Vector((math.cos(a), math.sin(a), 0))
    top = lean_dir * h * 0.22 + Vector((0, 0, h))
    pts = [Vector((0, 0, -0.15)), lean_dir * h * 0.02 + Vector((0, 0, h * 0.3)),
           lean_dir * h * 0.09 + Vector((0, 0, h * 0.65)), top]
    rings = int(h * 4)

    def ringed(t):   # a bulge at every leaf scar, and a flared foot
        return 1.0 + 0.09 * max(0.0, math.sin(t * rings * math.pi)) ** 4 + 3.0 * max(0.0, 0.08 - t)
    wood.add_tube([tuple(p) for p in pts], h * 0.032, h * 0.022, sides=12, radius_fn=ringed)
    trunk_obj = wood.done(f"{name} Trunk", at, "palm bark", smooth=True)
    fronds = Parts()
    bm = fronds.bm
    count = 11
    length = h * 0.42
    for i in range(count):
        ang = 2 * math.pi * i / count + r.uniform(-0.15, 0.15)
        d = Vector((math.cos(ang), math.sin(ang), 0))
        up = r.uniform(0.15, 0.55) if i % 3 else r.uniform(0.6, 0.9)
        steps = 26
        side = d.cross(Vector((0, 0, 1))).normalized()
        spine = [top + d * length * (k / steps) + Vector((0, 0, length * (up * (k / steps) -
                                                                           (0.55 + up * 0.4) * (k / steps) ** 2)))
                 for k in range(steps + 1)]
        # the rib: a thin tapering strip along the spine
        for k in range(steps):
            w0, w1 = 0.03 * (1 - k / steps), 0.03 * (1 - (k + 1) / steps)
            bm.faces.new((bm.verts.new(spine[k] + side * w0), bm.verts.new(spine[k + 1] + side * w1),
                          bm.verts.new(spine[k + 1] - side * w1), bm.verts.new(spine[k] - side * w0)))
        # leaflets: narrow blades off both sides, longest mid-frond, swept forward and drooping
        for k in range(2, steps):
            t = k / steps
            p = spine[k]
            ahead = (spine[min(k + 1, steps)] - spine[k - 1]).normalized()
            blade = length * 0.36 * math.sin(math.pi * min(1.0, t * 1.08)) ** 0.8
            if blade < 0.05:
                continue
            for sgn in (-1, 1):
                out = (side * sgn * 0.8 + ahead * 0.55).normalized()
                tip = p + out * blade + Vector((0, 0, -blade * (0.35 + 0.4 * t)))
                mid = p + out * blade * 0.5 + Vector((0, 0, -blade * 0.12))
                w = blade * 0.07
                bm.faces.new((bm.verts.new(p + ahead * w), bm.verts.new(mid + ahead * w),
                              bm.verts.new(tip), bm.verts.new(mid - ahead * w), bm.verts.new(p - ahead * w)))
    leaf_obj = fronds.done(f"{name} Fronds", at, _leaf_material(leaves, "palm"), smooth=True)
    solid = leaf_obj.modifiers.new("Solidify", "SOLIDIFY")
    solid.thickness = 0.015
    nuts = Parts()
    for i in range(r.randint(3, 5)):
        b = 2 * math.pi * i / 5 + r.uniform(-0.3, 0.3)
        nuts.lump(tuple(top + Vector((math.cos(b) * 0.22, math.sin(b) * 0.22, -0.25))), 0.13, irregularity=0.08,
                  detail=2, seed=seed + i)
    nut_obj = nuts.done(f"{name} Coconuts", at, "#3b2a14", smooth=True)
    return [trunk_obj, leaf_obj, nut_obj]


# ---------- rocks, bushes ----------

def rock(name="Rock", at=None, size=1.0, moss=False, seed=0, count=1, rotation=0, **kw):
    """A natural rock: faceted, weathered, flat where it sits, optionally mossy on top. count > 1 makes a cluster
    of smaller rocks around one big one."""
    size = max(0.1, min(8.0, float(size or 1.0)))
    count = max(1, min(12, int(count or 1)))
    params = dict(size=size, moss=bool(moss), seed=seed, count=count, rotation=rotation)
    at = _here(at)
    r = rng(seed * 13 + 5)   # noqa: F821
    stones = Parts()
    spots = [(0.0, 0.0, size)]
    for i in range(count - 1):
        a = r.uniform(0, 2 * math.pi)
        d = size * r.uniform(0.9, 1.7)
        spots.append((math.cos(a) * d, math.sin(a) * d, size * r.uniform(0.25, 0.55)))
    noise = mathutils.noise
    for i, (x, y, s_) in enumerate(spots):
        verts = stones.lump((0.0, 0.0, 0.0), s_ * 0.6, irregularity=0.42,
                            squash=(r.uniform(1.1, 1.4), 1.0, r.uniform(0.6, 0.8)), detail=3, seed=seed * 17 + i,
                            flat_bottom=0.35)
        off = Vector((seed * 3.1 + i, seed * 1.7, i * 2.3))
        for v in verts:   # sharper, faceted weathering on top of the smooth lump
            v.co += v.co.normalized() * s_ * 0.07 * noise.ridged_multi_fractal(v.co * 2.5 / s_ + off, 0.8, 2.0, 3,
                                                                              1.0, 2.0)
        low = min(v.co.z for v in verts)
        for v in verts:
            v.co += Vector((x, y, -low - s_ * 0.04))
    if moss:
        stones.bm.normal_update()
        for f in stones.bm.faces:
            f.material_index = 1 if f.normal.z > 0.55 else 0
    obj = stones.done(f"{name} Stone", at, "rock", smooth=True)
    if moss:
        obj.data.materials.append(material("moss"))   # noqa: F821
    return _finish_asset(name, "rock", params, [obj], at, rotation,
                         ("a mossy " if moss else "a weathered ") + ("rock" if count == 1 else f"group of {count} rocks"))


def bush(name="Bush", at=None, size=1.0, flowers=None, seed=0, rotation=0, **kw):
    """A leafy bush (size = its height in metres), optionally flowering: flowers='pink'."""
    size = max(0.3, min(4.0, float(size or 1.0)))
    params = dict(size=size, flowers=flowers, seed=seed, rotation=rotation)
    at = _here(at)
    r = rng(seed * 19 + 3)   # noqa: F821
    leaves_p = Parts()
    tops = []
    for i in range(7):
        a = r.uniform(0, 2 * math.pi)
        d = size * r.uniform(0.0, 0.42)
        c = (math.cos(a) * d, math.sin(a) * d, size * r.uniform(0.32, 0.6))
        rad = size * r.uniform(0.3, 0.42)
        leaves_p.lump(c, rad, irregularity=0.35, squash=(1, 1, 0.85), detail=3, seed=seed * 23 + i)
        tops.append((c, rad))
    for v in leaves_p.bm.verts:
        v.co.z = max(v.co.z, 0.02)
    made = [leaves_p.done(f"{name} Leaves", at, "leaves", smooth=True)]
    if flowers and str(flowers).lower() not in ("none", "no", "false"):
        petals = Parts()
        for i in range(int(18 * size) + 8):
            c, rad = r.choice(tops)
            d = Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(0.1, 1))).normalized()
            p = Vector(c) + d * rad * 1.02
            if p.z > 0.15:
                petals.lump(tuple(p), size * 0.035, irregularity=0.1, detail=1, seed=i)
        made.append(petals.done(f"{name} Flowers", at, flowers, smooth=True))
    return _finish_asset(name, "bush", params, made, at, rotation,
                         "a leafy bush" + (f" with {flowers} flowers" if len(made) > 1 else ""))


# ---------- fence ----------

def fence(name="Fence", at=None, length=6.0, height=1.0, color=None, style="picket", rotation=0, **kw):
    """A fence running along x, centred on `at`: posts every ~2 m with caps, rails, and pointed pickets
    (style='picket') or three rails (style='rail'). rotation turns it."""
    length = max(1.0, min(60.0, float(length or 6.0)))
    height = max(0.4, min(2.5, float(height or 1.0)))
    style = "rail" if str(style).lower().startswith("rail") else "picket"
    params = dict(length=length, height=height, color=color, style=style, rotation=rotation)
    at = _here(at)
    wood_mat = color or ("#f2efe8" if style == "picket" else "wood")
    p = Parts()
    spans = max(1, int(round(length / 2.0)))
    post_xs = [-length / 2 + length * i / spans for i in range(spans + 1)]
    for x in post_xs:
        p.box((x, 0, height * 0.55), (0.1, 0.1, height * 1.1))
        p.box((x, 0, height * 1.1 + 0.02), (0.13, 0.13, 0.04))
    for z in ((0.25, 0.7) if style == "picket" else (0.2, 0.5, 0.8)):
        p.box((0, 0.07 if style == "picket" else 0.0, height * z), (length, 0.035 if style == "picket" else 0.06, 0.09))
    if style == "picket":
        n = int(length / 0.13)
        for k in range(n):
            x = -length / 2 + (k + 0.5) * length / n
            if min(abs(x - px) for px in post_xs) < 0.09:
                continue
            p.prism([(x - 0.04, 0.04), (x + 0.04, 0.04), (x + 0.04, height * 0.9), (x, height),
                     (x - 0.04, height * 0.9)], 0.09, 0.112, axis="y")
    obj = p.done(f"{name} Boards", at, wood_mat, bevel=0.005)
    return _finish_asset(name, "fence", params, [obj], at, rotation,
                         f"{_a(round(length))} {round(length)} m {style} fence with capped posts")


# ---------- swimming pool ----------

def pool(name="Pool", at=None, length=8.0, width=4.0, depth=1.5, deck=True, deck_width=1.2, ladder=True,
         water_color=None, tiles=None, deck_color=None, rotation=0, seed=0, **kw):
    """A swimming pool sunk into the ground: a tiled basin with real walls and a floor, clear water a hand below a
    stone coping, a paved deck around it (deck=True) and a steel ladder. `length` runs along x (rotation turns it);
    `at` is the middle of the water at ground level."""
    L = max(2.5, min(30.0, float(length or 8.0)))
    Wd = max(1.8, min(15.0, float(width or 4.0)))
    if Wd > L:
        L, Wd = Wd, L
    Dp = max(0.6, min(3.5, float(depth or 1.5)))
    dw = max(0.4, min(4.0, float(deck_width or 1.2)))
    water = water_color or (kw.get("water") if isinstance(kw.get("water"), str) else None)
    params = dict(length=L, width=Wd, depth=Dp, deck=bool(deck), deck_width=dw, ladder=bool(ladder), water_color=water,
                  tiles=tiles, deck_color=deck_color, rotation=rotation, seed=seed)
    at = _here(at)
    T = 0.25                       # basin wall thickness
    C = 0.25                       # coping overhang outside the walls
    made = []
    basin = Parts()
    basin.ring(L + 2 * T, Wd + 2 * T, T, -Dp, 0.0)
    basin.box((0, 0, -Dp - 0.1), (L + 2 * T, Wd + 2 * T, 0.2))
    made.append(basin.done(f"{name} Basin", at, tiles or "pool tiles"))
    w = Parts()
    w.box((0, 0, (-Dp - 0.12) / 2), (L - 0.004, Wd - 0.004, Dp - 0.12))
    surface = w.done(f"{name} Water", at, None, kind="water")
    surface.data.materials.append(_water_material(water or "#2fb2cc"))
    made.append(surface)
    coping = Parts()
    Lc, Wc = L + 2 * (T + C), Wd + 2 * (T + C)
    coping.ring(Lc, Wc, T + C, 0.0, 0.06)
    made.append(coping.done(f"{name} Coping", at, "travertine", bevel=0.01))
    if deck:
        pavers = Parts()
        bands = [(-(Lc / 2 + dw), -(Wc / 2 + dw), Lc / 2 + dw, -Wc / 2), (-(Lc / 2 + dw), Wc / 2, Lc / 2 + dw, Wc / 2 + dw),
                 (-(Lc / 2 + dw), -Wc / 2, -Lc / 2, Wc / 2), (Lc / 2, -Wc / 2, Lc / 2 + dw, Wc / 2)]
        for x0, y0, x1, y1 in bands:
            nx, ny = max(1, round((x1 - x0) / 0.6)), max(1, round((y1 - y0) / 0.6))
            sx, sy = (x1 - x0) / nx, (y1 - y0) / ny
            for i in range(nx):
                for j in range(ny):
                    pavers.box((x0 + sx * (i + 0.5), y0 + sy * (j + 0.5), 0.02), (sx - 0.02, sy - 0.02, 0.04))
        made.append(pavers.done(f"{name} Deck", at, deck_color or "travertine", bevel=0.006))
    if ladder:
        rails = Parts()
        lx, ly = L / 2 - 0.9, Wd / 2
        for side in (-0.25, 0.25):
            rails.add_tube([(lx + side, ly - 0.14, -1.1), (lx + side, ly - 0.14, 0.45), (lx + side, ly + 0.05, 0.75),
                            (lx + side, ly + 0.3, 0.55), (lx + side, ly + 0.36, 0.06)], 0.024, sides=10)
        for k in range(3):
            rails.box((lx, ly - 0.16, -0.95 + k * 0.3), (0.5, 0.09, 0.03))
        made.append(rails.done(f"{name} Ladder", at, "steel", smooth=True))
    hole = _sink_into_ground(name, at, [(-Lc / 2, -Wc / 2), (Lc / 2, -Wc / 2), (Lc / 2, Wc / 2), (-Lc / 2, Wc / 2)],
                             rotation)
    if hole is not None:
        made.append(hole)
    root = _finish_asset(name, "pool", params, made, at, rotation,
                         f"{_a(round(L))} {round(L)} x {round(Wd)} m swimming pool with a tiled basin, clear water, "
                         "a stone coping" + (", a paved deck" if deck else "") + (" and a steel ladder" if ladder else ""))
    root["jervis_role"] = "sunken"
    return root


def _sink_into_ground(name, at, outline, rotation=0.0, depth=4.0):
    """A sunken thing (a pool, a pond) opens the ground plane it's dug into: a Boolean on each flat ground under it
    subtracts a hidden cutter shaped like `outline` (local (x, y) points), and the cutter becomes part of the thing —
    so moving the pool moves its hole, and deleting or undoing it leaves the ground whole (the modifier then has
    nothing to cut). Nothing is applied: the user's ground mesh itself is never changed. The cutter, or None."""
    at = tuple(at)
    turn = math.radians(float(rotation or 0))
    pts = [(x * math.cos(turn) - y * math.sin(turn), x * math.sin(turn) + y * math.cos(turn)) for x, y in outline]
    lo = (at[0] + min(p[0] for p in pts), at[1] + min(p[1] for p in pts))
    hi = (at[0] + max(p[0] for p in pts), at[1] + max(p[1] for p in pts))
    grounds = []
    for o in _scene().objects:   # noqa: F821
        if o.type != "MESH" or o.name.startswith((name + " ", "__")) or o.name == name or o.get("jervis_asset"):
            continue
        if o.parent is not None and o.parent.get("jervis_asset"):
            continue
        (x0, y0, z0), (x1, y1, z1) = bounds(o)   # noqa: F821
        flat = (z1 - z0) < 0.35 and -0.2 < z1 - at[2] < 0.2
        covers = x0 < hi[0] and x1 > lo[0] and y0 < hi[1] and y1 > lo[1]
        if flat and covers and (x1 - x0) * (y1 - y0) > (hi[0] - lo[0]) * (hi[1] - lo[1]):
            grounds.append(o)
    if not grounds:
        return None
    cut = Parts()
    bottom = [cut.bm.verts.new((x, y, -depth)) for x, y in outline]
    top = [cut.bm.verts.new((x, y, 0.3)) for x, y in outline]
    cut.bm.faces.new(list(reversed(bottom)))
    cut.bm.faces.new(top)
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        cut.bm.faces.new((bottom[i], bottom[j], top[j], top[i]))
    hole = cut.done(f"{name} Ground Cut", at, kind="cutter")
    hole.display_type = "WIRE"
    hole.hide_render = True
    hole.hide_set(True)
    hole["jervis_role"] = "cutter"
    for g in grounds:
        mod = g.modifiers.get(f"Jervis hole {name}") or g.modifiers.new(f"Jervis hole {name}", "BOOLEAN")
        mod.operation, mod.object = "DIFFERENCE", hole
        try:
            mod.solver = "EXACT"
        except Exception:
            pass
    return hole


# ---------- outdoor furniture ----------

def bench(name="Bench", at=None, length=1.6, style="park", color=None, frame_color=None, rotation=0, seed=0, **kw):
    """A bench to sit on, its seat facing -y (rotation turns it): style 'park' (wooden slats on cast-iron side
    frames with armrests and a sloped slatted back) or 'garden' (all wood, square legs, a plain back)."""
    L = max(0.9, min(4.0, float(length or 1.6)))
    style = "garden" if str(style or "").lower().startswith("gard") or str(style).lower() == "simple" else "park"
    params = dict(length=L, style=style, color=color, frame_color=frame_color, rotation=rotation, seed=seed)
    at = _here(at)
    wood = color or "wood"
    frame = frame_color or ("iron" if style == "park" else wood)
    seat_z, made = 0.45, []
    slats = Parts()
    for k in range(5):   # the seat: five boards with gaps, front to back
        slats.box((0, -0.19 + k * 0.095, seat_z), (L, 0.08, 0.03))
    for k in range(3):   # the back: three boards leaning back
        slats.box((0, 0.26 + k * 0.025, 0.62 + k * 0.11), (L - (0.06 if style == "park" else 0.0), 0.022, 0.085),
                  tilt=("x", -14))
    made.append(slats.done(f"{name} Seat", at, wood, bevel=0.008))
    legs = Parts()
    ends = (-(L / 2 - 0.09), L / 2 - 0.09)
    for x in ends:
        if style == "park":   # a cast-iron end: legs, seat rail, a rear post up into the back, an armrest
            legs.beam((x, -0.21, 0.0), (x, -0.19, seat_z - 0.02), 0.05)
            legs.beam((x, 0.21, 0.0), (x, 0.19, seat_z - 0.02), 0.05)
            legs.beam((x, 0.19, seat_z - 0.02), (x, 0.3, 0.92), 0.045)
            legs.beam((x, -0.24, seat_z - 0.03), (x, 0.23, seat_z - 0.03), 0.045, 0.04)
            legs.beam((x, -0.22, seat_z), (x, -0.22, 0.66), 0.04)
            legs.beam((x, -0.26, 0.67), (x, 0.24, 0.7), 0.05, 0.035)
            legs.box((x, -0.21, 0.015), (0.09, 0.12, 0.03))
            legs.box((x, 0.21, 0.015), (0.09, 0.12, 0.03))
        else:
            for y in (-0.18, 0.18):
                legs.box((x, y, (seat_z - 0.015) / 2), (0.06, 0.06, seat_z - 0.015))
            legs.box((x, 0.27, 0.62), (0.05, 0.05, 0.5))
            legs.box((x, 0.0, seat_z - 0.05), (0.05, 0.42, 0.05))
    if style == "garden":
        legs.box((0, 0.0, 0.12), (L - 0.2, 0.04, 0.05))   # a stretcher between the ends
    made.append(legs.done(f"{name} Frame", at, frame, bevel=0.006))
    return _finish_asset(name, "bench", params, made, at, rotation,
                         f"a {L:.1f} m {'park bench with cast-iron ends and wooden slats' if style == 'park' else 'wooden garden bench'}")


def lounger(name="Sun Lounger", at=None, color=None, cushion="#f2efe6", rotation=0, seed=0, **kw):
    """A sun lounger: a slatted wooden bed on legs, its head end raised, with a cushion and two small wheels. Its
    foot faces -y (rotation turns it)."""
    params = dict(color=color, cushion=cushion, rotation=rotation, seed=seed)
    at = _here(at)
    wood = color or "light wood"
    L, W, Z = 2.0, 0.7, 0.3
    frame = Parts()
    for x in (-W / 2 + 0.03, W / 2 - 0.03):
        frame.beam((x, -L / 2, Z), (x, L * 0.15, Z), 0.05, 0.08)            # the side rails
        for y in (-L / 2 + 0.1, L * 0.1):
            frame.box((x, y, Z / 2), (0.05, 0.05, Z))                        # legs
    frame.beam((-W / 2 + 0.03, -L / 2 + 0.02, Z), (W / 2 - 0.03, -L / 2 + 0.02, Z), 0.05, 0.08)
    for k in range(13):   # the flat bed's slats
        frame.box((0, -L / 2 + 0.07 + k * 0.1, Z + 0.05), (W - 0.1, 0.07, 0.02))
    back_len, angle = L * 0.35, 35
    for k in range(6):    # the raised head end
        t = 0.06 + k * (back_len - 0.08) / 5
        y = L * 0.15 + t * math.cos(math.radians(angle))
        z = Z + 0.05 + t * math.sin(math.radians(angle))
        frame.box((0, y, z), (W - 0.1, 0.07, 0.02), tilt=("x", angle))
    for x in (-W / 2 + 0.03, W / 2 - 0.03):
        frame.beam((x, L * 0.15, Z + 0.04), (x, L * 0.15 + back_len * math.cos(math.radians(angle)),
                                             Z + 0.04 + back_len * math.sin(math.radians(angle))), 0.04)
    made = [frame.done(f"{name} Bed", at, wood, bevel=0.006)]
    pad = Parts()
    pad.box((0, -L / 2 + 0.05 + (L * 0.65 - 0.05) / 2, Z + 0.1), (W - 0.12, L * 0.65 - 0.08, 0.07))
    mid = back_len / 2
    pad.box((0, L * 0.15 + mid * math.cos(math.radians(angle)) - 0.03,
             Z + 0.1 + mid * math.sin(math.radians(angle))), (W - 0.12, back_len - 0.05, 0.07), tilt=("x", angle))
    cushion_obj = pad.done(f"{name} Cushion", at, cushion or "fabric", bevel=0.025, segments=3)
    made.append(cushion_obj)
    wheels = Parts()
    for x in (-W / 2 - 0.02, W / 2 + 0.02):
        wheels.cylinder((x, L * 0.1 + 0.02, 0.07), 0.07, 0.04, segments=16, axis="x")
    made.append(wheels.done(f"{name} Wheels", at, "rubber", smooth=True))
    return _finish_asset(name, "lounger", params, made, at, rotation,
                         "a wooden sun lounger with a raised back, a cushion and wheels")


# ---------- car, garage, gate: what a driveway is made of ----------

def car(name="Car", at=None, color=None, length=4.4, rotation=0, **kw):
    """A car: a bevelled body, a tinted glasshouse with a roof, four wheels that turn (each its own object, its
    centre at the axle, so drive() rolls them), headlights, tail lights and bumpers. Its front faces +x
    (rotation turns it); drive() always drives it forwards."""
    L = max(3.2, min(5.6, float(length or 4.4)))
    W, R = 0.41 * L, 0.075 * L + 0.01                   # 1.8 m wide, 0.34 m wheels for a 4.4 m car
    params = dict(color=color, length=L, rotation=rotation)
    at = _here(at)
    paint = color or "#b3221d"
    made = []
    body = Parts()
    body.box((0, 0, R + 0.28), (L, W, 0.56))                                   # sills to shoulders
    made.append(body.done(f"{name} Body", at, paint, bevel=0.06))
    glass = Parts()
    x0, x1 = -0.33 * L, 0.2 * L                                                # the glasshouse, sloped front and back
    glass.prism([(x0, R + 0.55), (x1, R + 0.55), (x1 - 0.42, R + 1.0), (x0 + 0.3, R + 1.0)], -W / 2 + 0.12,
                W / 2 - 0.12, axis="y")
    made.append(glass.done(f"{name} Windows", at, "#1d2a33", bevel=0.02))
    top = Parts()
    top.box(((x0 + 0.3 + x1 - 0.42) / 2, 0, R + 1.02), (x1 - 0.42 - x0 - 0.3 + 0.08, W - 0.2, 0.05))
    made.append(top.done(f"{name} Top", at, paint, bevel=0.02))
    trim = Parts()
    for x in (-L / 2 - 0.02, L / 2 + 0.02):
        trim.box((x, 0, R + 0.08), (0.12, W + 0.02, 0.16))                     # bumpers
    made.append(trim.done(f"{name} Bumpers", at, "#202022", bevel=0.03))
    lamps = Parts()
    for y in (-W / 2 + 0.3, W / 2 - 0.3):
        lamps.box((L / 2 + 0.005, y, R + 0.38), (0.04, 0.34, 0.12))
    made.append(lamps.done(f"{name} Headlights", at, "#fff6d6"))
    tails = Parts()
    for y in (-W / 2 + 0.25, W / 2 - 0.25):
        tails.box((-L / 2 - 0.005, y, R + 0.4), (0.04, 0.3, 0.1))
    made.append(tails.done(f"{name} Tail Lights", at, "#c4100c"))
    axle = 0.31 * L
    for i, (x, y) in enumerate(((axle, -W / 2 + 0.12), (axle, W / 2 - 0.12), (-axle, -W / 2 + 0.12),
                                (-axle, W / 2 - 0.12)), 1):
        wheel = Parts()   # centred on its own axle: its origin is where it turns
        wheel.cylinder((0, 0.12, 0), R, 0.24, segments=20, axis="y")          # (an y-cylinder runs from base to -y)
        wheel.cylinder((0, -0.11 if y < 0 else 0.13, 0), R * 0.55, 0.02, segments=16, axis="y")   # the hub, outside
        made.append(wheel.done(f"{name} Wheel {i}", (at[0] + x, at[1] + y, at[2] + R), "rubber", smooth=True))
    said = str(color) if color and not str(color).startswith("#") else ("red" if color is None else "")
    root = _finish_asset(name, "car", params, made, at, rotation, f"a {said + ' ' if said else ''}car "
                         f"{L:.1f} m long, with a tinted glasshouse, headlights and four wheels that turn")
    root["jervis_front_axis"] = 0.0   # degrees, in its own frame: its nose points along +x
    return root


def garage(name="Garage", at=None, width=3.6, depth=6.5, height=2.7, walls=None, door_color=None, rotation=0,
           **kw):
    """A garage: plastered walls round a concrete floor, a flat roof, and a panelled up-and-over door across the
    front (-y; rotation turns it) — open_door() swings it up under the roof. width 3.6 for one car, 6 for two."""
    W = max(2.8, min(9.0, float(width or 3.6)))
    D = max(4.5, min(9.0, float(depth or 6.5)))
    H = max(2.3, min(4.0, float(height or 2.7)))
    params = dict(width=W, depth=D, height=H, walls=walls, door_color=door_color, rotation=rotation)
    at = _here(at)
    made = []
    door_w, door_h = W - 0.8, min(H - 0.35, 2.25)
    shell = Parts()
    shell.ring(W, D, 0.2, 0.0, H)
    walls_obj = shell.done(f"{name} Walls", at, walls or "plaster")
    _cut_boxes(walls_obj, [((0, -D / 2, door_h / 2), (door_w, 0.8, door_h))])
    made.append(walls_obj)
    roof = Parts()
    roof.box((0, 0, H + 0.08), (W + 0.3, D + 0.3, 0.16))
    roof.box((0, -D / 2 - 0.13, H + 0.2), (W + 0.3, 0.04, 0.1))                # a fascia board at the front
    made.append(roof.done(f"{name} Roof", at, "concrete", bevel=0.01))
    floor = Parts()
    floor.box((0, 0, 0.03), (W - 0.4, D - 0.4, 0.06))
    floor.box((0, -D / 2 - 0.6, 0.02), (door_w + 0.4, 1.2, 0.04))              # an apron in front of the door
    made.append(floor.done(f"{name} Floor", at, "concrete"))
    door = Parts()
    door.box((0, -D / 2 + 0.06, door_h / 2), (door_w - 0.04, 0.05, door_h - 0.02))
    for k in range(1, 4):   # the panels' seams
        door.box((0, -D / 2 + 0.03, door_h * k / 4), (door_w - 0.1, 0.02, 0.04))
    door_obj = door.done(f"{name} Door", at, door_color or "#d9d6cf", bevel=0.005)
    door_obj["jervis_door"] = "up"   # an up-and-over door: open_door() lifts it, it never swings sideways
    made.append(door_obj)
    return _finish_asset(name, "garage", params, made, at, rotation,
                         f"a {W:.1f} by {D:.1f} m garage with a flat roof and an up-and-over door")


def gate(name="Gate", at=None, width=3.6, height=1.5, color=None, style="bars", rotation=0, **kw):
    """A driveway gate: two posts and two leaves (each its own object) of a framed panel with bars (style 'bars')
    or boards ('boards'), across an opening `width` wide facing -y (rotation turns it). open_door() swings both
    leaves open on their posts, in toward the property."""
    Wd = max(1.0, min(8.0, float(width or 3.6)))
    Hg = max(0.8, min(2.5, float(height or 1.5)))
    style = "boards" if str(style or "").lower().startswith(("board", "wood")) else "bars"
    params = dict(width=Wd, height=Hg, color=color, style=style, rotation=rotation)
    at = _here(at)
    made = []
    posts = Parts()
    for x in (-Wd / 2 - 0.14, Wd / 2 + 0.14):
        posts.box((x, 0, (Hg + 0.35) / 2), (0.26, 0.26, Hg + 0.35))
        posts.box((x, 0, Hg + 0.37), (0.32, 0.32, 0.05))                       # caps
    made.append(posts.done(f"{name} Posts", at, "stone" if style == "bars" else "dark wood", bevel=0.01))
    finish = color or ("#2b2b2e" if style == "bars" else "wood")
    leaf_w = Wd / 2 - 0.02
    for i, side in enumerate((-1, 1), 1):
        cx = side * (Wd / 4)
        leaf = Parts()
        z0, z1 = 0.08, Hg
        for z in (z0 + 0.03, z1 - 0.03):
            leaf.box((cx, 0, z), (leaf_w, 0.06, 0.06))                         # top and bottom rails
        for x in (cx - leaf_w / 2 + 0.03, cx + leaf_w / 2 - 0.03):
            leaf.box((x, 0, (z0 + z1) / 2), (0.06, 0.06, z1 - z0))             # stiles
        if style == "bars":
            n = max(3, int(leaf_w / 0.14))
            for k in range(1, n):
                leaf.box((cx - leaf_w / 2 + k * leaf_w / n, 0, (z0 + z1) / 2), (0.025, 0.025, z1 - z0 - 0.06))
        else:
            n = max(3, int(leaf_w / 0.16))
            for k in range(n):
                leaf.box((cx - leaf_w / 2 + 0.06 + (k + 0.5) * (leaf_w - 0.12) / n, 0, (z0 + z1) / 2),
                         ((leaf_w - 0.12) / n - 0.015, 0.035, z1 - z0 - 0.06))
        obj = leaf.done(f"{name} Leaf {i}", at, finish, bevel=0.005)
        obj["jervis_door"] = "leaf"   # one of a pair: open_door() swings each on its own post
        made.append(obj)
    return _finish_asset(name, "gate", params, made, at, rotation,
                         f"a {Wd:.1f} m driveway gate with two {'barred' if style == 'bars' else 'boarded'} leaves "
                         "on stone posts")


# ---------- fountain ----------

def fountain(name="Fountain", at=None, size=3.0, tiers=2, color=None, water_color=None, rotation=0, **kw):
    """A stone fountain: a round basin with a moulded rim and water in it, a turned pedestal carrying an upper bowl
    (tiers=2, or a third smaller one), water in each bowl and a jet rising from the top. size = the basin's width."""
    S = max(1.0, min(12.0, float(size or 3.0)))
    tiers = max(1, min(3, int(tiers or 2)))
    params = dict(size=S, tiers=tiers, color=color, water_color=water_color, rotation=rotation)
    at = _here(at)
    stone = color or "stone"
    R = S / 2
    made = []
    rim = 0.45 * min(1.4, max(0.7, S / 3))
    made.append(lathe(f"{name} Basin", [(R, 0), (R + 0.06, 0.06), (R + 0.06, rim - 0.06), (R, rim), (R - 0.18, rim),   # noqa: F821
                                        (R - 0.18, 0.12), (0, 0.12)], at=at, color=stone, segments=48))
    pools = Parts()
    pools.cylinder((0, 0, rim - 0.12), R - 0.19, 0.02, segments=48)
    top, bowl_r = 0.12, R * 0.48
    stem = []
    for k in range(tiers - 1):   # each tier: a turned pedestal, then a bowl
        h = 0.95 * (0.85 ** k) * min(1.3, max(0.8, S / 3))
        stem += [(0.22 * (0.8 ** k), top), (0.17 * (0.8 ** k), top + h * 0.15), (0.12 * (0.8 ** k), top + h * 0.7),
                 (0.2 * (0.8 ** k), top + h)]
        z = top + h
        made.append(lathe(f"{name} Bowl {k + 1}", [(0, z), (0.18, z), (bowl_r, z + 0.18), (bowl_r + 0.04, z + 0.26),   # noqa: F821
                                                     (bowl_r - 0.05, z + 0.26), (0.14, z + 0.1), (0, z + 0.1)],
                          at=at, color=stone, segments=40))
        pools.cylinder((0, 0, z + 0.2), bowl_r - 0.06, 0.02, segments=40)
        top, bowl_r = z + 0.1, bowl_r * 0.6
    stem += [(0.1, top + 0.15), (0.0, top + 0.28)]
    made.append(lathe(f"{name} Pedestal", [(0.3, 0.12)] + stem, at=at, color=stone, segments=32))   # noqa: F821
    jet = Parts()
    jet.add_tube([(0, 0, top + 0.25), (0, 0, top + 0.55), (0, 0, top + 0.75)], 0.035, radius_end=0.012, sides=10)
    water = pools.done(f"{name} Water", at, None, kind="water", smooth=True)
    water.data.materials.append(_water_material(water_color or "#3d8fa0"))
    spout = jet.done(f"{name} Jet", at, None, kind="water", smooth=True)
    spout.data.materials.append(_water_material(water_color or "#cfe7ee"))
    made += [water, spout]
    return _finish_asset(name, "fountain", params, made, at, rotation,
                         f"{_a(round(S))} {round(S)} m stone fountain with {'a bowl' if tiers == 2 else f'{tiers - 1} bowls'}"
                         " on a turned pedestal, water and a jet")


# ---------- garden pond ----------

def pond(name="Pond", at=None, size=4.0, depth=0.6, rocks=True, reeds=True, water_color=None, seed=0, rotation=0,
         **kw):
    """A natural garden pond sunk into the ground: an irregular outline, a bank sloping down under clear water a
    hand below the ground, stones round its edge and clumps of reeds. size = its length in metres."""
    S = max(1.2, min(30.0, float(size or 4.0)))
    Dp = max(0.2, min(2.0, float(depth or 0.6)))
    params = dict(size=S, depth=Dp, rocks=bool(rocks), reeds=bool(reeds), water_color=water_color, seed=seed,
                  rotation=rotation)
    at = _here(at)
    r = rng(seed * 29 + 7)   # noqa: F821
    n = 36
    off = r.uniform(0, 100)
    outline = []
    for i in range(n):
        a = 2 * math.pi * i / n
        k = 1 + 0.16 * mathutils.noise.noise(Vector((math.cos(a) * 1.3 + off, math.sin(a) * 1.3, 0.5)))
        outline.append((math.cos(a) * S / 2 * k, math.sin(a) * S * 0.36 * k))
    made = []
    basin = Parts()
    rings = []
    for frac, z in ((1.12, 0.02), (1.0, 0.0), (0.82, -0.3 * Dp), (0.5, -0.8 * Dp), (0.2, -Dp)):
        rings.append([basin.bm.verts.new((x * frac, y * frac, z)) for x, y in outline])
    bottom = basin.bm.verts.new((0, 0, -Dp - 0.02))
    for ra, rb in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            basin.bm.faces.new((ra[i], ra[j], rb[j], rb[i]))
    for i in range(n):
        basin.bm.faces.new((rings[-1][i], rings[-1][(i + 1) % n], bottom))
    made.append(basin.done(f"{name} Bed", at, "dirt", smooth=True))
    w = Parts()
    top = [w.bm.verts.new((x * 0.86, y * 0.86, -0.1)) for x, y in outline]
    w.bm.faces.new(top)
    surface = w.done(f"{name} Water", at, None, kind="water", smooth=True)
    surface.data.materials.append(_water_material(water_color or "#2c5f5a"))
    made.append(surface)
    if rocks:
        stones = Parts()
        k = 0
        for i in range(0, n, 2):
            if r.random() < 0.25:
                continue
            x, y = outline[i]
            s_ = r.uniform(0.14, 0.3) * min(1.5, max(0.7, S / 4))
            stones.lump((x * 1.04, y * 1.04, -s_ * 0.35), s_, irregularity=0.35, squash=(1.2, 1.0, 0.7), detail=2,
                        seed=seed * 41 + k, flat_bottom=0.3)
            k += 1
        made.append(stones.done(f"{name} Stones", at, "rock", smooth=True))
    if reeds:
        blades = Parts()
        for c in range(3):
            i = int(r.uniform(0, n))
            cx, cy = outline[i][0] * 0.95, outline[i][1] * 0.95
            for b in range(9):
                bx, by = cx + r.uniform(-0.25, 0.25), cy + r.uniform(-0.25, 0.25)
                h = r.uniform(0.6, 1.2)
                lean = (r.uniform(-0.15, 0.15), r.uniform(-0.15, 0.15))
                blades.add_tube([(bx, by, -0.12), (bx + lean[0] * 0.4, by + lean[1] * 0.4, h * 0.5),
                                 (bx + lean[0], by + lean[1], h)], 0.012, radius_end=0.004, sides=5)
        made.append(blades.done(f"{name} Reeds", at, "grass", smooth=True))
    hole = _sink_into_ground(name, at, [(x * 0.95, y * 0.95) for x, y in outline], rotation)
    if hole is not None:
        made.append(hole)
    root = _finish_asset(name, "pond", params, made, at, rotation,
                         f"{_a(round(S))} {round(S)} m garden pond with a sloping bank, clear water"
                         + (", stones round its edge" if rocks else "") + (" and reeds" if reeds else ""))
    root["jervis_role"] = "sunken"
    return root


# ---------- paths that really connect two places ----------

def _ribbon(parts, pts, half, z0, z1, zs=None):
    """A flat strip `half`*2 wide along 2D points (mitred at the bends), from z0 to z1 above each point's zs."""
    n = len(pts)
    zs = zs or [0.0] * n
    left, right = [], []
    for i, (x, y) in enumerate(pts):
        if i == 0 or i == n - 1:
            a, b = (pts[0], pts[1]) if i == 0 else (pts[-2], pts[-1])
            d = Vector((b[0] - a[0], b[1] - a[1], 0)).normalized()
            nrm, k = Vector((-d.y, d.x, 0)), 1.0
        else:
            d1 = Vector((x - pts[i - 1][0], y - pts[i - 1][1], 0)).normalized()
            d2 = Vector((pts[i + 1][0] - x, pts[i + 1][1] - y, 0)).normalized()
            n1, n2 = Vector((-d1.y, d1.x, 0)), Vector((-d2.y, d2.x, 0))
            nrm = (n1 + n2).normalized() if (n1 + n2).length > 1e-6 else n1
            k = 1.0 / max(0.4, nrm.dot(n1))
        left.append((x + nrm.x * half * k, y + nrm.y * half * k))
        right.append((x - nrm.x * half * k, y - nrm.y * half * k))
    bm = parts.bm
    rows = []
    for i in range(n):
        lb = bm.verts.new((left[i][0], left[i][1], zs[i] + z0))
        rb = bm.verts.new((right[i][0], right[i][1], zs[i] + z0))
        rt = bm.verts.new((right[i][0], right[i][1], zs[i] + z1))
        lt = bm.verts.new((left[i][0], left[i][1], zs[i] + z1))
        rows.append((lb, rb, rt, lt))
    for i in range(n - 1):
        a, b = rows[i], rows[i + 1]
        for f in ((a[3], a[2], b[2], b[3]), (a[0], b[0], b[1], a[1]), (a[0], a[3], b[3], b[0]), (a[1], b[1], b[2], a[2])):
            bm.faces.new(f)
    bm.faces.new(rows[0])
    bm.faces.new(tuple(reversed(rows[-1])))


def _offset_line(pts, off):
    """The 2D line `pts` moved `off` metres to its left (negative: right), with mitred corners."""
    out, n = [], len(pts)
    for i, (x, y) in enumerate(pts):
        if i == 0 or i == n - 1:
            a, b = (pts[0], pts[1]) if i == 0 else (pts[-2], pts[-1])
            d = Vector((b[0] - a[0], b[1] - a[1], 0)).normalized()
            m, k = Vector((-d.y, d.x, 0)), 1.0
        else:
            d1 = Vector((x - pts[i - 1][0], y - pts[i - 1][1], 0)).normalized()
            d2 = Vector((pts[i + 1][0] - x, pts[i + 1][1] - y, 0)).normalized()
            n1, n2 = Vector((-d1.y, d1.x, 0)), Vector((-d2.y, d2.x, 0))
            m = (n1 + n2).normalized() if (n1 + n2).length > 1e-6 else n1
            k = 1.0 / max(0.4, m.dot(n1))
        out.append((x + m.x * off * k, y + m.y * off * k))
    return out


def _slabs(parts, pts, zs, half, z0, z1, step=0.7, joint=0.035):
    """Paving slabs tiling a strip `half`*2 wide along 2D points: cut across about every `step` metres and along the
    mitre at every bend, each slab a joint smaller than its cell — so bends tile cleanly instead of overlapping."""
    n = len(pts)

    def mitre(i):
        x, y = pts[i]
        if i == 0 or i == n - 1:
            a, b = (pts[0], pts[1]) if i == 0 else (pts[-2], pts[-1])
            d = Vector((b[0] - a[0], b[1] - a[1], 0)).normalized()
            return Vector((-d.y, d.x, 0)), 1.0
        d1 = Vector((x - pts[i - 1][0], y - pts[i - 1][1], 0)).normalized()
        d2 = Vector((pts[i + 1][0] - x, pts[i + 1][1] - y, 0)).normalized()
        n1, n2 = Vector((-d1.y, d1.x, 0)), Vector((-d2.y, d2.x, 0))
        m = (n1 + n2).normalized() if (n1 + n2).length > 1e-6 else n1
        return m, 1.0 / max(0.4, m.dot(n1))

    stations = []   # (point, across, mitre factor, z)
    for i in range(n - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1e-6:
            continue
        cuts = max(1, round(length / step))
        across = Vector((-(y1 - y0) / length, (x1 - x0) / length, 0))
        for c in range(cuts):
            t = c / cuts
            nrm, k = mitre(i) if c == 0 else (across, 1.0)
            stations.append((Vector((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, 0)), nrm, k,
                             zs[i] + (zs[i + 1] - zs[i]) * t))
    end_nrm, end_k = mitre(n - 1)
    stations.append((Vector((pts[-1][0], pts[-1][1], 0)), end_nrm, end_k, zs[-1]))
    bm = parts.bm
    for (pa, na, ka, za), (pb, nb, kb, zb) in zip(stations, stations[1:]):
        corners = [(pa + na * half * ka, za), (pa - na * half * ka, za), (pb - nb * half * kb, zb),
                   (pb + nb * half * kb, zb)]
        mid = sum((c for c, _ in corners), Vector((0, 0, 0))) / 4
        shrunk = []
        for c, z in corners:
            gap_ = (mid - c).length
            shrunk.append((c + (mid - c) * min(0.45, joint / max(gap_, 1e-6)), z))
        low = [bm.verts.new((c.x, c.y, z + z0)) for c, z in shrunk]
        high = [bm.verts.new((c.x, c.y, z + z1)) for c, z in shrunk]
        bm.faces.new(low[::-1])
        bm.faces.new(high)
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new((low[i], low[j], high[j], high[i]))


_WALKWAY_START = ("start", "from_", "frm", "source", "start_point", "begin", "a", "origin", "from_obj")
_WALKWAY_END = ("end", "to", "target", "destination", "end_point", "dest", "b", "to_obj", "goal")


def walkway(*args, **kw):
    """A path that really connects two places: walkway(name, start, end, width=1.2, style='pavers').
    start/end: things ('Villa' = from just outside its front door, 'Pool' = to its nearest edge) or (x, y) points;
    with no start it leaves the building in the scene. It's routed around buildings and everything else in the way,
    leaves a door square-on and arrives square at its target. style: 'pavers' (paving slabs on a gravel bed, with
    edging), 'stones' (stepping stones) or 'gravel'. Forgiving about how it's called: walkway('Path', 'Villa',
    'Pool'), walkway('Path', start='Villa', to='Pool'), walkway(name='Path', from_='Villa', end=(10, 2))."""
    args = list(args)
    name = kw.pop("name", None) or (args.pop(0) if args and isinstance(args[0], str) and not _is_thing_name(args[0])
                                     else "Path")
    start = next((kw.pop(k) for k in _WALKWAY_START if k in kw), None)
    end = next((kw.pop(k) for k in _WALKWAY_END if k in kw), None)
    if end is None and args:
        end = args.pop(-1) if (start is not None or len(args) == 1) else None
    if start is None and args:
        start = args.pop(0)
    if end is None and args:
        end = args.pop(0)
    return _walkway(name, start, end, **kw)


def _is_thing_name(text):
    """walkway('Villa', 'Pool') with no name of its own: the first word is a place, not the path's name."""
    try:
        return get(text) is not None and not str(text).lower().startswith(("path", "walk", "drive", "trail"))  # noqa: F821
    except KeyError:
        return False


def _walkway(name="Path", start=None, end=None, width=1.2, color=None, style="pavers", edging=True, points=None,
             **kw):
    width = max(0.5, min(4.0, float(width or 1.2)))
    style = str(style or "pavers").lower()
    style = "stones" if style.startswith("ston") or "stepping" in style else "gravel" if style.startswith("grav") \
        else "pavers"
    ts = scene_things()   # noqa: F821
    ts = [t for t in ts if t["name"] != name]
    a_t = b_t = None
    if points:
        route_pts = [(float(p[0]), float(p[1])) for p in points]
    else:
        if end is None:
            raise ValueError("walkway() needs an end: walkway('Path', 'Villa', 'Pool').")
        if not isinstance(end, (tuple, list, Vector)):
            b_t = _thing(end, ts)   # noqa: F821
        if start is None:
            homes = [t for t in ts if t["category"] == "building" and t is not b_t]
            if not homes:
                raise ValueError("walkway(): say where it starts (a building, a thing or an (x, y) point).")
            a_t = homes[0]
        elif not isinstance(start, (tuple, list, Vector)):
            a_t = _thing(start, ts)   # noqa: F821
        if a_t is not None and b_t is not None and a_t["name"] == b_t["name"]:
            raise ValueError(f"walkway(): the start and the end are both {a_t['name']!r}.")
        if a_t is not None and b_t is not None:
            s, sdir, e, edir = spatial.path_ends(a_t, b_t)   # noqa: F821
        else:
            e_pt = (float(end[0]), float(end[1])) if b_t is None else None
            s_pt = (float(start[0]), float(start[1])) if a_t is None else None
            if a_t is not None:
                s, sdir = (spatial.entrance(a_t), a_t["front"]) if a_t["category"] == "building" else \
                    spatial._edge_point(a_t["outer"], e_pt)   # noqa: F821
            else:
                s, sdir = s_pt, None
            if b_t is not None:
                e, out = spatial._edge_point(b_t["outer"], s)   # noqa: F821
                edir = (-out[0], -out[1])
            else:
                e, edir = e_pt, None
        keep_clear = [t for t in ts if t is not a_t and t is not b_t]
        route_pts = spatial.route(s, e, keep_clear + [t for t in (a_t, b_t) if t is not None], width=width,   # noqa: F821
                                  start_dir=sdir, end_dir=edir)
    if len(route_pts) < 2:
        raise ValueError("walkway() needs two different points.")
    ox, oy = route_pts[0]
    oz = ground_height(ox, oy)
    local = [(x - ox, y - oy) for x, y in route_pts]
    zs = [ground_height(x, y) - oz for x, y in route_pts]
    at = (ox, oy, oz)
    made = []
    bed = Parts()
    _ribbon(bed, local, width / 2 + (0.05 if style != "stones" else -0.1), -0.02, 0.025 if style != "gravel" else 0.05,
            zs)
    made.append(bed.done(f"{name} Bed", at, "gravel" if style != "stones" else "grass"))
    total, seg = 0.0, []
    for (x0, y0), (x1, y1) in zip(local, local[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        seg.append((total, length, x0, y0, x1, y1))
        total += length
    if style == "pavers":
        stones = Parts()
        _slabs(stones, local, zs, width / 2 - 0.04, 0.025, 0.075, step=0.7, joint=0.035)
        made.append(stones.done(f"{name} Pavers", at, color or "pavers", bevel=0.006))
    elif style == "stones":
        stones = Parts()
        r = rng(len(route_pts) * 7 + int(total * 10))   # noqa: F821
        k, dist, step = 0, 0.31, 0.62
        while dist < total - 0.15:
            s0, length, x0, y0, x1, y1 = next(sg for sg in seg if sg[0] <= dist <= sg[0] + sg[1] + 1e-9)
            t = (dist - s0) / max(1e-9, length)
            px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            pz = zs[seg.index((s0, length, x0, y0, x1, y1))]
            stones.lump((px + r.uniform(-0.08, 0.08), py + r.uniform(-0.08, 0.08), pz),
                        min(0.34, width * 0.3) * r.uniform(0.85, 1.05), irregularity=0.3,
                        squash=(r.uniform(1.0, 1.25), 0.9, 0.12), detail=2, seed=k, flat_bottom=0.5)
            k += 1
            dist += step
        made.append(stones.done(f"{name} Stones", at, color or "stone", bevel=0.008))
    if edging and style != "stones":
        edge = Parts()
        for sign in (-1, 1):   # each kerb is the path's line moved sideways, mitred at the bends
            _ribbon(edge, _offset_line(local, sign * (width / 2 + 0.06)), 0.04, -0.02, 0.09, zs)
        made.append(edge.done(f"{name} Edging", at, "concrete", bevel=0.01))
    if a_t is not None and a_t.get("asset_type") == "house":
        # The walkway leaves the house's door: the house's own short stepping-stone path would run alongside it.
        own = bpy.data.objects.get(f"{a_t['name']} Path")
        house_root = bpy.data.objects.get(a_t["name"])
        if own is not None and own.users_collection:
            trash(own.name)   # noqa: F821  (undoable, like every removal)
            STEP.setdefault("retired", []).append(own.name)   # noqa: F821  (on purpose: not "lost")
            if house_root is not None and house_root.get("jervis_asset"):
                info = json.loads(house_root["jervis_asset"])
                info["params"]["path"] = False   # a rebuild ("bigger windows") mustn't bring it back
                house_root["jervis_asset"] = json.dumps(info)
    root = assemble(name, [m.name for m in made if m is not None], at=at)   # noqa: F821
    root["jervis_role"] = "path"
    root["jervis_path"] = json.dumps({"from": a_t["name"] if a_t else None, "to": b_t["name"] if b_t else None,
                                      "width": width, "style": style,
                                      "points": [list(p) for p in route_pts]})
    root["jervis_summary"] = (f"{_a(round(total))} {round(total)} m {style if style != 'pavers' else 'paved'} path"
                              + (f" from {a_t['name']}" if a_t else "") + (f" to {b_t['name']}" if b_t else ""))
    _select(root)   # noqa: F821
    return root


# ---------- terrain and water ----------

def _smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def _terrain_material(name, sand_to=0.45, grass_from=0.85):
    """Sand along the shore (darker where it's wet, under the water), grass above it, bare rock on steep slopes,
    with natural mottling: driven by the terrain's own height and slope, so it fits whatever shape was made."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    for n in list(nodes):
        if n.type != "OUTPUT_MATERIAL":
            nodes.remove(n)
    out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    coords = nodes.new("ShaderNodeTexCoord")
    geo = nodes.new("ShaderNodeNewGeometry")
    split = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords.outputs["Object"], split.inputs["Vector"])
    mottle = nodes.new("ShaderNodeTexNoise")
    mottle.inputs["Scale"].default_value = 0.35
    mottle.inputs["Detail"].default_value = 6.0
    links.new(coords.outputs["Object"], mottle.inputs["Vector"])
    # height (with a little noise so the sand/grass line isn't ruler-straight) -> colour
    wobble = nodes.new("ShaderNodeMath")
    wobble.operation = "MULTIPLY_ADD"
    links.new(mottle.outputs["Fac"], wobble.inputs[0])
    wobble.inputs[1].default_value = 0.5
    links.new(split.outputs["Z"], wobble.inputs[2])
    height = nodes.new("ShaderNodeMapRange")
    links.new(wobble.outputs["Value"], height.inputs["Value"])
    height.inputs["From Min"].default_value = -1.0
    height.inputs["From Max"].default_value = grass_from + 1.5
    ramp = nodes.new("ShaderNodeValToRGB")
    links.new(height.outputs["Result"], ramp.inputs["Fac"])
    span = grass_from + 2.5
    stops = [(0.0, (0.2, 0.2, 0.14)), ((1.0 + 0.0) / span, (0.5, 0.43, 0.27)),
             ((1.0 + sand_to) / span, (0.6, 0.5, 0.31)), ((1.0 + grass_from) / span, (0.16, 0.3, 0.07)),
             (1.0, (0.1, 0.24, 0.05))]
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[0].color = stops[0][0], (*stops[0][1], 1)
    ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = stops[-1][0], (*stops[-1][1], 1)
    for pos, rgb in stops[1:-1]:
        el = ramp.color_ramp.elements.new(min(0.99, max(0.01, pos)))
        el.color = (*rgb, 1)
    # steep ground is bare rock (above the beach)
    slope = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geo.outputs["Normal"], slope.inputs["Vector"])
    steep = nodes.new("ShaderNodeMapRange")
    links.new(slope.outputs["Z"], steep.inputs["Value"])
    steep.inputs["From Min"].default_value = 0.86
    steep.inputs["From Max"].default_value = 0.74
    above = nodes.new("ShaderNodeMapRange")
    links.new(split.outputs["Z"], above.inputs["Value"])
    above.inputs["From Min"].default_value = sand_to
    above.inputs["From Max"].default_value = sand_to + 0.4
    rocky = nodes.new("ShaderNodeMath")
    rocky.operation = "MULTIPLY"
    links.new(steep.outputs["Result"], rocky.inputs[0])
    links.new(above.outputs["Result"], rocky.inputs[1])
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    links.new(rocky.outputs["Value"], mix.inputs["Factor"])
    links.new(ramp.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = (0.24, 0.22, 0.2, 1)
    # mottling: grass and sand are never one flat colour
    shade = nodes.new("ShaderNodeMix")
    shade.data_type = "RGBA"
    shade.blend_type = "MULTIPLY"
    shade.inputs["Factor"].default_value = 0.35
    links.new(mix.outputs[2], shade.inputs[6])
    fine = nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 2.5
    fine.inputs["Detail"].default_value = 8.0
    links.new(coords.outputs["Object"], fine.inputs["Vector"])
    tint = nodes.new("ShaderNodeValToRGB")
    tint.color_ramp.elements[0].color = (0.7, 0.7, 0.7, 1)
    tint.color_ramp.elements[1].color = (1.15, 1.15, 1.1, 1)
    links.new(fine.outputs["Fac"], tint.inputs["Fac"])
    links.new(tint.outputs["Color"], shade.inputs[7])
    links.new(shade.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.9
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    links.new(fine.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    mat.diffuse_color = (0.3, 0.42, 0.18, 1)   # what Solid view shows
    return mat


def _water_material(color=None):
    rgb = _rgb(color, (0.01, 0.2, 0.3))
    name = "Jervis water surface" if color is None else "Jervis water %02x%02x%02x" % tuple(int(c * 255) for c in rgb)
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = 0.04
    bsdf.inputs["IOR"].default_value = 1.33
    bsdf.inputs["Alpha"].default_value = 0.8
    bsdf.inputs["Coat Weight"].default_value = 0.6
    waves = nodes.new("ShaderNodeTexNoise")
    waves.inputs["Scale"].default_value = 1.6
    waves.inputs["Detail"].default_value = 6.0
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    links.new(waves.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    try:
        mat.surface_render_method = "BLENDED"   # see the shallows through it, in the viewport and in renders
    except Exception:
        mat.blend_method = "BLEND"
    mat.diffuse_color = (*rgb, 0.75)
    return mat


def water(name="Water", at=None, size=60.0, color=None, waves=0.5, **kw):
    """A water surface (sea, lake, pond) `size` metres across at `at`'s height: gently rolling, clear enough to see
    the shallows through, and reflective."""
    size = max(1.0, min(2000.0, float(size or 60.0)))
    waves = max(0.0, min(1.0, float(waves if waves is not None else 0.5)))
    params = dict(size=size, color=color, waves=waves)
    if at is None:
        at = (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)
    at = tuple(_vec3(at))   # noqa: F821  (water sits at its own level, never on the terrain)
    p = Parts()
    n = 60
    bmesh.ops.create_grid(p.bm, x_segments=n, y_segments=n, size=size / 2)
    off = Vector((7.3, 1.9, 0))
    for v in p.bm.verts:
        v.co.z = waves * 0.08 * mathutils.noise.noise(v.co * (6.0 / max(size, 6.0)) * 4 + off)
    obj = p.done(f"{name} Surface", at, None, smooth="all", kind="water")
    obj.data.materials.append(_water_material(color))
    return _finish_asset(name, "water", params, [obj], at, 0, f"{_a(round(size))} {round(size)} m water surface with gentle waves")


def _rock_lump(parts, center, s_, seed):
    verts = parts.lump((0.0, 0.0, 0.0), s_ * 0.6, irregularity=0.42, squash=(1.25, 1.0, 0.7), detail=3, seed=seed,
                       flat_bottom=0.35)
    off = Vector((seed * 3.1, seed * 1.7, seed * 2.3))
    for v in verts:
        v.co += v.co.normalized() * s_ * 0.07 * mathutils.noise.ridged_multi_fractal(v.co * 2.5 / s_ + off, 0.8, 2.0, 3,
                                                                                     1.0, 2.0)
    low = min(v.co.z for v in verts)
    for v in verts:
        v.co += Vector(center) + Vector((0, 0, -low - s_ * 0.08))
    return verts


def _shore_foam(name, at, terrain, R, seed):
    """White surf in a broken band where the water meets the beach: the coastline found by searching outward along
    many directions for where the terrain drops below the sea."""
    bpy.context.view_layer.update()
    from mathutils.bvhtree import BVHTree
    tree_ = BVHTree.FromObject(terrain, bpy.context.evaluated_depsgraph_get())   # once: thousands of rays follow
    inv = terrain.matrix_world.inverted()
    down = (inv.to_3x3() @ Vector((0, 0, -1))).normalized()

    def height(x, y):
        hit = tree_.ray_cast(inv @ Vector((x, y, 1000.0)), down)
        return (terrain.matrix_world @ hit[0]).z if hit and hit[0] is not None else -1.0

    rings_in, rings_out = [], []
    steps = 160
    r = rng(seed * 71 + 5)   # noqa: F821
    for k in range(steps):
        a = 2 * math.pi * k / steps
        d = R * 0.6
        while d < R * 1.6:   # the first point outward where the ground is under water
            if height(at[0] + math.cos(a) * d, at[1] + math.sin(a) * d) - at[2] < 0.0:
                break
            d += R * 0.01
        width = R * r.uniform(0.025, 0.06)
        rings_in.append((math.cos(a) * (d - width * 0.6), math.sin(a) * (d - width * 0.6)))
        rings_out.append((math.cos(a) * (d + width), math.sin(a) * (d + width)))
    p = Parts()
    bm = p.bm
    inner = [bm.verts.new((x, y, 0.03)) for x, y in rings_in]
    outer = [bm.verts.new((x, y, 0.03)) for x, y in rings_out]
    for k in range(steps):
        j = (k + 1) % steps
        bm.faces.new((inner[k], inner[j], outer[j], outer[k]))
    obj = p.done(name, at, None, smooth="all", kind="water")
    mat = bpy.data.materials.get("Jervis surf") or bpy.data.materials.new("Jervis surf")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.95, 0.97, 1.0, 1)
    bsdf.inputs["Roughness"].default_value = 0.4
    if not any(n.type == "TEX_NOISE" for n in nodes):
        breakup = nodes.new("ShaderNodeTexNoise")   # broken, frothy edges rather than a solid ring
        breakup.inputs["Scale"].default_value = 1.4
        breakup.inputs["Detail"].default_value = 8.0
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.45
        ramp.color_ramp.elements[1].position = 0.62
        links.new(breakup.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Alpha"])
    try:
        mat.surface_render_method = "BLENDED"
    except Exception:
        mat.blend_method = "BLEND"
    mat.diffuse_color = (0.95, 0.97, 1.0, 0.6)
    obj.data.materials.append(mat)
    return obj


def island(name="Island", at=None, radius=15.0, height=4.0, seed=0, water=True, rocks=True, trees=0,
           tree_kind="palm", waves=0.35, sea_color=None, foam=False, **kw):
    """An island: a natural coastline, a sandy beach that slopes into turquoise shallows, grassy hills and rocky
    slopes (the material follows the height and steepness), rocks along the shore, and the sea around it
    (water=False leaves the sea out), and trees=N of tree_kind growing on it. The sea: waves=0-1 (rolling swell and
    ripples), sea_color, foam=True (white surf where the waves meet the beach). Things built on it afterwards stand
    on its surface by themselves; scatter_on('Island Terrain', count) gives spots for more trees, rocks or huts."""
    R = max(4.0, min(120.0, float(radius or 15.0)))
    Hmax = max(0.5, min(40.0, float(height or 4.0)))
    trees = max(0, min(40, int(trees or 0)))
    waves = max(0.0, min(1.0, float(waves if waves is not None else 0.35)))
    params = dict(radius=R, height=Hmax, seed=seed, water=bool(water), rocks=bool(rocks), trees=trees,
                  tree_kind=tree_kind, waves=waves, sea_color=sea_color, foam=bool(foam))
    if at is None:
        at = (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)
    at = tuple(_vec3(at))   # noqa: F821
    noise = mathutils.noise
    off = Vector(((seed * 12.9898) % 97 + 3.3, (seed * 78.233) % 89 + 1.1, 0))
    p = Parts()
    n = 190   # the sea floor reaches as far as the sea, so no edge shows through the water
    bmesh.ops.create_grid(p.bm, x_segments=n, y_segments=n, size=R * 2.6)
    for v in p.bm.verts:
        x, y = v.co.x, v.co.y
        ang = math.atan2(y, x)
        coast = R * (1 + 0.16 * noise.noise(Vector((math.cos(ang), math.sin(ang), 0)) * 1.3 + off)
                     + 0.07 * noise.noise(Vector((math.cos(ang), math.sin(ang), 0)) * 3.1 + off * 1.7))
        d = math.hypot(x, y) / coast
        hills = 0.72 + 0.55 * noise.fractal(Vector((x, y, 0)) / R * 1.6 + off, 0.6, 2.0, 4)
        land = Hmax * (1 - _smoothstep(0.0, 0.95, d)) ** 1.35 * max(0.2, hills)
        shore = 1.6 * (0.98 - d)                      # a gentle beach crossing the waterline near the coast
        shore -= 9.0 * max(0.0, d - 1.12) ** 1.4      # then the sea floor drops away
        z = max(-6.0, min(shore, 0.6) + land) + 0.06 * noise.noise(Vector((x, y, 0)) * 0.9 + off)
        v.co.z = z
    terrain = p.done(f"{name} Terrain", at, None, smooth="all", kind="terrain")
    terrain.data.materials.append(_terrain_material(f"Jervis island ground {name}"))
    made = [terrain]
    if rocks:
        rp = Parts()
        r = rng(seed * 29 + 7)   # noqa: F821
        bpy.context.view_layer.update()
        for i in range(9):
            a = 2 * math.pi * i / 9 + r.uniform(-0.25, 0.25)
            for _ in range(20):   # find the shoreline along this direction
                dist = R * r.uniform(0.85, 1.05)
                x, y = math.cos(a) * dist, math.sin(a) * dist
                z = ground_height(at[0] + x, at[1] + y, default=None)
                if z is not None and -0.2 < z - at[2] < 0.5:
                    break
            s_ = r.uniform(0.5, 1.3)
            _rock_lump(rp, (x, y, (z - at[2]) if z is not None else 0.0), s_, seed * 41 + i)
            if r.random() < 0.6:
                _rock_lump(rp, (x + r.uniform(-1, 1) * s_, y + r.uniform(-1, 1) * s_,
                                (z - at[2]) if z is not None else 0.0), s_ * 0.45, seed * 43 + i)
        made.append(rp.done(f"{name} Rocks", at, "rock", smooth=True))
    if water:
        sea = Parts()
        bmesh.ops.create_grid(sea.bm, x_segments=90, y_segments=90, size=R * 2.6)
        for v in sea.bm.verts:   # a long rolling swell plus choppier ripples, both scaled by `waves`
            swell = 0.12 * noise.noise(v.co * (0.9 / R) + off)
            chop = 0.035 * noise.noise(v.co * 0.6 + off * 1.7)
            v.co.z = waves * (swell + chop) * 1.6
        sea_obj = sea.done(f"{name} Sea", at, None, smooth="all", kind="water")
        mat = _water_material(sea_color)
        try:
            bump = next(n for n in mat.node_tree.nodes if n.type == "BUMP")
            bump.inputs["Strength"].default_value = 0.1 + 0.4 * waves
        except StopIteration:
            pass
        sea_obj.data.materials.append(mat)
        made.append(sea_obj)
        if foam:
            made.append(_shore_foam(f"{name} Foam", at, terrain, R, seed))
    if trees:
        bpy.context.view_layer.update()
        r = rng(seed * 61 + 17)   # noqa: F821
        label = {"palm": "Palm", "pine": "Pine", "birch": "Birch"}.get(str(tree_kind).lower(), "Tree")
        spots = scatter_on(terrain.name, trees, min_height=min(0.7, Hmax * 0.25), max_slope=28, seed=seed,
                           min_gap=max(2.0, R * 0.22))
        for i, spot in enumerate(spots):
            made.append(tree(f"{name} {label} {i + 1}", at=spot, kind=tree_kind, seed=seed * 7 + i,
                             height=r.uniform(0.8, 1.2) * {"palm": 7.0, "pine": 8.0}.get(str(tree_kind).lower(), 6.0),
                             rotation=r.uniform(0, 360)))
    grown = sum(1 for o in made if o is not None and o.get("jervis_asset"))
    summary = (f"{_a(round(R * 2))} {round(R * 2)} m island with a sandy beach sloping into turquoise shallows, grassy hills"
               + (", rocks along the shore" if rocks else "") + (f", {grown} {tree_kind} trees" if grown else "")
               + (" and the sea around it" if water else ""))
    return _finish_asset(name, "island", params, made, at, 0, summary)


def scatter_on(terrain, count=6, min_height=0.6, max_slope=30.0, seed=0, min_gap=2.0, avoid=0.0):
    """`count` spots on a terrain's surface (world (x, y, z)) where things can stand: above `min_height` (off the
    beach), on ground no steeper than `max_slope` degrees, at least `min_gap` metres apart. For trees, huts, rocks
    on an island or a hill: for i, p in enumerate(scatter_on('Island Terrain', 6)): tree(f'Palm {i+1}', 'palm', at=p)
    avoid=6 also keeps every spot that far from the things already standing there (its trees, a hut)."""
    obj = get(terrain)   # noqa: F821
    owner = obj.parent
    standing = [o.matrix_world.translation.copy() for o in _scene().objects   # noqa: F821
                if o.get("jervis_asset") and o is not owner] if avoid else []
    deps = bpy.context.evaluated_depsgraph_get()
    from mathutils.bvhtree import BVHTree
    tree_ = BVHTree.FromObject(obj, deps)
    mw = obj.matrix_world
    (x0, y0, _), (x1, y1, _) = bounds(obj)   # noqa: F821
    base_z = obj.matrix_world.translation.z
    r = rng(seed * 53 + 1)   # noqa: F821
    out = []
    inv = mw.inverted()
    for _ in range(int(count) * 200):
        if len(out) >= count:
            break
        x, y = r.uniform(x0, x1), r.uniform(y0, y1)
        hit = tree_.ray_cast(inv @ Vector((x, y, 1000.0)), (inv.to_3x3() @ Vector((0, 0, -1))).normalized())
        if not hit or hit[0] is None:
            continue
        p = mw @ hit[0]
        nz = abs((mw.to_3x3() @ hit[1]).normalized().z)
        if p.z - base_z < min_height or nz < math.cos(math.radians(max_slope)):
            continue
        if any((p.x - q[0]) ** 2 + (p.y - q[1]) ** 2 < min_gap ** 2 for q in out):
            continue
        if any((p.x - q.x) ** 2 + (p.y - q.y) ** 2 < avoid ** 2 for q in standing):
            continue
        out.append((round(p.x, 3), round(p.y, 3), round(p.z, 3)))
    return out


# ---------- changing an asset later ----------

def asset_info(obj):
    """{"type", "params"} of the asset an object belongs to (the object itself or one of its parts), or None."""
    o = get(obj)   # noqa: F821
    while o is not None:
        if o.get("jervis_asset"):
            data = json.loads(o["jervis_asset"])
            data["root"] = o.name
            return data
        o = o.parent
    return None


def rebuild_asset(obj, **changes):
    """Build an asset again with some options changed ("bigger windows", "a red roof", "two floors"), in the same
    place, under the same name. The old one is kept aside (Jervis's undo can bring it back)."""
    info = asset_info(obj)
    if info is None:
        raise ValueError(f"{get(obj).name!r} isn't one of the finished assets (house, tree, island...), so it can't be "   # noqa: F821
                         "rebuilt with new options. To remodel it, call its builders again with the SAME part names "
                         "and new sizes (e.g. box('Bench Seat', (1.6, 0.45, 0.05), at=...)), which replaces those parts, "
                         "or resize()/move() them.")
    root = get(info["root"])   # noqa: F821
    params = dict(info["params"])
    params.update({k: v for k, v in changes.items() if v is not None})
    location = tuple(root.location)
    rotation = math.degrees(root.rotation_euler.z)
    name = root.name
    # what it means in the scene (tag_semantic) and its lights' memory outlive the rebuild
    keep = {k: root[k] for k in ("jervis_semantic", "jervis_sid", "jervis_tags") if k in root.keys()}
    old = [c.name for c in root.children_recursive] + [root.name]
    for o_name in old:
        PROTECTED.discard(o_name)   # noqa: F821  (this request may replace exactly these)
        trash(o_name)   # noqa: F821
    coll = bpy.data.collections.get(name)
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)
    params["rotation"] = params.get("rotation", rotation) if "rotation" in changes else rotation
    builder = {"house": house, "tree": tree, "island": island, "water": water, "rock": rock, "bush": bush,
               "fence": fence, "pool": pool, "pond": pond, "bench": bench, "lounger": lounger,
               "fountain": fountain, "car": car, "garage": garage, "gate": gate, "fire": globals().get("fire"), "flag": globals().get("flag"),
               "waterfall": globals().get("waterfall"), "river": globals().get("river"),
               "cloud": globals().get("cloud"), "smoke": globals().get("smoke")}.get(info["type"])
    builder = builder or globals().get(info["type"])   # the place builders too (villa, storefront, forest, ground...)
    if builder is None:
        raise ValueError(f"There's no builder for a {info['type']!r} to rebuild it with.")
    for o_name in old:   # free the names: the rebuilt parts take them again
        o = bpy.data.objects.get(o_name)
        if o is not None:
            o.name = f"__old {o_name}"
    new = builder(name, at=location, **params)
    for k, v in keep.items():
        new[k] = v
    return new


ASSET_BUILDERS = ("house", "tree", "island", "water", "rock", "bush", "fence", "pool", "pond", "bench", "lounger",
                  "fountain", "car", "garage", "gate", "walkway", "scatter_on",
                  "ground_height", "save_file", "asset_info", "rebuild_asset")
if bpy is not None:
    try:   # the kit restores its own names before every step (see blender_kit._KIT): these are kit names too
        _KIT.update({k: globals()[k] for k in ASSET_BUILDERS})   # noqa: F821
        _KIT.update({k: globals()[k] for k in ("Parts", "_cut_boxes", "_here", "_finish_asset", "_remember",
                                                "_rgb", "_house_roof", "_hip_roof", "_house_porch", "_oak", "_pine",
                                                "_palm", "_leaf_material", "_terrain_material", "_water_material",
                                                "_rock_lump", "_smoothstep", "_ribbon", "_slabs", "_offset_line", "_sink_into_ground", "_walkway", "_is_thing_name",
                                                "_WALKWAY_START", "_WALKWAY_END", "ASSETS_VERSION", "ASSET_TYPES")})
    except NameError:
        pass
