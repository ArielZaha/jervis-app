"""The app sends "recreate this image in Blender" (with a picture in the conversation) to the Blender agent —
never to the chat AI, which can only describe a picture — and leaves picture questions and other requests alone."""
import pytest

import app


@pytest.fixture
def picture(monkeypatch):
    monkeypatch.setattr(app.images, "has_pending_context", lambda *a, **k: True)
    monkeypatch.setattr(app.blender_control, "blender_running", lambda: False)
    monkeypatch.setattr(app, "blender_last_used", 0.0)


@pytest.mark.parametrize("text,yes", [
    ("Recreate this image in Blender", True), ("turn this photo into a 3D scene", True),
    ("rebuild the picture in blender", True), ("what's in this picture?", False),
    ("describe the image", False), ("create a house in blender", False),
])
def test_a_rebuild_with_a_picture_goes_to_blender(picture, text, yes):
    assert app.wants_picture_rebuilt(text) is yes


def test_without_a_picture_it_is_not_a_rebuild(monkeypatch):
    monkeypatch.setattr(app.images, "has_pending_context", lambda *a, **k: False)
    assert app.wants_picture_rebuilt("Recreate this image in Blender") is False


def test_the_rebuild_starts_a_blender_agent_session(picture, monkeypatch):
    started = []
    monkeypatch.setattr(app, "start_computer_task", lambda goal, **kw: started.append((goal, kw)) or "on it")
    assert app.handle_blender_command("Recreate this image in Blender") == "on it"
    assert started[0][1].get("blender") is True and started[0][1].get("persistent") is True
