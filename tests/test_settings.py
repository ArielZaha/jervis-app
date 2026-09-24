"""Settings: first start, the old .env, a damaged file, validation, and secrets never shown back."""
import importlib
import json
import os

import pytest


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A clean settings module on an empty data folder, with no Jervis variables in the environment."""
    for key in list(os.environ):
        if key.startswith(("JERVIS_", "GROQ_", "LLM_", "OLLAMA_", "WEATHER_", "SPOTIFY_", "OPENAI_", "GOOGLE_",
                           "WHATSAPP_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("JERVIS_DATA_DIR", str(tmp_path))
    import paths
    import settings
    importlib.reload(paths)
    monkeypatch.setattr(paths, "RESOURCE_DIR", str(tmp_path / "app"))   # no project .env leaks into the test
    importlib.reload(settings)
    return settings, tmp_path


def test_defaults_mean_local_ai_and_no_key(fresh):
    settings, _ = fresh
    settings.load()
    assert os.environ["LLM_BACKEND"] == "ollama"
    assert settings.get("GROQ_API_KEY") == ""


def test_env_file_is_imported_once_and_keeps_online_ai(fresh):
    settings, data = fresh
    (data / ".env").write_text("GROQ_API_KEY=gsk_test_value_1234  # mine\nWHATSAPP_READING=off\n")
    settings.load()
    stored = json.loads((data / "settings.json").read_text())["values"]
    assert stored["GROQ_API_KEY"] == "gsk_test_value_1234"   # inline comment stripped
    assert stored["LLM_BACKEND"] == "auto"                    # someone with a key keeps the online AI
    assert os.environ["WHATSAPP_READING"] == "off"


def test_damaged_file_is_set_aside_not_lost(fresh):
    settings, data = fresh
    (data / "settings.json").write_text("{ this is not json")
    settings.load()
    assert settings.get("LLM_BACKEND") == "ollama"   # started from defaults
    kept = [p for p in os.listdir(data) if p.startswith("settings.json.damaged-")]
    assert kept and (data / kept[0]).read_text() == "{ this is not json"


def test_old_flat_file_is_migrated(fresh):
    settings, data = fresh
    (data / "settings.json").write_text(json.dumps({"WEATHER_CITY": "Haifa"}))   # a version-less file
    settings.load()
    assert settings.get("WEATHER_CITY") == "Haifa"


def test_invalid_values_are_refused_and_nothing_is_saved(fresh):
    settings, data = fresh
    settings.load()
    with pytest.raises(ValueError):
        settings.update({"WEATHER_CITY": "Paris", "LLM_BACKEND": "nonsense"})
    assert settings.get("WEATHER_CITY") == ""
    with pytest.raises(ValueError):
        settings.update({"WEATHER_CITY": "two\nlines"})
    with pytest.raises(ValueError):
        settings.update({"NOT_A_SETTING": "x"})


def test_restart_only_when_needed(fresh):
    settings, _ = fresh
    settings.load()
    assert settings.update({"WEATHER_CITY": "Tel Aviv"}) == {"saved": ["WEATHER_CITY"], "restart": False}
    assert settings.update({"LLM_BACKEND": "auto"})["restart"] is True
    assert settings.update({"WEATHER_CITY": "Tel Aviv"})["saved"] == []   # unchanged: nothing to apply


def test_secrets_are_never_sent_back(fresh):
    settings, _ = fresh
    settings.load()
    settings.update({"GROQ_API_KEY": "gsk_secret_value_5678"})
    view = settings.public_view()
    assert view["values"]["GROQ_API_KEY"] == "set"
    assert "gsk_secret_value_5678" not in json.dumps(view)
    settings.update({"GROQ_API_KEY": "set"})   # the window sending "set" back means unchanged
    assert settings.get("GROQ_API_KEY") == "gsk_secret_value_5678"


def test_real_environment_wins_until_changed_in_settings(fresh, monkeypatch):
    settings, _ = fresh
    monkeypatch.setenv("WEATHER_CITY", "From Shell")
    settings.load()
    assert settings.get("WEATHER_CITY") == "From Shell"
    settings.update({"WEATHER_CITY": "From Settings"})
    assert os.environ["WEATHER_CITY"] == "From Settings"
