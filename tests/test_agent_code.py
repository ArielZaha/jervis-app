"""Programming (agent_code.py): the program is really run, and only reported as working when it ran cleanly and its
own self-checks passed; a failing program is fixed from its real error and run again. The AI is faked; the programs
really run (Python)."""
import sys

import pytest

import agent_code


GOOD = 'def add(a, b):\n    return a + b\n\nprint("2 + 3 =", add(2, 3))\nassert add(2, 2) == 4\nprint("SELF-CHECK OK")\n'
BROKEN = 'def add(a, b):\n    return a - b\n\nprint("2 + 3 =", add(2, 3))\nassert add(2, 2) == 4\nprint("SELF-CHECK OK")\n'


def as_text(d: dict) -> str:
    """An answer in the plain form the coding prompts ask for (labelled lines, then one fenced code block)."""
    lines = [f"File: {d.get('filename', '')}", f"Summary: {d.get('summary', '')}",
             f"Expected: {d.get('expected_output', '')}", f"Diagnosis: {d.get('diagnosis', '')}",
             f"```{d.get('language', 'python')}", d["code"], "```"]
    return "\n".join(lines)


class AI:
    """Answers in order (in the plain answer form); records what it was told."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.told = []

    def __call__(self, messages, temperature=0.15):
        self.told.append(messages[-1]["content"])
        return as_text(self.answers.pop(0))


@pytest.fixture
def python(monkeypatch):
    monkeypatch.setattr(agent_code, "interpreter", lambda language: sys.executable if language == "python" else None)


def task(tmp_path, ai, **kw):
    return agent_code.CodeTask("write a python program that adds two numbers", ai, log=lambda m: None,
                               workspace=str(tmp_path), **kw)


def test_a_working_program_is_reported_with_what_it_printed(tmp_path, python):
    ai = AI({"language": "python", "filename": "adder.py", "code": GOOD, "expected_output": "2 + 3 = 5",
             "summary": "Adds two numbers."})
    t = task(tmp_path, ai)
    result = t.run()
    assert t.state == "completed" and "self-checks passed" in result and "2 + 3 = 5" in result
    assert (tmp_path / "adder.py").read_text(encoding="utf-8") == GOOD


def test_a_failing_program_is_fixed_from_its_real_error_and_run_again(tmp_path, python):
    ai = AI({"language": "python", "filename": "adder.py", "code": BROKEN, "expected_output": "", "summary": ""},
            {"code": GOOD, "diagnosis": "subtracted instead of adding", "expected_output": ""})
    t = task(tmp_path, ai)
    result = t.run()
    assert t.state == "completed" and "1 fix" in result
    assert "AssertionError" in ai.told[1]           # the fix was asked with the real error in hand


def test_it_never_claims_success_when_it_still_fails(tmp_path, python):
    ai = AI(*([{"language": "python", "filename": "adder.py", "code": BROKEN, "expected_output": ""}] +
              [{"code": BROKEN, "diagnosis": "?", "expected_output": ""}] * agent_code.MAX_FIXES))
    t = task(tmp_path, ai)
    result = t.run()
    assert t.state == "error" and "still fails" in result and "Done" not in result


def test_output_that_misses_what_was_expected_is_a_failure(tmp_path, python):
    ai = AI({"language": "python", "filename": "adder.py", "code": GOOD, "expected_output": "2 + 3 = 6"},
            {"code": GOOD, "diagnosis": "the expectation was wrong", "expected_output": "2 + 3 = 5"})
    t = task(tmp_path, ai)
    assert "self-checks passed" in t.run()
    assert "doesn't contain" in ai.told[1]


def test_a_program_that_never_ends_is_stopped_and_fixed(tmp_path, python):
    ai = AI({"language": "python", "filename": "loop.py", "code": "while True:\n    pass\n", "expected_output": ""},
            {"code": GOOD, "diagnosis": "endless loop", "expected_output": ""})
    t = task(tmp_path, ai, run_seconds=2)
    assert "self-checks passed" in t.run()
    assert "didn't finish" in ai.told[1]


def test_code_that_can_change_files_runs_only_with_the_users_ok(tmp_path, python):
    risky = 'import os\nos.remove("x.txt")\nprint("SELF-CHECK OK")\n'
    asked = []
    ai = AI({"language": "python", "filename": "cleanup.py", "code": risky, "expected_output": ""})
    t = task(tmp_path, ai, confirm=lambda q: asked.append(q) or False)
    result = t.run()
    assert asked and "os.remove" in asked[0]
    assert "didn't run it" in result


def test_a_language_it_cannot_run_is_written_and_said_so(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_code, "interpreter", lambda language: None)
    ai = AI({"language": "rust", "filename": "main.rs", "code": 'fn main() { println!("hi"); }', "expected_output": ""})
    result = task(tmp_path, ai).run()
    assert "can't run rust" in result


def test_a_follow_up_changes_the_last_program(tmp_path, python):
    first = task(tmp_path, AI({"language": "python", "filename": "adder.py", "code": GOOD, "expected_output": ""}))
    first.run()
    ai = AI({"code": GOOD.replace('print("SELF-CHECK OK")', 'print("sum of 1..3 =", 6)\nprint("SELF-CHECK OK")'),
             "expected_output": "sum of 1..3"})
    follow = agent_code.CodeTask("make it also print the sum of 1 to 3", ai, log=lambda m: None,
                                 previous=first.program())
    assert "self-checks passed" in follow.run()
    assert follow.path == first.path and "program so far" in ai.told[0]


def test_run_it_again_reruns_the_file_as_it_is_now(tmp_path, python):
    first = task(tmp_path, AI({"language": "python", "filename": "adder.py", "code": GOOD, "expected_output": ""}))
    first.run()
    again = agent_code.CodeTask("run it again", AI(), log=lambda m: None, previous=first.program(), rerun=True)
    assert again.run().startswith("Done — I ran it again")


@pytest.mark.parametrize("text,expected", [
    ("write a python program that prints the first 10 primes", True),
    ("can you write a function that reverses a string", True),
    ("write me a script to rename files", True),
    ("write me a story about a dragon", False),
    ("what's a python", False),
    ("make the program window bigger", False),
])
def test_what_counts_as_a_programming_request(text, expected):
    assert agent_code.is_program_request(text) is expected


def test_a_story_about_a_python_is_not_programming():
    assert not agent_code.is_program_request("write a story about a python")
    assert agent_code.is_program_request("write a python script that prints a short poem")


@pytest.mark.parametrize("text,follow", [("make it also print their sum", True), ("run it again", True),
                                         ("add a function that counts vowels", True), ("fix it", False),
                                         ("make it louder", False), ("make it bigger", False),
                                         ("make it red", False)])
def test_only_follow_ups_about_the_program_change_it(text, follow):
    assert bool(agent_code.FOLLOW_UP.match(text)) is follow


def test_a_filename_header_line_never_breaks_the_program(tmp_path, python):
    ai = AI({"language": "python", "filename": "adder.py", "code": "filename: adder.py\n\n" + GOOD, "expected_output": ""})
    t = task(tmp_path, ai)
    assert "self-checks passed" in t.run()


def test_an_ai_answer_cut_off_twice_is_said_plainly_not_crashed_on(tmp_path, python):
    def ask(messages, temperature=0.15):
        raise RuntimeError("the local AI didn't answer")
    t = task(tmp_path, ask)
    result = t.run()
    assert t.state == "error" and "couldn't write that program" in result


def test_a_plain_answer_is_read_into_its_parts():
    answer = agent_code.parse_answer("File: primes.py\nSummary: Prints primes.\nExpected: 2, 3, 5\n"
                                     "```python\nprint(2, 3, 5)\nprint('SELF-CHECK OK')\n```\nSome chatter after.")
    assert answer["filename"] == "primes.py" and answer["expected"] == "2, 3, 5" and answer["language"] == "python"
    assert answer["code"] == "print(2, 3, 5)\nprint('SELF-CHECK OK')"


def test_a_wrong_self_check_is_fixed_as_the_bug(tmp_path, python):
    wrong_check = 'words = "the cat the dog the end".split()\nassert words.count("the") == 2\nprint("SELF-CHECK OK")\n'
    right = wrong_check.replace("== 2", "== 3")
    ai = AI({"language": "python", "filename": "count.py", "code": wrong_check, "expected_output": ""},
            {"code": right, "diagnosis": "the check miscounted: 'the' appears 3 times", "expected_output": ""})
    t = task(tmp_path, ai)
    assert "self-checks passed" in t.run()
    assert "AssertionError" in ai.told[1]


def test_an_empty_field_never_takes_the_next_line():
    answer = agent_code.parse_answer("File: a.py\nSummary:\nExpected:\n```python\nprint('SELF-CHECK OK')\n```")
    assert answer["summary"] == "" and answer["expected"] == "" and answer["filename"] == "a.py"


@pytest.mark.parametrize("expected,kept", [("2 + 3 = 5", "2 + 3 = 5"), ("Sum: 129", "Sum: 129"),
                                           ("The output should be a dictionary of word counts.", ""),
                                           ("A dictionary with words as keys", "")])
def test_only_literal_expected_output_is_checked(expected, kept):
    assert agent_code.literal_output(expected) == kept


def test_a_sentence_about_the_output_is_not_checked_for():
    assert agent_code.literal_output("The longest word in the sentence.") == ""
    assert agent_code.literal_output("Longest word: elephant") == "Longest word: elephant"
