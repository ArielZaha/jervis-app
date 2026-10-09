"""Checking a rebuild by eye, and fixing what's most wrong first: render the scene through its camera, compare with
the reference picture, find the biggest mismatch, fix it, render again — while it keeps getting better.

The comparison is measured, not guessed:
- COMPOSITION: where each rebuilt thing lands in the render (its box, from Blender) against where the picture shows
  it (its box from the vision pass). A shift or scale shared by everything is the camera's fault (turn it, tilt it,
  move it closer or back); what's left over is that thing's own placement or size.
- COLOUR AND LIGHT: the main things' colours in the render against the picture's, region by region, and the overall
  brightness; a material or the exposure is corrected.
- STRUCTURE: an edge-map correlation and a colour-layout distance (image_analysis.compare) score the whole.
Every fix is kept only if the score improves; otherwise it's taken back. The order follows what matters most:
camera and composition, then main structures and their placement and proportions, then colours and light.

Finally the vision model is asked, side by side, for the biggest difference left — said to the user, not hidden."""
import json
import math
import os
import tempfile
import time

import image_analysis
import visual_scene
from visual_scene import val

ROUNDS = 4
RENDER_WIDTH = 640


def _bridge_json(bridge, code, timeout=60):
    r = bridge.run(code, timeout=timeout)
    if not r.get("ok"):
        raise RuntimeError((r.get("error") or "")[-300:])
    try:
        return json.loads(r.get("output") or "null")
    except ValueError:
        return r.get("output")


def render(bridge, path, width=RENDER_WIDTH, engine="EEVEE"):
    out = _bridge_json(bridge, f"RESULT = json.dumps(render_view({path!r}, width={width}, engine={engine!r}))",
                       timeout=240)
    return out if isinstance(out, str) and os.path.exists(out) else None


def alignment(scene: dict, built: dict, frames: dict) -> list:
    """For each rebuilt element seen in both: where the picture has it vs where the render has it (normalised
    0..1 boxes) — centre offsets and log size ratios, weighted by how much the element matters."""
    out = []
    for e in scene["elements"]:
        name = built.get(e["id"])
        if not name or name not in frames or e["category"] in ("ground", "sky", "part"):
            continue
        a, b = e["box_norm"], frames[name][:4]
        if b[2] - b[0] < 1e-3 or b[3] - b[1] < 1e-3:
            continue
        trunc = e.get("truncated", {})
        w_ok = not (trunc.get("left") or trunc.get("right"))
        h_ok = not (trunc.get("top") or trunc.get("bottom"))
        # the foot of a thing on the ground is the most reliable point of all
        dx = ((b[0] + b[2]) / 2 - (a[0] + a[2]) / 2)
        dy = (b[3] - a[3]) if not trunc.get("bottom") else ((b[1] + b[3]) / 2 - (a[1] + a[3]) / 2)
        sw = math.log(max(1e-3, b[2] - b[0]) / max(1e-3, a[2] - a[0])) if w_ok else None
        sh = math.log(max(1e-3, b[3] - b[1]) / max(1e-3, a[3] - a[1])) if h_ok else None
        weight = {"high": 3.0, "medium": 1.5, "low": 0.6}.get(e.get("priority"), 1.0) * (0.5 + e.get("confidence", 0.6))
        out.append({"id": e["id"], "name": name, "kind": e["kind"], "category": e["category"], "dx": dx, "dy": dy,
                    "sw": sw, "sh": sh, "weight": weight})
    return out


def _wmean(items, key):
    vals = [(it[key], it["weight"]) for it in items if it.get(key) is not None]
    tw = sum(w for _, w in vals)
    return (sum(v * w for v, w in vals) / tw) if tw else None


def composition_error(items) -> float:
    """One number for how far off the composition is (0 = every thing exactly where the picture has it)."""
    if not items:
        return 0.0
    tw = sum(i["weight"] for i in items)
    err = 0.0
    for i in items:
        e = abs(i["dx"]) + abs(i["dy"]) + 0.5 * abs(i["sw"] or 0.0) + 0.5 * abs(i["sh"] or 0.0)
        err += e * i["weight"]
    return err / tw


def camera_fix(items, camera: dict) -> dict:
    """The camera change that removes what EVERYTHING shares: a common horizontal shift is a turn, a vertical one a
    tilt, a common scale a move closer or back. Only when the things agree (a consistent shift), so one misplaced
    thing never swings the camera."""
    if len(items) < 1:
        return {}
    hfov = math.radians(val(camera.get("hfov"), 54.0))
    vfov = math.radians(camera.get("vfov") or 38.0)
    dx, dy = _wmean(items, "dx"), _wmean(items, "dy")
    scale = _wmean(items, "sw") if _wmean(items, "sw") is not None else _wmean(items, "sh")
    agree_x = len(items) == 1 or sum(1 for i in items if i["dx"] * (dx or 0) > 0) >= 0.7 * len(items)
    agree_s = scale is not None and (len(items) == 1 or sum(1 for i in items if (i["sw"] or i["sh"] or 0) * scale > 0)
                                     >= 0.7 * len(items))
    fix = {}
    if dx is not None and agree_x and abs(dx) > 0.02:
        # rendered things sit to the RIGHT of where they should: turn the camera right (negative yaw)
        fix["d_yaw"] = -math.degrees(math.atan(2 * dx * math.tan(hfov / 2))) * 0.85
    if dy is not None and abs(dy) > 0.02:
        # rendered things sit LOWER than they should: tilt the camera down (positive pitch)
        fix["d_pitch"] = math.degrees(math.atan(2 * dy * math.tan(vfov / 2))) * 0.85
    if scale is not None and agree_s and abs(scale) > 0.06:
        fix["dolly"] = max(0.5, min(1.8, math.exp(scale * 0.85)))   # too big -> farther away
    return fix


def object_fixes(items, built_positions: dict, camera: dict, max_fixes=3) -> list:
    """What's left after the camera: things placed or sized wrong on their own. Small things move; buildings are
    left to the camera (they define it)."""
    fixes = []
    hfov = math.radians(val(camera.get("hfov"), 54.0))
    for i in sorted(items, key=lambda i: -(abs(i["dx"]) + abs(i["sw"] or 0)) * i["weight"]):
        if i["category"] == "building" or len(fixes) >= max_fixes:
            continue
        pos = built_positions.get(i["name"])
        if pos is None:
            continue
        dist = max(1.0, math.hypot(pos[0], pos[1]))
        if abs(i["dx"]) > 0.04:
            # the render has it dx (fraction of the width) to the right: move it left by that much at its distance
            shift = -i["dx"] * 2 * dist * math.tan(hfov / 2)
            fixes.append({"name": i["name"], "move_x": round(shift, 2)})
        elif i["sw"] is not None and abs(i["sw"]) > 0.25 and i["category"] in ("outdoor", "furniture"):
            fixes.append({"name": i["name"], "scale": round(math.exp(-i["sw"] * 0.8), 3)})
    return fixes


def colour_fixes(scene, built, ref_img, render_img, frames, max_fixes=2) -> list:
    """The main things' colour in the render vs in the picture: a big difference in a building's walls or the
    ground is corrected to the picture's colour."""
    out = []
    W, H = render_img.size
    for e in sorted(scene["elements"], key=lambda e: -e["area"]):
        name = built.get(e["id"])
        if not name or name not in frames or e["category"] not in ("building", "ground", "sunken"):
            continue
        b = frames[name][:4]
        box = (b[0] * W, b[1] * H, b[2] * W, b[3] * H)
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue
        mine = image_analysis.region(render_img, box)
        theirs = e["measured"].get("color")
        if not theirs:
            continue
        ref_rgb = [int(theirs[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        diff = sum(abs(a - b) for a, b in zip(mine["rgb"], ref_rgb))
        if diff > 0.35:
            part = "walls" if e["category"] == "building" else "ground" if e["category"] == "ground" else "water"
            out.append({"name": name, "part": part, "color": theirs, "diff": round(diff, 2)})
        if len(out) >= max_fixes:
            break
    return out


def _main_name(scene, built):
    main = max([e for e in scene["elements"] if built.get(e["id"]) and e["category"] in ("building", "sunken",
                                                                                         "outdoor")] or [None],
               key=lambda e: e["area"] if e else 0)
    return built.get(main["id"]) if main else None


def _sane(before, after, scene, built) -> bool:
    """A fix is only kept if the picture still shows what it's about: the main thing still in view (and not much
    less of it), and the render not gone dark — a black frame can score close to a dark photo's average colour."""
    name = _main_name(scene, built)
    if name:
        fb, fa = before["frames"].get(name), after["frames"].get(name)
        if fb and not fa:
            return False
        if fb and fa:
            area = lambda f: (f[2] - f[0]) * (f[3] - f[1])
            if area(fa) < 0.6 * area(fb) and area(fb) < 0.9:
                return False
    if after["stats"]["brightness_render"] < 0.4 * max(0.02, before["stats"]["brightness_render"]):
        return False
    return True


def sky_fix_for(ref_img, render_img, scene):
    """The sky's colour and brightness in the photo vs the render (the top band, where the photo shows sky)."""
    share = (scene.get("measurements", {}).get("sky") or {}).get("share", 0)
    if share < 0.3:
        return None
    a = image_analysis.region(ref_img, (0, 0, ref_img.width, ref_img.height * 0.18), inner=0.05)
    b = image_analysis.region(render_img, (0, 0, render_img.width, render_img.height * 0.18), inner=0.05)
    diff = sum(abs(x - y) for x, y in zip(a["rgb"], b["rgb"]))
    if diff < 0.18:
        return None
    lin = lambda c: (c / 12.92) if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    target = [lin(c) for c in a["rgb"]]
    peak = max(target + [1e-3])
    colour = image_analysis.to_hex([c / peak for c in target])
    return {"color": colour, "strength": max(0.05, min(3.0, peak * 1.6))}


def run(adapter, scene: dict, built: dict, image_path: str, rounds: int = ROUNDS, log=print) -> dict:
    """The critique loop on a live scene (adapter.bridge). Returns {"score_before", "score_after", "fixes",
    "remaining", "renders"}."""
    from PIL import Image
    bridge = adapter.bridge
    work = tempfile.mkdtemp(prefix="jervis-critique-")
    try:   # Blender is about to render: give it the GPU's memory (the vision model reloads for the last look)
        import local_llm
        local_llm.unload_all()
    except Exception:
        pass
    ref = Image.open(image_path).convert("RGB")
    camera = scene["camera"]
    applied, renders = [], []

    def measure(tag):
        path = render(bridge, os.path.join(work, f"render_{tag}.png"))
        if path is None:
            return None
        img = Image.open(path).convert("RGB")
        frames = _bridge_json(bridge, "RESULT = thing_frames()") or {}
        items = alignment(scene, built, frames)
        stats = image_analysis.compare(ref, img)
        comp = composition_error(items)
        # things the picture shows but the render doesn't (out of view) count as badly placed
        seen = {i["name"] for i in items}
        missing = sum(1 for e in scene["elements"] if built.get(e["id"]) and e["category"] in ("building", "sunken")
                      and built[e["id"]] not in seen)
        comp += 0.5 * missing
        score = stats["score"] * 0.3 + max(0.0, 1.0 - comp * 2.5) * 0.7
        renders.append(path)
        return {"img": img, "frames": frames, "items": items, "stats": stats, "comp": comp, "score": score,
                "path": path}

    def positions():
        raw = _bridge_json(bridge, "RESULT = json.dumps({t['name']: list(spatial.center(t['outer'])) for t in "
                                   "scene_things()})") or {}
        return raw

    started = time.time()
    m = measure("0")
    if m is None:
        return {"error": "the scene couldn't be rendered", "fixes": []}
    first = m["score"]
    log(f"Critique: score {first:.3f} (composition error {m['comp']:.3f}, structure {m['stats']['structure']:.2f})")
    for r in range(1, rounds + 1):
        candidates = []
        cam = camera_fix(m["items"], camera)
        if cam:
            candidates.append(("camera", f"RESULT = camera_adjust('Camera', d_yaw={cam.get('d_yaw', 0.0):.3f}, "
                                         f"d_pitch={cam.get('d_pitch', 0.0):.3f}, dolly={cam.get('dolly', 1.0):.3f})",
                               f"turned/moved the camera to match the photo's framing"))
        for f in object_fixes(m["items"], positions(), camera):
            if "move_x" in f:
                candidates.append(("object", f"RESULT = str(move({f['name']!r}, by=({f['move_x']}, 0, 0)))",
                                   f"moved {f['name']} to where the photo has it"))
            elif "scale" in f:
                candidates.append(("object", f"RESULT = str(scale({f['name']!r}, {f['scale']}))",
                                   f"resized {f['name']} to the photo's proportions"))
        for f in colour_fixes(scene, built, ref, m["img"], m["frames"]):
            candidates.append(("colour", f"RESULT = str(material_edit({f['name']!r}, {f['part']!r}, "
                                         f"color={f['color']!r}))", f"matched the {f['part']} of {f['name']} to the "
                                                                    "photo's colour"))
        sky_fix = sky_fix_for(ref, m["img"], scene)
        if sky_fix:
            candidates.append(("sky", f"RESULT = sky_color({sky_fix['color']!r}, mix=0.9, "
                                      f"strength={sky_fix['strength']:.3f})", "matched the sky to the photo's"))
        bright_ref, bright_ren = m["stats"]["brightness_ref"], m["stats"]["brightness_render"]
        if abs(bright_ren - bright_ref) > 0.08:
            ev = max(-2.0, min(2.0, math.log2(max(0.02, bright_ref) / max(0.02, bright_ren)) * 0.8))
            candidates.append(("exposure", f"bpy.context.scene.view_settings.exposure += {ev:.3f}\nRESULT = 'ok'",
                               "matched the photo's brightness"))
        if not candidates:
            break
        improved = False
        for kind, code, said in candidates:   # most important first; keep a fix only if it helps
            snap = adapter.snapshot()
            pose = _bridge_json(bridge, "RESULT = camera_pose('Camera')") if kind == "camera" else None
            res = bridge.run(code, timeout=60)
            if not res.get("ok"):
                adapter.rollback(snap)
                continue
            after = measure(f"{r}_{len(applied)}")
            if after is not None and after["score"] > m["score"] + 0.004 and _sane(m, after, scene, built):
                log(f"Critique round {r}: {said} — score {m['score']:.3f} -> {after['score']:.3f}")
                applied.append(said)
                m = after
                improved = True
                break
            if kind == "camera" and pose:
                bridge.run(f"RESULT = set_camera_pose({pose!r}, 'Camera')", timeout=20)
            else:
                adapter.rollback(snap)
        if not improved or time.time() - started > 600:
            break
    remaining = None
    try:
        answer = adapter.vision_compare(image_path, m["path"]) if hasattr(adapter, "vision_compare") else None
        if answer:
            remaining = answer
    except Exception:
        remaining = None
    try:   # and the GPU back to Blender, which the user is working in
        import local_llm
        local_llm.unload_all(wait=2.0)
    except Exception:
        pass
    return {"score_before": round(first, 3), "score_after": round(m["score"], 3), "fixes": applied,
            "remaining": remaining, "renders": renders, "final_render": m["path"],
            "composition_error": round(m["comp"], 3)}


COMPARE_PROMPT = """Image 1 is a reference photo. Image 2 is a 3D rebuild of it. Compare them and answer ONLY with JSON:
{"same_scene": true or false, "biggest_differences": [{"aspect": "camera | structure | proportions | terrain | materials | lighting | atmosphere | missing object | extra object", "what": "short description"}], "overall_match": "poor | fair | good"}
List at most 3 differences, most important first."""


def vision_compare(reference_path: str, render_path: str) -> dict:
    import vision
    return vision.compare_json([reference_path, render_path], COMPARE_PROMPT, max_tokens=500)
