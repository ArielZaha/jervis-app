"""Settings: first start, the old .env, a damaged file, validation, and secrets never shown back."""
import importlib
import json
import os

import pytest


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A clean settings module on an empty data folder, with no Jarvis variables in the environment."""
    for key in list(os.environ):
        if key.startswith(("JARVIS_", "GROQ_", "LLM_", "OLLAMA_", "WEATHER_", "SPOTIFY_", "OPENAI_", "GOOGLE_",
                           "WHATSAPP_", "TWILIO_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
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


def test_a_genuinely_new_install_is_first_run(fresh):
    settings, _ = fresh
    settings.load()
    assert settings.is_first_run() is True


def test_saving_anything_ends_first_run(fresh):
    settings, _ = fresh
    settings.load()
    settings.update({})   # the welcome screen's "Skip for now" sends exactly this
    assert settings.is_first_run() is False


def test_an_old_env_file_is_still_first_run_the_first_time_settings_json_is_made(fresh):
    """An old .env is imported into settings.json (test_env_file_is_imported_once_and_keeps_online_ai already
    checks that), but the welcome screen still hasn't been seen yet, so it's offered once regardless."""
    settings, data = fresh
    (data / ".env").write_text("GROQ_API_KEY=gsk_test_value_1234\n")
    settings.load()
    assert settings.is_first_run() is True


def test_an_existing_settings_file_is_not_first_run(fresh):
    settings, data = fresh
    settings.load()
    settings.update({"WEATHER_CITY": "Tel Aviv"})
    importlib.reload(settings)   # a later launch: fresh process state, same settings.json on disk
    settings.load()
    assert settings.is_first_run() is False


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


# ---------- which AI answers: a line in .env decides ----------
def _env(tmp_path, text):
    (tmp_path / "app").mkdir(exist_ok=True)
    env_file = tmp_path / "app" / ".env"
    env_file.write_text(text, encoding="utf-8")
    return env_file


def _saved(tmp_path, **values):
    (tmp_path / "settings.json").write_text(json.dumps({"version": 1, "values": values}), encoding="utf-8")


def test_the_env_line_chooses_the_ai_even_over_a_saved_setting(fresh):
    settings, tmp_path = fresh
    _saved(tmp_path, LLM_BACKEND="auto", GROQ_API_KEY="gsk_x")
    _env(tmp_path, "GROQ_API_KEY=gsk_x\nLLM_BACKEND=groq\n")
    settings.load()
    assert os.environ["LLM_BACKEND"] == "groq"
    assert settings.public_view()["values"]["LLM_BACKEND"] == "groq"   # and the Settings screen shows the same


def test_other_settings_keep_the_usual_order(fresh):
    settings, tmp_path = fresh
    _saved(tmp_path, WEATHER_CITY="From Settings")
    _env(tmp_path, "WEATHER_CITY=From File\n")
    settings.load()
    assert settings.get("WEATHER_CITY") == "From Settings"


@pytest.mark.parametrize("written, meant", [("Groq", "groq"), ("grok", "groq"), (" GROQ ", "groq"), ('"ollama"', "ollama"),
                                            ("local", "ollama"), ("OLLAMA", "ollama"), ("auto", "auto")])
def test_the_env_line_is_read_however_it_is_written(fresh, written, meant):
    settings, tmp_path = fresh
    _saved(tmp_path, LLM_BACKEND="auto" if meant != "auto" else "ollama")
    _env(tmp_path, f"LLM_BACKEND={written}\n")
    settings.load()
    assert os.environ["LLM_BACKEND"] == meant


def test_an_env_line_naming_no_ai_is_ignored_and_said(fresh, capsys):
    settings, tmp_path = fresh
    _saved(tmp_path, LLM_BACKEND="auto")
    _env(tmp_path, "LLM_BACKEND=chatgpt\n")
    settings.load()
    assert os.environ["LLM_BACKEND"] == "auto"
    assert "chatgpt" in capsys.readouterr().out


def test_no_env_line_means_the_saved_setting(fresh):
    settings, tmp_path = fresh
    _saved(tmp_path, LLM_BACKEND="auto")
    _env(tmp_path, "GROQ_API_KEY=gsk_x\n# LLM_BACKEND=groq\n")
    settings.load()
    assert os.environ["LLM_BACKEND"] == "auto"


def test_choosing_in_settings_rewrites_only_that_env_line(fresh):
    settings, tmp_path = fresh
    text = "GROQ_API_KEY=gsk_secret\n\n# Which AI answers\nLLM_BACKEND=groq   # online only\nSPOTIFY_CLIENT_ID=abc\n"
    env_file = _env(tmp_path, text)
    settings.load()
    result = settings.update({"LLM_BACKEND": "ollama"})
    assert result == {"saved": ["LLM_BACKEND"], "restart": True}
    assert os.environ["LLM_BACKEND"] == "ollama"
    assert env_file.read_text(encoding="utf-8") == text.replace("LLM_BACKEND=groq   # online only", "LLM_BACKEND=ollama")
    importlib.reload(settings)   # the next start reads the same choice from both places
    settings.load()
    assert os.environ["LLM_BACKEND"] == "ollama"


def test_choosing_in_settings_leaves_an_env_file_without_the_line_alone(fresh):
    settings, tmp_path = fresh
    env_file = _env(tmp_path, "GROQ_API_KEY=gsk_secret\n")
    settings.load()
    settings.update({"LLM_BACKEND": "groq"})
    assert env_file.read_text(encoding="utf-8") == "GROQ_API_KEY=gsk_secret\n"
    assert os.environ["LLM_BACKEND"] == "groq"


def test_the_real_environment_still_beats_the_env_line(fresh, monkeypatch):
    settings, tmp_path = fresh
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    _env(tmp_path, "LLM_BACKEND=groq\n")
    settings.load()
    assert os.environ["LLM_BACKEND"] == "ollama"
