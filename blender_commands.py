"""Deterministic handling for the common, everyday Blender commands ("create a cube", "make it two times bigger",
"color it red", "rotate it 45 degrees", "delete the cube", "undo", "save") — tried before ever asking the AI.

Why this exists: BlenderComputerTask (see computer_use.py) asks a model to write bpy code from scratch for every
request, including a small local one when there's no Groq key. For the things people actually say most of the time,
that is slow and unreliable — a small model can wander, claim success without checking, or invent an interpretation
of something vague. Here, each recognized command runs one specific, known-correct bpy snippet, re-queries Blender
afterward to confirm it actually happened, and only then reports success — no model call involved at all, so it
takes well under a second. Anything not recognized here still falls through to BlenderComputerTask.

Several commands can be chained ("select the cube and make it red", "create a sphere then move it left"): each part
must be recognized here, or the whole request goes to the AI instead.

Object references ("it", "the second one", "the cube") resolve against `session.blender_objects`
(computer_use.ControlSession) first, then against Blender's real scene (its default "Cube", or whatever the user
selected by hand). "it" means the object the last command worked on.
"""
import re

_SHAPES = {
    "cube": "cube", "box": "cube",
    "sphere": "uv_sphere", "ball": "uv_sphere",
    "cylinder": "cylinder",
    "cone": "cone",
    "plane": "plane",
    "torus": "torus", "donut": "torus", "doughnut": "torus",
    "monkey": "monkey", "suzanne": "monkey",
}
# Each primitive operator takes its own size argument; passing `size` to the sphere/cylinder/cone/torus ones fails.
_SHAPE_ARGS = {"cube": "size=2", "plane": "size=2", "monkey": "size=2", "uv_sphere": "radius=1",
               "cylinder": "radius=1, depth=2", "cone": "radius1=1, depth=2", "torus": "major_radius=1, minor_radius=0.25"}
_SHAPE_WORDS = r"(?:cube|box|sphere|ball|cylinder|cone|plane|torus|donut|doughnut|monkey|suzanne)"
_COLORS = {"red": (0.8, 0.02, 0.02), "green": (0.05, 0.6, 0.05), "blue": (0.02, 0.1, 0.8),
           "yellow": (0.9, 0.8, 0.02), "orange": (0.9, 0.3, 0.02), "purple": (0.4, 0.05, 0.7),
           "pink": (0.9, 0.3, 0.5), "white": (0.9, 0.9, 0.9), "black": (0.01, 0.01, 0.01),
           "gray": (0.3, 0.3, 0.3), "grey": (0.3, 0.3, 0.3), "brown": (0.25, 0.1, 0.03),
           "gold": (0.9, 0.6, 0.1), "silver": (0.7, 0.7, 0.75), "cyan": (0.02, 0.7, 0.8)}
_PLEASE = r"^(?:please |can you |could you |would you |now )*"
_NUMBER = r"(?:\d+(?:\.\d+)?|two|three|four|five|ten)"
_TIMES_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "half": 2}

_CREATE = re.compile(
    _PLEASE + r"(?:create|add|make|build|insert)\s+(?:me\s+)?(?:a |an |another |a second |a third |one more |a new )?"
    rf"(?P<shape>{_SHAPE_WORDS})\b(?:\s+(?:in blender|please|for me))?\.?$", re.I)
_RESIZE_WORD = r"(?:taller|shorter|higher|lower|wider|narrower|bigger|larger|smaller|thinner|fatter)"
_RESIZE = re.compile(_PLEASE + rf"make\s+(?P<ref>.+?)\s+(?:(?P<times>{_NUMBER})\s*(?:times|x)\s+)?"
                     rf"(?P<direction>{_RESIZE_WORD})(?:\s+than (?:before|now|it is))?\.?$", re.I)
_TWICE = re.compile(_PLEASE + r"make\s+(?P<ref>.+?)\s+(?:twice|double)(?:\s+as\s+(?:big|large))?"
                    r"(?:\s+(?:the|its) size)?\.?$", re.I)
_HALF = re.compile(_PLEASE + r"make\s+(?P<ref>.+?)\s+half\s+(?:the|its|as)\s+(?:size|big|large)\.?$", re.I)
_DOUBLE = re.compile(_PLEASE + r"double\s+(?:the size of\s+)?(?P<ref>.+?)(?:'s size)?\.?$", re.I)
_SCALE = re.compile(_PLEASE + r"(?:scale|resize)\s+(?P<ref>.+?)\s+(?P<way>up|down)?\s*(?:by|to)?\s*(?:a factor of\s+)?"
                    rf"(?P<times>{_NUMBER}|half)\s*(?:times|x)?\.?$", re.I)
_COLOR = re.compile(
    _PLEASE + r"(?:make|colou?r|paint|turn|change(?: the colou?r of)?|set the colou?r of)\s+(?P<ref>.+?)\s+"
    r"(?:to\s+|into\s+)?(?:the colou?r\s+)?(?P<color>" + "|".join(_COLORS) + r")(?:\s+colou?r)?\.?$", re.I)
_ROTATE = re.compile(
    _PLEASE + r"(?:rotate|spin)\s+(?P<ref>.+?)(?:\s+(?:by\s+)?(?P<deg>-?\d+(?:\.\d+)?)\s*(?:degrees?|°))?"
    r"(?:\s+(?:around|on|about|along)\s+(?:the\s+)?(?P<axis>[xyz])(?:[ -]?axis)?)?\.?$", re.I)
_DELETE = re.compile(_PLEASE + r"(?:delete|remove|get rid of)\s+(?P<ref>.+?)\.?$", re.I)
_DUPLICATE = re.compile(_PLEASE + r"(?:duplicate|copy|clone)\s+(?P<ref>.+?)\.?$", re.I)
_SELECT = re.compile(_PLEASE + r"select\s+(?P<ref>.+?)\.?$", re.I)
_DIRECTION_WORD = r"(?:left|right|up|down|forward|forwards|back|backward|backwards)"
_MOVE_NEXT_TO = re.compile(
    _PLEASE + r"(?:move|put|place)\s+(?P<ref>.+?)\s+next to\s+(?P<target>.+?)\.?$", re.I)
_NEW_THING = re.compile(r"(?:a|an|another|some|one more|two|three|four|\d+)\s", re.I)
_MOVE_DIR = re.compile(_PLEASE + rf"move\s+(?P<ref>.+?)\s+(?P<direction>{_DIRECTION_WORD})\.?$", re.I)
_FOCUS = re.compile(r"^(?:please )?(?:go (?:back )?to|switch (?:back )?to|bring (?:back )?|focus (?:back )?(?:on )?)"
                    r"\s*blender\.?$", re.I)
_UNDO = re.compile(r"^(?:please )?undo(?:\s+(?:that|it|the last (?:change|action|step)))?\.?$", re.I)
_REDO = re.compile(r"^(?:please )?redo(?:\s+(?:that|it))?\.?$", re.I)
_ANOTHER = re.compile(r"^(?:please |now )?(?:create|make|add|build)\s+(?:another|one more)(?:\s+one)?\.?$", re.I)
_AGAIN = re.compile(r"^(?:do (?:that|it) again|again|repeat that|repeat it|one more time)\.?$", re.I)
_SAVE = re.compile(r"^(?:please )?save(?:\s+(?:the\s+)?(?:project|file|scene|blend(?:er)? file|it))?"
                   r"(?:\s+as\s+(?P<name>[\w .'-]+?))?\.?$", re.I)
# What a reference to a scene object looks like, so "delete the timer" / "copy that link" while Blender happens to
# be open aren't taken as Blender commands.
_OBJECT_REF_FULL = re.compile(
    r"(?:the |that |this |my )?(?:(?:first|second|third|fourth|fifth|last|selected|active|other|new)\s+)?"
    rf"(?:it|that|this|them|one|object|selection|everything|all|{_SHAPE_WORDS}|camera|light|lamp|mesh|"
    r"[a-z]+\.\d{3})(?:\s+(?:one|object))?", re.I)


def _is_object_ref(ref: str, session=None) -> bool:
    """A reference to a scene object: "it", "the cube", "the second one" — or a part this session built ("the
    roof" after a house was built with a 'House Roof')."""
    if _OBJECT_REF_FULL.fullmatch(" ".join((ref or "").split())):
        return True
    w = _clean_ref(ref)
    return bool(w and session is not None and len(w) > 2 and
                any(form in o["name"].lower() for form in _forms(w) for o in getattr(session, "blender_objects", [])))

# Speech recognition's usual mishearings ("make the cube be girl" = "bigger", "two times the big hill").
_MISHEARD = [(re.compile(r"\bbe (?:girl|gear|ger|gur|ghur)\b", re.I), "bigger"),
             (re.compile(r"\bsmall (?:her|ur)\b", re.I), "smaller"),
             (re.compile(rf"\b({_NUMBER})\s+times\s+(?:the|as|its)\s+(?:big|large|size)\w*\b.*$", re.I), r"\1 times bigger"),
             (re.compile(rf"\bsize\s+(?=(?:{_NUMBER})\s*(?:times|x)\b)", re.I), ""),
             (re.compile(r"\bthe cube's\b", re.I), "the cube")]
_FILLER = re.compile(r"^(?:(?:okay|ok|so|now|and|alright|all right|well|hey|jervis|jarvis|blender|please|"
                     r"in blender|actually|um+|uh+|hmm+|oh)\b[,.!]?\s*)+", re.I)
_CLAUSE_SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:and then|and also|and|then|after that)\b\s*,?\s*", re.I)

_ORDINAL = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
            "fifth": 4, "5th": 4, "last": -1, "latest": -1, "newest": -1}
_GROW = {"taller": True, "higher": True, "shorter": False, "lower": False, "wider": True, "narrower": False,
         "bigger": True, "larger": True, "smaller": False, "fatter": True, "thinner": False}
_RESIZE_AXES = {"taller": (0, 0, 1), "higher": (0, 0, 1), "shorter": (0, 0, 1), "lower": (0, 0, 1),
                "wider": (1, 0, 0), "narrower": (1, 0, 0), "fatter": (1, 1, 0), "thinner": (1, 1, 0),
                "bigger": (1, 1, 1), "larger": (1, 1, 1), "smaller": (1, 1, 1)}
_DIRECTION_VECTOR = {"left": (-1, 0, 0), "right": (1, 0, 0), "up": (0, 0, 1), "down": (0, 0, -1),
                     "forward": (0, 1, 0), "forwards": (0, 1, 0), "back": (0, -1, 0), "backward": (0, -1, 0),
                     "backwards": (0, -1, 0)}
MOVE_STEP = 2.0
RESIZE_FACTOR = 1.4

# (plural too: "no, I meant the windows" ... "now make them bigger" — the windows; a multi-part group is all its
# parts, see _focus_group)
_GENERIC_REF = ("it", "", "object", "one", "thing", "selected", "selection", "selected object", "selected one",
                "active object", "that", "this", "them", "those", "these", "they")
_SCENE = ("scene = getattr(bpy.context, 'scene', None) or bpy.data.scenes[0]\n"
          "layer = scene.view_layers[0]\n")


# ---------- object references ----------

def _clean_ref(ref_text: str) -> str:
    w = re.sub(r"[^a-z0-9 ]", " ", (ref_text or "").lower()).strip()
    w = re.sub(r"^(?:the colou?r of|the size of)\s+", "", w)
    return re.sub(r"^(?:the|that|this|my)\s+", "", w).strip()


def _forms(w: str) -> list:
    """The words to look for: "windows" also finds 'House Window Frames', "the boxes" a 'Box'."""
    forms = [w]
    if len(w) > 3 and w.endswith("es") and w[:-2].endswith(("x", "ch", "sh", "ss")):
        forms.append(w[:-2])
    elif len(w) > 3 and w.endswith("ies"):
        forms.append(w[:-3] + "y")
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        forms.append(w[:-1])
    return forms


def _resolve_reference(ref_text: str, session, bridge=None):
    """Which object (its real Blender name) `ref_text` ("it", "the second one", "the cube") means, or None if
    nothing matches. Objects Jervis made this session come first; otherwise the real scene is asked (Blender's
    default "Cube", or whatever the user selected by hand), never guessed."""
    found = _resolve_tracked(ref_text, session)
    if found and bridge is not None and not _exists(bridge, found):
        _forget(session, found)   # deleted by hand since: look in the scene instead
        found = None
    if not found and bridge is not None:
        found = _resolve_in_scene(ref_text, bridge)
        if found:
            session.remember_blender_object(found, "")
    if found:
        session.blender_focus = found
        if _clean_ref(ref_text) not in _GENERIC_REF:
            session.blender_focus_group = None   # a part named on its own ("the roof"): from now on, "it" is that
    return found


def _exists(bridge, name: str) -> bool:
    response = _run(bridge, _SCENE + f"RESULT = '1' if {name!r} in scene.objects else '0'", timeout=8)
    return response.get("output") != "0"   # only a definite "not there" counts; an odd answer keeps the name


def _forget(session, name: str) -> None:
    session.blender_objects[:] = [o for o in session.blender_objects if o["name"] != name]
    if getattr(session, "blender_focus", None) == name:
        session.blender_focus = None


def _resolve_in_scene(ref_text: str, bridge):
    w = _clean_ref(ref_text)
    response = _run(bridge, f"w = {w!r}\nforms = {_forms(w)!r}\n" + _SCENE +
                            "objs = list(scene.objects)\n"
                            f"if w in {_GENERIC_REF!r}:\n"
                            "    pick = layer.objects.active or next((o for o in objs if o.select_get(view_layer=layer)),"
                            " None)\n"
                            "else:\n"
                            "    pick = None\n"
                            "    for w in forms:\n"
                            "        pick = (next((o for o in objs if o.name.lower() == w), None)\n"
                            "                or next((o for o in objs if o.name.lower().endswith(' ' + w)), None)\n"
                            "                or next((o for o in objs if o.name.lower().startswith(w)), None)\n"
                            "                or next((o for o in objs if w.endswith(o.name.lower())), None)\n"
                            "                or next((o for o in reversed(objs) if len(w) > 2 and w in o.name.lower()),"
                            " None))\n"
                            "        if pick: break\n"
                            "RESULT = pick.name if pick else ''", timeout=8)
    if not response.get("ok"):
        return None
    return (response.get("output") or "").strip() or None


def _resolve_tracked(ref_text: str, session):
    w = _clean_ref(ref_text)
    if not session.blender_objects:
        return None
    if w in _GENERIC_REF:
        return getattr(session, "blender_focus", None) or session.last_blender_object
    for word, idx in _ORDINAL.items():
        if re.search(rf"\b{word}\b", w):
            try:
                return session.blender_objects[idx]["name"]
            except IndexError:
                return None
    # "the ball" is the sphere, "the box" the cube: the words _SHAPES accepts when creating them
    kinds_said = {"sphere" if _SHAPES[x] == "uv_sphere" else _SHAPES[x] for x in w.split() if x in _SHAPES}
    for obj in reversed(session.blender_objects):
        if obj["kind"] and (obj["kind"] in w or obj["kind"] in kinds_said):
            return obj["name"]
    for obj in session.blender_objects:
        if obj["name"].lower() in w:
            return obj["name"]
    for form in _forms(w):   # "the roof" is 'House Roof' itself, before 'House Roof Ridge'
        for obj in session.blender_objects:
            if len(form) > 2 and obj["name"].lower().endswith(" " + form):
                return obj["name"]
    for form in _forms(w):
        for obj in reversed(session.blender_objects):
            if len(form) > 2 and form in obj["name"].lower():
                return obj["name"]
    return None   # names something not tracked here: the scene lookup decides


def _run(bridge, code: str, timeout: float = 15):
    return bridge.run(code, timeout=timeout)


def _error(response) -> str:
    return (response.get("error") or "unknown error").strip().splitlines()[-1][:200]


def _target(bridge, session, ref_text: str, doing: str) -> str:
    name = _resolve_reference(ref_text, session, bridge)
    if not name:
        raise RuntimeError(f"I couldn't find \"{ref_text.strip()}\" in Blender's scene, so I didn't {doing}.")
    return name


def _before_after(response, failed: str, unchanged: str):
    if not response.get("ok"):
        raise RuntimeError(f"{failed}: {_error(response)}")
    before, _, after = (response.get("output") or "").partition("|")
    if not after or before == after:
        raise RuntimeError(unchanged)
    return before


# ---------- "it" = the whole thing the agent just built (a tree is trunk + crown) ----------

def _focus_group(ref_text: str, session, bridge=None):
    """Every part of a multi-part thing: "it"/"that" right after a build ("add a tree" -> "make it bigger"), or a
    thing named by what its parts share ("the car" = 'Car Body', 'Car Cabin', 'Car Wheel 1'... when nothing is
    called just 'Car')."""
    if session is None:
        return None
    w = _clean_ref(ref_text)
    group = getattr(session, "blender_focus_group", None)
    if group and len(group) > 1 and w in ("it", "that", "this", "them", ""):
        return list(group)
    names = [o["name"] for o in getattr(session, "blender_objects", [])]
    if bridge is not None and w and not any(n.lower().startswith(w + " ") for n in names):
        # Built before this session (Jervis restarted): ask the scene itself.
        listed = _run(bridge, _SCENE + "RESULT = '|'.join(o.name for o in scene.objects if o.type == 'MESH')  # scene names",
                      timeout=8)
        names = [n for n in (listed.get("output") or "").split("|") if n] if listed.get("ok") else names
    if w and len(w) > 2 and not any(n.lower() == w for n in names):
        members = [n for n in names if n.lower().startswith(w + " ")]
        if len(members) > 1:
            return members
    return None


_GROUP_CODE = """import json, math, mathutils
names = {names!r}
objs = [bpy.data.objects.get(n) for n in names]
objs = [o for o in objs if o is not None]
if not objs:
    raise KeyError('Those objects are no longer in the scene')
def state(o):
    return [list(o.location), list(o.rotation_euler), list(o.scale), o.active_material.name if o.active_material else None]
before = {{o.name: state(o) for o in objs}}
pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
pivot = mathutils.Vector(((min(p.x for p in pts) + max(p.x for p in pts)) / 2,
                          (min(p.y for p in pts) + max(p.y for p in pts)) / 2, min(p.z for p in pts)))
around = mathutils.Matrix.Translation(pivot)
{body}
after = {{o.name: state(o) for o in objs if o.name in bpy.data.objects}}
RESULT = json.dumps([before, after])"""

_GROUP_RESTORE = """import json
for name, (loc, rot, scl, mat) in json.loads({before!r}).items():
    o = bpy.data.objects.get(name)
    if o is None: continue
    o.location, o.rotation_euler, o.scale = loc, rot, scl
    if o.data is not None and hasattr(o.data, 'materials'):
        if mat and bpy.data.materials.get(mat):
            if o.data.materials: o.data.materials[0] = bpy.data.materials[mat]
            else: o.data.materials.append(bpy.data.materials[mat])
        elif not mat:
            o.data.materials.clear()
RESULT = 'restored'"""


def _group_run(bridge, session, names, body: str, doing: str, description: str) -> None:
    import json
    response = _run(bridge, _GROUP_CODE.format(names=names, body=body), timeout=20)
    if not response.get("ok"):
        raise RuntimeError(f"I tried to {doing} but Blender reported an error: {_error(response)}")
    before, after = json.loads(response.get("output") or "[{}, {}]")
    if before == after:
        raise RuntimeError(f"I ran it, but nothing in Blender actually changed — I won't claim I could {doing}.")
    session.last_undo = {"description": description, "code": _GROUP_RESTORE.format(before=json.dumps(before))}


def _group_matrix(bridge, session, names, matrix_code: str, doing: str, description: str) -> None:
    body = (f"m = around @ ({matrix_code}) @ around.inverted()\n"
            "for o in objs:\n"
            "    if o.parent is None or o.parent not in objs:\n"
            "        o.matrix_world = m @ o.matrix_world")
    _group_run(bridge, session, names, body, doing, description)


# ---------- actions: each runs, checks Blender's real state, and only then reports success ----------

def _create_action(bridge, session, shape_word: str):
    op = _SHAPES.get(shape_word.lower(), "cube")
    kind = "sphere" if op == "uv_sphere" else op

    def action():
        offset = sum(1 for o in session.blender_objects if o["kind"] == kind) * 3.0
        response = _run(bridge, "before = set(bpy.data.objects.keys())\n"
                                f"bpy.ops.mesh.primitive_{op}_add({_SHAPE_ARGS[op]}, location=({offset}, 0, 0))\n"
                                "made = [n for n in bpy.data.objects.keys() if n not in before]\n"
                                "RESULT = made[0] if made else ''")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to create a {shape_word} but Blender reported an error: {_error(response)}")
        new_name = (response.get("output") or "").strip()
        verify = _run(bridge, f"RESULT = '1' if bpy.data.objects.get({new_name!r}) else '0'", timeout=8)
        if not new_name or verify.get("output") != "1":
            raise RuntimeError(f"I ran the command to create a {shape_word}, but Blender's scene doesn't actually "
                               "show it — I won't claim that worked.")
        session.remember_blender_object(new_name, kind)
        session.blender_focus = new_name
        session.blender_focus_group = None
        session.last_undo = {"description": f"created a {shape_word}",
                             "code": f"obj = bpy.data.objects.get({new_name!r})\n"
                                     "if obj: bpy.data.objects.remove(obj, do_unlink=True)\n"
                                     "RESULT = 'removed'"}
        return f"Done — I created a {shape_word} ({new_name})."
    return action


def _asset_part(bridge, name: str):
    """{"root", "type", "params"} when `name` is one part of a finished asset (blender_assets: a house's windows, a
    tree's leaves) rather than the asset itself; None otherwise (or when the kit isn't loaded in this Blender)."""
    import json
    response = _run(bridge, f"info = asset_info({name!r}) if 'asset_info' in globals() else None\n"
                            f"RESULT = json.dumps(info) if info and info.get('root') != {name!r} else ''", timeout=8)
    try:
        return json.loads(response.get("output") or "null") if response.get("ok") else None
    except ValueError:
        return None


def _rebuild_asset(bridge, session, root: str, changes: dict, description: str) -> None:
    """Build an asset again with options changed, undoably (the old parts are kept aside, see agent_blender)."""
    import agent_blender
    snapshot = _run(bridge, agent_blender._SNAPSHOT_CODE, timeout=10)
    args = ", ".join(f"{k}={v!r}" for k, v in changes.items())
    # Grown bigger: what stood beside it keeps its place beside it, just clear of it (blender_world.make_room)
    grows = any(k in changes for k in ("width", "depth", "length", "size", "floors", "radius", "height"))
    room = f"\nif 'make_room' in globals(): make_room({root!r})" if grows else ""
    response = _run(bridge, f"rebuild_asset({root!r}, {args}){room}\n"
                            f"RESULT = json.dumps(asset_info({root!r})['params'])", timeout=60)
    if not response.get("ok"):
        raise RuntimeError(f"I tried to rebuild {root} but Blender reported an error: {_error(response)}")
    import json
    params = json.loads(response.get("output") or "{}")
    if any(params.get(k) != v for k, v in changes.items()):
        raise RuntimeError(f"I rebuilt {root}, but its options didn't change as asked — I won't claim that worked.")
    if snapshot.get("ok"):
        try:
            session.last_undo = {"description": description,
                                 "code": agent_blender._restore_code(json.loads(snapshot.get("output") or "{}"))}
        except ValueError:
            pass


def _resize_action(bridge, session, ref_text: str, direction: str, times: float = None):
    def action():
        amount = times or RESIZE_FACTOR
        factor = amount if _GROW[direction] else 1 / amount
        ax, ay, az = _RESIZE_AXES[direction]
        sx, sy, sz = (factor if ax else 1.0), (factor if ay else 1.0), (factor if az else 1.0)
        how = (("half the size" if direction == "smaller" and amount == 2 else f"{amount:g} times {direction}")
               if times else direction)
        group = _focus_group(ref_text, session, bridge)
        if group:   # the whole build grows from where it stands, its parts staying together
            _group_matrix(bridge, session, group, f"mathutils.Matrix.Diagonal(({sx}, {sy}, {sz}, 1.0))",
                          f"make it {how}", f"made it {how}")
            return f"Done — I made it {how} (all {len(group)} parts)."
        name = _target(bridge, session, ref_text, "resize anything")
        part = _asset_part(bridge, name)
        if part:
            if part["type"] == "house" and "window" in name.lower() and direction in ("bigger", "larger", "smaller"):
                # One option sizes every window and its opening together; scaling the frames object alone would
                # push them off the walls (they all share the house's origin).
                old = float(part["params"].get("window_scale") or 1.0)
                new = round(max(0.5, min(1.8, old * factor)), 3)
                if new == round(old, 3):
                    raise RuntimeError(f"The windows of {part['root']} are already as "
                                       f"{'big' if factor > 1 else 'small'} as they can be.")
                _rebuild_asset(bridge, session, part["root"], {"window_scale": new}, f"made the windows {how}")
                return f"Done — I rebuilt {part['root']} with {direction} windows."
            # Any other part of an asset grows from its own base, where it stands (a chimney gets taller upward).
            _group_matrix(bridge, session, [name], f"mathutils.Matrix.Diagonal(({sx}, {sy}, {sz}, 1.0))",
                          f"make it {how}", f"made it {how}")
            return f"Done — I made {name} {how}."
        response = _run(bridge, f"obj = bpy.data.objects.get({name!r})\n"
                                f"before = tuple(obj.scale)\n"
                                f"obj.scale = (obj.scale[0]*{sx}, obj.scale[1]*{sy}, obj.scale[2]*{sz})\n"
                                f"RESULT = str(before) + '|' + str(tuple(obj.scale))")
        before_s = _before_after(response, f"I tried to make it {direction} but Blender reported an error",
                                 "I ran the resize, but the object's scale in Blender didn't actually change — "
                                 "I won't claim that worked.")
        session.last_undo = {"description": f"made it {how}",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"obj.scale = {before_s}\nRESULT = 'restored'"}
        return f"Done — I made {name} {how}."
    return action


def _move_direction_action(bridge, session, ref_text: str, direction: str):
    def action():
        dx, dy, dz = _DIRECTION_VECTOR[direction]
        group = _focus_group(ref_text, session, bridge)
        if group:
            _group_matrix(bridge, session, group, "mathutils.Matrix.Translation(("
                          f"{dx * MOVE_STEP}, {dy * MOVE_STEP}, {dz * MOVE_STEP}))", f"move it {direction}",
                          f"moved it {direction}")
            return f"Done — I moved it {direction} (all {len(group)} parts)."
        name = _target(bridge, session, ref_text, "move anything")
        response = _run(bridge, f"obj = bpy.data.objects.get({name!r})\n"
                                f"before = tuple(obj.location)\n"
                                f"obj.location = (obj.location[0]+{dx * MOVE_STEP}, "
                                f"obj.location[1]+{dy * MOVE_STEP}, obj.location[2]+{dz * MOVE_STEP})\n"
                                f"RESULT = str(before) + '|' + str(tuple(obj.location))")
        before_s = _before_after(response, f"I tried to move it {direction} but Blender reported an error",
                                 "I ran the move, but the object's location in Blender didn't actually change — "
                                 "I won't claim that worked.")
        session.last_undo = {"description": f"moved it {direction}",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"obj.location = {before_s}\nRESULT = 'restored'"}
        return f"Done — I moved {name} {direction}."
    return action


def _move_next_to_action(bridge, session, ref_text: str, target_text: str):
    def action():
        name = _resolve_reference(ref_text, session, bridge)
        target_name = _resolve_reference(target_text, session, bridge)
        if target_name == name:
            others = [o["name"] for o in session.blender_objects if o["name"] != name]
            target_name = others[-1] if others else None
        if not name or not target_name:
            raise RuntimeError("I don't have two distinct objects to work with yet in this session.")
        session.blender_focus = name
        # Beside it means outside its footprint, clear of everything (the kit's place_near measures both whole
        # things); without the kit, at least clear of its bounds — never "3 m from its origin", which is inside a
        # house.
        response = _run(bridge, "import json, mathutils\n"
                                f"obj = bpy.data.objects.get({name!r})\n"
                                f"ref = bpy.data.objects.get({target_name!r})\n"
                                "tops = [o for o in bpy.data.objects if o.parent is None and o.users_collection]\n"
                                "spots = {o.name: [round(v, 4) for v in o.location] for o in tops}\n"
                                "if 'place_near' in globals() and obj.parent is None:\n"
                                f"    place_near({name!r}, {target_name!r}, 'beside')\n"
                                "else:\n"
                                "    def box_of(o):\n"
                                "        fam = [o] + list(o.children_recursive)\n"
                                "        pts = [x.matrix_world @ mathutils.Vector(c) for x in fam for c in x.bound_box]\n"
                                "        return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]\n"
                                "    (a0, a1), (b0, b1) = box_of(obj), box_of(ref)\n"
                                "    obj.location.x += (b1[0] + 1.0) - a0[0]\n"
                                "    obj.location.y += (b0[1] + b1[1]) / 2 - (a0[1] + a1[1]) / 2\n"
                                "bpy.context.view_layer.update()\n"
                                "moved = {n: v for n, v in spots.items() if bpy.data.objects.get(n) is not None\n"
                                "         and [round(x, 4) for x in bpy.data.objects[n].location] != v}\n"
                                "if obj.parent is not None and obj.name not in moved:\n"
                                "    moved[obj.name] = spots.get(obj.name)\n"
                                "RESULT = json.dumps(moved)")
        if not response.get("ok"):
            raise RuntimeError("I tried to move it next to the other object but Blender reported an error: "
                               f"{_error(response)}")
        import json
        try:
            moved = json.loads(response.get("output") or "")
        except ValueError:
            raise RuntimeError("I ran the move, but Blender didn't report a location back — I won't claim that "
                               "worked.") from None
        moved = {n: v for n, v in (moved or {}).items() if v is not None}
        if not moved:
            # It was already exactly where "next to" would put it (e.g. still at its original creation offset) —
            # genuinely nothing to do, not a failure to report as one.
            return "Done — it was already next to the other one."
        session.last_undo = {"description": "moved it next to the other one",
                             "code": f"for n, v in {moved!r}.items():\n"
                                     "    o = bpy.data.objects.get(n)\n"
                                     "    if o is not None: o.location = v\n"
                                     "RESULT = 'restored'"}
        return "Done — I moved it next to the other one."
    return action


# Colouring a whole finished asset means its main surface, not every part: a red house has red walls, not red
# window glass, steps and gutters; a yellow tree has yellow leaves.
_ASSET_COLOUR_PARTS = {"house": ("Walls", "Gables"), "tree": ("Leaves", "Fronds", "Needles"), "bush": ("Leaves",),
                       "fence": ("Boards",), "rock": ("Stone",), "water": ("Surface",), "island": ("Terrain",)}

_COLOUR_TARGETS = """import json  # colour targets
names = {names!r}
parts = {parts!r}
def surfaces(root):
    kind = json.loads(root['jervis_asset'])['type']
    return [c.name for c in root.children if c.type == 'MESH' and any(c.name == root.name + ' ' + p
                                                                       for p in parts.get(kind, ()))]
objs = [bpy.data.objects.get(n) for n in names]
objs = [o for o in objs if o is not None]
out = []
if len(objs) == 1 and objs[0].get('jervis_asset'):          # the asset itself ("the house")
    out = surfaces(objs[0])
elif len(objs) == 1 and objs[0].type == 'EMPTY':               # a group the agent built: all its parts
    out = [c.name for c in objs[0].children_recursive if c.type == 'MESH']
elif len(objs) == 1:                                          # a part, with the pieces of its surface
    out = [objs[0].name] + [o.name for o in bpy.data.objects if o.users_collection and o.type == 'MESH'
                            and o.name.startswith(objs[0].name + ' ')
                            and o.name[len(objs[0].name) + 1:].lower() in ('ridge', 'cap', 'caps', 'trim', 'edge')]
else:                                                         # every part of one asset ("it", right after a build)
    roots = set()
    for o in objs:
        r = o
        while r is not None and not r.get('jervis_asset'):
            r = r.parent
        roots.add(r.name if r is not None else None)
    if len(roots) == 1 and None not in roots:
        out = surfaces(bpy.data.objects[roots.pop()])
RESULT = json.dumps(out)"""


def _colour_targets(bridge, names) -> list:
    """What colouring `names` should really change: a finished asset's main surface (a red house has red walls, not
    red window glass and gutters; a yellow tree, yellow leaves), or a part together with the pieces named after it
    ('House Roof' and 'House Roof Ridge'). [] when there's nothing to add (colour exactly what was named)."""
    import json
    response = _run(bridge, _COLOUR_TARGETS.format(names=list(names), parts=_ASSET_COLOUR_PARTS), timeout=8)
    try:
        out = json.loads(response.get("output") or "[]") if response.get("ok") else []
    except ValueError:
        return []
    return [n for n in out if isinstance(n, str)] if isinstance(out, list) else []


def _color_action(bridge, session, ref_text: str, color: str):
    r, g, b = _COLORS[color.lower()]

    def action():
        material = f"Jervis {color.lower()}"
        group = _focus_group(ref_text, session, bridge)
        name = None
        if group:
            group = _colour_targets(bridge, group) or group
        else:
            name = _target(bridge, session, ref_text, "color anything")
            targets = _colour_targets(bridge, [name])
            group = targets if targets and targets != [name] else None
            if group:   # "the roof" was 'House Roof' + 'House Roof Ridge': "now make them smaller" means both
                session.blender_focus_group = list(group)
        if group:
            body = (f"mat = bpy.data.materials.get({material!r}) or bpy.data.materials.new({material!r})\n"
                    f"mat.diffuse_color = ({r}, {g}, {b}, 1)\n"
                    "try:\n"
                    "    mat.use_nodes = True\n"
                    f"    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = ({r}, {g}, {b}, 1)\n"
                    "except Exception:\n"
                    "    pass\n"
                    "for o in objs:\n"
                    "    if o.data is not None and hasattr(o.data, 'materials'):\n"
                    "        if o.data.materials:\n"
                    "            for i in range(len(o.data.materials)): o.data.materials[i] = mat\n"
                    "        else:\n"
                    "            o.data.materials.append(mat)")
            _group_run(bridge, session, group, body, f"color it {color}", f"colored it {color}")
            shown = ", ".join(group[:3]) + (" ..." if len(group) > 3 else "")
            return f"Done — {shown} {'is' if len(group) == 1 else 'are'} {color} now."
        response = _run(bridge, f"obj = bpy.data.objects.get({name!r})\n"
                                "before = obj.active_material.name if obj.active_material else ''\n"
                                f"mat = bpy.data.materials.get({material!r}) or bpy.data.materials.new({material!r})\n"
                                f"mat.diffuse_color = ({r}, {g}, {b}, 1)\n"
                                "try:\n"
                                "    mat.use_nodes = True\n"
                                "    bsdf = mat.node_tree.nodes.get('Principled BSDF')\n"
                                f"    if bsdf: bsdf.inputs['Base Color'].default_value = ({r}, {g}, {b}, 1)\n"
                                "except Exception:\n"
                                "    pass\n"
                                "if obj.data and hasattr(obj.data, 'materials'):\n"
                                "    if obj.data.materials:\n"
                                "        obj.data.materials[0] = mat\n"
                                "    else:\n"
                                "        obj.data.materials.append(mat)\n"
                                "RESULT = before + '|' + (obj.active_material.name if obj.active_material else '')")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to color it {color} but Blender reported an error: {_error(response)}")
        before, _, after = (response.get("output") or "").partition("|")
        if after != material:
            raise RuntimeError(f"I ran the color change, but {name} doesn't show the {color} material — I won't "
                               "claim that worked.")
        restore = f"bpy.data.materials.get({before!r})" if before else "None"
        session.last_undo = {"description": f"colored it {color}",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"old = {restore}\n"
                                     "if old: obj.data.materials[0] = old\n"
                                     "else: obj.data.materials.clear()\n"
                                     "RESULT = 'restored'"}
        return f"Done — {name} is {color} now."
    return action


def _rotate_action(bridge, session, ref_text: str, degrees: float, axis: str):
    index = "xyz".index(axis)

    def action():
        group = _focus_group(ref_text, session, bridge)
        if group:   # turns as one piece around its own middle
            _group_matrix(bridge, session, group, f"mathutils.Matrix.Rotation(math.radians({degrees}), 4, "
                                                  f"{axis.upper()!r})",
                          f"rotate it {degrees:g} degrees", f"rotated it {degrees:g} degrees")
            return f"Done — I rotated it {degrees:g} degrees around {axis.upper()} (all {len(group)} parts)."
        name = _target(bridge, session, ref_text, "rotate anything")
        response = _run(bridge, "import math\n"
                                f"obj = bpy.data.objects.get({name!r})\n"
                                "before = tuple(obj.rotation_euler)\n"
                                f"obj.rotation_euler[{index}] += math.radians({degrees})\n"
                                "RESULT = str(before) + '|' + str(tuple(obj.rotation_euler))")
        before_s = _before_after(response, "I tried to rotate it but Blender reported an error",
                                 "I ran the rotation, but the object didn't actually turn — I won't claim that "
                                 "worked.")
        session.last_undo = {"description": f"rotated it {degrees:g} degrees",
                             "code": f"obj = bpy.data.objects.get({name!r})\n"
                                     f"obj.rotation_euler = {before_s}\nRESULT = 'restored'"}
        return f"Done — I rotated {name} {degrees:g} degrees around {axis.upper()}."
    return action


def _delete_group(bridge, session, names) -> str:
    import json
    # Each object's parent and place are recorded first, so "undo" puts the group back together exactly.
    response = _run(bridge, _SCENE + "import json\n"
                            f"kept = {{}}\n"
                            f"names = {names!r}\n"
                            "info = {n: (bpy.data.objects[n].parent.name if bpy.data.objects[n].parent else '',\n"
                            "            [list(r) for r in bpy.data.objects[n].matrix_world])\n"
                            "        for n in names if bpy.data.objects.get(n) is not None}\n"
                            "for n in names:\n"
                            "    o = bpy.data.objects.get(n)\n"
                            "    if o is None: continue\n"
                            "    home = o.users_collection[0].name if o.users_collection else ''\n"
                            "    keep = o.copy()\n"
                            "    keep.use_fake_user = True\n"
                            "    bpy.data.objects.remove(o, do_unlink=True)\n"
                            "    keep.name = n\n"
                            "    kept[keep.name] = [home] + list(info.get(n, ('', None)))\n"
                            "if '_rewire_holes' in globals(): _rewire_holes()   # a pool's hole goes with it\n"
                            "RESULT = json.dumps([kept, [n for n in kept if n in scene.objects]])", timeout=20)
    if not response.get("ok"):
        raise RuntimeError(f"I tried to delete it but Blender reported an error: {_error(response)}")
    kept, still_there = json.loads(response.get("output") or "[{}, []]")
    if not kept or still_there:
        raise RuntimeError("I ran the delete, but it's still in the scene — I won't claim that worked.")
    for name in kept:
        _forget(session, name)
    session.blender_focus_group = None
    session.last_undo = {"description": f"deleted it ({len(kept)} parts)",
                         "code": _SCENE + "import json, mathutils\n"
                                 f"kept = json.loads({json.dumps(kept)!r})\n"
                                 "for n, entry in kept.items():\n"
                                 "    home = entry[0] if isinstance(entry, list) else entry\n"
                                 "    o = bpy.data.objects.get(n)\n"
                                 "    if o is None: continue\n"
                                 "    ((bpy.data.collections.get(home) if home else None) or scene.collection)"
                                 ".objects.link(o)\n"
                                 "    o.use_fake_user = False\n"
                                 "for n, entry in kept.items():\n"
                                 "    o = bpy.data.objects.get(n)\n"
                                 "    if o is None or not isinstance(entry, list) or entry[2] is None: continue\n"
                                 "    o.parent = bpy.data.objects.get(entry[1]) if entry[1] else None\n"
                                 "    if o.parent is not None: o.matrix_parent_inverse = mathutils.Matrix.Identity(4)\n"
                                 "for n, entry in kept.items():   # parents first, then their parts, at their places\n"
                                 "    o = bpy.data.objects.get(n)\n"
                                 "    if o is not None and isinstance(entry, list) and entry[2] is not None:\n"
                                 "        bpy.context.view_layer.update()\n"
                                 "        o.matrix_world = mathutils.Matrix(entry[2])\n"
                                 "if '_rewire_holes' in globals(): _rewire_holes()\n"
                                 "RESULT = 'restored'"}
    return f"Done — I deleted it (all {len(kept)} parts)."


def _delete_action(bridge, session, ref_text: str):
    def action():
        group = _focus_group(ref_text, session, bridge)
        if group:
            return _delete_group(bridge, session, group)
        name = _target(bridge, session, ref_text, "delete anything")
        # A hidden copy is kept (fake user) so "undo" can put it back exactly as it was. A group ("the pool") is
        # its empty AND every part: then nothing is deleted here, the whole family goes through _delete_group.
        response = _run(bridge, _SCENE +
                                f"obj = bpy.data.objects.get({name!r})\n"
                                "if obj.children:\n"
                                "    RESULT = 'GROUP|' + '|'.join([obj.name] + [c.name for c in obj.children_recursive])\n"
                                "else:\n"
                                "    home = obj.users_collection[0].name if obj.users_collection else ''\n"
                                "    keep = obj.copy()\n"
                                "    keep.use_fake_user = True\n"
                                "    bpy.data.objects.remove(obj, do_unlink=True)\n"
                                f"    keep.name = {name!r}\n"
                                f"    RESULT = home + '|' + keep.name + '|' + ('0' if {name!r} in scene.objects else '1')")
        if not response.get("ok"):
            raise RuntimeError(f"I tried to delete {name} but Blender reported an error: {_error(response)}")
        if (response.get("output") or "").startswith("GROUP|"):
            return _delete_group(bridge, session, response["output"].split("|")[1:])
        home, kept, gone = ((response.get("output") or "").split("|") + ["", "", ""])[:3]
        if gone != "1":
            raise RuntimeError(f"I ran the delete, but {name} is still in the scene — I won't claim that worked.")
        _forget(session, name)
        collection = f"bpy.data.collections.get({home!r})" if home else "None"
        session.last_undo = {"description": f"deleted {name}",
                             "code": _SCENE +
                                     f"obj = bpy.data.objects.get({kept!r})\n"
                                     f"home = {collection} or scene.collection\n"
                                     "home.objects.link(obj)\n"
                                     "obj.use_fake_user = False\n"
                                     "RESULT = obj.name"}
        return f"Done — I deleted {name}."
    return action


_DUPLICATE_FAMILY = """obj = bpy.data.objects.get({name!r})
family = [obj] + list(obj.children_recursive)
lo = [min((o.matrix_world @ mathutils.Vector(c))[i] for o in family for c in o.bound_box) for i in range(3)]
hi = [max((o.matrix_world @ mathutils.Vector(c))[i] for o in family for c in o.bound_box) for i in range(3)]
copies = {{}}
for o in family:
    c = o.copy()
    if o.data: c.data = o.data.copy()
    (o.users_collection[0] if o.users_collection else scene.collection).objects.link(c)
    copies[o] = c
for o, c in copies.items():
    if o.parent in copies:
        c.parent = copies[o.parent]
        c.matrix_parent_inverse = o.matrix_parent_inverse.copy()   # (assigning a parent resets it)
new = copies[obj]
new.location.x += max(3.0, hi[0] - lo[0] + 1.5)   # clear of the original, however big the thing is
RESULT = new.name if new.name in scene.objects else ''"""


def _duplicate_action(bridge, session, ref_text: str):
    def action():
        name = _target(bridge, session, ref_text, "duplicate anything")
        response = _run(bridge, _SCENE + "import mathutils\n" + _DUPLICATE_FAMILY.format(name=name))
        if not response.get("ok") or not (response.get("output") or "").strip():
            raise RuntimeError(f"I tried to duplicate {name} but it didn't work: {_error(response)}")
        new_name = response["output"].strip()
        kind = next((o["kind"] for o in session.blender_objects if o["name"] == name), "")
        session.remember_blender_object(new_name, kind)
        session.blender_focus = new_name
        session.last_undo = {"description": f"duplicated {name}",
                             "code": f"obj = bpy.data.objects.get({new_name!r})\n"
                                     "if obj: bpy.data.objects.remove(obj, do_unlink=True)\n"
                                     "RESULT = 'removed'"}
        return f"Done — I duplicated {name} ({new_name})."
    return action


def _select_action(bridge, session, ref_text: str):
    def action():
        name = _target(bridge, session, ref_text, "select anything")
        response = _run(bridge, _SCENE +
                                "for o in scene.objects: o.select_set(False, view_layer=layer)\n"
                                f"obj = bpy.data.objects.get({name!r})\n"
                                "obj.select_set(True, view_layer=layer)\n"
                                "layer.objects.active = obj\n"
                                "RESULT = layer.objects.active.name if layer.objects.active else ''")
        if not response.get("ok") or (response.get("output") or "").strip() != name:
            raise RuntimeError(f"I tried to select {name} but it didn't work: {_error(response)}")
        return f"Done — {name} is selected."
    return action


def _focus_action():
    """Bring Blender's window forward — a plain OS window-focus action, no bpy/bridge round trip needed, so it
    works even if Blender happens to be mid-operation or the bridge is momentarily busy."""
    def action():
        import app_launcher
        import winctl
        windows = app_launcher.app_windows("Blender")
        if not windows:
            raise RuntimeError("Blender doesn't seem to be open anymore.")
        winctl.focus(windows[0][0])
        return "Done — switched to Blender."
    return action


def _undo_action(bridge, session):
    """Reverses whatever Jervis's own last deterministic action did, rather than calling Blender's native
    bpy.ops.ed.undo() — that operator's poll() rejects calls made from a script/timer context (confirmed: it fails
    even with temp_override supplying a window/area/region), and more importantly, undoing Jervis's own last change
    specifically is what "undo that" means here — not whatever the user may have done by hand in Blender."""
    def action():
        pending = session.last_undo
        if not pending:
            raise RuntimeError("There's nothing I've done in this session yet for me to undo.")
        response = _run(bridge, pending["code"])
        if not response.get("ok"):
            raise RuntimeError(f"Undo didn't work: {_error(response)}")
        session.last_undo = None
        return f"Done — undid: {pending['description']}."
    return action


def _redo_action():
    def action():
        return "There's nothing to redo — I can only undo my own last action once."
    return action


_SAVE_CODE = """import os, time
target = {target!r}
before = None
if target:
    path = os.path.join(os.path.expanduser('~'), 'Documents', target)
elif bpy.data.filepath:
    path = bpy.data.filepath
else:
    # A scene never saved before gets a name of its own: never write over an earlier session's file.
    base = os.path.join(os.path.expanduser('~'), 'Documents', 'jervis_scene')
    path, k = base + '.blend', 2
    while os.path.exists(path):
        path, k = f'{{base}}_{{k}}.blend', k + 1
os.makedirs(os.path.dirname(path), exist_ok=True)
before = os.path.getmtime(path) if os.path.exists(path) else None
started = time.time()
if path == bpy.data.filepath:
    bpy.ops.wm.save_mainfile()
else:
    bpy.ops.wm.save_as_mainfile(filepath=path)
ok = os.path.exists(path) and os.path.getsize(path) > 0 and (before is None or os.path.getmtime(path) > before
                                                             or os.path.getmtime(path) >= started - 1)
RESULT = ('saved|' if ok else 'unchanged|') + path"""


def _save_action(bridge, name: str = None):
    def action():
        target = None
        if name:
            target = name.strip()
            if not target.lower().endswith(".blend"):
                target += ".blend"
        response = _run(bridge, _SAVE_CODE.format(target=target), timeout=60)
        if not response.get("ok") or "|" not in (response.get("output") or ""):
            raise RuntimeError("I tried to save but Blender reported an error: "
                               f"{(response.get('error') or 'no file path came back')[:200]}")
        status, _, path = response.get("output").partition("|")
        # Verified on disk: the file is there, not empty, and was written just now (an old copy doesn't count).
        if status != "saved":
            raise RuntimeError(f"I ran the save, but {path} wasn't written just now — I won't claim it's saved.")
        return f"Done — saved to {path}."
    return action


# ---------- recognizing what was said ----------

def normalize(text: str) -> str:
    """Speech as heard -> the instruction in it: "Okay, make the cube be girl." -> "make the cube bigger";
    "Blender, you have a cube selected. Make the cube two times bigger." -> "Make the cube two times bigger"."""
    t = " ".join((text or "").split())
    for pattern, fix in _MISHEARD:
        t = pattern.sub(fix, t)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    if len(sentences) > 1:
        instructions = [s for s in sentences if _CONCRETE_VERB.search(s)]
        if instructions:
            t = instructions[-1]
    t = _FILLER.sub("", t).strip(" .!?,")
    for pattern, fix in _RESIZE_VERBS:   # "enlarge it", "shrink the roof": the same as "make it bigger/smaller"
        t = pattern.sub(fix, t)
    return re.sub(r"\s+in blender$", "", t, flags=re.I)


_RESIZE_VERBS = [
    (re.compile(r"^(?:increase|enlarge|grow|expand|scale up|upsize)\s+(?:the size of\s+)?(?P<ref>.+?)"
                r"(?:\s+(?:a bit|a little|some|slightly))?$", re.I), r"make \g<ref> bigger"),
    (re.compile(r"^(?:shrink|decrease|reduce|scale down|downsize)\s+(?:the size of\s+)?(?P<ref>.+?)"
                r"(?:\s+(?:a bit|a little|some|slightly))?$", re.I), r"make \g<ref> smaller"),
]


def _clauses(text: str) -> list:
    return [c.strip(" ,.") for c in _CLAUSE_SPLIT.split(text) if c.strip(" ,.")]


def _match_one(t: str, session, bridge, *, everyday_only: bool = False):
    """[(description, action)] for one clause, or None. `everyday_only` leaves out undo/redo/save/"again", which
    without "Blender" said could mean any app."""
    if _FOCUS.match(t):
        return [("Switching to Blender", _focus_action())]
    m = _MOVE_NEXT_TO.match(t)
    if m and not _NEW_THING.match(m.group("ref")):   # "put a bench next to the tree" builds a bench
        return [(f"Moving {m.group('ref')} next to {m.group('target')}",
                 _move_next_to_action(bridge, session, m.group("ref"), m.group("target")))]
    m = _CREATE.match(t)
    if m:
        shape = m.group("shape")
        return [(f"Creating a {shape}", _create_action(bridge, session, shape))]
    if _ANOTHER.match(t):   # "create another one": the same kind of shape as the last one made
        kinds = [o["kind"] for o in getattr(session, "blender_objects", [])
                 if o.get("kind") in {"cube", "sphere", "cylinder", "cone", "plane", "torus", "monkey"}]
        shape = kinds[-1] if kinds else "cube"
        return [(f"Creating another {shape}", _create_action(bridge, session, shape))]
    m = _COLOR.match(t)
    if m and _is_object_ref(m.group("ref"), session):
        color = m.group("color").lower()
        return [(f"Coloring {m.group('ref')} {color}", _color_action(bridge, session, m.group("ref"), color))]
    m = _RESIZE.match(t)
    if m:
        direction = m.group("direction").lower()
        times = m.group("times")
        times = float(_TIMES_WORDS.get(times.lower(), times)) if times else None
        return [(f"Making {m.group('ref')} {direction}",
                 _resize_action(bridge, session, m.group("ref"), direction, times))]
    for pattern, direction, times in ((_TWICE, "bigger", 2.0), (_HALF, "smaller", 2.0), (_DOUBLE, "bigger", 2.0)):
        m = pattern.match(t)
        if m and _is_object_ref(m.group("ref"), session):
            return [(f"Making {m.group('ref')} {times:g} times {direction}",
                     _resize_action(bridge, session, m.group("ref"), direction, times))]
    m = _SCALE.match(t)
    if m and _is_object_ref(m.group("ref"), session):
        word = m.group("times").lower()
        amount = float(_TIMES_WORDS.get(word, word))
        shrink = word == "half" or (m.group("way") or "").lower() == "down" or amount < 1
        amount = 1 / amount if amount < 1 else amount
        direction = "smaller" if shrink else "bigger"
        return [(f"Scaling {m.group('ref')}", _resize_action(bridge, session, m.group("ref"), direction, amount))]
    m = _MOVE_DIR.match(t)
    if m:
        direction = m.group("direction").lower()
        return [(f"Moving {m.group('ref')} {direction}",
                 _move_direction_action(bridge, session, m.group("ref"), direction))]
    m = _ROTATE.match(t)
    if m and _is_object_ref(m.group("ref"), session):
        degrees = float(m.group("deg") or 90)
        axis = (m.group("axis") or "z").lower()
        return [(f"Rotating {m.group('ref')}", _rotate_action(bridge, session, m.group("ref"), degrees, axis))]
    for pattern, make, label in ((_DELETE, _delete_action, "Deleting"), (_DUPLICATE, _duplicate_action, "Duplicating"),
                                 (_SELECT, _select_action, "Selecting")):
        m = pattern.match(t)
        if m and _is_object_ref(m.group("ref"), session):
            return [(f"{label} {m.group('ref')}", make(bridge, session, m.group("ref")))]
    if everyday_only:
        return None
    if _UNDO.match(t):
        return [("Undoing the last change", _undo_action(bridge, session))]
    if _REDO.match(t):
        return [("Redoing", _redo_action())]
    m = _SAVE.match(t)
    if m:
        return [("Saving the project", _save_action(bridge, m.group("name")))]
    return None


def _match_steps(t: str, session, bridge, everyday_only: bool = False):
    # Clauses first: matched whole, "select the cube and make it red" would read as selecting "the cube and make it red".
    parts = _clauses(t)
    if len(parts) > 1:
        steps = []
        for part in parts:
            found = _match_one(part, session, bridge, everyday_only=everyday_only)
            if found is None:
                break
            steps += found
        else:
            return steps
    return _match_one(t, session, bridge, everyday_only=everyday_only)


# ---------- corrections and follow-ups to the last command: "no, the roof", "the door too", "same for the door" ----------
_INSTEAD = re.compile(r"^(?:no+|nope|nah|not (?:that|it|that one|this one)|wrong(?: one)?)\b[,.!]?\s*"
                      r"(?:(?:i )?(?:meant|mean|said)\s+)?(?:the |that |this |my )?(?P<ref>[a-z][a-z0-9 ]{1,40}?)"
                      r"(?:\s+instead)?\.?$|^i (?:meant|mean)\s+(?:the |that |this )?(?P<ref2>[a-z][a-z0-9 ]{1,40}?)\.?$",
                      re.I)
# ("the shutter is too": how speech recognition often hears "the shutters too")
_ALSO = re.compile(r"^(?:and |also |now )?(?:the |that |this )?(?P<ref>[a-z][a-z0-9 ]{1,40}?)(?:\s+is|'s)?\s+"
                   r"(?:too|as well|also)\.?$|"
                   r"^(?:(?:and |also |now )?(?:do |the )?same (?:to|for|with) |(?:and |also )?do (?:that|it) (?:to|for) )"
                   r"(?:the |that |this )?(?P<ref2>[a-z][a-z0-9 ]{1,40}?)\.?$", re.I)
_REF_PATTERNS = ("_RESIZE", "_TWICE", "_HALF", "_DOUBLE", "_SCALE", "_COLOR", "_ROTATE", "_MOVE_DIR", "_DELETE",
                 "_DUPLICATE")


def correction(text: str):
    """("instead", ref) for "no, the roof" (the last command was meant for something else), ("also", ref) for "the
    door too" / "same for the door" (do it there as well), or None."""
    t = normalize(text)
    for kind, pattern in (("instead", _INSTEAD), ("also", _ALSO)):
        m = pattern.match(t)
        if m:
            ref = (m.group("ref") or m.group("ref2") or "").strip()
            if ref and ref not in ("it", "that", "this", "one", "same") and len(ref.split()) <= 4:
                return kind, ref
    return None


def retarget(previous: str, ref: str):
    """The previous command said about `ref` instead: ("make it bigger", "roof") -> "make the roof bigger"."""
    for name in _REF_PATTERNS:
        m = globals()[name].match(previous or "")
        if m and m.group("ref"):
            start, end = m.span("ref")
            return previous[:start] + f"the {ref}" + previous[end:]
    return None


def is_command(text: str) -> bool:
    """Whether `text` is made of the everyday object commands here (create / resize / color / move / rotate /
    delete / duplicate / select / switch to Blender), or a correction/follow-up of the last one. Nothing is run."""
    return _match_steps(normalize(text), None, None, everyday_only=True) is not None or correction(text) is not None


def steps_for(text: str, session, bridge):
    """[(description, action)] for `text` if it's made of the common, deterministic Blender commands this module
    knows — each action executes, re-verifies against real Blender state, and returns a clean result string (or
    raises, which ScriptedTask reports as a failure, never a false success). None if nothing recognized here;
    the caller falls back to BlenderComputerTask's free-form AI loop."""
    t = normalize(text)
    if _AGAIN.match(t):
        previous = getattr(session, "last_deterministic_text", None)
        return steps_for(previous, session, bridge) if previous else None
    fix = correction(t)
    if fix:
        previous = getattr(session, "last_deterministic_text", None)
        changed = retarget(previous, fix[1]) if previous else None
        steps = _match_steps(changed, session, bridge) if changed else None
        if not steps:
            return None   # nothing to correct: the slower paths (or a question) take it from here
        if fix[0] == "instead" and session.last_undo:   # "no, the roof": take back what was done to the wrong thing
            undo = _undo_action(bridge, session)

            def put_back():
                undo()   # raises (and stops here) if it couldn't be undone
                return "Okay, I put that back —"
            steps = [("Undoing that", put_back)] + steps
        session.last_deterministic_text = changed
        return steps
    steps = _match_steps(t, session, bridge)
    if steps is not None:
        session.last_deterministic_text = t
    return steps


# ---------- never invent a technical interpretation of vague/incomplete language ----------
_COPULA_COMPLAINT = re.compile(r"^(?:it'?s|that'?s|this is|there'?s|something(?:'?s| is)|things? (?:is|are))\b", re.I)
_VAGUE_TRAILING = re.compile(r"\b(?:a level|totally|somewhat|kind of|sort of)\s*\.?$", re.I)
_CONCRETE_VERB = re.compile(
    r"\b(create|add|make|build|move|put|place|rotate|scale|resize|delete|remove|save|undo|redo|duplicate|copy|"
    r"render|export|set|change|turn|switch|open|close|select|colou?r|paint|texture|material|assign|group|rename|"
    r"align|snap|parent|join|separate|extrude|bevel|subdivide|apply|link|flip|mirror|merge|go (?:to|back)|bring|"
    r"focus|double|spin|insert|plant|grow|scatter|spawn|erect|improve|refine)\b", re.I)
# Naming Blender itself removes the main source of ambiguity even with a generic verb ("go back to Blender"),
# unlike a bare pronoun ("take it to a level") which still leaves the actual target unclear.
_NAMES_BLENDER = re.compile(r"\bblender\b", re.I)


def looks_concrete(text: str) -> bool:
    """Whether `text` reads like an actual instruction Blender could carry out, rather than a vague or incomplete
    remark ("it's sticky", "take it to a level", "make the cube totally"). When this is False, the caller should
    ask for clarification instead of ever handing it to an AI that might invent a technical-sounding guess."""
    t = (text or "").strip()
    if not t:
        return False
    if _COPULA_COMPLAINT.match(t) and not _CONCRETE_VERB.search(t):
        return False
    if _VAGUE_TRAILING.search(t) and len(t.split()) <= 6:
        return False
    return bool(_CONCRETE_VERB.search(t) or _NAMES_BLENDER.search(t))


def clarification_for(text: str) -> str:
    return ("I'm not sure what you'd like me to do there. Try something like: create a cube, make it two times "
            "bigger, color it red, rotate it 45 degrees, or move it left.")
