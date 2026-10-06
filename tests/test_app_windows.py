"""Which open windows belong to an app (so "open X" brings it forward and "close X" closes it), and the small parsers
around opening and closing apps (app_launcher.py)."""
import pytest

import app_launcher
import winctl

WINDOWS = {   # hwnd: (title, program)
    1: ("Untitled - Notepad", "notepad.exe"),
    2: ("Inbox - Gmail - Google Chrome", "chrome.exe"),
    3: ("app.py - jarvis-app - Visual Studio Code", "code.exe"),
    4: ("Friends - Discord", "discord.exe"),
    5: ("Jarvis", "jarvis.exe"),
    6: ("Program Manager", "explorer.exe"),
    7: ("How to use Discord - Google Chrome", "chrome.exe"),
    8: ("Document1 - Word", "winword.exe"),
    9: ("(Unsaved) - Blender 4.5.3 LTS", r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"),
    10: ("Blender", r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
}


def _path(hwnd):
    program = WINDOWS[hwnd][1]
    return program if "\\" in program else rf"C:\Apps\{program}"


@pytest.fixture
def fake_windows(monkeypatch):
    monkeypatch.setattr(app_launcher.osal, "IS_WIN", True)
    monkeypatch.setattr(winctl, "list_windows", lambda: [(h, t) for h, (t, _p) in WINDOWS.items()])
    monkeypatch.setattr(winctl, "window_process_path", _path)
    monkeypatch.setattr(winctl, "window_process_name", lambda h: _path(h).rsplit("\\", 1)[-1].lower())


@pytest.mark.parametrize("app,expected", [
    ("Notepad", [1]), ("Google Chrome", [2, 7]), ("Visual Studio Code", [3]), ("Discord", [4]), ("Word", [8]),
    ("Spotify", []), ("Blender 4.5", [9]), ("Blender 4.3", [10]), ("Blender", [9, 10]),
])
def test_windows_are_matched_to_their_app(fake_windows, app, expected):
    assert [h for h, _t in app_launcher.app_windows(app)] == expected


def test_jarvis_and_the_desktop_are_never_matched(fake_windows):
    assert app_launcher.app_windows("Jarvis") == []
    assert app_launcher.app_windows("explorer") == []   # "Program Manager" is the desktop itself


def test_this_app_is_the_one_behind_jarvis(fake_windows, monkeypatch):
    monkeypatch.setattr(winctl, "list_windows", lambda: [(5, "Jarvis"), (3, "x - Visual Studio Code‬")])
    hwnd, _title, friendly = app_launcher.front_app_window()
    assert hwnd == 3 and friendly == "Visual Studio Code"


def test_open_brings_an_already_open_app_forward(fake_windows, monkeypatch):
    focused = []
    monkeypatch.setattr(winctl, "focus", lambda hwnd: focused.append(hwnd) or True)
    monkeypatch.setattr(app_launcher, "installed_apps", lambda: {"discord": "Discord"})
    monkeypatch.setattr(app_launcher, "_launch", lambda name: pytest.fail("started a second copy"))
    assert app_launcher.open_application("discord") == "Discord is already open, so I brought it to the front."
    assert focused == [4]


def test_a_missing_app_is_said_plainly(monkeypatch):
    monkeypatch.setattr(app_launcher, "installed_apps", lambda: {"notepad": "Notepad"})
    assert app_launcher.open_application("fakeappxyz") == "I couldn't find an app called fakeappxyz."


@pytest.mark.parametrize("said,target", [
    ("close discord", "discord"), ("quit chrome please", "chrome"), ("exit vs code", "vs code"),
    ("close this app", "this app"), ("close the current window", "the current window"),
    ("close it", None), ("close this", None), ("I closed the door", None),
])
def test_close_requests(said, target):
    assert app_launcher.parse_close_request(said) == target


@pytest.mark.parametrize("answer,picked", [
    ("4.5", "Blender 4.5"), ("Blender 4.3", "Blender 4.3"), ("the second one", "Blender 4.5"), ("the newest", "Blender 4.5"),
    ("first", "Blender 4.3"), ("blender", None), ("pizza", None),
])
def test_answers_to_which_one(answer, picked):
    assert app_launcher.pick_choice(answer, ["Blender 4.3", "Blender 4.5"]) == picked


def test_start_menu_entries_left_behind_by_an_uninstall_are_never_offered(monkeypatch, tmp_path):
    real = tmp_path / "Blender 4.5" / "blender-launcher.exe"
    real.parent.mkdir()
    real.write_text("")
    rows = [{"Name": "Blender 4.3", "AppID": r"{6D809377-6AF0-444B-8957-A3773F02200E}\Blender 4.3\blender-launcher.exe"},
            {"Name": "Blender 4.5", "AppID": r"{6D809377-6AF0-444B-8957-A3773F02200E}\Blender 4.5\blender-launcher.exe"},
            {"Name": "Notepad", "AppID": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"}]
    import json
    monkeypatch.setattr(app_launcher.osal, "run_powershell", lambda script, timeout=30: (0, json.dumps(rows), ""))
    monkeypatch.setattr(app_launcher, "_known_folder", lambda guid: str(tmp_path))
    monkeypatch.setattr(app_launcher, "_cache", {"at": 0.0, "apps": {}})
    monkeypatch.setattr(app_launcher, "BROKEN_APPS", {})
    monkeypatch.setattr(app_launcher.platform, "system", lambda: "Windows")
    assert app_launcher.resolve_app("blender") == ("ok", "Blender 4.5")         # nothing to choose between
    assert app_launcher.resolve_app("notepad") == ("ok", "Notepad")             # Store apps aren't file paths
    assert app_launcher.resolve_app("blender 4.3") == ("missing", None)         # never quietly opens 4.5 instead
    assert "uninstalled" in app_launcher.open_application("blender 4.3")


def test_windows_problem_with_shortcut_box_ends_the_wait(monkeypatch):
    closed = []
    monkeypatch.setattr(app_launcher.osal, "IS_WIN", True)
    monkeypatch.setattr(winctl, "list_windows", lambda: [(77, "Problem with Shortcut")])
    monkeypatch.setattr(winctl, "window_process_name", lambda h: "explorer.exe")
    monkeypatch.setattr(winctl, "close_window", lambda h: closed.append(h) or True)
    assert app_launcher._wait_for_app_window("Blender 4.3", before=set(), seconds=5) == "broken"
    assert closed == [77]
