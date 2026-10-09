"""Questions about the screen (screen_reader.py): answered from what was really read from the window — never a
guess — and the vision model is only used when a window exposes almost nothing to read. Fake screens only."""
import pytest

import computer_use
import screen_reader


class Screen(computer_use.Environment):
    def __init__(self, observation):
        self.observation = observation

    def available(self):
        return True, ""

    def observe(self):
        return self.observation


def element(i, role, name="", value="", focused=False, password=False):
    return computer_use.Element(i, role, name, value, (0, 0, 10, 10), focused=focused, password=password)


ERROR = computer_use.Observation(app="Code", window="app.py - jervis-app - Visual Studio Code", elements=[
    element(1, "text", "Traceback (most recent call last):"),
    element(2, "text", "NameError: name 'microphone' is not defined"),
    element(3, "button", "Run"),
    element(4, "text field", "Search", value=""),
    element(5, "text field", "Password", value="hunter2", password=True)])


@pytest.mark.parametrize("q", ["what's on my screen", "what does this error say?", "explain this error",
                               "what am I looking at", "can you see my screen", "why did this crash"])
def test_screen_questions_are_recognised(q):
    assert screen_reader.is_screen_question(q)


@pytest.mark.parametrize("q", ["make the screen brighter", "screen recording tips", "what's the weather"])
def test_other_sentences_are_not(q):
    assert not screen_reader.is_screen_question(q)


def test_the_answer_is_built_from_what_is_really_in_the_window_and_never_a_password():
    told = []
    reply = screen_reader.answer("explain this error", Screen(ERROR), None,
                                 lambda messages: told.append(messages[-1]["content"]) or "It's a NameError.")
    assert reply == "It's a NameError."
    assert "NameError: name 'microphone' is not defined" in told[0] and "Visual Studio Code" in told[0]
    assert "hunter2" not in told[0]


def test_a_window_with_almost_nothing_to_read_is_looked_at():
    blank = computer_use.Observation(app="blender", window="Blender", elements=[element(1, "button", "File")],
                                     screenshot=object())

    class Vision:
        def look(self, image, question):
            return "A 3D viewport with a red cube."
    told = []
    screen_reader.answer("what's on my screen", Screen(blank), Vision(),
                         lambda messages: told.append(messages[-1]["content"]) or "A red cube in Blender.")
    assert "red cube" in told[0]


def test_a_readable_window_is_not_sent_to_the_vision_model():
    class Vision:
        def look(self, image, question):
            raise AssertionError("should not look")
    ERROR.screenshot = object()
    screen_reader.answer("explain this error", Screen(ERROR), Vision(), lambda messages: "ok")
