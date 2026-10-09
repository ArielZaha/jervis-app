"""Programming: "write a Python program that ...", "write a function that ...", then "make it also ...", "run it
again". The code is never assumed to work:

    WRITE  -> the local coding model writes the program, non-interactive, ending with its OWN self-checks (asserts
              on known cases, then the line SELF-CHECK OK)
    RUN    -> it runs in its own project folder (Jervis's data folder, projects/<name>/), with a time limit;
              code that deletes files, starts programs or uses the network runs only after the user says yes
    INSPECT-> exit code 0, no traceback, the self-checks passed, and the output the request expects is there
    FIX    -> otherwise the model gets its code, the exact error and the output, and rewrites it
    RUN AGAIN, VERIFY -> up to MAX_FIXES times; the reply says only what was verified ("ran it, self-checks passed,
              it printed ...") or exactly what still fails.

Python and JavaScript run when their interpreter is installed (a packaged Jervis has no Python of its own for user
code, so the system's is used); other languages are written to a file and reported as not run.
"""
import os
import re
import shutil
import subprocess
import sys
import time

import paths

MAX_FIXES = 3
RUN_SECONDS = 20
CHECK_MARK = "SELF-CHECK OK"
LANGUAGES = {"python": (".py", ["python", "py", "python3"]), "javascript": (".js", ["node"])}

# A NEW program is asked for: "write a script...", "code me a function...", "create some python code..." — not "make the
# program window bigger" (an existing thing, with "the").
PROGRAM_REQUEST = re.compile(
    r"\b(?:write|create|make|build|code|generate|give me|i need|implement)\s+(?:me\s+|us\s+)?"
    r"(?!the\b|it\b|that\b|this\b|my\b|its\b)(?:\S+\s+){0,6}?"
    r"(?:program|script|function|class|algorithm|code|regex|module|cli|command[- ]line tool|python|javascript|"
    r"js|node(?:\.js)?)s?\b", re.I)
_FOLLOW_UP = re.compile(r"^(?:(?:now|ok|okay|and|also|then|please)\s+)*(?:make it|change it|have it|let it|"
                        r"it should|add|fix it|also make it|update it|modify it|can you make it|run it(?: again)?|"
                        r"rerun it|test it(?: again)?)\b", re.I)
# ...and about the program: "make it also print the sum", "add a function that...", "run it again" — never "make it
# louder" or "make it bigger" (the volume, a Blender model), which only happen to start the same way.
_ABOUT_CODE = re.compile(r"\b(?:print\w*|output|return\w*|function|program|script|code|loop|list|input|argument|"
                         r"variable|class|method|error|exception|bug|test|tests|sort\w*|count\w*|calculate|"
                         r"compute|file|csv|json|format|decimal|integer|string|faster|slower|recursive|it again|"
                         r"convert\w*|display|accept\w*|handle|support|validat\w*|round\w*|celsius|fahrenheit|"
                         r"numbers?|words?|lines?|values?|results?)\b", re.I)


class _FollowUp:
    @staticmethod
    def match(text: str):
        text = text or ""
        return _FOLLOW_UP.match(text) if _ABOUT_CODE.search(text) else None


FOLLOW_UP = _FollowUp()
RISKY = re.compile(r"\b(?:os\.(?:remove|unlink|rmdir|removedirs|system|popen|rename|replace|chmod)|shutil\.\w+|"
                   r"subprocess\.\w+|requests\.\w+|urllib\.\w+|socket\.\w+|http\.client|ctypes|winreg|"
                   r"open\([^)]*['\"][wa]b?['\"]|Path\([^)]*\)\.(?:unlink|rmdir|write_text|write_bytes)|"
                   r"fs\.(?:unlink|rm|rmdir|writeFile)|child_process|fetch\(|eval\(|exec\()")

WRITE_PROMPT = """You are an expert programmer. Write a complete, correct program for the request.
The program must run with NO user input (no input(); use example values, or command-line arguments with sensible
defaults), finish within a few seconds, and print its results clearly. It must END with self-checks of its main logic:
a few assert statements on cases whose answer you have worked out carefully, then print("{mark}"). (In JavaScript,
throw an Error when a check fails.) Use Python unless the request names another language.
Reply in exactly this form, nothing else:
File: <short_snake_case_name.ext>
Summary: <one sentence: what the program does>
Expected: <a short piece of text its output must contain, or leave empty>
```<language>
<the whole program>
```""".replace("{mark}", CHECK_MARK)

FIX_PROMPT = """The program below does not work yet. Find the real cause in the error and output. If a self-check
itself is wrong (its expected answer is miscalculated), the check is the bug: correct the check. Otherwise fix the
code. Keep it non-interactive and keep the self-checks ending with print("{mark}").
Reply in exactly this form, nothing else:
Diagnosis: <one sentence: what was wrong>
Expected: <a short piece of text its output must contain, or leave empty>
```<language>
<the whole corrected program>
```""".replace("{mark}", CHECK_MARK)

# (spaces only around the value: an empty "Expected:" must not swallow the next line as its value)
_FIELD = re.compile(r"^[ \t]*(File|Summary|Expected|Diagnosis)[ \t]*:[ \t]*(.*)$", re.I | re.M)
_BLOCK = re.compile(r"```([\w+-]*)[ \t]*\n(.*?)(?:\n```|\Z)", re.S)


def parse_answer(text: str) -> dict:
    """{"code", "language", "filename", "summary", "expected", "diagnosis"} from the AI's plain answer: a few labelled
    lines and ONE fenced code block (code inside JSON strings, with every newline and quote escaped, is where a small
    model loses its way)."""
    text = text or ""
    block = _BLOCK.search(text)
    code = block.group(2) if block else text
    outside = text[:block.start()] + text[block.end():] if block else ""
    fields = {k.lower(): v.strip() for k, v in _FIELD.findall(outside)}
    language = (block.group(1).lower() if block and block.group(1) else "") or ""
    language = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript"}.get(language, language)
    return {"code": code, "language": language, "filename": fields.get("file", ""),
            "summary": fields.get("summary", ""), "expected": fields.get("expected", ""),
            "diagnosis": fields.get("diagnosis", "")}


def ask_local(messages, temperature: float = 0.15) -> str:
    """The local coding model's plain-text answer."""
    import local_llm
    response = local_llm.chat(messages=messages, role="agent", max_tokens=3000, temperature=temperature)
    return response.choices[0].message.content or ""


_PROSE = re.compile(r"\b(?:story|poem|essay|letter|song|article|email|message|joke|speech|lyrics|summary)\b", re.I)
_CODE_NOUN = re.compile(r"\b(?:program|script|function|code|class|algorithm|regex)\b", re.I)


_DESCRIBES = re.compile(r"\b(?:should|will|would|output|outputs|prints?|returns?|the program|the function|a dictionary|"
                        r"a list|containing|consisting|which|that is|as keys|values)\b", re.I)


def literal_output(expected) -> str:
    """The "expected output" only when it's a piece of text the output can really contain ("2 + 3 = 5", "Sum: 129").
    A small model often writes a description there ("The output should be a dictionary of counts"), which no
    working program prints — the self-checks are what verify the logic."""
    text = " ".join(str(expected or "").split()).strip("\"'` ")
    if not text or len(text) > 60 or len(text.split()) > 8 or _DESCRIBES.search(text):
        return ""
    if text.endswith(".") and len(text.split()) > 3 and not re.search(r"[\d:=]", text):
        return ""   # "The longest word in the sentence." — a sentence about the output, not a piece of it
    return text


def is_program_request(text: str) -> bool:
    text = text or ""
    if _PROSE.search(text) and not _CODE_NOUN.search(text):
        return False   # "write a story about a python" is writing, not programming
    return bool(PROGRAM_REQUEST.search(text))


def interpreter(language: str):
    """The command that runs this language here, or None."""
    for name in LANGUAGES.get(language, (None, []))[1]:
        found = shutil.which(name)
        if found and not found.lower().endswith("windowsapps\\python.exe"):   # the Store stub only opens the Store
            return found
    if language == "python" and not getattr(sys, "frozen", False):
        return sys.executable
    return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (name or "program").lower()).strip("_")[:40] or "program"


def _fence(code: str) -> str:
    """The program as it should be saved: no Markdown fences, and no "filename: x.py" / "# File: x.py" header line a
    model sometimes puts at the top (a syntax error in Python)."""
    code = re.sub(r"^```[\w+-]*\s*\n?|\n?```\s*$", "", (code or "").strip()).strip()
    code = re.sub(r"^(?:file ?name|file)\s*:\s*\S+\s*\n+", "", code, flags=re.I)
    return code.strip() + "\n"


class CodeTask:
    """One programming request. Same controls as the other tasks (run/stop/state), so app.py can run it the same
    way; run() returns the sentence to say."""

    def __init__(self, request: str, ask=None, report=None, log=print, confirm=None, previous=None,
                 workspace: str = None, run_seconds: float = RUN_SECONDS, rerun: bool = False):
        self.request = " ".join((request or "").split())
        self.ask = ask or ask_local          # messages, temperature -> the AI's plain answer
        self.report = report or (lambda state: None)
        self.log = log
        self.confirm = confirm
        self.previous = previous          # {"path", "language", "code", "request"} of the last program, if any
        self.workspace = workspace
        self.run_seconds = run_seconds
        self.state = "starting"
        self.result = ""
        self.path = None
        self.language = "python"
        self.code = ""
        self.attempts = []                 # [(code, problem)]
        self.rerun = rerun and previous is not None   # "run it again": the same program, run and checked again
        self.expected = ""
        self.summary = ""
        self._stop = False

    def stop(self):
        self._stop = True

    def _report(self, state, detail=""):
        self.state = state
        try:
            self.report({"state": state, "detail": detail, "goal": self.request})
        except Exception:
            pass

    # ---------- the loop ----------
    def run(self) -> str:
        try:
            self._report("thinking", "Writing the program…")
            first = self._reload() if self.rerun else self._write()
            if first is None:
                return self._finish("error", "I couldn't write that program — the local AI didn't give me usable code.")
            runner = interpreter(self.language)
            if runner is None:
                return self._finish("completed", f"I wrote {self._where()}, but I can't run {self.language} on this "
                                                 "computer, so I couldn't test it.")
            risk = RISKY.search(self.code)
            if risk and not (self.confirm and self.confirm(f"This program uses “{risk.group(0)}” — it can change files "
                                                           "or reach the network. Can I run it?")):
                return self._finish("completed", f"I wrote {self._where()} but didn't run it, since it uses "
                                                 f"“{risk.group(0)}” and you didn't OK that.")
            for attempt in range(MAX_FIXES + 1):
                if self._stop:
                    return self._finish("stopped", f"Stopped. The program so far is in {self._where()}.")
                self._report("acting", "Running it…" if attempt == 0 else f"Running the fixed version ({attempt})…")
                ok, problem, output = self._run(runner)
                if ok:
                    return self._finish("completed", self._success(output, attempt))
                self.log(f"Program attempt {attempt + 1} failed: {problem[:300]}")
                self.attempts.append((self.code, problem))
                if attempt == MAX_FIXES:
                    break
                self._report("acting", "Fixing what went wrong…")
                if not self._fix(problem, output):
                    break
            last = self.attempts[-1][1] if self.attempts else "it didn't work"
            return self._finish("error", f"I wrote {self._where()} and tried {len(self.attempts)} times, but it still "
                                         f"fails: {last[:220]}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._finish("error", f"Something went wrong while programming ({type(e).__name__}: {str(e)[:120]}).")

    def _finish(self, state, message):
        self.result = message
        self._report(state, message)
        return message

    def _where(self) -> str:
        return f"{os.path.basename(self.path)} in {os.path.dirname(self.path)}" if self.path else "the program"

    # ---------- writing ----------
    def _write(self):
        user = f"Request: {self.request}"
        if self.previous:
            user = (f"The user's program so far ({self.previous['language']}), from the request "
                    f"“{self.previous['request']}”:\n{self.previous['code']}\n\nChange it as they now ask: "
                    f"{self.request}\nReply with the COMPLETE new program.")
        answer = self._ask([{"role": "system", "content": WRITE_PROMPT}, {"role": "user", "content": user}], 0.15)
        if answer is None:
            return None
        code = _fence(answer.get("code"))
        if len(code.strip()) < 10:
            return None
        self.language = (answer.get("language") or (self.previous or {}).get("language") or "python").lower()
        self.language = "javascript" if self.language in ("js", "node", "nodejs") else self.language
        self.code = code
        self.expected = literal_output(answer.get("expected"))
        self.summary = (answer.get("summary") or "").strip()
        ext = LANGUAGES.get(self.language, ("." + _slug(self.language)[:4], []))[0]
        if self.previous and self.previous.get("path"):
            self.path = self.previous["path"]
        else:
            stem = _slug(os.path.splitext(answer.get("filename") or "program")[0])
            folder = self.workspace or paths.data_dir("projects", stem)
            os.makedirs(folder, exist_ok=True)
            self.path = os.path.join(folder, stem + ext)
        self._save()
        return code

    def _reload(self):
        self.path, self.language = self.previous["path"], self.previous["language"]
        try:
            with open(self.path, encoding="utf-8") as f:
                self.code = f.read()   # as it is on disk now (the user may have edited it)
        except OSError:
            self.code = self.previous["code"]
        return self.code

    def _ask(self, messages, temperature):
        """The AI's answer, parsed; asked again once (a little warmer) when it came back without usable code; None
        if it still didn't — the caller says so instead of crashing."""
        for attempt in range(2):
            try:
                answer = parse_answer(self.ask(messages, temperature + 0.15 * attempt))
                if len(answer["code"].strip()) >= 10:
                    return answer
                self.log(f"The AI's answer had no code in it ({attempt + 1}).")
            except Exception as e:   # local_llm.LocalAIUnavailable: no AI, or an error
                self.log(f"Asking the AI for code failed ({attempt + 1}): {str(e)[:160]}")
        return None

    def _save(self):
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.code)

    def _fix(self, problem: str, output: str) -> bool:
        tried = "\n\n".join(f"Attempt {i}: {p[:600]}" for i, (_, p) in enumerate(self.attempts, 1))
        answer = self._ask([{"role": "system", "content": FIX_PROMPT}, {"role": "user", "content": (
            f"Request: {self.request}\n\nProgram ({self.language}):\n{self.code}\n\nWhat happened when it ran:\n"
            f"{problem}\n\nIts output (last part):\n{output[-1500:]}\n\nEarlier attempts:\n{tried}")}],
            0.2 + 0.1 * len(self.attempts))
        if answer is None:
            return False
        code = _fence(answer.get("code"))
        if len(code.strip()) < 10:
            return False
        self.log(f"Program fix: {(answer.get('diagnosis') or '')[:200]}")
        self.code = code
        self.expected = literal_output(answer.get("expected"))
        self._save()
        return True

    # ---------- running and inspecting ----------
    def _run(self, runner: str):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        try:
            done = subprocess.run([runner, self.path], cwd=os.path.dirname(self.path), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=self.run_seconds, env=env,
                                  stdin=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return False, f"It didn't finish within {self.run_seconds} seconds (an endless loop, or waiting for " \
                          "input it will never get).", ""
        output, errors = done.stdout or "", done.stderr or ""
        if done.returncode != 0 or "Traceback (most recent call last)" in errors:
            return False, f"It crashed (exit code {done.returncode}):\n{errors.strip()[-1200:] or output[-600:]}", output
        if CHECK_MARK not in output:
            return False, ("It ran, but its self-checks never finished (no “" + CHECK_MARK + "” at the end).\n"
                           + errors.strip()[-600:]), output
        flat = lambda t: " ".join(t.lower().split())   # "1 4 9" matches numbers printed one per line too
        if self.expected and flat(self.expected) not in flat(output):
            return False, f"It ran, but its output doesn't contain “{self.expected}”.", output
        return True, "", output

    def _success(self, output: str, fixes: int) -> str:
        shown = [l.strip() for l in output.replace(CHECK_MARK, "").strip().splitlines() if l.strip()]
        # the start and the end of what it printed (a total or a summary line usually comes last)
        picked = shown if len(shown) <= 5 else shown[:3] + ["…"] + shown[-2:]
        # in backticks: it's the program's exact output (shown as code, and never translated into another language)
        printed = " / ".join(picked)[:240].replace("`", "'")
        lines = len(self.code.strip().splitlines())
        fixed = f" It needed {fixes} fix{'es' if fixes > 1 else ''} to get there." if fixes else ""
        what = f" {self.summary.rstrip('.')}." if self.summary else ""
        done = "I ran it again" if self.rerun else f"I wrote {os.path.basename(self.path)} ({lines} lines)"
        return (f"Done — {done}.{what} It ran and its self-checks passed."
                + (f" It printed: `{printed}`." if printed else "") + fixed
                + " It's in your Jervis projects folder.")   # the full path is shown with the code (see app.py)

    def program(self) -> dict:
        """What a follow-up ("make it also ...") builds on."""
        return {"path": self.path, "language": self.language, "code": self.code, "request": self.request,
                "at": time.time()}
