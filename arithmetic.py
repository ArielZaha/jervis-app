"""Plain arithmetic, answered by Jarvis himself: "what's 12 times 12", "15% of 80", "square root of 144".

A language model can get sums wrong and takes a second to answer; this is exact and immediate. Only pure arithmetic
is taken (numbers and operations, nothing else in the sentence), so anything with a unit, a variable or a wider
question still goes where it always went (the equation solver, the graphs, the AI).
"""
import ast
import math
import re

import functions

_LEAD = re.compile(r"^(?:(?:hey |ok |okay )?(?:jarvis|jervis)[ ,]+)?(?:(?:please|can you|could you|quickly) )*"
                   r"(?:what(?:'s| is|s)|how much is|calculate|compute|work out|evaluate|tell me|solve|do the math[: ]*)?\s*", re.I)
_TAIL = re.compile(r"(?:\s*(?:equals?|is equal to|=|\?|please|is|make))*\s*[.!?]*$", re.I)
_FRACTIONS = {"half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4, "fifth": 5, "fifths": 5,
              "sixth": 6, "sixths": 6, "eighth": 8, "eighths": 8, "tenth": 10, "tenths": 10}
_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
        ast.Mod: lambda a, b: a % b}


class _NotArithmetic(Exception):
    pass


def _expression(question: str) -> str:
    """The sentence as a Python arithmetic expression, or raise _NotArithmetic."""
    q = re.sub(r"(?<=\d),(?=\d{3}\b)", "", question.lower())                 # 1,250 -> 1250
    q = re.sub(r"\b(?:a|one) (half|third|quarter|fifth|sixth|eighth|tenth) of\b", r"1 \1 of", q)
    q = re.sub(r"\bhalf of\b", "1 half of", q)
    q = functions.normalize(q)
    q = q.replace("^", "**").replace("×", "*").replace("÷", "/")
    q = re.sub(r"(\d(?:[\d.]*))\s*(?:%|percent)\s+off\s+", r"(1-\1/100)*", q)     # 20% off 50
    q = re.sub(r"(\d(?:[\d.]*))\s*(?:%|percent)\s+of\s+", r"(\1/100)*", q)        # 15% of 80
    q = re.sub(r"(\d(?:[\d.]*))\s*(?:%|percent)(?!\w)", r"(\1/100)", q)
    for word, parts in _FRACTIONS.items():
        q = re.sub(rf"(\d(?:[\d.]*))\s+{word}\s+of\s+", rf"(\1/{parts})*", q)       # 2 thirds of 90
    q = re.sub(r"\bsqrt\s*\(?\s*(\d[\d.]*)\s*\)?", r"sqrt(\1)", q)
    q = re.sub(r"\bmod(?:ulo)?\b", "%", q)
    if re.search(r"[a-z_]", q.replace("sqrt", "")) or not re.search(r"\d", q):
        raise _NotArithmetic
    return q.strip()


def _value(node):
    if isinstance(node, ast.Expression):
        return _value(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _value(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_value(node.left), _value(node.right))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        base, power = _value(node.left), _value(node.right)
        if abs(power) > 200 or abs(base) > 1e12:
            raise OverflowError
        return base ** power
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "sqrt" and len(node.args) == 1:
        value = _value(node.args[0])
        if value < 0:
            raise ValueError("the square root of a negative number isn't a real number")
        return math.sqrt(value)
    raise _NotArithmetic


def _say(value) -> str:
    if isinstance(value, complex) or value != value or abs(value) == float("inf"):
        raise OverflowError
    if abs(value - round(value)) < 1e-9 and abs(value) < 1e15:
        return f"{round(value):,}"
    return f"{value:,.6f}".rstrip("0").rstrip(".") if abs(value) >= 0.0001 else f"{value:.3g}"


def answer(text: str):
    """What to say for a piece of pure arithmetic ("12 times 12 is 144."), else None."""
    asked = _TAIL.sub("", _LEAD.sub("", (text or "").strip(), count=1)).strip()
    if not asked or len(asked) > 120:
        return None
    try:
        expression = _expression(asked)
        if not re.search(r"[-+*/%]|sqrt|\*\*", expression.lstrip("-+ ")):
            return None                                  # a bare number is not a sum
        if re.fullmatch(r"\s*\d{1,4}\s*/\s*\d{1,4}\s*", asked):
            return None                                  # "9/11", "24/7": a date or a saying, not a division
        value = _value(ast.parse(expression, mode="eval"))
    except ZeroDivisionError:
        return "You can't divide by zero."
    except ValueError as e:
        return f"That has no real answer: {e}."
    except OverflowError:
        return "That number is too big for me to write out."
    except (_NotArithmetic, SyntaxError, TypeError, RecursionError, MemoryError):
        return None
    shown = re.sub(r"\s+", " ", asked)
    return f"{shown[0].upper() + shown[1:]} is {_say(value)}."
