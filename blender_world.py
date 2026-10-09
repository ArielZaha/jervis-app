"""The living environment of a Jervis scene, inside Blender: time of day that changes everything it should (sun,
sky, exposure, windows, signs, street lamps), fog / mist / haze as ONE adjustable volume, weather (rain that wets,
storms, snow that settles), water and wind that can be made calmer or stronger, animation that can be paused or
removed, materials changed by meaning ("the windows", "the roof"), cameras matched to a photo and moved safely —
and the semantic memory each object carries (what it IS, not just its name).

Edits MODIFY what exists — a second "add fog" thickens the fog rather than stacking another volume; "make it
sunset" retunes the one sun. The environment's state lives on the scene (scene["jervis_env"]), so it survives
saving and is read back by Jervis (env_state()).

Runs inside Blender after blender_kit / blender_assets / blender_motion / blender_places / blender_props."""
import json
import math

try:
    import bpy
    import mathutils
    from mathutils import Vector
except ImportError:
    bpy = mathutils = Vector = None

WORLD_VERSION = 1

# ---------- the environment's state ----------


def _env() -> dict:
    try:
        return json.loads(_scene().get("jervis_env", "{}") or "{}")   # noqa: F821
    except (ValueError, TypeError):
        return {}


def _env_set(**changes) -> dict:
    env = _env()
    for k, v in changes.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    _scene()["jervis_env"] = json.dumps(env)   # noqa: F821
    return env


def env_state() -> str:
    """The environment as JSON: what Jervis set (time, weather, wind, fog, water...) and what Blender shows now
    (the sun's strength, the fog's density, rain present, lights on)."""
    env = _env()
    s = _scene()   # noqa: F821
    sun = next((o for o in bpy.data.objects if o.type == "LIGHT" and o.data.type == "SUN" and o.users_collection), None)
    fog_obj = bpy.data.objects.get("Jervis Fog")
    lit = [o.name for o in bpy.data.objects if o.type == "LIGHT" and o.users_collection and o.data.type != "SUN"
           and o.data.energy > 0.01]
    live = {"sun_energy": round(sun.data.energy, 3) if sun else None,
            "sun_elevation": round(90 - math.degrees((sun.matrix_world.to_3x3() @ Vector((0, 0, -1))).angle(
                Vector((0, 0, -1)))), 1) if sun else None,
            "fog_density": round(_fog_density(fog_obj), 5) if fog_obj else 0.0,
            "rain": bpy.data.objects.get("Rain") is not None, "snow": bpy.data.objects.get("Snow") is not None,
            "lights_on": len(lit), "exposure": round(s.view_settings.exposure, 2),
            "camera": s.camera.name if s.camera else None,
            "cameras": [o.name for o in bpy.data.objects if o.type == "CAMERA" and o.users_collection]}
    return json.dumps({"set": env, "live": live})


# ---------- what things are ----------

def tag_semantic(obj, kind, role=None, ref=None, source="user", **extra):
    """Mark what a thing IS (its kind in Jervis's ontology, its role in the scene — 'main building', 'the pool' —
    which element of the reference picture it rebuilds) so it can be found by meaning later, whatever it's named."""
    o = get(obj)   # noqa: F821
    info = {"kind": kind, "role": role, "ref": ref, "source": source}
    info.update({k: v for k, v in extra.items() if v is not None})
    o["jervis_semantic"] = json.dumps(info)
    if "jervis_sid" not in o:
        n = int(_scene().get("jervis_sid_next", 1))   # noqa: F821
        o["jervis_sid"] = f"s{n}"
        _scene()["jervis_sid_next"] = n + 1   # noqa: F821
    return o


def semantic_registry() -> str:
    """Every thing Jervis knows the meaning of, as JSON: name, stable id, kind, role, where it is and how big, its
    lights and its animation — the scene's semantic memory, read fresh from Blender."""
    out = []
    for o in bpy.data.objects:
        if not o.users_collection or "jervis_semantic" not in o:
            continue
        try:
            info = json.loads(o["jervis_semantic"])
        except (ValueError, TypeError):
            continue
        try:
            (lo, hi) = bounds(o)   # noqa: F821
        except Exception:
            lo = hi = tuple(o.matrix_world.translation)
        lights_ = [c.name for c in o.children_recursive if c.type == "LIGHT"]
        out.append({"name": o.name, "sid": o.get("jervis_sid"), **info,
                    "center": [round((lo[i] + hi[i]) / 2, 2) for i in range(3)],
                    "size": [round(hi[i] - lo[i], 2) for i in range(3)], "lights": lights_,
                    "motion": o.get("jervis_motion"), "glow": o.get("jervis_glow")})
    return json.dumps(out)


def _roots_of(kind_words=None, tag=None):
    """Asset roots whose meaning or name fits."""
    found = []
    for o in bpy.data.objects:
        if not o.users_collection or o.parent is not None:
            continue
        sem = {}
        if "jervis_semantic" in o:
            try:
                sem = json.loads(o["jervis_semantic"])
            except (ValueError, TypeError):
                sem = {}
        asset = {}
        if "jervis_asset" in o:
            try:
                asset = json.loads(o["jervis_asset"])
            except (ValueError, TypeError):
                asset = {}
        kind = str(sem.get("kind") or asset.get("type") or "")
        if kind_words and not any(w in kind or w in o.name.lower() for w in kind_words):
            continue
        if tag and tag not in str(o.get("jervis_tags", "")) and tag not in sem.get("tags", []):
            continue
        found.append(o)
    return found


def _parts_named(root, words, exclude=()):
    fam = [root] + list(root.children_recursive)
    return [p for p in fam if p.type == "MESH" and any(w in p.name.lower() for w in words)
            and not any(x in p.name.lower() for x in exclude)]


# ---------- light that comes from inside: windows, signs, lamps ----------

def _own_material(obj, base=None, prefix="Jervis"):
    """The object's own copy of its material (so changing it never changes anything else that shared it)."""
    mat = obj.active_material
    if mat is None:
        mat = bpy.data.materials.new(f"{prefix} {obj.name}")
        mat.use_nodes = True
        obj.data.materials.append(mat)
        return mat
    if mat.users > 1 or not mat.name.startswith(prefix):
        mat = mat.copy()
        mat.name = f"{prefix} {obj.name}"
        for i, slot in enumerate(obj.material_slots):
            if slot.material is not None and slot.material.name == (base or slot.material.name):
                slot.material = mat
                break
        else:
            obj.material_slots[0].material = mat
    mat.use_nodes = True
    return mat


def _bsdf(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.use_nodes else None


def _emission_input(bsdf):
    for key in ("Emission Color", "Emission"):
        if key in bsdf.inputs:
            return bsdf.inputs[key]
    return None


def _kelvin_rgb(k):
    return tuple(cinema.kelvin(float(k)))   # noqa: F821


def _pane_values(obj, seed=0):
    """A random number per pane (each separate piece of the glass mesh), stored on the mesh as 'jervis_pane' so the
    shader can light some windows and not others, each its own brightness — whole panes, never half of one."""
    import bmesh as _bm
    me = obj.data
    if "jervis_pane" in me.attributes:
        return
    bm = _bm.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    island = [-1] * len(bm.faces)
    n = 0
    for f in bm.faces:
        if island[f.index] >= 0:
            continue
        stack = [f]
        island[f.index] = n
        while stack:
            cur = stack.pop()
            for e in cur.edges:
                for g in e.link_faces:
                    if island[g.index] < 0:
                        island[g.index] = n
                        stack.append(g)
        n += 1
    bm.free()
    r = rng(seed + len(me.polygons))   # noqa: F821
    values = [r.random() for _ in range(n)]
    attr = me.attributes.new("jervis_pane", "FLOAT", "CORNER")
    data = [0.0] * len(me.loops)
    for poly in me.polygons:
        v = values[island[poly.index]]
        for li in poly.loop_indices:
            data[li] = v
    attr.data.foreach_set("value", data)


def window_glow(building, on=True, level=0.7, share=0.5, warmth=2800, vary=True, interior=True):
    """A building's windows lit from inside (or dark again, on=False): its glass glows with warm light, but not
    every window alike — `share` of them lit (0..1), each at its own brightness (a cell pattern the size of a
    window decides which), `level` how bright overall. The rooms behind get a little real light too (interior
    point lights, low). Calling it again changes the glow; it never stacks a second one."""
    t = _thing(building)   # noqa: F821
    root = bpy.data.objects.get(t["name"])
    panes = _parts_named(root, ("window glass", "glass"), exclude=("balcony", "door", "clear", "display"))
    if not panes:
        panes = [p for p in _parts_named(root, ("window",)) if "frame" not in p.name.lower()]
    if not panes:
        raise ValueError(f"{t['name']!r} has no window glass to light.")
    rgb = _kelvin_rgb(warmth)
    # (at 1.8 a lit window went white under AgX at night exposure; warm glass must stay warm)
    strength = max(0.0, float(level)) * 1.2 if on else 0.0
    for pane in panes:
        _pane_values(pane)
        mat = _own_material(pane, prefix="Jervis lit glass")
        nt = mat.node_tree
        bsdf = _bsdf(mat)
        emit = _emission_input(bsdf)
        if emit is None:
            continue
        mask = nt.nodes.get("Jervis glow mask")
        if mask is None and vary:
            attr = nt.nodes.new("ShaderNodeAttribute")
            attr.attribute_name = "jervis_pane"
            lit = nt.nodes.new("ShaderNodeMath")
            lit.operation = "LESS_THAN"
            lit.name = "Jervis glow share"
            nt.links.new(attr.outputs["Fac"], lit.inputs[0])
            # each lit pane its own brightness: a second number from the same one (its fraction times 7)
            spread = nt.nodes.new("ShaderNodeMath")
            spread.operation = "MULTIPLY"
            spread.inputs[1].default_value = 7.13
            nt.links.new(attr.outputs["Fac"], spread.inputs[0])
            frac = nt.nodes.new("ShaderNodeMath")
            frac.operation = "FRACT"
            nt.links.new(spread.outputs[0], frac.inputs[0])
            shade = nt.nodes.new("ShaderNodeMapRange")
            nt.links.new(frac.outputs[0], shade.inputs["Value"])
            shade.inputs["To Min"].default_value, shade.inputs["To Max"].default_value = 0.45, 1.0
            mask = nt.nodes.new("ShaderNodeMath")
            mask.operation = "MULTIPLY"
            mask.name = "Jervis glow mask"
            nt.links.new(lit.outputs[0], mask.inputs[0])
            nt.links.new(shade.outputs["Result"], mask.inputs[1])
            power = nt.nodes.new("ShaderNodeMath")
            power.operation = "MULTIPLY"
            power.name = "Jervis glow power"
            nt.links.new(mask.outputs[0], power.inputs[0])
            nt.links.new(power.outputs[0], bsdf.inputs["Emission Strength"])
        share_node = nt.nodes.get("Jervis glow share")
        if share_node is not None:
            share_node.inputs[1].default_value = max(0.0, min(1.0, float(share)))
        power = nt.nodes.get("Jervis glow power")
        if power is not None:
            power.inputs[1].default_value = strength
        else:
            bsdf.inputs["Emission Strength"].default_value = strength
        emit.default_value = (*rgb, 1.0)
    if interior:
        inside = _parts_named(root, ("interior",))
        for part in inside:
            mat = _own_material(part, prefix="Jervis lit interior")
            b = _bsdf(mat)
            if b is not None and _emission_input(b) is not None:
                _emission_input(b).default_value = (*rgb, 1.0)
                if on:   # lamplit rooms read warm and dim from outside, not as a pale wall lit white by the lamps
                    b.inputs["Base Color"].default_value = (rgb[0] * 0.35, rgb[1] * 0.3, rgb[2] * 0.25, 1.0)
                # a shop's interior is its display: it glows brighter than a home's rooms (brighter still went
                # white under AgX at night exposure — warm light reads warm only short of that)
                shop = "storefront" in str(root.get("jervis_asset", ""))
                b.inputs["Emission Strength"].default_value = (0.4 if shop else 0.18) * float(level) if on else 0.0
        own = [o for o in root.children_recursive if o.type == "LIGHT" and o.get("jervis_light_for") == t["name"]]
        if on and not own and t["category"] == "building":
            # (a shop's small deep room, lit at 40 W a lamp, burnt its walls to white through the glass)
            shop = "storefront" in str(root.get("jervis_asset", ""))
            own = interior_lights(t["name"], on=True, energy=(14.0 if shop else 40.0) * float(level),   # noqa: F821
                                  kelvin=min(warmth, 2600) if shop else warmth)
        for lt in own:
            lt["jervis_energy"] = 40.0 * float(level)
            lt.data.energy = lt["jervis_energy"] if on else 0.0
            lt.data.color = rgb
    root["jervis_glow"] = json.dumps({"on": bool(on), "level": level, "share": share, "warmth": warmth})
    return [p.name for p in panes]


def sign_glow(target=None, on=True, strength=1.4):
    """Signs and lanterns glowing — or not: every '... Sign' and '... Lanterns' part of `target` (or of all)."""
    roots = [bpy.data.objects.get(_thing(target)["name"])] if target else _roots_of()   # noqa: F821
    done = []
    for root in roots:
        for part in _parts_named(root, ("sign", "lantern")):
            mat = _own_material(part, prefix="Jervis sign")
            b = _bsdf(mat)
            if b is None or _emission_input(b) is None:
                continue
            base = tuple(b.inputs["Base Color"].default_value)
            if "lantern" in part.name.lower():   # paper lit by a flame or a warm bulb behind it
                warm = _kelvin_rgb(2300)
                colour = tuple(base[i] * 0.4 + warm[i] * 0.6 for i in range(3)) + (1.0,)
                level = float(strength) * 0.35
            else:   # a sign lit from the window light around it, not a lightbox: a pale sign blew out to white
                colour, level = base, float(strength) * 0.03
            _emission_input(b).default_value = colour
            b.inputs["Emission Strength"].default_value = level if on else 0.0
            done.append(part.name)
    return done


def lamps(on=True, which="night", level=1.0):
    """Lamps on or off: street lamps and lanterns (which='night'), lamps indoors ('indoor'), or 'all' — their bulbs
    to their own brightness, their glass and paper glowing."""
    done = []
    for lt in [o for o in bpy.data.objects if o.type == "LIGHT" and o.users_collection and o.get("jervis_light_for")]:
        root = bpy.data.objects.get(lt["jervis_light_for"])
        tags = str(root.get("jervis_tags", "")) if root is not None else ""
        indoor = root is not None and "floor_lamp" in str(root.get("jervis_asset", ""))
        if which == "night" and "light_source_night" not in tags:
            continue
        if which == "indoor" and not indoor:
            continue
        full = float(lt.get("jervis_energy") or 100.0) * float(level)
        lt.data.energy = full if on else 0.0
        glow = bpy.data.materials.get(lt.get("jervis_glow_material", ""))
        if glow is not None and _bsdf(glow) is not None and _emission_input(_bsdf(glow)) is not None:
            b = _bsdf(glow)
            _emission_input(b).default_value = tuple(b.inputs["Base Color"].default_value)
            b.inputs["Emission Strength"].default_value = (3.0 * float(level)) if on else 0.0
        done.append(lt.name)
    return done


# ---------- time of day ----------

_SKY_LOOK = {"sunrise": "sunrise", "dawn": "sunrise", "morning": "morning", "day": "day", "midday": "day",
             "noon": "day", "afternoon": "afternoon", "golden hour": "golden hour", "sunset": "sunset",
             "dusk": "dusk", "evening": "dusk", "twilight": "dusk", "night": "night", "midnight": "night",
             "overcast": "overcast"}
_EXPOSURE = {"night": 0.6, "dusk": 0.35, "sunset": 0.1, "sunrise": 0.15, "golden hour": 0.0}
# How much of the physical sky shows (vs the flat colour of the time of day), and how strong it is
_SKY_TEXTURE = {"sunrise": (0.35, 0.22), "morning": (0.0, 0.3), "day": (0.0, 0.3), "afternoon": (0.0, 0.3),
                "golden hour": (0.2, 0.28), "sunset": (0.35, 0.25), "dusk": (0.85, 0.6), "night": (1.0, 1.0),
                "overcast": (0.6, 0.45)}


def _physical_sky(look, sun):
    """A physically based sky (Nishita) lit by the very sun of the scene, blended with the time of day's own
    colour (night is mostly its colour, day mostly the real sky): gradients, a bright horizon, a sunset glow."""
    w, bg = _world()   # noqa: F821
    nt = w.node_tree
    tex = nt.nodes.get("Jervis sky texture")
    mix = nt.nodes.get("Jervis sky mix")
    if tex is None:
        tex = nt.nodes.new("ShaderNodeTexSky")
        tex.name = "Jervis sky texture"
        try:
            tex.sky_type = "NISHITA"
        except TypeError:
            pass
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.name = "Jervis sky mix"
        nt.links.new(tex.outputs["Color"], mix.inputs["A"])
    if not bg.inputs["Color"].is_linked:
        nt.links.new(mix.outputs["Result"], bg.inputs["Color"])
    fac, strength = _SKY_TEXTURE.get(look, (0.0, 0.3))
    fwd = sun.matrix_world.to_3x3() @ Vector((0, 0, -1))
    try:
        tex.sun_elevation = max(math.radians(-5), math.asin(max(-1.0, min(1.0, -fwd.z))))
        tex.sun_rotation = math.atan2(-fwd.x, -fwd.y) % math.tau
        tex.sun_disc = look not in ("night", "dusk")
        tex.air_density = 1.0
        tex.dust_density = 1.5 if look in ("sunset", "sunrise", "golden hour") else 0.8
    except AttributeError:
        pass
    k = cinema.SKY.get(look, cinema.SKY["day"])   # noqa: F821
    mix.inputs["B"].default_value = (*k["sky"], 1.0)
    mix.inputs["Factor"].default_value = fac
    bg.inputs["Strength"].default_value = strength * (k["sky_strength"] if fac > 0.5 else 1.0)


def sky_clouds(cover=0.4, remove=False):
    """Clouds across the sky (a layer in the sky itself, drifting nowhere): `cover` 0..1 of the sky clouded, lit
    by the time of day — white by day, gold and pink at sunset, grey at night. Called again it changes the cover;
    remove=True clears the sky. They're tinted again whenever the time of day changes."""
    w, bg = _world()   # noqa: F821
    nt = w.node_tree
    mixn = nt.nodes.get("Jervis clouds mix")
    if remove:
        if mixn is not None:
            src = mixn.inputs["A"].links[0].from_socket if mixn.inputs["A"].is_linked else None
            for n in [n for n in nt.nodes if n.name.startswith("Jervis clouds")]:
                nt.nodes.remove(n)
            if src is not None:
                nt.links.new(src, bg.inputs["Color"])
        _env_set(clouds=None)
        return "cleared"
    cover = max(0.0, min(1.0, float(cover)))
    if mixn is None:
        if not bg.inputs["Color"].is_linked:   # a flat sky: its colour, as a node the clouds can sit over
            flat = nt.nodes.new("ShaderNodeRGB")
            flat.name = "Jervis flat sky"   # (stays when the clouds go)
            flat.outputs[0].default_value = tuple(bg.inputs["Color"].default_value)
            nt.links.new(flat.outputs[0], bg.inputs["Color"])
        src = bg.inputs["Color"].links[0].from_socket
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.name = "Jervis clouds coord"
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        sep.name = "Jervis clouds sep"
        nt.links.new(coord.outputs["Generated"], sep.inputs["Vector"])
        # the view direction projected onto a cloud deck overhead: (x/z, y/z) — clouds shrink toward the horizon
        zc = nt.nodes.new("ShaderNodeMath")
        zc.name, zc.operation = "Jervis clouds z", "MAXIMUM"
        zc.inputs[1].default_value = 0.035
        nt.links.new(sep.outputs["Z"], zc.inputs[0])
        parts = []
        for axis in ("X", "Y"):
            d = nt.nodes.new("ShaderNodeMath")
            d.name, d.operation = f"Jervis clouds {axis}", "DIVIDE"
            nt.links.new(sep.outputs[axis], d.inputs[0])
            nt.links.new(zc.outputs[0], d.inputs[1])
            parts.append(d)
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        comb.name = "Jervis clouds deck"
        nt.links.new(parts[0].outputs[0], comb.inputs["X"])
        nt.links.new(parts[1].outputs[0], comb.inputs["Y"])
        drift = nt.nodes.new("ShaderNodeMapping")
        drift.name = "Jervis clouds drift"
        nt.links.new(comb.outputs["Vector"], drift.inputs["Vector"])
        try:   # slowly across the sky, with the timeline (a driver: no keys to clash with a shot's)
            fc = drift.inputs["Location"].driver_add("default_value", 0)
            fc.driver.type = "SCRIPTED"
            fc.driver.expression = "frame * 0.0025"
        except (TypeError, AttributeError):
            pass
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.name = "Jervis clouds noise"
        # (finer than this read as streaks of cirrus; these are heaps of cumulus)
        noise.inputs["Scale"].default_value = 0.55
        noise.inputs["Detail"].default_value = 5.0
        noise.inputs["Roughness"].default_value = 0.62
        nt.links.new(drift.outputs["Vector"], noise.inputs["Vector"])
        shape = nt.nodes.new("ShaderNodeMapRange")
        shape.name = "Jervis clouds shape"
        shape.inputs["To Min"].default_value, shape.inputs["To Max"].default_value = 0.0, 1.0
        nt.links.new(noise.outputs["Fac"], shape.inputs["Value"])
        # thinning out right at the horizon, and none below it
        fade = nt.nodes.new("ShaderNodeMapRange")
        fade.name = "Jervis clouds horizon"
        # (seen edge-on, a cloud deck piles up into a grey band at the horizon: thin it out low down, as the haze
        # of distance does, so the sky near the horizon stays sky)
        fade.inputs["From Min"].default_value, fade.inputs["From Max"].default_value = 0.02, 0.3
        nt.links.new(sep.outputs["Z"], fade.inputs["Value"])
        mask = nt.nodes.new("ShaderNodeMath")
        mask.name, mask.operation = "Jervis clouds mask", "MULTIPLY"
        nt.links.new(shape.outputs["Result"], mask.inputs[0])
        nt.links.new(fade.outputs["Result"], mask.inputs[1])
        mixn = nt.nodes.new("ShaderNodeMix")
        mixn.data_type = "RGBA"
        mixn.name = "Jervis clouds mix"
        nt.links.new(src, mixn.inputs["A"])
        nt.links.new(mask.outputs[0], mixn.inputs["Factor"])
        # a cloud is the sky's own light made white and brighter (a fixed colour came out darker than a physical
        # sky's blue), then tinted by the hour
        white = nt.nodes.new("ShaderNodeHueSaturation")
        white.name = "Jervis clouds white"
        white.inputs["Saturation"].default_value = 0.12
        nt.links.new(src, white.inputs["Color"])
        tint = nt.nodes.new("ShaderNodeMix")
        tint.data_type, tint.blend_type = "RGBA", "MULTIPLY"
        tint.name = "Jervis clouds tint"
        tint.inputs["Factor"].default_value = 1.0
        nt.links.new(white.outputs["Color"], tint.inputs["A"])
        nt.links.new(tint.outputs["Result"], mixn.inputs["B"])
        nt.links.new(mixn.outputs["Result"], bg.inputs["Color"])
    shape = nt.nodes["Jervis clouds shape"]
    edge = 0.64 - 0.3 * cover   # noise above this is cloud: more of the sky as cover grows
    shape.inputs["From Min"].default_value, shape.inputs["From Max"].default_value = edge, edge + 0.07
    _env_set(clouds=round(cover, 3))
    _clouds_tint()
    return "ok"


def _clouds_tint():
    """The clouds' colour for the time of day: sunlit white by day, warm at the ends of it, a dim grey at night —
    always brighter than the sky around them."""
    w, bg = _world()   # noqa: F821
    nt = w.node_tree
    tint, white = nt.nodes.get("Jervis clouds tint"), nt.nodes.get("Jervis clouds white")
    if tint is None or white is None:
        return
    look = _env().get("time") or "day"
    k = cinema.SKY.get(look, cinema.SKY["day"])   # noqa: F821
    sun = _kelvin_rgb(k["kelvin"])
    warm = 0.7 if look in ("sunset", "sunrise", "golden hour") else 0.0 if look in ("night", "dusk") else 0.12
    peak = max(sun)
    tint.inputs["B"].default_value = tuple(1.0 - warm + warm * sun[i] / peak for i in range(3)) + (1.0,)
    white.inputs["Value"].default_value = {"night": 1.5, "dusk": 1.4}.get(look, 1.9)


def sky_color(color, mix=0.85, strength=None):
    """The sky's colour made `color` (blended over the physical sky by `mix`) — to match a photo's sky."""
    w, bg = _world()   # noqa: F821
    mixn = w.node_tree.nodes.get("Jervis sky mix")
    if mixn is None:
        bg.inputs["Color"].default_value = (*rgb_of(color), 1.0)   # noqa: F821
    else:
        mixn.inputs["B"].default_value = (*rgb_of(color), 1.0)   # noqa: F821
        mixn.inputs["Factor"].default_value = max(0.0, min(1.0, float(mix)))
    if strength is not None:
        bg.inputs["Strength"].default_value = max(0.0, float(strength))
    _env_set(sky_color=str(color))
    return "ok"


def _flat_sky():
    """Back to the flat sky colour (a sky that changes over the shot is keyed on it)."""
    w, bg = _world()   # noqa: F821
    for link in list(w.node_tree.links):
        if link.to_socket == bg.inputs["Color"]:
            w.node_tree.links.remove(link)


def time_of_day(look="day", sun_side=None, windows=None, lamps_on=None, pool_lights_on=None, start=None, end=None):
    """Make it `look` (sunrise | morning | day | afternoon | golden hour | sunset | dusk | night) — the whole
    environment, not just the sky: the sun's height, direction and colour, the sky's colour and brightness, the
    exposure, and what's lit. After dark, homes glow from some rooms, shops from all of theirs and their signs, and
    street lamps and lanterns come on (windows/lamps_on override); by day they're off. sun_side: 'left' | 'right' |
    'behind camera' | 'in front of camera' — where the sun should be as the active camera sees it (to match a
    photo's shadows)."""
    look = _SKY_LOOK.get(str(look).lower().strip(), "day")
    sun = sky(look, start=start, end=end)   # noqa: F821
    if start is not None or end is not None:
        _flat_sky()
    if sun_side and _scene().camera is not None and start is None:   # noqa: F821
        cam = _scene().camera   # noqa: F821
        fwd = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
        cam_az = math.degrees(math.atan2(fwd.y, fwd.x))
        offset = {"left": 90, "right": -90, "behind camera": 180, "in front of camera": 0}.get(str(sun_side).lower())
        if offset is not None:
            # the sun comes FROM that side: it sits there, so its light travels the other way
            az = cam_az + offset
            k = cinema.SKY.get(look, cinema.SKY["day"])   # noqa: F821
            sun.rotation_euler = _sun_rotation(max(-8.0, k["elevation"]), az)   # noqa: F821
    if start is None and end is None:
        _update()   # noqa: F821  (the sun's new direction, for the sky)
        _physical_sky(look, sun)
    dark = look in ("dusk", "night")
    s = _scene()   # noqa: F821
    _interior_daylight(look)
    try:
        s.view_settings.exposure = _EXPOSURE.get(look, 0.0)
    except Exception:
        pass
    lit_windows = dark if windows is None else bool(windows)
    changed = []
    for root in _roots_of():
        kind = str(json.loads(root.get("jervis_asset", "{}") or "{}").get("type", "")) if "jervis_asset" in root \
            else ""
        sem = json.loads(root.get("jervis_semantic", "{}") or "{}") if "jervis_semantic" in root else {}
        kind = sem.get("kind") or kind
        if kind in ("storefront", "shop"):
            glow = dict(level=1.0, share=0.95)
        elif kind in ("house", "villa"):
            glow = dict(level=0.75, share=0.55)
        elif kind in ("building",):
            glow = dict(level=0.6, share=0.35)
        else:
            continue
        try:
            window_glow(root.name, on=lit_windows, **glow)
            if kind in ("storefront", "shop"):
                sign_glow(root.name, on=lit_windows)
            changed.append(root.name)
        except (ValueError, KeyError):
            pass
    lamps(on=dark if lamps_on is None else bool(lamps_on), which="night")
    if pool_lights_on is not None:
        for root in _roots_of(("pool",)):
            if not _lights_of(root.name) and pool_lights_on:   # noqa: F821
                pool_lights(root.name, on=True)   # noqa: F821
            for lt in _lights_of(root.name):   # noqa: F821
                lt.data.energy = float(lt.get("jervis_energy") or 120.0) if pool_lights_on else 0.0
            glow = bpy.data.materials.get("Jervis pool light")
            if glow is not None and _bsdf(glow) is not None:
                _bsdf(glow).inputs["Emission Strength"].default_value = 6.0 if pool_lights_on else 0.0
    _env_set(time=look)
    _fog_ambient()
    _clouds_tint()
    return {"time": look, "lit": changed if lit_windows else [], "sun": sun.name}


def _interior_daylight(look):
    """A room is lit the way real rooms are: daylight comes in through its windows (an area light in each opening,
    as strong as the time of day makes it), the sky's light doesn't leak through its walls (EEVEE would wash the
    room out), and its ceiling light and lamps are on after dark."""
    rooms = [o for o in bpy.data.objects if o.users_collection and o.get("jervis_role") == "room"]
    if not rooms:
        return
    day = {"night": 0.0, "dusk": 0.12, "sunset": 0.35, "sunrise": 0.35, "golden hour": 0.5, "morning": 0.8}.get(look, 1.0)
    w, bg = _world()   # noqa: F821
    bg.inputs["Strength"].default_value = bg.inputs["Strength"].default_value * 0.25
    for room in rooms:
        info = json.loads(room.get("jervis_asset", "{}") or "{}").get("params", {})
        W, D, H = float(info.get("width", 6)), float(info.get("depth", 5)), float(info.get("height", 2.8))
        c = room.matrix_world.translation
        k = 0
        for wdef in info.get("windows") or [{"wall": "back"}]:
            wall = str((wdef or {}).get("wall") or "back")
            k += 1
            nm = f"{room.name} Daylight {k}"
            if wall == "back":
                at, aim = (c.x, c.y + D / 2 + 0.3, c.z + H * 0.55), (c.x, c.y, c.z + 0.6)
            else:
                side = -1 if wall == "left" else 1
                at, aim = (c.x + side * (W / 2 + 0.3), c.y, c.z + H * 0.55), (c.x, c.y, c.z + 0.6)
            lt = light(nm, "area", at=at, energy=900 * day, color=6200 if look not in ("sunset", "golden hour") else 3600,   # noqa: F821
                       size=2.0, aim=aim)
            lt["jervis_light_for"] = room.name
        fixture = bpy.data.materials.get("Jervis ceiling light")
        dark = look in ("dusk", "night")
        if fixture is not None and _bsdf(fixture) is not None:
            _bsdf(fixture).inputs["Emission Strength"].default_value = 4.0 if dark else 0.0
        bulb = bpy.data.objects.get(f"{room.name} Ceiling Bulb")
        if bulb is None:
            bulb = light(f"{room.name} Ceiling Bulb", "point", at=(c.x, c.y, c.z + H - 0.3), energy=180, color=2900,   # noqa: F821
                         size=0.3)
            bulb["jervis_light_for"] = room.name
        bulb.data.energy = 180.0 if dark else 0.0
    lamps(on=look in ("dusk", "night"), which="indoor")


# ---------- fog, mist, haze ----------

_FOG_KINDS = {   # density (per metre), height (m, where it thins out; 0 = everywhere), colour, anisotropy
    "fog": (0.03, 0.0, (0.82, 0.84, 0.86), 0.2),      # ~100 m visibility
    "mist": (0.012, 6.0, (0.9, 0.92, 0.94), 0.3),     # ~250 m: things across a bay soften, not vanish
    "ground fog": (0.08, 2.0, (0.88, 0.9, 0.92), 0.2),
    "haze": (0.006, 0.0, (0.78, 0.82, 0.9), 0.5),
    "smoke": (0.04, 0.0, (0.5, 0.48, 0.45), 0.1),
    "dust": (0.012, 8.0, (0.75, 0.65, 0.5), 0.4),
}


def _fog_ambient():
    """Fog lit by the sky around it: EEVEE's volumes take little of the world's light, so fog only darkened what was
    behind it (mist at sunset was a brown band). Its glow is the light it would scatter from the sky — the sky's
    colour and brightness at this time of day, tinted by the fog's own colour, in proportion to how thick it is."""
    obj = bpy.data.objects.get("Jervis Fog")
    if obj is None or obj.active_material is None:
        return
    nt = obj.active_material.node_tree
    vol, dens = nt.nodes.get("Jervis fog volume"), nt.nodes.get("Jervis fog density")
    if vol is None or dens is None or "Emission Strength" not in vol.inputs:
        return
    k = cinema.SKY.get(_env().get("time") or "day", cinema.SKY["day"])   # noqa: F821
    tint = tuple(vol.inputs["Color"].default_value)[:3]
    vol.inputs["Emission Color"].default_value = tuple(k["sky"][i] * tint[i] for i in range(3)) + (1.0,)
    glow = nt.nodes.get("Jervis fog glow")
    if glow is None:
        glow = nt.nodes.new("ShaderNodeMath")
        glow.operation = "MULTIPLY"
        glow.name = "Jervis fog glow"
        nt.links.new(dens.outputs[0], glow.inputs[0])
        nt.links.new(glow.outputs[0], vol.inputs["Emission Strength"])
    # (tuned by eye: ~0.5 by day, a little more at a dim sunset; much more washed the near palms out)
    glow.inputs[1].default_value = 0.5 + 0.3 * (1.0 - k["sky_strength"])


def _fog_density(obj):
    try:
        node = obj.active_material.node_tree.nodes.get("Jervis fog density")
        return float(node.inputs[1].default_value)
    except Exception:
        return 0.0


def fog(kind=None, density=None, height=None, color=None, factor=None, remove=False):
    """Fog in the air, as ONE volume over the whole scene (made once, then changed): kind 'fog' | 'mist' |
    'ground fog' (thick near the ground, thinning by `height` metres) | 'haze' (light, far: distant things fade) |
    'smoke' | 'dust'. factor=1.6 thickens what's there, 0.5 thins it; remove=True clears the air."""
    obj = bpy.data.objects.get("Jervis Fog")
    if remove:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        _env_set(fog=None)
        return "cleared"
    env = _env().get("fog") or {}
    kind = str(kind or env.get("kind") or "fog").lower()
    base = _FOG_KINDS.get(kind, _FOG_KINDS["fog"])
    if density is None:
        density = env.get("density") if (env and kind == env.get("kind")) else base[0]
    if factor:
        density = float(density) * float(factor)
    density = max(0.0, min(0.5, float(density)))
    height = base[1] if height is None and (not env or kind != env.get("kind")) else \
        (height if height is not None else env.get("height", base[1]))
    rgb = rgb_of(color) if color is not None else tuple(env.get("color") or base[2])   # noqa: F821
    # the volume covers everything there is (and the view out to its edge)
    ts = scene_things()   # noqa: F821
    if ts:
        lo = [min(t["lo"][i] for t in ts) for i in range(3)]
        hi = [max(t["hi"][i] for t in ts) for i in range(3)]
    else:
        lo, hi = [-50, -50, 0], [50, 50, 10]
    reach = max(120.0, max(hi[0] - lo[0], hi[1] - lo[1]) * 1.5)
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    top = (float(height) * 2.5 if height else max(40.0, hi[2] + 20.0))
    if obj is None:
        mesh = bpy.data.meshes.new("Jervis Fog")
        obj = bpy.data.objects.new("Jervis Fog", mesh)
        _scene().collection.objects.link(obj)   # noqa: F821
        import bmesh as _bm
        bm = _bm.new()
        _bm.ops.create_cube(bm, size=1.0)
        bm.to_mesh(mesh)
        bm.free()
        obj["jervis_role"] = "sky"
        obj.hide_select = True
        obj.display_type = "BOUNDS"
        mat = bpy.data.materials.new("Jervis Fog")
        mat.use_nodes = True
        nt = mat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        vol = nt.nodes.new("ShaderNodeVolumePrincipled")
        vol.name = "Jervis fog volume"
        coords = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        # density falls off with height: d * clamp(1 - z_world / height)  (or d everywhere when height == 0)
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
        fall = nt.nodes.new("ShaderNodeMapRange")
        fall.name = "Jervis fog falloff"
        nt.links.new(sep.outputs["Z"], fall.inputs["Value"])
        fall.inputs["To Min"].default_value, fall.inputs["To Max"].default_value = 1.0, 0.0
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 0.05
        nt.links.new(geo.outputs["Position"], noise.inputs["Vector"])
        patchy = nt.nodes.new("ShaderNodeMapRange")
        nt.links.new(noise.outputs["Fac"], patchy.inputs["Value"])
        patchy.inputs["To Min"].default_value, patchy.inputs["To Max"].default_value = 0.6, 1.3
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        nt.links.new(fall.outputs["Result"], mul.inputs[0])
        nt.links.new(patchy.outputs["Result"], mul.inputs[1])
        dens = nt.nodes.new("ShaderNodeMath")
        dens.operation = "MULTIPLY"
        dens.name = "Jervis fog density"
        nt.links.new(mul.outputs[0], dens.inputs[0])
        nt.links.new(dens.outputs[0], vol.inputs["Density"])
        nt.links.new(vol.outputs[0], out.inputs["Volume"])
        obj.data.materials.append(mat)
    obj.location = (cx, cy, top / 2 - 1.0)
    obj.scale = (reach * 2, reach * 2, top)
    nt = obj.active_material.node_tree
    nt.nodes["Jervis fog density"].inputs[1].default_value = density
    fall = nt.nodes["Jervis fog falloff"]
    fall.inputs["From Min"].default_value = 0.0
    fall.inputs["From Max"].default_value = float(height) if height else 10000.0
    vol = nt.nodes["Jervis fog volume"]
    vol.inputs["Color"].default_value = (*rgb, 1.0)
    if "Anisotropy" in vol.inputs:
        vol.inputs["Anisotropy"].default_value = base[3]
    try:
        s = _scene()   # noqa: F821
        s.eevee.volumetric_end = max(s.eevee.volumetric_end, reach * 1.2)
        s.eevee.volumetric_tile_size = "8"
    except Exception:
        pass
    _env_set(fog={"kind": kind, "density": round(density, 5), "height": height, "color": list(rgb)})
    _fog_ambient()
    return obj.name


# ---------- weather ----------

def _wet_targets():
    """The surfaces rain wets: ground, roads, paving, decks, roofs, steps — what faces the sky and isn't water."""
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.users_collection or o.get("jervis_role") in ("sky", "library"):
            continue
        n = o.name.lower()
        if o.get("jervis_kind") == "terrain" or any(w in n for w in ("asphalt", "sidewalk", "road", "paving", "deck",
                                                                       "terrace", "floor", "roof", "slab", "steps",
                                                                       "path", "sand", "ground", "kerb", "coping")):
            if "water" not in n and "interior" not in n and "glass" not in n:
                out.append(o)
    return out


def wet(amount=1.0):
    """Rain-wet surfaces: darker, glossy, with standing water in the low spots (amount 0 = dry again). Each material
    remembers how it was, so drying puts it back exactly."""
    amount = max(0.0, min(1.0, float(amount)))
    done = []
    seen = set()
    for o in _wet_targets():
        for slot in o.material_slots:
            mat = slot.material
            if mat is None or mat.name in seen or not mat.use_nodes:
                continue
            seen.add(mat.name)
            b = _bsdf(mat)
            if b is None:
                continue
            if "jervis_dry_rough" not in mat:
                mat["jervis_dry_rough"] = float(b.inputs["Roughness"].default_value)
            dry = float(mat["jervis_dry_rough"])
            nt = mat.node_tree
            puddles = nt.nodes.get("Jervis puddles")
            if puddles is None and not b.inputs["Roughness"].is_linked:
                noise = nt.nodes.new("ShaderNodeTexNoise")
                noise.inputs["Scale"].default_value = 0.35
                coords = nt.nodes.new("ShaderNodeTexCoord")
                nt.links.new(coords.outputs["Object"], noise.inputs["Vector"])
                puddles = nt.nodes.new("ShaderNodeMapRange")
                puddles.name = "Jervis puddles"
                nt.links.new(noise.outputs["Fac"], puddles.inputs["Value"])
                puddles.inputs["From Min"].default_value, puddles.inputs["From Max"].default_value = 0.45, 0.62
                nt.links.new(puddles.outputs["Result"], b.inputs["Roughness"])
            if puddles is not None:
                wet_rough = dry * (1 - 0.8 * amount)
                puddles.inputs["To Min"].default_value = 0.02 if amount > 0 else dry
                puddles.inputs["To Max"].default_value = wet_rough if amount > 0 else dry
            else:
                b.inputs["Roughness"].default_value = dry * (1 - 0.75 * amount)
            if "jervis_dry_dark" not in mat:
                mat["jervis_dry_dark"] = 1.0
            mat["jervis_wet"] = amount
            mat.diffuse_color = tuple(c * (1 - 0.35 * amount) if i < 3 else c for i, c in enumerate(mat.diffuse_color))
            done.append(mat.name)
    _env_set(wet=round(amount, 2) if amount > 0 else None)
    return done


def weather(kind="clear", intensity=1.0):
    """The weather, all of it together: 'clear' (rain/snow gone, surfaces dry), 'cloudy' / 'overcast' (cloud,
    softer light), 'rain' (falling rain, wet surfaces), 'storm' (heavy rain, dark cloud, strong wind, rough water),
    'snow' (falling snow, white settling on the ground and roofs). Replaces the weather there was."""
    kind = str(kind or "clear").lower()
    intensity = max(0.1, min(3.0, float(intensity or 1.0)))
    for nm in ("Rain", "Snow"):
        o = bpy.data.objects.get(nm)
        if o is not None and not ((kind in ("rain", "storm") and nm == "Rain") or (kind == "snow" and nm == "Snow")):
            for c in [o] + list(o.children_recursive):
                bpy.data.objects.remove(c, do_unlink=True)
    made = []
    if kind in ("rain", "storm"):
        if bpy.data.objects.get("Rain") is None:
            made.append(rain("Rain", heavy=kind == "storm" or intensity > 1.3).name)   # noqa: F821
        wet(min(1.0, 0.6 + 0.4 * intensity))
    else:
        wet(0.0)
    if kind == "snow":
        if bpy.data.objects.get("Snow") is None:
            made.append(snow("Snow", heavy=intensity > 1.3).name)   # noqa: F821
        snow_cover(min(1.0, 0.5 * intensity))
    else:
        snow_cover(0.0)
    if kind in ("storm",):
        sun = sky("dramatic")   # noqa: F821
        _update()   # noqa: F821
        _physical_sky("overcast", sun)
        try:
            wind(2.0)   # noqa: F821
        except Exception:
            pass
        try:
            water_motion(strength=2.0)
        except ValueError:
            pass
    elif kind in ("cloudy", "overcast", "rain"):
        env = _env()
        if env.get("time") in (None, "day", "afternoon", "morning"):
            sun = sky("overcast")   # noqa: F821
            _update()   # noqa: F821
            _physical_sky("overcast", sun)
    _env_set(weather=kind, weather_intensity=intensity)
    return {"weather": kind, "made": made}


def snow_cover(amount=0.6):
    """Snow settling on what faces up (ground, roofs, leaves): white blended in by how level each surface is."""
    amount = max(0.0, min(1.0, float(amount)))
    seen = set()
    for o in _wet_targets() + [o for o in bpy.data.objects if o.type == "MESH" and any(
            w in o.name.lower() for w in ("leaves", "fronds", "needles", "hedge"))]:
        for slot in o.material_slots:
            mat = slot.material
            if mat is None or mat.name in seen or not mat.use_nodes:
                continue
            seen.add(mat.name)
            b = _bsdf(mat)
            if b is None:
                continue
            nt = mat.node_tree
            mix = nt.nodes.get("Jervis snow")
            if mix is None:
                if amount <= 0:
                    continue
                mix = nt.nodes.new("ShaderNodeMix")
                mix.data_type = "RGBA"
                mix.name = "Jervis snow"
                src = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].is_linked else None
                if src is not None:
                    nt.links.new(src, mix.inputs["A"])
                else:
                    mix.inputs["A"].default_value = b.inputs["Base Color"].default_value
                mix.inputs["B"].default_value = (0.93, 0.95, 0.98, 1)
                geo = nt.nodes.new("ShaderNodeNewGeometry")
                sep = nt.nodes.new("ShaderNodeSeparateXYZ")
                nt.links.new(geo.outputs["Normal"], sep.inputs["Vector"])
                up = nt.nodes.new("ShaderNodeMapRange")
                up.name = "Jervis snow up"
                nt.links.new(sep.outputs["Z"], up.inputs["Value"])
                up.inputs["From Min"].default_value, up.inputs["From Max"].default_value = 0.55, 0.85
                nt.links.new(up.outputs["Result"], mix.inputs["Factor"])
                nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
            up = nt.nodes.get("Jervis snow up")
            if up is not None:
                up.inputs["To Max"].default_value = amount
    _env_set(snow_cover=round(amount, 2) if amount > 0 else None)
    return len(seen)


# ---------- water and wind, made calmer or stronger ----------

def water_motion(target=None, strength=None, speed=None, strength_factor=None, speed_factor=None, mode=None):
    """Change how water moves (it must already move — natural motion gives it that): `strength` / `speed` set it,
    the *_factor ones scale what it is now ("calmer" 0.5, "stronger waves" 1.8, "faster" 1.6). target: a thing, or
    None for every water surface. Each water remembers its settings, so changes add up sensibly."""
    roots = []
    if target:
        roots = [bpy.data.objects.get(_thing(target)["name"])]   # noqa: F821
    else:
        roots = [o for o in bpy.data.objects if o.users_collection and o.parent is None and any(
            p.get("jervis_kind") == "water" for p in [o] + list(o.children_recursive))]
    done = []
    for root in roots:
        if root is None:
            continue
        info = json.loads(root.get("jervis_water", "{}") or "{}")
        kind = mode or info.get("kind") or {"pool": "ripples", "pond": "ripples", "fountain": "ripples",
                                            "river": "flow", "waterfall": "falls"}.get(
            json.loads(root.get("jervis_asset", "{}") or "{}").get("type", ""), "waves")
        st = float(info.get("strength", 1.0))
        sp = float(info.get("speed", 1.0))
        if strength is not None:
            st = float(strength)
        if strength_factor:
            st *= float(strength_factor)
        if speed is not None:
            sp = float(speed)
        if speed_factor:
            sp *= float(speed_factor)
        st, sp = max(0.05, min(4.0, st)), max(0.1, min(5.0, sp))
        animate_water(root.name, kind, strength=st, speed=sp)   # noqa: F821
        root["jervis_water"] = json.dumps({"kind": kind, "strength": st, "speed": sp})
        done.append(root.name)
    if not done:
        raise ValueError("There's no water here to change.")
    return done


def wind_strength(strength=None, factor=None):
    """Wind through the vegetation, set or scaled from what it is now ("make the trees move more": 1.6)."""
    env = _env()
    st = float(env.get("wind_strength", 1.0) if strength is None else strength)
    if factor:
        st *= float(factor)
    st = max(0.0, min(4.0, st))
    if st <= 0.01:
        pause_motion(kinds=("sway", "flutter"))
        _env_set(wind_strength=0.0)
        return []
    resume_motion(kinds=("sway", "flutter"))
    done = wind(st)   # noqa: F821
    _env_set(wind_strength=round(st, 2))
    return done


# ---------- pausing, resuming, removing motion ----------

def _motion_owners(target=None):
    objs = [o for o in bpy.data.objects if o.users_collection]
    if target:
        root = bpy.data.objects.get(_thing(target)["name"])   # noqa: F821
        objs = [root] + list(root.children_recursive) if root is not None else []
    owners = []
    for o in objs:
        owners.append(o)
        if o.data is not None and hasattr(o.data, "animation_data"):
            owners.append(o.data)
        for slot in getattr(o, "material_slots", []):
            if slot.material is not None and slot.material.node_tree is not None:
                owners.append(slot.material.node_tree)
    return owners


def pause_motion(target=None, kinds=None):
    """Hold things still without losing their animation: procedural wobble muted, drivers off, keyed motion's
    action muted (resume_motion() brings it all back). kinds: only motion of these kinds ('sway', 'flutter'...)."""
    n = 0
    for owner in _motion_owners(target):
        if kinds and getattr(owner, "get", None) and owner.get("jervis_motion") not in kinds and not any(
                k in getattr(owner, "name", "").lower() for k in ("leaves", "fronds", "needles")):
            if not (hasattr(owner, "parent") and owner.parent is not None and owner.parent.get("jervis_motion") in kinds):
                continue
        ad = getattr(owner, "animation_data", None)
        if ad is None:
            continue
        for fc in (list(ad.action.fcurves) if ad.action is not None and hasattr(ad.action, "fcurves") else []):
            for m in fc.modifiers:
                m.mute = True
            fc.mute = True
        for d in ad.drivers:
            d.mute = True
        for m in getattr(owner, "modifiers", []):
            if m.type in ("WAVE",):
                m.show_viewport = m.show_render = False
        n += 1
    _env_set(paused=True if not kinds else None)
    return n


def resume_motion(target=None, kinds=None):
    n = 0
    for owner in _motion_owners(target):
        ad = getattr(owner, "animation_data", None)
        if ad is None:
            continue
        for fc in (list(ad.action.fcurves) if ad.action is not None and hasattr(ad.action, "fcurves") else []):
            for m in fc.modifiers:
                m.mute = False
            fc.mute = False
        for d in ad.drivers:
            d.mute = False
        for m in getattr(owner, "modifiers", []):
            if m.type in ("WAVE",):
                m.show_viewport = m.show_render = True
        n += 1
    _env_set(paused=None)
    return n


def remove_animation(target=None, keep_camera=False):
    """Take animation away for good (undo can still bring it back): keys, drivers and motion modifiers — of
    `target`, or everything (but the camera's moves, with keep_camera=True). Geometry is never touched."""
    n = 0
    for owner in _motion_owners(target):
        if keep_camera and getattr(owner, "type", None) == "CAMERA":
            continue
        ad = getattr(owner, "animation_data", None)
        if ad is not None and (ad.action is not None or len(ad.drivers)):
            for d in list(ad.drivers):
                try:
                    ad.drivers.remove(d)
                except Exception:
                    pass
            ad.action = None
            n += 1
        if hasattr(owner, "get") and owner.get("jervis_motion"):
            del owner["jervis_motion"]
    for p in [o for o in bpy.data.objects if o.users_collection and o.name.endswith("Wave Driver")]:
        p.animation_data_clear()
    return n


# ---------- materials, by meaning ----------

_PART_WORDS = {
    "walls": ("walls", "slabs", "render", "facade", "siding"), "roof": ("roof", "eaves", "parapet"),
    "windows": ("window glass", "glass"), "window frames": ("windows",), "door": ("door",), "trim": ("trim",),
    "grass": ("surface", "lawn", "grass"), "ground": ("surface", "sand", "ground"), "water": ("water", "sea", "surface"),
    "leaves": ("leaves", "fronds", "needles"), "trunk": ("trunk",), "wood": ("wood", "cladding", "deck", "boards"),
    "floor": ("floor",), "deck": ("deck", "coping", "terrace"), "pavement": ("sidewalk", "paving", "asphalt", "road"),
    "sign": ("sign",), "awning": ("awning",), "cushions": ("cushion",), "fabric": ("cushion", "frame", "canopy"),
}


def _target_parts(target=None, part=None):
    roots = [bpy.data.objects.get(_thing(target)["name"])] if target else [   # noqa: F821
        o for o in bpy.data.objects if o.users_collection and o.parent is None and o.type in ("MESH", "EMPTY")]
    words = _PART_WORDS.get(str(part or "").lower(), (str(part).lower(),) if part else None)
    found = []
    for root in roots:
        if root is None:
            continue
        fam = [root] + list(root.children_recursive)
        for p in fam:
            if p.type != "MESH" or p.get("jervis_role") in ("sky", "library"):
                continue
            n = p.name.lower()
            if words and not any(w in n for w in words):
                continue
            if part == "windows" and ("balcony" in n or "frame" in n):
                continue
            if part == "grass" and p.get("jervis_kind") != "terrain" and "lawn" not in n and "grass" not in n:
                continue
            found.append(p)
    return found


def material_edit(target=None, part=None, color=None, darker=None, lighter=None, roughness=None, reflective=None,
                  greener=None, warmer=None, clearer=None):
    """Change how something looks by what it is: material_edit('Villa', 'walls', color='white'),
    ('House', 'roof', darker=0.3), (None, 'windows', reflective=True), (None, 'grass', greener=0.4), (pool,
    'water', clearer=True). Only those parts change — each gets its own copy of its material first."""
    parts = _target_parts(target, part)
    fallback = {"roof": "slabs", "walls": "cladding", "windows": "glass", "floor": "terrace"}.get(str(part or ""))
    if not parts and fallback:   # a modern villa's roof is its top slab; a glass shop's "walls" its cladding...
        parts = _target_parts(target, fallback)
    if not parts:
        raise ValueError(f"I can't find {part or 'parts'} on {target or 'anything'} to change.")
    changed = []
    for p in parts:
        mat = _own_material(p, prefix="Jervis edit")
        b = _bsdf(mat)
        if b is None:
            continue
        nt = mat.node_tree
        ramp = next((n for n in nt.nodes if n.type == "VALTORGB"), None)

        def recolour(fn):
            if ramp is not None and b.inputs["Base Color"].is_linked:
                for el in ramp.color_ramp.elements:
                    el.color = (*fn(tuple(el.color)[:3]), 1.0)
            else:
                b.inputs["Base Color"].default_value = (*fn(tuple(b.inputs["Base Color"].default_value)[:3]), 1.0)
            mat.diffuse_color = (*fn(tuple(mat.diffuse_color)[:3]), 1.0)
        if color is not None:
            rgb = rgb_of(color)   # noqa: F821
            if ramp is not None and b.inputs["Base Color"].is_linked:
                for i, el in enumerate(ramp.color_ramp.elements):
                    k = 0.88 if i == 0 else 1.0
                    el.color = (rgb[0] * k, rgb[1] * k, rgb[2] * k, 1.0)
            else:
                b.inputs["Base Color"].default_value = (*rgb, 1.0)
            mat.diffuse_color = (*rgb, 1.0)
        if darker:
            recolour(lambda c: tuple(v * (1 - 0.6 * float(darker)) for v in c))
        if lighter:
            recolour(lambda c: tuple(min(1.0, v + (1 - v) * 0.6 * float(lighter)) for v in c))
        if greener:
            g = float(greener)
            recolour(lambda c: (c[0] * (1 - 0.35 * g), min(1.0, c[1] * (1 + 0.6 * g)), c[2] * (1 - 0.3 * g)))
        if warmer:
            w = float(warmer)
            recolour(lambda c: (min(1.0, c[0] * (1 + 0.25 * w)), c[1], c[2] * (1 - 0.25 * w)))
        if roughness is not None and not b.inputs["Roughness"].is_linked:
            b.inputs["Roughness"].default_value = max(0.0, min(1.0, float(roughness)))
        if reflective is not None:
            if not b.inputs["Roughness"].is_linked:
                b.inputs["Roughness"].default_value = 0.02 if reflective else 0.4
            if "Specular IOR Level" in b.inputs:
                b.inputs["Specular IOR Level"].default_value = 0.9 if reflective else 0.5
            if reflective:
                recolour(lambda c: tuple(v * 0.6 for v in c))
        if clearer:
            for key in ("Transmission Weight", "Transmission"):
                if key in b.inputs:
                    b.inputs[key].default_value = 0.9
            recolour(lambda c: (c[0] * 0.8, min(1.0, c[1] * 1.05), min(1.0, c[2] * 1.1)))
        changed.append(p.name)
    return changed


# ---------- cameras: matching a photo, and moving safely ----------

def _cam(name=None):
    if name:
        o = bpy.data.objects.get(name)
        if o is None or o.type != "CAMERA":
            raise KeyError(f"There's no camera called {name!r}. Cameras: "
                           f"{', '.join(c.name for c in bpy.data.objects if c.type == 'CAMERA') or '(none)'}")
        return o
    s = _scene()   # noqa: F821
    if s.camera is None:
        raise KeyError("There's no camera in the scene yet.")
    return s.camera


def _obstacles(exclude=()):
    ts = scene_things()   # noqa: F821
    return ts, cinema.obstacles_3d(ts, exclude=set(exclude))   # noqa: F821


def _safe_place(cam_pos, aim, exclude=(), see_past=()):
    """The nearest place to cam_pos that is clear: out of every building and object, above the ground, with a view
    of `aim` (craned up only as far as needed) — past everything but `see_past`, what it is looking at."""
    ts, boxes = _obstacles(exclude)
    cam = list(cam_pos)
    cam[2] = max(cam[2], ground_height(cam[0], cam[1], default=0.0) + 0.35)   # noqa: F821
    cam = list(cinema.clear_position(cam, aim, boxes, step=0.4, tries=80, see_past=see_past))   # noqa: F821
    return tuple(cam)


def _view_hit(pos, aim):
    """The first thing the view from `pos` toward `aim` runs into (name, distance to its surface) — what the camera
    is looking at — or None when the view is open."""
    d = aim - pos
    if d.length < 1e-6:
        return None
    best = None
    for name, lo, hi in _obstacles()[1]:
        t0, t1 = 0.0, 1e9
        for i in range(3):
            if abs(d[i]) < 1e-9:
                if pos[i] < lo[i] or pos[i] > hi[i]:
                    t0 = 1e9
                continue
            a, b = (lo[i] - pos[i]) / d[i], (hi[i] - pos[i]) / d[i]
            t0, t1 = max(t0, min(a, b)), min(t1, max(a, b))
        if t0 <= t1 and 0.0 < t0 < 1e8 and (best is None or t0 < best[1]):
            best = (name, t0)
    return (best[0], best[1] * d.length) if best else None


def camera_match(name="Camera", height=1.6, pitch=0.0, yaw=0.0, lens=35.0, at=(0.0, 0.0), look_distance=20.0,
                 active=True):
    """A camera set up like the one a photo was taken with: standing at `at` (x, y), `height` m up, turned `yaw`
    degrees from +y (positive: to the left), pitched `pitch` degrees down (negative: up), with a `lens` mm lens on
    a 36 mm sensor. Aimed through its target (so orbits and push-ins work on it afterwards)."""
    cam, target = _rig(name, float(lens))   # noqa: F821
    y = math.radians(float(yaw))
    p = math.radians(float(pitch))
    fwd = Vector((-math.sin(y) * math.cos(p), math.cos(y) * math.cos(p), -math.sin(p)))
    pos = Vector((float(at[0]), float(at[1]), float(height)))
    cam.location = pos
    target.location = pos + fwd * float(look_distance)
    cam.data.sensor_fit = "HORIZONTAL"
    cam["jervis_shot"] = "matched"
    cam["jervis_match"] = json.dumps({"height": height, "pitch": pitch, "yaw": yaw, "lens": lens, "at": list(at)})
    if active:
        _scene().camera = cam   # noqa: F821
    _update()   # noqa: F821
    return cam.name


def camera_on_box(name="Camera", lo=(0, 0, 0), hi=(1, 1, 1), shot="wide", elevation=None, lens=None, active=True):
    """A camera framing a stretch of a place (lo, hi corners) rather than a thing: a beach's sand at its water, an
    island's land without its sea — placed like camera(), clear of everything, aimed by its target."""
    lo, hi = [float(v) for v in lo], [float(v) for v in hi]
    focus = {"name": "__focus", "lo": lo, "hi": hi, "outer": (lo[0], lo[1], hi[0], hi[1]), "core": (lo[0], lo[1], hi[0], hi[1]),
             "category": "object", "front": (0.0, -1.0), "names": [], "parts": [], "side_parts": [], "pieces": []}
    ts = scene_things()   # noqa: F821
    plan = cinema.plan_shot(ts, [focus], shot, lens=lens, elevation=elevation)   # noqa: F821
    cam, target = _rig(name, plan["lens"])   # noqa: F821
    cam.location = plan["location"]
    target.location = plan["aim"]
    cam["jervis_shot"] = shot
    if active:
        _scene().camera = cam   # noqa: F821
    _update()   # noqa: F821
    return cam


_WET_WORDS = ("water", "sea", "ocean", "surf", "foam", "waves", "lake", "pond")


def place_box(things):
    """(lo, hi) of a place's LAND — the vertices of its parts that aren't water and stand above the water (an
    island's seabed and sea run far out under the surface) — at a size a camera can frame: a huge place is looked
    at round a 24 m stretch of it, where its land meets its water when the water is on one side (a beach)."""
    names = [things] if isinstance(things, str) else list(things)
    meshes, wet = [], []
    for n in names:
        root = bpy.data.objects.get(n)
        for o in ([root] + list(root.children_recursive)) if root is not None else []:
            if o.type == "MESH":
                (wet if any(w in o.name.lower() for w in _WET_WORDS) else meshes).append(o)
    level = max([o.matrix_world.translation.z for o in wet] + [-1e9]) if wet else -1e9
    pts = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
    above = [p for p in pts if p.z > level + 0.05] or pts
    if not above:
        raise ValueError(f"{names} has nothing to look at.")
    lo = [min(p[i] for p in above) for i in range(3)]
    hi = [max(p[i] for p in above) for i in range(3)]
    if max(hi[0] - lo[0], hi[1] - lo[1]) > 90:
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        if wet:
            (wlo, whi) = bounds(wet[0])   # noqa: F821
            one_side = wlo[1] > lo[1] + 0.25 * (hi[1] - lo[1])   # water only beyond the land (a shore)
            if one_side:
                cy = wlo[1] - 14.0
        lo, hi = [cx - 12.0, cy - 12.0, lo[2]], [cx + 12.0, cy + 12.0, min(hi[2], lo[2] + 6.0)]
    return lo, hi


def _model_radius(coll, cache={}):
    """Half the width of a planting model (a tree's crown, a shrub, a stone), from its own geometry."""
    key = coll.as_pointer()
    if key not in cache:
        pts = [o.matrix_world @ Vector(c) for o in coll.all_objects if o.type == "MESH" for c in o.bound_box]
        cache[key] = (max(max(p.x for p in pts) - min(p.x for p in pts),
                                max(p.y for p in pts) - min(p.y for p in pts)) / 2,
                            max(p.z for p in pts)) if pts else (0.5, 1.0)
    return cache[key]


def clear_view(camera=None, subjects=None):
    """Nothing planted stands between the camera and what it shows: every tree, shrub or stone of the
    surroundings (forest() stands, jervis_role 'backdrop') in the way of the view of `subjects` (or of what the
    camera aims at) is taken out. Returns how many."""
    cam = _cam(camera)
    origin = Vector(cam.matrix_world.translation)
    targets = []
    for n in ([subjects] if isinstance(subjects, str) else list(subjects or [])):
        try:
            t = _thing(n)   # noqa: F821
        except Exception:
            continue
        lo, hi = t["lo"], t["hi"]
        targets += [Vector((x, y, z)) for x in (lo[0], hi[0], (lo[0] + hi[0]) / 2) for y in ((lo[1] + hi[1]) / 2,)
                    for z in (lo[2] + 0.3, (lo[2] + hi[2]) / 2, hi[2])]
    if not targets:
        targets = [_subject_point(cam)]
    removed = 0
    for root in [o for o in bpy.data.objects if o.get("jervis_role") == "backdrop"]:
        for inst in list(root.children):
            coll = inst.instance_collection if inst.instance_type == "COLLECTION" else None
            if coll is None:
                continue
            radius, height = _model_radius(coll)
            s_ = max(inst.scale)
            p = Vector(inst.matrix_world.translation)
            if (p.xy - origin.xy).length < radius * s_ + 1.0 and origin.z < p.z + height * s_ + 0.5:
                bpy.data.objects.remove(inst, do_unlink=True)   # the camera stood in its crown
                removed += 1
                continue
            for t in targets:
                seg = t - origin
                k = max(0.0, min(1.0, (p - origin).xy.dot(seg.xy) / max(1e-6, seg.xy.length_squared)))
                near = origin + seg * k
                if k < 0.02 or k > 0.98:
                    continue
                if (near.xy - p.xy).length < radius * s_ + 0.4 and near.z < p.z + height * s_:
                    bpy.data.objects.remove(inst, do_unlink=True)
                    removed += 1
                    break
    return removed


def camera_horizon(camera=None) -> float:
    """How much of the picture (0..1, from the top) lies above the horizon: the share there is for sky."""
    cam = _cam(camera)
    s = _scene()   # noqa: F821
    fwd = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
    pitch = math.asin(max(-1.0, min(1.0, -fwd.z)))   # positive: looking down
    sx, sy = s.render.resolution_x, s.render.resolution_y
    hfov = 2 * math.atan(cam.data.sensor_width / 2 / cam.data.lens)
    vfov = 2 * math.atan(math.tan(hfov / 2) * sy / max(1, sx))
    return max(0.0, min(1.0, 0.5 - math.tan(pitch) / math.tan(vfov / 2) * 0.5))


def camera_on_place(name="Camera", things=(), shot="wide", elevation=None, lens=None, active=True):
    """A camera on a place asked for itself (an island, a beach): its land, not its sea to the horizon."""
    lo, hi = place_box(things)
    return camera_on_box(name, lo, hi, shot, elevation=elevation, lens=lens, active=active)


def _subject_point(cam):
    """What a camera looks at: its target, else straight ahead 15 m."""
    target = bpy.data.objects.get(f"{cam.name} Target")
    if target is not None:
        return Vector(target.matrix_world.translation)
    return cam.matrix_world.translation + (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))) * 15.0


def camera_edit(name=None, closer=None, farther=None, side=None, height=None, raise_by=None, low=False, high=False,
                drone=False, lens=None, lens_factor=None, pan=None, tilt=None, subject=None, keep_keys=False):
    """Move a camera the way a person asks, keeping what it looks at in view and itself out of every wall:
    closer=0.6 (distance x0.6) / farther=1.5; side='left'|'right'|'behind'|'front' (around its subject);
    height=metres / raise_by; low=True (a low angle looking up); high=True / drone=True (from well above);
    lens=mm or lens_factor (0.7 wider, 1.5 tighter); pan / tilt in degrees (turn without moving); subject: a thing
    to look at instead. The camera's animation is replaced by the new still position unless keep_keys."""
    cam = _cam(name)
    s = _scene()   # noqa: F821
    if cam.animation_data and cam.animation_data.action and not keep_keys:
        cam.animation_data.action = None
    target = bpy.data.objects.get(f"{cam.name} Target")
    if target is None:
        _rig(cam.name, cam.data.lens)   # noqa: F821
        target = bpy.data.objects.get(f"{cam.name} Target")
        target.location = _subject_point(cam)
    if target.animation_data and target.animation_data.action and not keep_keys:
        target.animation_data.action = None
    exclude = []
    if subject:
        t = _thing(subject)   # noqa: F821
        c = spatial.center(t["outer"])   # noqa: F821
        target.location = (c[0], c[1], (t["lo"][2] + t["hi"][2]) * 0.45)
        exclude = [t["name"]]
        cam["jervis_subject"] = json.dumps([t["name"]])
    aim = Vector(target.location)
    pos = Vector(cam.location)
    off = pos - aim
    flat = Vector((off.x, off.y, 0.0))
    dist = max(1.0, off.length)
    # what it looks at: the first thing along its view (its target is often a point inside a building)
    hit = None if subject else _view_hit(pos, aim)
    see_past = [t["name"]] if subject else ([hit[0]] if hit else [])
    if side:
        az_now = math.atan2(off.y, off.x)
        if subject or side in ("behind", "front", "back"):
            # around the subject, relative to ITS front where it has one
            try:
                t = _thing(subject) if subject else _nearest_thing(aim)   # noqa: F821
                fx, fy = t["front"]
                front_az = math.atan2(fy, fx)
            except Exception:
                front_az = az_now
        else:
            front_az = az_now
        # "from the left": round to the viewer's left (seen from above, clockwise); the camera faces the subject
        turn = {"left": -math.radians(70), "right": math.radians(70), "behind": math.pi, "back": math.pi,
                "front": 0.0}.get(str(side).lower(), 0.0)
        base = front_az if str(side).lower() in ("behind", "back", "front") else az_now
        r = max(4.0, flat.length)
        # the first of: the full turn, a shallower one, nearer — whose view of the subject is open at eye height
        # (a neighbour's house in the way had the safety crane lift the camera 22 m into an aerial view)
        tries = [(1.0, 1.0), (0.75, 1.0), (1.0, 0.7), (0.55, 1.0), (0.75, 0.6), (0.4, 0.8)]
        if str(side).lower() in ("behind", "back", "front"):
            tries = [(1.0, 1.0), (1.0, 0.7), (1.0, 0.5)]
        best = None
        for k_turn, k_r in tries:
            az = base + turn * k_turn
            cand = Vector((aim.x + math.cos(az) * r * k_r, aim.y + math.sin(az) * r * k_r, pos.z))
            lifted = _safe_place(tuple(cand), tuple(aim), exclude=exclude, see_past=see_past)[2] - cand.z
            if best is None or lifted < best[1] - 0.5:
                best = (cand, lifted)
            if lifted < 1.0:
                break
        pos = best[0]
        off = pos - aim
    if closer and hit and not side:
        # nearer to the surface it looks at — not to a target point behind that surface (moving toward a point
        # inside a shop put the camera in its awning, and the safety crane then lifted it 30 m)
        view = (aim - pos).normalized()
        surface = hit[1]
        pos = pos + view * max(0.0, surface - max(1.2, surface * max(0.15, float(closer))))
    elif closer:
        pos = aim + off * max(0.15, float(closer))
    if farther:
        pos = aim + off * max(1.0, float(farther))
    if height is not None:
        pos.z = float(height)
    if raise_by:
        pos.z += float(raise_by)
    if low:
        pos.z = max(0.4, ground_height(pos.x, pos.y, default=0.0) + 0.5)   # noqa: F821
        aim.z = max(aim.z, aim.z + 1.0)
    if high or drone:
        flat_d = max(8.0, (pos - aim).length)
        pos.z = aim.z + flat_d * (0.9 if drone else 0.55)
        if drone:
            pos = aim + (pos - aim) * 1.3
    if pan:
        a = math.radians(float(pan))
        v = aim - pos
        aim = pos + Vector((v.x * math.cos(a) - v.y * math.sin(a), v.x * math.sin(a) + v.y * math.cos(a), v.z))
    if tilt:
        aim.z += math.tan(math.radians(float(tilt))) * (aim - pos).length
    safe = _safe_place(tuple(pos), tuple(aim), exclude=exclude, see_past=see_past)
    cam.location = safe
    target.location = aim
    if lens:
        cam.data.lens = max(8.0, min(300.0, float(lens)))
    if lens_factor:
        cam.data.lens = max(8.0, min(300.0, cam.data.lens * float(lens_factor)))
    if drone:
        cam["jervis_shot"] = "drone"
    _update()   # noqa: F821
    moved_for_safety = (Vector(safe) - pos).length > 0.05
    return {"camera": cam.name, "location": [round(v, 2) for v in safe], "aim": [round(v, 2) for v in aim],
            "lens": round(cam.data.lens, 1), "adjusted": moved_for_safety}


def camera_adjust(name=None, d_yaw=0.0, d_pitch=0.0, dolly=1.0, lens_factor=1.0, d_height=0.0):
    """Nudge a camera: turn it d_yaw degrees (positive: to the left) and d_pitch (positive: down), move it along
    its view by `dolly` (0.8 = 20% closer to what it looks at, 1.2 = farther), change its lens, raise it — keeping
    its target the same distance ahead, and itself clear of everything. Returns its new pose."""
    cam = _cam(name)
    target = bpy.data.objects.get(f"{cam.name} Target")
    if target is None:
        _rig(cam.name, cam.data.lens)   # noqa: F821
        target = bpy.data.objects.get(f"{cam.name} Target")
        target.location = _subject_point(cam)
    pos, aim = Vector(cam.location), Vector(target.location)
    v = aim - pos
    dist = max(0.5, v.length)
    yaw = math.atan2(-v.x, v.y) + math.radians(float(d_yaw))
    pitch = math.asin(max(-1.0, min(1.0, -v.z / dist))) + math.radians(float(d_pitch))
    fwd = Vector((-math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), -math.sin(pitch)))
    focus = pos + fwd * dist
    new_pos = focus - fwd * dist * float(dolly)
    new_pos.z += float(d_height)
    safe = _safe_place(tuple(new_pos), tuple(focus))
    cam.location = safe
    target.location = Vector(safe) + fwd * dist * float(dolly)
    cam.data.lens = max(8.0, min(300.0, cam.data.lens * float(lens_factor)))
    _update()   # noqa: F821
    return json.dumps({"location": [round(c, 3) for c in safe], "yaw": round(math.degrees(yaw), 2),
                       "pitch": round(math.degrees(pitch), 2), "lens": round(cam.data.lens, 2)})


def camera_pose(name=None) -> str:
    cam = _cam(name)
    target = bpy.data.objects.get(f"{cam.name} Target")
    return json.dumps({"location": list(cam.location), "target": list(target.location) if target else None,
                       "lens": cam.data.lens})


def set_camera_pose(pose, name=None):
    cam = _cam(name)
    cam.location = pose["location"]
    target = bpy.data.objects.get(f"{cam.name} Target")
    if target is not None and pose.get("target"):
        target.location = pose["target"]
    cam.data.lens = pose["lens"]
    _update()   # noqa: F821
    return "ok"


def _nearest_thing(point):
    ts = [t for t in scene_things() if t["category"] not in ("ground", "sky")]   # noqa: F821
    return min(ts, key=lambda t: math.dist(spatial.center(t["outer"]), (point.x, point.y)))   # noqa: F821


def cameras() -> str:
    return json.dumps([{"name": o.name, "lens": round(o.data.lens, 1), "active": o == _scene().camera,   # noqa: F821
                        "location": [round(v, 2) for v in o.matrix_world.translation],
                        "subject": json.loads(o.get("jervis_subject", "[]") or "[]")}
                       for o in bpy.data.objects if o.type == "CAMERA" and o.users_collection])


def switch_camera(name=None):
    """Make a camera the active one: by name, or the next one (cycling) when no name is given."""
    cams = [o for o in bpy.data.objects if o.type == "CAMERA" and o.users_collection]
    if not cams:
        raise KeyError("There are no cameras.")
    s = _scene()   # noqa: F821
    if name:
        s.camera = _cam(name)
    else:
        cams.sort(key=lambda o: o.name)
        k = cams.index(s.camera) if s.camera in cams else -1
        s.camera = cams[(k + 1) % len(cams)]
    return s.camera.name


def rename_camera(old, new):
    cam = _cam(old)
    target = bpy.data.objects.get(f"{cam.name} Target")
    cam.name = new
    cam.data.name = new
    if target is not None:
        target.name = f"{cam.name} Target"
    return cam.name


def delete_camera(name):
    cam = _cam(name)
    target = bpy.data.objects.get(f"{cam.name} Target")
    s = _scene()   # noqa: F821
    was_active = s.camera == cam
    trash(cam.name)   # noqa: F821  (undoable)
    if target is not None:
        trash(target.name)   # noqa: F821
    if was_active:
        rest = [o for o in bpy.data.objects if o.type == "CAMERA" and o.users_collection]
        s.camera = rest[0] if rest else None
    return name


def camera_check(name=None) -> str:
    """Is a camera somewhere it may be? JSON: inside a thing, below the ground, its view to what it looks at blocked
    — and by what."""
    cam = _cam(name)
    pos = tuple(cam.matrix_world.translation)
    aim = tuple(_subject_point(cam))
    ts, boxes = _obstacles()
    inside = [n for n, lo, hi in boxes if cinema._inside_box(pos, lo, hi, 0.15)]   # noqa: F821
    blocked = [n for n, lo, hi in boxes if cinema._seg_hits_box(pos, aim, lo, hi) and n not in inside]   # noqa: F821
    ground = ground_height(pos[0], pos[1], default=0.0)   # noqa: F821
    return json.dumps({"camera": cam.name, "inside": sorted(set(inside)), "blocked_by": sorted(set(blocked))[:4],
                       "below_ground": pos[2] < ground + 0.1, "location": [round(v, 2) for v in pos],
                       "lens": round(cam.data.lens, 1)})


# ---------- rendering, for checking by eye ----------

def render_view(path, camera=None, width=640, height=None, engine="EEVEE", samples=12, frame=None):
    """Render what a camera sees to `path` (PNG) — small and quick, for comparing against a reference. The scene's
    own render settings are put back afterwards."""
    s = _scene()   # noqa: F821
    keep = {"engine": s.render.engine, "x": s.render.resolution_x, "y": s.render.resolution_y,
            "pct": s.render.resolution_percentage, "path": s.render.filepath, "camera": s.camera,
            "frame": s.frame_current}
    try:
        if camera:
            s.camera = _cam(camera)
        if s.camera is None:
            raise KeyError("There's no camera to render from.")
        h = height or int(round(width * keep["y"] / max(1, keep["x"])))
        s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = int(width), int(h), 100
        eng = {"EEVEE": "BLENDER_EEVEE_NEXT", "WORKBENCH": "BLENDER_WORKBENCH", "CYCLES": "CYCLES"}.get(
            str(engine).upper(), "BLENDER_EEVEE_NEXT")
        try:
            s.render.engine = eng
        except TypeError:
            s.render.engine = "BLENDER_EEVEE"
        if s.render.engine.startswith("BLENDER_EEVEE"):
            try:
                s.eevee.taa_render_samples = int(samples)
            except Exception:
                pass
        if s.render.engine == "CYCLES":
            s.cycles.samples = int(samples)
        if frame is not None:
            s.frame_set(int(frame))
        s.render.filepath = str(path)
        s.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
    finally:
        s.render.engine = keep["engine"]
        s.render.resolution_x, s.render.resolution_y = keep["x"], keep["y"]
        s.render.resolution_percentage = keep["pct"]
        s.render.filepath = keep["path"]
        if keep["camera"] is not None:
            s.camera = keep["camera"]
        if frame is not None:
            s.frame_set(keep["frame"])
    return str(path)


def project_points(points, camera=None) -> str:
    """Where world points land in a camera's picture (0..1 from the top-left), for comparing a rebuild with the
    reference's boxes. JSON list of [x, y, depth] (None behind the camera)."""
    from bpy_extras.object_utils import world_to_camera_view
    s = _scene()   # noqa: F821
    cam = _cam(camera)
    out = []
    for p in points:
        v = world_to_camera_view(s, cam, Vector(p))
        out.append([round(v.x, 4), round(1 - v.y, 4), round(v.z, 3)] if v.z > 0 else None)
    return json.dumps(out)


def thing_frames(camera=None) -> str:
    """Every thing's box as the camera sees it (0..1 from the top-left), JSON {name: [x1, y1, x2, y2]} — the render's
    side of a reference-vs-rebuild comparison."""
    from bpy_extras.object_utils import world_to_camera_view
    s = _scene()   # noqa: F821
    cam = _cam(camera)
    out = {}
    for t in scene_things():   # noqa: F821
        corners = [(x, y, z) for x in (t["lo"][0], t["hi"][0]) for y in (t["lo"][1], t["hi"][1])
                   for z in (t["lo"][2], t["hi"][2])]
        vs = [world_to_camera_view(s, cam, Vector(c)) for c in corners]
        vs = [v for v in vs if v.z > 0]
        if not vs:
            continue
        raw = [min(v.x for v in vs), 1 - max(v.y for v in vs), max(v.x for v in vs), 1 - min(v.y for v in vs)]
        box = [max(0.0, min(1.0, raw[0])), max(0.0, min(1.0, raw[1])), max(0.0, min(1.0, raw[2])),
               max(0.0, min(1.0, raw[3]))]
        if box[2] - box[0] < 1e-4 or box[3] - box[1] < 1e-4:
            continue   # entirely out of the picture
        whole = max(1e-6, (raw[2] - raw[0]) * (raw[3] - raw[1]))
        out[t["name"]] = [round(v, 4) for v in box] + [round((box[2] - box[0]) * (box[3] - box[1]) / whole, 3)]
    return json.dumps(out)


# ---------- lights, by meaning ----------

def lights_set(target=None, on=True, factor=None, warmth=None):
    """Lights of a thing (or all of them) on, off, brighter (factor), warmer/cooler (warmth in kelvin): a
    building's windows and rooms, a pool's underwater lights (made if it has none), street lamps and lanterns,
    a lamp. Changes the lights that are there; adds only what a thing needs to be lit at all."""
    done = []
    roots = [bpy.data.objects.get(_thing(target)["name"])] if target else [o for o in _roots_of()]   # noqa: F821
    for root in roots:
        if root is None:
            continue
        kind = ""
        try:
            kind = json.loads(root.get("jervis_semantic", "{}") or "{}").get("kind") or \
                json.loads(root.get("jervis_asset", "{}") or "{}").get("type", "")
        except (ValueError, TypeError):
            pass
        glow = json.loads(root.get("jervis_glow", "{}") or "{}")
        if kind in ("house", "villa", "storefront", "shop", "building") or _parts_named(root, ("window glass",)):
            level = float(glow.get("level", 1.0 if kind in ("storefront", "shop") else 0.7)) * float(factor or 1.0)
            try:
                window_glow(root.name, on=on, level=min(3.0, level), share=glow.get("share", 0.9 if kind in (
                    "storefront", "shop") else 0.55), warmth=warmth or glow.get("warmth", 2800))
                if kind in ("storefront", "shop"):
                    sign_glow(root.name, on=on)
                done.append(root.name)
            except (ValueError, KeyError):
                pass
            continue
        if kind in ("swimming pool", "pool", "pond") or "pool" in root.name.lower():
            own = _lights_of(root.name)   # noqa: F821
            if not own and on:
                own = pool_lights(root.name, on=True)   # noqa: F821
            for lt in own:
                full = float(lt.get("jervis_energy") or 120.0) * float(factor or 1.0)
                lt["jervis_energy"] = full
                lt.data.energy = full if on else 0.0
                if warmth:
                    lt.data.color = _kelvin_rgb(warmth)
            mat = bpy.data.materials.get("Jervis pool light")
            if mat is not None and _bsdf(mat) is not None:
                _bsdf(mat).inputs["Emission Strength"].default_value = 6.0 if on else 0.0
            done.append(root.name)
            continue
        own = [o for o in [root] + list(root.children_recursive) if o.type == "LIGHT"]
        for lt in own:
            full = float(lt.get("jervis_energy") or lt.data.energy or 100.0) * float(factor or 1.0)
            lt["jervis_energy"] = full
            lt.data.energy = full if on else 0.0
            if warmth:
                lt.data.color = _kelvin_rgb(warmth)
            gm = bpy.data.materials.get(lt.get("jervis_glow_material", ""))
            if gm is not None and _bsdf(gm) is not None:
                _bsdf(gm).inputs["Emission Strength"].default_value = 3.0 if on else 0.0
        if own:
            done.append(root.name)
    if not done:
        raise ValueError(f"There's nothing with lights to change{' in ' + str(target) if target else ''}.")
    return done


def path_lights(path, spacing=3.0, height=0.6, on=True):
    """Low bollard lights along a path or a road's edges, every `spacing` metres, warm, on (after dark they show)."""
    t = _thing(path)   # noqa: F821
    pts = []
    root = bpy.data.objects.get(t["name"])
    route = json.loads(root.get("jervis_route", "[]") or "[]") if root is not None else []
    if not route:
        route = [list(p) for p in (t.get("ends") or [])]
    if len(route) < 2:
        r = t["outer"]
        long_x = (r[2] - r[0]) >= (r[3] - r[1])
        cy, cx = (r[1] + r[3]) / 2, (r[0] + r[2]) / 2
        route = [[r[0], cy], [r[2], cy]] if long_x else [[cx, r[1]], [cx, r[3]]]
        half = ((r[3] - r[1]) if long_x else (r[2] - r[0])) / 2 + 0.4
    else:
        half = float(json.loads(root.get("jervis_asset", "{}") or "{}").get("params", {}).get("width", 1.2)) / 2 + 0.35
    made = []
    k = 0
    for (x0, y0), (x1, y1) in zip(route, route[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(seg / spacing))
        nx, ny = -(y1 - y0) / max(seg, 1e-6), (x1 - x0) / max(seg, 1e-6)
        for i in range(n):
            a = (i + 0.5) / n
            px, py = x0 + (x1 - x0) * a, y0 + (y1 - y0) * a
            side = 1 if k % 2 == 0 else -1
            k += 1
            nm = f"{t['name']} Light {k}"
            bx, by = px + nx * half * side, py + ny * half * side
            post = Parts()   # noqa: F821
            post.cylinder((0, 0, 0), 0.07, height, segments=10)
            cap = Parts()   # noqa: F821
            cap.cylinder((0, 0, height), 0.09, 0.08, segments=10)
            z = ground_height(bx, by)   # noqa: F821
            p_obj = post.done(f"{nm} Post", (bx, by, z), "dark metal", smooth=True)
            c_obj = cap.done(f"{nm} Lens", (bx, by, z), material("#fff1d0", name="Jervis bollard glass",   # noqa: F821
                                                                   emission=2.0 if on else 0.0), smooth=True)
            root_l = assemble(nm, [p_obj.name, c_obj.name], at=(bx, by, z))   # noqa: F821
            lt = light(f"{nm} Bulb", "point", at=(bx, by, z + height + 0.05), energy=30, color=2800, size=0.05,   # noqa: F821
                       on=on)
            _adopt(lt, root_l)   # noqa: F821
            lt["jervis_light_for"] = root_l.name
            lt["jervis_glow_material"] = "Jervis bollard glass"
            root_l["jervis_tags"] = "light_source_night"
            tag_semantic(root_l.name, "path light", role=f"light along {t['name']}")
            made.append(root_l.name)
    return made


def fill_light(direction="sun", soft=True, energy=None, name="Fill Light"):
    """A light from a direction — 'sun' (where the sun is), 'left' / 'right' / 'camera' (as the camera sees it) —
    soft (a big area light) or hard, aimed at the middle of the scene."""
    ts = [t for t in scene_things() if t["category"] not in ("ground", "sky")]   # noqa: F821
    if ts:
        lo = [min(t["lo"][i] for t in ts) for i in range(3)]
        hi = [max(t["hi"][i] for t in ts) for i in range(3)]
    else:
        lo, hi = [-5, -5, 0], [5, 5, 3]
    c = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2))
    r = max(6.0, (Vector(hi) - Vector(lo)).length * 0.8)
    s = _scene()   # noqa: F821
    if direction == "sun":
        sun = next((o for o in bpy.data.objects if o.type == "LIGHT" and o.data.type == "SUN"), None)
        d = -(sun.matrix_world.to_3x3() @ Vector((0, 0, -1))) if sun else Vector((0.5, -0.5, 0.7))
        col = tuple(sun.data.color) if sun else (1.0, 0.8, 0.6)
    else:
        cam = s.camera
        fwd = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))) if cam else Vector((0, 1, 0))
        right = Vector((fwd.y, -fwd.x, 0)).normalized()
        d = {"left": -right, "right": right, "camera": -fwd}.get(direction, -fwd)
        d = Vector((d.x, d.y, 0.6)).normalized()
        col = (1.0, 0.92, 0.82)
    d.z = max(0.15, d.z)
    pos = c + d.normalized() * r
    lt = light(name, "area" if soft else "spot", at=tuple(pos), energy=energy or 1500.0 * (r / 10) ** 2,   # noqa: F821
               color=col, size=r * 0.5 if soft else 0.1, aim=tuple(c))
    return lt.name


def move_with(name, direction=None, distance=None, toward=None, gap=2.5):
    """Move a thing together with what belongs with it — its own parts, its lights, things standing on or attached
    to it (a lounger on its terrace, lamps along its path) — `direction` 'back' | 'forward' | 'left' | 'right' |
    'away' | 'closer' (as the camera sees it) by `distance` metres (a sensible amount by default), or `toward`
    another thing until `gap` metres apart. Things that merely stand nearby keep their places."""
    t = _thing(name)   # noqa: F821
    ts = scene_things()   # noqa: F821
    c = Vector((*spatial.center(t["outer"]), 0))   # noqa: F821
    size = max(t["outer"][2] - t["outer"][0], t["outer"][3] - t["outer"][1])
    if toward is not None:
        o = _thing(toward)   # noqa: F821
        oc = Vector((*spatial.center(o["outer"]), 0))   # noqa: F821
        dist_now = spatial.gap(t["outer"], o["outer"])   # noqa: F821
        step = max(0.0, dist_now - gap)
        v = (oc - c)
        v = v.normalized() * step if v.length > 1e-6 else Vector((0, 0, 0))
    else:
        cam = _scene().camera   # noqa: F821
        fwd = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))) if cam else Vector((0, 1, 0))
        fwd = Vector((fwd.x, fwd.y, 0)).normalized() if Vector((fwd.x, fwd.y, 0)).length > 1e-6 else Vector((0, 1, 0))
        right = Vector((fwd.y, -fwd.x, 0))
        amount = float(distance) if distance else max(2.0, size * 0.35)
        d = {"back": fwd, "backward": fwd, "backwards": fwd, "away": fwd, "forward": -fwd, "forwards": -fwd,
             "closer": -fwd, "left": -right, "right": right}.get(str(direction).lower(), fwd)
        v = d * amount
    followers = [t["name"]]
    for o in ts:   # what stands on it or within its footprint (its terrace furniture), and what is attached to it
        if o["name"] == t["name"] or o["category"] in ("ground", "sky", "building"):
            continue
        g = spatial.grow(t["outer"], 0.3)   # noqa: F821
        within = g[0] <= o["outer"][0] and g[1] <= o["outer"][1] and o["outer"][2] <= g[2] and o["outer"][3] <= g[3]
        if within or spatial.overlap_depth(o["outer"], t["outer"]) > 0.5:   # noqa: F821
            followers.append(o["name"])
    for nm in followers:
        root = bpy.data.objects.get(nm)
        if root is None:
            continue
        root.location = root.location + v
    _update()   # noqa: F821
    return {"moved": followers, "by": [round(v.x, 2), round(v.y, 2)]}


def make_room(name, margin=0.8):
    """After a thing grew (a house made bigger): whatever now stands in it or against it — a pool, a car, a bench —
    is moved straight out from it, just far enough, each as a whole; the ground and paths stay. Keeps every
    relationship (still beside it, still in front of it), only the gap is restored."""
    t = _thing(name)   # noqa: F821
    grown = spatial.grow(t["outer"], margin)   # noqa: F821
    cx, cy = spatial.center(t["outer"])   # noqa: F821
    moved = []
    for o in scene_things():   # noqa: F821
        if o["name"] == t["name"] or o["category"] in ("ground", "sky", "path", "surface"):
            continue
        if spatial.overlap_depth(o["outer"], grown) <= 0.01:   # noqa: F821
            continue
        ox_, oy_ = spatial.center(o["outer"])   # noqa: F821
        dx, dy = ox_ - cx, oy_ - cy
        # out through the nearest side of the grown footprint
        if abs(dx) * (grown[3] - grown[1]) >= abs(dy) * (grown[2] - grown[0]):
            shift = (grown[2] - o["outer"][0]) if dx >= 0 else (grown[0] - o["outer"][2])
            v = (shift, 0.0)
        else:
            shift = (grown[3] - o["outer"][1]) if dy >= 0 else (grown[1] - o["outer"][3])
            v = (0.0, shift)
        try:
            shift_thing(o["names"], v[0], v[1], 0.0)   # noqa: F821
            moved.append(o["name"])
        except Exception:
            pass
    return moved


def cinematic_look():
    """A filmic finish: punchier contrast, a little depth of field on the active camera, motion blur."""
    s = _scene()   # noqa: F821
    try:
        s.view_settings.view_transform = "AgX"
        s.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        try:
            s.view_settings.look = "Medium High Contrast"
        except TypeError:
            pass
    try:
        s.render.use_motion_blur = True
    except AttributeError:
        pass
    if s.camera is not None:
        s.camera.data.dof.use_dof = True
        s.camera.data.dof.aperture_fstop = 2.8
    _env_set(cinematic=True)
    return "filmic"


WORLD_BUILDERS = ("env_state", "tag_semantic", "semantic_registry", "window_glow", "sign_glow", "lamps",
                  "time_of_day", "fog", "wet", "weather", "snow_cover", "water_motion", "wind_strength",
                  "pause_motion", "resume_motion", "remove_animation", "material_edit", "camera_match",
                  "camera_edit", "cameras", "switch_camera", "rename_camera", "delete_camera", "camera_check",
                  "render_view", "project_points", "thing_frames", "lights_set", "path_lights", "fill_light",
                  "move_with", "cinematic_look", "camera_adjust", "camera_pose", "set_camera_pose", "sky_color",
                  "make_room", "sky_clouds", "camera_on_box", "camera_on_place", "place_box", "clear_view",
                  "camera_horizon")
if bpy is not None:
    try:
        _KIT.update({k: globals()[k] for k in WORLD_BUILDERS})   # noqa: F821
        _KIT.update({k: v for k, v in globals().items() if k.startswith("_") and callable(v) and k not in _KIT})   # noqa: F821
    except NameError:
        pass
