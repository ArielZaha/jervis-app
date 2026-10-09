import math

import pytest

import pointer_motion as pm


def test_a_move_lands_exactly_on_the_target():
    points = pm.path((100, 100), (1300, 700))
    assert points[-1] == (1300, 700)


def test_a_tiny_move_is_a_single_set():
    assert pm.path((10, 10), (12, 11)) == [(12, 11)]


def test_longer_moves_take_longer_but_stay_quick():
    short, medium, long_ = (pm.duration_for(d) for d in (30, 400, 2500))
    assert pm.MIN_SECONDS <= short < medium < long_ <= pm.MAX_SECONDS


def test_the_glide_accelerates_then_decelerates():
    points = pm.path((0, 0), (1000, 0))
    steps = [math.dist(a, b) for a, b in zip(points, points[1:])]
    third = len(steps) // 3
    assert max(steps[third:2 * third]) > 3 * max(steps[:3])     # fast in the middle
    assert max(steps[third:2 * third]) > 3 * max(steps[-3:])    # slow on arrival


def test_the_path_is_a_gentle_arc_not_a_detour():
    points = pm.path((0, 0), (1000, 0))
    worst = max(abs(y) for _, y in points)
    assert 5 < worst <= 60


def test_the_same_move_is_the_same_path():
    assert pm.path((5, 5), (800, 300)) == pm.path((5, 5), (800, 300))


class FakePointer:
    def __init__(self, at, grab_after=None, grab_to=(0, 0)):
        self.at, self.sets, self.grab_after, self.grab_to = at, 0, grab_after, grab_to

    def set(self, x, y):
        self.at = (x, y)
        self.sets += 1
        if self.grab_after is not None and self.sets == self.grab_after:
            self.at = self.grab_to   # the user yanks the mouse

    def get(self):
        return self.at


def test_glide_moves_the_pointer_to_the_target():
    pointer = FakePointer((50, 50))
    pm.glide((50, 50), (900, 500), pointer.set, pointer.get, sleep=lambda s: None)
    assert pointer.at == (900, 500)
    assert pointer.sets > 10


def test_glide_stops_the_moment_the_user_grabs_the_mouse():
    pointer = FakePointer((50, 50), grab_after=5, grab_to=(1500, 20))
    with pytest.raises(pm.PointerTakenOver):
        pm.glide((50, 50), (900, 500), pointer.set, pointer.get, sleep=lambda s: None)
    assert pointer.sets == 5    # not one more move after the user took it


def test_a_pointer_takeover_mid_task_pauses_instead_of_failing_the_step():
    import computer_use

    class Env(computer_use.Environment):
        def available(self):
            return True, ""

        def observe(self):
            return computer_use.Observation(app="Notepad", window="Untitled", cursor=(0, 0), elements=[
                computer_use.Element(1, "button", "Save", rect=(10, 10, 40, 20))])

        def focus_moved(self):
            return False

        def click(self, point, button="left", double=False):
            raise pm.PointerTakenOver("You moved the mouse, so I didn't click.")

    class Message:
        def __init__(self, call):
            self.content, self.tool_calls = "", [call]

    calls = iter([("double_click", {"element": 1})])

    def ask_ai(messages, tools):
        import json
        import types
        name, args = next(calls)
        call = types.SimpleNamespace(function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=Message(call))])

    states = []
    task = computer_use.ComputerTask("open the file", env=Env(), ask_ai=ask_ai, report=lambda s: states.append(s),
                                     max_steps=3, log=lambda *_: None)
    original_pause = task.pause

    def pause_then_stop(why=""):
        original_pause(why)
        task.stop()

    task.pause = pause_then_stop
    result = task.run()
    assert any(s.get("state") == "paused" for s in states)
    assert result.startswith("Stopped")
