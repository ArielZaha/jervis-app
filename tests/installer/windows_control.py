"""Computer control on a real Windows desktop (run in CI): Jervis types into Notepad through the whole loop.

The AI is scripted (type, then done), but everything else is real: UI Automation reads Notepad, the cursor is put in
its text area, SendInput types, and the result is read back from the window. Notepad is closed without saving.
    python tests/installer/windows_control.py
"""
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import computer_use  # noqa: E402
import screen_windows  # noqa: E402
import winctl  # noqa: E402

TEXT = "Hello from Jervis, typed on Windows."
EDITABLE = ("document", "text field")


def scripted(*steps):
    remaining = list(steps)

    def ask(messages, tools):
        name, args = remaining.pop(0) if remaining else ("done", {"summary": "done"})
        call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])
    return ask


def main() -> int:
    notepad = subprocess.Popen(["notepad.exe"])
    try:
        for _ in range(20):
            windows = winctl.find_windows("Notepad", browsers_only=False)
            if windows:
                winctl.focus(windows[0][0])
                break
            time.sleep(0.5)
        time.sleep(1.5)
        env = screen_windows.WindowsScreen()
        print("available:", env.available())
        observation = env.observe()
        print(f"in front: {observation.app!r} / {observation.window!r}, {len(observation.elements)} elements")
        for element in observation.elements[:25]:
            print("  ", element.describe())
        target = next((e for e in observation.elements if e.role in EDITABLE), None)
        if target is None:
            print("FAIL: no text area found in Notepad")
            return 1
        task = computer_use.ComputerTask("type a sentence", env,
                                         scripted(("type_text", {"element": target.id, "text": TEXT}),
                                                  ("done", {"summary": "Typed it."})), max_steps=4)
        started = time.time()
        result = task.run()
        print(f"result: {result!r} ({task.state}, {time.time() - started:.1f}s)")
        after = env.observe()
        typed = " ".join(e.value for e in after.elements if e.role in EDITABLE)
        print(f"text area now: {typed[:120]!r}")
        if TEXT not in typed:
            print("FAIL: the sentence isn't in Notepad")
            return 1
        print("PASS")
        return 0
    finally:
        notepad.kill()   # never saved: nothing is left behind


if __name__ == "__main__":
    sys.exit(main())
