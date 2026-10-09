"""Exact math for questions with numbers: the calculation interpreter only does arithmetic, and the verified result
reaches the chat model as a fact."""
import pytest

import reasoning


def test_plain_arithmetic_with_named_steps():
    env = reasoning.run("start = 3\nbought = 2 * 12\ngiven = 7\napples = start + bought - given")
    assert env["apples"] == 20


def test_time_of_day_with_divmod_and_fstrings():
    env = reasoning.run("depart = 15*60 + 40\narrive = depart + 2*60 + 35\nhours, minutes = divmod(arrive, 60)\n"
                        "shown = f'{hours - 12}:{minutes:02d} pm'")
    assert env["shown"] == "6:15 pm"


def test_print_and_math_functions():
    env = reasoning.run("import_free = math.sqrt(16) + round(2.6)\nprint(import_free * 2)")
    assert env["result"] == 14


@pytest.mark.parametrize("code", [
    "import os", "__import__('os').system('dir')", "open('x')", "x = ().__class__", "x = 'a' * 10",
    "for i in range(10): x = i", "x = 9 ** 9 ** 9", "x = 1 / 0", "def f(): pass", "x = eval('1')",
    "x = math.__dict__", "x = [y for y in (1, 2)]", "lambda: 1", "x = 10 ** 400",
])
def test_anything_but_arithmetic_is_refused(code):
    with pytest.raises(reasoning.CalcError):
        reasoning.run(code)


def test_answer_placeholders_are_filled_without_attribute_access():
    env = {"apples": 20.0, "price": 51.52, "minutes": 5.0}
    assert reasoning.fill("You have {apples} apples, {price} each, {minutes:02d} min.", env) == \
        "You have 20 apples, 51.52 each, 05 min."
    assert reasoning.fill("{apples.__class__}", env) == "{apples.__class__}"   # not a placeholder: left as text
    with pytest.raises(reasoning.CalcError):
        reasoning.fill("You have {pears} pears.", env)


@pytest.mark.parametrize("text,expected", [
    ("If I have 3 apples and buy 2 dozen more, then give away 7, how many do I have?", True),
    ("I'm 3 times as old as my son. In 12 years I'll be twice as old. How old am I?", True),
    ("Dinner cost 184 shekels for 4 people with a 12 percent tip, how much each?", True),
    ("What's the capital of Japan?", False),
    ("Set a timer for 5 minutes", False),
    ("Play the top 10 songs on Spotify", False),
    ("Solve x^2 + 3x - 4 = 0", False),
])
def test_which_questions_get_exact_math(text, expected):
    assert reasoning.looks_quantitative(text) is expected


def test_verified_facts_end_to_end_with_a_fake_model():
    def ask(messages, schema, **kw):
        return {"needs_math": True, "code": "apples = 3 + 2*12 - 7", "facts": "You have {apples} apples."}
    assert reasoning.verified_facts("how many apples", ask) == "You have 20 apples."


def test_a_broken_calculation_never_blocks_the_answer():
    def ask(messages, schema, **kw):
        return {"needs_math": True, "code": "import os", "facts": "x"}
    assert reasoning.verified_facts("how many apples", ask) is None


def test_an_answer_sentence_pasted_into_the_code_is_dropped():
    env = reasoning.run("total = 184 * 1.12\neach = total / 4\n{each} shekels per person.")
    assert env["each"] == pytest.approx(51.52)
