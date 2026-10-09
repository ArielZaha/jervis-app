"""The scene Jervis is working on (scene_state.py): the reference picture kept apart from the current scene, and
the words people use for things resolved by meaning, position as the camera sees it, and the conversation."""
import pytest

import scene_state


def current():
    return {
        "things": [
            {"name": "Villa", "kind": "villa", "role": "the main building", "size": [30, 12, 9]},
            {"name": "Garage", "kind": "garage", "role": None, "size": [4, 7, 3]},
            {"name": "Swimming Pool", "kind": "swimming pool", "size": [14, 5, 1.5]},
            {"name": "Palm Tree", "kind": "palm tree", "size": [5, 5, 8]},
            {"name": "Palm Tree 2", "kind": "palm tree", "size": [5, 5, 8]},
            {"name": "Palm Tree 3", "kind": "palm tree", "size": [5, 5, 8]},
            {"name": "Sun Lounger", "kind": "sun lounger", "size": [2, 0.7, 0.4]},
            {"name": "Sun Lounger 2", "kind": "sun lounger", "size": [2, 0.7, 0.4]},
        ],
        "frames": {"Palm Tree": [0.05, 0.3, 0.2, 0.7], "Palm Tree 2": [0.45, 0.35, 0.55, 0.65],
                   "Palm Tree 3": [0.8, 0.2, 0.95, 0.75], "Villa": [0.2, 0.3, 0.9, 0.7]},
        "cameras": [{"name": "Camera", "active": True}, {"name": "Camera 2", "active": False}],
        "env": {"set": {"time": "dusk"}},
    }


@pytest.mark.parametrize("phrase,expected", [
    ("the pool", ["Swimming Pool"]), ("the house", ["Villa"]), ("the main building", ["Villa"]),
    ("the left palm", ["Palm Tree"]), ("the rightmost palm tree", ["Palm Tree 3"]),
    ("the middle palm", ["Palm Tree 2"]), ("those loungers", ["Sun Lounger", "Sun Lounger 2"]),
    ("all the palm trees", ["Palm Tree", "Palm Tree 2", "Palm Tree 3"]), ("Garage", ["Garage"]),
])
def test_things_are_found_by_what_they_are_and_where_they_stand(phrase, expected):
    names, conf, question = scene_state.Resolver().resolve(phrase, current())
    assert names == expected and question is None and conf >= 0.6


def test_that_means_what_was_just_talked_about():
    r = scene_state.Resolver()
    names, _, _ = r.resolve("the left palm", current())
    r.remember(names)
    assert r.resolve("that", current())[0] == ["Palm Tree"]
    assert r.resolve("it", current())[0] == ["Palm Tree"]


def test_a_real_ambiguity_is_a_question_not_a_guess():
    cur = current()
    cur["frames"] = {}
    names, conf, question = scene_state.Resolver().resolve("the palm tree", cur)
    assert names == [] and "which one" in question.lower()


def test_something_that_isnt_there_is_said_so():
    names, conf, question = scene_state.Resolver().resolve("the windmill", current())
    assert names == [] and "can't find" in question


@pytest.mark.parametrize("phrase,expected", [("the other camera", "Camera 2"), ("the second camera", "Camera 2"),
                                             ("the camera", "Camera"), ("camera 2", "Camera 2")])
def test_cameras_are_found_too(phrase, expected):
    names, _, _ = scene_state.Resolver().resolve(phrase, current(), want_camera=True)
    assert names == [expected]


def test_the_reference_is_kept_apart_and_its_edits_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_state, "STORE", str(tmp_path))
    sid = scene_state.save_reference({"environment": {"time_of_day": {"value": "night"}}}, {"e1": "Villa"},
                                     "C:/pics/villa.jpg")
    scene_state.note_edit(sid, "make it sunrise", "Done: made it sunrise.")
    ref = scene_state.load_reference(sid)
    assert ref["image"] == "C:/pics/villa.jpg" and ref["built"] == {"e1": "Villa"}
    assert ref["visual_scene"]["environment"]["time_of_day"]["value"] == "night"   # the reference stays night...
    assert ref["edits"][0]["request"] == "make it sunrise"                        # ...the edit is what changed
    assert scene_state.load_reference("nope") is None


def test_the_current_scene_is_read_from_blender_or_is_empty():
    class Bridge:
        def run(self, code, timeout=15):
            assert "semantic_registry()" in code and "env_state()" in code
            return {"ok": True, "output": '{"things": [], "env": {}, "cameras": [], "scene_id": null, "frames": {}}'}

    class Broken:
        def run(self, code, timeout=15):
            return {"ok": False, "error": "boom"}
    assert scene_state.read_current(Bridge())["things"] == []
    assert scene_state.read_current(Broken()) == {}


def test_the_house_of_a_rebuilt_photo_is_its_main_building_unless_more_is_said():
    # the vehicle photo: its villa was tagged a 'building' (the main one), the neighbour's half-seen 'House'
    cur = {"things": [{"name": "Villa", "kind": "building", "role": "the main building"},
                      {"name": "House", "kind": "house"}, {"name": "Car", "kind": "car"}],
           "frames": {"Villa": [0.4, 0.2, 0.9, 0.5], "House": [0.9, 0.3, 1.0, 0.55]}}
    r = scene_state.Resolver()
    assert r.resolve("the house", cur)[0] == ["Villa"]
    assert r.resolve("the right house", cur)[0] == ["House"]
