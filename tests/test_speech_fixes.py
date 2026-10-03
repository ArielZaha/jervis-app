"""Speech-recognition mishearings that matter for computer control: "Blender" in particular (see BUG 12)."""
import pytest

from speech_fixes import fix_names


@pytest.mark.parametrize("heard,expect", [
    ("open blingdon", "open blender"),
    ("open blendor", "open blender"),
    ("take control and open blinder 4.5", "take control and open blender 4 5"),
])
def test_blender_mishearings_are_corrected(heard, expect):
    assert fix_names(heard) == expect


def test_unrelated_text_with_no_name_in_it_is_left_alone():
    assert fix_names("create a cube") == "create a cube"
