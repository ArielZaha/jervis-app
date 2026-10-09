"""Exact numbers for questions with numbers in them: the local model writes a tiny calculation, and this module
runs it — models are unreliable at arithmetic ("3 apples + 2 dozen - 7" came back as 25 and as 9), code isn't.

The calculation is run by a small interpreter, not exec(): only numbers, + - * / // % **, comparisons, a few math
functions, and assignments to plain names — no imports, attributes (beyond math.*), strings or loops — so whatever
the model writes can't do anything but arithmetic. The verified result is then handed to the chat model as a fact.
"""
import ast
import math
import operator
import re

_NUMBER_WORDS = (r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|"
                 r"thousand|million|dozen|half|twice|double|triple|quarter")
_QUANTITY = re.compile(r"\b(?:how (?:many|much|old|long|far|fast)|what time|when (?:does|will|did)|total|left|remain\w*|"
                       r"each|per|percent|%|average|cost\w*|price|split|share|times|twice|older|younger|faster|"
                       r"altogether|in all|more than|less than|fewer|difference|sum|product)\b", re.I)
_HAS_NUMBER = re.compile(rf"\d|\b(?:{_NUMBER_WORDS})\b", re.I)
_SKIP = re.compile(r"\b(?:timer|alarm|remind|volume|weather|forecast|play|song|spotify|youtube|open|graph|plot|draw|"
                   r"solve|equation|x\s*[=^]|derivative|integral)\b", re.I)

MAX_STATEMENTS = 40
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: None}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
_COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
            ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCTIONS = {"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "int": int, "float": float,
              "divmod": divmod}
_MATH = {name: getattr(math, name) for name in ("sqrt", "floor", "ceil", "pi", "e", "log", "log10", "exp", "sin",
                                                "cos", "tan", "radians", "degrees", "hypot", "gcd", "factorial")}

SCHEMA = {"type": "object", "properties": {
    "needs_math": {"type": "boolean"},
    "code": {"type": "string"},
    "facts": {"type": "string"}}, "required": ["needs_math", "code", "facts"]}

PROMPT = """You turn a question into an exact calculation. Write short Python using only numbers, variables, \
+ - * / // % **, round(), min(), max(), abs(), divmod() and math.*. No strings, imports, loops or functions. \
Name every intermediate value clearly. Don't round to whole numbers unless asked; money is round(x, 2). \
Times of day: work in minutes since midnight (e.g. 15*60+40), then divmod. Code only — the sentence goes in "facts".
"facts": one short sentence stating the result(s) with {variable} placeholders, e.g. "You have {apples} apples." or \
"It arrives at {hours}:{minutes:02d}." If the question needs no calculation, set needs_math false."""


def looks_quantitative(text: str) -> bool:
    t = text or ""
    return bool(_HAS_NUMBER.search(t) and _QUANTITY.search(t) and not _SKIP.search(t) and len(t) < 400)


class CalcError(ValueError):
    pass


def _value(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise CalcError("only numbers are allowed")
    if isinstance(v, float) and not math.isfinite(v):
        raise CalcError("the result isn't a finite number")
    if abs(v) > 1e18:
        raise CalcError("the numbers got too large")
    return v


def _eval(node, env):
    if isinstance(node, ast.Constant):
        return _value(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _MATH:
            return _MATH[node.id]
        raise CalcError(f"unknown name {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow):
            if abs(b) > 100 or (abs(a) > 1e6 and abs(b) > 3):
                raise CalcError("that power is too large")
            return _value(a ** b)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
            raise CalcError("division by zero")
        return _value(_BIN[type(node.op)](a, b))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, env))
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
        return _COMPARE[type(node.ops[0])](_eval(node.left, env), _eval(node.comparators[0], env))
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(_eval(e, env) for e in node.elts)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "math":
        if node.attr in _MATH:
            return _MATH[node.attr]
        raise CalcError(f"math.{node.attr} isn't allowed")
    if isinstance(node, ast.JoinedStr):   # f"{hours}:{minutes:02d}" — text to show, never to compute with
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                spec = ""
                if part.format_spec is not None:
                    if not all(isinstance(p, ast.Constant) for p in part.format_spec.values):
                        raise CalcError("only plain format specs are allowed")
                    spec = "".join(p.value for p in part.format_spec.values)
                value = _eval(part.value, env)
                if isinstance(value, float) and value.is_integer() and spec.endswith("d"):
                    value = int(value)
                parts.append(format(value, spec))
            else:
                raise CalcError("that text isn't allowed")
        return "".join(parts)[:200]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print" and node.args:
        return _eval(node.args[0], env)   # the model "printing" its answer: that value is the result
    if isinstance(node, ast.Call) and not node.keywords:
        func = node.func
        if isinstance(func, ast.Name) and func.id in _FUNCTIONS:
            fn = _FUNCTIONS[func.id]
        elif isinstance(func, (ast.Attribute, ast.Name)):
            fn = _eval(func, env)
            if fn not in _MATH.values() or not callable(fn):
                raise CalcError("that function isn't allowed")
        else:
            raise CalcError("that call isn't allowed")
        args = [_eval(a, env) for a in node.args]
        result = fn(*args)
        return tuple(_value(r) for r in result) if isinstance(result, tuple) else _value(result)
    raise CalcError(f"{type(node).__name__} isn't allowed in a calculation")


def run(code: str) -> dict:
    """Run a calculation; returns its variables. Raises CalcError for anything that isn't plain arithmetic."""
    lines = (code or "").splitlines()
    for _ in range(4):   # the model sometimes pastes its answer sentence in as a line: drop lines that don't parse
        try:
            tree = ast.parse("\n".join(lines), mode="exec")
            break
        except SyntaxError as e:
            if not e.lineno or e.lineno > len(lines) or len(lines) < 2:
                raise CalcError(f"the calculation isn't valid Python ({e.msg})") from e
            del lines[e.lineno - 1]
    else:
        raise CalcError("the calculation isn't valid Python")
    if len(tree.body) > MAX_STATEMENTS:
        raise CalcError("the calculation is too long")
    env = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            value = _eval(stmt.value, env)
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    env[target.id] = value
                elif isinstance(target, ast.Tuple) and all(isinstance(t, ast.Name) for t in target.elts) \
                        and isinstance(value, tuple) and len(value) == len(target.elts):
                    env.update({t.id: v for t, v in zip(target.elts, value)})
                else:
                    raise CalcError("only plain names can be assigned")
        elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name) and type(stmt.op) in _BIN:
            env[stmt.target.id] = _eval(ast.BinOp(left=ast.Name(stmt.target.id, ast.Load()), op=stmt.op,
                                                  right=stmt.value), env)
        elif isinstance(stmt, ast.Expr):
            env["result"] = _eval(stmt.value, env)
        else:
            raise CalcError(f"{type(stmt).__name__} isn't allowed in a calculation")
    return env


_PLACEHOLDER = re.compile(r"\{(\w+)(?::([0-9.,+\- ]*[dfge%]?))?\}")


def fill(template: str, env: dict) -> str:
    """Put computed values into "{name}" / "{name:02d}" placeholders (only those — no attribute access)."""
    def sub(m):
        if m.group(1) not in env:
            raise CalcError(f"the answer mentions {{{m.group(1)}}}, which the calculation didn't compute")
        value = env[m.group(1)]
        if isinstance(value, float) and value.is_integer() and (not m.group(2) or m.group(2).endswith("d")):
            value = int(value)
        elif isinstance(value, float) and not m.group(2):
            value = round(value, 4)
        try:
            return format(value, m.group(2) or "")
        except (ValueError, TypeError):
            return str(value)
    return _PLACEHOLDER.sub(sub, template or "")


def verified_facts(question: str, ask_json):
    """The question's numbers, worked out in code: a sentence like "You have 20 apples.", or None when the question
    isn't a calculation, or the calculation failed (then the chat model answers on its own, as before)."""
    try:
        answer = ask_json([{"role": "system", "content": PROMPT}, {"role": "user", "content": question}], SCHEMA,
                          role="agent", max_tokens=400, temperature=0.0)
        if not answer.get("needs_math") or not answer.get("code"):
            return None
        env = run(answer["code"])
        facts = fill(answer.get("facts") or "", env).strip()
        return facts or None
    except Exception as e:   # never block an answer on this
        print(f"Verified math skipped: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return None
