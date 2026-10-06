"""Jarvis was called Jervis: settings, data folders and the wake install made under the old name carry over."""
import json
import os

import paths
import settings

OLD = "JE" + "RVIS_"   # spelled in two parts so a project-wide rename never touches it


def test_old_setting_keys_are_kept_under_the_new_names(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "RESOURCE_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"version": 1, "values": {
        OLD + "PHONE_CONTROL": "on", OLD + "USER_NAME": "Ariel", "JARVIS_SPEAK_VOLUME": "40", OLD + "SPEAK_VOLUME": "90",
        "GROQ_API_KEY": "k"}}))
    for key in ("JARVIS_PHONE_CONTROL", "JARVIS_USER_NAME", "JARVIS_SPEAK_VOLUME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(OLD + "AUDIO", "off")
    settings.load()
    assert os.environ["JARVIS_PHONE_CONTROL"] == "on"
    assert os.environ["JARVIS_USER_NAME"] == "Ariel"
    assert os.environ["JARVIS_SPEAK_VOLUME"] == "40"     # a value already under the new name wins
    assert os.environ["JARVIS_AUDIO"] == "off"           # an old variable from outside still counts
    saved = json.loads((tmp_path / "settings.json").read_text())["values"]
    assert not any(k.startswith(OLD) for k in saved)     # the file itself now uses the new names
    assert saved["JARVIS_PHONE_CONTROL"] == "on" and saved["GROQ_API_KEY"] == "k"


def test_the_old_data_folder_is_taken_over_not_replaced_by_an_empty_one(tmp_path):
    old, new = tmp_path / "Jervis", tmp_path / "Jarvis"
    old.mkdir()
    (old / "phone_devices.json").write_text("{}")
    assert paths.adopt_renamed(str(new), str(old)) == str(new)
    assert (new / "phone_devices.json").exists() and not old.exists()
    # both exist (e.g. the new name was created meanwhile): the new one is used, the old one isn't touched
    old.mkdir()
    assert paths.adopt_renamed(str(new), str(old)) == str(new) and old.exists()


def test_an_old_folder_that_cannot_be_moved_keeps_being_used(tmp_path, monkeypatch):
    old, new = tmp_path / "Jervis", tmp_path / "Jarvis"
    old.mkdir()
    monkeypatch.setattr(os, "rename", lambda a, b: (_ for _ in ()).throw(OSError("in use")))
    assert paths.adopt_renamed(str(new), str(old)) == str(old)
