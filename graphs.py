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
_LEAD_WORDS = {"", "hey", "jervis", "jarvis", "ok", "okay", "please", "can", "could", "would", "you", "now", "then", "and", "just", "lets", "let", "s",
               "i", "want", "need", "to", "wanna", "like", "me", "also", "so", "well", "yes", "yeah", "no"}


def _is_command(prefix: str) -> bool:
    """True if what comes before the verb is only politeness ("hey jervis can you ..."), so it is an order and not a story about drawing."""
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


def parse_request(text: str):
    """None if this isn't about graphing, else one of:
    {"action": "close"}, {"action": "ask"} (no equation given), {"action": "unsupported"} (not a function of x),
    {"action": "unclear"} (a word or symbol that isn't math), {"action": "graph", "a", "b", "c"} (a quadratic or a line),
    {"action": "function", "ast": tree} (anything else)."""
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
