""""Close the X tab": Jarvis finds the tab the user means among all open tabs and closes exactly that one.
Chrome itself is simulated (the AppleScript calls are replaced), so no real tab is ever touched."""
import pytest

import sandbox
import youtube_browser as yb
from youtube_browser import Tab, pick_tabs, short_title, tab_match_score

TABS = [
    Tab(1, "11", False, "Bohemian Rhapsody - Queen (Official Video) - YouTube", "https://www.youtube.com/watch?v=fJ9rUzIMcZQ"),
    Tab(1, "12", False, "Inbox (3) - arielizaha@gmail.com - Gmail", "https://mail.google.com/mail/u/0/#inbox"),
    Tab(1, "13", True, "Breaking Bad | Netflix", "https://www.netflix.com/watch/70196252"),
    Tab(1, "14", False, "Easy Pasta Carbonara Recipe | Bon Appétit", "https://www.bonappetit.com/recipe/simple-carbonara"),
    Tab(2, "21", True, "python - How do I sort a dict by value? - Stack Overflow", "https://stackoverflow.com/questions/613183"),
    Tab(2, "22", False, "Albert Einstein - Wikipedia", "https://en.wikipedia.org/wiki/Albert_Einstein"),
    Tab(2, "23", False, "Cheap flights to Rome | Skyscanner", "https://www.skyscanner.net/routes/tlv/rome"),
    Tab(2, "24", False, "weather tel aviv - Google Search", "https://www.google.com/search?q=weather+tel+aviv"),
]
app = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


def closes(said: str):
    command = app.parse_close_command(said)
    chosen = pick_tabs(command["target"], TABS, command["mode"])
    return [t.id for t in chosen]


@pytest.mark.parametrize("said, tab", [
    ("close the YouTube tab", "11"), ("close the Bohemian Rhapsody tab", "11"), ("close the Queen video tab", "11"),
    ("close gmail tab", "12"), ("close my email tab", "12"), ("close the Breaking Bad tab", "13"), ("close Netflix", "13"),
    ("close the pasta recipe tab", "14"), ("close the carbonara tab", "14"), ("close the stack overflow tab", "21"),
    ("close the Wikipedia tab about Einstein", "22"), ("close the Einstein tab", "22"), ("close the flights tab", "23"),
    ("close the flight tab", "23"), ("close the tab with the flights to Rome", "23"), ("close the weather tab", "24"),
    ("close the google search tab", "24"), ("close the google tab", "24"),
])
def test_the_tab_the_user_means_is_found(said, tab):
    assert closes(said) == [tab]


@pytest.mark.parametrize("said", ["close the X tab", "close the art tab", "close the pizza tab", "close the Spotify tab"])
def test_a_tab_that_is_not_open_is_never_confused_with_another(said):
    """Whole words and whole sites only: "x" is not netflix.com, "art" is not "start"."""
    assert closes(said) == []


def test_a_known_site_is_not_matched_by_its_words_alone():
    # "Google" means a Google search tab — not Gmail, even though Gmail lives at mail.google.com
    assert tab_match_score("google", "Inbox - Gmail", "https://mail.google.com/mail/u/0/") == 0


def test_with_several_matches_the_one_in_front_of_the_user_is_closed():
    tabs = [Tab(2, "a", True, "Lofi beats - YouTube", "https://www.youtube.com/watch?v=1"),
            Tab(1, "b", False, "Cats - YouTube", "https://www.youtube.com/watch?v=2"),
            Tab(1, "c", True, "Dogs - YouTube", "https://www.youtube.com/watch?v=3")]
    assert [t.id for t in pick_tabs("youtube", tabs, "one")] == ["c"]          # front window, active tab
    assert [t.id for t in pick_tabs("youtube", tabs[:2], "one")] == ["b"]      # else the front window's
    assert sorted(t.id for t in pick_tabs("youtube", tabs, "all")) == ["a", "b", "c"]


def test_the_closed_tab_is_named_briefly():
    assert short_title("Bohemian Rhapsody - Queen (Official Video) - YouTube") == "Bohemian Rhapsody - Queen (Official Video)"
    assert short_title("Breaking Bad | Netflix") == "Breaking Bad"
    assert len(short_title("A " * 80)) <= 60


def test_close_tabs_closes_exactly_the_chosen_tab(monkeypatch):
    calls = []
    def fake_osascript(script, *args, timeout=10):
        calls.append((script, args))
        if script is yb._LIST_TABS:
            return "\n".join(f"{t.window}\t{t.id}\t{'true' if t.active else 'false'}\t{t.title}\t{t.url}" for t in TABS)
        if script is yb._CLOSE_TAB_IDS:
            return str(len(args))
        raise AssertionError("unexpected script")
    monkeypatch.setattr(yb, "_chrome_running", lambda: True)
    monkeypatch.setattr(yb, "_osascript", fake_osascript)
    monkeypatch.setattr(yb.osal, "IS_WIN", False)

    assert yb.close_tabs("pasta recipe", "one") == "Closed “Easy Pasta Carbonara Recipe”."
    assert calls[-1] == (yb._CLOSE_TAB_IDS, ("14",))
    assert yb.close_tabs("pizza", "one") == "I don't see a pizza tab open."
    assert calls[-1][0] is yb._LIST_TABS   # nothing was closed


def test_the_whole_command_through_jarvis(monkeypatch):
    monkeypatch.setattr(yb, "_chrome_running", lambda: True)
    closed = []
    def fake_osascript(script, *args, timeout=10):
        if script is yb._LIST_TABS:
            return "\n".join(f"{t.window}\t{t.id}\t{'true' if t.active else 'false'}\t{t.title}\t{t.url}" for t in TABS)
        closed.extend(args)
        return str(len(args))
    monkeypatch.setattr(yb, "_osascript", fake_osascript)
    monkeypatch.setattr(yb.osal, "IS_WIN", False)
    assert app.handle_direct_command("Close the Wikipedia tab about Einstein") == "Closed “Albert Einstein”."
    assert closed == ["22"]
