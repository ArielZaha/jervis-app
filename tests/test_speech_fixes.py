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


# ---------- the assistant's own name, however it was heard ----------
import pytest as _pytest
import speech_fixes as _sf


@_pytest.mark.parametrize("heard,expected", [("Hey Gravis, make it red", "Hey jervis, make it red"),
                                              ("okay gervis", "okay jervis"), ("wake up Jervais", "wake up jervis"),
                                              ("Gravis, open Spotify", "jervis, open Spotify")])
def test_misheard_names_after_a_greeting_wake_jervis(heard, expected):
    assert _sf.fix_wake_name(heard) == expected


@_pytest.mark.parametrize("said", ["customer service is bad", "my friend Travis called", "I'm nervous about it"])
def test_the_same_words_inside_a_sentence_are_left_alone(said):
    assert _sf.fix_wake_name(said) == said


@_pytest.mark.parametrize("said,unfinished", [("put a tree next to the", True), ("open spotify and", True),
                                              ("make the roof green", False), ("what time is it", False),
                                              ("um", False)])
def test_sentences_cut_off_by_a_pause(said, unfinished):
    assert _sf.sounds_unfinished(said) is unfinished
