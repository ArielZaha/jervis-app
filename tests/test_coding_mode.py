"""Coding Mode inside Jarvis (app.py): a spoken or typed request becomes a job for the engine, the answer says only what
happened, follow-ups reach the same project, and the AI's write_code tool gets the real result back. The AI itself
is a stand-in here, and so are the apps (the sandbox records "open VS Code" instead of doing it)."""
import os
import time

import pytest

import sandbox

app = None
PLAN = ("PROJECT: calc\nLANGUAGE: Python\nSUMMARY: A small calculator.\nRUN: python calc.py\nTEST: python -m unittest\nNEEDS: none\n"
        "FILES:\ncalc.py | the calculator\ntests/test_calc.py | its tests\n")
FILES = ("=== FILE: calc.py ===\ndef add(a, b):\n    return a + b\n=== END FILE ===\n"
         "=== FILE: tests/test_calc.py ===\nimport unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n=== END FILE ===\n")
CHANGE = "SUMMARY: Added subtraction.\n=== FILE: calc.py ===\ndef add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n=== END FILE ===\n"


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    app.real_code_chat = imported._code_chat   # the tests below replace it; the last ones test it
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    sandbox.reset()
    monkeypatch.setenv("CODE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(app.coder, "HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(app.coder, "BACKUP_DIR", str(tmp_path / "backups"))
    app.code_state.update(open=False, job=None, project=None, busy=False, at=0.0)
    monkeypatch.setattr(app, "ws_loop", None)
    asked = []

    def chat(messages, max_tokens):
        user = messages[1]["content"]
        asked.append(user)
        return PLAN if "Plan the smallest" in user else CHANGE if "existing project" in user else FILES
    monkeypatch.setattr(app, "_code_chat", chat)
    return asked


def test_a_spoken_request_writes_the_project_and_opens_it(tmp_path):
    reply = app.handle_direct_command("Jarvis, write a Python calculator and open it in VS Code.")
    folder = tmp_path / "projects" / "calc"
    assert (folder / "calc.py").read_text() == "def add(a, b):\n    return a + b\n" and (folder / "tests" / "test_calc.py").exists()
    assert reply.startswith("I wrote calc: 2 files. 2 syntax checks passed. I haven't run it or its tests")
    assert reply.endswith(f"It's open in Visual Studio Code. The project folder is {folder}.")
    assert any("Visual Studio Code" in action or "bin/code" in action for action in sandbox.actions)   # VS Code was asked to open it


def test_without_a_destination_jarvis_just_builds_it_and_says_where(tmp_path):
    reply = app.handle_direct_command("write a Python script that organizes my Downloads folder")
    folder = tmp_path / "projects" / "calc"
    assert reply.startswith("I wrote calc: 2 files.") and reply.endswith(f"It's in {folder}.") and (folder / "calc.py").exists()
    assert not any("Visual Studio Code" in a or "bin/code" in a or a.startswith("run open") for a in sandbox.actions)   # nothing is opened unasked


def test_no_language_is_needed_the_ai_chooses_it(fresh, tmp_path):
    reply = app.handle_direct_command("make a snake game")
    assert reply.startswith("I wrote calc: 2 files.") and "Choose the language that fits the request best" in fresh[0]
    assert app.code_state["job"].language == "Python"                 # what the AI's plan said, shown as it is


def test_follow_ups_change_the_same_project_and_show_the_changes(tmp_path, fresh):
    app.handle_direct_command("write a Python calculator and save the project locally")
    reply = app.handle_direct_command("Now add a subtract function")
    assert reply.startswith("I changed 1 file in calc.") and "def sub(a, b)" in (tmp_path / "projects" / "calc" / "calc.py").read_text()
    assert list(app.code_state["job"].diffs) == ["calc.py"] and sorted(os.listdir(tmp_path / "projects")) == ["calc"]   # the same folder, no second project
    assert "def add(a, b)" in fresh[-1]                               # the AI was shown the existing file before changing it


def test_run_the_tests_is_the_only_thing_that_runs_the_code(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(app.coder, "run_tests", lambda root, declared="": ran.append(root) or {"status": "failed", "command": "python -m unittest discover -s tests",
                                                                                                   "output": "AssertionError: -1 != 5\nFAILED (failures=1)", "sandboxed": True})
    app.handle_direct_command("write a Python calculator and save the project locally")
    assert ran == []                                                  # written and checked, never executed
    reply = app.handle_direct_command("run the tests")
    assert ran == [str(tmp_path / "projects" / "calc")]
    assert reply.startswith("The tests of calc failed (in a sandbox, without network). The last line says: FAILED (failures=1)")


def test_fixing_after_failed_tests_shows_the_ai_their_output_and_runs_them_again(tmp_path, monkeypatch, fresh):
    results = iter([{"status": "failed", "command": "t", "output": "AssertionError: -1 != 5\nFAILED (failures=1)", "sandboxed": True},
                    {"status": "passed", "command": "t", "output": "Ran 1 test\n\nOK", "sandboxed": True}])
    monkeypatch.setattr(app.coder, "run_tests", lambda root, declared="": next(results))
    app.handle_direct_command("write a Python calculator and save the project locally")
    app.handle_direct_command("run the tests")
    reply = app.handle_direct_command("fix the errors in the code")
    assert "AssertionError: -1 != 5" in fresh[-1]                     # the real failure went to the AI
    assert "I ran the tests again. The tests of calc passed (in a sandbox, without network): OK" in reply


def test_save_it_somewhere_else_and_a_place_that_cannot_be_used(tmp_path, monkeypatch):
    app.handle_direct_command("write a Python calculator and save the project locally")
    reply = app.handle_direct_command("Put this code into a Word document.")
    assert "The Word document is" in reply and (tmp_path / "projects" / "calc" / "calc.docx").exists()
    for name in ("GOOGLE_DRIVE_CLIENT_ID", "GOOGLE_DRIVE_CLIENT_SECRET", "GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    drive = app.handle_direct_command("save it to Google Drive")
    assert drive.startswith("Google Drive isn't connected yet.") and "in your Google Drive" not in drive


def test_asking_to_save_code_that_does_not_exist():
    assert app.handle_direct_command("Put this code into a Word document.") == "I haven't written any code yet. Tell me what to build, and where to put it."


def test_one_job_at_a_time():
    app.code_state.update(busy=True, job=app.coder.Job(id="x", request="r", name="shop"))
    assert app.handle_direct_command("write a Python calculator and open it in VS Code") == "I'm still working on shop. Ask again when it's done."


def test_a_failure_is_said_as_a_failure(monkeypatch, tmp_path):
    def down(messages, max_tokens):
        raise ConnectionError("Connection error.")
    monkeypatch.setattr(app, "_code_chat", down)
    reply = app.handle_direct_command("write a Python calculator and open it in VS Code")
    assert reply == "I couldn't reach the AI. Check the internet connection and try again."
    assert not any("Visual Studio Code" in a or "bin/code" in a for a in sandbox.actions) and not app.code_state["busy"]


def test_other_features_are_untouched():
    assert app.handle_direct_command("what's 12 times 12") == "12 times 12 is 144."
    assert app.handle_code_command("write a poem about the sea") is None
    assert app.handle_code_command("write a short story in word") is None
    assert app.handle_code_command("make it louder") is None


# ---- the AI's tool ----
def test_the_tool_gives_the_ai_the_real_result(tmp_path):
    result = app.TOOL_FUNCTIONS["write_code"](request="a python calculator")
    assert result.startswith("I wrote calc: 2 files. 2 syntax checks passed.") and result.endswith(f"It's in {tmp_path / 'projects' / 'calc'}.")
    assert app.TOOL_FUNCTIONS["write_code"](request="x") == "Nothing was written: the request didn't say what to build. Ask the user what they want."
    assert any(t["function"]["name"] == "write_code" for t in app.TOOLS) and "write_code" in app.ACTION_TOOLS


@pytest.mark.parametrize("said,offered", [
    ("could you build me a little app that tracks my reading", True), ("I want you to make a website for my band", True),
    ("I had to solve a hard problem at work", False), ("Word is a program by Microsoft", False),
    ("my brother made a website yesterday", False), ("write a poem about my app", False),
])
def test_the_tool_is_only_offered_for_coding(said, offered):
    assert app.is_code_request(said) is offered


# ---- what the window asks for ----
def window(monkeypatch):
    sent = []
    monkeypatch.setattr(app, "send_ui_update_once", sent.append)
    return sent


def test_the_window_gets_what_it_needs_to_draw_itself(monkeypatch):
    sent = window(monkeypatch)
    app.coding_window_says({"type": "code_info"})
    info = sent[-1]["data"]
    assert sent[-1]["type"] == "coding_info" and len(info["languages"]) >= 30 and info["model"] == app.code_model_name()
    assert [d["key"] for d in info["destinations"]] == ["vscode", "local", "word", "notes", "gdrive", "zip"]
    assert all(d["available"] or d["why"] for d in info["destinations"])   # a place that can't be used says why


def test_the_form_is_only_a_description_and_progress_is_real(monkeypatch, tmp_path):
    sent = window(monkeypatch)
    app.coding_window_says({"type": "code_start", "request": "a calculator for the command line"})
    phases = [m["data"]["phase"] for m in sent if m["type"] == "coding"]
    assert phases[0] == "planning" and "writing" in phases and "checking" in phases and phases[-1] == "done"
    assert (tmp_path / "projects" / "calc" / "calc.py").exists() and not sandbox.actions   # made, nothing opened
    app.coding_window_says({"type": "code_start", "request": "x"})
    assert sent[-1] == {"type": "coding_note", "message": "Say what to build, in a sentence or two."}


def test_the_window_reads_a_file_but_only_inside_the_project(monkeypatch, tmp_path):
    sent = window(monkeypatch)
    app.handle_direct_command("write a Python calculator and save the project locally")
    app.coding_window_says({"type": "code_file", "path": "calc.py"})
    assert sent[-1]["content"] == "def add(a, b):\n    return a + b\n"
    (tmp_path / "secret.txt").write_text("private")
    app.coding_window_says({"type": "code_file", "path": "../../secret.txt"})
    assert sent[-1]["content"] == "" and "couldn't read that file" in sent[-1]["error"]


# ---- which AI writes the code ----
def test_code_is_written_by_groqs_larger_model_whoever_jarvis_talks_with(monkeypatch):
    monkeypatch.setattr(app, "GROQ_KEY", "a-key")
    monkeypatch.setattr(app, "LLM_BACKEND", "ollama")          # the chat AI is the local one: code still goes to Groq
    monkeypatch.setattr(app, "_code_model_refused", False)
    assert app.code_model_name() == "openai/gpt-oss-120b" == app.DEFAULT_CODE_MODEL
    monkeypatch.setattr(app, "GROQ_KEY", "")
    assert app.code_model_name().endswith("(on this computer)")   # no key at all: said as it is


class FakeGroq:
    """Stands in for Groq's client: answers from a list (an Exception in it is raised)."""

    def __init__(self, answers):
        self.answers, self.asked = list(answers), []
        self.chat = self
        self.completions = self

    def with_options(self, **_kwargs):
        return self

    def create(self, **kwargs):
        self.asked.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        message = type("M", (), {"content": answer})
        return type("R", (), {"choices": [type("C", (), {"message": message})]})


def test_a_rate_limit_is_waited_out_and_said(monkeypatch):
    groq = FakeGroq([RuntimeError("Error code: 429 - Rate limit reached ... Please try again in 7.5s."), "PROJECT: x"])
    slept, shown = [], []
    monkeypatch.setattr(app, "GROQ_KEY", "a-key")
    monkeypatch.setattr(app, "_code_model_refused", False)
    monkeypatch.setattr(app, "groq_client", groq)
    monkeypatch.setattr(app.time, "sleep", slept.append)
    monkeypatch.setattr(app, "send_ui_update_once", shown.append)
    app.code_state.update(busy=True, job=app.coder.Job(id="j", request="r"))
    assert app.real_code_chat([{"role": "user", "content": "plan"}], 4000) == "PROJECT: x"
    assert slept == [8.5] and shown[-1]["data"]["step"] == "Waiting 8 seconds for the AI's free-plan limit"
    assert [k["model"] for k in groq.asked] == ["openai/gpt-oss-120b"] * 2 and groq.asked[0]["reasoning_effort"] == "low"


def test_a_model_this_key_no_longer_has_falls_back_and_says_which(monkeypatch):
    groq = FakeGroq([RuntimeError("Error code: 404 - The model `openai/gpt-oss-120b` does not exist or you do not have access to it."), "ok"])
    monkeypatch.setattr(app, "GROQ_KEY", "a-key")
    monkeypatch.setattr(app, "_code_model_refused", False)
    monkeypatch.setattr(app, "groq_client", groq)
    assert app.real_code_chat([{"role": "user", "content": "write"}], 12000) == "ok"
    assert [k["model"] for k in groq.asked] == ["openai/gpt-oss-120b", app.GROQ_MODEL] and app.code_model_name() == app.GROQ_MODEL


def test_an_ai_that_keeps_failing_is_an_error_not_a_loop(monkeypatch):
    groq = FakeGroq([ConnectionError("Connection error.")])
    monkeypatch.setattr(app, "GROQ_KEY", "a-key")
    monkeypatch.setattr(app, "_code_model_refused", False)
    monkeypatch.setattr(app, "groq_client", groq)
    with pytest.raises(ConnectionError):
        app.real_code_chat([{"role": "user", "content": "write"}], 12000)
    assert len(groq.asked) == 1
