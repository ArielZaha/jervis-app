import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Tests never write into the project folder or the real user data folder.
os.environ.setdefault("JARVIS_DATA_DIR", tempfile.mkdtemp(prefix="jarvis-tests-"))
os.environ.setdefault("JARVIS_AUDIO", "off")


@pytest.fixture(autouse=True)
def _no_take_control_session_left_over():
    """A test that opened a "take control" session, or just worked in Blender, must not leave that for the next one: it made "yes" and
    "no thanks" in later, unrelated tests answer a control question nobody asked (only in the full run). Cleared
    before each test too: a task thread an earlier test started can open the session after that test ended."""
    for _ in range(2):
        app = sys.modules.get("app")
        if app is not None:
            app.control_session = None
            if hasattr(app, "blender_last_used"):
                app.blender_last_used = 0.0   # else "no thanks" or "yes" counts as a follow-up to Blender work
        if _ == 0:
            yield
