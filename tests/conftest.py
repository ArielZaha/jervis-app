import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Tests never write into the project folder or the real user data folder.
os.environ.setdefault("JERVIS_DATA_DIR", tempfile.mkdtemp(prefix="jervis-tests-"))
os.environ.setdefault("JERVIS_AUDIO", "off")
