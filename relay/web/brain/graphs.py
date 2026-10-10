"""Graphs of y = ax^2 + bx + c (also straight lines): understand the request, work out the key points, and describe them.

The picture itself is drawn by the window (graph.js). This module only turns "graph two x squared minus four x plus one"
or "draw a parabola with a 1, b minus 2, c 3" into numbers, and works out the vertex, the roots and the intercepts.
"""
import math
import re

import functions

_VERB = re.compile(r"\b(?:graph(?:ing|ed)?|plot(?:ting|ted)?|draw(?:ing|n|s)?|drew|sketch(?:ing|ed)?|paint(?:ing|ed)?|chart|visuali[sz]e|illustrate|make|create|show)\b")
_STRONG = re.compile(r"\b(?:graph|plot|chart|curve|function|parabola|quadratic|equation|sketch|drawing|picture)\b")
_STRONG_NOUN = re.compile(r"\b(?:graph|plot|chart|curve|function|parabola|quadratic|equation)\b")
_LEAD_WORDS = {"", "hey", "jarvis", "jervis", "ok", "okay", "please", "can", "could", "would", "you", "now", "then", "and", "just", "lets", "let", "s",
               "i", "want", "need", "to", "wanna", "like", "me", "also", "so", "well", "yes", "yeah", "no"}


def _is_command(prefix: str) -> bool:
    """True if what comes before the verb is only politeness ("hey jarvis can you ..."), so it is an order and not a story about drawing."""
    return all(word in _LEAD_WORDS for word in re.sub(r"[^a-z ]", " ", prefix).split())


_RESHOW = re.compile(
    r"\b(?:show|open|bring\s+up|pull\s+up|display|see|reopen|put\s+up|look\s+at|let\s+me\s+see|go\s+back\s+to)\b.*\b(?:graph|graphs|plot|chart|drawing|parabola|curve|picture)\b.*\b(?:again|last|previous|earlier|before|back|once\s+more|one\s+more\s+time|next|first)\b"
    r"|\b(?:the\s+)?(?:previous|last|next|earlier|first)\s+(?:graph|plot|chart|drawing)\b|\b(?:graph|plot|drawing)\s+(?:again|from\s+before)\b"
    r"|\bshow\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?graphs\b")
_CLOSE = re.compile(r"\b(?:close|hide|dismiss|remove|clear|exit)\b.{0,20}\b(?:graph|chart|plot|parabola|picture|drawing)\b")


def _from_letters(text: str):
    """"a 2, b minus 3, c 1" / "a=2 b=-3 c=1" -> (2, -3, 1). Needs at least a; a missing b or c is 0."""
    values = {}
    for letter in "abc":
        m = re.search(rf"(?<![a-z]){letter}\s*(?:=|is|of)?\s*(-?\s*\d+(?:\.\d+)?)(?![a-z])", text.replace("- ", "-"))
        if m:
            values[letter] = float(m.group(1).replace(" ", ""))
    if "a" in values and len(values) >= 2:
        return values["a"], values.get("b", 0.0), values.get("c", 0.0)
    return None


def parse_request(text: str, expecting: bool = False):
    """None if this isn't about graphing, else one of:
    {"action": "close"}, {"action": "ask"} (no equation given), {"action": "unsupported"} (not a function of x),
    {"action": "unclear"} (a word or symbol that isn't math), {"action": "graph", "a", "b", "c"} (a quadratic or a line),
    {"action": "function", "ast": tree} (anything else), {"action": "several", "requests": [...], "unread": n} (more than
    one function asked for at once: "graph y = x^2 and g = x + 1").
    expecting: Jarvis has just asked for the equation, so a message that is only a formula is the answer to that."""
    # "compare y = x^2 and y = 2x": the two of them on one graph
    text = re.sub(r"^(\s*(?:(?:hey |ok |okay )?(?:jarvis|jervis)[, ]+)?(?:(?:please|can you|could you)\s+)*)compare\s+(?:the\s+)?"
                  r"(?:(?:graphs?|functions?|curves?|lines?)\s+(?:of\s+)?)?", r"\1graph ", text or "", flags=re.I)
    request = _parse_one(text)
    if request is None:
        # A formula on its own, with no "graph" or "draw": the answer to "tell me the equation", or plainly a function
        # written out ("y = 2x + 3", "y = x^2 and y = x + 1").
        n = functions.normalize(text)
        if n and not _VERB.search(n) and (expecting or re.match(r"^y\s*=", n)) and "x" in functions._tokenize(n):
            answer = parse_request(f"graph {text}")
            if answer and answer["action"] in ("graph", "function", "several"):
                return answer
        return None
    several = _parse_several(text) if _BETWEEN.search(functions.normalize(text)) else None
    if several and (request["action"] in ("unclear", "unsupported") or (not several["unread"] and len(several["requests"]) > 1)):
        return several   # "sine of x and cosine of x" is two curves, not one multiplied by the other
    return request


# what stands between two functions asked for together, and the words around them that aren't part of either
_BETWEEN = re.compile(r"\s+(?:and|&|vs\.?|versus|against|together with|along with|with|compared (?:to|with))\s+")
_TOGETHER = re.compile(r"\b(?:(?:on|in) (?:the )?same (?:graph|axes|axis|plane|plot|picture|chart|screen|window)|together|side by side|"
                       r"both|the (?:two )?(?:functions|graphs|curves|lines)(?: of)?|two functions)\b")


def _parse_several(text: str):
    """"graph y = x^2 and g = x + 1": each function between the "and"s, read on its own. A function under another
    name ("g = …", "h(x) = …") is still a function of x."""
    n = functions.normalize(text)
    verb = _VERB.search(n)
    if not verb:
        return None
    parts = [p.strip() for p in _BETWEEN.split(" " + _TOGETHER.sub(" ", n[verb.end():]) + " ") if p.strip()]
    if len(parts) < 2:
        return None
    found, names, unread = [], [], 0
    for part in parts[:4]:
        named = re.match(r"^(?:then\s+|also\s+)?([a-df-wz])\s*(?:\(\s*x\s*\))?\s*=\s*(?=[^=]*$)", part)
        one = _parse_one(f"graph {'y = ' + part[named.end():] if named else part}")
        if one and one["action"] in ("graph", "function"):
            found.append(one)
            names.append(named.group(1) if named else "")
        else:
            unread += 1
    # the names they were given ("g = x + 1"); the rest are f, g, h, k in order
    free = [letter for letter in NAMES if letter not in names]
    names = [name if name and names.index(name) == i else free.pop(0) for i, name in enumerate(names)]
    return {"action": "several", "requests": found, "names": names, "unread": unread} if found else None


NAMES = "fghkpqrs"


def _parse_one(text: str):
    n = functions.normalize(text)
    if not n:
        return None
    if _CLOSE.search(n):
        return {"action": "close"}
    if _RESHOW.search(n) and _is_command(n[:re.search(r"\b(?:show|open|bring|pull|display|see|reopen|put|look|let|go|previous|last|next|earlier|first|graph|plot|drawing)\b", n).start()]):
        which = "first" if re.search(r"\bfirst\b", n) else "prev" if re.search(r"\b(?:previous|before|earlier|back)\b", n) else "next" if re.search(r"\bnext\b", n) else "last"
        return {"action": "reshow", "which": which}
    verb = _VERB.search(n)
    if not verb:
        return None
    if verb.group(0) in ("make", "create", "show") and not _STRONG.search(n):
        return None
    rest = n[verb.end():]
    letters = _from_letters(rest) if re.search(r"\b(?:parabola|quadratic|coefficients?)\b|\ba\s*=?\s*-?\d", rest) else None
    if letters:
        return {"action": "graph", "a": letters[0], "b": letters[1], "c": letters[2]}
    tokens = functions._tokenize(rest)
    kept = [t for t in tokens if t not in functions._FILLER]
    shape = next((t for t in kept if t in functions._SHAPES), None)
    is_math = ("x" in kept or "^" in kept or shape is not None or any(t in functions._FUNCTIONS or re.fullmatch(r"logb\d+|log10", t) for t in kept)
               or ("y" in kept and "=" in kept))
    if not is_math:
        # "what is 2x + 6 = 0, draw the graph" / "y = x^2, plot it": the formula came first, then the order to draw it.
        before = re.sub(r"(?:\s|[,.;:!?]|\b(?:and|then|also|now|so|please|can you|could you|would you)\b)*$", "", n[:verb.start()])
        before = re.sub(r"^(?:(?:hey |ok |okay )?(?:jarvis|jervis)\s+)?(?:what(?:'s| is| are)(?: the answer (?:to|of))?|solve|calculate|"
                        r"compute|find|work out|tell me)\b\s*", "", before).strip()
        # …or just "y = 2x + 3 graph", with the order as the last word
        if before and not kept and (not rest.strip(" .") or _STRONG_NOUN.search(rest) or re.search(r"\b(?:it|this|that|them)\b", rest)) \
                and "x" in functions._tokenize(before):
            request = _parse_one(f"graph {before}")
            if request and request["action"] in ("graph", "function"):
                return {**request, "solve": before if "=" in before and not re.search(r"\by\b", before) else None}
        # "draw the function", "graph it", "plot that": no formula, so it means the one talked about last (the app knows which).
        if not kept and _is_command(n[:verb.start()]) and (_STRONG_NOUN.search(n) or re.search(r"\b(?:it|this|that|them)\b", rest)):
            return {"action": "last", "explicit": bool(_STRONG_NOUN.search(n))}
        return None
    if shape is not None and len(kept) == 1:
        tree = functions._SHAPES[shape]
        return {"action": "last", "explicit": True} if tree is None else {"action": "function", "ast": tree}   # "plot the parabola": the one just talked about
    if len(kept) == 1 and (kept[0] in functions._FUNCTIONS or re.fullmatch(r"logb\d+|log10", kept[0])):
        return {"action": "function", "ast": functions._Parser._call(kept[0], ["x"])}     # "the sine wave" = sin(x)
    kept = [t for t in kept if t not in functions._SHAPES]
    if any(t[0].isalpha() and t not in functions._FUNCTIONS and t not in functions._CONSTANTS and t not in ("x", "y")
           and not re.fullmatch(r"logb\d+|log10", t) for t in kept):
        return {"action": "unclear"}
    if "=" in kept:
        cut = kept.index("=")
        left, right = kept[:cut], kept[cut + 1:]
        if left == ["y"]:
            body = right
        elif right == ["y"]:
            body = left
        elif "y" in kept:
            return {"action": "unsupported"}
        else:
            body = None
        try:
            if body is not None:
                tree = functions.parse(body)
            else:
                tree = ["sub", functions.parse(left), functions.parse(right)]
        except functions.ParseError:
            return {"action": "unclear"}
    else:
        if "y" in kept:
            return {"action": "unsupported"}
        if not kept:
            return {"action": "ask"}
        try:
            tree = functions.parse(kept)
        except functions.ParseError:
            return {"action": "unclear"}
    return request_from_tree(tree)


def request_from_tree(tree):
    """A graph request for a function tree: a quadratic or line (exact facts) or any other function."""
    quadratic = functions.as_quadratic(tree)
    if quadratic is not None:
        return {"action": "graph", "a": quadratic[0], "b": quadratic[1], "c": quadratic[2], "ast": tree}
    return {"action": "function", "ast": tree}


# ---------- the numbers behind the picture ----------
def _clean(x: float) -> float:
    x = round(x + 0.0, 6)
    return 0.0 if x == 0 else x


def fmt(x: float, unicode_minus: bool = False) -> str:
    text = f"{_clean(x):.4f}".rstrip("0").rstrip(".")
    text = "0" if text in ("-0", "") else text
    return text.replace("-", "−") if unicode_minus else text


def _terms(a: float, b: float, c: float, superscript: bool, minus: str) -> str:
    out = []
    for coef, tail in ((a, "x²" if superscript else "x^2"), (b, "x"), (c, "")):
        if coef == 0:
            continue
        digits = fmt(abs(coef))
        body = tail if (tail and digits == "1") else digits + tail
        sign = minus if coef < 0 else "+"
        out.append(f"{'' if not out and sign == '+' else (sign if not out else ' ' + sign + ' ')}{body}" if not out else f"{sign} {body}")
    joined = " ".join(out) if out else "0"
    return joined.replace(f"{minus} ", minus, 1) if joined.startswith(f"{minus} ") else joined


def equation_plain(a: float, b: float, c: float) -> str:
    return "y = " + _terms(a, b, c, True, "−")


def equation_latex(a: float, b: float, c: float) -> str:
    return "y = " + _terms(a, b, c, False, "-")


def facts(a: float, b: float, c: float) -> dict:
    """Everything the window needs to draw and label the graph."""
    a, b, c = _clean(a), _clean(b), _clean(c)
    info = {"a": a, "b": b, "c": c, "plain": equation_plain(a, b, c), "latex": equation_latex(a, b, c),
            "yint": c, "roots": [], "complex": None, "vertex": None, "opens": None, "disc": None}
    if a == 0:
        info["kind"] = "line"
        if b != 0:
            info["roots"] = [_clean(-c / b)]
        return info
    info["kind"] = "parabola"
    vx = -b / (2 * a)
    info["vertex"] = [_clean(vx), _clean(a * vx * vx + b * vx + c)]
    info["opens"] = "up" if a > 0 else "down"
    d = b * b - 4 * a * c
    info["disc"] = _clean(d)
    if d > 1e-12:
        r = math.sqrt(d)
        info["roots"] = sorted([_clean((-b - r) / (2 * a)), _clean((-b + r) / (2 * a))])
    elif abs(d) <= 1e-12:
        info["roots"] = [_clean(vx)]
    else:
        info["complex"] = [_clean(vx), _clean(math.sqrt(-d) / (2 * abs(a)))]
    return info


def _say(x: float) -> str:
    return ("negative " + fmt(-x)) if x < 0 else fmt(x)


def describe(info: dict) -> str:
    """The reply: a spoken-style first sentence (no symbols), then the key facts as a list for the screen."""
    roots = info["roots"]
    if info["kind"] == "line":
        slope = info["b"]
        lead = ("Here's your line. " + ("It goes up as you move right" if slope > 0 else "It goes down as you move right" if slope < 0 else "It is flat")
                + (f", and it crosses the x-axis at x equals {_say(roots[0])}." if roots else "."))
        lines = [f"- **Equation:** ${info['latex']}$", f"- **Slope:** ${fmt(info['b'])}$", f"- **Y-intercept:** $(0,\\ {fmt(info['yint'])})$"]
        if roots:
            lines.append(f"- **X-intercept:** $({fmt(roots[0])},\\ 0)$")
        return lead + "\n\n" + "\n".join(lines)
    vx, vy = info["vertex"]
    extreme = "lowest" if info["opens"] == "up" else "highest"
    if len(roots) == 2:
        crossing = f"it crosses the x-axis at x equals {_say(roots[0])} and x equals {_say(roots[1])}"
    elif len(roots) == 1:
        crossing = f"it touches the x-axis at x equals {_say(roots[0])}"
    else:
        crossing = "it never crosses the x-axis"
    lead = (f"Here's your parabola. It opens {'upward' if info['opens'] == 'up' else 'downward'}, its {extreme} point is at "
            f"x equals {_say(vx)} and y equals {_say(vy)}, and {crossing}.")
    lines = [f"- **Equation:** ${info['latex']}$",
             f"- **Vertex:** $({fmt(vx)},\\ {fmt(vy)})$",
             f"- **Axis of symmetry:** $x = {fmt(vx)}$",
             f"- **Y-intercept:** $(0,\\ {fmt(info['yint'])})$"]
    if len(roots) == 2:
        lines.append(f"- **Roots:** $x = {fmt(roots[0])}$ and $x = {fmt(roots[1])}$")
    elif len(roots) == 1:
        lines.append(f"- **Root:** $x = {fmt(roots[0])}$ (a double root)")
    else:
        re_part, im_part = info["complex"]
        lines.append(f"- **Roots:** none on the graph (complex: $x = {fmt(re_part)} \\pm {fmt(im_part)}i$)")
    return lead + "\n\n" + "\n".join(lines)


def describe_function(info: dict) -> str:
    """The reply for a general function: a spoken-style lead (no symbols), then the key facts as a list for the screen."""
    roots, extrema = info["roots"], info["extrema"]
    maxima = [e for e in extrema if e["type"] == "max"]
    minima = [e for e in extrema if e["type"] == "min"]
    def say(x):
        return _say(round(x, 2) + 0.0)

    parts = []
    if not roots:
        parts.append("it never crosses the x-axis here")
    elif len(roots) == 1:
        parts.append(f"it crosses the x-axis at x equals {say(roots[0])}")
    elif len(roots) == 2:
        parts.append(f"it crosses the x-axis at x equals {say(roots[0])} and x equals {say(roots[1])}")
    else:
        parts.append(f"it crosses the x-axis {len(roots)} times in this view")
    if len(extrema) == 1:
        e = extrema[0]
        parts.append(f"it has a {'peak' if e['type'] == 'max' else 'dip'} at x equals {say(e['x'])}, where y is {say(e['y'])}")
    elif len(extrema) == 2 and len(maxima) == 1:
        parts.append(f"it peaks at {say(maxima[0]['y'])} and dips to {say(minima[0]['y'])}")
    elif extrema:
        parts.append(f"it has {len(extrema)} turning points")
    if info["poles"]:
        parts.append("it has " + ("a vertical asymptote" if len(info["poles"]) == 1 else "vertical asymptotes"))
    lead = f"Here's your {info['kindName'].lower()} function. " + ("Notably, " + "; ".join(parts[:2]) + "." if parts else "")
    lines = [f"- **Function:** ${info['latex']}$", f"- **Type:** {info['kindName']}"]
    if info["yint"] is not None:
        lines.append(f"- **Y-intercept:** $(0,\\ {fmt(info['yint'])})$")
    if roots:
        shown = ", ".join(f"${fmt(r)}$" for r in roots[:6]) + (f" and {len(roots) - 6} more" if len(roots) > 6 else "")
        lines.append(f"- **X-intercepts:** {shown}")
    for label, group in (("Local maxima", maxima), ("Local minima", minima)):
        if group:
            shown = ", ".join(f"$({fmt(e['x'])},\\ {fmt(e['y'])})$" for e in group[:4]) + (f" and {len(group) - 4} more" if len(group) > 4 else "")
            lines.append(f"- **{label}:** {shown}")
    if info["poles"]:
        lines.append("- **Vertical asymptotes:** " + ", ".join(f"$x = {fmt(p)}$" for p in info["poles"][:5]))
    if info["horizontal"]:
        lines.append("- **Horizontal asymptote:** " + ", ".join(f"$y = {fmt(h)}$" for h in info["horizontal"]))
    if info["domain"]:
        lo, hi, lo_open, hi_open = info["domain"]
        greater, less = ("\\gt" if lo_open else "\\ge"), ("\\lt" if hi_open else "\\le")
        if lo is not None and hi is not None:
            text = f"${fmt(lo)} {'\\lt' if lo_open else '\\le'} x {less} {fmt(hi)}$"
        elif lo is not None:
            text = f"$x {greater} {fmt(lo)}$"
        else:
            text = f"$x {less} {fmt(hi)}$"
        lines.append("- **Domain:** " + text)
    return lead.strip() + "\n\n" + "\n".join(lines)


def build_function(tree) -> dict:
    """Everything the window needs to draw a general function."""
    analysis = functions.analyze(tree)
    view = functions.build_view(tree, analysis)
    return functions.describe_function(tree, analysis, view)


def build(request: dict) -> tuple:
    """(what the window draws, what Jarvis says about it) for one "graph" or "function" request."""
    if request["action"] == "function":
        info = build_function(request["ast"])
        return info, describe_function(info)
    info = facts(request["a"], request["b"], request["c"])
    return info, describe(info)


def describe_several(infos: list, unread: int) -> str:
    """What Jarvis says when only one of the functions asked for together could be read."""
    name = infos[0].get("plain") or "the function"
    return (f"I could only read one of those as a function of x, so I drew {name}. "
            "Give me the other one again, like: graph y equals x plus 1.")


# ---------- two functions on the same axes: each one, and how they relate ----------
def _at(tree, x: float) -> float:
    try:
        return functions.evaluate(tree, x)
    except (ValueError, ZeroDivisionError, OverflowError):
        return float("nan")


def _meetings(f, g):
    """Where two curves meet, as [{"x", "y"}]: exactly for lines and parabolas, found by search for anything else.
    None when they are the same function everywhere."""
    difference = ["sub", f, g]
    quadratic = functions.as_quadratic(difference)
    if quadratic is not None:
        a, b, c = quadratic
        if a == 0 and b == 0:
            return None if c == 0 else []
        if a == 0:
            xs = [-c / b]
        else:
            d = b * b - 4 * a * c
            xs = [] if d < -1e-12 else [-b / (2 * a)] if abs(d) <= 1e-12 else sorted([(-b - math.sqrt(d)) / (2 * a), (-b + math.sqrt(d)) / (2 * a)])
    else:
        xs = functions.analyze(difference)["roots"]
    points = []
    for x in xs:
        y = _at(f, x)
        if math.isfinite(y):
            points.append({"x": _clean(x), "y": _clean(y)})
    return points


def _kind_words(info: dict) -> str:
    if info["kind"] == "line":
        return "a straight line"
    if info["kind"] == "parabola":
        return "a parabola"
    name = info["kindName"].lower()
    return f"{'an' if name[:1] in 'aeiou' else 'a'} {name} function"


def _point(p: dict, latex: bool = True) -> str:
    return f"$({fmt(p['x'])},\\ {fmt(p['y'])})$" if latex else f"({fmt(p['x'], True)}, {fmt(p['y'], True)})"


def relate(first: dict, second: dict, within: tuple = None) -> dict:
    """How two functions stand to each other: where they meet, which is higher where, the area they enclose, and what
    is special about the pair (parallel, perpendicular, tangent, the same shape moved, mirror images).
    within: (lowest x, highest x) to look at, for curves that go on meeting for ever (sine and cosine)."""
    f, g, fn, gn = first["ast"], second["ast"], first["name"], second["name"]
    meet = _meetings(f, g)
    if meet and within:
        meet = [p for p in meet if within[0] <= p["x"] <= within[1]]
    out = {"same": meet is None, "meet": meet or [], "notes": [], "higher": [], "area": None}
    if out["same"]:
        out["notes"].append(f"{fn} and {gn} are the same function: one curve lies exactly on the other")
        return out
    kinds = (first["kind"], second["kind"])
    if kinds == ("line", "line"):
        m1, m2 = first["b"], second["b"]
        if m1 == m2:
            apart = abs(first["c"] - second["c"]) / math.sqrt(1 + m1 * m1)
            out["notes"].append(f"The lines are parallel: both have slope {fmt(m1, True)}, so they never meet. They stay {fmt(apart, True)} apart")
        elif abs(m1 * m2 + 1) < 1e-9:
            out["notes"].append("The lines are perpendicular: they cross at a right angle (their slopes multiply to −1)")
        else:
            angle = math.degrees(math.atan(abs((m1 - m2) / (1 + m1 * m2)))) if abs(1 + m1 * m2) > 1e-12 else 90.0
            out["notes"].append(f"The lines cross at an angle of {fmt(round(angle, 1), True)}°")
    elif set(kinds) == {"line", "parabola"}:
        count = len(out["meet"])
        out["notes"].append("The line cuts through the parabola at two points" if count == 2
                            else "The line is tangent to the parabola: it touches it at exactly one point" if count == 1
                            else "The line never touches the parabola")
    elif kinds == ("parabola", "parabola"):
        if first["a"] == second["a"]:
            dx, dy = second["vertex"][0] - first["vertex"][0], second["vertex"][1] - first["vertex"][1]
            moves = [f"{fmt(abs(dx), True)} to the {'right' if dx > 0 else 'left'}" if dx else "", f"{fmt(abs(dy), True)} {'up' if dy > 0 else 'down'}" if dy else ""]
            out["notes"].append(f"The parabolas have the same shape: {gn} is {fn} moved {' and '.join(m for m in moves if m)}")
        elif first["a"] == -second["a"]:
            out["notes"].append("The parabolas are equally wide and open in opposite directions")
        else:
            wider = fn if abs(first["a"]) < abs(second["a"]) else gn
            out["notes"].append(f"{wider} is the wider parabola")
    # the same curve moved straight up or down, or a mirror image
    difference = functions.as_quadratic(["sub", f, g])
    if difference is not None and difference[0] == 0 and difference[1] == 0 and difference[2] != 0 and kinds != ("line", "line") \
            and not (kinds == ("parabola", "parabola") and first["a"] == second["a"]):
        c = difference[2]
        out["notes"].append(f"{gn} is {fn} moved {fmt(abs(c), True)} {'down' if c > 0 else 'up'}: they are always exactly that far apart")
    samples = (-2.3, -0.7, 0.4, 1.9, 3.1)
    pairs = [(_at(f, x), _at(g, x), _at(g, -x)) for x in samples]
    if all(math.isfinite(v) for row in pairs for v in row):
        if all(abs(fv + gv) < 1e-9 * (1 + abs(fv)) for fv, gv, _ in pairs) and any(abs(fv) > 1e-9 for fv, _, _ in pairs):
            out["notes"].append(f"They are mirror images of each other across the x-axis ({gn} is −{fn})")
        elif all(abs(fv - gm) < 1e-9 * (1 + abs(fv)) for fv, _, gm in pairs) and any(abs(fv - gv) > 1e-9 for fv, gv, _ in pairs):
            out["notes"].append("They are mirror images of each other across the y-axis")
    # which one is higher, stretch by stretch between the meeting points (and the places either one breaks off)
    cuts = [p["x"] for p in out["meet"]]
    breaks = [x for info in (first, second) for x in info.get("poles") or [] if not within or within[0] <= x <= within[1]]
    edges = [None] + sorted(set(cuts) | set(breaks)) + [None]
    for lo, hi in zip(edges, edges[1:]):
        x = (lo + hi) / 2 if lo is not None and hi is not None else (hi - 1 if hi is not None else lo + 1 if lo is not None else 0.37)
        fv, gv = _at(f, x), _at(g, x)
        if math.isfinite(fv) and math.isfinite(gv) and fv != gv:
            who = fn if fv > gv else gn
            if out["higher"] and out["higher"][-1]["who"] == who and out["higher"][-1]["to"] == lo:
                out["higher"][-1]["to"] = hi      # they only touch here: the same one stays on top
            else:
                out["higher"].append({"who": who, "from": lo, "to": hi})
    # the area they enclose, between the first and the last meeting point
    if 2 <= len(cuts) <= 4 and cuts[-1] - cuts[0] < 200 and not any(cuts[0] < x < cuts[-1] for x in breaks):
        steps, lo, hi = 2000, cuts[0], cuts[-1]
        width = (hi - lo) / steps
        values = [abs(_at(f, lo + i * width) - _at(g, lo + i * width)) for i in range(steps + 1)]
        if all(math.isfinite(v) for v in values):
            out["area"] = _clean(width / 3 * (values[0] + values[-1] + 4 * sum(values[1:-1:2]) + 2 * sum(values[2:-1:2])))
    return out


def _joint_view(infos: list, meet: list, within: tuple = None) -> dict:
    """The part of the plane where everything worth seeing about all of them is: their own key points and where they meet."""
    near = (lambda x: within[0] <= x <= within[1]) if within else (lambda x: abs(x) <= 60)
    xs = [0.0] + [p["x"] for p in meet if near(p["x"])]
    for info in infos:
        xs += [r for r in info.get("roots") or [] if near(r)]
        if info.get("vertex") and near(info["vertex"][0]):
            xs.append(info["vertex"][0])
        xs += [e["x"] for e in info.get("extrema") or [] if near(e["x"])]
    lo, hi = min(xs), max(xs)
    pad = max((hi - lo) * 0.45, 2.5)
    xmin, xmax = (within if within else (lo - pad, hi + pad))
    key = [0.0] + [p["y"] for p in meet if abs(p["x"]) <= 60]
    for info in infos:
        key += [v for v in (_at(info["ast"], x) for x in xs) if math.isfinite(v)]
    key_lo, key_hi = min(key), max(key)
    room = max(key_hi - key_lo, (xmax - xmin) * 0.42)
    seen = [v for info in infos for v in (_at(info["ast"], xmin + (xmax - xmin) * i / 240) for i in range(241)) if math.isfinite(v)]
    ymin = min(key_lo, max(min(seen, default=key_lo), key_lo - room * 1.15))
    ymax = max(key_hi, min(max(seen, default=key_hi), key_hi + room * 1.15))
    ypad = max((ymax - ymin) * 0.1, 0.4)
    return {"xmin": _clean(xmin), "xmax": _clean(xmax), "ymin": _clean(ymin - ypad), "ymax": _clean(ymax + ypad)}


def _higher_words(higher: list, latex: bool) -> str:
    def stretch(h):
        num = lambda v: (f"${fmt(v)}$" if latex else fmt(v, True))
        if h["from"] is None and h["to"] is None:
            return "everywhere"
        if h["from"] is None:
            return f"for x below {num(h['to'])}"
        if h["to"] is None:
            return f"for x above {num(h['from'])}"
        return f"between x = {num(h['from'])} and x = {num(h['to'])}"
    if len(higher) > 5:
        return "they take turns, swapping at every meeting point"
    by_name = {}
    for h in higher:
        by_name.setdefault(h["who"], []).append(stretch(h))
    return "; ".join(f"{name} is higher {' and '.join(parts)}" for name, parts in by_name.items())


def build_pair(requests: list, names: list = None) -> dict:
    """Everything the window needs to draw two (or more) functions on the same axes, each in its own colour, with the
    points where they meet marked, and everything to say about each of them and about how they relate."""
    names = list(names or NAMES[:len(requests)])
    infos = []
    for request, name in zip(requests, names):
        info, _ = build(request)
        infos.append({**info, "ast": request["ast"], "name": name,
                      "label": info["plain"].replace("y =", f"{name}(x) =", 1), "latexLabel": info["latex"].replace("y =", f"{name}(x) =", 1)})
    # a function that goes on for ever (sine, 1/x) already knows the stretch it looks best over: that is where to look
    spans = [(i["view"]["xmin"], i["view"]["xmax"]) for i in infos if i.get("view")]
    within = (max(min(lo for lo, _ in spans), -30.0), min(max(hi for _, hi in spans), 30.0)) if spans else None
    relation = relate(infos[0], infos[1], within) if len(infos) == 2 else None
    meet = list(relation["meet"]) if relation else []
    if relation is None:        # three or four: every pair's meeting points, for the picture
        for i, first in enumerate(infos):
            for second in infos[i + 1:]:
                meet += [p for p in _meetings(first["ast"], second["ast"]) or []
                         if (not within or within[0] <= p["x"] <= within[1]) and p not in meet]
        meet.sort(key=lambda p: p["x"])
    pair = {"kind": "pair", "plain": "  and  ".join(i["label"] for i in infos), "latex": ",\\quad ".join(i["latexLabel"] for i in infos),
            "functions": infos, "meet": meet[:12], "relation": relation, "view": _joint_view(infos, meet, within)}
    chips = [[f"{i['name']}(x)", f"{i['plain'].replace('y = ', '', 1)}  ·  {_kind_words(i).split(' ', 1)[1]}"] for i in infos]
    if relation and relation["same"]:
        chips.append(["Relation", "the same function"])
    else:
        chips.append(["Meet at", "  ,  ".join(_point(p, False) for p in meet[:4]) + (f"  +{len(meet) - 4}" if len(meet) > 4 else "") if meet else "nowhere in view"])
    if relation and not relation["same"]:
        if relation["higher"]:
            chips.append(["Higher", _higher_words(relation["higher"], False)])
        for note in relation["notes"][:2]:
            chips.append(["Relation", note])
        if relation["area"] is not None:
            chips.append(["Area between them", f"≈ {fmt(relation['area'], True)}"])
    pair["chips"] = chips
    return pair


def describe_pair(pair: dict, unread: int = 0) -> str:
    """The reply: a spoken-style lead (no symbols), then everything about each function, then how they relate."""
    infos, relation, meet = pair["functions"], pair["relation"], pair["meet"]
    said = lambda v: _say(round(v, 2) + 0.0)
    lead = f"Here are {'both' if len(infos) == 2 else f'all {len(infos)}'} on one graph. "
    kinds = {_kind_words(i) for i in infos}
    if len(kinds) == 1:      # "f and g are both parabolas"
        lead += (" and ".join([", ".join(i["name"] for i in infos[:-1]), infos[-1]["name"]])
                 + f" are {'both' if len(infos) == 2 else 'all'} {kinds.pop().split(' ', 1)[1]}s. ")
    else:
        lead += ", ".join(f"{i['name']} is {_kind_words(i)}" for i in infos[:-1]) + f" and {infos[-1]['name']} is {_kind_words(infos[-1])}. "
    if relation and relation["same"]:
        lead += "They are the same function, so one curve lies exactly on the other."
    elif not meet:
        lead += "They never meet" + (" in this view." if any(i["kind"] == "function" for i in infos) else ".")
    elif len(meet) == 1:
        lead += f"They meet at one point, where x equals {said(meet[0]['x'])} and y equals {said(meet[0]['y'])}."
    elif len(meet) == 2:
        lead += f"They meet at two points: x equals {said(meet[0]['x'])} and x equals {said(meet[1]['x'])}."
    else:
        lead += f"They meet at {len(meet)} points in this view."
    sections = []
    for info in infos:
        own = describe(info) if info["kind"] in ("line", "parabola") else describe_function(info)
        sections.append(f"### {info['label']}\n" + own.split("\n\n", 1)[1])
    if relation:
        lines = []
        if relation["same"]:
            lines.append("- **The same function:** every point of one is a point of the other.")
        else:
            lines.append("- **Meet at:** " + (", ".join(_point(p) for p in meet[:6]) + (f" and {len(meet) - 6} more" if len(meet) > 6 else "") if meet
                                              else "nowhere" + (" in this view" if any(i["kind"] == "function" for i in infos) else "")))
            if relation["higher"]:
                lines.append("- **Which is higher:** " + _higher_words(relation["higher"], True) + ".")
            lines += [f"- **{note.split(':', 1)[0]}**{':' + note.split(':', 1)[1] if ':' in note else ''}." for note in relation["notes"]]
            if relation["area"] is not None:
                lines.append(f"- **Area between them:** $\\approx {fmt(relation['area'])}$ square units, from the first meeting point to the last.")
        sections.append("### How they relate\n" + "\n".join(lines))
    elif meet:
        sections.append("### Where they meet\n- " + ", ".join(_point(p) for p in meet[:8]))
    text = lead + "\n\n" + "\n\n".join(sections)
    return text + ("\n\nOne more I couldn't read as a function of x." if unread else "")


_ABOUT_THE_PAIR = re.compile(r"\b(?:they|them|the two|both|these|those|the (?:functions|graphs|lines|curves|parabolas)|each other|between them|"
                             r"which (?:one|of|function|line|curve|is))\b")


def pair_followup(text: str, pair: dict):
    """A question about the two functions just drawn ("where do they meet?", "which one is higher?", "what's the area
    between them?", "are they parallel?"), answered from what is already known. None if it isn't one."""
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower()).split())
    relation, meet = pair.get("relation"), pair.get("meet") or []
    if not relation or len(n.split()) > 14 or not _ABOUT_THE_PAIR.search(n):
        return None
    if relation["same"]:
        return relation["notes"][0] + "."
    names = " and ".join(i["name"] for i in pair["functions"])
    if re.search(r"\b(?:meet|meets|intersect|intersects|intersection|intersections|cross|crosses|touch|touches|same point|common)\b", n):
        if not meet:
            return f"{names} never meet" + (" in the part I drew." if any(i["kind"] == "function" for i in pair["functions"]) else ".")
        return f"They meet at {', '.join(_point(p) for p in meet[:6])}."
    if re.search(r"\b(?:higher|above|bigger|greater|larger|on top|lower|below|smaller|under)\b", n):
        return (_higher_words(relation["higher"], True) + ".").capitalize() if relation["higher"] else "Neither is higher: they are the same."
    if re.search(r"\barea\b", n):
        return (f"The area between them, from the first meeting point to the last, is about ${fmt(relation['area'])}$ square units."
                if relation["area"] is not None else "They don't enclose an area: for that they have to meet at two points or more.")
    if re.search(r"\b(?:parallel|perpendicular|tangent|related|relation|relationship|connection|connected|difference|different|same|similar|mirror)\b", n):
        return (". ".join(relation["notes"]) + ".") if relation["notes"] else (
            f"They meet at {len(meet)} point{'s' if len(meet) != 1 else ''}; beyond that they have nothing special in common." if meet
            else "They never meet, and have nothing special in common.")
    return None


ASK_FOR_EQUATION = "Tell me the equation, for example: graph y equals x squared minus 4x plus 3. Or give me a, b and c."
