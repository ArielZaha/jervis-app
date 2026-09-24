"""Solve equations in x (linear and quadratic) exactly, with the steps, instead of trusting the AI's arithmetic.

"x in: 3x^2 + 6x + 4", "solve 2x + 4 = 24", "what is x if x squared minus 5x plus 6 equals zero" -> a worksheet in the layout the window
typesets: a spoken-style first line, a Problem, numbered Steps (one formula each) and the highlighted answer.
"""
import math
import re
from fractions import Fraction

import functions

_LEAD = re.compile(r"^\s*(?:hey\s+)?(?:jervis\s+)?(?:please\s+)?(?:(?:the\s+)?x|y)\s+(?:in|is|for|of)\b\s*:?\s*")
_KEYWORD = re.compile(r"\b(?:solve|solution|solutions|roots?|zeros?|find\s+(?:the\s+)?(?:value\s+of\s+)?x|value\s+of\s+x|what\s+is\s+x|whats\s+x|calculate\s+x|for\s+x)\b")
_NOISE = re.compile(r"\b(?:solve|find|calculate|compute|work|out|what|are|what's|whats|tell|me|give|the|value|values|of|for|solutions?|roots?|zeros?|answers?|to|in|is|please|hey|jervis|equation|if|can|you|this|that|help|with|a|an|it|and|then|now)\b")


def _fraction(v: float) -> Fraction:
    return Fraction(v).limit_denominator(10000)


def _latex(fr: Fraction) -> str:
    if fr.denominator == 1:
        return str(fr.numerator)
    sign = "-" if fr < 0 else ""
    return f"{sign}\\frac{{{abs(fr.numerator)}}}{{{fr.denominator}}}"


def _say(v: float) -> str:
    text = _dec(round(v, 2))
    return "negative " + text[1:] if text.startswith("-") else text


def _dec(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _term(coef: Fraction, tail: str, first: bool) -> str:
    if coef == 0:
        return ""
    body = _latex(abs(coef)) if not (abs(coef) == 1 and tail) else ""
    if abs(coef).denominator != 1 and tail:
        body = _latex(abs(coef))
    text = body + tail
    sign = "-" if coef < 0 else "+"
    return (("-" if coef < 0 else "") + text) if first else f" {sign} {text}"


def _poly_latex(a: Fraction, b: Fraction, c: Fraction) -> str:
    out, first = "", True
    for coef, tail in ((a, "x^2"), (b, "x"), (c, "")):
        piece = _term(coef, tail, first) if tail else (_term(coef, "", first) if coef != 0 else "")
        if piece:
            out += piece
            first = False
    return out or "0"


def _split_square(n: int):
    """n = k^2 * m with m square-free: (k, m)."""
    k, m, p = 1, n, 2
    while p * p <= m:
        while m % (p * p) == 0:
            m //= p * p
            k *= p
        p += 1
    return k, m


def _exact_roots(a: Fraction, b: Fraction, disc: Fraction):
    """LaTeX for both roots of ax^2 + bx + c = 0 and a flag if they are complex, in one exact form."""
    p, q = disc.numerator, disc.denominator
    n = abs(p) * q
    k, m = _split_square(n)                      # sqrt(|disc|) = k*sqrt(m)/q
    r = -b / (2 * a)
    s = Fraction(k, q) / (2 * abs(a))            # the coefficient of sqrt(m)
    complex_roots = disc < 0
    radical = ("i" if complex_roots else "") + (f"\\sqrt{{{m}}}" if m != 1 else "")
    if m == 1 and not complex_roots:            # rational roots
        return [_latex(r - s), _latex(r + s)] if s != 0 else [_latex(r)], False
    if m == 1 and complex_roots:
        radical = "i"
    d = math.lcm(r.denominator, s.denominator)
    num_r, num_s = int(r * d), int(s * d)
    g = math.gcd(math.gcd(abs(num_r), abs(num_s)), d) or 1
    num_r, num_s, d = num_r // g, num_s // g, d // g
    lead = "" if num_s == 1 else str(num_s)
    top = (f"{num_r} \\pm " if num_r else "\\pm ") + f"{lead}{radical}"
    if num_r == 0:
        top = f"\\pm {lead}{radical}"
    return [top if d == 1 else f"\\frac{{{top}}}{{{d}}}"], complex_roots


def parse_request(text: str):
    """(left tree, right tree or None) for an equation Jervis should solve, else None."""
    raw = text or ""
    colon = False
    if ":" in raw:                                   # "what is the x: x^2 + 3x - 4": what follows the colon is the problem
        head, _, tail = raw.rpartition(":")
        if re.search(r"\b(?:graph|plot|draw|drew|sketch)", head.lower()):
            return None
        if "x" in functions._tokenize(functions.normalize(tail)):
            raw, colon = tail, True
    n = functions.normalize(raw)
    if not n or "graph" in n or "plot" in n:
        return None
    lead = bool(_LEAD.match(n))
    keyword = lead or colon or bool(_KEYWORD.search(n))
    if not keyword and "=" not in n:
        return None
    body = _LEAD.sub("", n, count=1)
    body = re.sub(r"\b(?:find|calculate|compute|solve|what\s+is|whats|what's|tell\s+me|give\s+me)\s+(?:for\s+)?(?:the\s+)?(?:value\s+of\s+)?x\b\s*(?:if\b|when\b|for\b|in\b|is\b|(?=\s+[\d.(]))", " ", body)
    body = re.sub(r"\bfor\s+x\b", " ", body)
    body = _NOISE.sub(" ", body)
    body = re.sub(r"\b(?:the|zero)\b", lambda m: "0" if m.group(0) == "zero" else " ", body)
    tokens = functions._tokenize(body)
    if "x" not in tokens or any(t[0].isalpha() and t not in ("x", "pi", "e") for t in tokens):
        return None
    if "y" in tokens:
        return None
    if "=" in tokens:
        cut = tokens.index("=")
        left, right = tokens[:cut], tokens[cut + 1:]
        if not left or not right:
            return None
        try:
            return functions.parse(left), functions.parse(right)
        except functions.ParseError:
            return None
    try:
        if tokens == ["x"]:
            return None
        return functions.parse(tokens), None
    except functions.ParseError:
        return None


def solve(left, right):
    """The worksheet as Markdown, or None if the equation isn't linear or quadratic in x."""
    tree = left if right is None else ["sub", left, right]
    coefficients = functions.as_quadratic(tree)
    if coefficients is None:
        return None
    a, b, c = (_fraction(v) for v in coefficients)
    given = functions.to_latex(left) + (" = 0" if right is None else " = " + functions.to_latex(right))
    steps = []          # (title, formula)
    already_standard = right is not None and functions.to_latex(right) == "0" and functions.as_quadratic(left) is not None
    standard = f"{_poly_latex(a, b, c)} = 0"
    if right is not None and not already_standard or right is None and False:
        steps.append(("Move everything to one side", standard))
    lead = ""
    answer = ""
    if a == 0 and b == 0:
        return (("The equation has no x in it after simplifying. " + ("It is always true." if c == 0 else "It can never be true.")) +
                f"\n\n### Problem\n$${given}$$\n\n### Step 1 · Simplify\n$${standard}$$")
    if a == 0:                                     # linear: bx + c = 0
        value = -c / b
        steps.append(("Isolate the x term", f"{_latex(b)}x = {_latex(-c)}" if b != 1 else f"x = {_latex(-c)}"))
        if b != 1:
            steps.append((f"Divide both sides by {_latex(b)}", f"x = {_latex(value)}"))
        answer = f"x = {_latex(value)}"
        lead = f"The answer is x equals {_say(float(value))}."
    else:
        disc = b * b - 4 * a * c
        steps.append(("Identify a, b and c", f"a = {_latex(a)},\\quad b = {_latex(b)},\\quad c = {_latex(c)}"))
        wrap = lambda v: f"({_latex(v)})" if v < 0 or v.denominator != 1 else _latex(v)
        steps.append(("Compute the discriminant", f"\\Delta = b^2 - 4ac = {wrap(b)}^2 - 4\\cdot {wrap(a)}\\cdot {wrap(c)} = {_latex(disc)}"))
        exact, complex_roots = _exact_roots(a, b, disc)
        if disc > 0:
            steps.append(("Apply the quadratic formula", f"x = \\frac{{-b \\pm \\sqrt{{\\Delta}}}}{{2a}} = \\frac{{{_latex(-b)} \\pm \\sqrt{{{_latex(disc)}}}}}{{{_latex(2 * a)}}}"))
            values = sorted([(-float(b) - math.sqrt(float(disc))) / (2 * float(a)), (-float(b) + math.sqrt(float(disc))) / (2 * float(a))])
            if len(exact) == 2:
                steps.append(("Simplify", f"x = {exact[0]} \\quad\\text{{or}}\\quad x = {exact[1]}"))
                answer = f"x = {exact[0]}\\ \\text{{or}}\\ x = {exact[1]}"
            else:
                steps.append(("Simplify", f"x = {exact[0]}"))
                answer = f"x = {exact[0]}"
                steps.append(("Decimal values", f"x \\approx {_dec(values[0])}\\quad\\text{{or}}\\quad x \\approx {_dec(values[1])}"))
            lead = f"The solutions are x equals {_say(values[0])} and x equals {_say(values[1])}."
            if all(abs(v - round(v)) < 1e-9 for v in values):
                lead = f"The solutions are x equals {_say(values[0])} and x equals {_say(values[1])}."
        elif disc == 0:
            value = -b / (2 * a)
            steps.append(("The discriminant is zero, so there is one solution", f"x = -\\frac{{b}}{{2a}} = {_latex(value)}"))
            answer = f"x = {_latex(value)}"
            lead = f"There is one solution: x equals {_say(float(value))}."
        else:
            steps.append(("The discriminant is negative, so the solutions are complex", f"x = \\frac{{-b \\pm \\sqrt{{\\Delta}}}}{{2a}} = {exact[0]}"))
            answer = f"x = {exact[0]}"
            lead = "This equation has no real solutions. It has two complex solutions, shown on your screen."
    lines = [lead, "", "### Problem", f"$${given}$$"]
    for i, (title, formula) in enumerate(steps, 1):
        lines += ["", f"### Step {i} · {title}", f"$${formula}$$"]
    lines += ["", f"> ${answer}$"]
    return "\n".join(lines)


def handle(text: str):
    request = parse_request(text)
    if request is None:
        return None
    return solve(*request)
