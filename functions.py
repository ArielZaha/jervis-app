"""Any function of x, from words or symbols: "sine of x over x", "e to the minus x squared", "|x - 2|", "ln(x) + 3".

Understanding: normalize() turns spoken math into plain symbols, parse() builds a small syntax tree (nested lists), and
evaluate() computes it. The window (graph.js) evaluates the SAME tree, so nothing is ever run as code on either side.
Analysis: analyze() finds where to look (the view), the x-intercepts, the highs and lows, the y-intercept and the asymptotes.

Tree nodes: ["num", v] ["x"] ["neg", a] ["add"|"sub"|"mul"|"div"|"pow", a, b] ["fn", name, a] ["abs", a]
"""
import math
import re

# ---------- words -> symbols ----------
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMBER_WORD = "|".join(sorted([*_ONES, *_TENS, "hundred"], key=len, reverse=True))
_NUMBER_PHRASE = re.compile(rf"\b(?:{_NUMBER_WORD})(?:[\s-]+(?:and\s+)?(?:{_NUMBER_WORD}))*(?:\s+point(?:\s+(?:zero|one|two|three|four|five|six|seven|eight|nine))+)?\b")
_ORDINALS = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}


def _phrase_value(phrase: str) -> str:
    words = phrase.replace("-", " ").split()
    decimals = ""
    if "point" in words:
        cut = words.index("point")
        decimals = "".join(str(_ONES[w]) for w in words[cut + 1:])
        words = words[:cut]
    current = 0
    for w in words:
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(1, current) * 100
    return f"{current}.{decimals}" if decimals else str(current)


_FUNCTIONS = {"sin", "cos", "tan", "cot", "sec", "csc", "asin", "acos", "atan", "sinh", "cosh", "tanh", "sqrt", "cbrt", "abs",
              "exp", "ln", "log", "log2", "floor", "ceil"}
_FUNCTION_NAMES = "|".join(sorted(_FUNCTIONS, key=len, reverse=True))


def normalize(text: str) -> str:
    """Spoken or typed math -> plain symbols: "two x squared minus the square root of x" -> "2 x ^2 - sqrt x"."""
    t = (text or "").lower().replace("’", "'")
    for a, b in (("²", "^2"), ("³", "^3"), ("−", "-"), ("–", "-"), ("×", "*"), ("·", "*"), ("÷", "/"),
                 ("√", " sqrt "), ("π", " pi "), ("−", "-")):
        t = t.replace(a, b)
    t = re.sub(r"[?!,;:]", " ", t)
    t = _NUMBER_PHRASE.sub(lambda m: " " + _phrase_value(m.group(0)) + " ", t)
    # function names
    t = re.sub(r"\b(?:arc|inverse)\s*(sin|sine|cos|cosine|tan|tangent)\b", lambda m: "a" + m.group(1)[:3], t)
    t = re.sub(r"\barc(sin|cos|tan)\b", r"a\1", t)
    for word, sym in (("hyperbolic sine", "sinh"), ("hyperbolic cosine", "cosh"), ("hyperbolic tangent", "tanh"), ("cosecant", "csc"),
                      ("cotangent", "cot"), ("secant", "sec"), ("cosine", "cos"), ("sine", "sin"), ("tangent", "tan"),
                      ("cube root", "cbrt"), ("square root", "sqrt"), ("absolute value", "abs"), ("modulus", "abs"), ("magnitude", "abs"),
                      ("natural logarithm", "ln"), ("natural log", "ln"), ("logarithm", "log"), ("exponential", "exp")):
        t = re.sub(rf"\b{word}\b", f" {sym} ", t)
    t = re.sub(r"\blog\s+base\s+(\d+)\b", lambda m: " log10 " if m.group(1) == "10" else " log2 " if m.group(1) == "2" else f" logb{m.group(1)} ", t)
    t = re.sub(rf"\b({_FUNCTION_NAMES}|logb\d+|log10)\s+of\b", r"\1", t)
    t = re.sub(r"\be\s+(?:raised\s+)?to\s+the\s+power\s+of\b|\be\s+raised\s+to\b|\be\s+to\s+the\b", " e ^ ", t)
    # powers
    t = re.sub(r"\b(?:squared|square)\b", " ^2 ", t)
    t = re.sub(r"\b(?:cubed|cube)\b", " ^3 ", t)
    t = re.sub(r"\bto\s+the\s+(second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)(?:\s+power)?\b", lambda m: f" ^{_ORDINALS[m.group(1)]} ", t)
    t = re.sub(r"\b(?:raised\s+to(?:\s+the)?(?:\s+power)?(?:\s+of)?|to\s+the\s+power\s+of|to\s+the\s+power|to\s+the|to\s+power)\b", " ^ ", t)
    # operators
    t = re.sub(r"\b(?:multiplied\s+by|times)\b", " * ", t)
    t = re.sub(r"\b(?:divided\s+by|over)\b", " / ", t)
    t = re.sub(r"\b(?:minus|negative|less)\b", " - ", t)
    t = re.sub(r"\bplus\b", " + ", t)
    t = re.sub(r"\b(?:equals|equal\s+to|is\s+equal\s+to|equal)\b", " = ", t)
    t = re.sub(r"\bf\s*(?:\(\s*x\s*\)|of\s+x)\s*", " y ", t)
    return " ".join(t.split())


# ---------- tokens and the parser ----------
_TOKEN = re.compile(r"\d+(?:\.\d+)?|\.\d+|[a-z]+\d*|[-+*/^()|=]")
_FILLER = {"of", "for", "the", "a", "an", "me", "please", "function", "functions", "equation", "curve", "graph", "graphs", "plot", "wave", "with",
           "that", "is", "whose", "like", "called", "following", "this", "given", "my", "i", "want", "you", "to", "can", "could", "would", "make",
           "create", "show", "draw", "paint", "sketch", "chart", "picture", "image", "drawing", "visualize", "visualise", "illustrate", "it",
           "on", "in", "screen", "and", "then", "now", "hey", "jervis", "some", "simple", "just", "nice", "beautiful", "pretty", "cool", "here",
           "give", "get", "let", "lets", "see", "look", "at", "up", "out", "again", "once", "more", "same", "previous", "last", "earlier", "there", "polynomial", "shape", "line", "straight"}
_SHAPES = {"parabola": None, "parabolas": None, "quadratic": None, "quadratics": None,
           "cubic": ["pow", ["x"], ["num", 3]], "hyperbola": ["div", ["num", 1], ["x"]], "reciprocal": ["div", ["num", 1], ["x"]],
           "gaussian": ["fn", "exp", ["neg", ["div", ["pow", ["x"], ["num", 2]], ["num", 2]]]],
           "bell": ["fn", "exp", ["neg", ["div", ["pow", ["x"], ["num", 2]], ["num", 2]]]],
           "sigmoid": ["div", ["num", 1], ["add", ["num", 1], ["fn", "exp", ["neg", ["x"]]]]],
           "logistic": ["div", ["num", 1], ["add", ["num", 1], ["fn", "exp", ["neg", ["x"]]]]]}
_CONSTANTS = {"pi": math.pi, "e": math.e}


class ParseError(ValueError):
    pass


def _tokenize(text: str) -> list:
    tokens = []
    for raw in _TOKEN.findall(text):
        if raw[0].isalpha():
            if raw in _FUNCTIONS or re.fullmatch(r"logb\d+|log10", raw) or raw in _CONSTANTS or raw in ("x", "y"):
                tokens.append(raw)
                continue
            m = re.fullmatch(rf"({_FUNCTION_NAMES})(x|pi|e)", raw)      # "sinx" typed without a space
            if m:
                tokens.extend(m.groups())
                continue
            if re.fullmatch(r"x\d", raw):                                # "x2" -> x^2
                tokens.extend(["x", "^", raw[1]])
                continue
            if raw.strip("x") == "" and len(raw) <= 3:                  # "xx" -> x x
                tokens.extend(["x"] * len(raw))
                continue
            tokens.append(raw)                                          # unknown word: the parser reports it
        else:
            tokens.append(raw)
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0
        self.bars = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def _starts_atom(self, tok):
        if tok is None:
            return False
        if tok == "|":
            return self.bars == 0
        return tok in ("(", "x") or tok[0].isdigit() or tok[0] == "." or tok in _CONSTANTS or tok in _FUNCTIONS or re.fullmatch(r"logb\d+|log10", tok) is not None

    def expr(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            node = ["add" if op == "+" else "sub", node, self.term()]
        return node

    def term(self):
        node = self.unary()
        while True:
            tok = self.peek()
            if tok in ("*", "/"):
                self.take()
                node = ["mul" if tok == "*" else "div", node, self.unary()]
            elif self._starts_atom(tok):                    # 2x, 3(x+1), (x+1)(x-1), x sin x
                node = ["mul", node, self.unary()]
            else:
                return node

    def unary(self):
        if self.peek() in ("-", "+"):
            sign = self.take()
            inner = self.unary()
            return ["neg", inner] if sign == "-" else inner
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == "^":
            self.take()
            return ["pow", base, self.exponent()]
        return base

    def exponent(self):
        if self.peek() in ("-", "+"):
            sign = self.take()
            inner = self.exponent()
            return ["neg", inner] if sign == "-" else inner
        return self.power()

    def atom(self):
        tok = self.take()
        if tok is None:
            raise ParseError("unfinished")
        if tok[0].isdigit() or tok[0] == ".":
            return ["num", float(tok)]
        if tok == "x":
            return ["x"]
        if tok in _CONSTANTS:
            return ["num", _CONSTANTS[tok]]
        if tok == "(":
            inner = self.expr()
            if self.take() != ")":
                raise ParseError("missing )")
            return inner
        if tok == "|":
            self.bars += 1
            inner = self.expr()
            self.bars -= 1
            if self.take() != "|":
                raise ParseError("missing |")
            return ["abs", inner]
        if tok in _FUNCTIONS or re.fullmatch(r"logb\d+|log10", tok):
            name = tok
            power = None
            if self.peek() == "^":                          # sin^2(x) = (sin x)^2
                self.take()
                power = self.exponent()
            if self.peek() == "(":
                self.take()
                arg = self.expr()
                if self.take() != ")":
                    raise ParseError("missing )")
            elif self._starts_atom(self.peek()) or self.peek() in ("-",):
                arg = self.argument()
            else:
                raise ParseError("bare function")
            node = self._call(name, arg)
            return ["pow", node, power] if power is not None else node
        raise ParseError(f"unknown word {tok}")

    def argument(self):
        """The argument of a function written without brackets: "sin 2x", "sqrt x + 1" (= sqrt(x) + 1), "ln x^2" (= ln(x^2))."""
        if self.peek() == "-":
            self.take()
            return ["neg", self.argument()]
        node = self.power()
        while self.peek() in ("x", "pi", "e") and node[0] in ("num", "mul"):     # 2x, 2 pi x
            node = ["mul", node, self.power()]
        return node

    @staticmethod
    def _call(name, arg):
        if name == "abs":
            return ["abs", arg]
        if re.fullmatch(r"logb\d+", name):
            base = float(name[4:])
            return ["div", ["fn", "ln", arg], ["num", math.log(base)]] if base > 0 and base != 1 else ["fn", "ln", arg]
        return ["fn", "log" if name == "log10" else name, arg]


def parse(tokens: list):
    parser = _Parser(tokens)
    node = parser.expr()
    if parser.peek() is not None:
        raise ParseError("leftover")
    return node


# ---------- evaluation (the window has the same rules) ----------
def _pow(a, b):
    try:
        if a < 0 and b != int(b):
            third = 1.0 / b
            if abs(third - round(third)) < 1e-9 and int(round(third)) % 2 == 1:   # x^(1/3): the real cube root
                return -((-a) ** b)
            return math.nan
        return math.pow(a, b)
    except OverflowError:
        return math.inf if a > 0 or b % 2 == 0 else -math.inf
    except (ValueError, ZeroDivisionError):
        return math.inf if a == 0 and b < 0 else math.nan


_FN = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "cot": lambda v: 1 / math.tan(v), "sec": lambda v: 1 / math.cos(v),
    "csc": lambda v: 1 / math.sin(v), "asin": math.asin, "acos": math.acos, "atan": math.atan, "sinh": math.sinh,
    "cosh": math.cosh, "tanh": math.tanh, "sqrt": math.sqrt, "cbrt": lambda v: math.copysign(abs(v) ** (1 / 3), v),
    "exp": math.exp, "ln": math.log, "log": math.log10, "log2": math.log2, "floor": math.floor, "ceil": math.ceil,
}


def evaluate(node, x: float) -> float:
    kind = node[0]
    try:
        if kind == "num":
            return node[1]
        if kind == "x":
            return x
        if kind == "neg":
            return -evaluate(node[1], x)
        if kind == "abs":
            return abs(evaluate(node[1], x))
        if kind == "fn":
            return float(_FN[node[1]](evaluate(node[2], x)))
        a, b = evaluate(node[1], x), evaluate(node[2], x)
        if kind == "add":
            return a + b
        if kind == "sub":
            return a - b
        if kind == "mul":
            return a * b
        if kind == "div":
            return a / b if b != 0 else (math.copysign(math.inf, a) if a != 0 else math.nan)
        return _pow(a, b)
    except OverflowError:
        return math.inf
    except (ValueError, ZeroDivisionError):
        return math.nan


def uses(node, *names) -> bool:
    if node[0] == "fn":
        return node[1] in names or uses(node[2], *names)
    return node[0] in names or any(uses(child, *names) for child in node[1:] if isinstance(child, list))


def depends_on_x(node) -> bool:
    if node[0] == "x":
        return True
    return any(depends_on_x(child) for child in node[1:] if isinstance(child, list))


# ---------- writing a function back out ----------
def _num(v: float) -> str:
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def to_latex(node, parent: int = 0) -> str:
    kind = node[0]
    if kind == "num":
        v = node[1]
        if abs(v - math.pi) < 1e-12:
            return r"\pi"
        if abs(v - math.e) < 1e-12:
            return "e"
        return _num(v)
    if kind == "x":
        return "x"
    if kind == "neg":
        return ("(-" + to_latex(node[1], 4) + ")") if parent > 1 else "-" + to_latex(node[1], 4)
    if kind == "abs":
        return r"\left|" + to_latex(node[1]) + r"\right|"
    if kind == "fn":
        name = node[1]
        arg = to_latex(node[2])
        if name == "sqrt":
            return r"\sqrt{" + arg + "}"
        if name == "cbrt":
            return r"\sqrt[3]{" + arg + "}"
        if name == "exp":
            return "e^{" + arg + "}"
        if name in ("floor", "ceil"):
            return r"\left\lfloor " + arg + r"\right\rfloor" if name == "floor" else r"\left\lceil " + arg + r"\right\rceil"
        macro = {"asin": r"\arcsin", "acos": r"\arccos", "atan": r"\arctan", "log": r"\log_{10}", "log2": r"\log_{2}"}.get(name, "\\" + name)
        return f"{macro}\\left({arg}\\right)"
    a, b = node[1], node[2]
    if kind in ("add", "sub"):
        text = to_latex(a, 1) + (" + " if kind == "add" else " - ") + to_latex(b, 2 if kind == "sub" else 1)
        return "(" + text + ")" if parent > 1 else text
    if kind == "mul":
        left, right = to_latex(a, 3), to_latex(b, 3)
        glue = r" \cdot " if (right[:1].isdigit() or right.startswith(("(", "\\left")) and left[-1:].isdigit() and not left.endswith("}")) else " "
        if right[:1].isdigit() or a[0] == "num" and b[0] == "num":
            glue = r" \cdot "
        elif a[0] == "num" and b[0] != "num":
            glue = ""
        text = left + glue + right
        return "(" + text + ")" if parent > 3 else text
    if kind == "div":
        return r"\frac{" + to_latex(a) + "}{" + to_latex(b) + "}"
    if kind == "pow":
        base = to_latex(a, 5)
        if a[0] in ("add", "sub", "mul", "div", "neg") or (a[0] == "fn" and a[1] not in ("sqrt", "cbrt", "exp")):
            base = r"\left(" + to_latex(a) + r"\right)"
        if a[0] == "fn" and a[1] in ("sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh", "ln", "log") and b[0] == "num":
            return "\\" + a[1] + "^{" + to_latex(b) + r"}\left(" + to_latex(a[2]) + r"\right)"
        return base + "^{" + to_latex(b) + "}"
    return "?"


_SUPER = {"2": "²", "3": "³"}


def to_plain(node, parent: int = 0) -> str:
    kind = node[0]
    if kind == "num":
        v = node[1]
        return "π" if abs(v - math.pi) < 1e-12 else "e" if abs(v - math.e) < 1e-12 else _num(v)
    if kind == "x":
        return "x"
    if kind == "neg":
        return ("(−" + to_plain(node[1], 4) + ")") if parent > 1 else "−" + to_plain(node[1], 4)
    if kind == "abs":
        return "|" + to_plain(node[1]) + "|"
    if kind == "fn":
        return f"e^({to_plain(node[2])})" if node[1] == "exp" else f"{node[1]}({to_plain(node[2])})"
    a, b = node[1], node[2]
    if kind in ("add", "sub"):
        text = to_plain(a, 1) + (" + " if kind == "add" else " − ") + to_plain(b, 2 if kind == "sub" else 1)
        return "(" + text + ")" if parent > 1 else text
    if kind == "mul":
        left, right = to_plain(a, 3), to_plain(b, 3)
        glue = "" if (a[0] == "num" and b[0] != "num") else "·" if (right[:1].isdigit() or b[0] in ("fn", "abs")) else ""
        text = left + glue + right
        return "(" + text + ")" if parent > 3 else text
    if kind == "div":
        return to_plain(a, 3) + "/" + to_plain(b, 4)
    base = to_plain(a, 5)
    if b[0] == "num" and _num(b[1]) in _SUPER:
        return (base if a[0] in ("x", "num", "abs") else "(" + to_plain(a) + ")") + _SUPER[_num(b[1])]
    return (base if a[0] in ("x", "num") else "(" + to_plain(a) + ")") + "^" + (to_plain(b) if b[0] in ("num", "x") else "(" + to_plain(b) + ")")


# ---------- what the function does ----------
def as_quadratic(node):
    """(a, b, c) if the function is a polynomial of degree at most 2 (checked at many points), else None."""
    f = lambda v: evaluate(node, v)
    c, p, m = f(0.0), f(1.0), f(-1.0)
    if not all(math.isfinite(v) for v in (c, p, m)):
        return None
    a, b = (p + m) / 2 - c, (p - m) / 2
    for v in (2.0, -3.0, 0.5, 7.0, -11.0, 0.1234):
        want = a * v * v + b * v + c
        got = f(v)
        if not math.isfinite(got) or abs(got - want) > 1e-7 * (1 + abs(want)):
            return None
    clean = lambda v: 0.0 if abs(v) < 1e-9 else round(v, 9)
    return clean(a), clean(b), clean(c)


def _finite(v):
    return isinstance(v, float) and math.isfinite(v)


def _bisect(node, lo, hi, iterations=60):
    flo = evaluate(node, lo)
    for _ in range(iterations):
        mid = (lo + hi) / 2
        fm = evaluate(node, mid)
        if not math.isfinite(fm):
            return mid, math.nan
        if (fm < 0) == (flo < 0) and fm != 0:
            lo, flo = mid, fm
        else:
            hi = mid
    mid = (lo + hi) / 2
    return mid, evaluate(node, mid)


def _minimum(node, lo, hi, sign):
    """Refine the highest (sign=-1) or lowest (sign=1) point between lo and hi (golden section)."""
    g = 0.6180339887498949
    a, b = lo, hi
    for _ in range(70):
        c, d = b - g * (b - a), a + g * (b - a)
        if sign * evaluate(node, c) < sign * evaluate(node, d):
            b = d
        else:
            a = c
    x = (a + b) / 2
    return x, evaluate(node, x)


def analyze(node, span: float = 24.0, samples: int = 6000) -> dict:
    """Roots, extrema, asymptotes and a good view for any function of x. All numbers are found by sampling."""
    xs = [-span + 2 * span * (i + 0.3719) / samples for i in range(samples)]   # off the round numbers, so x = 0 or x = 1 is never hit exactly
    ys = [evaluate(node, x) for x in xs]
    step = xs[1] - xs[0]
    scale = max([abs(v) for v in ys if math.isfinite(v) and abs(v) < 1e6] or [1.0])
    roots, poles, extrema = [], [], []
    samples = len(xs) - 1
    for i in range(samples):
        y0, y1 = ys[i], ys[i + 1]
        if math.isinf(y0):
            poles.append(xs[i])
            continue
        if math.isfinite(y0) != math.isfinite(y1):                    # the edge of the domain: an intercept if the curve ends on the axis
            lo, hi = (xs[i], xs[i + 1])
            for _ in range(60):
                mid = (lo + hi) / 2
                if math.isfinite(evaluate(node, mid)) == math.isfinite(y0):
                    lo = mid
                else:
                    hi = mid
            edge = lo if math.isfinite(y0) else hi
            fe = evaluate(node, edge)
            if math.isfinite(fe) and abs(fe) < 1e-6:
                roots.append(edge)
            continue
        if not (math.isfinite(y0) and math.isfinite(y1)):
            continue
        if y0 == 0:
            roots.append(xs[i])
        elif y0 * y1 < 0:
            x, fx = _bisect(node, xs[i], xs[i + 1])
            (roots if math.isfinite(fx) and abs(fx) < 1e-5 * max(1.0, min(abs(y0), abs(y1))) + 1e-7 else poles).append(x)
    # points where the slope changes sign
    for i in range(1, samples):
        a, b, c = ys[i - 1], ys[i], ys[i + 1]
        if not all(math.isfinite(v) for v in (a, b, c)) or max(abs(a), abs(b), abs(c)) > 1e8:
            continue
        if (b > a and b >= c and b > c - 1e-15) or (b < a and b <= c):
            if (b - a) * (c - b) < 0 or (b == c and b > a) or (b == c and b < a):
                sign = -1 if b > a else 1
                x, fx = _minimum(node, xs[i - 1], xs[i + 1], sign)
                if math.isfinite(fx) and not any(abs(x - px) < step * 3 for px in poles) and abs(x) < span - 3 * step:
                    extrema.append({"type": "max" if sign == -1 else "min", "x": x, "y": fx})
    dedup = []
    for e in extrema:
        if not any(abs(e["x"] - d["x"]) < step * 4 for d in dedup):
            dedup.append(e)
    extrema = dedup
    for e in extrema:               # an extremum sitting on the x-axis (x^4 at 0, a double root) counts as a root as well
        if abs(e["y"]) < 1e-6 and not any(abs(e["x"] - r) < step * 4 for r in roots):
            roots.append(e["x"])
    roots = sorted({round(r, 6) for r in roots})
    poles = sorted({round(p, 6) for p in poles})
    return {"xs": xs, "ys": ys, "roots": roots, "poles": poles, "extrema": extrema, "scale": scale}


def _domain(xs, ys, node=None):
    """(low, high) of the region where the function has values inside the sampled span, or None where it is defined everywhere."""
    good = [i for i, y in enumerate(ys) if math.isfinite(y)]
    if not good or len(good) == len(xs):
        return None
    lo_i, hi_i = good[0], good[-1]
    lo, hi = xs[lo_i], xs[hi_i]
    if node is not None:                                          # the exact edge, not just the first sample
        for edge_i, step, which in ((lo_i, -1, "lo"), (hi_i, 1, "hi")):
            j = edge_i + step
            if 0 <= j < len(xs) and not math.isfinite(ys[j]):
                a, b = xs[edge_i], xs[j]
                for _ in range(60):
                    mid = (a + b) / 2
                    if math.isfinite(evaluate(node, mid)):
                        a = mid
                    else:
                        b = mid
                if which == "lo":
                    lo = a
                else:
                    hi = a
    return lo, hi


def build_view(node, info: dict) -> dict:
    """Where to look: a window around the interesting points, cut to the domain, with the y-range from the curve itself."""
    xs, ys = info["xs"], info["ys"]
    span = xs[-1]
    domain = _domain(xs, ys, node)
    features = sorted([0.0] + info["roots"] + [e["x"] for e in info["extrema"]] + info["poles"], key=abs)
    near = features[:6]
    lo, hi = min(near), max(near)
    pad = max((hi - lo) * 0.4, 2.0)
    reach = max(abs(lo), abs(hi)) + pad
    xmin, xmax = -max(reach, 4.0), max(reach, 4.0)
    if domain:
        d_lo, d_hi = domain
        edge = xs[1] - xs[0]
        if d_lo > -span + 3 * edge and d_hi < span - 3 * edge:       # a bounded domain: show all of it
            width = d_hi - d_lo
            xmin, xmax = d_lo - 0.18 * width, d_hi + 0.18 * width
        elif d_lo > -span + 3 * edge:                                # starts somewhere (sqrt x, ln x)
            xmin, xmax = d_lo - 1.5, max(d_lo + 9.5, hi + pad)
        elif d_hi < span - 3 * edge:
            xmin, xmax = min(d_hi - 9.5, lo - pad), d_hi + 1.5
    inside = sorted(y for x, y in zip(xs, ys) if xmin <= x <= xmax and math.isfinite(y))
    if not inside:
        return {"xmin": -5.0, "xmax": 5.0, "ymin": -5.0, "ymax": 5.0}
    k = len(inside)
    cut = 0.07 if info["poles"] else 0.03
    ylo, yhi = inside[int(k * cut)], inside[min(k - 1, int(k * (1 - cut)))]
    key = [0.0] + [e["y"] for e in info["extrema"] if xmin <= e["x"] <= xmax]
    y0 = evaluate(node, 0.0)
    if math.isfinite(y0):
        key.append(y0)
    if not info["poles"]:                      # no asymptotes to cut off: keep the ends of the curve too
        ylo, yhi = min(ylo, inside[0]), max(yhi, inside[-1])
    key_lo, key_hi = min(key), max(key)
    room = max(key_hi - key_lo, (xmax - xmin) * 0.3)
    ylo, yhi = max(ylo, key_lo - 3 * room), min(yhi, key_hi + 3 * room)      # a curve that shoots up is cut, so its details stay readable
    ylo, yhi = min(ylo, *key), max(yhi, *key)
    if yhi - ylo < 1e-6:
        ylo, yhi = ylo - 1, yhi + 1
    margin = (yhi - ylo) * 0.1
    ymin, ymax = ylo - margin, yhi + margin
    if ymax - ymin < 2:
        mid = (ymax + ymin) / 2
        ymin, ymax = mid - 1, mid + 1
    return {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax}


def kind_name(node) -> str:
    if uses(node, "sin", "cos", "tan", "cot", "sec", "csc", "asin", "acos", "atan", "sinh", "cosh", "tanh"):
        return "Trigonometric"
    if uses(node, "exp") or (node[0] == "pow" and not depends_on_x(node[1]) and depends_on_x(node[2])):
        return "Exponential"
    if uses(node, "ln", "log", "log2"):
        return "Logarithmic"
    if uses(node, "sqrt", "cbrt"):
        return "Radical"
    if uses(node, "abs"):
        return "Absolute value"
    if uses(node, "floor", "ceil"):
        return "Step function"
    if uses(node, "div") and _has_x_in_denominator(node):
        return "Rational"
    for degree, name in ((3, "Cubic"), (4, "Quartic")):
        pass
    return "Polynomial"


def _has_x_in_denominator(node) -> bool:
    if node[0] == "div" and depends_on_x(node[2]):
        return True
    return any(_has_x_in_denominator(child) for child in node[1:] if isinstance(child, list))


def describe_function(node, info: dict, view: dict) -> dict:
    """The payload the window draws, plus the facts for the chat."""
    inside = lambda x: view["xmin"] <= x <= view["xmax"]
    roots = [r for r in info["roots"] if inside(r)]
    extrema = [e for e in info["extrema"] if inside(e["x"])]
    poles = [p for p in info["poles"] if inside(p)]
    y0 = evaluate(node, 0.0)
    horizontal = []
    for sign in (1, -1):
        values = [evaluate(node, sign * far) for far in (1e4, 1e5, 1e6)]
        if all(math.isfinite(v) for v in values) and max(values) - min(values) < 1e-3 * (1 + abs(values[-1])):
            v = round(values[-1], 4) + 0.0
            v = 0.0 if abs(v) < 1e-9 else v
            if view["ymin"] <= v <= view["ymax"] and not any(abs(v - h) < 1e-3 for h in horizontal):
                horizontal.append(v)
    domain = _domain(info["xs"], info["ys"], node)
    limit = info["xs"][-1] - 3 * (info["xs"][1] - info["xs"][0])
    if domain and (domain[0] > -limit or domain[1] < limit):
        low = None if domain[0] <= -limit else round(domain[0], 4)
        high = None if domain[1] >= limit else round(domain[1], 4)
    else:
        low = high = None
    clean = lambda v: 0.0 if abs(v) < 1e-9 else round(v, 4)
    return {
        "kind": "function", "kindName": kind_name(node), "ast": node, "plain": "y = " + to_plain(node), "latex": "y = " + to_latex(node),
        "view": view,
        "roots": [clean(r) for r in roots][:24],
        "extrema": [{"type": e["type"], "x": clean(e["x"]), "y": clean(e["y"])} for e in extrema][:24],
        "poles": [clean(p) for p in poles][:12], "horizontal": horizontal[:2],
        "yint": clean(y0) if math.isfinite(y0) else None,
        "domain": ([low, high, low is not None and not math.isfinite(evaluate(node, low)), high is not None and not math.isfinite(evaluate(node, high))]
                   if (low is not None or high is not None) else None),
    }
