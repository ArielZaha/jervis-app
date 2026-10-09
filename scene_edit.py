"""Editing the scene that exists, in plain words — "add fog", "make the fog thicker", "make it sunset", "turn on the
house lights", "make the ocean calmer", "make the windows darker", "show the house from behind", "use a wider lens",
"switch to the other camera", "stop the animation", "move the villa back"…

Each request becomes a short plan of kit calls that CHANGE what is there (one fog, retuned; one sun, moved) rather
than add another copy, with checks that prove the change (the fog's density went up, the camera isn't inside a
wall). Things are found by what they are (scene_state.Resolver): "the pool", "the left palm", "those chairs", "that"
(what was just talked about). When the words could mean several things and the scene can't settle it, the plan is a
question instead of a guess.

INTENTS is the table: (pattern, handler). A handler gets the match, the text, the current scene and the resolver,
and returns steps (or a question). Adding an edit is adding a row. Pure Python."""
import re

import semantics

_NUM = r"(\d+(?:\.\d+)?)"
MORE = r"(?:thicker|denser|heavier|stronger|more|bigger|rougher|wilder|higher|faster|brighter|louder|harder)"
LESS = r"(?:thinner|lighter|subtle|subtler|softer|weaker|less|calmer|gentler|smaller|slower|dimmer|quieter|lower)"


def _step(title, code, checks=None):
    return {"title": title, "code": code if "RESULT" in code else code + "\nRESULT = 'ok'", "checks": checks or []}


def _plan(understanding, steps, note=None):
    return {"understanding": understanding, "question": "", "steps": steps, "final_checks": [],
            "edit": True, "note": note}


def _ask(question):
    return {"understanding": "", "question": question, "steps": [], "final_checks": []}


def _target(phrase, current, resolver, kinds=None):
    """(names, question) for a phrase, preferring things of `kinds` when given."""
    names, conf, question = resolver.resolve(phrase, current)
    if not names and kinds:
        for k in kinds:
            names = [t["name"] for t in current.get("things", []) if t.get("kind") == k or
                     semantics.canonical(str(t.get("kind"))) == k]
            if names:
                break
    if not names:
        return [], question or f"I can't find {phrase!r} in the scene."
    resolver.remember(names)
    return names, None


def _factor(text, more=1.6, less=0.55):
    if re.search(rf"\b{MORE}\b", text, re.I) or re.search(r"\bincrease\b|\bboost\b|\bintensif", text, re.I):
        return more
    if re.search(rf"\b{LESS}\b", text, re.I) or re.search(r"\breduce\b|\bdecrease\b|\btone down\b", text, re.I):
        return less
    return None


# ---------- environment ----------

def fog_edit(m, text, current, resolver):
    t = text.lower()
    if re.search(r"\b(?:remove|clear|get rid of|no more|turn off|delete|lift)\b", t):
        return _plan("Clear the fog", [_step("Clear the air", "RESULT = fog(remove=True)",
                                             [{"type": "env", "path": "live.fog_density", "op": "<=", "value": 0.0}])])
    kind = "ground fog" if re.search(r"\b(?:ground|low|near the ground|valley)\b", t) else \
        "mist" if "mist" in t else "haze" if re.search(r"\b(?:haze|hazy|fade|atmospher)", t) else \
        "smoke" if "smoke" in t and "fog" not in t else "dust" if "dust" in t else None
    factor = _factor(t, 1.7, 0.5)
    have = (current.get("env") or {}).get("set", {}).get("fog")
    before = float((current.get("env") or {}).get("live", {}).get("fog_density") or 0.0)
    if factor and have:
        code = f"RESULT = fog(factor={factor})"
        op = ">" if factor > 1 else "<"
        title = "Thicken the fog" if factor > 1 else "Thin the fog"
        return _plan(title, [_step(title, code, [{"type": "env", "path": "live.fog_density", "op": op,
                                                  "value": before}])])
    args = [repr(kind or "fog")]
    if factor:
        args.append(f"factor={factor}")
    if kind == "haze" and re.search(r"\bmountain|hill|distance|far\b", t):
        args.append("density=0.012")
    code = f"RESULT = fog({', '.join(args)})"
    extra = []
    if re.search(r"\bmorning mist\b", t):
        extra.append(_step("Make it early morning", "RESULT = time_of_day('morning')",
                           [{"type": "env", "path": "set.time", "op": "==", "value": "morning"}]))
    return _plan(f"Add {kind or 'fog'}", extra + [_step(f"Fill the air with {kind or 'fog'}", code,
                                                        [{"type": "env", "path": "live.fog_density", "op": ">",
                                                          "value": 0.0}])])


def time_edit(m, text, current, resolver):
    word = m.group("t").lower()
    look = {"nighttime": "night", "night time": "night", "midnight": "night", "evening": "dusk", "twilight": "dusk",
            "dawn": "sunrise", "daytime": "day", "day time": "day", "noon": "day", "midday": "day",
            "daylight": "day"}.get(word, word)
    if look not in semantics.TIMES and look != "overcast":
        look = "day"
    return _plan(f"Make it {look}", [_step(f"Make it {look}", f"RESULT = str(time_of_day({look!r}))",
                                           [{"type": "env", "path": "set.time", "op": "==", "value": look}])])


def clouds_edit(t, env):
    """"Add some clouds", "more clouds", "fewer clouds", "remove the clouds": the cloud layer in the sky
    (sky_clouds), not the weather — a few clouds on a sunny day aren't an overcast sky."""
    have = float(env.get("clouds") or 0.0)
    if re.search(r"\b(?:remove|clear|get rid of|no more|without|delete)\b", t):
        return _plan("Clear the clouds", [_step("Clear the sky of clouds", "RESULT = sky_clouds(remove=True)",
                                                [{"type": "env", "path": "set.clouds", "op": "<=", "value": 0}])])
    f = _factor(t, 1.6, 0.5) or (0.5 if re.search(r"\b(?:fewer|a few|some|light|scattered)\b", t) else None)
    cover = min(0.9, max(0.1, have * f)) if (f and have) else \
        0.2 if re.search(r"\b(?:a few|scattered|light)\b", t) else 0.65 if (f or 1) > 1 else 0.4
    op = "<" if (have and f and f < 1) else ">"
    return _plan("Change the clouds" if have else "Add clouds",
                 [_step("Cloud the sky" if not have else "Change the clouds", f"RESULT = sky_clouds(cover={cover:.2f})",
                        [{"type": "env", "path": "set.clouds", "op": op, "value": have if f else 0}])])


def weather_edit(m, text, current, resolver):
    t = text.lower()
    env = (current.get("env") or {}).get("set", {})
    if re.search(r"\bclouds?\b", t) and not re.search(r"\b(?:cloudy|overcast|rain|snow|storm|thunder)\b", t):
        return clouds_edit(t, env)
    if re.search(r"\b(?:remove|stop|clear|no more|end|get rid of)\b.*\b(?:rain|snow|storm|weather|clouds?)\b|"
                 r"\bmake it (?:clear|sunny|dry)\b|\bclear (?:the )?(?:sky|weather)\b", t):
        return _plan("Clear the weather", [_step("Clear the weather", "RESULT = str(weather('clear'))",
                                                 [{"type": "env", "path": "set.weather", "op": "==",
                                                   "value": "clear"}])])
    kind = "storm" if re.search(r"\bstorm|thunder|lightning", t) else "snow" if re.search(r"\bsnow", t) else \
        "rain" if re.search(r"\brain|drizzle|shower|wet\b", t) else "cloudy"
    intensity = 1.0
    f = _factor(t, 1.8, 0.5)
    if f:
        intensity = float(env.get("weather_intensity", 1.0)) * f
    if kind == "rain" and re.search(r"\b(?:pavement|ground|street|road|surfaces?)\b.*\bwet\b|\bwet\b", t) and \
            not re.search(r"\brain", t):
        return _plan("Wet the surfaces", [_step("Wet the surfaces", "RESULT = str(len(wet(1.0)))",
                                                [{"type": "env", "path": "set.wet", "op": ">", "value": 0}])])
    code = f"RESULT = str(weather({kind!r}, intensity={intensity:.2f}))"
    return _plan(f"Make it {kind}", [_step(f"Make it {kind}", code,
                                           [{"type": "env", "path": "set.weather", "op": "==", "value": kind}])])


def wind_edit(m, text, current, resolver):
    t = text.lower()
    if re.search(r"\b(?:stop|no|remove|calm)\b.*\bwind\b|\bwindless\b|\bstill air\b", t):
        return _plan("Stop the wind", [_step("Still the air", "RESULT = str(wind_strength(0))",
                                             [{"type": "env", "path": "set.wind_strength", "op": "<=", "value": 0}])])
    f = _factor(t, 1.6, 0.5)
    env = (current.get("env") or {}).get("set", {})
    before = float(env.get("wind_strength", 0.0) or 0.0)
    code = f"RESULT = str(wind_strength(factor={f}))" if f and before else "RESULT = str(wind_strength(1.0))"
    op = "<" if f and f < 1 else ">"
    return _plan("Change the wind", [_step("Wind through the trees", code,
                                           [{"type": "env", "path": "set.wind_strength", "op": op, "value": before}])])


def water_edit(m, text, current, resolver):
    t = text.lower()
    phrase = m.group("w")
    names, q = _target(phrase, current, resolver, kinds=["ocean", "swimming pool", "lake", "river", "waterfall",
                                                          "pond", "beach"])
    if q:
        return _ask(q)
    speed = re.search(r"\b(?:faster|quicker|slower|slow down|speed up)\b", t)
    if speed:
        f = 1.6 if re.search(r"faster|quicker|speed up", t) else 0.55
        kw = f"speed_factor={f}"
    else:
        f = _factor(t, 1.8, 0.5)
        kw = f"strength_factor={f or 1.0}"
    steps = [_step(f"Change {n}'s water", f"RESULT = str(water_motion({n!r}, {kw}))",
                   [{"type": "animated", "object": n}]) for n in names]
    if re.search(r"\bloop\b", t):
        steps = [_step(f"Loop {n}", f"RESULT = str(water_motion({n!r}))", [{"type": "animated", "object": n}])
                 for n in names]
    return _plan("Change the water", steps)


def vegetation_edit(m, text, current, resolver):
    t = text.lower()
    f = 1.7 if re.search(rf"\b{MORE}\b|\bmore\b", t) else 0.5 if re.search(rf"\b{LESS}\b|\bless\b", t) else 1.0
    if re.search(r"\b(?:stop|freeze|still)\b", t):
        return _plan("Hold the trees still", [_step("Still the trees", "RESULT = str(wind_strength(0))")])
    return _plan("Change how the plants move", [_step("Wind through the plants",
                                                      f"RESULT = str(wind_strength(factor={f}))",
                                                      [{"type": "env", "path": "set.wind_strength",
                                                        "op": ">" if f > 1 else "<", "value": float(
                                                            ((current.get("env") or {}).get("set", {}) or {}).get(
                                                                "wind_strength", 1.0) or 1.0)}])])


def animation_edit(m, text, current, resolver):
    t = text.lower()
    target = m.groupdict().get("obj")
    names = []
    if target and not re.match(r"^(?:the )?(?:animation|animations|everything|all|motion|it all)$", target.strip()):
        names, q = _target(target, current, resolver)
        if q:
            return _ask(q)
    if re.search(r"\b(?:remove|delete|clear|get rid of)\b", t):
        if names:
            return _plan("Remove the animation", [_step(f"Stop {n} moving", f"RESULT = str(remove_animation({n!r}))")
                                                  for n in names])
        return _plan("Remove all animation", [_step("Remove every animation", "RESULT = str(remove_animation())")])
    if re.search(r"\b(?:resume|play|restart|start|continue|unpause)\b", t):
        return _plan("Resume the animation", [_step("Bring the motion back", "RESULT = str(resume_motion())")])
    if names:
        return _plan(f"Stop {', '.join(names)}", [_step(f"Stop {n}", f"RESULT = str(remove_animation({n!r}))")
                                                 for n in names])
    return _plan("Pause the animation", [_step("Hold everything still", "RESULT = str(pause_motion())",
                                               [{"type": "env", "path": "set.paused", "op": "==", "value": True}])])


# ---------- lights ----------

def lights_edit(m, text, current, resolver):
    t = text.lower()
    phrase = (m.groupdict().get("obj") or "").strip()
    off = bool(re.search(r"\b(?:off|out|darker|dim|dimmer)\b", t)) and not re.search(r"\bwarm", t)
    warm = re.search(r"\bwarm(?:er)?\b|\bcosier|cozier", t)
    cool = re.search(r"\bcool(?:er)?\b|\bcolder|bluer\b", t)
    brighter = re.search(r"\bbright(?:er)?\b|\bmore light\b|\bstronger\b", t)
    if phrase in ("", "the", "all the", "all"):
        names = []
    else:
        names, q = _target(phrase.replace(" lights", "").replace(" light", "") or phrase, current, resolver)
        if q:
            return _ask(q)
    if not names:
        names = [None]
    steps = []
    for n in names:
        args = [repr(n)] + (["on=False"] if off and not brighter and not warm else ["on=True"])
        if warm:
            args.append("warmth=2300")
        if cool:
            args.append("warmth=5200")
        if brighter:
            args.append("factor=1.6")
        elif re.search(r"\bdarker\b|\bdimmer\b|\bdim\b", t) and not off:
            args.append("factor=0.5")
        steps.append(_step(f"{'Turn off' if 'on=False' in args else 'Light'} {n or 'the lights'}",
                           f"RESULT = str(lights_set({', '.join(args)}))",
                           [{"type": "env", "path": "live.lights_on", "op": ">=" if "on=True" in args else ">=",
                             "value": 0}]))
    return _plan("Change the lights", steps)


def path_lights_edit(m, text, current, resolver):
    names, q = _target(m.group("p"), current, resolver, kinds=["path", "road", "walkway"])
    if q:
        return _ask(q)
    return _plan("Light the path", [_step(f"Lights along {n}", f"RESULT = str(path_lights({n!r}))",
                                          [{"type": "env", "path": "live.lights_on", "op": ">", "value": 0}])
                                    for n in names])


def fill_light_edit(m, text, current, resolver):
    t = text.lower()
    toward = "sun" if re.search(r"\bsun", t) else "left" if "left" in t else "right" if "right" in t else "camera"
    soft = not re.search(r"\bhard|harsh|sharp\b", t)
    return _plan("Add a light", [_step("Add a light", f"RESULT = fill_light(direction={toward!r}, soft={soft})",
                                       [{"type": "env", "path": "live.lights_on", "op": ">", "value": 0}])])


# ---------- materials ----------

_MATERIAL_PART = re.compile(r"\b(?P<part>walls?|roof|windows?|window frames|door|trim|grass|lawn|ground|water|"
                            r"leaves|foliage|trunks?|wood|floor|deck|pavement|sidewalk|road|street|asphalt|concrete|"
                            r"sign|awning|cushions|sofa|facade|façade)\b", re.I)


def material_edit_intent(m, text, current, resolver):
    t = text.lower()
    part_m = _MATERIAL_PART.search(t)
    part = part_m.group("part").lower() if part_m else None
    part = {"wall": "walls", "window": "windows", "lawn": "grass", "foliage": "leaves", "trunks": "trunk",
            "sidewalk": "pavement", "road": "pavement", "street": "pavement", "asphalt": "pavement",
            "facade": "walls", "façade": "walls", "concrete": "walls"}.get(part, part)
    if part == "pavement" and re.search(r"\bwet\b", t):
        return _plan("Wet the pavement", [_step("Wet the surfaces", "RESULT = str(len(wet(1.0)))",
                                                [{"type": "env", "path": "set.wet", "op": ">", "value": 0}])])
    owner = re.search(r"\b(?:of|on) (?:the )?(?P<o>[a-z ]+?)(?: \w+er\b|$)", t)
    target = None
    if owner and semantics.canonical(owner.group("o")):
        names, q = _target(owner.group("o"), current, resolver)
        if q:
            return _ask(q)
        target = names[0]
    kw = []
    colour = re.search(r"\b(white|black|grey|gray|red|blue|green|yellow|orange|brown|beige|cream|pink|purple|"
                       r"silver|gold|navy|teal|turquoise|dark grey|light grey|charcoal)\b", t)
    if colour and not re.search(r"\b(?:greener|redder|bluer)\b", t):
        kw.append(f"color={colour.group(1)!r}")
    if re.search(r"\bdarker\b", t):
        kw.append("darker=0.35")
    if re.search(r"\blighter\b|\bbrighter\b|\bpaler\b", t) and part not in ("windows",):
        kw.append("lighter=0.35")
    if re.search(r"\bgreener\b|\blusher\b", t):
        kw.append("greener=0.5")
    if re.search(r"\bwarmer\b", t):
        kw.append("warmer=0.5")
    if re.search(r"\brougher\b|\bmatte\b", t):
        kw.append("roughness=0.9")
    if re.search(r"\bsmoother\b|\bglossier\b|\bshinier\b|\bpolished\b", t):
        kw.append("roughness=0.15")
    if re.search(r"\breflective\b|\bmirror", t):
        kw.append("reflective=True")
    if re.search(r"\bclearer\b|\bclean(?:er)?\b|\btransparent\b", t):
        kw.append("clearer=True")
    if not kw:
        return None
    if part == "windows" and re.search(r"\bdarker\b", t) and not re.search(r"\bnight|lights?\b", t):
        kw = [k for k in kw if not k.startswith("darker")] + ["darker=0.5"]
    return _plan(f"Change the {part or 'material'}",
                 [_step(f"Change the {part or 'surfaces'}", f"RESULT = str(material_edit({target!r}, {part!r}, "
                                                            f"{', '.join(kw)}))")])


# ---------- cameras ----------

def camera_edit_intent(m, text, current, resolver):
    t = text.lower()
    cams = current.get("cameras") or []
    if re.search(r"\b(?:switch|change|go) to (?:the )?(?:other|next|second|another|previous)\b|\bother camera\b", t) \
            and not re.search(r"\bcreate|add|new\b", t):
        names, conf, q = resolver.resolve("the other camera", current, want_camera=True)
        if q:
            return _ask(q)
        return _plan("Switch camera", [_step("Switch camera", f"RESULT = switch_camera({names[0]!r})")])
    named = re.search(r"\bswitch to (?:the )?(?:camera )?['\"]?(?P<n>[\w ]+?)['\"]?(?: camera)?$", t)
    if named and any(c["name"].lower() == named.group("n").strip() for c in cams):
        n = next(c["name"] for c in cams if c["name"].lower() == named.group("n").strip())
        return _plan("Switch camera", [_step("Switch camera", f"RESULT = switch_camera({n!r})")])
    new = re.search(r"\b(?:create|add|make|set up|place) (?:a |another |a second |a new |one more )?(?:new )?camera"
                    r"(?: (?:looking at|on|pointing at|facing|aimed at|that shows|showing|of) (?:the )?(?P<subj>.+))?$", t)
    if new:
        subj = None
        if new.group("subj"):
            names, q = _target(new.group("subj"), current, resolver)
            if q:
                return _ask(q)
            subj = names[0]
        name = f"Camera {len(cams) + 1}" if cams else "Camera"
        return _plan("Add a camera", [_step(f"Add {name}", f"RESULT = camera({name!r}, {subj!r}, 'wide').name",
                                            [{"type": "exists", "object": name},
                                             {"type": "camera_safe", "object": name}])])
    rename = re.search(r"\brename (?:the )?(?P<a>.+?) (?:camera )?to ['\"]?(?P<b>[\w ]+?)['\"]?$", t)
    if rename and cams:
        names, conf, q = resolver.resolve(rename.group("a"), current, want_camera=True)
        if q:
            return _ask(q)
        return _plan("Rename the camera", [_step("Rename the camera",
                                                 f"RESULT = rename_camera({names[0]!r}, {rename.group('b').title()!r})")])
    if re.search(r"\b(?:delete|remove)\b.*\bcamera\b", t):
        names, conf, q = resolver.resolve(t, current, want_camera=True)
        if q:
            return _ask(q)
        return _plan("Delete the camera", [_step("Delete the camera", f"RESULT = delete_camera({names[0]!r})",
                                                 [{"type": "absent", "object": names[0]}])])
    kw, subject = [], None
    subj_m = re.search(r"\b(?:show|see|view|frame|look at|film|shoot)\b (?:me )?(?:the )?(?P<s>.+?)(?: from| at| in|$)", t) \
        or re.search(r"\b(?:behind|in front of|beside|next to|left of|right of|above|over) (?:the )?(?P<s>.+?)$", t)
    if subj_m and semantics.canonical(subj_m.group("s")):
        names, q = _target(subj_m.group("s"), current, resolver)
        if q:
            return _ask(q)
        subject = names[0]
        kw.append(f"subject={subject!r}")
    if re.search(r"\bbehind\b|\bfrom (?:the )?(?:back|behind|rear)\b", t):
        kw.append("side='behind'")
    elif re.search(r"\bfrom (?:the )?left\b|\bleft side\b", t):
        kw.append("side='left'")
    elif re.search(r"\bfrom (?:the )?right\b|\bright side\b", t):
        kw.append("side='right'")
    elif re.search(r"\bfrom (?:the )?front\b|\bin front of\b", t):
        kw.append("side='front'")
    if re.search(r"\bcloser\b|\bnearer\b|\bmove in\b|\bget closer\b", t):
        kw.append("closer=0.65")
    if re.search(r"\bfarther\b|\bfurther\b|\bback up\b|\bfurther away\b|\bmove (?:the camera )?back\b|\bzoom out\b", t) \
            and not re.search(r"\bbehind\b", t):
        kw.append("farther=1.5")
    if re.search(r"\blow(?:er)?[- ]angle\b|\bfrom below\b|\bground level\b|\bworm", t):
        kw.append("low=True")
    if re.search(r"\bhigh[- ]angle\b|\bfrom above\b|\bbird'?s?[- ]eye\b|\boverhead\b", t):
        kw.append("high=True")
    if re.search(r"\bdrone\b|\baerial\b", t):
        kw.append("drone=True")
    lens = re.search(r"\b" + _NUM + r"\s*mm\b", t)
    if lens:
        kw.append(f"lens={float(lens.group(1))}")
    elif re.search(r"\bwider\b|\bwide[- ]angle\b|\bwide lens\b|\bwider lens\b", t):
        kw.append("lens_factor=0.7")
    elif re.search(r"\btighter\b|\blonger lens\b|\btelephoto\b|\bzoom in\b|\bnarrower\b", t):
        kw.append("lens_factor=1.45")
    height = re.search(r"\b" + _NUM + r"\s*(?:m|metres|meters) (?:up|high)\b", t)
    if height:
        kw.append(f"height={float(height.group(1))}")
    elif re.search(r"\b(?:raise|higher|up higher|move (?:the camera )?up)\b", t) and "high=True" not in kw:
        kw.append("raise_by=2.0")
    pan = re.search(r"\bpan (?P<d>left|right)\b", t)
    if pan:
        kw.append(f"pan={20 if pan.group('d') == 'left' else -20}")
    tilt = re.search(r"\btilt (?P<d>up|down)\b", t)
    if tilt:
        kw.append(f"tilt={10 if tilt.group('d') == 'up' else -10}")
    if not kw:
        return None
    cam_names, conf, q = resolver.resolve(t, current, want_camera=True)
    if q:
        return _ask(q)
    cam = cam_names[0]
    steps = [_step("Move the camera", f"RESULT = str(camera_edit({cam!r}, {', '.join(kw)}))",
                   [{"type": "camera_safe", "object": cam}])]
    if "drone=True" in kw:   # a drone shot drifts: a slow orbit from up there
        steps.append(_step("Let it drift like a drone",
                           f"RESULT = str(camera_move({cam!r}, 'orbit', {subject!r}, start=0, end=None, sweep=35))",
                           [{"type": "camera_frames", "object": cam, "other": subject or ""}]))
    return _plan("Change the camera", steps)


# ---------- objects ----------

def move_with_intent(m, text, current, resolver):
    """'move the villa back', 'move the pool closer to the house': the thing and what belongs to it move together,
    then the scene's relationships are checked (spatial repair takes it from there)."""
    names, q = _target(m.group("obj"), current, resolver)
    if q:
        return _ask(q)
    t = text.lower()
    toward = re.search(r"\b(?:closer to|nearer|next to|toward|towards) (?:the )?(?P<o>.+)$", t)
    if toward:
        others, q = _target(toward.group("o"), current, resolver)
        if q:
            return _ask(q)
        return _plan(f"Move {names[0]} closer to {others[0]}",
                     [_step(f"Move {names[0]} toward {others[0]}",
                            f"RESULT = str(move_with({names[0]!r}, toward={others[0]!r}))",
                            [{"type": "near", "object": names[0], "other": others[0], "max": 6.0}])])
    d = re.search(r"\b(?P<dir>back|backward|backwards|forward|forwards|left|right|away|closer)\b(?: by )?"
                  r"(?:" + _NUM + r"\s*(?:m|metres|meters))?", t)
    if not d:
        return None
    dist = float(d.group(2)) if d.group(2) else None
    return _plan(f"Move {names[0]} {d.group('dir')}",
                 [_step(f"Move {names[0]} {d.group('dir')}",
                        f"RESULT = str(move_with({names[0]!r}, direction={d.group('dir')!r}, distance={dist!r}))")])


def cinematic_intent(m, text, current, resolver):
    """'make it cinematic' / 'create a cinematic shot' with nothing more specific: a slow push-in on the main
    subject, depth of field, a touch of haze, a filmic contrast — the user asked for the treatment."""
    things = current.get("things") or []
    main = next((t["name"] for t in things if "main" in str(t.get("role") or "")), None) or \
        (max(things, key=lambda t: (t.get("size") or [0, 0])[0] * (t.get("size") or [0, 0])[1])["name"]
         if things else None)
    steps = [_step("A slow push-in", f"RESULT = str(camera_move('Camera', 'push_in', {main!r}, start=0, end=8))",
                   [{"type": "camera_frames", "object": "Camera", "other": main or ""}]),
             _step("A filmic look", "RESULT = cinematic_look()")]
    if not (current.get("env") or {}).get("set", {}).get("fog"):
        steps.append(_step("A touch of atmosphere", "RESULT = fog('haze', density=0.004)"))
    return _plan("Make it cinematic", steps)


INTENTS = [
    (re.compile(r"\b(?:fog|foggy|mist|misty|haze|hazy|smog|ground fog|fade into the)\b", re.I), fog_edit),
    (re.compile(r"\b(?:make|set|change|turn|switch) (?:it|the scene|the time|everything)? ?(?:to |into )?(?:a )?"
                r"(?P<t>sunrise|sunset|night ?time|night|midnight|dusk|dawn|evening|twilight|day ?time|day|daylight|"
                r"morning|afternoon|golden hour|noon|midday|overcast)\b", re.I), time_edit),
    (re.compile(r"\b(?:rain|rainy|raining|snow|snowy|storm|stormy|thunder|clouds|cloudy|overcast|drizzle|weather|"
                r"sunny)\b", re.I), weather_edit),
    (re.compile(r"\b(?:the )?(?P<w>ocean|sea|waves|pool|pool water|water|lake|river|waterfall|pond|stream)\b.*\b(?:"
                r"calmer|stronger|rougher|bigger|smaller|faster|slower|gentler|loop|wilder|higher|lower)\b|\b(?:slow "
                r"down|speed up|calm) (?:the )?(?P<w2>ocean|sea|waves|water|waterfall|river)\b", re.I), None),
    (re.compile(r"\b(?:trees|palms|plants|vegetation|leaves|grass|bushes|foliage)\b.*\b(?:move|sway|wave|blow)\b",
                re.I), vegetation_edit),
    (re.compile(r"\bwind(?:y|ier)?\b|\bbreeze\b", re.I), wind_edit),
    (re.compile(r"\b(?:stop|pause|freeze|remove|delete|clear|resume|play|restart|unpause|get rid of)\b (?:all )?"
                r"(?P<obj>the animations?|animations?|all animation|everything|motion|the motion|the [a-z ]+?)"
                r"(?: (?:moving|animation|motion))?$", re.I), animation_edit),
    (re.compile(r"\b(?:add|put|place) (?:some )?lights? (?:along|on|beside|by|to|lining) (?:the )?(?P<p>.+)$", re.I),
     path_lights_edit),
    (re.compile(r"\b(?:add|put in|install|give it) (?:some )?(?:the )?(?P<obj>[a-z ]+?) lights?$", re.I),
     lambda m, text, current, resolver: lights_edit(m, text + " on", current, resolver)),
    (re.compile(r"\badd (?:a )?(?:soft |warm |gentle )?(?:fill |rim |key )?light from\b", re.I), fill_light_edit),
    (re.compile(r"\b(?:turn|switch|put) (?:on|off) (?P<obj>.*?lights?)\b|\b(?:turn|switch) (?P<obj2>.+?) (?:on|off)$|"
                r"\b(?:make|turn) (?:the )?(?P<obj3>[a-z ]*?(?:lights?|windows?|storefront|shop|street lamps?|"
                r"lamps?))\b (?:brighter|dimmer|darker|warmer|cooler|on|off)|"
                r"\b(?:warm|cool|brighten|dim) (?:up |down )?(?:the )?(?P<obj4>[a-z ]*?lights?)\b", re.I), None),
    (re.compile(r"\b(?:camera|lens|shot|angle|view|drone|aerial|close ?up|zoom)\b|\bshow (?:me )?(?:the )?.+ from\b",
                re.I), camera_edit_intent),
    (re.compile(r"\bmove (?:the )?(?P<obj>.+?) (?:back|backward|backwards|forward|forwards|left|right|away|closer"
                r"(?: to)?|nearer|toward|towards|next to)\b", re.I), move_with_intent),
    (re.compile(r"\b(?:make|turn|paint|colou?r|change)\b.*\b(?:walls?|roof|windows?|door|trim|grass|lawn|ground|"
                r"water|leaves|foliage|trunks?|wood|floor|deck|pavement|sidewalk|road|street|asphalt|concrete|sign|"
                r"awning|cushions|sofa|facade)\b", re.I), material_edit_intent),
    (re.compile(r"\b(?:make it|make the scene|make this|give it a|create a) (?:look |feel )?(?:more )?cinematic"
                r"(?: shot| look| feel)?$|^cinematic$", re.I), cinematic_intent),
]


def _lights_dispatch(m, text, current, resolver):
    obj = m.group("obj") or m.group("obj2") or m.group("obj3") or m.group("obj4") or ""
    dark = ((current.get("env") or {}).get("set") or {}).get("time") in ("dusk", "night")
    if re.search(r"\bwindows?\b", obj) and not dark and re.search(r"\b(?:darker|lighter|reflective)\b", text, re.I):
        return material_edit_intent(m, text, current, resolver)   # by day "darker windows" is the glass itself
    obj = re.sub(r"\b(?:lights?|windows?)\b", "", obj).strip() or ""

    class _M:
        def groupdict(self):
            return {"obj": obj}
    return lights_edit(_M(), text, current, resolver)


def _water_dispatch(m, text, current, resolver):
    w = m.group("w") or m.group("w2") or "water"
    w = {"waves": "ocean", "pool water": "pool"}.get(w.lower(), w)

    class _M:
        def group(self, k):
            return w
    return water_edit(_M(), text, current, resolver)


INTENTS = [(rx, h if h is not None else (_water_dispatch if "calmer" in rx.pattern else _lights_dispatch))
           for rx, h in INTENTS]


def plan(text: str, current: dict, resolver):
    """The edit plan for `text` on the current scene, a question, or None (not an edit this table knows: the
    asset, direction and general planners take it)."""
    text = " ".join(str(text or "").split()).rstrip(".!")
    if not text:
        return None
    for rx, handler in INTENTS:
        m = rx.search(text)
        if not m:
            continue
        result = handler(m, text, current, resolver)
        if result is not None:
            return result
    return None
