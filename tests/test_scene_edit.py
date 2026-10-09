"""Editing the scene that's there, in plain words (scene_edit.py): each request becomes calls that CHANGE what
exists (one fog, retuned; the one sun moved) with checks that prove the change — or a question when the words could
mean several things."""
import pytest

import scene_edit
import scene_state
from test_scene_state import current as base_scene


def scene(**env):
    cur = base_scene()
    cur["things"] += [{"name": "Beach", "kind": "beach"}, {"name": "Sea", "kind": "ocean"},
                      {"name": "Waterfall", "kind": "waterfall"}, {"name": "Car", "kind": "car"},
                      {"name": "Path", "kind": "path"}, {"name": "Shop", "kind": "storefront"}]
    cur["env"] = {"set": env, "live": {"fog_density": env.get("fog", {}).get("density", 0.0) if env.get("fog") else 0.0,
                                       "lights_on": 0}}
    return cur


def plan(text, cur=None, resolver=None):
    return scene_edit.plan(text, cur or scene(), resolver or scene_state.Resolver())


def code(text, cur=None):
    p = plan(text, cur)
    assert p is not None and p["steps"], (text, p)
    return "\n".join(s["code"] for s in p["steps"])


@pytest.mark.parametrize("text,expected", [
    ("Add fog", "fog('fog')"),
    ("Make it foggy", "fog('fog')"),
    ("Put fog near the ground", "fog('ground fog')"),
    ("Add morning mist", "fog('mist')"),
    ("Make the mountains fade into the fog", "fog('haze'"),
    ("Remove the fog", "fog(remove=True)"),
])
def test_fog_is_one_volume_added_or_cleared(text, expected):
    assert expected in code(text)


def test_existing_fog_is_thickened_or_thinned_not_duplicated():
    cur = scene(fog={"kind": "fog", "density": 0.04})
    assert "fog(factor=1.7)" in code("Make the fog thicker", cur)
    assert "fog(factor=0.5)" in code("Make the fog subtle", cur)
    checks = plan("Make the fog thicker", cur)["steps"][0]["checks"]
    assert checks == [{"type": "env", "path": "live.fog_density", "op": ">", "value": 0.04}]


@pytest.mark.parametrize("text,look", [("Make it sunrise", "sunrise"), ("Make it sunset", "sunset"),
                                       ("Make it nighttime", "night"), ("make it night time", "night"),
                                       ("Make it morning", "morning"), ("change it to golden hour", "golden hour")])
def test_time_of_day_changes_the_whole_environment(text, look):
    p = plan(text)
    assert f"time_of_day({look!r})" in p["steps"][0]["code"]
    assert p["steps"][0]["checks"] == [{"type": "env", "path": "set.time", "op": "==", "value": look}]


@pytest.mark.parametrize("text,expected", [
    ("Add rain", "weather('rain', intensity=1.00)"), ("Make it snow", "weather('snow'"),
    ("Make it stormy", "weather('storm'"), ("Remove the rain", "weather('clear')"),
    ("Make the pavement wet", "wet(1.0)"), ("Make it cloudy", "weather('cloudy'"),
])
def test_weather_replaces_the_weather_there_was(text, expected):
    assert expected in code(text)


@pytest.mark.parametrize("text,env,expected", [
    ("Add clouds", {}, "sky_clouds(cover=0.40)"),
    ("Add a few clouds", {}, "sky_clouds(cover=0.20)"),
    ("More clouds", {"clouds": 0.4}, "sky_clouds(cover=0.64)"),
    ("Fewer clouds", {"clouds": 0.4}, "sky_clouds(cover=0.20)"),
    ("Remove the clouds", {"clouds": 0.4}, "sky_clouds(remove=True)"),
])
def test_clouds_are_a_layer_in_the_sky_not_an_overcast_day(text, env, expected):
    # a few clouds on a sunny day are not weather('cloudy') (which greys the whole sky over)
    got = code(text, scene(**env))
    assert expected in got and "weather(" not in got


def test_heavier_rain_builds_on_the_rain_there_is():
    assert "intensity=1.80" in code("Make the rain heavier", scene(weather="rain", weather_intensity=1.0))


@pytest.mark.parametrize("text,expected", [
    ("Make the ocean calmer", "water_motion('Sea', strength_factor=0.5)"),
    ("Make the waves stronger", "water_motion('Sea', strength_factor=1.8)"),
    ("Make the waterfall faster", "water_motion('Waterfall', speed_factor=1.6)"),
    ("Slow down the waves", "water_motion('Sea', speed_factor=0.55)"),
    ("Make the pool calmer", "water_motion('Swimming Pool', strength_factor=0.5)"),
])
def test_water_is_made_calmer_or_stronger_by_kind(text, expected):
    assert expected in code(text)


def test_wind_and_vegetation():
    assert "wind_strength(1.0)" in code("Add wind")
    assert "wind_strength(factor=1.7)" in code("Make the trees move more", scene(wind_strength=1.0))
    assert "wind_strength(0)" in code("Stop the wind")


@pytest.mark.parametrize("text,expected", [
    ("Stop the animation", "pause_motion()"), ("Remove all animation", "remove_animation()"),
    ("Resume the animation", "resume_motion()"), ("Stop the car", "remove_animation('Car')"),
])
def test_animation_is_paused_removed_or_stopped_per_thing(text, expected):
    assert expected in code(text)


@pytest.mark.parametrize("text,expected", [
    ("Turn on the house lights", "lights_set('Villa', on=True)"),
    ("Turn off the pool lights", "lights_set('Swimming Pool', on=False)"),
    ("Make the storefront brighter", "lights_set('Shop', on=True, factor=1.6)"),
    ("Warm up the house lights", "warmth=2300"),
    ("Add lights along the path", "path_lights('Path')"),
    ("Add a soft light from the sunset direction", "fill_light(direction='sun', soft=True)"),
])
def test_lights_change_by_what_they_light(text, expected):
    assert expected in code(text)


@pytest.mark.parametrize("text,expected", [
    ("Make the walls white", "material_edit(None, 'walls', color='white')"),
    ("Make the roof darker", "material_edit(None, 'roof', darker=0.35)"),
    ("Make the windows more reflective", "material_edit(None, 'windows', reflective=True)"),
    ("Make the pool water clearer", "material_edit(None, 'water', clearer=True)"),
    ("Make the grass greener", "material_edit(None, 'grass', greener=0.5)"),
    ("Make the wood darker", "material_edit(None, 'wood', darker=0.35)"),
    ("Make the concrete rougher", "roughness=0.9"),
])
def test_materials_change_on_the_parts_meant(text, expected):
    assert expected in code(text)


def test_windows_darker_by_day_is_the_glass_but_at_night_the_glow():
    assert "material_edit(None, 'windows'" in code("Make the windows darker", scene(time="day"))
    assert "lights_set" in code("Make the windows darker", scene(time="night"))


@pytest.mark.parametrize("text,expected", [
    ("Move the camera closer", "camera_edit('Camera', closer=0.65)"),
    ("Show me the house from behind", "subject='Villa', side='behind'"),
    ("Put the camera behind the house", "side='behind'"),
    ("Show the house from the left", "side='left'"),
    ("Give me a low-angle shot", "low=True"),
    ("Make it a drone shot", "drone=True"),
    ("Use a wider lens", "lens_factor=0.7"),
    ("Use a 24mm lens", "lens=24.0"),
    ("Switch to the other camera", "switch_camera('Camera 2')"),
    ("Create a second camera looking at the pool", "camera('Camera 3', 'Swimming Pool', 'wide')"),
])
def test_cameras_move_safely_by_what_is_asked(text, expected):
    c = code(text)
    assert expected in c, c


def test_every_camera_move_is_checked_for_safety():
    p = plan("Move the camera closer")
    assert {"type": "camera_safe", "object": "Camera"} in p["steps"][0]["checks"]


def test_moving_a_thing_takes_what_belongs_to_it():
    assert "move_with('Villa', direction='back'" in code("Move the villa back")
    c = code("Move the pool closer to the house")
    assert "move_with('Swimming Pool', toward='Villa')" in c


def test_make_it_cinematic_is_a_treatment_not_a_random_effect():
    c = code("Make it cinematic")
    assert "camera_move('Camera', 'push_in', 'Villa'" in c and "cinematic_look()" in c


def test_ambiguous_words_get_a_question():
    cur = scene()
    cur["frames"] = {}
    p = plan("Remove the palm tree animation", cur)
    assert p["question"] and not p["steps"]


def test_requests_that_are_not_edits_are_left_to_the_other_planners():
    for text in ("create a house", "add two palm trees beside the pool", "orbit around the villa",
                 "make a 10-second cinematic where the camera approaches the villa", "save it"):
        assert plan(text) is None, text
