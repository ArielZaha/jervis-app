"""Motion, cameras and light for Jervis's Blender kit: the timeline, keyframes with real easing, things that move by
themselves (water, wind, fire, smoke, rain, snow, clouds, flags), cameras that frame what they should, lights and
skies that change over time — and what Jervis checks it all with (motion_report) and undoes it with
(anim_snapshot / anim_restore).

Loaded into the bridge's namespace after blender_kit.py and blender_assets.py (it uses their functions: get, bounds,
scene_things, Parts, _finish_asset, material...) and after `cinema` (cinema.py, the planning side). Times the AI
writes are in SECONDS (sec(2.5) -> a frame); everything procedural (noise, drivers, modifiers) is non-destructive:
geometry is never changed, and undo puts every action, driver, constraint and modifier back as it was.
"""
import json
import math

try:
    import bmesh
    import bpy
    import mathutils
    from mathutils import Matrix, Vector
except ImportError:   # imported outside Blender (packaging checks only)
    bpy = bmesh = mathutils = Matrix = Vector = None

MOTION_VERSION = 1


# ---------- the timeline ----------

def fps():
    s = _scene()   # noqa: F821
    return s.render.fps / (s.render.fps_base or 1.0)


def sec(seconds):
    """The frame `seconds` into the timeline (from its first frame)."""
    s = _scene()   # noqa: F821
    return int(round(s.frame_start + float(seconds) * fps()))


def _frame(t):
    """A time the AI wrote: seconds (2.5), 'f48' / 'frame 48' for frames, '2.5s'."""
    if isinstance(t, str):
        text = t.strip().lower()
        if text.startswith(("f", "frame")):
            return int(float(text.lstrip("frame ").lstrip("f").strip()))
        return sec(float(text.rstrip("s").strip()))
    return sec(float(t))


def timeline(seconds=None, fps_=None, start=1, keep_longer=True):
    """Set the scene's timeline: `seconds` long at `fps_` (the scene's own fps unless asked). Never cuts keyed
    motion already there short (keep_longer) — what moves forever (waves, wind) has no length to keep. Returns
    (first frame, last frame, fps)."""
    s = _scene()   # noqa: F821
    if fps_:
        s.render.fps, s.render.fps_base = int(fps_), 1.0
    if seconds:
        s.frame_start = int(start)
        end = int(round(start + float(seconds) * fps()))
        s.frame_end = max(end, min(s.frame_end, _last_key())) if keep_longer else end
    return s.frame_start, s.frame_end, fps()


def _last_key():
    """The last frame where something keyed in the scene still changes (procedural and looping motion excluded)."""
    last = 0
    owners = [o for o in bpy.data.objects if o.users_collection]
    owners += [o.data for o in owners if o.type in ("LIGHT", "CAMERA")]
    owners += [s.material.node_tree for o in owners if getattr(o, "material_slots", None)
               for s in o.material_slots if s.material is not None and s.material.node_tree is not None]
    for owner in owners:
        for fc in _fcurves(owner):
            if len(fc.keyframe_points) < 2 or any(m.type in ("NOISE", "CYCLES") for m in fc.modifiers):
                continue
            last = max(last, int(round(fc.keyframe_points[-1].co.x)))
    return last


def _extend_timeline(last_frame):
    s = _scene()   # noqa: F821
    if last_frame > s.frame_end:
        s.frame_end = int(last_frame)


# ---------- keyframes ----------

def _fcurves(owner):
    """The F-curves animating a datablock (object, light, camera, node tree, world)."""
    ad = getattr(owner, "animation_data", None)
    if ad is None or ad.action is None:
        return []
    try:
        return list(ad.action.fcurves)
    except AttributeError:   # newer layered actions
        try:
            from bpy_extras import anim_utils
            bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
            return list(bag.fcurves) if bag else []
        except Exception:
            return []


_EASE = {   # request easing -> Blender interpolation, easing
    "smooth": ("BEZIER", "AUTO"), "linear": ("LINEAR", "AUTO"), "constant": ("CONSTANT", "AUTO"),
    "in": ("CUBIC", "EASE_IN"), "out": ("CUBIC", "EASE_OUT"), "in_out": ("SINE", "EASE_IN_OUT"),
    "back": ("BACK", "EASE_OUT"), "bounce": ("BOUNCE", "EASE_OUT"), "elastic": ("ELASTIC", "EASE_OUT"),
    "sine": ("SINE", "EASE_IN_OUT"),
}


def _shape(owner, path, f0, f1, ease="smooth", loop=False):
    """Give the keys of `path` between frames f0..f1 their easing (and make them repeat when loop)."""
    interp, easing = _EASE.get(str(ease or "smooth").lower(), _EASE["smooth"])
    for fc in _fcurves(owner):
        if fc.data_path != path:
            continue
        for kp in fc.keyframe_points:
            if f0 - 0.5 <= kp.co.x <= f1 + 0.5:
                kp.interpolation = interp
                kp.easing = easing
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        fc.update()
        if loop and not any(m.type == "CYCLES" for m in fc.modifiers):
            fc.modifiers.new("CYCLES")


def _clear_keys(owner, path, f0, f1):
    """Remove `path`'s keys strictly inside f0..f1 (a re-run of a step replaces its own keys, never others)."""
    for fc in _fcurves(owner):
        if fc.data_path != path:
            continue
        for kp in reversed(list(fc.keyframe_points)):
            if f0 - 0.5 <= kp.co.x <= f1 + 0.5:
                fc.keyframe_points.remove(kp)


def _key(owner, path, value, frame, group="Jervis"):
    """Set owner.path = value and key it at `frame`."""
    if isinstance(value, (tuple, list)):
        current = getattr(owner, path)
        for i, v in enumerate(value[:len(current)]):
            current[i] = v
    else:
        setattr(owner, path, value)
    try:
        owner.keyframe_insert(path, frame=frame, group=group)
    except TypeError:   # node sockets: no groups
        owner.keyframe_insert(path, frame=frame)


def _root(obj):
    """What moves when a thing moves: the whole thing (its group) — unless a part of it was named on its own ("the
    windmill's blades"). Loose parts of one thing ('Car Body', 'Car Wheel 1') are grouped first, so they never
    drift apart."""
    ref = obj
    obj = get(obj)   # noqa: F821
    try:
        t = _thing(obj.name)   # noqa: F821
    except KeyError:
        return obj
    asked = str(ref if isinstance(ref, str) else obj.name).strip().lower()
    if obj.parent is not None and obj.name != t["name"] and asked != t["name"].lower() and asked == obj.name.lower():
        return obj   # a part asked for by its own name
    root = bpy.data.objects.get(t["name"])
    if root is not None and root.users_collection:
        return root
    tops = [bpy.data.objects[n] for n in t["names"] if bpy.data.objects.get(n) is not None
            and bpy.data.objects[n].parent is None and bpy.data.objects[n].users_collection]
    if len(tops) > 1:
        return assemble(t["name"], [o.name for o in tops])   # noqa: F821
    return tops[0] if tops else obj


def animate(obj, prop, keys, ease="smooth", loop=False, group=None):
    """Keyframe one property over time: keys = [(seconds, value), ...]. prop: 'location' (world (x, y, z) of its
    origin), 'rotation' (degrees (x, y, z)), 'scale' (a number or (x, y, z)), 'visible' (True/False), 'energy'
    (a light's watts), 'color' (a light's or the object's colour), 'lens' (a camera's mm), or any property path.
    ease: smooth | linear | constant | in | out | back | bounce | elastic. loop=True repeats it forever."""
    target = get(obj)   # noqa: F821
    keys = sorted(((_frame(t), v) for t, v in keys), key=lambda k: k[0])
    if not keys:
        raise ValueError("animate() needs at least one (seconds, value) key.")
    f0, f1 = keys[0][0], keys[-1][0]
    prop = str(prop).lower()
    group = group or f"Jervis {prop}"
    if prop in ("location", "position", "move"):
        owner, path = target, "location"
        parent_inv = target.parent.matrix_world.inverted() if target.parent else None
        values = []
        for f, v in keys:
            p = Vector(_vec3(v))   # noqa: F821
            values.append((f, tuple(parent_inv @ p) if parent_inv is not None else tuple(p)))
    elif prop in ("rotation", "rotate", "rotation_euler"):
        owner, path = target, "rotation_euler"
        values = [(f, tuple(math.radians(a) for a in (_vec3(v) if not isinstance(v, (int, float))   # noqa: F821
                                                      else (0, 0, v)))) for f, v in keys]
    elif prop in ("scale", "size"):
        owner, path = target, "scale"
        values = [(f, _vec3(v)) for f, v in keys]   # noqa: F821
    elif prop in ("visible", "visibility", "hide"):
        for f, v in keys:
            for p in [target] + list(target.children_recursive):
                _key(p, "hide_viewport", not bool(v), f, group)
                _key(p, "hide_render", not bool(v), f, group)
                _shape(p, "hide_viewport", f0, f1, "constant")
                _shape(p, "hide_render", f0, f1, "constant")
        _extend_timeline(f1)
        return target
    elif prop in ("energy", "power", "brightness", "intensity") and target.type == "LIGHT":
        owner, path = target.data, "energy"
        values = [(f, max(0.0, float(v))) for f, v in keys]
    elif prop in ("color", "colour") and target.type == "LIGHT":
        owner, path = target.data, "color"
        values = [(f, tuple(rgb_of(v))) for f, v in keys]   # noqa: F821
    elif prop in ("color", "colour"):
        return _animate_colour(target, keys, ease, loop)
    elif prop in ("lens", "zoom", "focal_length") and target.type == "CAMERA":
        owner, path = target.data, "lens"
        values = [(f, max(8.0, float(v))) for f, v in keys]
    else:
        owner, path = target, prop
        values = keys
    _clear_keys(owner, path, f0, f1)
    for f, v in values:
        _key(owner, path, v, f, group)
    _shape(owner, path, f0, f1, ease, loop)
    _extend_timeline(f1)
    return target


def _animate_colour(target, keys, ease="smooth", loop=False):
    """An object's colour over time — on its own copy of each material, so nothing else sharing it changes."""
    parts = [target] if target.type == "MESH" else [c for c in target.children_recursive if c.type == "MESH"]
    f0, f1 = keys[0][0], keys[-1][0]
    for p in parts:
        for i, slot in enumerate(p.material_slots):
            mat = slot.material
            if mat is None:
                continue
            if not mat.get("jervis_animated_for") == p.name:
                mat = mat.copy()
                mat["jervis_animated_for"] = p.name
                p.material_slots[i].material = mat
            bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.use_nodes else None
            for f, v in keys:
                rgb = tuple(rgb_of(v)) + (1.0,)   # noqa: F821
                if bsdf is not None and not bsdf.inputs["Base Color"].is_linked:
                    bsdf.inputs["Base Color"].default_value = rgb
                    bsdf.inputs["Base Color"].keyframe_insert("default_value", frame=f)
                mat.diffuse_color = rgb
                mat.keyframe_insert("diffuse_color", frame=f)
            _shape(mat.node_tree, 'nodes["Principled BSDF"].inputs[0].default_value', f0, f1, ease, loop)
            _shape(mat, "diffuse_color", f0, f1, ease, loop)
    _extend_timeline(f1)
    return target


def move_to(obj, to, start=0.0, end=2.0, ease="smooth"):
    """Move a thing (its whole group) so its base stands at `to` (a point or another thing's name)."""
    root = _root(obj)
    (lo, hi) = bounds(root)   # noqa: F821
    base = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]))
    if isinstance(to, str):
        x, y, z = spot_near(to, "beside", size=(hi[0] - lo[0], hi[1] - lo[1]))   # noqa: F821
        to = (x, y, z)
    goal = Vector(_vec3(to))   # noqa: F821
    offset = root.matrix_world.translation - base
    return animate(root, "location", [(start, tuple(root.matrix_world.translation)), (end, tuple(goal + offset))],
                   ease)


def rise(obj, height=2.0, start=0.0, end=2.0, ease="smooth"):
    root = _root(obj)
    p = root.matrix_world.translation
    return animate(root, "location", [(start, tuple(p)), (end, (p.x, p.y, p.z + float(height)))], ease)


def spin(obj, degrees=360.0, axis="z", start=0.0, end=2.0, ease="linear", loop=False):
    """Turn a thing about its own origin (a group about its base): degrees, axis 'x'/'y'/'z'."""
    root = _root(obj)
    i = "xyz".index(str(axis).lower()[0])
    a = [math.degrees(v) for v in root.rotation_euler]
    b = list(a)
    b[i] += float(degrees)
    return animate(root, "rotation", [(start, a), (end, b)], ease, loop)


def scale_to(obj, factor=1.5, start=0.0, end=1.5, ease="smooth"):
    root = _root(obj)
    s = tuple(root.scale)
    f = _vec3(factor) if not isinstance(factor, (int, float)) else (float(factor),) * 3   # noqa: F821
    return animate(root, "scale", [(start, s), (end, tuple(a * b for a, b in zip(s, f)))], ease)


def bounce(obj, height=1.0, times=3, start=0.0, end=2.0):
    """Hop up and down `times` times, each hop lower, landing where it started."""
    root = _root(obj)
    p = root.matrix_world.translation
    keys, n = [], max(1, int(times))
    for k in range(n):
        t0 = start + (end - start) * k / n
        tm = start + (end - start) * (k + 0.5) / n
        keys += [(t0, tuple(p)), (tm, (p.x, p.y, p.z + float(height) * (0.6 ** k)))]
    keys.append((end, tuple(p)))
    animate(root, "location", keys, "smooth")
    return root


def appear(obj, at=0.0):
    """It is not there until `at` seconds, then it is."""
    root = _root(obj)
    return animate(root, "visible", [(0.0, False), (at, True)]) if float(at) > 0 else root


def disappear(obj, at=0.0):
    root = _root(obj)
    return animate(root, "visible", [(max(0.0, float(at) - 0.05), True), (at, False)])


def colour_to(obj, colour, start=0.0, end=1.5, ease="smooth"):
    target = get(obj)   # noqa: F821
    mats = [s.material for p in ([target] + list(target.children_recursive)) for s in getattr(p, "material_slots", [])
            if s.material is not None]
    first = tuple(mats[0].diffuse_color[:3]) if mats else (0.8, 0.8, 0.8)
    return _animate_colour(target, sorted([(_frame(start), first), (_frame(end), colour)]), ease)


# ---------- doors, gates, lids ----------

_DOOR = ("door", "gate", "lid", "hatch", "shutter")


def _find_door(ref):
    """The door a request means: a part named like a door ('House Door') of the thing named, or the object."""
    try:
        t = _thing(ref)   # noqa: F821
    except KeyError:
        t = None
    if t is not None:
        parts = [n for n in t["names"] if any(w in n.lower() for w in _DOOR)
                 and not any(w in n.lower() for w in ("handle", "knob", "frame", "step", "hinge", "light"))]
        if parts:
            return get(sorted(parts, key=len)[0])   # noqa: F821
    return get(ref)   # noqa: F821


def _door_leaves(ref):
    """The door(s) a request means: a gate's two leaves, or the one door."""
    try:
        t = _thing(ref)   # noqa: F821
    except KeyError:
        t = None
    if t is not None:
        leaves = [get(n) for n in sorted(t["names"]) if bpy.data.objects.get(n) is not None   # noqa: F821
                  and bpy.data.objects[n].get("jervis_door") == "leaf"]
        if leaves:
            return leaves
    return [_find_door(ref)]


def _inward(door, lo, hi):
    """Which way a door opens: into the building it belongs to — or, for a gate standing on its own, toward the
    property it closes (the nearest building)."""
    mid = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 0))
    ts = scene_things()   # noqa: F821
    own = next((t for t in ts if door.name in t["names"]), None)
    if own is not None and own["category"] == "building":
        cx, cy = spatial.center(own["core"])   # noqa: F821
        return Vector((cx, cy, 0)) - mid
    homes = [t for t in ts if t["category"] == "building" and (own is None or t["name"] != own["name"])]
    if homes:
        near = min(homes, key=lambda t: math.dist(spatial.center(t["core"]), mid.xy))   # noqa: F821
        cx, cy = spatial.center(near["core"])   # noqa: F821
        return Vector((cx, cy, 0)) - mid
    return Vector((0, 0, 0))


def open_door(obj="door", degrees=95.0, start=0.0, end=1.8, ease="out", close=False):
    """Open a door (or gate, lid) the way it really opens: a door swings on a vertical hinge at its side, into the
    building it belongs to, its handle with it; a gate's two leaves each swing on their own post, in toward the
    property; a garage's up-and-over door lifts up under the roof. close=True shuts it again."""
    doors = _door_leaves(obj)
    pivots = [_swing(d, degrees, start, end, ease, close, pair=len(doors) > 1) for d in doors]
    return pivots[0]


def _swing(door, degrees, start, end, ease, close, pair=False):
    _update()   # noqa: F821
    (lo, hi) = bounds(door)   # noqa: F821
    thin_y = (hi[1] - lo[1]) <= (hi[0] - lo[0])
    inward = _inward(door, lo, hi)
    if door.get("jervis_door") == "up":
        return _lift_door(door, lo, hi, thin_y, inward, start, end, ease, close)
    hinge = Vector((lo[0], (lo[1] + hi[1]) / 2, lo[2])) if thin_y else Vector(((lo[0] + hi[0]) / 2, lo[1], lo[2]))
    free = Vector((hi[0] - lo[0], 0, 0)) if thin_y else Vector((0, hi[1] - lo[1], 0))
    if pair:   # one leaf of a pair hangs on the post at its OUTER side (away from where the two leaves meet)
        try:
            own = next(t for t in scene_things() if door.name in t["names"])   # noqa: F821
            gx, gy = spatial.center(own["outer"])   # noqa: F821
        except StopIteration:
            gx, gy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        if thin_y and (lo[0] + hi[0]) / 2 < gx:
            hinge, free = Vector((lo[0], (lo[1] + hi[1]) / 2, lo[2])), Vector((hi[0] - lo[0], 0, 0))
        elif thin_y:
            hinge, free = Vector((hi[0], (lo[1] + hi[1]) / 2, lo[2])), Vector((lo[0] - hi[0], 0, 0))
        elif (lo[1] + hi[1]) / 2 < gy:
            hinge, free = Vector(((lo[0] + hi[0]) / 2, lo[1], lo[2])), Vector((0, hi[1] - lo[1], 0))
        else:
            hinge, free = Vector(((lo[0] + hi[0]) / 2, hi[1], lo[2])), Vector((0, lo[1] - hi[1], 0))
    swing = Vector((-free.y, free.x, 0))
    sign = 1.0 if (swing.dot(inward) >= 0 or inward.length < 1e-6) else -1.0
    pivot = _hinge_pivot(door, hinge, sign)
    sign = float(pivot.get("jervis_hinge", sign))
    shut = math.degrees(pivot.rotation_euler.z)
    a, b = (shut, shut + sign * float(degrees)) if not close else (shut, shut - sign * float(degrees))
    if close and abs(shut) < 1:   # already shut
        a, b = sign * float(degrees), 0.0
    animate(pivot, "rotation", [(start, (0, 0, a)), (end, (0, 0, b))], ease)
    return pivot


def _hinge_pivot(door, hinge, sign):
    """The empty a door turns about (made once, at its hinge; the door and its handle hang from it)."""
    pivot_name = f"{door.name} Hinge"
    pivot = bpy.data.objects.get(pivot_name)
    if pivot is None:
        pivot = bpy.data.objects.new(pivot_name, None)
        pivot.empty_display_type, pivot.empty_display_size = "SINGLE_ARROW", 0.3
        (door.users_collection[0] if door.users_collection else _scene().collection).objects.link(pivot)   # noqa: F821
        pivot.location = hinge
        if door.parent is not None:
            pivot.parent = door.parent
            pivot.matrix_parent_inverse = door.parent.matrix_world.inverted()
        _update()   # noqa: F821
        followers = [door] + [o for o in bpy.data.objects if o is not door and o.users_collection and
                              o.name.startswith(door.name + " ") and any(w in o.name.lower() for w in ("handle", "knob"))]
        for o in followers:
            world = o.matrix_world.copy()
            o.parent = pivot
            o.matrix_world = world
        pivot["jervis_hinge"] = sign
    return pivot


def _lift_door(door, lo, hi, thin_y, inward, start, end, ease, close):
    """An up-and-over door: it turns about its top edge until it lies flat under the roof, inside."""
    top = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2]))
    if thin_y:   # across x: about the x axis; +angle swings its foot toward +y
        axis, sign = 0, (1.0 if inward.y >= 0 else -1.0)
    else:        # across y: about the y axis; +angle swings its foot toward -x
        axis, sign = 1, (-1.0 if inward.x >= 0 else 1.0)
    pivot = _hinge_pivot(door, top, sign)
    sign = float(pivot.get("jervis_hinge", sign))
    now = math.degrees(pivot.rotation_euler[axis])
    up = sign * 88.0
    a, b = (now, up) if not close else (now if abs(now) > 1 else up, 0.0)
    vec = lambda v: tuple(v if i == axis else 0.0 for i in range(3))
    animate(pivot, "rotation", [(start, vec(a)), (end, vec(b))], ease)
    return pivot


def close_door(obj="door", degrees=95.0, start=0.0, end=1.4, ease="in_out"):
    return open_door(obj, degrees, start, end, ease, close=True)


# ---------- travelling on the ground ----------

def _place_of(ref, toward=None):
    """A point for a trip's end: a thing's doorstep (a building: just outside its door) or its edge facing
    `toward`; or a point given."""
    if isinstance(ref, (tuple, list, Vector)):
        return (float(ref[0]), float(ref[1]))
    t = _thing(ref)   # noqa: F821
    if t["category"] == "building":
        return spatial.entrance(t)   # noqa: F821
    if toward is None:
        return spatial.center(t["outer"])   # noqa: F821
    return spatial._edge_point(t["outer"], toward)[0]   # noqa: F821


def drive(obj, to, start_place=None, start=0.0, end=None, speed=6.0, ease="smooth", route=True):
    """Travel a thing (a car, a cart, a boat, a person) along the ground from where it is (or `start_place`) to
    `to` — round buildings and anything in the way, staying on the ground, turning to face where it goes,
    speeding up and slowing down. end=None: as long as the trip takes at `speed` m/s."""
    root = _root(obj)
    t = _thing(root.name)   # noqa: F821
    (lo, hi) = bounds(root)   # noqa: F821
    here = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    # Clear enough for its LENGTH, not just its width: a car's ends sweep wide when it turns a corner.
    width = max(0.8, hi[0] - lo[0], hi[1] - lo[1])
    a = here
    if start_place is not None:
        a = _place_of(start_place, toward=here)
        if not isinstance(start_place, (tuple, list, Vector)) and _thing(start_place)["category"] == "building":
            front = _thing(start_place)["front"]   # noqa: F821  (out of the door by half its length: not in the wall)
            a = (a[0] + front[0] * (width / 2 + 0.3), a[1] + front[1] * (width / 2 + 0.3))
        if math.dist(a, here) < width + 2.0:
            a = here   # it's already there ("the car in front of the garage" leaves from where it stands)
    ts = [x for x in scene_things() if x["name"] != t["name"]]   # noqa: F821
    if not route:
        pts = [a, _place_of(to, toward=a)]
    else:
        # The side of the destination it can really reach: the one facing it first, then the others — its middle
        # stopping half its length short, so it pulls up AT the gate or the door, not into it.
        # It arrives square-on, straightening up over its last length (`side`: the way it faces the target from).
        reach = width / 2 + 0.3
        ends = [(_place_of(to, toward=a), None)]
        if not isinstance(to, (tuple, list, Vector)) and _thing(to)["category"] == "building":   # noqa: F821
            front = _thing(to)["front"]   # noqa: F821
            p = ends[0][0]
            ends = [((p[0] + front[0] * reach, p[1] + front[1] * reach), front)]
        elif not isinstance(to, (tuple, list, Vector)):
            r = _thing(to)["outer"]   # noqa: F821
            cx, cy = spatial.center(r)   # noqa: F821
            w_, d_ = r[2] - r[0], r[3] - r[1]
            fars = [a, (r[0] - 50, cy), (r[2] + 50, cy), (cx, r[1] - 50), (cx, r[3] + 50)]
            if max(w_, d_) > 2.5 * max(0.1, min(w_, d_)):   # a gate, a fence: drive up to its face, never its end
                fars = [(cx, r[1] - 50), (cx, r[3] + 50)] if w_ > d_ else [(r[0] - 50, cy), (r[2] + 50, cy)]
            ends = []
            for far in fars:
                p, side = spatial._edge_point(r, far)   # noqa: F821
                p = (p[0] + side[0] * reach, p[1] + side[1] * reach)
                if all(math.dist(p, e) > 0.5 for e, _ in ends):
                    ends.append((p, side))
            ends.sort(key=lambda e: math.dist(e[0], a))
        pts, last_error = None, None
        for b, side in ends:
            try:
                # first to a point a length further out, then straight in (a shorter run-up where it's tight)
                for run_up in ((width, width / 2) if side is not None else ()):
                    lead = (b[0] + side[0] * run_up, b[1] + side[1] * run_up)
                    try:
                        pts = spatial.route(a, lead, ts, width=width) + [b]   # noqa: F821
                        break
                    except ValueError:
                        pass
                if pts is None:
                    pts = spatial.route(a, b, ts, width=width)   # noqa: F821
                break
            except ValueError as e:
                last_error = e
        if pts is None:
            raise ValueError(f"{root.name!r} can't get to {to!r}: {last_error} (it needs {width:.1f} m of room to turn).")
    pts = [p for i, p in enumerate(pts) if i == 0 or math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) > 0.05]
    dense = [pts[0]]
    for p, q in zip(pts, pts[1:]):   # a key every ~2 m, so turns are smooth and the ground is followed
        n = max(1, int(math.hypot(q[0] - p[0], q[1] - p[1]) / 2.0))
        dense += [(p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n) for k in range(1, n + 1)]
    lengths = [0.0]
    for p, q in zip(dense, dense[1:]):
        lengths.append(lengths[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
    total = lengths[-1] or 1.0
    if end is None:
        end = float(start) + max(1.0, total / max(0.5, float(speed)))
    offset = root.matrix_world.translation - Vector((here[0], here[1], lo[2]))
    lift = lo[2] - _ground(here[0], here[1])   # noqa: F821
    # Which way it faces now: its long side, front or back — whichever is nearer where it first heads, so it never
    # spins round on the spot before it leaves.
    long_axis = 0.0 if (hi[0] - lo[0]) >= (hi[1] - lo[1]) else math.pi / 2
    h0 = math.atan2(dense[min(1, len(dense) - 1)][1] - dense[0][1], dense[min(1, len(dense) - 1)][0] - dense[0][0])
    if abs(math.remainder(h0 - (long_axis + math.pi), 2 * math.pi)) < abs(math.remainder(h0 - long_axis, 2 * math.pi)):
        long_axis += math.pi
    yaw0 = root.rotation_euler.z
    if root.get("jervis_front_axis") is not None:   # a car knows its nose: it drives forwards, never backs away
        long_axis = yaw0 + math.radians(float(root["jervis_front_axis"]))
    keys_loc, keys_rot, previous = [], [], None
    for k, (p, s_) in enumerate(zip(dense, lengths)):
        tt = float(start) + (float(end) - float(start)) * _invert_ease(s_ / total, ease)
        z = _ground(p[0], p[1]) + lift   # noqa: F821
        keys_loc.append((tt, (p[0] + offset.x, p[1] + offset.y, z + offset.z)))
        q = dense[min(k + 1, len(dense) - 1)]
        r_ = dense[max(k - 1, 0)]
        heading = math.atan2(q[1] - r_[1], q[0] - r_[0]) if q != r_ else (previous if previous is not None else h0)
        if previous is not None:   # no 359 -> 0 spins: always the short way round
            heading = previous + math.remainder(heading - previous, 2 * math.pi)
        previous = heading
        keys_rot.append((tt, (math.degrees(root.rotation_euler.x), math.degrees(root.rotation_euler.y),
                              math.degrees(yaw0 + (heading - long_axis)))))
    animate(root, "location", keys_loc, "linear")
    animate(root, "rotation", keys_rot, "linear")
    _roll_wheels(root, [k[0] for k in keys_loc], lengths)
    root["jervis_route"] = json.dumps([list(p) for p in dense])
    return root


def _roll_wheels(root, times, distances):
    """Its wheels turn as it goes — one turn per circumference travelled, so they never skid — about their axles
    (each wheel's own origin, across the way it drives)."""
    for w in [c for c in root.children_recursive if c.type == "MESH" and "wheel" in c.name.lower()]:
        radius = max(0.05, w.dimensions.z / 2)
        across = 1 if w.dimensions.y <= min(w.dimensions.x, w.dimensions.z) + 1e-6 else 0   # its thin side: the axle
        base = list(w.rotation_euler)
        keys = []
        for tt, dist in zip(times, distances):
            r = [math.degrees(v) for v in base]
            r[across] += math.degrees(dist / radius) * (1 if across == 1 else -1)
            keys.append((tt, tuple(r)))
        animate(w, "rotation", keys, "linear")


def _invert_ease(progress, ease="smooth"):
    """The time (0..1) at which an eased motion has covered `progress` of the way."""
    lo_, hi_ = 0.0, 1.0
    for _ in range(30):
        mid = (lo_ + hi_) / 2
        if cinema.ease(mid, ease if ease in ("smooth", "linear", "in", "out") else "smooth") < progress:   # noqa: F821
            lo_ = mid
        else:
            hi_ = mid
    return (lo_ + hi_) / 2


# ---------- things that move by themselves ----------

def _noise(owner, path, index, strength, scale, phase=0.0, group="Jervis motion"):
    """A procedural wobble on one channel (non-destructive, forever, no keys to maintain)."""
    value = getattr(owner, path)
    if not hasattr(value, "__len__"):   # a single number (a light's energy): no index
        index = -1
    s = _scene()   # noqa: F821
    keyed = any(fc.data_path == path and fc.array_index == max(0, index) and len(fc.keyframe_points)
                for fc in _fcurves(owner))
    if not keyed:   # (keying again would bake the wobble of this very frame into the rest pose)
        try:
            owner.keyframe_insert(path, index=index, frame=s.frame_start, group=group)
        except TypeError:
            owner.keyframe_insert(path, index=index, frame=s.frame_start)
    for fc in _fcurves(owner):
        if fc.data_path == path and fc.array_index == max(0, index):
            for m in [m for m in fc.modifiers if m.type == "NOISE"]:
                fc.modifiers.remove(m)
            m = fc.modifiers.new("NOISE")
            m.strength, m.scale, m.phase = float(strength), float(scale), float(phase)
            return m
    return None


def _driver(owner, path, expression, index=-1):
    """A value that follows the clock (frame), e.g. 'frame*0.02': no keys, no Python needed."""
    try:
        owner.driver_remove(path, index) if index >= 0 else owner.driver_remove(path)
    except (TypeError, RuntimeError):
        pass
    fc = owner.driver_add(path, index) if index >= 0 else owner.driver_add(path)
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = expression
    return fc


def _adopt(obj, parent):
    """Make `obj` part of `parent`'s group exactly where it stands. (A new object's world matrix is only computed on
    the next update: reading it before that put lights made for a pool at the world's origin.)"""
    _update()   # noqa: F821
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = world
    for c in parent.users_collection:
        if c not in obj.users_collection:
            c.objects.link(obj)
    if len(obj.users_collection) > 1 and _scene().collection in obj.users_collection:   # noqa: F821
        _scene().collection.objects.unlink(obj)   # noqa: F821
    return obj


def _materials_of(objs):
    seen = []
    for o in objs:
        for slot in getattr(o, "material_slots", []):
            if slot.material is not None and slot.material not in seen:
                seen.append(slot.material)
    return seen


def _parts(obj):
    o = get(obj)   # noqa: F821
    return [o] if o.type == "MESH" else [c for c in o.children_recursive if c.type == "MESH"]


def _water_parts(obj):
    o = get(obj)   # noqa: F821
    family = [o] + list(o.children_recursive)
    water = [p for p in family if p.type == "MESH" and (p.get("jervis_kind") == "water" or any(
        w in p.name.lower() for w in ("water", "sea", "ocean", "surface", "lake", "river", "jet")))]
    return water or [p for p in family if p.type == "MESH"]


def animate_water(obj, kind="waves", strength=1.0, speed=1.0, direction=(1.0, 0.3)):
    """Water that moves, without touching its mesh: its surface shimmer animates (the material's noise flows with
    time), and open water (a sea, a lake, an island's ocean) also rolls in slow waves (a displacement whose
    pattern drifts). Water in a pool, pond or fountain only ripples — it stays exactly inside its container.
    kind: waves | ripples | flow (a river, along its length) | falls (a waterfall, downward)."""
    parts = _water_parts(obj)
    for p in parts:   # a water surface casts no shadow: a moving sea a kilometre wide in the sun's shadow map made
        try:          # EEVEE take minutes per frame (and hang), for a shadow no one would see
            p.visible_shadow = False
        except AttributeError:
            pass
    rate = 0.012 * float(speed) * (1.6 if kind in ("flow", "falls") else 1.0)
    for mat in _materials_of(parts):
        if not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_NOISE":
                node.noise_dimensions = "4D"
                _driver(node.inputs["W"], "default_value", f"frame*{rate:.5f}")
            elif node.type == "MAPPING" and kind in ("flow", "falls"):
                axis = 1
                _driver(node.inputs["Location"], "default_value", f"-frame*{0.02 * float(speed):.5f}", axis)
        mat["jervis_motion"] = kind
    if kind == "waves":
        for p in parts:
            if len(p.data.vertices) < 200:
                continue
            (lo, hi) = bounds(p)   # noqa: F821
            span = max(hi[0] - lo[0], hi[1] - lo[1])
            drv_name = f"{p.name} Wave Driver"
            drv = bpy.data.objects.get(drv_name)
            if drv is None:
                drv = bpy.data.objects.new(drv_name, None)
                drv.empty_display_size = 0.5
                (p.users_collection[0] if p.users_collection else _scene().collection).objects.link(drv)   # noqa: F821
                drv.hide_set(True)
                drv.hide_render = True
                drv.parent = p
            dx, dy = direction
            _driver(drv, "location", f"frame*{0.03 * float(speed) * dx:.5f}", 0)
            _driver(drv, "location", f"frame*{0.03 * float(speed) * dy:.5f}", 1)
            tex = bpy.data.textures.get(f"{p.name} Waves") or bpy.data.textures.new(f"{p.name} Waves", "CLOUDS")
            tex.noise_scale = max(1.5, span / 18.0)
            tex.noise_depth = 2
            mod = p.modifiers.get("Jervis Waves") or p.modifiers.new("Jervis Waves", "DISPLACE")
            mod.texture, mod.texture_coords, mod.texture_coords_object = tex, "OBJECT", drv
            mod.strength = min(0.6, max(0.04, span / 300.0)) * float(strength)
            mod.mid_level, mod.direction = 0.5, "Z"
    root = get(obj)   # noqa: F821
    root["jervis_motion"] = kind
    return root


def sway(obj, strength=1.0, speed=1.0):
    """Wind in a tree, bush, reeds or a lamp post: the whole thing leans and recovers from its base, its foliage
    stirs a little more — procedural, forever, nothing in the mesh changed."""
    root = _root(obj)
    s = float(strength)
    family = [root] + list(root.children_recursive)
    seed = sum(map(ord, root.name)) % 97
    palm = "palm" in root.name.lower() or any("frond" in p.name.lower() for p in family)
    # a gentle lean of about half a degree each way (a few centimetres at the top of a tree), slower than the leaves
    _noise(root, "rotation_euler", 0, 0.034 * s * (1.6 if palm else 1.0), 80 / float(speed), phase=seed)
    _noise(root, "rotation_euler", 1, 0.024 * s * (1.6 if palm else 1.0), 95 / float(speed), phase=seed + 13)
    for p in family:
        name = p.name.lower()
        if p is not root and p.type == "MESH" and any(w in name for w in ("leaves", "leaf", "needles", "fronds",
                                                                          "foliage", "crown", "canopy", "flowers")):
            _noise(p, "rotation_euler", 2, 0.02 * s, 30 / float(speed), phase=seed + 7)
    root["jervis_motion"] = "sway"
    return root


def drift(obj, distance=2.0, speed=1.0):
    """A slow wander (clouds), within `distance` metres of where it is."""
    root = _root(obj)
    seed = sum(map(ord, root.name)) % 89
    _noise(root, "location", 0, float(distance), 400 / float(speed), phase=seed)
    _noise(root, "location", 1, float(distance) * 0.6, 520 / float(speed), phase=seed + 31)
    root["jervis_motion"] = "drift"
    return root


def flicker(obj, strength=0.35, speed=1.0):
    """Fire: its flames stretch and waver, its light flickers."""
    root = get(obj)   # noqa: F821
    family = [root] + list(root.children_recursive)
    seed = sum(map(ord, root.name)) % 71
    for k, p in enumerate(family):
        if p.type == "MESH" and "flame" in p.name.lower():
            _noise(p, "scale", 2, 0.18 * float(strength) / 0.35, 6 / float(speed), phase=seed + k * 5)
            _noise(p, "scale", 0, 0.08 * float(strength) / 0.35, 9 / float(speed), phase=seed + k * 7)
            _noise(p, "rotation_euler", 2, 0.12, 14 / float(speed), phase=seed + k)
        if p.type == "LIGHT":
            _noise(p.data, "energy", 0, p.data.energy * float(strength), 4 / float(speed), phase=seed)
    for mat in _materials_of([p for p in family if p.type == "MESH" and "flame" in p.name.lower()]):
        for node in mat.node_tree.nodes if mat.use_nodes else []:
            if node.type == "TEX_NOISE":
                node.noise_dimensions = "4D"
                _driver(node.inputs["W"], "default_value", f"frame*{0.08 * float(speed):.4f}")
    root["jervis_motion"] = "fire"
    return root


def flutter(obj, strength=1.0, speed=1.0):
    """A flag or banner rippling in the wind (its Wave modifier runs with time) and leaning a little."""
    root = get(obj)   # noqa: F821
    family = [root] + list(root.children_recursive)
    for p in family:
        mod = next((m for m in getattr(p, "modifiers", []) if m.type == "WAVE"), None)
        if mod is not None:
            mod.speed = 0.25 * float(speed)
            mod.height = mod.height or 0.1 * float(strength)
        elif p.type == "MESH" and any(w in p.name.lower() for w in ("cloth", "flag", "banner", "sail", "curtain")) \
                and len(p.data.vertices) >= 30:
            mod = p.modifiers.new("Jervis Flutter", "WAVE")
            (lo, hi) = bounds(p)   # noqa: F821
            mod.use_normal, mod.use_x, mod.use_y = True, True, False
            mod.height = 0.08 * float(strength) * max(0.5, hi[0] - lo[0])
            mod.width, mod.narrowness, mod.speed = 0.6, 1.2, 0.25 * float(speed)
    root["jervis_motion"] = "flutter"
    return root


def spin_parts(obj, words=("blade", "sail", "propeller", "rotor", "fan"), rpm=12.0):
    """Turn the rotating parts of a windmill, fan or propeller about their own centre, forever."""
    root = get(obj)   # noqa: F821
    for p in [root] + list(root.children_recursive):
        if p.type == "MESH" and any(w in p.name.lower() for w in words):
            axis = 1 if p.dimensions.y < min(p.dimensions.x, p.dimensions.z) else 0
            _driver(p, "rotation_euler", f"frame*{2 * math.pi * float(rpm) / 60 / fps():.5f}", axis)
    root["jervis_motion"] = "spin"
    return root


def animate_naturally(obj, motion=None, strength=1.0, speed=1.0):
    """Give a thing the motion it has by nature (cinema.natural_motion decides; or say `motion`)."""
    t = _thing(obj)   # noqa: F821
    motion = motion or cinema.natural_motion(t)   # noqa: F821
    root = get(t["name"]) if bpy.data.objects.get(t["name"]) else get(obj)   # noqa: F821
    if motion in ("waves", "ripples", "flow", "falls"):
        return animate_water(root.name, motion, strength, speed)
    if motion == "sway":
        return sway(root.name, strength, speed)
    if motion == "drift":
        return drift(root.name, speed=speed)
    if motion == "fire":
        return flicker(root.name, speed=speed)
    if motion == "flutter":
        return flutter(root.name, strength, speed)
    if motion == "spin":
        return spin_parts(root.name)
    if motion in ("smoke", "rain", "snow"):
        return root   # particle systems move by themselves
    raise ValueError(f"{t['name']!r} doesn't move by itself; say how it should move (animate(), spin(), drive()...).")


def wind(strength=1.0, things=None):
    """Wind through the scene: every tree, bush and flag (or the ones named) sways or flutters."""
    done = []
    for t in scene_things():   # noqa: F821
        if things and t["name"] not in things:
            continue
        words = set(spatial.words_of(t["name"])) | {t.get("asset_type") or ""}   # noqa: F821
        if words & {"flag", "banner", "pennant", "windsock"}:   # (first: 'Palm Flag' is a flag, not a palm)
            flutter(t["name"], strength)
            done.append(t["name"])
        elif words & cinema.WIND_SWAYS or t.get("asset_type") in ("tree", "bush"):   # noqa: F821
            sway(t["name"], strength)
            done.append(t["name"])
        else:   # what grows or flies on a bigger thing: an island's palms, a garden's bushes, a house's flag
            # (whole plants only: a lawn's grass or a flower box tilting from its origin would look broken)
            for owner, n in spatial.find_parts([t], "tree bush shrub hedge reed bamboo fern sunflower"):   # noqa: F821
                sway(n, strength)
                done.append(n)
            for owner, n in spatial.find_parts([t], "flag banner pennant windsock"):   # noqa: F821
                flutter(n, strength)
                done.append(n)
    return done


# ---------- particles: smoke, rain, snow ----------

def _library():
    """A hidden collection for the shapes particles are made of (never rendered themselves)."""
    lib = bpy.data.collections.get("Jervis Library")
    if lib is None:
        lib = bpy.data.collections.new("Jervis Library")
        _scene().collection.children.link(lib)   # noqa: F821
    lib.hide_render = lib.hide_viewport = True
    return lib


def _particle_shape(name, builder):
    shape = bpy.data.objects.get(name)
    if shape is None:
        shape = builder()
        shape["jervis_role"] = "library"   # not a thing of the scene: what particles are made of
        for c in list(shape.users_collection):
            c.objects.unlink(shape)
        _library().objects.link(shape)
    return shape


def _emitter(name, at, size, z):
    em = Parts()   # noqa: F821
    em.box((0, 0, 0), (size[0], size[1], 0.02))
    obj = em.done(name, (at[0], at[1], z), kind="emitter")
    obj.show_instancer_for_render = obj.show_instancer_for_viewport = False
    obj["jervis_role"] = "sky"
    return obj


def _particles(obj, count, lifetime, velocity, shape, size, random_size=0.3, brownian=0.0, gravity=0.0, preroll=True):
    s = _scene()   # noqa: F821
    mod = obj.modifiers.new("Jervis Particles", "PARTICLE_SYSTEM")
    st = obj.particle_systems[-1].settings
    st.count = int(count)
    st.lifetime = int(lifetime)
    st.frame_start = s.frame_start - (int(lifetime) if preroll else 0)
    st.frame_end = s.frame_end + 1
    st.emit_from = "FACE"
    st.normal_factor = 0.0
    st.object_align_factor = (0.0, 0.0, float(velocity))
    st.factor_random = 0.1
    st.render_type = "OBJECT"
    st.instance_object = shape
    st.particle_size = size
    st.size_random = random_size
    st.brownian_factor = brownian
    st.effector_weights.gravity = gravity
    st.use_rotations = False
    st.display_method = "RENDER"
    st.display_percentage = 100 if count <= 3000 else max(10, int(300000 / count))
    return mod


def _scene_area(pad=8.0):
    ts = [t for t in scene_things() if t["category"] not in ("sky",)]   # noqa: F821
    if not ts:
        return (0.0, 0.0), (30.0, 30.0), 10.0
    lo = [min(t["lo"][i] for t in ts) for i in range(3)]
    hi = [max(t["hi"][i] for t in ts) for i in range(3)]
    return ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2), (hi[0] - lo[0] + 2 * pad, hi[1] - lo[1] + 2 * pad), hi[2]


def rain(name="Rain", at=None, size=None, heavy=False):
    """Rain falling over the whole scene (or `size` (x, y) metres round `at`), from frame one to the end."""
    centre, area, top = _scene_area()
    if at is not None:
        centre = (_vec3(at)[0], _vec3(at)[1])   # noqa: F821
    if size is not None:
        area = (float(size), float(size)) if isinstance(size, (int, float)) else tuple(size)[:2]
    height = max(18.0, top + 8.0)
    obj = _emitter(f"{name} Clouds", centre, area, height)

    def drop():
        p = Parts()   # noqa: F821
        p.cylinder((0, 0, 0), 0.006, 0.35, segments=4)
        d = p.done(f"{name} Drop", (0, 0, -200), "#b8c7d6", kind="particle")
        return d
    shape = _particle_shape(f"{name} Drop", drop)
    speed = 9.0
    life = int(height / speed * fps()) + 2
    density = 14 if heavy else 6   # drops per m² per second
    _particles(obj, min(30000, int(area[0] * area[1] * density * life / max(1, fps()))), life, -speed, shape, 1.0, 0.2)
    root = _finish_asset(name, "rain", {"size": list(area), "heavy": bool(heavy)}, [obj], (centre[0], centre[1], 0.0))  # noqa: F821
    root["jervis_role"] = "sky"
    root["jervis_motion"] = "rain"
    return root


def snow(name="Snow", at=None, size=None, heavy=False):
    """Snow drifting down over the whole scene."""
    centre, area, top = _scene_area()
    if at is not None:
        centre = (_vec3(at)[0], _vec3(at)[1])   # noqa: F821
    if size is not None:
        area = (float(size), float(size)) if isinstance(size, (int, float)) else tuple(size)[:2]
    height = max(15.0, top + 6.0)
    obj = _emitter(f"{name} Clouds", centre, area, height)

    def flake():
        p = Parts()   # noqa: F821
        p.lump((0, 0, 0), 0.025, irregularity=0.2, detail=1)
        return p.done(f"{name} Flake", (0, 0, -200), "snow", kind="particle")
    shape = _particle_shape(f"{name} Flake", flake)
    speed = 1.1
    life = int(height / speed * fps()) + 2
    density = 3 if heavy else 1.2
    _particles(obj, min(30000, int(area[0] * area[1] * density * life / max(1, fps()))), life, -speed, shape, 1.0,
               0.5, brownian=0.4)
    root = _finish_asset(name, "snow", {"size": list(area), "heavy": bool(heavy)}, [obj], (centre[0], centre[1], 0.0))  # noqa: F821
    root["jervis_role"] = "sky"
    root["jervis_motion"] = "snow"
    return root


def smoke(name="Smoke", at=None, size=1.0, rate=1.0):
    """Smoke rising from `at` (a chimney top, a fire), spreading and fading as it climbs."""
    at = _vec3(at) if at is not None else (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)   # noqa: F821
    obj = _emitter(f"{name} Source", at[:2], (0.4 * size, 0.4 * size), at[2] + 0.05)
    obj["jervis_role"] = "effect"

    def puff():
        p = Parts()   # noqa: F821
        p.lump((0, 0, 0), 0.35, irregularity=0.3, detail=2)
        d = p.done(f"{name} Puff", (0, 0, -200), None, kind="particle", smooth="all")
        m = bpy.data.materials.new(f"Jervis {name} smoke")
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (0.45, 0.45, 0.46, 1)
        b.inputs["Alpha"].default_value = 0.28
        b.inputs["Roughness"].default_value = 1.0
        try:
            m.surface_render_method = "BLENDED"
        except Exception:
            m.blend_method = "BLEND"
        d.data.materials.append(m)
        return d
    shape = _particle_shape(f"{name} Puff", puff)
    life = int(4.0 * fps())
    _particles(obj, int(60 * rate * life / fps()), life, 0.9 * size, shape, 0.8 * size, 0.6, brownian=0.35)
    st = obj.particle_systems[-1].settings
    st.effector_weights.gravity = 0.0
    root = _finish_asset(name, "smoke", {"size": size, "rate": rate}, [obj], tuple(at))   # noqa: F821
    root["jervis_motion"] = "smoke"
    return root


# ---------- fire, clouds, flags, rivers, waterfalls ----------

def _flame_material():
    m = bpy.data.materials.get("Jervis flame")
    if m is not None:
        return m
    m = bpy.data.materials.new("Jervis flame")
    m.use_nodes = True
    nodes, links = m.node_tree.nodes, m.node_tree.links
    b = nodes.get("Principled BSDF")
    coords, sep = nodes.new("ShaderNodeTexCoord"), nodes.new("ShaderNodeSeparateXYZ")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 4.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (1.0, 0.85, 0.3, 1)
    ramp.color_ramp.elements[1].color = (0.9, 0.12, 0.01, 1)
    links.new(coords.outputs["Object"], sep.inputs["Vector"])
    links.new(coords.outputs["Object"], noise.inputs["Vector"])
    mix = nodes.new("ShaderNodeMath")
    mix.operation = "MULTIPLY_ADD"
    mix.inputs[1].default_value = 0.6
    links.new(sep.outputs["Z"], mix.inputs[0])
    links.new(noise.outputs["Fac"], mix.inputs[2])
    links.new(mix.outputs["Value"], ramp.inputs["Fac"])
    b.inputs["Base Color"].default_value = (0, 0, 0, 1)
    for key in ("Emission Color", "Emission"):
        if key in b.inputs:
            links.new(ramp.outputs["Color"], b.inputs[key])
    if "Emission Strength" in b.inputs:
        b.inputs["Emission Strength"].default_value = 9.0
    b.inputs["Alpha"].default_value = 0.85
    m.diffuse_color = (1.0, 0.45, 0.08, 1)
    return m


def fire(name="Fire", at=None, size=1.0, logs=True, stones=True):
    """A campfire: crossed logs in a ring of stones, layered flames that waver, and a warm light that flickers."""
    size = max(0.3, min(5.0, float(size or 1.0)))
    at = _here(at)   # noqa: F821
    r = rng(sum(map(ord, name)))   # noqa: F821
    made = []
    if logs:
        wood = Parts()   # noqa: F821
        for k in range(4):
            a = math.radians(k * 45 + r.uniform(-8, 8))
            dx, dy = math.cos(a) * 0.45 * size, math.sin(a) * 0.45 * size
            wood.add_tube([(-dx, -dy, 0.08 * size), (dx, dy, 0.12 * size)], 0.07 * size, sides=10)
        made.append(wood.done(f"{name} Logs", at, "bark", smooth=True))
    if stones:
        ring = Parts()   # noqa: F821
        for k in range(10):
            a = 2 * math.pi * k / 10
            ring.lump((math.cos(a) * 0.62 * size, math.sin(a) * 0.62 * size, 0.0), 0.12 * size * r.uniform(0.8, 1.2),
                      irregularity=0.3, squash=(1.2, 1, 0.75), detail=2, seed=k, flat_bottom=0.4)
        made.append(ring.done(f"{name} Stones", at, "stone", smooth=True))
    for k, (h, rad, dx, dy) in enumerate(((1.1, 0.26, 0, 0), (0.75, 0.2, 0.15, 0.08), (0.7, 0.18, -0.12, 0.1),
                                          (0.55, 0.15, 0.03, -0.15))):
        f = Parts()   # noqa: F821
        f.lump((dx * size, dy * size, h * 0.42 * size), rad * size, irregularity=0.25, squash=(1, 1, h / rad * 0.48),
               detail=3, seed=k + 3)
        flame = f.done(f"{name} Flame {k + 1}", at, None, smooth="all")
        flame.data.materials.append(_flame_material())
        made.append(flame)
    light_data = bpy.data.lights.new(f"{name} Glow", "POINT")
    light_data.energy = 180.0 * size * size
    light_data.color = cinema.kelvin(1900)   # noqa: F821
    light_data.shadow_soft_size = 0.3 * size
    glow = bpy.data.objects.new(f"{name} Glow", light_data)
    _scene().collection.objects.link(glow)   # noqa: F821
    glow.location = (at[0], at[1], at[2] + 0.6 * size)
    root = _finish_asset(name, "fire", {"size": size}, made, at, 0,   # noqa: F821
                         "a campfire with crossed logs in a ring of stones and flickering flames")
    _adopt(glow, root)
    flicker(root.name)
    return root


def cloud(name="Cloud", at=None, size=6.0, count=1, height=None):
    """Soft white clouds in the sky above the scene (they drift slowly)."""
    size = max(1.0, min(60.0, float(size or 6.0)))
    base = _vec3(at) if at is not None else (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)   # noqa: F821
    _, _, top = _scene_area()
    z = float(height) if height else max(base[2] if base[2] > 1 else 0.0, top + 14.0, 22.0)
    r = rng(sum(map(ord, name)))   # noqa: F821
    puffs = Parts()   # noqa: F821
    for c in range(max(1, int(count))):
        cx, cy = (c - (count - 1) / 2) * size * 1.6, r.uniform(-size, size) * (0.8 if count > 1 else 0)
        for k in range(7):
            puffs.lump((cx + r.uniform(-0.45, 0.45) * size, cy + r.uniform(-0.25, 0.25) * size, r.uniform(0, 0.2) * size),
                       size * r.uniform(0.22, 0.36), irregularity=0.25, squash=(1.2, 1, 0.65), detail=3, seed=k + c * 9)
    obj = puffs.done(f"{name} Puffs", (base[0], base[1], z), "white", smooth="all")
    root = _finish_asset(name, "cloud", {"size": size, "count": count}, [obj], (base[0], base[1], z), 0,   # noqa: F821
                         "soft clouds drifting in the sky")
    root["jervis_role"] = "sky"
    drift(root.name, distance=size * 0.4)
    return root


def flag(name="Flag", at=None, height=5.0, size=1.5, color="red", pole_color="steel"):
    """A flag on a pole, rippling in the wind."""
    height = max(1.5, min(30.0, float(height or 5.0)))
    w = max(0.4, min(6.0, float(size or 1.5)))
    h = w * 0.62
    at = _here(at)   # noqa: F821
    pole = Parts()   # noqa: F821
    pole.cylinder((0, 0, 0), 0.04 + height * 0.004, height, segments=16, radius_top=0.03 + height * 0.003)
    pole.lump((0, 0, height + 0.06), 0.07, irregularity=0.0, detail=2)
    made = [pole.done(f"{name} Pole", at, pole_color, smooth=True)]
    cloth = Parts()   # noqa: F821
    nx, nz = 24, 15
    verts = [[cloth.bm.verts.new((0.06 + w * i / nx, 0.0, height - 0.08 - h + h * j / nz)) for j in range(nz + 1)]
             for i in range(nx + 1)]
    for i in range(nx):
        for j in range(nz):
            cloth.bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    flag_obj = cloth.done(f"{name} Cloth", at, color, smooth="all")
    group = flag_obj.vertex_groups.new(name="Flutter")
    for v in flag_obj.data.vertices:
        group.add([v.index], min(1.0, (v.co.x / w) ** 1.2), "REPLACE")
    mod = flag_obj.modifiers.new("Jervis Flutter", "WAVE")   # the wave first, then the thickness
    mod.use_normal, mod.use_x, mod.use_y = True, True, False
    mod.height, mod.width, mod.narrowness, mod.speed = 0.09 * w, 0.55 * w, 1.0, 0.25
    mod.vertex_group = "Flutter"
    solid = flag_obj.modifiers.new("Thickness", "SOLIDIFY")
    solid.thickness = 0.006
    made.append(flag_obj)
    root = _finish_asset(name, "flag", {"height": height, "size": w, "color": color}, made, at, 0,   # noqa: F821
                         f"a {color} flag on a {height:.0f} m pole, rippling in the wind")
    root["jervis_motion"] = "flutter"
    return root


def _flow_material(name, color="#2f8fa3", alpha=0.8):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nodes, links = m.node_tree.nodes, m.node_tree.links
    b = nodes.get("Principled BSDF")
    uv, mapping, noise = nodes.new("ShaderNodeTexCoord"), nodes.new("ShaderNodeMapping"), nodes.new("ShaderNodeTexNoise")
    mapping.inputs["Scale"].default_value = (3.0, 0.6, 1.0)
    noise.inputs["Scale"].default_value = 6.0
    noise.inputs["Detail"].default_value = 6.0
    links.new(uv.outputs["UV"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    rgb = rgb_of(color)   # noqa: F821
    ramp.color_ramp.elements[0].color = (*[c * 0.7 for c in rgb], 1)
    ramp.color_ramp.elements[1].color = (min(1, rgb[0] + 0.5), min(1, rgb[1] + 0.5), min(1, rgb[2] + 0.5), 1)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.3
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = 0.05
    b.inputs["Alpha"].default_value = alpha
    try:
        m.surface_render_method = "BLENDED"
    except Exception:
        m.blend_method = "BLEND"
    m.diffuse_color = (*rgb, alpha)
    return m


def _strip_with_uv(parts, pts, half, z, zs=None):
    """A flat strip along 2D points with UVs running along it (u across, v = metres along): what flowing water
    is drawn on."""
    n = len(pts)
    zs = zs or [0.0] * n
    left = _offset_line(pts, half)   # noqa: F821
    right = _offset_line(pts, -half)   # noqa: F821
    bm = parts.bm
    uv = bm.loops.layers.uv.verify()
    rows, along = [], 0.0
    for i in range(n):
        if i:
            along += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        rows.append((bm.verts.new((left[i][0], left[i][1], z + zs[i])), bm.verts.new((right[i][0], right[i][1],
                                                                                      z + zs[i])), along))
    for (a, b, va), (c, d, vb) in zip(rows, rows[1:]):
        f = bm.faces.new((a, b, d, c))
        for loop, (u, v) in zip(f.loops, ((0, va), (1, va), (1, vb), (0, vb))):
            loop[uv].uv = (u, v / max(0.1, half * 2))
    return rows


def river(name="River", start=None, end=None, width=4.0, points=None, color="#2b7f90", at=None, length=40.0,
          **kw):
    """A river flowing from `start` to `end` (things or (x, y) points) — or `length` metres along x through `at`
    — winding a little, round buildings: water sunk between earthy banks, flowing along its length."""
    width = max(1.0, min(40.0, float(width or 4.0)))
    ts = scene_things()   # noqa: F821
    if points is None and (start is None or end is None):
        c = _vec3(at) if at is not None else (globals().get("X", 0.0), globals().get("Y", 0.0), 0.0)   # noqa: F821
        half = max(5.0, min(400.0, float(length or 40.0))) / 2
        start, end = (c[0] - half, c[1]), (c[0] + half, c[1])
    if points:
        pts = [(float(p[0]), float(p[1])) for p in points]
    else:
        a = _place_of(start) if not isinstance(start, (tuple, list)) else (float(start[0]), float(start[1]))
        b = _place_of(end) if not isinstance(end, (tuple, list)) else (float(end[0]), float(end[1]))
        try:
            pts = spatial.route(a, b, ts, width=width + 2)   # noqa: F821
        except ValueError:   # water finds its way: a straight course rather than no river at all
            pts = [a, b]
    dense = [pts[0]]
    for p, q in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(q[0] - p[0], q[1] - p[1]) / 2.0))
        dense += [(p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n) for k in range(1, n + 1)]
    wobbly = []
    for k, (x, y) in enumerate(dense):   # a gentle meander across the line
        if 0 < k < len(dense) - 1:
            dx, dy = dense[k + 1][0] - dense[k - 1][0], dense[k + 1][1] - dense[k - 1][1]
            n_ = math.hypot(dx, dy) or 1.0
            s = math.sin(k * 0.45) * width * 0.35
            x, y = x - dy / n_ * s, y + dx / n_ * s
        wobbly.append((x, y))
    ox, oy = wobbly[0]
    local = [(x - ox, y - oy) for x, y in wobbly]
    at = (ox, oy, 0.0)
    water = Parts()   # noqa: F821
    _strip_with_uv(water, local, width / 2, -0.25)
    w_obj = water.done(f"{name} Water", at, None, kind="water")
    w_obj.data.materials.append(_flow_material(f"Jervis river {name}", color))
    banks = Parts()   # noqa: F821
    for side in (-1, 1):
        inner = _offset_line(local, side * width / 2 * 0.98)   # noqa: F821
        outer = _offset_line(local, side * (width / 2 + 1.4))   # noqa: F821
        for (a1, b1), (a2, b2) in zip(zip(inner, outer), zip(inner[1:], outer[1:])):
            v = [banks.bm.verts.new((a1[0], a1[1], -0.7)), banks.bm.verts.new((b1[0], b1[1], 0.02)),
                 banks.bm.verts.new((b2[0], b2[1], 0.02)), banks.bm.verts.new((a2[0], a2[1], -0.7))]
            banks.bm.faces.new(v if side > 0 else list(reversed(v)))
    bed = Parts()   # noqa: F821
    _strip_with_uv(bed, local, width / 2, -0.75)
    made = [w_obj, banks.done(f"{name} Banks", at, "dirt", smooth=True), bed.done(f"{name} Bed", at, "dirt")]
    root = _finish_asset(name, "river", {"width": width, "points": [list(p) for p in wobbly]}, made, at, 0,   # noqa: F821
                         f"a {width:.0f} m wide river winding between earthy banks")
    root["jervis_role"] = "path"
    root["jervis_path"] = json.dumps({"from": None, "to": None, "width": width + 2.8, "points": [list(p) for p in wobbly]})
    _carve_terrain(name, local, at, width / 2 + 1.3)
    animate_water(root.name, "flow")
    return root


def _carve_terrain(name, local, at, half):
    """Cut the river's course out of the ground it runs through (its water lies below ground level: under an
    uncut lawn it was simply not there). A hidden channel-shaped cutter, a Boolean on each terrain surface it
    crosses; the river's banks cover the cut edge."""
    import bmesh as _bm
    left, right = _offset_line(local, half), _offset_line(local, -half)   # noqa: F821
    bm = _bm.new()
    rows = [[bm.verts.new((x, y, z)) for (x, y) in line for z in (-6.0, 6.0)] for line in (left, right)]
    n = len(local)
    L = lambda side, k, top: rows[side][2 * k + top]   # noqa: E731
    for k in range(n - 1):
        for top in (0, 1):
            f = [L(0, k, top), L(1, k, top), L(1, k + 1, top), L(0, k + 1, top)]
            bm.faces.new(f if top else list(reversed(f)))
        for side in (0, 1):
            f = [L(side, k, 0), L(side, k + 1, 0), L(side, k + 1, 1), L(side, k, 1)]
            bm.faces.new(f if side else list(reversed(f)))
    for k, flip in ((0, False), (n - 1, True)):
        f = [L(0, k, 0), L(0, k, 1), L(1, k, 1), L(1, k, 0)]
        bm.faces.new(list(reversed(f)) if flip else f)
    _bm.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(f"{name} Cut")
    bm.to_mesh(me)
    bm.free()
    cutter = bpy.data.objects.new(f"{name} Cut", me)
    cutter.location = at
    cutter["jervis_role"] = "library"   # not a thing of the scene: the shape the ground is cut by
    _library().objects.link(cutter)
    lo = Vector((min(p[0] for p in left + right) + at[0], min(p[1] for p in left + right) + at[1]))
    hi = Vector((max(p[0] for p in left + right) + at[0], max(p[1] for p in left + right) + at[1]))
    for o in list(_scene().objects):   # noqa: F821
        if o.type != "MESH" or o.get("jervis_kind") != "terrain":
            continue
        c = [o.matrix_world @ Vector(v) for v in o.bound_box]
        if max(v.x for v in c) < lo.x or min(v.x for v in c) > hi.x or \
                max(v.y for v in c) < lo.y or min(v.y for v in c) > hi.y:
            continue
        mod = o.modifiers.new(f"Jervis cut {name}", "BOOLEAN")
        mod.operation, mod.object = "DIFFERENCE", cutter
        try:
            mod.solver = "EXACT"
            mod.use_hole_tolerant = True   # the ground is an open sheet, not a solid
        except (TypeError, AttributeError):
            pass


def _cliff(name, at, height, width, r, moss=False):
    """A rock face for water to fall from: wide and concave (its sides reach forward round the pool), layered in
    rough horizontal strata with ledges, a lower lip where the water pours over, and a plateau running back on top.
    Mossy: green on its ledges and top, and in damp patches across the face (a cliff in a wet forest)."""
    import bmesh as _bm
    W = width + max(6.0, height * 1.6)
    nu, nv, back = 48, 26, 7
    p = Parts()   # noqa: F821
    off = Vector((r.uniform(0, 50), r.uniform(0, 50), 0))

    def top_at(x):
        lip = abs(x) < width / 2 + 0.25
        rim = height + 0.9 + 1.1 * mathutils.noise.noise(Vector((x / 3.0, 0.5, 0)) + off)
        if lip:
            return height
        blend = min(1.0, (abs(x) - width / 2 - 0.25) / 1.2)
        return height + (rim - height) * blend

    rows = []
    for j in range(nv + back + 1):
        row = []
        for i in range(nu + 1):
            u = i / nu
            x = (u - 0.5) * W
            reach = (2 * abs(x) / W) ** 2
            y_face = 1.0 - 3.0 * reach
            t = top_at(x)
            if j <= nv:
                z = -0.6 + (t + 0.6) * j / nv
                v = Vector((x / 1.7, z / 1.1, 0)) + off
                rough = 0.45 * mathutils.noise.ridged_multi_fractal(v, 0.9, 2.0, 3, 0.4, 1.0)
                strata = 0.28 * math.sin(z * 2.6 + 1.5 * mathutils.noise.noise(v * 0.5))
                ledge = 0.22 if (z % 1.3) < 0.18 else 0.0
                y = y_face - rough - strata - ledge
                if abs(x) < width / 2 + 0.25 and z > height - 1.2:
                    y += 0.35 * (z - (height - 1.2))   # the lip worn back where the water runs
            else:
                m = j - nv
                y = y_face + 0.4 + m * 1.1
                z = t + 0.25 * mathutils.noise.noise(Vector((x / 2.5, y / 2.5, 0)) + off) - (0.25 if m == 1 else 0)
            row.append(p.bm.verts.new((x, y, z)))
        rows.append(row)
    for j in range(len(rows) - 1):
        for i in range(nu):
            p.bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    if moss:
        p.bm.normal_update()
        for f in p.bm.faces:
            c = f.calc_center_median()
            damp = mathutils.noise.noise(Vector((c.x / 4.0, c.z / 4.0, 0.7)) + off)
            f.material_index = 1 if (f.normal.z > 0.35 or damp > 0.12) else 0
    obj = p.done(name, at, "rock", smooth=True, kind="terrain")
    if moss:
        obj.data.materials.append(material("moss"))   # noqa: F821
    return obj


def waterfall(name="Waterfall", at=None, height=4.0, width=2.5, pool=True, moss=False):
    """A waterfall: a rock cliff, water pouring over its lip in a sheet that falls continuously, foam where it lands
    and a pond below. moss=True: the cliff green with moss (a waterfall in a wet forest)."""
    height = max(1.0, min(40.0, float(height or 4.0)))
    width = max(0.5, min(20.0, float(width or 2.5)))
    at = _here(at)   # noqa: F821
    r = rng(sum(map(ord, name)))   # noqa: F821
    made = []
    made.append(_cliff(f"{name} Cliff", at, height, width, r, moss=bool(moss)))
    sheet = Parts()   # noqa: F821
    profile = [(0.6, height), (0.25, height + 0.05), (0.0, height - 0.15)] + [
        (-0.04 * k ** 1.3, height - 0.15 - (height - 0.3) * k / 10) for k in range(1, 11)]
    nx = 8
    uv = sheet.bm.loops.layers.uv.verify()
    rows = [[sheet.bm.verts.new(((i / nx - 0.5) * width, y, z)) for i in range(nx + 1)] for y, z in profile]
    along = [0.0]
    for (y1, z1), (y2, z2) in zip(profile, profile[1:]):
        along.append(along[-1] + math.hypot(y2 - y1, z2 - z1))
    for j in range(len(rows) - 1):
        for i in range(nx):
            f = sheet.bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
            for loop, (u, v) in zip(f.loops, ((i / nx, along[j]), ((i + 1) / nx, along[j]), ((i + 1) / nx, along[j + 1]),
                                              (i / nx, along[j + 1]))):
                loop[uv].uv = (u * width / 2, v / 2)
    fall = sheet.done(f"{name} Water", at, None, kind="water", smooth=True)
    fall.data.materials.append(_flow_material(f"Jervis falling water {name}", "#9fd3e0", alpha=0.75))
    made.append(fall)
    foam = Parts()   # noqa: F821
    for k in range(8):
        foam.lump(((k / 7 - 0.5) * width, r.uniform(-0.9, -0.3), 0.05), r.uniform(0.25, 0.45) * min(2, width / 2),
                  irregularity=0.3, squash=(1.3, 1, 0.45), detail=2, seed=k + 20)
    foam_obj = foam.done(f"{name} Foam", at, "white", smooth=True)
    made.append(foam_obj)
    if pool:
        made.append(pond(f"{name} Pool", at=(at[0], at[1] - max(2.0, width * 0.8), at[2]), size=max(3.0, width * 1.8),   # noqa: F821
                         reeds=False))
    root = _finish_asset(name, "waterfall", {"height": height, "width": width, "moss": bool(moss)}, made, at, 0,   # noqa: F821
                         f"a {height:.0f} m waterfall pouring over a rock cliff into a pool")
    animate_water(root.name, "falls", speed=1.8)
    _noise(foam_obj, "scale", 2, 0.12, 8, phase=3)
    return root


# ---------- cameras ----------

def _swept(ts, f0, f1, samples=9):
    """The things as they will be: an animated thing (a car driving past) claims every place it passes through
    between frames f0 and f1 — so a camera planned now isn't blocked by it later."""
    s = _scene()   # noqa: F821
    keep = s.frame_current
    moving = []
    for t in ts:
        objs = [bpy.data.objects.get(n) for n in t["names"]]
        if any(o is not None and o.animation_data and o.animation_data.action for o in objs):
            moving.append((t, [o for o in objs if o is not None and o.parent is None] or [o for o in objs if o]))
    if not moving:
        return ts
    out = {id(t): t for t in ts}
    for t, tops in moving:
        rects, zl, zh = [], t["lo"][2], t["hi"][2]
        for k in range(samples):
            s.frame_set(int(round(f0 + (f1 - f0) * k / (samples - 1))))
            (lo, hi) = bounds(tops[0])   # noqa: F821
            rects.append((lo[0], lo[1], hi[0], hi[1]))
            zl, zh = min(zl, lo[2]), max(zh, hi[2])
        out[id(t)] = dict(t, pieces=rects, lo=[t["lo"][0], t["lo"][1], zl], hi=[t["hi"][0], t["hi"][1], zh])
    s.frame_set(keep)
    return [out[id(t)] for t in ts]


def _subject_things(subject):
    ts = scene_things()   # noqa: F821
    if subject is None or subject in ("scene", "everything", "all"):
        return ts, [t for t in ts if t["category"] not in ("ground", "sky")]
    refs = subject if isinstance(subject, (list, tuple)) else [subject]
    picked = []
    for ref in refs:
        t = spatial.find_thing(ts, ref)   # noqa: F821
        parts = []
        if t is not None and str(ref) != t["name"] and str(ref) in t["names"]:
            parts = [(t, str(ref))]   # a part named exactly ('Island Palm 2'): that part, not the whole island
        elif t is None:
            parts = spatial.find_parts(ts, ref)   # noqa: F821  ("the palm trees" growing on the island)
            if not parts:
                raise KeyError(f"There's nothing called {ref!r} in the scene to point a camera at. Things there: "
                               f"{', '.join(repr(x['name']) for x in ts[:20]) or '(none)'}")
        if not parts:
            picked.append(t)
        for owner, n in parts:
            (lo, hi) = bounds(n)   # noqa: F821
            sub = spatial.virtual_thing(n, (lo[0], lo[1], hi[0], hi[1]), "object", hi[2])   # noqa: F821
            sub["lo"][2], sub["front"] = lo[2], owner["front"]
            picked.append(sub)
    if len(picked) == 1:
        door = [n for n in picked[0]["names"] if any(w in n.lower() for w in _DOOR) and str(refs[0]).lower() in
                ("door", "entrance", "front door", "the door") and "handle" not in n.lower()]
        if door:   # "a close-up of the door": the door itself is the subject
            o = get(door[0])   # noqa: F821
            (lo, hi) = bounds(o)   # noqa: F821
            sub = spatial.virtual_thing(o.name, (lo[0], lo[1], hi[0], hi[1]), "object", hi[2])   # noqa: F821
            sub["lo"][2], sub["front"] = lo[2], picked[0]["front"]
            return ts, [sub]
    return ts, picked


def _rig(name="Camera", lens=35.0):
    """A camera aimed by a target empty ('<name> Target', Track To), with depth of field on its target."""
    cam = bpy.data.objects.get(name)
    if cam is None or cam.type != "CAMERA":
        name = _make_room_for(name) if cam is not None else name   # noqa: F821
        data = bpy.data.cameras.new(name)
        cam = bpy.data.objects.new(name, data)
        _scene().collection.objects.link(cam)   # noqa: F821
    cam.data.sensor_width = cinema.SENSOR   # noqa: F821
    cam.data.lens = float(lens)
    cam.data.clip_end = max(cam.data.clip_end, 2000.0)
    target = bpy.data.objects.get(f"{cam.name} Target")
    if target is None:
        target = bpy.data.objects.new(f"{cam.name} Target", None)
        target.empty_display_type, target.empty_display_size = "SPHERE", 0.25
        _scene().collection.objects.link(target)   # noqa: F821
    track = cam.constraints.get("Jervis Aim") or cam.constraints.new("TRACK_TO")
    track.name = "Jervis Aim"
    track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    try:
        cam.data.dof.use_dof = True
        cam.data.dof.focus_object = target
        cam.data.dof.aperture_fstop = 5.6
    except Exception:
        pass
    s = _scene()   # noqa: F821
    s.render.resolution_x, s.render.resolution_y = (s.render.resolution_x or 1920), (s.render.resolution_y or 1080)
    return cam, target


def camera(name="Camera", subject=None, shot="wide", lens=None, azimuth=None, elevation=None, active=True):
    """A camera framing `subject` (a thing's name, a list of them, or None for the whole scene) as a shot type:
    establishing | wide | medium | close | overhead | low. Placed by the scene's real geometry: outside every
    building, with a clear line of sight; aimed by its target empty. Returns the camera."""
    ts, things_ = _subject_things(subject)
    plan = cinema.plan_shot(ts, things_, shot, lens=lens, azimuth=azimuth, elevation=elevation)   # noqa: F821
    cam, target = _rig(name, plan["lens"])
    cam.location = plan["location"]
    target.location = plan["aim"]
    cam["jervis_subject"] = json.dumps([t["name"] for t in things_][:6])
    cam["jervis_shot"] = shot
    if active:
        _scene().camera = cam   # noqa: F821
    _update()   # noqa: F821
    return cam


def _subject_motion(things_, start_f, end_f, samples=12):
    """[(progress, (x, y, z), heading)] of a moving subject, read from its animation."""
    s = _scene()   # noqa: F821
    keep = s.frame_current
    root = bpy.data.objects.get(things_[0]["name"]) or get(things_[0]["names"][0])   # noqa: F821
    out, previous = [], None
    for k in range(samples + 1):
        f = int(round(start_f + (end_f - start_f) * k / samples))
        s.frame_set(f)
        (lo, hi) = bounds(root)   # noqa: F821
        pos = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2])
        heading = (pos[0] - previous[0], pos[1] - previous[1]) if previous else (0.0, 0.0)
        out.append((k / samples, pos, heading))
        previous = pos
    s.frame_set(keep)
    for k in range(len(out)):   # the first heading: where it goes next; stops keep their last heading
        p, pos, h = out[k]
        if math.hypot(*h) < 1e-4:
            nxt = next((o[2] for o in out[k + 1:] if math.hypot(*o[2]) > 1e-4), None)
            prev = next((o[2] for o in reversed(out[:k]) if math.hypot(*o[2]) > 1e-4), None)
            out[k] = (p, pos, nxt or prev or (0.0, 1.0))
    return out


def camera_move(name="Camera", move="push_in", subject=None, start=0.0, end=None, shot_from=None, shot_to=None,
                sweep=None, direction=None, to=None, ease="smooth", active=True):
    """Move a camera over time, framing the subject all the way: push_in | pull_out | orbit (sweep degrees,
    direction 'left'/'right') | crane | reveal | pan (to another thing, or direction) | tilt ('up'/'down') |
    overhead | flyover | fly_through (subject: several things) | follow | track (a moving subject) | still.
    start/end in seconds (end=None: the end of the timeline). Every position is checked clear of the scene's
    buildings; the camera's target empty carries its aim. Returns the camera."""
    ts, things_ = _subject_things(subject)
    other = None
    if to is not None:
        other = spatial.find_thing(ts, to)   # noqa: F821
    s = _scene()   # noqa: F821
    f0 = _frame(start)
    f1 = _frame(end) if end is not None else s.frame_end
    if f1 <= f0:
        f1 = f0 + int(round(2 * fps()))
    motion = _subject_motion(things_, f0, f1) if move in ("follow", "track") else None
    ts = _swept(ts, f0, f1)
    keys = cinema.camera_path(ts, things_, move, shot_from=shot_from, shot_to=shot_to, sweep=sweep,   # noqa: F821
                              direction=direction, subject_to=other, motion=motion)
    cam, target = _rig(name, keys[0][3])
    for owner, path in ((cam, "location"), (target, "location"), (cam.data, "lens")):
        _clear_keys(owner, path, f0, f1)
    for p, loc, aim, lens in keys:
        f = int(round(f0 + (f1 - f0) * p))
        _key(cam, "location", loc, f, "Jervis camera")
        _key(target, "location", aim, f, "Jervis camera")
        _key(cam.data, "lens", float(lens), f, "Jervis camera")
    many = len(keys) > 2
    shape = "linear" if move in ("follow", "track") else ("smooth" if not many else "smooth")
    for owner, path in ((cam, "location"), (target, "location"), (cam.data, "lens")):
        _shape(owner, path, f0, f1, shape if many else ease)
    cam["jervis_subject"] = json.dumps([t["name"] for t in things_][:6])
    cam["jervis_move"] = move
    try:
        cam.data.dof.aperture_fstop = 2.8 if (shot_to or "") == "close" else 5.6
    except Exception:
        pass
    if active:
        s.camera = cam
    _extend_timeline(f1)
    _update()   # noqa: F821
    return cam


def unblock_camera(name="Camera"):
    """Lift each of a camera's keyed positions (craning up) out of anything it is inside, or that stands between
    it and what it films. How many positions moved."""
    cam = get(name)   # noqa: F821
    s = _scene()   # noqa: F821
    keep = s.frame_current
    track = next((c for c in cam.constraints if c.type == "TRACK_TO" and c.target is not None), None)
    subject = json.loads(cam.get("jervis_subject", "[]") or "[]")
    boxes = cinema.obstacles_3d(scene_things(), exclude=set(subject))   # noqa: F821
    fcs = [fc for fc in _fcurves(cam) if fc.data_path == "location"]
    frames = sorted({int(round(kp.co.x)) for fc in fcs for kp in fc.keyframe_points}) or [s.frame_current]
    moved = 0
    for f in frames:
        s.frame_set(f)
        _update()   # noqa: F821
        aim = track.target.matrix_world.translation if track else cam.matrix_world.translation + \
            cam.matrix_world.to_quaternion() @ Vector((0, 0, -10))
        pos = tuple(round(v, 3) for v in cam.matrix_world.translation)
        new = cinema.clear_position(pos, tuple(aim), boxes)   # noqa: F821
        if new != pos:
            cam.location = new
            if fcs:
                cam.keyframe_insert("location", frame=f, group="Jervis camera")
            moved += 1
    s.frame_set(keep)
    return moved


def cut_to(name="Camera", at=0.0):
    """From `at` seconds, the film is seen through this camera (a timeline marker bound to it)."""
    cam = get(name)   # noqa: F821
    s = _scene()   # noqa: F821
    f = _frame(at)
    for m in list(s.timeline_markers):
        if m.frame == f and m.camera is not None:
            s.timeline_markers.remove(m)
    marker = s.timeline_markers.new(f"Cut {cam.name}", frame=f)
    marker.camera = cam
    if f <= s.frame_start:
        s.camera = cam
    return marker


# ---------- light ----------

def _aim(obj, point):
    d = Vector(_vec3(point)) - obj.matrix_world.translation   # noqa: F821
    if d.length > 1e-6:
        obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def _light_colour(color):
    if color is None:
        return (1.0, 1.0, 1.0)
    if isinstance(color, (int, float)) and 1000 <= float(color) <= 40000:
        return cinema.kelvin(color)   # noqa: F821
    try:
        return tuple(rgb_of(color))   # noqa: F821
    except (ValueError, TypeError):
        _warn(f"Unknown light colour {color!r}: used white")   # noqa: F821
        return (1.0, 1.0, 1.0)


def light(name="Light", kind="point", at=None, energy=None, color=None, size=None, aim=None, angle=45.0,
          shadows=True, on=True):
    """A light: kind point | spot | area | sun, standing at `at`, pointing at `aim` (a point or a thing's name),
    energy in watts (W/m² for a sun), color a colour or a temperature in kelvin (3000 = warm, 6500 = daylight).
    on=False: in place but off (lights_on() brings it up). Every value is checked: never negative, NaN or None."""
    kind = str(kind or "point").upper()
    kind = kind if kind in ("POINT", "SPOT", "AREA", "SUN") else "POINT"
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "LIGHT" or obj.data.type != kind:
        name = _make_room_for(name) if obj is not None else name   # noqa: F821
        obj = bpy.data.objects.new(name, bpy.data.lights.new(name, kind))
        _scene().collection.objects.link(obj)   # noqa: F821
    data = obj.data
    default = {"POINT": 400.0, "SPOT": 800.0, "AREA": 300.0, "SUN": 3.5}[kind]
    target = float(energy) if energy is not None and math.isfinite(float(energy)) else default
    target = max(0.0, target)
    data.color = _light_colour(color)
    if size is not None and math.isfinite(float(size)):
        if kind == "AREA":
            data.size = max(0.01, float(size))
        elif kind == "SUN":
            data.angle = math.radians(max(0.1, min(30.0, float(size))))
        else:
            data.shadow_soft_size = max(0.0, float(size))
    if kind == "SPOT":
        data.spot_size = math.radians(max(1.0, min(179.0, float(angle))))
        data.spot_blend = 0.35
    data.use_shadow = bool(shadows)
    obj["jervis_energy"] = target
    data.energy = target if on else 0.0
    if at is not None:
        obj.location = _vec3(at)   # noqa: F821
    if aim is not None:
        point = aim
        if isinstance(aim, str):
            t = _thing(aim)   # noqa: F821
            point = spatial.center(t["outer"]) + (((t["lo"][2] + t["hi"][2]) / 2),)   # noqa: F821
        _update()   # noqa: F821
        _aim(obj, point)
    return obj


def _world():
    s = _scene()   # noqa: F821
    if s.world is None:
        s.world = bpy.data.worlds.new("World")
    w = s.world
    w.use_nodes = True
    bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        bg = w.node_tree.nodes.new("ShaderNodeBackground")
        out = next((n for n in w.node_tree.nodes if n.type == "OUTPUT_WORLD"), None) or \
            w.node_tree.nodes.new("ShaderNodeOutputWorld")
        w.node_tree.links.new(bg.outputs[0], out.inputs[0])
    return w, bg


def _sun_rotation(elevation, azimuth):
    e, a = math.radians(elevation), math.radians(azimuth)
    towards = Vector((-math.cos(e) * math.cos(a), -math.cos(e) * math.sin(a), -math.sin(e)))
    return towards.to_track_quat("-Z", "Y").to_euler()


def sky(look="day", start=None, end=None, sun_name="Sun"):
    """The sky and the sun for a time of day — day | sunrise | sunset | dusk | night | dramatic | overcast — or a
    change over the timeline (start/end seconds): 'day_to_night', 'night_to_day', or 'sunset'/'sunrise' happening
    during the shot. Moves the sun, its colour and strength, and the sky's colour and brightness together."""
    transition = start is not None or end is not None or look in ("day_to_night", "night_to_day")
    keys = cinema.sky_keys(look, transition=transition)   # noqa: F821
    sun_obj = bpy.data.objects.get(sun_name)
    if sun_obj is None or sun_obj.type != "LIGHT" or sun_obj.data.type != "SUN":
        sun_obj = light(sun_name, "sun", at=(0, 0, 30), energy=keys[0][1]["strength"], color=keys[0][1]["color"],
                        size=0.6)
    w, bg = _world()
    s = _scene()   # noqa: F821
    f0 = _frame(start) if start is not None else s.frame_start
    f1 = _frame(end) if end is not None else s.frame_end
    previous = None
    for p, k in keys:
        f = int(round(f0 + (f1 - f0) * p)) if len(keys) > 1 else f0
        rot = _sun_rotation(max(-8.0, k["elevation"]), k["azimuth"])
        if previous is not None:
            rot.make_compatible(previous)
        previous = rot
        sun_obj.rotation_euler = rot
        sun_obj.data.color = k["color"]
        sun_obj.data.energy = k["strength"] if k["elevation"] > -2 else k["strength"] * 0.3
        bg.inputs["Color"].default_value = (*k["sky"], 1.0)
        bg.inputs["Strength"].default_value = k["sky_strength"]
        if len(keys) > 1:
            sun_obj.keyframe_insert("rotation_euler", frame=f, group="Jervis sky")
            sun_obj.data.keyframe_insert("color", frame=f)
            sun_obj.data.keyframe_insert("energy", frame=f)
            bg.inputs["Color"].keyframe_insert("default_value", frame=f)
            bg.inputs["Strength"].keyframe_insert("default_value", frame=f)
    if len(keys) > 1:
        for owner, path in ((sun_obj, "rotation_euler"), (sun_obj.data, "color"), (sun_obj.data, "energy")):
            _shape(owner, path, f0, f1, "smooth")
        _extend_timeline(f1)
    sun_obj["jervis_energy"] = keys[-1][1]["strength"]
    sun_obj["jervis_sky"] = look
    return sun_obj


def lighting(setup="dramatic", subject=None):
    """A lighting setup around a subject: 'dramatic' (a strong warm key from the side, a cool rim from behind, little
    fill, a dark sky), 'studio' (soft key, fill and rim), or a time of day (passed on to sky())."""
    if setup not in ("dramatic", "studio", "three point", "three-point"):
        return sky(setup)
    ts, things_ = _subject_things(subject)
    lo = [min(t["lo"][i] for t in things_) for i in range(3)]
    hi = [max(t["hi"][i] for t in things_) for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    r = max(1.0, 0.5 * math.dist(lo, hi))
    az = cinema.base_azimuth(things_[0] if len(things_) == 1 else None)   # noqa: F821
    made = []
    for nm, d_az, el, dist, kel, power, size in (("Key", -40, 38, 1.9, 3600, 1.0, 0.25), ("Rim", 150, 30, 1.7, 7500, 0.7,
                                                                                         0.15),
                                                 ("Fill", 50, 15, 2.2, 5500, 0.12 if setup == "dramatic" else 0.35,
                                                  0.5)):
        d = cinema._dir(az + d_az, el)   # noqa: F821
        pos = (c[0] + d[0] * r * dist, c[1] + d[1] * r * dist, c[2] + d[2] * r * dist)
        watts = 900.0 * power * (r * dist / 5.0) ** 2
        made.append(light(f"{nm} Light", "area", at=pos, energy=watts, color=kel, size=max(1.0, r * size * 2),
                          aim=tuple(c)))
    if setup == "dramatic":
        sky("dramatic")
    return made


def _lights_of(target=None, kind=None):
    """The lights a request means: a thing's own (inside or parented to it), or every light but the sun."""
    lights_ = [o for o in bpy.data.objects if o.type == "LIGHT" and o.users_collection and o.data.type != "SUN"]
    if target is None:
        return lights_
    t = _thing(target)   # noqa: F821
    root = bpy.data.objects.get(t["name"])
    own = [o for o in lights_ if root is not None and root in _ancestors(o)]   # noqa: F821
    if own:
        return own
    r = spatial.grow(t["outer"], 0.5)   # noqa: F821
    return [o for o in lights_ if r[0] <= o.matrix_world.translation.x <= r[2] and
            r[1] <= o.matrix_world.translation.y <= r[3]]


def interior_lights(building, on=False, energy=60.0, kelvin=2900):
    """Warm ceiling lights through a building's rooms (off unless on=True), part of the building."""
    t = _thing(building)   # noqa: F821
    root = bpy.data.objects.get(t["name"])
    made = []
    for k, p in enumerate(cinema.light_spots_inside(t), 1):   # noqa: F821
        o = light(f"{t['name']} Light {k}", "point", at=p, energy=energy, color=kelvin, size=0.15, on=on)
        if root is not None:
            _adopt(o, root)
        o["jervis_light_for"] = t["name"]
        made.append(o)
    return made


def pool_lights(pool_name, on=False, energy=120.0, color="#bff4ff"):
    """Lights set in a pool's (or pond's, fountain's) walls under the water, facing across it, with glowing
    fixtures — off unless on=True."""
    t = _thing(pool_name)   # noqa: F821
    water = [n for n in t["names"] if "water" in n.lower()]
    o = get(water[0]) if water else get(t["name"])   # noqa: F821
    (lo, hi) = bounds(o)   # noqa: F821
    root = bpy.data.objects.get(t["name"])
    glow = bpy.data.materials.get("Jervis pool light") or material("#e8fdff", name="Jervis pool light",   # noqa: F821
                                                                   emission=0.0)
    made = []
    for k, (p, facing) in enumerate(cinema.pool_light_spots(lo, hi), 1):   # noqa: F821
        aim = (p[0] + facing[0] * 3, p[1] + facing[1] * 3, p[2] - 0.2)
        lt = light(f"{t['name']} Light {k}", "spot", at=p, energy=energy, color=color, angle=110, size=0.05,
                   aim=aim, on=on)
        fix = Parts()   # noqa: F821
        fix.cylinder((0, 0, -0.08), 0.1, 0.02, segments=16, axis="y" if facing[0] == 0 else "x")
        fixture = fix.done(f"{t['name']} Light {k} Lens", p, None, smooth=True)
        fixture.data.materials.append(glow)
        for obj in (lt, fixture):
            if root is not None:
                _adopt(obj, root)
        lt["jervis_light_for"] = t["name"]
        made.append(lt)
    return made


def lights_on(target=None, start=0.0, end=None, ease="smooth", off=False):
    """Bring lights up (or down with off=True) from `start` to `end` seconds — a building's (it gets interior
    lights if it has none), a pool's (it gets underwater lights), one light by name, or all of them."""
    lights_ = []
    if target is not None:
        o = bpy.data.objects.get(target) if isinstance(target, str) else None
        if o is not None and o.type == "LIGHT":
            lights_ = [o]
        else:
            lights_ = _lights_of(target)
            if not lights_ and not off:
                t = _thing(target)   # noqa: F821
                if t["category"] == "building":
                    lights_ = interior_lights(t["name"], on=False)
                elif t["category"] == "sunken" or any("water" in n.lower() for n in t["names"]):
                    lights_ = pool_lights(t["name"], on=False)
                else:
                    (lo, hi) = (t["lo"], t["hi"])
                    lights_ = [light(f"{t['name']} Light", "point", at=((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2,
                                                                       hi[2] + 0.5), energy=200, color=3200, on=False)]
    else:
        lights_ = _lights_of(None)
    if not lights_:
        raise ValueError("There are no lights to turn " + ("off" if off else "on") + " here.")
    s = _scene()   # noqa: F821
    end = end if end is not None else float(start) + 0.8
    for lt in lights_:
        full = float(lt.get("jervis_energy") or lt.data.energy or 300.0)
        a, b = (0.0, full) if not off else (full, 0.0)
        animate(lt.name, "energy", [(start, a), (end, b)], ease)
    for mat in [m for m in bpy.data.materials if m.name.startswith("Jervis pool light")]:
        bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.use_nodes else None
        if bsdf is not None and "Emission Strength" in bsdf.inputs:
            for t_, v in ((start, 0.0 if not off else 6.0), (end, 6.0 if not off else 0.0)):
                bsdf.inputs["Emission Strength"].default_value = v
                bsdf.inputs["Emission Strength"].keyframe_insert("default_value", frame=_frame(t_))
            for key in ("Emission Color", "Emission"):
                if key in bsdf.inputs:
                    bsdf.inputs[key].default_value = (0.75, 0.97, 1.0, 1)
    return lights_


def lights_off(target=None, start=0.0, end=None, ease="smooth"):
    return lights_on(target, start, end, ease, off=True)


def check_lights():
    """Every light's values made valid (no negative or NaN energy, colours within 0..1, sane spot angles): what
    was fixed."""
    fixed = []
    for o in bpy.data.objects:
        if o.type != "LIGHT":
            continue
        d = o.data
        if not math.isfinite(d.energy) or d.energy < 0:
            d.energy = max(0.0, float(o.get("jervis_energy") or 0.0)) if math.isfinite(d.energy) else 0.0
            fixed.append(f"{o.name} energy")
        if any(not math.isfinite(c) or c < 0 or c > 1 for c in d.color):
            d.color = tuple(max(0.0, min(1.0, c if math.isfinite(c) else 1.0)) for c in d.color)
            fixed.append(f"{o.name} colour")
        if d.type == "SPOT" and not (0.01 < d.spot_size < math.pi):
            d.spot_size = math.radians(45)
            fixed.append(f"{o.name} spot angle")
    return fixed


# ---------- what Jervis checks ----------

def _animated(o):
    ad = o.animation_data
    if ad and (ad.action or len(ad.drivers)):
        return True
    data_ad = getattr(o.data, "animation_data", None) if o.data is not None else None
    if data_ad and (data_ad.action or len(data_ad.drivers)):
        return True
    if any(m.type in ("WAVE", "PARTICLE_SYSTEM") or (m.type == "DISPLACE" and getattr(m, "texture_coords_object", None))
           for m in getattr(o, "modifiers", [])):
        return True
    if o.type == "MESH" and any(_shader_animated(s.material) for s in o.material_slots):
        return True
    return bool(o.constraints) and o.type == "CAMERA"


def _shader_animated(mat):
    ad = getattr(getattr(mat, "node_tree", None), "animation_data", None) if mat is not None else None
    return bool(ad and (ad.action or len(ad.drivers)))


def _shader_value(o, dg):
    """A number that changes when an object's surface pattern moves with time (water rippling, flames)."""
    total = 0.0
    for s in o.material_slots:
        if not _shader_animated(s.material):
            continue
        m = s.material.evaluated_get(dg)
        for n in m.node_tree.nodes:
            if n.type == "TEX_NOISE" and "W" in n.inputs:
                total += n.inputs["W"].default_value
            elif n.type == "MAPPING":
                total += sum(n.inputs["Location"].default_value)
    return round(total, 5)


def _signature(o, dg):
    """A number that changes when a deforming object's surface moves (waves, a fluttering flag)."""
    if o.type != "MESH":
        return 0.0
    ev = o.evaluated_get(dg)
    verts = ev.data.vertices
    step = max(1, len(verts) // 60)
    return round(sum(verts[i].co.z + verts[i].co.y * 0.37 for i in range(0, len(verts), step)), 4)


def _key_range(o):
    frames = []
    for owner in (o, o.data if o.data is not None else None):
        for fc in _fcurves(owner) if owner is not None else []:
            frames += [kp.co.x for kp in fc.keyframe_points]
    return (min(frames), max(frames), len(frames)) if frames else None


def motion_report(names=None, samples=5):
    """What moves in the scene, measured at a few frames across the timeline: per object its keys, world box,
    location/rotation/scale, a deformation signature, its light energy, a camera's view of its subject — and the
    sky. JSON for Jervis's checks; the current frame is left as it was."""
    s = _scene()   # noqa: F821
    keep = s.frame_current
    f0, f1 = s.frame_start, s.frame_end
    frames = sorted({int(round(f0 + (f1 - f0) * k / (samples - 1))) for k in range(samples)})
    objs = [o for o in bpy.data.objects if o.users_collection and not o.name.startswith("__")
            and (names is None or o.name in names)]
    watched = [o for o in objs if _animated(o) or o.type in ("CAMERA", "LIGHT") or
               any(_animated(a) for a in _ancestors(o))]   # noqa: F821
    report = {"scene": {"fps": fps(), "start": f0, "end": f1, "camera": s.camera.name if s.camera else None,
                        "frames": frames}, "objects": {}, "world": []}
    w = s.world
    bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None) if w and w.use_nodes else None
    from bpy_extras.object_utils import world_to_camera_view
    for o in watched:
        rng_ = _key_range(o)
        entry = {"type": o.type, "keys": rng_[2] if rng_ else 0, "key_range": list(rng_[:2]) if rng_ else None,
                 "drivers": len(o.animation_data.drivers) if o.animation_data else 0,
                 "noise": any(m.type == "NOISE" for fc in _fcurves(o) for m in fc.modifiers),
                 "modifiers": [m.type for m in getattr(o, "modifiers", [])], "samples": [],
                 "particles": 0, "parent": o.parent.name if o.parent else None}
        if o.type == "LIGHT":
            entry["light"] = {"kind": o.data.type, "energy": round(o.data.energy, 3), "color": list(o.data.color),
                              "target": o.get("jervis_energy")}
        if o.type == "CAMERA":
            entry["camera"] = {"subject": json.loads(o.get("jervis_subject", "[]") or "[]"), "lens": o.data.lens,
                               "move": o.get("jervis_move")}
        report["objects"][o.name] = entry
    for f in frames:
        s.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        if bg is not None:
            report["world"].append({"frame": f, "color": [round(c, 4) for c in bg.inputs["Color"].default_value[:3]],
                                    "strength": round(bg.inputs["Strength"].default_value, 4)})
        for o in watched:
            entry = report["objects"][o.name]
            pts = _world_points(o)   # noqa: F821
            sample = {"frame": f, "loc": [round(v, 4) for v in o.matrix_world.translation],
                      "rot": [round(v, 4) for v in o.matrix_world.to_euler()],
                      "scale": [round(v, 4) for v in o.matrix_world.to_scale()],
                      "lo": [round(min(p[i] for p in pts), 3) for i in range(3)],
                      "hi": [round(max(p[i] for p in pts), 3) for i in range(3)],
                      "hidden": bool(o.hide_render), "sig": _signature(o, dg)}
            if o.type == "LIGHT":
                ev = o.evaluated_get(dg)
                sample["energy"] = round(ev.data.energy, 4)
            if o.type == "MESH" and any(_shader_animated(s.material) for s in o.material_slots):
                sample["shader"] = _shader_value(o, dg)
            if o.type == "MESH":
                for ps in o.evaluated_get(dg).particle_systems:
                    alive = sum(1 for p in ps.particles if p.alive_state == "ALIVE")
                    entry["particles"] = max(entry["particles"], alive)
                    sample["particles"] = alive
            if o.type == "CAMERA":
                ev = o.evaluated_get(dg)
                subject = entry["camera"]["subject"]
                cam_pos = ev.matrix_world.translation
                sample["lens"] = round(ev.data.lens, 3)
                sample["aim"] = [round(v, 4) for v in (ev.matrix_world.to_quaternion() @ Vector((0, 0, -1)))]
                spts = []
                for n in subject:
                    so = bpy.data.objects.get(n)
                    if so is not None:
                        spts += _world_points(so)   # noqa: F821
                if spts:
                    lo_ = Vector([min(p[i] for p in spts) for i in range(3)])
                    hi_ = Vector([max(p[i] for p in spts) for i in range(3)])
                    corners = [Vector((x, y, z)) for x in (lo_.x, hi_.x) for y in (lo_.y, hi_.y) for z in (lo_.z, hi_.z)]
                    centre = (lo_ + hi_) / 2
                    view = [world_to_camera_view(s, ev, p) for p in corners + [centre]]
                    inside = [v for v in view[:-1] if 0 <= v.x <= 1 and 0 <= v.y <= 1 and v.z > 0]
                    c = view[-1]
                    hit = s.ray_cast(dg, cam_pos, (centre - cam_pos).normalized(), distance=(centre - cam_pos).length)
                    hit_obj = hit[4] if hit[0] else None
                    ignorable = hit_obj is not None and (
                        hit_obj.get("jervis_role") in ("sky", "library", "cutter") or
                        (hit_obj.parent is not None and hit_obj.parent.get("jervis_role") == "sky"))
                    blocker = hit_obj.name if hit_obj is not None and not ignorable else None
                    own = set(subject)
                    for n in subject:
                        so = bpy.data.objects.get(n)
                        if so is not None:
                            own |= {x.name for x in so.children_recursive}
                    sample["view"] = {"visible": round(len(inside) / 8, 3), "centre": [round(c.x, 3), round(c.y, 3)],
                                      "in_front": c.z > 0,
                                      "blocked_by": blocker if blocker and blocker not in own else None}
            entry["samples"].append(sample)
    s.frame_set(keep)
    return json.dumps(report)


# ---------- undo for motion ----------

def _anim_entry(owner):
    """Enough to put a datablock's animation back: a copy of its action, its drivers and (for objects) its
    constraints and modifiers."""
    ad = getattr(owner, "animation_data", None)
    entry = {"action": None, "drivers": []}
    if ad is not None:
        if ad.action is not None:
            copy = ad.action.copy()
            copy.use_fake_user = True
            copy["jervis_snap"] = True
            entry["action"] = copy.name
        entry["drivers"] = [[d.data_path, d.array_index] for d in ad.drivers]
    return entry


def anim_snapshot():
    """The scene's animation now (actions copied aside, drivers, constraints, modifiers, the timeline, the sky,
    light and camera settings), for anim_restore() to bring back exactly."""
    s = _scene()   # noqa: F821
    snap = {"scene": {"start": s.frame_start, "end": s.frame_end, "fps": s.render.fps, "fps_base": s.render.fps_base,
                      "camera": s.camera.name if s.camera else None,
                      "markers": [[m.name, m.frame, m.camera.name if m.camera else None] for m in s.timeline_markers]},
            "objects": {}, "data": {}, "materials": {}, "world": None}
    for o in bpy.data.objects:
        if not o.users_collection:
            continue
        e = _anim_entry(o)
        e["constraints"] = [c.name for c in o.constraints]
        e["modifiers"] = [m.name for m in getattr(o, "modifiers", [])]
        e["hide"] = [o.hide_viewport, o.hide_render]
        snap["objects"][str(o.session_uid)] = e
        if o.type in ("LIGHT", "CAMERA") and o.data is not None:
            d = _anim_entry(o.data)
            if o.type == "LIGHT":
                d["values"] = {"energy": o.data.energy, "color": list(o.data.color)}
            else:
                d["values"] = {"lens": o.data.lens}
            snap["data"][o.data.name] = d
    for m in bpy.data.materials:
        if m.node_tree is not None and m.node_tree.animation_data is not None:
            snap["materials"][m.name] = _anim_entry(m.node_tree)
    if s.world is not None and s.world.use_nodes:
        w, bg = _world()
        snap["world"] = dict(_anim_entry(w.node_tree), color=list(bg.inputs["Color"].default_value),
                             strength=bg.inputs["Strength"].default_value)
    return snap


def _anim_put_back(owner, entry):
    ad = getattr(owner, "animation_data", None)
    if entry is None or (entry["action"] is None and not entry["drivers"]):
        if ad is not None:
            owner.animation_data_clear()
        return
    ad = owner.animation_data_create()
    if entry["action"] and bpy.data.actions.get(entry["action"]):
        changed = ad.action
        ad.action = bpy.data.actions[entry["action"]].copy()   # the kept copy stays for another undo
        ad.action.use_fake_user = False
        if changed is not None and changed.users == 0:
            bpy.data.actions.remove(changed)
    elif ad.action is not None:
        ad.action = None
    keep = {(p, i) for p, i in entry["drivers"]}
    for d in list(ad.drivers):
        if (d.data_path, d.array_index) not in keep:
            ad.drivers.remove(d)


def anim_restore(snap):
    """Put the scene's animation back as anim_snapshot() saw it."""
    if not snap:
        return
    s = _scene()   # noqa: F821
    sc = snap.get("scene") or {}
    if sc:
        s.frame_start, s.frame_end = sc["start"], sc["end"]
        s.render.fps, s.render.fps_base = sc["fps"], sc["fps_base"]
        cam = bpy.data.objects.get(sc["camera"]) if sc.get("camera") else None
        s.camera = cam if cam is not None and cam.users_collection else s.camera if sc.get("camera") else None
        kept = {(n, f) for n, f, _ in sc.get("markers", [])}
        for m in list(s.timeline_markers):
            if (m.name, m.frame) not in kept:
                s.timeline_markers.remove(m)
    by_uid = {str(o.session_uid): o for o in bpy.data.objects}
    for uid, o in by_uid.items():
        e = snap["objects"].get(uid)
        if e is None:
            continue
        _anim_put_back(o, e)
        for c in list(o.constraints):
            if c.name not in e["constraints"]:
                o.constraints.remove(c)
        for m in list(getattr(o, "modifiers", [])):
            if m.name not in e["modifiers"]:
                o.modifiers.remove(m)
        o.hide_viewport, o.hide_render = e["hide"]
        if o.type in ("LIGHT", "CAMERA") and o.data is not None:
            d = snap["data"].get(o.data.name)
            _anim_put_back(o.data, d)
            for k, v in ((d or {}).get("values") or {}).items():
                setattr(o.data, k, v)
    for m in bpy.data.materials:
        if m.node_tree is None:
            continue
        e = snap["materials"].get(m.name)
        if e is not None or m.node_tree.animation_data is not None:
            _anim_put_back(m.node_tree, e)
    if snap.get("world") and s.world is not None:
        w, bg = _world()
        _anim_put_back(w.node_tree, snap["world"])
        bg.inputs["Color"].default_value = snap["world"]["color"]
        bg.inputs["Strength"].default_value = snap["world"]["strength"]


def purge_snapshots():
    """Drop the action copies earlier snapshots kept aside (called before each new request)."""
    for a in [a for a in bpy.data.actions if a.get("jervis_snap")]:
        bpy.data.actions.remove(a)


MOTION_BUILDERS = ("timeline", "sec", "fps", "animate", "move_to", "rise", "spin", "scale_to", "bounce", "appear",
                   "disappear", "colour_to", "open_door", "close_door", "drive", "animate_water", "sway", "drift",
                   "flicker", "flutter", "spin_parts", "animate_naturally", "wind", "rain", "snow", "smoke", "fire",
                   "cloud", "flag", "river", "waterfall", "camera", "camera_move", "cut_to", "light", "sky",
                   "lighting", "interior_lights", "pool_lights", "lights_on", "lights_off", "check_lights", "unblock_camera",
                   "motion_report", "anim_snapshot", "anim_restore", "purge_snapshots")
if bpy is not None:
    try:   # kit names too, restored before every step (see blender_kit._KIT)
        _KIT.update({k: v for k, v in globals().items() if callable(v) and not k.startswith("__")})   # noqa: F821
        _KIT.update({"MOTION_VERSION": MOTION_VERSION, "MOTION_BUILDERS": MOTION_BUILDERS, "cinema": cinema})   # noqa: F821
    except NameError:
        pass
