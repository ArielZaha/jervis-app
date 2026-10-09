"""What things are and what naturally happens around them (semantics.py): labels mapped onto kinds, and behaviour
rules that add only what a scene justifies — each effect with its reason."""
import pytest

import semantics


@pytest.mark.parametrize("label,kind", [
    ("coconut palms", "palm tree"), ("palm", "palm tree"), ("a tall oak tree", "tree"), ("boutique", "shop"),
    ("Restaurant facade", "shop"), ("infinity pool", "swimming pool"), ("street lamp", "street lamp"),
    ("SUV", "car"), ("sun loungers", "sun lounger"), ("parasols", "umbrella"), ("the ocean", "ocean"),
    ("waves", "ocean"), ("stepping stones", "path"), ("a sofa", "sofa"), ("modern villa", "villa"),
    ("pedestrians", "person"), ("table lamp", "floor lamp"), ("waterfall", "waterfall"), ("nothing at all", None),
])
def test_labels_map_onto_kinds(label, kind):
    assert semantics.canonical(label) == kind


def test_kinds_carry_their_meaning():
    assert {"wind_reactive", "fronds"} <= semantics.tags("palm tree")
    assert {"commercial", "storefront", "lightable_interior"} <= semantics.tags("shop")
    assert "water_waves" in semantics.tags("ocean") and "water_calm" in semantics.tags("swimming pool")
    assert semantics.category("villa") == "building" and semantics.spec("villa")["asset"] == "house"
    assert semantics.typical_size("car")[0] > 4


@pytest.mark.parametrize("kind,area,depth,expected", [
    ("house", 0.3, "midground", "high"), ("rock", 0.001, "background", "low"), ("bench", 0.06, "foreground", "medium"),
])
def test_priority_depends_on_how_much_a_thing_matters_in_this_view(kind, area, depth, expected):
    assert semantics.priority(kind, area, depth) == expected


def effects(things, **env):
    ctx = semantics.context_of(things, env)
    return {(b["effect"], b.get("mode")): b for b in semantics.behaviours(ctx)}


def test_a_shop_at_night_glows_from_inside_with_its_signs_but_not_by_day():
    things = [{"name": "Shop", "kind": "shop"}, {"name": "Sign", "kind": "sign"}]
    night = effects(things, time_of_day="night")
    assert ("interior_glow", None) in night and ("sign_glow", None) in night
    assert night[("interior_glow", None)]["targets"] == ["Shop"] and night[("interior_glow", None)]["why"]
    assert ("interior_glow", None) not in effects(things, time_of_day="midday")


def test_water_moves_as_its_kind_does():
    things = [{"name": "Sea", "kind": "ocean"}, {"name": "Pool", "kind": "swimming pool"},
              {"name": "River", "kind": "river"}, {"name": "Falls", "kind": "waterfall"}]
    e = effects(things, time_of_day="day")
    assert e[("water", "waves")]["targets"] == ["Sea"]
    assert e[("water", "ripples")]["targets"] == ["Pool"]
    assert ("water", "flow") in e and ("water", "falls") in e


def test_vegetation_moves_only_when_there_is_wind_or_a_sea_breeze():
    things = [{"name": "Oak", "kind": "tree"}]
    assert ("sway", None) not in effects(things, wind="none")
    assert ("sway", None) in effects(things, wind="light")
    coast = [{"name": "Palm", "kind": "palm tree"}]
    breeze = effects(coast, wind="none", setting="coastal")
    assert breeze[("sway", None)]["strength"] == 0.5


def test_weather_brings_what_goes_with_it_and_nothing_is_invented():
    things = [{"name": "Sea", "kind": "ocean"}, {"name": "Oak", "kind": "tree"}]
    storm = effects(things, weather="storm")
    assert ("rain", None) in storm and ("wet", None) in storm and ("clouds", None) in storm
    assert storm[("water", "waves")]["strength"] == 2.0   # rough water, not the everyday waves
    calm = effects([{"name": "House", "kind": "house"}], weather="clear", time_of_day="day")
    assert not calm   # a house on a clear day: nothing to add


def test_a_street_at_night_without_lamps_gets_street_lights():
    e = effects([{"name": "Road", "kind": "road"}], time_of_day="night")
    assert ("add_street_lights", None) in e


def test_each_effect_appears_once():
    things = [{"name": "Sea", "kind": "ocean"}]
    out = semantics.behaviours(semantics.context_of(things, {"weather": "storm"}))
    keys = [(b["effect"], tuple(b["targets"]), b.get("mode")) for b in out]
    assert len(keys) == len(set(keys))
