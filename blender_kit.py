"""Jervis's building kit for Blender: a small, forgiving API that the agent's AI writes against instead of raw bpy.

Loaded into the bridge's namespace (see agent_blender.BlenderAdapter.prepare), so code the AI sends can call
box(), roof(), color()... directly. Why a kit and not raw bpy: a local 7B model writes correct ten-line scripts
against a short, documented API far more reliably than against bpy's huge, context-dependent one. Every builder:

  - builds meshes with bmesh + the data API (never bpy.ops), so it works from the bridge's timer, where operators
    that need a 3D-view context fail;
  - puts the object's origin at the bottom centre (`at` is where it stands), so stacking is just arithmetic;
  - replaces an existing object of the same name, so re-running a repaired step never leaves "Roof.001" behind;
  - accepts the argument spellings models tend to use (at/location/position, size as a number or a tuple, colors
    as names, hex or RGB).

Also importable outside Blender (bpy is then None), so Jervis shares COLORS and color_name() for its checks.
"""
import json
import math
import re

try:
    import bmesh
    import bpy
    import mathutils
except ImportError:   # imported by Jervis itself for COLORS / color_name
    bpy = bmesh = mathutils = None
try:
    spatial   # inside Blender: loaded just before the kit (agent_blender.kit_source)
except NameError:
    import spatial

KIT_VERSION = 27   # (includes blender_assets.py and spatial.py, loaded with it)

# What the current step made and anything the kit had to work around, read back by Jervis after every step: a step
# that was meant to build something but made nothing has failed, whatever its code returned.
STEP = {"made": [], "warnings": [], "retired": []}


def step_begin():
    STEP["made"].clear()
    STEP["warnings"].clear()
    STEP.setdefault("retired", []).clear()   # what the kit took away on purpose (a house's path a walkway replaced)


def _warn(text):
    if text not in STEP["warnings"]:
        STEP["warnings"].append(text)

COLORS = {
    "red": (0.8, 0.03, 0.03), "dark red": (0.3, 0.01, 0.01), "maroon": (0.25, 0.01, 0.03),
    "orange": (0.9, 0.3, 0.02), "yellow": (0.9, 0.75, 0.02), "gold": (0.85, 0.55, 0.1),
    "green": (0.05, 0.5, 0.05), "dark green": (0.01, 0.15, 0.02), "lime": (0.3, 0.8, 0.05),
    "grass": (0.08, 0.35, 0.04), "leaf": (0.04, 0.3, 0.03), "olive": (0.25, 0.25, 0.03),
    "blue": (0.02, 0.1, 0.8), "light blue": (0.3, 0.55, 0.9), "sky blue": (0.4, 0.65, 0.95), "sky": (0.4, 0.65, 0.95),
    "navy": (0.01, 0.02, 0.2), "dark blue": (0.01, 0.03, 0.3), "cyan": (0.02, 0.65, 0.75), "teal": (0.01, 0.3, 0.3),
    "turquoise": (0.05, 0.6, 0.5), "purple": (0.35, 0.05, 0.65), "violet": (0.45, 0.15, 0.75),
    "pink": (0.9, 0.3, 0.5), "magenta": (0.8, 0.02, 0.6),
    "brown": (0.25, 0.1, 0.03), "wood": (0.35, 0.18, 0.07), "dark wood": (0.12, 0.05, 0.02),
    "beige": (0.75, 0.65, 0.45), "cream": (0.9, 0.85, 0.7), "tan": (0.6, 0.45, 0.28), "sand": (0.8, 0.7, 0.45),
    "white": (0.9, 0.9, 0.9), "black": (0.01, 0.01, 0.01), "gray": (0.3, 0.3, 0.3), "grey": (0.3, 0.3, 0.3),
    "light gray": (0.6, 0.6, 0.6), "light grey": (0.6, 0.6, 0.6), "dark gray": (0.08, 0.08, 0.08),
    "dark grey": (0.08, 0.08, 0.08), "silver": (0.7, 0.7, 0.72), "metal": (0.55, 0.56, 0.58), "steel": (0.5, 0.52, 0.55),
    "glass": (0.6, 0.8, 0.9), "stone": (0.35, 0.33, 0.3), "brick": (0.45, 0.12, 0.06), "concrete": (0.45, 0.45, 0.43),
    "water": (0.05, 0.3, 0.6), "skin": (0.8, 0.55, 0.4), "snow": (0.95, 0.95, 0.97), "dirt": (0.2, 0.12, 0.05),
}
_METALLIC = {"gold", "silver", "metal", "steel"}


# ---------- colors (pure Python: also used by Jervis's checks) ----------

def _rgb_numbers(values):
    values = [float(v) for v in values]
    if len(values) < 3 or any(v != v for v in values):   # (NaN != NaN)
        raise ValueError
    values = values[:3]
    if any(v > 1 for v in values):
        values = [v / 255 for v in values]
    return tuple(max(0.0, min(1.0, v)) for v in values)


def rgb_of(color):
    """(r, g, b) in 0..1 for a color name ("red", "dark wood", "bright red"), hex ("#ff0000", "#f00", "ff0000"),
    "rgb(255, 0, 0)", "0.8, 0.2, 0.1" or a tuple (0..1 or 0..255, an alpha is ignored). Raises ValueError for
    anything that isn't a colour (a bare number like 4, "color 4") — material() turns that into a fallback."""
    if color is None:
        return None
    if bpy is not None and isinstance(color, bpy.types.Material):
        return tuple(color.diffuse_color[:3])
    if isinstance(color, bool) or isinstance(color, (int, float)):
        raise ValueError(f"Unknown color {color!r}: a number isn't a colour. Use a name ('red', 'wood'), a hex like "
                         "'#ff0000', or an (r, g, b) tuple.")
    if isinstance(color, (tuple, list)):
        try:
            return _rgb_numbers(list(color))
        except (TypeError, ValueError):
            raise ValueError(f"Unknown color {color!r}: an (r, g, b) tuple needs three numbers.") from None
    text = str(color).strip().lower().replace("_", " ").replace("-", " ")
    bare = text.lstrip("#")
    if all(c in "0123456789abcdef" for c in bare) and (text.startswith("#") or any(c.isdigit() for c in bare)) \
            and len(bare) in (3, 6, 8):
        if len(bare) == 3:
            bare = "".join(c * 2 for c in bare)
        return tuple(int(bare[i:i + 2], 16) / 255 for i in (0, 2, 4))
    numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(numbers) >= 3 and re.fullmatch(r"\s*(?:rgba?\s*)?\(?\s*[-\d.,\s]+\)?\s*", text):
        try:
            return _rgb_numbers(numbers[:3])
        except ValueError:
            pass
    if text in COLORS:
        return COLORS[text]
    preset = preset_of(text) if "preset_of" in globals() else None
    if preset:
        a, b = PRESETS[preset]["colors"]
        return tuple((x + y) / 2 for x, y in zip(a, b))
    for name in sorted(COLORS, key=len, reverse=True):   # "bright red roof tiles" -> red
        if re.search(r"\b" + re.escape(name) + r"\b", text):
            return COLORS[name]
    import difflib
    close = difflib.get_close_matches(text, list(COLORS), n=1, cutoff=0.8)   # "grren", "lightblue"
    if close:
        return COLORS[close[0]]
    raise ValueError(f"Unknown color {color!r}. Use a name ({', '.join(list(COLORS)[:16])}, ...), "
                     "a hex like '#ff0000', or an (r, g, b) tuple.")


# When the AI's colour isn't one ("color 4", 7, None-like junk), the part's own name says what it's made of.
_NAME_MATERIALS = [
    (r"water|pool water|sea|lake|pond", "water"), (r"roof|tiles?|shingles?", "roof tiles"),
    (r"trunk|bark|branch\w*|log", "bark"), (r"lea(?:f|ves)|foliage|crown|canopy|bush|hedge|shrub", "leaves"),
    (r"grass|lawn", "grass"), (r"glass|pane|window", "glass"), (r"brick", "brick"),
    (r"path|paver\w*|stone|rock|boulder|kerb|curb|coping", "stone"), (r"sand|beach", "sand"),
    (r"metal|steel|iron|handle|ladder|rail\w*|pipe|pole|post|lamp", "steel"),
    (r"foundation|base|slab|concrete|plinth|step\w*", "concrete"), (r"cushion|sofa|couch|pillow|fabric|bed", "fabric"),
    (r"wall\w*|facade|plaster", "plaster"),
    (r"wood\w*|plank\w*|board\w*|bench|table|chair|desk|door|deck\w*|fence|shelf|frame|beam|leg\w*", "wood"),
]


def _guess_material(name):
    low = str(name or "").lower()
    for pattern, preset in _NAME_MATERIALS:
        if re.search(r"\b(?:" + pattern + r")\b", low):
            return preset
    return None


def color_name(rgb) -> str:
    """The plain color family of an RGB value: red, orange, yellow, green, cyan, blue, purple, pink, brown, white,
    gray or black. Two colors "match" in a check when their families are the same."""
    import colorsys
    r, g, b = (max(0.0, min(1.0, float(v))) for v in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v < 0.06:
        return "black"
    if s < 0.18:
        return "white" if v > 0.75 else "gray"
    deg = h * 360
    if deg < 12 or deg >= 345:
        return "red"
    if deg < 45:
        return "brown" if v < 0.55 else "orange"
    if deg < 70:
        return "yellow" if v >= 0.35 else "brown"
    if deg < 165:
        return "green"
    if deg < 195:
        return "cyan"
    if deg < 255:
        return "blue"
    if deg < 290:
        return "purple"
    return "pink"


# ---------- inside Blender ----------

def _vec3(value, default=(0.0, 0.0, 0.0)):
    if value is None:
        return tuple(default)
    if isinstance(value, (int, float)):
        return (float(value),) * 3
    values = [float(v) for v in value]
    return tuple((values + list(default))[:3])


def _radius_or_at(radius, at, default):
    """cylinder('Wheel', (2, 0, 0), ...): a position given where the radius goes."""
    if isinstance(radius, (tuple, list)) and at is None:
        return default, radius
    return radius, at


def _where(at, kw):
    for alias in ("location", "position", "pos", "center", "loc"):
        if at is None and alias in kw:
            at = kw.pop(alias)
    return _vec3(at)


def _scene():
    return getattr(bpy.context, "scene", None) or bpy.data.scenes[0]


def _layer():
    return getattr(bpy.context, "view_layer", None) or _scene().view_layers[0]


def _update():
    _layer().update()


def get(name, *more):
    """The object called `name` (exact, then case-insensitive, then by prefix). Several names: a list of them."""
    if more:
        return [get(n) for n in (name, *more)]
    if isinstance(name, str) and name in ALIASES:
        name = ALIASES[name]
    if bpy is not None and isinstance(name, bpy.types.Object):
        try:
            name.name
        except ReferenceError:
            raise KeyError("That object was replaced or deleted since you stored it in a variable: refer to objects "
                           "by their name (a string) instead.") from None
        return name
    if name is None or (not isinstance(name, str) and not isinstance(name, (int, float))):
        raise KeyError(f"{name!r} isn't an object name: refer to objects by their name, a string like 'House Roof'.")
    obj = bpy.data.objects.get(str(name))
    if obj and not (obj.get("jervis_trash") and not obj.users_collection):
        return obj
    low = str(name).lower().strip()
    live = [o for o in _scene().objects if not o.name.startswith("__")]
    # exact (any case), then a whole-word prefix ('Pool' -> 'Pool Water'), then whole words anywhere ('Door' ->
    # 'House Door') — the shortest such name, so 'Tree' never means 'Tree 2 Leaves 7' when 'Tree 2' is there.
    for test in (lambda n: n == low, lambda n: n.startswith(low + " "),
                 lambda n: re.search(r"(?:^|\s)" + re.escape(low) + r"(?:\s|$)", n) is not None,
                 lambda n: n.startswith(low), lambda n: low in n):
        hits = [o for o in live if test(o.name.lower())]
        if hits:
            return min(hits, key=lambda o: (o.parent is not None, len(o.name)))
    names = ", ".join(o.name for o in live[:40]) or "(none)"
    raise KeyError(f"There is no object named {name!r}. Objects in the scene: {names}")


def material(color, name=None, metallic=None, roughness=0.5, emission=0.0, alpha=1.0, vary=0.0, seed=0, hint=None):
    """A material: a preset that looks like something ('bark', 'wood', 'stone', 'brick', 'leaves', 'roof tiles',
    'plaster', 'metal', 'glass'... see PRESETS), or a plain colour (name, '#rrggbb' or (r, g, b)). Something that
    isn't a colour at all (4, 'color 4') never stops the build: the part gets the material its name suggests
    (`hint`: 'Pool Water' -> water) or a neutral grey, and the step reports it."""
    if bpy is not None and isinstance(color, bpy.types.Material):
        return color
    if isinstance(color, str) and preset_of(color):
        return textured_material(color, vary=vary, seed=seed, name=name)
    try:
        rgb = rgb_of(color)
    except (ValueError, TypeError) as e:
        guess = _guess_material(hint)
        _warn(f"{str(e).split('. Use')[0].split(': ')[0]} for {hint or 'a part'!r}: used "
              f"{guess or 'light grey'} instead")
        if guess:
            return textured_material(guess, vary=vary, seed=seed)
        rgb, color = (0.6, 0.6, 0.6), "light grey"
    label = name or (f"Jervis {str(color).strip().lower()}" if isinstance(color, str) else
                     "Jervis #%02x%02x%02x" % tuple(int(c * 255) for c in rgb))
    if metallic is None:
        metallic = 1.0 if isinstance(color, str) and color.strip().lower() in _METALLIC else 0.0
    mat = bpy.data.materials.get(label) or bpy.data.materials.new(label)
    mat.diffuse_color = (*rgb, alpha)
    mat.metallic = metallic
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (*rgb, 1)
            bsdf.inputs["Metallic"].default_value = metallic
            bsdf.inputs["Roughness"].default_value = roughness
            if alpha < 1:
                bsdf.inputs["Alpha"].default_value = alpha
            if emission:
                for key in ("Emission Color", "Emission"):
                    if key in bsdf.inputs:
                        bsdf.inputs[key].default_value = (*rgb, 1)
                if "Emission Strength" in bsdf.inputs:
                    bsdf.inputs["Emission Strength"].default_value = emission
    except Exception:
        pass
    return mat


def color(obj, color_value=None, **kw):
    """Give an object (or a list of objects) a material: color('Roof', 'roof tiles'), color('Trunk', 'bark'),
    color('Door', 'red'). vary=0.15, seed=i gives each of several objects its own slightly different shade."""
    color_value = color_value if color_value is not None else kw.pop("color", kw.pop("colour", kw.pop("material", None)))
    if isinstance(obj, (list, tuple)):
        return [globals()["color"](o, color_value, **kw) for o in obj]
    obj = get(obj)
    # A group (an assembly's empty) has no surface of its own: colouring it means colouring its parts.
    targets = [obj] if obj.data is not None and hasattr(obj.data, "materials") else [
        c for c in obj.children_recursive if c.data is not None and hasattr(c.data, "materials")]
    if not targets:
        raise ValueError(f"{obj.name!r} has no surface to colour (it's {obj.type.lower()} with no parts): colour its "
                         "parts by name instead.")
    kw.setdefault("hint", obj.name)
    mat = material(color_value, **kw)
    for target in targets:
        if target.data.materials:
            for i in range(len(target.data.materials)):
                target.data.materials[i] = mat
        else:
            target.data.materials.append(mat)
    return obj


# Names of objects that were in the scene before the current request (set by Jervis for each request). A builder
# never silently replaces one of those: "build a house" next to an existing 'House Walls' must not rebuild it.
PROTECTED = set()


# Per request: names the AI asked for that were taken by something already in the scene, and what its new object
# was called instead ('Bench Seat' -> 'Bench 2 Seat'). get() follows them, so the AI's own code keeps working.
ALIASES = {}
NAME_HINT = ""      # the thing being built ("Bench 2"), when Jervis knows it: renames follow its pattern


def _fresh_name(name):
    first = name.split()[0] if name.split() else name
    candidates = []
    if NAME_HINT and NAME_HINT.split()[0].lower() == first.lower() and not name.lower().startswith(NAME_HINT.lower()):
        candidates.append(NAME_HINT + name[len(first):])
    candidates += [f"{name} {k}" for k in range(2, 200)]
    for candidate in candidates:
        if bpy.data.objects.get(candidate) is None and candidate not in PROTECTED:
            return candidate
    return name + " new"


_JOIN_GROUP = {}   # a new shape's name -> the group (assembly) it goes in, see _claim


def _claim(name):
    """(the name a new shape really gets, an object of this request's to reuse for it or None): something already in
    the scene before this request is never touched — the new shape gets a fresh name, remembered in ALIASES."""
    name = str(name).strip() or "Part"
    name = ALIASES.get(name, name)
    old = bpy.data.objects.get(name)
    if old is None:
        return name, None
    if name in PROTECTED and old.users_collection:
        fresh = _fresh_name(name)
        ALIASES[name] = fresh
        return fresh, None
    if old.type != "MESH" and old.children:
        # box('Pool', ...) after assemble('Pool'): the name is the group's. Removing that empty would scatter its
        # parts, so the new shape becomes one more part of the group instead.
        body = _fresh_name(f"{name} Body") if bpy.data.objects.get(f"{name} Body") else f"{name} Body"
        _JOIN_GROUP[body] = old.name
        _warn(f"{name!r} is a group of parts, so the new shape was named {body!r} and added to it")
        return body, None
    if old.type != "MESH":
        _retire(old)
        return name, None
    if not old.users_collection:
        _scene().collection.objects.link(old)
    if "jervis_trash" in old:
        del old["jervis_trash"]
        old.use_fake_user = False
    return name, old


def _make_room_for(name):
    """The name a new object really gets. An object of that name made earlier in this same request is replaced (a
    step being re-run); one that was already in the scene is never touched — the new object gets a fresh name
    instead, remembered in ALIASES so later code naming it still reaches the new one."""
    name = ALIASES.get(name, name)
    old = bpy.data.objects.get(name)
    if old is None:
        return name
    if name in PROTECTED and old.users_collection:
        fresh = _fresh_name(name)
        ALIASES[name] = fresh
        return fresh
    _retire(old)
    return name


def _retire(obj):
    """Take an object this request made out of the way of a new one with its name — kept aside (like trash()) under
    another name, never deleted: if the step that replaces it is undone, Jervis's snapshot brings back this very
    object (by its session id). Its parts are freed first, exactly where they stand."""
    if obj.children:
        _update()
        for child in list(obj.children):
            world = child.matrix_world.copy()
            child.parent = None
            child.matrix_world = world
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    obj.use_fake_user = True
    obj["jervis_trash"] = True
    k = 1
    while bpy.data.objects.get(f"__retired {obj.name} {k}") is not None:
        k += 1
    obj.name = f"__retired {obj.name} {k}"


def _finish(bm, name, at, color_value, rotation, kw, kind="mesh"):
    if color_value is None:
        color_value = kw.pop("colour", kw.pop("material", None))
    bevel_width = kw.pop("bevel", 0) or 0
    shade_vary = kw.pop("vary", 0) or 0
    for key in list(kw):   # tolerated extras the model sometimes adds (segments=..., smooth=...)
        if key not in ("smooth",):
            kw.pop(key)
    at = tuple(float(v) for v in at)
    bad = [v for v in at if not math.isfinite(v)] or [c for v in bm.verts for c in v.co if not math.isfinite(c)][:1]
    if bad:   # NaN / infinity from the AI's arithmetic: refuse before anything is made, never leave an object nowhere
        bm.free()
        raise ValueError(f"{name!r}: its {'position ' + str(at) if not all(map(math.isfinite, at)) else 'size'} "
                         "isn't a real number (check the arithmetic before it).")
    name, obj = _claim(name)
    mesh = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    if obj is not None:
        # Rebuilding something this request made: same object, new shape — so a Python reference the AI kept
        # (rocks = [blob(...), ...]) still points at it instead of at a deleted object.
        old_mesh = obj.data
        obj.data = mesh
        obj.modifiers.clear()
        obj.rotation_euler, obj.scale = (0, 0, 0), (1, 1, 1)
        for key in ("jervis_shaped", "jervis_kind"):
            if key in obj:
                del obj[key]
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    else:
        obj = bpy.data.objects.new(name, mesh)
        _scene().collection.objects.link(obj)
    obj.location = at
    if rotation:
        rot = (0, 0, rotation) if isinstance(rotation, (int, float)) else _vec3(rotation)
        obj.rotation_euler = tuple(math.radians(r) for r in rot)
    if obj.parent is not None:
        # A part of an assembly being rebuilt: `at` is a WORLD position, so it must not be taken relative to the
        # group's origin (that once put a rebuilt trunk twice as far from the scene's centre as its tree).
        _update()
        obj.matrix_parent_inverse = obj.parent.matrix_world.inverted()
    group = _JOIN_GROUP.pop(name, None)
    if group and bpy.data.objects.get(group) is not None:
        _update()
        holder = bpy.data.objects[group]
        obj.parent = holder
        obj.matrix_parent_inverse = holder.matrix_world.inverted()
        for coll in holder.users_collection:
            if coll not in obj.users_collection:
                coll.objects.link(obj)
    if color_value is not None:
        import zlib
        color(obj, color_value, vary=shade_vary, seed=zlib.crc32(name.encode()) % 997 if shade_vary else 0)
    if kw.get("smooth"):
        _auto_smooth(obj, 180 if kw.get("smooth") == "all" else 40)
    obj["jervis_kind"] = kind
    if bevel_width:
        bevel(obj, float(bevel_width))
    _select(obj)
    if not len(obj.data.vertices):
        _warn(f"{name!r} came out empty (no geometry): check its size")
    STEP["made"].append(obj.name)
    return obj


def _select(obj):
    try:
        layer = _layer()
        for o in _scene().objects:
            o.select_set(False)
        obj.select_set(True)
        layer.objects.active = obj
    except Exception:
        pass


def _lift(bm, height, base):
    if base:
        bmesh.ops.translate(bm, vec=(0, 0, height / 2), verts=bm.verts)


def box(name, size=(1, 1, 1), at=None, color=None, base=True, rotation=0, **kw):
    """A box `size` = (width x, depth y, height z) — or one number for a cube — standing at `at`."""
    at = _where(at, kw)
    for alias in ("dimensions", "dims", "scale"):
        if alias in kw:
            size = kw.pop(alias)
    sx, sy, sz = _vec3(size, (1, 1, 1))
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    _lift(bm, sz, base)
    return _finish(bm, name, at, color, rotation, kw, "box")


cube = box


def _orient(bm, axis, radius, height, base):
    """Stand the shape up along z (default), or lay it on its side along x or y — a wheel, a log, an axle — still
    resting on `at`."""
    axis = str(axis or "z").lower()[:1]
    if axis in ("x", "y"):
        turn = mathutils.Matrix.Rotation(math.radians(90), 4, "Y" if axis == "x" else "X")
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=turn)
        if base:
            bmesh.ops.translate(bm, vec=(0, 0, radius), verts=bm.verts)
    else:
        _lift(bm, height, base)


def cylinder(name, radius=0.5, height=1.0, at=None, color=None, base=True, vertices=32, rotation=0, axis="z", **kw):
    """A cylinder standing on `at`; axis='x' or 'y' lays it on its side (a wheel: radius 0.35, height = its width)."""
    radius, at = _radius_or_at(radius, at, 0.5)
    at = _where(at, kw)
    radius = kw.pop("r", radius)
    height = kw.pop("depth", kw.pop("h", kw.pop("length", kw.pop("width", height))))
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=int(kw.pop("segments", vertices)),
                          radius1=radius, radius2=radius, depth=height)
    _orient(bm, axis, radius, height, base)
    return _finish(bm, name, at, color, rotation, kw, "cylinder")


def cone(name, radius=0.5, height=1.0, at=None, color=None, radius_top=0.0, base=True, vertices=32, rotation=0,
         axis="z", **kw):
    radius, at = _radius_or_at(radius, at, 0.5)
    at = _where(at, kw)
    radius = kw.pop("radius1", kw.pop("r", radius))
    radius_top = kw.pop("radius2", radius_top)
    height = kw.pop("depth", kw.pop("h", height))
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=int(kw.pop("segments", vertices)),
                          radius1=radius, radius2=radius_top, depth=height)
    _orient(bm, axis, max(radius, radius_top), height, base)
    return _finish(bm, name, at, color, rotation, kw, "cone")


def sphere(name, radius=0.5, at=None, color=None, base=True, segments=32, **kw):
    """A sphere resting on `at`, like every other builder (base=False: centred on it)."""
    radius, at = _radius_or_at(radius, at, 0.5)
    at = _where(at, kw)
    radius = kw.pop("r", radius)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=int(segments), v_segments=max(8, int(segments) // 2), radius=radius)
    _lift(bm, radius * 2, base)
    kw.setdefault("smooth", "all")
    return _finish(bm, name, at, color, 0, kw, "sphere")


def plane(name, size=10, at=None, color=None, rotation=0, **kw):
    """A flat ground/floor plane: size = one number or (x, y)."""
    at = _where(at, kw)
    sx, sy, _ = _vec3(size if not isinstance(size, (int, float)) else (size, size, 0))
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    bmesh.ops.scale(bm, vec=(sx, sy, 1), verts=bm.verts)
    return _finish(bm, name, at, color, rotation, kw, "plane")


ground = plane


def roof(name, width=4.0, depth=4.0, height=1.5, at=None, color=None, style="gable", overhang=0.2, rotation=0,
         thickness=None, gable_color=None, **kw):
    """A roof whose eaves sit at `at` (put `at` on top of the walls). style: 'gable' (ridge along x), 'pyramid'
    or 'flat'. width/depth are the walls' size; `overhang` is added on every side. thickness=0.15 makes a real gable
    roof: two sloped slabs hanging over the walls, plus the triangular gable walls under them (a separate object,
    "<name> Gables", coloured gable_color — use the walls' material)."""
    at = _where(at, kw)
    if thickness and style == "gable":
        return _slab_roof(name, float(width), float(depth), float(height), at, color, float(overhang),
                          float(thickness), gable_color, rotation, kw)
    w, d = width / 2 + overhang, depth / 2 + overhang
    bm = bmesh.new()
    if style == "flat":
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(w * 2, d * 2, max(0.05, height)), verts=bm.verts)
        _lift(bm, max(0.05, height), True)
        return _finish(bm, name, at, color, rotation, kw, "roof")
    if style == "pyramid":
        corners = [(-w, -d, 0), (w, -d, 0), (w, d, 0), (-w, d, 0), (0, 0, height)]
        v = [bm.verts.new(c) for c in corners]
        faces = [(v[3], v[2], v[1], v[0]), (v[0], v[1], v[4]), (v[1], v[2], v[4]), (v[2], v[3], v[4]),
                 (v[3], v[0], v[4])]
    else:
        corners = [(-w, -d, 0), (w, -d, 0), (w, d, 0), (-w, d, 0), (-w, 0, height), (w, 0, height)]
        v = [bm.verts.new(c) for c in corners]
        faces = [(v[3], v[2], v[1], v[0]), (v[0], v[1], v[5], v[4]), (v[2], v[3], v[4], v[5]),
                 (v[3], v[0], v[4]), (v[1], v[2], v[5])]
    for face in faces:
        bm.faces.new(face)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _finish(bm, name, at, color, rotation, kw, "roof")


def _slab_roof(name, width, depth, height, at, color, overhang, t, gable_color, rotation, kw):
    half = depth / 2
    slope = math.atan2(height, half)
    run = (half + overhang) / math.cos(slope)          # along the slope, from ridge to the overhanging eave
    nz = mathutils.Vector((0, math.sin(slope), math.cos(slope)))   # the slab's up direction (for the -y side)
    bm = bmesh.new()
    length = width + 2 * overhang
    for sign in (-1, 1):
        ridge = mathutils.Vector((0, 0, height))
        eave = ridge + mathutils.Vector((0, sign * run * math.cos(slope), -run * math.sin(slope)))
        up = mathutils.Vector((0, -sign * nz.y, nz.z))
        corners = []
        for base_pt in (ridge, eave):
            for x in (-length / 2, length / 2):
                corners.append(base_pt + mathutils.Vector((x, 0, 0)))
        top = [c + up * t for c in corners]
        v = [bm.verts.new(c) for c in corners + top]
        # 0 ridge-left, 1 ridge-right, 2 eave-left, 3 eave-right; +4 the same on top
        for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            bm.faces.new([v[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    roof_obj = _finish(bm, name, at, color, rotation, kw, "roof")
    roof_obj["jervis_shaped"] = True
    bevel(roof_obj, min(0.03, t * 0.3), 2)
    gables = bmesh.new()
    for x in (-width / 2, width / 2):
        tri = [gables.verts.new((x + dx, y, z)) for dx in (-0.1, 0.1) for y, z in ((-half, 0), (half, 0), (0, height))]
        for f in ((0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)):
            gables.faces.new([tri[i] for i in f])
    bmesh.ops.recalc_face_normals(gables, faces=gables.faces)
    _finish(gables, f"{name} Gables", at, gable_color, rotation, {}, "roof")
    _select(roof_obj)
    return roof_obj


_GEOMETRY_TYPES = ("MESH", "CURVE", "SURFACE", "META", "FONT")


def _meshes(obj, doing="shape"):
    """The mesh objects `obj` stands for: itself, or — for a group (an assembly's empty) — its mesh parts. A clear
    error instead of "'NoneType' object has no attribute 'vertices'" when there's no mesh at all."""
    obj = get(obj)
    if obj.type == "MESH" and obj.data is not None:
        return [obj]
    parts = [c for c in obj.children_recursive if c.type == "MESH" and c.data is not None]
    if parts:
        return parts
    raise ValueError(f"{obj.name!r} is {'a group' if obj.type == 'EMPTY' else 'a ' + obj.type.lower()} with no "
                     f"mesh to {doing}: name one of its parts instead.")


def _one_mesh(obj, doing="shape"):
    """The single mesh a deformation works on. A group with several parts can't be bent or tapered as one: say
    which parts it has, so the next try names one."""
    parts = _meshes(obj, doing)
    if len(parts) == 1:
        return parts[0]
    raise ValueError(f"{get(obj).name!r} is a group of {len(parts)} parts, so it can't be {doing}ed as one shape: "
                     f"{doing} one part ({', '.join(repr(p.name) for p in parts[:6])}).")


def hollow(obj, thickness=0.2, open_top=False):
    """Hollow out a box-like object, leaving walls `thickness` thick (and a floor; open_top keeps the top open):
    house walls you can cut doors and windows through, boxes, planters, drawers, cups."""
    obj = _one_mesh(obj, "hollow")
    _update()
    (x0, y0, z0), (x1, y1, z1) = bounds(obj)
    t = float(thickness)
    inner = box("__jervis_cutter", (x1 - x0 - 2 * t, y1 - y0 - 2 * t, (z1 - z0) - t + (1 if open_top else -t)),
                at=((x0 + x1) / 2, (y0 + y1) / 2, z0 + t))
    return cut(obj, inner)


def torus(name, radius=1.0, thickness=0.25, at=None, color=None, segments=32, rings=12, **kw):
    """A ring lying flat, centred on `at`."""
    at = _where(at, kw)
    bm = bmesh.new()
    grid = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        row = []
        for j in range(rings):
            b = 2 * math.pi * j / rings
            r = radius + thickness * math.cos(b)
            row.append(bm.verts.new((r * math.cos(a), r * math.sin(a), thickness * math.sin(b))))
        grid.append(row)
    for i in range(segments):
        for j in range(rings):
            bm.faces.new((grid[i][j], grid[(i + 1) % segments][j], grid[(i + 1) % segments][(j + 1) % rings],
                          grid[i][(j + 1) % rings]))
    kw.setdefault("smooth", "all")
    return _finish(bm, name, at, color, 0, kw, "torus")


def monkey(name, size=1.0, at=None, color=None, **kw):
    at = _where(at, kw)
    bm = bmesh.new()
    bmesh.ops.create_monkey(bm)
    bmesh.ops.scale(bm, vec=(size / 2,) * 3, verts=bm.verts)
    kw.setdefault("smooth", "all")
    return _finish(bm, name, at, color, 0, kw, "monkey")


def stairs(name, steps=5, width=1.0, step_height=0.2, step_depth=0.3, at=None, color=None, rotation=0, **kw):
    """A staircase rising along +y, its first step's front edge at `at`."""
    at = _where(at, kw)
    bm = bmesh.new()
    for i in range(int(steps)):
        part = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        bmesh.ops.scale(bm, vec=(width, step_depth, step_height * (i + 1)), verts=part)
        bmesh.ops.translate(bm, vec=(0, step_depth * (i + 0.5), step_height * (i + 1) / 2), verts=part)
    return _finish(bm, name, at, color, rotation, kw, "stairs")


# ---------- modeling: shapes beyond primitives ----------
# These are what make a result look modelled rather than assembled: organic lumps, tapered curving tubes, shapes
# spun from a profile, extruded outlines, frames, openings cut into walls, deformation, seeded variation and real
# materials. They are generic building blocks — the AI decides how to combine them for whatever is asked.

import random as _random


# Set by Jervis for each request, so code reusing the same seeds (often straight from an example) still gives each
# tree, rock or bush its own shape — while a step re-run within one request stays exactly the same.
SALT = 0


def rng(seed=0):
    """A seeded random generator, so a build is varied but repeatable: r = rng(7); r.uniform(0.8, 1.2)."""
    return _random.Random(f"{seed}/{SALT}")


def vary(value, amount=0.2, r=None, seed=None):
    """`value` (a number or a tuple) changed by up to ±amount (0.2 = 20%) — natural irregularity."""
    r = r or rng(seed)
    if isinstance(value, (tuple, list)):
        return tuple(float(v) * (1 + r.uniform(-amount, amount)) for v in value)
    return float(value) * (1 + r.uniform(-amount, amount))


def points_on_sphere(center, radius, count, seed=0, upper=False, jitter=0.15):
    """`count` points spread evenly over a sphere around `center` (upper=True: only its top half), each nudged a
    little — e.g. where foliage clusters, berries or decorations go."""
    r = rng(seed)
    cx, cy, cz = _vec3(center)
    golden = math.pi * (3 - math.sqrt(5))
    out = []
    count = max(1, int(count))
    for i in range(count):
        h = 1 - (i + 0.5) / count * (1 if upper else 2)
        ring = math.sqrt(max(0.0, 1 - h * h))
        angle = golden * i + r.uniform(-jitter, jitter) * 2
        k = radius * (1 + r.uniform(-jitter, jitter))
        out.append((cx + math.cos(angle) * ring * k, cy + math.sin(angle) * ring * k, cz + h * k))
    return out


def points_in_circle(center, radius, count, seed=0, min_gap=0.0):
    """`count` random points on the ground inside a circle, at least `min_gap` apart where possible — scattering
    rocks, flowers, trees, fence posts..."""
    r = rng(seed)
    cx, cy, cz = _vec3(center)
    out = []
    for _ in range(int(count) * 30):
        if len(out) >= count:
            break
        a, d = r.uniform(0, 2 * math.pi), radius * math.sqrt(r.random())
        p = (cx + math.cos(a) * d, cy + math.sin(a) * d, cz)
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= min_gap ** 2 for q in out):
            out.append(p)
    return out


def corners(x, y, width, depth, inset=0.05):
    """The four (x, y) spots just inside the corners of a width x depth rectangle centred on (x, y): where the legs of
    a table, bench, bed, desk or cabinet go — under its top, never outside it."""
    dx, dy = width / 2 - inset, depth / 2 - inset
    return [(x - dx, y - dy), (x + dx, y - dy), (x - dx, y + dy), (x + dx, y + dy)]


def _part_name(obj_name, part):
    """'Bench Seat' + 'Leg' -> 'Bench Leg' (the thing's name with the part's)."""
    words = obj_name.split()
    return " ".join((words[:-1] or words) + [part])


def legs_under(obj, count=4, inset=0.06, thickness=0.05, shape="round", color=None, name=None, taper_to=0.8):
    """Legs from the ground up to the underside of `obj` (a seat, table top, bed frame, desk, cabinet...), placed
    under its corners (count=4), or 3 for a stool, or 2 wide supports for a bench end each. They are always under it
    and always reach it — build the top at its height first, then call this. shape='round' (turned, slightly
    tapered) or 'square'. Returns the legs' names."""
    top_obj = get(obj)
    (x0, y0, z0), (x1, y1, z1) = bounds(top_obj)
    height = z0
    if height <= 0.02:
        raise ValueError(f"{top_obj.name!r} sits on the ground (its bottom is at z={round(z0, 3)}): build it at its "
                         "real height first (a seat at 0.45, a table top at 0.72), then call legs_under().")
    base = name or _part_name(top_obj.name, "Leg")
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, d = x1 - x0, y1 - y0
    if int(count) == 3:
        spots = [(cx + (w / 2 - inset) * math.cos(a), cy + (d / 2 - inset) * math.sin(a))
                 for a in (math.radians(90), math.radians(210), math.radians(330))]
    elif int(count) == 2:
        spots = [(x0 + inset + thickness, cy), (x1 - inset - thickness, cy)]
    else:
        spots = corners(cx, cy, w, d, inset + thickness / 2)
    made = []
    color = color if color is not None else (top_obj.active_material
                                             if top_obj.active_material else None)
    for i, (x, y) in enumerate(spots, 1):
        leg = f"{base} {i}"
        if int(count) == 2:
            box(leg, (thickness, d - 2 * inset, height), at=(x, y, 0), color=color, bevel=thickness * 0.15)
        elif shape == "square":
            box(leg, (thickness, thickness, height), at=(x, y, 0), color=color, bevel=thickness * 0.15)
        else:
            tube(leg, [(x, y, 0), (x, y, height)], radius=thickness / 2 * taper_to, radius_end=thickness / 2,
                 color=color, sides=12)
        made.append(get(leg).name)
    return made


def supports(above, below, count=2, thickness=0.04, inset=0.08, color=None, name=None):
    """Posts joining the underside of `above` (a backrest, a shelf, a sign, a roof) down to the top of `below` (a
    seat, a lower shelf, the ground if below=None), under `above`'s two ends (count=2) or four corners (count=4).
    Build both parts first, then call this. Returns the posts' names."""
    up = get(above)
    (x0, y0, z0), (x1, y1, z1) = bounds(up)
    floor = 0.0 if below is None else top(below)
    if z0 - floor <= 0.01:
        raise ValueError(f"{up.name!r} isn't above {below!r}: raise it first (e.g. move it up), then add supports.")
    base = name or _part_name(up.name, "Support")
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if int(count) >= 4:
        spots = corners(cx, cy, x1 - x0, y1 - y0, inset)
    elif (x1 - x0) >= (y1 - y0):
        spots = [(x0 + inset, cy), (x1 - inset, cy)]
    else:
        spots = [(cx, y0 + inset), (cx, y1 - inset)]
    color = color if color is not None else (up.active_material
                                             if up.active_material else None)
    made = []
    for i, (x, y) in enumerate(spots, 1):
        post = f"{base} {i}"
        box(post, (thickness, thickness, z0 - floor + 0.02), at=(x, y, floor - 0.01), color=color,
            bevel=thickness * 0.15)
        made.append(get(post).name)
    return made


def ring_points(center, radius, count, start=0.0):
    """`count` points evenly around a circle (degrees `start` for the first) — chairs round a table, columns,
    petals, spokes."""
    cx, cy, cz = _vec3(center)
    return [(cx + radius * math.cos(math.radians(start) + 2 * math.pi * i / count),
             cy + radius * math.sin(math.radians(start) + 2 * math.pi * i / count), cz) for i in range(int(count))]


def path(start, end, bend=(0, 0, 0), points=6, wobble=0.0, seed=0):
    """Points from `start` to `end`, bowed by `bend` (how far the middle is pushed, as x, y, z) and wobbling by
    `wobble` metres — a natural line for tube(): a curving trunk, a branch, a tail, a vine."""
    a, b, c = mathutils.Vector(_vec3(start)), mathutils.Vector(_vec3(end)), mathutils.Vector(_vec3(bend))
    mid = (a + b) / 2 + c
    r = rng(seed)
    out = []
    n = max(2, int(points))
    for i in range(n):
        t = i / (n - 1)
        p = (1 - t) ** 2 * a + 2 * (1 - t) * t * mid + t ** 2 * b
        if wobble and 0 < i < n - 1:
            p += mathutils.Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-0.3, 0.3))) * wobble
        out.append(tuple(p))
    return out


def _spline(points, resolution):
    """Catmull-Rom curve through the points, so a tube bends smoothly instead of kinking."""
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(resolution):
            t = s / resolution
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                              (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(points[-1])
    return out


def blob(name, radius=0.5, at=None, color=None, irregularity=0.25, squash=(1, 1, 1), detail=3, seed=0,
         flat_bottom=0.0, base=True, rotation=0, **kw):
    """An organic lump: a sphere pushed in and out by smooth noise. Rocks and boulders (irregularity 0.3-0.5,
    flat_bottom 0.2), foliage clusters and bushes (0.2-0.35), pebbles (0.1), clouds, snow piles, dough. squash
    stretches it, e.g. (1.3, 1, 0.6) for a flat wide rock. Each seed gives a different shape. Rests on `at`
    (base=False: centred on it)."""
    radius, at = _radius_or_at(radius, at, 0.5)
    at = _where(at, kw)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=max(1, min(5, int(detail))), radius=1.0)
    salted = seed + SALT * 0.6180339
    off = mathutils.Vector(((salted * 12.9898) % 97, (salted * 78.233) % 89, (salted * 37.719) % 83))
    sx, sy, sz = _vec3(squash, (1, 1, 1))
    noise = mathutils.noise.noise
    for v in bm.verts:
        d = v.co.normalized()
        n = noise(d * 1.2 + off) + 0.35 * noise(d * 2.7 + off * 1.3) + 0.1 * noise(d * 6.0 + off * 0.7)
        k = max(0.25, 1 + irregularity * n)
        v.co = mathutils.Vector((d.x * k * sx, d.y * k * sy, d.z * k * sz)) * radius
    if flat_bottom:
        zs = [v.co.z for v in bm.verts]
        cut = min(zs) + (max(zs) - min(zs)) * float(flat_bottom)
        for v in bm.verts:
            v.co.z = max(v.co.z, cut)
    if base:
        low = min(v.co.z for v in bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0, -low), verts=bm.verts)
    kw.setdefault("smooth", "all" if not flat_bottom else True)
    obj = _finish(bm, name, at, color, rotation, kw, "blob")
    obj["jervis_shaped"] = True
    return obj


def tube(name, points, radius=0.1, radius_end=None, color=None, sides=12, smooth=True, cap=True, resolution=4,
         **kw):
    """A round tube following `points` (world positions, first to last), tapering from `radius` to `radius_end`:
    tree trunks and branches, curved chair legs, pipes, handles, horns, tails, cables, arches. With 3+ points it
    curves smoothly through them (use path() to make the points). Its origin is the first point."""
    pts = [mathutils.Vector(_vec3(p)) for p in points]
    pts = [p for i, p in enumerate(pts) if i == 0 or (p - pts[i - 1]).length > 1e-5]
    if len(pts) < 2:
        raise ValueError("tube() needs at least two different points")
    # A path that doubles back on itself (a zig-zag from too much wobble) would crumple the tube: drop such points.
    kept = [pts[0]]
    for p in pts[1:-1]:
        a, b = p - kept[-1], pts[-1] - p
        if a.length > 1e-6 and b.length > 1e-6 and a.angle(b) < math.radians(100):
            kept.append(p)
    pts = kept + [pts[-1]]
    if smooth and len(pts) > 2:
        pts = _spline(pts, max(1, int(resolution)))
    r0 = float(radius)
    r1 = r0 if radius_end is None else float(radius_end)
    origin = pts[0].copy()
    bm = bmesh.new()
    sides = max(3, int(sides))
    angles = [2 * math.pi * k / sides for k in range(sides)]
    rings, normal, previous = [], None, None
    n = len(pts)
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
        if normal is None:
            helper = mathutils.Vector((0, 0, 1)) if abs(t.z) < 0.9 else mathutils.Vector((1, 0, 0))
            normal = t.cross(helper).normalized()
        else:   # carry the frame along the curve without twisting
            normal = previous.rotation_difference(t) @ normal
            normal = (normal - t * normal.dot(t)).normalized()
        previous = t
        side = t.cross(normal)
        rr = max(1e-4, r0 + (r1 - r0) * (i / (n - 1)))
        rings.append([bm.verts.new(p - origin + (normal * math.cos(a) + side * math.sin(a)) * rr) for a in angles])
    for i in range(n - 1):
        for k in range(sides):
            bm.faces.new((rings[i][k], rings[i][(k + 1) % sides], rings[i + 1][(k + 1) % sides], rings[i + 1][k]))
    if cap:
        bm.faces.new(rings[0])
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    kw["smooth"] = "all" if smooth else False
    obj = _finish(bm, name, tuple(origin), color, 0, kw, "tube")
    obj["jervis_shaped"] = True
    return obj


def lathe(name, profile, at=None, color=None, segments=32, rotation=0, **kw):
    """Spin a side profile [(radius, height), ...] — listed bottom to top — around the vertical axis: vases, pots,
    cups, bottles, columns, balusters, lamp bases and shades, mushrooms, fountains, wheels' hubs, a trunk with a
    flared base. A radius of 0 closes the shape at that height. Stands on `at`."""
    at = _where(at, kw)
    prof = [(max(0.0, float(r)), float(z)) for r, z in profile]
    if len(prof) < 2:
        raise ValueError("lathe() needs at least two (radius, height) points")
    bm = bmesh.new()
    segments = max(3, int(segments))
    rings = []
    for r, z in prof:
        if r < 1e-6:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(2 * math.pi * k / segments),
                                        r * math.sin(2 * math.pi * k / segments), z)) for k in range(segments)])
    for a, b in zip(rings, rings[1:]):
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            for k in range(segments):
                bm.faces.new((a[0], b[k], b[(k + 1) % segments]))
        elif len(b) == 1:
            for k in range(segments):
                bm.faces.new((a[k], a[(k + 1) % segments], b[0]))
        else:
            for k in range(segments):
                bm.faces.new((a[k], a[(k + 1) % segments], b[(k + 1) % segments], b[k]))
    for ring in (rings[0], rings[-1]):
        if len(ring) > 2:
            bm.faces.new(ring)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    low = min(z for _, z in prof)
    if low:
        bmesh.ops.translate(bm, vec=(0, 0, -low), verts=bm.verts)
    kw.setdefault("smooth", True)
    obj = _finish(bm, name, at, color, rotation, kw, "lathe")
    obj["jervis_shaped"] = True
    return obj


def extrude_shape(name, outline, height=0.1, at=None, color=None, axis="z", rotation=0, **kw):
    """A flat outline [(x, y), ...] (drawn around 0, 0) made solid, `height` thick: any floor plan, a gable wall,
    an arched door, a sign, a leaf, a table top or shelf of any shape. axis='z' lies flat and rises from `at`;
    axis='y' stands upright facing the front (outline x = across, outline y = up), axis='x' faces the side."""
    at = _where(at, kw)
    pts = [(float(x), float(y)) for x, y in outline]
    if len(pts) < 3:
        raise ValueError("extrude_shape() needs at least three outline points")
    bm = bmesh.new()
    face = bm.faces.new([bm.verts.new((x, y, 0)) for x, y in pts])
    top = bmesh.ops.extrude_face_region(bm, geom=[face])
    moved = [g for g in top["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, float(height)), verts=moved)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    axis = str(axis or "z").lower()[:1]
    if axis in ("x", "y"):
        bmesh.ops.translate(bm, vec=(0, 0, -float(height) / 2), verts=bm.verts)
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=mathutils.Matrix.Rotation(math.radians(90), 4, "X"))
        if axis == "x":
            bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                             matrix=mathutils.Matrix.Rotation(math.radians(90), 4, "Z"))
    return _finish(bm, name, at, color, rotation, kw, "extrude")


def arc_points(center, radius, start=0, end=180, count=12):
    """Points along a circular arc (degrees, 0 = +x, 90 = up) — the round top of an arched door or window for
    extrude_shape(), a curved bench, a bridge."""
    cx, cy = (list(center) + [0, 0])[:2]
    return [(cx + radius * math.cos(math.radians(start + (end - start) * i / (count - 1))),
             cy + radius * math.sin(math.radians(start + (end - start) * i / (count - 1)))) for i in range(count)]


def _add_box(bm, center, size):
    verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    bmesh.ops.scale(bm, vec=_vec3(size), verts=verts)
    bmesh.ops.translate(bm, vec=_vec3(center), verts=verts)
    return verts


def frame(name, width=1.0, height=1.2, depth=0.12, border=0.08, at=None, color=None, axis="y", bars=0,
          rotation=0, **kw):
    """An upright rectangular frame whose bottom edge sits at `at`: window and door frames, picture frames,
    gates, doorways. axis='y' faces front/back (for a wall running along x), 'x' faces the sides. bars=1 adds a
    cross of glazing bars (a window), bars=2 a double cross."""
    at = _where(at, kw)
    w, h, d, b = float(width), float(height), float(depth), float(border)
    bm = bmesh.new()
    _add_box(bm, (-(w - b) / 2, 0, h / 2), (b, d, h))
    _add_box(bm, ((w - b) / 2, 0, h / 2), (b, d, h))
    _add_box(bm, (0, 0, b / 2), (w - 2 * b, d, b))
    _add_box(bm, (0, 0, h - b / 2), (w - 2 * b, d, b))
    for i in range(int(bars)):
        frac = (i + 1) / (int(bars) + 1)
        _add_box(bm, (-w / 2 + w * frac, 0, h / 2), (b * 0.5, d * 0.7, h - 2 * b))
        _add_box(bm, (0, 0, h * frac), (w - 2 * b, d * 0.7, b * 0.5))
    if str(axis).lower()[:1] == "x":
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=mathutils.Matrix.Rotation(math.radians(90), 4, "Z"))
    obj = _finish(bm, name, at, color, rotation, kw, "frame")
    bevel(obj, min(b, d) * 0.15, 2)
    return obj


def _bake(obj):
    """Apply an object's modifiers for good (through the evaluated mesh: works where operators don't)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(evaluated)
    old = obj.data
    obj.modifiers.clear()
    obj.data = mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)


def cut(obj, cutter, keep_cutter=False):
    """Carve `cutter`'s shape out of `obj` (boolean difference): openings, holes, notches, hollows. Raises (and
    leaves `obj` as it was) when the cutter misses it, or would leave nothing of it."""
    obj, cutter = _one_mesh(obj, "cut"), get(cutter)
    (a0, a1), (b0, b1) = bounds(obj), bounds(cutter)
    if any(a1[i] < b0[i] or b1[i] < a0[i] for i in range(3)):
        if not keep_cutter:
            bpy.data.objects.remove(cutter, do_unlink=True)
        raise ValueError(f"The cut misses {obj.name!r}: the cutter spans x {b0[0]:.2f}..{b1[0]:.2f}, y "
                         f"{b0[1]:.2f}..{b1[1]:.2f}, z {b0[2]:.2f}..{b1[2]:.2f} but {obj.name!r} spans x "
                         f"{a0[0]:.2f}..{a1[0]:.2f}, y {a0[1]:.2f}..{a1[1]:.2f}, z {a0[2]:.2f}..{a1[2]:.2f}. Put `at` "
                         "on the object's face.")
    backup = obj.data.copy()
    had = len(obj.data.vertices)
    mods = [(m.name, m.type) for m in obj.modifiers]   # keep a bevel etc. working after the cut
    kept = {m.name: (m.width, m.segments) for m in obj.modifiers if m.type == "BEVEL"}
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    mod = obj.modifiers.new("Jervis cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    try:
        mod.solver = "EXACT"
    except Exception:
        pass
    _bake(obj)
    if had and not len(obj.data.vertices):
        emptied = obj.data
        obj.data = backup
        if emptied.users == 0:
            bpy.data.meshes.remove(emptied)
        for name_, kind in mods:
            if kind == "BEVEL":
                bevel(obj, *kept[name_])
        if not keep_cutter:
            bpy.data.objects.remove(cutter, do_unlink=True)
        raise ValueError(f"Cutting {obj.name!r} would remove all of it (the cutter is bigger than it): make the "
                         "opening smaller than the object.")
    if backup.users == 0:
        bpy.data.meshes.remove(backup)
    for name_, kind in mods:
        if kind == "BEVEL":
            bevel(obj, *kept[name_])
    if not keep_cutter:
        bpy.data.objects.remove(cutter, do_unlink=True)
    obj["jervis_shaped"] = True
    return obj


def opening(obj, width=1.0, height=1.2, at=None, axis="y", depth=None, **kw):
    """Cut a rectangular hole through a wall: `at` is the bottom centre of the hole. axis='y' for a wall facing
    front/back, 'x' for one facing the sides. Put a frame() (and a pane) in it afterwards."""
    at = _where(at, kw)
    deep = float(depth or 2.0)
    size = (width, deep, height) if str(axis).lower()[:1] != "x" else (deep, width, height)
    cutter = box("__jervis_cutter", size, at=at)
    return cut(obj, cutter)


def densify(obj, cuts=2):
    """Add more geometry without changing the shape, so deform functions (bend, twist, roughen) have something to
    work with — a plain box has only 8 corners. A group: each of its parts."""
    for part in _meshes(obj, "densify"):
        bm = bmesh.new()
        bm.from_mesh(part.data)
        bmesh.ops.subdivide_edges(bm, edges=bm.edges, cuts=int(cuts), use_grid_fill=True)
        bm.to_mesh(part.data)
        bm.free()
    return get(obj)


def subdivide(obj, levels=2):
    """Smooth and round the whole shape (subdivision surface): soft furniture, cushions, organic forms."""
    if isinstance(obj, (list, tuple)):
        return [subdivide(o, levels) for o in obj]
    for part in _meshes(obj, "subdivide"):
        mod = part.modifiers.get("Subdivision") or part.modifiers.new("Subdivision", "SUBSURF")
        mod.levels = mod.render_levels = max(0, min(4, int(levels)))
        _auto_smooth(part, 180)
        part["jervis_shaped"] = True
    return get(obj)


def solidify(obj, thickness=0.05):
    """Give a flat surface real thickness (leaves, sheets, cloth, a lampshade)."""
    for part in _meshes(obj, "solidify"):
        mod = part.modifiers.get("Solidify") or part.modifiers.new("Solidify", "SOLIDIFY")
        mod.thickness = float(thickness)
    return get(obj)


def mirror(obj, axis="x"):
    """Mirror an object across its own origin (symmetrical things: build one half)."""
    obj = _one_mesh(obj, "mirror")
    mod = obj.modifiers.new("Mirror", "MIRROR")
    mod.use_axis = [a == str(axis).lower()[:1] for a in "xyz"]
    return obj


def _deform(obj, fn, doing="deform", per_part=False):
    if per_part:   # roughen: noise works on each part of a group alike
        for part in _meshes(obj, doing):
            _deform(part, fn, doing)
        return get(obj)
    obj = _one_mesh(obj, doing)
    vs = obj.data.vertices
    if not len(vs):
        return obj
    zs = [v.co.z for v in vs]
    low, high = min(zs), max(zs)
    span = (high - low) or 1.0
    for v in vs:
        v.co = fn(v.co.copy(), (v.co.z - low) / span, span, v)
    obj.data.update()
    obj["jervis_shaped"] = True
    return obj


def taper(obj, amount=0.5, axis="z"):
    """Narrow an object toward its top: 0.5 = half as wide at the top (posts, trunks, vases, legs, tails).
    A negative amount widens it."""
    return _deform(obj, lambda co, t, h, v: mathutils.Vector((co.x * (1 - amount * t), co.y * (1 - amount * t), co.z)),
                   "taper")


def bend(obj, amount=0.3, direction=(1, 0)):
    """Curve an object sideways as it rises: its top moves `amount` metres in `direction` (x, y) — a leaning
    trunk, a curved blade of grass, a horn, a drooping lamp."""
    dx, dy = (list(direction) + [0, 0])[:2]
    return _deform(obj, lambda co, t, h, v: mathutils.Vector((co.x + amount * dx * t * t,
                                                              co.y + amount * dy * t * t, co.z)), "bend")


def twist(obj, degrees=45):
    """Twist an object around its vertical axis, more toward the top (spirals, twisted columns, horns)."""
    def fn(co, t, h, v):
        a = math.radians(degrees) * t
        return mathutils.Vector((co.x * math.cos(a) - co.y * math.sin(a), co.x * math.sin(a) + co.y * math.cos(a), co.z))
    return _deform(obj, fn, "twist")


def roughen(obj, strength=0.05, scale=3.0, seed=0):
    """Push the surface in and out by smooth noise (metres): weathered stone, bark, uneven ground, lumpy clay.
    Needs enough geometry — use densify() first on boxes."""
    off = mathutils.Vector(((seed * 7.31) % 53, (seed * 3.17) % 47, (seed * 5.71) % 41))
    noise = mathutils.noise.noise
    return _deform(obj, lambda co, t, h, v: co + v.normal * strength * noise(co * scale + off), "roughen",
                   per_part=True)


def assemble(name, parts=None, at=None):
    """Make several parts one thing: they go in a collection called `name` and under a parent (an empty called
    `name`, at their base), so the whole thing moves, turns and scales together. Do this last for anything made of
    several parts. Without `parts`, it takes every part made in this request whose name starts with `name`
    ('Tree 1' gathers 'Tree 1 Trunk', 'Tree 1 Leaves 3'...). Calling it again (after adding a part) regroups
    everything in place — nothing moves."""
    name = str(name).strip()
    old_root = bpy.data.objects.get(ALIASES.get(name, name))
    freed = []
    if old_root is not None and old_root.type == "EMPTY" and old_root.name not in PROTECTED:
        # Regrouping: free the old group's parts first, exactly where they are (removing an empty with children
        # would otherwise leave them at their positions relative to it — scattered). They stay in the group.
        _update()
        for child in list(old_root.children):
            world = child.matrix_world.copy()
            child.parent = None
            child.matrix_world = world
            freed.append(child.name)
    elif old_root is not None and old_root.type != "EMPTY" and old_root.name not in PROTECTED \
            and old_root.users_collection:
        # box('Bench', ...) then assemble('Bench'): that shape is a part of the bench, not in the group's way
        body = _fresh_name(f"{name} Body") if bpy.data.objects.get(f"{name} Body") else f"{name} Body"
        old_root.name = body
        freed.append(body)
        old_root = None
    if parts is None:
        mine = [o for o in _scene().objects if o.name not in PROTECTED and o.type != "EMPTY"
                and not o.name.startswith("__")]
        for prefix in (name.lower() + " ", name.split()[0].lower() + " "):
            parts = [o.name for o in mine if o.name.lower().startswith(prefix)]
            if parts:
                break
        else:
            parts = [o.name for o in mine]
    elif isinstance(parts, str):
        parts = [parts]
    parts = [get(p) for p in list(parts) + [f for f in freed if f not in parts]]
    parts = [p for p in parts if p.name != name and not p.name.startswith("__")]
    if not parts:
        raise ValueError(f"assemble({name!r}) found no parts: name them '{name} <Part>' (e.g. '{name} Trunk') or pass "
                         "their names as a list.")
    # Never sweep up what was already in the scene ("everything named 'Tree ...'" can include the user's own tree),
    # unless grouping existing things is all this was asked to do.
    new_parts = [p for p in parts if p.name not in PROTECTED]
    parts = new_parts or parts
    chosen = set(parts)
    parts = [p for p in dict.fromkeys(parts) if not any(a in chosen for a in _ancestors(p))]   # sub-groups move whole
    _update()
    pts = [pt for p in parts for pt in _world_points(p)]
    base = _vec3(at) if at is not None else ((min(v.x for v in pts) + max(v.x for v in pts)) / 2,
                                            (min(v.y for v in pts) + max(v.y for v in pts)) / 2, min(v.z for v in pts))
    if old_root is not None and old_root.type == "EMPTY" and old_root.name not in PROTECTED \
            and old_root.users_collection:
        # Regrouping in the same request: the very same group object, moved to the parts' new base — so undoing
        # this step puts back exactly the group that was there.
        root = old_root
        root.location, root.rotation_euler, root.scale = base, (0, 0, 0), (1, 1, 1)
        name = root.name
    else:
        name = _make_room_for(name)
        root = bpy.data.objects.new(name, None)
        root.empty_display_type = "PLAIN_AXES"
        root.location = base
    coll = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if coll.name not in _scene().collection.children:
        _scene().collection.children.link(coll)
    if coll not in root.users_collection:
        coll.objects.link(root)
    _update()
    for p in parts:
        world = p.matrix_world.copy()
        p.parent = root
        p.matrix_world = world
        for o in [p] + list(p.children_recursive):
            if coll not in o.users_collection:
                coll.objects.link(o)
            if _scene().collection in o.users_collection and len(o.users_collection) > 1:
                _scene().collection.objects.unlink(o)
    root["jervis_kind"] = "assembly"
    return root


def _ancestors(obj):
    out, seen = [], set()
    p = obj.parent
    while p is not None and p.name not in seen:
        seen.add(p.name)
        out.append(p)
        p = p.parent
    return out


# ---------- materials that look like something ----------
# Procedural (no image files): textures driven by the object's own coordinates, so nothing needs unwrapping.
# In Blender's Solid view they show their main colour; in Material Preview / Rendered, the full surface.

PRESETS = {
    "bark": dict(colors=[(0.07, 0.045, 0.025), (0.22, 0.14, 0.08)], pattern="streaks", scale=5.0, bump=0.9, rough=0.95),
    "wood": dict(colors=[(0.27, 0.14, 0.065), (0.38, 0.22, 0.105)], pattern="grain", scale=4.0, bump=0.15, rough=0.5),
    "dark wood": dict(colors=[(0.07, 0.035, 0.017), (0.12, 0.065, 0.03)], pattern="grain", scale=4.0, bump=0.15, rough=0.45),
    "light wood": dict(colors=[(0.55, 0.38, 0.2), (0.68, 0.5, 0.29)], pattern="grain", scale=4.0, bump=0.1, rough=0.5),
    "leaves": dict(colors=[(0.02, 0.08, 0.015), (0.09, 0.24, 0.035)], pattern="noise", scale=9.0, bump=0.7, rough=0.65),
    "autumn leaves": dict(colors=[(0.45, 0.1, 0.02), (0.9, 0.45, 0.05)], pattern="noise", scale=7.0, bump=0.5, rough=0.6),
    "grass": dict(colors=[(0.04, 0.16, 0.02), (0.12, 0.33, 0.04)], pattern="noise", scale=12.0, bump=0.3, rough=0.8),
    "moss": dict(colors=[(0.06, 0.15, 0.02), (0.2, 0.32, 0.05)], pattern="noise", scale=15.0, bump=0.6, rough=0.9),
    "stone": dict(colors=[(0.13, 0.125, 0.115), (0.33, 0.315, 0.29)], pattern="cells", scale=3.0, bump=0.8, rough=0.85),
    "rock": dict(colors=[(0.07, 0.068, 0.062), (0.26, 0.245, 0.22)], pattern="cells", scale=1.6, bump=0.9, rough=0.9),
    "brick": dict(colors=[(0.32, 0.08, 0.04), (0.5, 0.17, 0.08)], mortar=(0.6, 0.57, 0.52), pattern="brick", scale=4.0, bump=0.4, rough=0.85),
    "roof tiles": dict(colors=[(0.35, 0.08, 0.03), (0.55, 0.15, 0.06)], mortar=(0.2, 0.05, 0.02), pattern="tiles", scale=3.0, bump=0.6, rough=0.7),
    "plaster": dict(colors=[(0.72, 0.68, 0.6), (0.85, 0.82, 0.75)], pattern="noise", scale=6.0, bump=0.2, rough=0.9),
    "concrete": dict(colors=[(0.35, 0.35, 0.33), (0.52, 0.51, 0.49)], pattern="noise", scale=8.0, bump=0.3, rough=0.9),
    "metal": dict(colors=[(0.5, 0.5, 0.52), (0.62, 0.62, 0.64)], pattern="noise", scale=20.0, bump=0.05, rough=0.35, metallic=1.0),
    "steel": dict(colors=[(0.45, 0.46, 0.5), (0.55, 0.56, 0.6)], pattern="noise", scale=20.0, bump=0.03, rough=0.25, metallic=1.0),
    "iron": dict(colors=[(0.08, 0.08, 0.08), (0.18, 0.17, 0.16)], pattern="noise", scale=10.0, bump=0.2, rough=0.6, metallic=1.0),
    "gold": dict(colors=[(0.75, 0.5, 0.12), (0.95, 0.72, 0.25)], pattern="noise", scale=20.0, bump=0.02, rough=0.2, metallic=1.0),
    "copper": dict(colors=[(0.55, 0.25, 0.12), (0.8, 0.42, 0.22)], pattern="noise", scale=20.0, bump=0.02, rough=0.3, metallic=1.0),
    "glass": dict(colors=[(0.75, 0.87, 0.95), (0.8, 0.9, 0.97)], pattern="none", rough=0.03, transmission=1.0),
    "water": dict(colors=[(0.05, 0.25, 0.4), (0.1, 0.4, 0.55)], pattern="noise", scale=4.0, bump=0.3, rough=0.05, transmission=0.7),
    "fabric": dict(colors=[(0.3, 0.3, 0.32), (0.4, 0.4, 0.42)], pattern="noise", scale=60.0, bump=0.2, rough=1.0),
    "leather": dict(colors=[(0.18, 0.08, 0.03), (0.3, 0.15, 0.07)], pattern="cells", scale=40.0, bump=0.2, rough=0.6),
    "ceramic": dict(colors=[(0.85, 0.85, 0.82), (0.9, 0.9, 0.88)], pattern="none", rough=0.15),
    "plastic": dict(colors=[(0.6, 0.6, 0.6), (0.62, 0.62, 0.62)], pattern="none", rough=0.4),
    "rubber": dict(colors=[(0.02, 0.02, 0.02), (0.05, 0.05, 0.05)], pattern="noise", scale=30.0, bump=0.1, rough=0.85),
    "sand": dict(colors=[(0.55, 0.45, 0.28), (0.75, 0.64, 0.42)], pattern="noise", scale=25.0, bump=0.3, rough=0.95),
    "dirt": dict(colors=[(0.12, 0.08, 0.04), (0.25, 0.17, 0.09)], pattern="noise", scale=10.0, bump=0.6, rough=1.0),
    "snow": dict(colors=[(0.85, 0.88, 0.92), (0.97, 0.98, 1.0)], pattern="noise", scale=6.0, bump=0.2, rough=0.6),
}
_PRESET_ALIASES = {"tree bark": "bark", "foliage": "leaves", "leaf": "leaves", "tiles": "roof tiles",
                   "roof tile": "roof tiles", "bricks": "brick", "cobblestone": "stone", "marble": "ceramic",
                   "cloth": "fabric", "wooden": "wood", "timber": "wood", "pine": "light wood", "oak": "wood",
                   "walnut": "dark wood", "stucco": "plaster", "chrome": "steel", "silver metal": "steel"}


def preset_of(name):
    key = str(name or "").strip().lower()
    key = _PRESET_ALIASES.get(key, key)
    return key if key in PRESETS else None


def _is_textured(mat):
    try:
        return bool(mat and mat.use_nodes and any(n.type.startswith("TEX_") for n in mat.node_tree.nodes))
    except Exception:
        return False


def _shift(rgb, r, amount):
    """A colour nudged in brightness and hue — no two leaves, stones or planks exactly alike."""
    k = 1 + r.uniform(-amount, amount)
    return tuple(max(0.0, min(1.0, c * k * (1 + r.uniform(-amount, amount) * 0.5))) for c in rgb)


def textured_material(preset, vary=0.0, seed=0, name=None):
    """A procedural material from PRESETS ('bark', 'wood', 'leaves', 'stone', 'brick', 'roof tiles', 'plaster',
    'metal', 'glass'...). vary=0.15 with different seeds gives each copy a slightly different shade."""
    key = preset_of(preset)
    spec = PRESETS[key]
    label = name or (f"Jervis {key}" + (f" {seed}" if vary else ""))
    existing = bpy.data.materials.get(label)
    if existing is not None:
        return existing
    r = rng(seed)
    colors = [_shift(c, r, vary) if vary else c for c in spec["colors"]]
    mat = bpy.data.materials.new(label)
    avg = tuple((a + b) / 2 for a, b in zip(*colors))
    mat.diffuse_color = (*avg, 1)
    mat.roughness = spec.get("rough", 0.5)
    mat.metallic = spec.get("metallic", 0.0)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = spec.get("rough", 0.5)
    bsdf.inputs["Metallic"].default_value = spec.get("metallic", 0.0)
    if spec.get("transmission"):
        for key_ in ("Transmission Weight", "Transmission"):
            if key_ in bsdf.inputs:
                bsdf.inputs[key_].default_value = spec["transmission"]
        if spec["transmission"] >= 0.9:
            # EEVEE draws transmission without ray tracing as dark: clear glass is blended instead, so a lit shop,
            # a room or a balcony shows through it (Cycles is unaffected)
            bsdf.inputs["Alpha"].default_value = 0.18
            try:
                mat.surface_render_method = "BLENDED"
            except (AttributeError, TypeError):
                try:
                    mat.blend_method = "BLEND"
                except (AttributeError, TypeError):
                    pass
    pattern = spec.get("pattern", "noise")
    if pattern == "none":
        bsdf.inputs["Base Color"].default_value = (*avg, 1)
        return mat
    coords = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    if pattern in ("brick", "tiles"):
        # Courses run horizontally on every wall, whichever way it faces: across = x + y, up = z.
        split = nodes.new("ShaderNodeSeparateXYZ")
        across = nodes.new("ShaderNodeMath")
        across.operation = "ADD"
        joined = nodes.new("ShaderNodeCombineXYZ")
        links.new(coords.outputs["Object"], split.inputs["Vector"])
        links.new(split.outputs["X"], across.inputs[0])
        links.new(split.outputs["Y"], across.inputs[1])
        links.new(across.outputs["Value"], joined.inputs["X"])
        links.new(split.outputs["Z"], joined.inputs["Y"])
        links.new(joined.outputs["Vector"], mapping.inputs["Vector"])
    else:
        links.new(coords.outputs["Object"], mapping.inputs["Vector"])
    scale = spec.get("scale", 5.0)
    stretch = {"streaks": (1, 1, 0.15), "grain": (1, 1, 0.12)}.get(pattern, (1, 1, 1))
    mapping.inputs["Scale"].default_value = tuple(scale * s for s in stretch)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*colors[0], 1)
    ramp.color_ramp.elements[1].color = (*colors[1], 1)
    if pattern in ("brick", "tiles"):
        tex = nodes.new("ShaderNodeTexBrick")
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        tex.inputs["Color1"].default_value = (*colors[0], 1)
        tex.inputs["Color2"].default_value = (*colors[1], 1)
        tex.inputs["Mortar"].default_value = (*spec.get("mortar", (0.5, 0.5, 0.5)), 1)
        tex.inputs["Scale"].default_value = 1.0
        tex.inputs["Mortar Size"].default_value = spec.get("mortar_size", 0.015 if pattern == "brick" else 0.03)
        if pattern == "tiles":
            tex.inputs["Row Height"].default_value = spec.get("row_height", 0.15)
            tex.inputs["Brick Width"].default_value = spec.get("brick_width", 0.25)
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        height = tex.outputs["Fac"]
    else:
        if pattern == "cells":
            # colour from broad mottling, relief from cracks/cells: stone, rock, leather
            tex = nodes.new("ShaderNodeTexNoise")
            tex.inputs["Detail"].default_value = 10.0
            tex.inputs["Roughness"].default_value = 0.6
            cells = nodes.new("ShaderNodeTexVoronoi")
            cells.feature = "DISTANCE_TO_EDGE"
            links.new(mapping.outputs["Vector"], cells.inputs["Vector"])
            cells.inputs["Scale"].default_value = 3.0
            out = tex.outputs["Fac"]
        elif pattern in ("grain", "streaks"):
            tex = nodes.new("ShaderNodeTexWave")
            tex.wave_type = "RINGS" if pattern == "grain" else "BANDS"
            tex.inputs["Distortion"].default_value = 6.0 if pattern == "streaks" else 3.0
            tex.inputs["Detail"].default_value = 4.0
            out = tex.outputs["Fac"]
        else:
            tex = nodes.new("ShaderNodeTexNoise")
            tex.inputs["Detail"].default_value = 8.0
            out = tex.outputs["Fac"]
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(out, ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        height = cells.outputs["Distance"] if pattern == "cells" else out
    if spec.get("bump"):
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = min(1.0, spec["bump"])
        bump.inputs["Distance"].default_value = 0.02
        links.new(height, bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# ---------- changing what's there ----------

def _numbers(args):
    """move('Box', 1, 2, 3) / scale('Box', 1, 1, 2): models often spread a vector into separate arguments."""
    if len(args) == 1:
        return args[0]
    return tuple(args) if args else None


def move(obj, *to_args, to=None, by=None, **kw):
    """Move an object (a group moves with all its parts): to=(x, y, z) a WORLD position for its origin (a kit
    shape's origin is its bottom centre, a group's its base), by=(dx, dy, dz) a shift. A part inside a group moves
    in the world the same way — never relative to the group."""
    obj = get(obj)
    to = to if to is not None else _numbers(to_args)
    to = to if to is not None else kw.get("at", kw.get("location"))
    _update()
    world = obj.matrix_world.copy()
    if to is not None:
        world.translation = mathutils.Vector(_vec3(to))
    if by is not None:
        world.translation = world.translation + mathutils.Vector(_vec3(by))
    if any(v != v for v in world.translation):
        raise ValueError(f"move({obj.name!r}): the position isn't a real number (check the arithmetic before it).")
    obj.matrix_world = world
    return obj


def rotate(obj, degrees=90, axis="z"):
    obj = get(obj)
    index = "xyz".index(str(axis).lower()[0])
    rot = list(obj.rotation_euler)
    rot[index] += math.radians(float(degrees))
    obj.rotation_euler = rot
    return obj


def scale(obj, *factor_args, factor=None, **kw):
    """Multiply an object's size: scale('Box', 2), scale('Box', (1, 1, 2)), scale('Box', 1, 1, 2), scale('Box', z=2)."""
    obj = get(obj)
    factor = factor if factor is not None else _numbers(factor_args)
    if factor is None:
        factor = (kw.get("x", 1), kw.get("y", 1), kw.get("z", 1)) if kw else 2.0
    f = _vec3(factor)
    obj.scale = tuple(s * k for s, k in zip(obj.scale, f))
    return obj


def resize(obj, size):
    """Set an object's real size in metres: resize('Table', (2, 1, 0.8)) — a group as a whole, from its base."""
    obj = get(obj)
    target = _vec3(size)
    dims = globals()["size"](obj)
    if not any(dims):
        raise ValueError(f"{obj.name!r} has no size to change (it has no geometry).")
    obj.scale = tuple(s * (t / d if d > 1e-6 and t > 0 else 1) for s, t, d in zip(obj.scale, target, dims))
    return obj


def trash(obj):
    """Take an object out of the scene but keep it (so Jervis's undo can put it back): see purge_trash."""
    obj = get(obj)
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    obj.use_fake_user = True
    obj["jervis_trash"] = True
    return obj.name


def _rewire_holes():
    """Every "Jervis hole <thing>" Boolean (a pool or pond dug into a ground plane) cuts only while its thing's cutter
    is really in the scene: after a delete the ground is whole again, after an undo the hole is back."""
    if bpy is None:
        return
    for g in bpy.data.objects:
        for mod in getattr(g, "modifiers", []):
            if mod.type != "BOOLEAN" or not mod.name.startswith("Jervis hole "):
                continue
            cutter = bpy.data.objects.get(mod.name[len("Jervis hole "):] + " Ground Cut")
            live = cutter is not None and bool(cutter.users_collection) and not cutter.get("jervis_trash")
            if live:
                mod.object = cutter
                try:   # hiding is per view layer: a cutter linked back in (an undo) shows again unless re-hidden
                    cutter.hide_set(True)
                    cutter.hide_render = True
                except Exception:
                    pass
            mod.show_viewport = mod.show_render = live


def purge_trash():
    """Really delete what trash() kept (called before each new request: by then "undo" has moved on)."""
    gone = [o.name for o in bpy.data.objects if o.get("jervis_trash") and not o.users_collection]
    for name in gone:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    return gone


def delete(*objs):
    """Remove objects (undoably). A group goes with all its parts."""
    names = []
    for o in objs:
        for item in (o if isinstance(o, (list, tuple)) else [o]):
            item = get(item)
            for part in list(item.children_recursive):
                if part.users_collection:
                    names.append(trash(part))
            names.append(trash(item))
    _rewire_holes()
    return names


def duplicate(obj, name=None, offset=(0, 0, 0), at=None, **kw):
    """A copy of an object — of a group, with all its parts ('Tree 1' -> 'Tree 2' with 'Tree 2 Trunk'...)."""
    src = get(obj)
    name = name or kw.get("new_name") or kw.get("new")
    at = at if at is not None else kw.get("location", kw.get("to"))
    new_name = name or src.name + " copy"
    if bpy.data.objects.get(ALIASES.get(new_name, new_name)) is not src:
        new_name = _make_room_for(new_name)
    _update()
    family = [src] + list(src.children_recursive)
    copies = {}
    for o in family:
        c = o.copy()
        if o.data is not None:
            c.data = o.data.copy()
        if o is src:
            c.name = new_name
        else:
            part = o.name[len(src.name):].strip() if o.name.startswith(src.name) else o.name
            c.name = _make_room_for(f"{new_name} {part}")
        copies[o] = c
        homes = list(o.users_collection) or [_scene().collection]
        homes[0].objects.link(c)
    for o, c in copies.items():
        if o.parent in copies:
            c.parent = copies[o.parent]
            c.matrix_parent_inverse = o.matrix_parent_inverse.copy()   # (assigning a parent resets it)
    new = copies[src]
    world = src.matrix_world.copy()
    world.translation = (mathutils.Vector(_vec3(at)) if at is not None
                         else world.translation + mathutils.Vector(_vec3(offset)))
    new.matrix_world = world
    for c in copies.values():
        if c.type == "MESH":
            STEP["made"].append(c.name)
    _select(new)
    return new


def array(obj, count=3, offset=(2, 0, 0), name=None):
    """`count` copies in a row (the original counts as the first): returns all of them."""
    src = get(obj)
    base = name or src.name
    out = [src]
    for i in range(1, int(count)):
        step = tuple(c * i for c in _vec3(offset))
        out.append(duplicate(src, f"{base} {i + 1}", at=tuple(a + b for a, b in zip(src.location, step))))
    return out


def place_on(obj, base, offset=(0, 0)):
    """Stand `obj` on top of `base`, centred on it (plus an x/y offset) — groups as wholes."""
    obj, base = get(obj), get(base)
    (b0, b1), (o0, o1) = bounds(base), bounds(obj)
    ox, oy = (list(offset) + [0, 0])[:2]
    dx = (b0[0] + b1[0]) / 2 + ox - (o0[0] + o1[0]) / 2
    dy = (b0[1] + b1[1]) / 2 + oy - (o0[1] + o1[1]) / 2
    return move(obj, by=(dx, dy, b1[2] - o0[2]))


def parent(child, parent_obj):
    child, parent_obj = get(child), get(parent_obj)
    world = child.matrix_world.copy()
    child.parent = parent_obj
    child.matrix_world = world
    return child


def group(name, *objs):
    """Put objects in a collection called `name` (they stay where they are)."""
    coll = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if coll.name not in _scene().collection.children:
        _scene().collection.children.link(coll)
    for item in objs:
        for o in (item if isinstance(item, (list, tuple)) else [item]):
            o = get(o)
            if coll not in o.users_collection:
                coll.objects.link(o)
    return coll


def join(objs, name=None, **kw):
    """Merge several mesh objects into one called `name`."""
    name = name or kw.get("new_name") or kw.get("into") or "Joined"
    objs = [m for o in objs for m in _meshes(o, "join")]
    first = objs[0]
    world = first.matrix_world.copy()
    bm = bmesh.new()
    for o in objs:
        temp = o.data.copy()
        temp.transform(first.matrix_world.inverted() @ o.matrix_world)
        bm.from_mesh(temp)
        bpy.data.meshes.remove(temp)
    mats = [m for o in objs for m in o.data.materials if m]
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    _scene().collection.objects.link(obj)
    obj.matrix_world = world
    for m in mats[:1]:
        mesh.materials.append(m)
    return obj


def bevel(obj, width=0.03, segments=3):
    """Round off hard edges (a modifier, so the shape stays editable): real objects never have razor edges."""
    if isinstance(obj, (list, tuple)):
        return [bevel(o, width, segments) for o in obj]
    for part in _meshes(obj, "bevel"):
        mod = part.modifiers.get("Bevel") or part.modifiers.new("Bevel", "BEVEL")
        mod.width, mod.segments = max(0.0, float(width)), max(1, int(segments))
        try:
            mod.limit_method = "ANGLE"
            mod.harden_normals = False
        except Exception:
            pass
        _auto_smooth(part, 40)
    return get(obj)


def _auto_smooth(obj, angle=40):
    """Smooth shading, with edges sharper than `angle` degrees kept crisp (180: smooth everything)."""
    mesh = obj.data
    if mesh is None or not hasattr(mesh, "polygons"):
        return
    for poly in mesh.polygons:
        poly.use_smooth = True
    if angle < 180:
        try:
            mesh.set_sharp_from_angle(angle=math.radians(angle))
        except Exception:
            pass


def smooth(obj, angle=40):
    """Smooth shading (edges sharper than `angle` degrees stay crisp; angle=180 smooths everything)."""
    if isinstance(obj, (list, tuple)):
        return [smooth(o, angle) for o in obj]
    for part in _meshes(obj, "smooth"):
        _auto_smooth(part, angle)
    return get(obj)


def _world_points(obj):
    """The corners of what `obj` really occupies in the world: its own box, or — for a group's empty — its parts'."""
    shapes = [obj] if obj.type in _GEOMETRY_TYPES else [c for c in obj.children_recursive
                                                         if c.type in _GEOMETRY_TYPES]
    shapes = shapes or [obj]
    return [o.matrix_world @ mathutils.Vector(c) for o in shapes for c in o.bound_box]


def bounds(obj):
    """((min x, y, z), (max x, y, z)) in world space — of a whole group when `obj` is one."""
    obj = get(obj)
    _update()
    pts = _world_points(obj)
    return (tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3)))


def top(obj):
    return bounds(obj)[1][2]


def bottom(obj):
    return bounds(obj)[0][2]


def size(obj):
    """(x, y, z) dimensions in metres — of a whole group when `obj` is one."""
    obj = get(obj)
    if obj.type in _GEOMETRY_TYPES:
        return tuple(obj.dimensions)
    lo, hi = bounds(obj)
    return tuple(b - a for a, b in zip(lo, hi))


# ---------- where things go: the same spatial reasoning Jervis checks the scene with (spatial.py) ----------

def scene_things():
    """The separate things in the scene (see spatial.things): name, category, footprint, front, door..."""
    return spatial.things(json.loads(scene_state()))


def _thing(ref, ts=None):
    ts = ts if ts is not None else scene_things()
    if bpy is not None and isinstance(ref, bpy.types.Object):
        ref = ref.name
    t = spatial.find_thing(ts, ref)
    if t is None:
        try:
            t = spatial.find_thing(ts, get(ref).name)
        except KeyError:
            pass
    if t is None:
        raise KeyError(f"There's nothing called {ref!r} in the scene to place things by. Things there: "
                       f"{', '.join(repr(x['name']) for x in ts[:20]) or '(none)'}")
    return t


def footprint(obj):
    """(x0, y0, x1, y1): the ground a thing covers (a building: its walls and roof, without its path)."""
    t = _thing(obj)
    r = t["core"] if t["category"] == "building" else t["outer"]
    return tuple(round(v, 3) for v in r)


def _ground(x, y):
    fn = globals().get("ground_height")
    return fn(x, y) if fn else 0.0


def entrance_of(obj):
    """(x, y, z) just outside a building's front door — where a path to it starts."""
    x, y = spatial.entrance(_thing(obj))
    return (round(x, 3), round(y, 3), round(_ground(x, y), 3))


class Spot(tuple):
    """An (x, y, z) position that also knows how the thing should turn (.rotation, degrees) and on which side of
    its anchor it is (.side)."""
    rotation = 0
    side = ""


def _spot(x, y, z, rotation=0, side=""):
    s = Spot((round(x, 3), round(y, 3), round(z, 3)))
    s.rotation, s.side = rotation, side
    return s


def spot_near(anchor, relation="beside", size=None, gap=None, what="", avoid=()):
    """Where to build something `relation` an existing thing: 'beside', 'near', 'in front of', 'behind', 'left
    of', 'right of', 'inside' (on its floor) or 'on'. Outside its footprint (inside, for 'inside'), clear of
    everything else, entrances kept free. size=(width, depth) in metres (or one number); what='swimming pool'
    guesses the size and kind. Returns (x, y, z) for `at`; .rotation is 90 when the long side should turn to run
    along the anchor's side."""
    ts = scene_things()
    a = _thing(anchor, ts)
    if size is None:
        size = spatial.estimate_size(what or "thing")
    elif isinstance(size, (int, float)):
        size = (float(size), float(size))
    else:
        size = tuple(float(v) for v in list(size)[:2])
    category = spatial.category_of(what) if what else "object"
    spot = spatial.place_relative(a, relation, size, ts, category, gap_=gap, ignore=tuple(avoid))
    if spot is None:
        raise ValueError(f"There's no free ground {spatial._phrase(spatial.normalize_relation(relation))} "
                         f"{a['name']!r} for something {size[0]:.1f} x {size[1]:.1f} m.")
    z = spot.get("z")
    if z is None:
        z = _ground(spot["x"], spot["y"])
    return _spot(spot["x"], spot["y"], z, spot.get("rotation", 0), spot.get("side", ""))


def shift_thing(names, dx=0.0, dy=0.0, dz=0.0, reground=True):
    """Move a whole thing — every top-level object among `names` — by (dx, dy, dz) in the world. reground: on
    sloping terrain it follows the ground to its new spot."""
    objs = [bpy.data.objects.get(n) for n in ([names] if isinstance(names, str) else names)]
    objs = [o for o in objs if o is not None]
    if not objs:
        raise KeyError(f"None of {names!r} is in the scene.")
    tops = [o for o in objs if o.parent is None or o.parent not in objs]
    if reground:
        _update()
        pts = [p for o in objs for p in _world_points(o)]
        cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
        cy = (min(p.y for p in pts) + max(p.y for p in pts)) / 2
        dz += _ground(cx + dx, cy + dy) - _ground(cx, cy)
    for o in tops:
        move(o, by=(dx, dy, dz))
    return [o.name for o in tops]


def place_near(obj, anchor, relation="beside", gap=None):
    """Move an existing thing (a whole group) so it stands `relation` another one, by the same rules as
    spot_near: place_near('Pool', 'Villa', 'behind'). Returns where it now stands."""
    ts = scene_things()
    t = _thing(obj, ts)
    if isinstance(anchor, (tuple, list)) or (mathutils is not None and isinstance(anchor, mathutils.Vector)):
        # place_near('Bench', spot_near(...)): a spot already worked out — stand the whole thing there
        x, y = float(anchor[0]), float(anchor[1])
        cx, cy = spatial.center(t["rect"])
        z = float(anchor[2]) if len(anchor) > 2 else None
        if z is not None and abs(z) > 1e-6:
            shift_thing(t["names"], x - cx, y - cy, z - t["lo"][2], reground=False)
        else:
            shift_thing(t["names"], x - cx, y - cy)
        return _spot(x, y, _ground(x, y))
    a = _thing(anchor, ts)
    size = (t["rect"][2] - t["rect"][0], t["rect"][3] - t["rect"][1])
    spot = spatial.place_relative(a, relation, size, ts, t["category"], gap_=gap, ignore=(t["name"],), orient=False)
    if spot is None:
        raise ValueError(f"There's no free ground {spatial._phrase(spatial.normalize_relation(relation))} "
                         f"{a['name']!r} big enough for {t['name']!r}.")
    cx, cy = spatial.center(t["rect"])
    if spot.get("z") is not None:
        shift_thing(t["names"], spot["x"] - cx, spot["y"] - cy, spot["z"] - t["lo"][2], reground=False)
    else:
        shift_thing(t["names"], spot["x"] - cx, spot["y"] - cy)
    return _spot(spot["x"], spot["y"], _ground(spot["x"], spot["y"]), 0, spot.get("side", ""))


def save_file(name=None):
    """Save the .blend file — to its own path, or as `name` in Documents; a scene never saved before gets a new name
    there (never an earlier file's). Raises unless the file on disk was really written just now."""
    import os
    import time
    if name:
        name = str(name).strip()
        path = os.path.join(os.path.expanduser("~"), "Documents", name if name.lower().endswith(".blend")
                            else name + ".blend")
    elif bpy.data.filepath:
        path = bpy.data.filepath
    else:
        base = os.path.join(os.path.expanduser("~"), "Documents", "jervis_scene")
        path, k = base + ".blend", 2
        while os.path.exists(path):
            path, k = f"{base}_{k}.blend", k + 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    before = os.path.getmtime(path) if os.path.exists(path) else None
    started = time.time()
    if path == bpy.data.filepath:
        bpy.ops.wm.save_mainfile()
    else:
        bpy.ops.wm.save_as_mainfile(filepath=path)
    written = os.path.exists(path) and os.path.getsize(path) > 0 and (
        before is None or os.path.getmtime(path) > before or os.path.getmtime(path) >= started - 1)
    if not written:
        raise RuntimeError(f"Blender didn't write {path}")
    return f"Saved to {path}"


def clear_scene(keep_camera_and_light=True):
    """Remove everything (but the camera and lights, unless told otherwise) — reversibly, see trash()."""
    gone = []
    for o in list(_scene().objects):
        if keep_camera_and_light and o.type in ("CAMERA", "LIGHT"):
            continue
        gone.append(trash(o))
    return gone


def frame_view():
    """Zoom the 3D view to show everything (best effort: needs Blender's window)."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    region = next(r for r in area.regions if r.type == "WINDOW")
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.view3d.view_all(center=False)
                    space = area.spaces.active
                    if getattr(space, "shading", None) is not None and space.shading.type == "SOLID":
                        space.shading.type = "MATERIAL"   # bark, grain and tiles only show in Material Preview
                    return True
    except Exception:
        pass
    return False


def _object_color(obj):
    mat = obj.active_material
    if mat is None:
        return None
    try:
        if mat.use_nodes:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf and not bsdf.inputs["Base Color"].is_linked:
                return tuple(round(c, 3) for c in bsdf.inputs["Base Color"].default_value[:3])
    except Exception:
        pass
    return tuple(round(c, 3) for c in mat.diffuse_color[:3])


def scene_state():
    """The scene as JSON: every object's name, type, world bounds, size, location and color — what Jervis's checks
    and the AI's next decision are based on (never a guess)."""
    _update()
    layer = _layer()
    objects = []
    for o in _scene().objects:
        pts = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
        rgb = _object_color(o) if o.type == "MESH" else None
        owner, asset, asset_type = o, None, None   # the finished asset (house, tree...) this is part of, if any
        while owner is not None:
            if owner.get("jervis_asset"):
                asset = owner.name
                try:
                    asset_type = json.loads(owner["jervis_asset"]).get("type")
                except (ValueError, TypeError):
                    pass
                break
            owner = owner.parent
        objects.append({
            "name": o.name, "type": o.type,
            "location": [round(v, 3) for v in o.location],
            "rotation": [round(math.degrees(v), 1) for v in o.rotation_euler],
            "size": [round(v, 3) for v in o.dimensions],
            "min": [round(min(p[i] for p in pts), 3) for i in range(3)],
            "max": [round(max(p[i] for p in pts), 3) for i in range(3)],
            "color": list(rgb) if rgb else None,
            "color_name": color_name(rgb) if rgb else None,
            "material": o.active_material.name if o.active_material else None,
            "parent": o.parent.name if o.parent else None,
            "vertices": len(o.data.vertices) if o.type == "MESH" and o.data is not None else 0,
            # How it was made — what the quality check looks at: a bare box is not a modelled shape.
            "kind": o.get("jervis_kind"),
            "shaped": bool(o.get("jervis_shaped")),
            "modifiers": [m.type for m in o.modifiers],
            "smooth": bool(o.type == "MESH" and o.data is not None and len(o.data.polygons)
                           and o.data.polygons[0].use_smooth),
            "textured": _is_textured(o.active_material),
            "asset": asset, "asset_type": asset_type,
            "role": o.get("jervis_role"),   # what a thing is for placement: 'path', 'sunken', 'surface'...
            "animated": bool(globals().get("_animated") and globals()["_animated"](o)),
            "motion": o.get("jervis_motion"),
        })
        if o.type == "LIGHT":
            objects[-1]["light"] = {"kind": o.data.type, "energy": round(o.data.energy, 3),
                                    "color": [round(c, 3) for c in o.data.color]}
        elif o.type == "CAMERA":
            objects[-1]["camera"] = {"lens": round(o.data.lens, 2), "subject": o.get("jervis_subject"),
                                     "move": o.get("jervis_move")}
        if o.get("jervis_path"):
            try:
                info = json.loads(o["jervis_path"])
                objects[-1]["route"], objects[-1]["width"] = info.get("points"), info.get("width")
                objects[-1]["path_from"], objects[-1]["path_to"] = info.get("from"), info.get("to")
            except (ValueError, TypeError):
                pass
    active = layer.objects.active
    s = _scene()
    return json.dumps({"objects": objects, "aliases": ALIASES, "active": active.name if active else None,
                       "selected": [o.name for o in _scene().objects if o.select_get()],
                       "file": bpy.data.filepath or "",
                       "timeline": {"fps": round(s.render.fps / (s.render.fps_base or 1.0), 3), "start": s.frame_start,
                                    "end": s.frame_end, "frame": s.frame_current,
                                    "camera": s.camera.name if s.camera else None}})


# Everything above, kept aside: code the AI sends runs in this same namespace, and a variable it names `top`, `size`
# or `color` would otherwise replace the kit's function for every later step. Jervis restores these before each step.
_PER_REQUEST = {"SALT", "NAME_HINT", "X", "Y", "r", "ALIASES", "PROTECTED"}
_KIT = {k: v for k, v in list(globals().items()) if not k.startswith("__") and k not in _PER_REQUEST}
