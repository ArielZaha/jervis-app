"""The installed engine has every file the code reads from its own folder. Running from source they're simply next to
app.py, so a file missing from the package only shows up in an installed copy: the phone page once was, and every
"connect my phone" ended in "The phone page couldn't be loaded"."""
import glob
import os
import re

import selftest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_names() -> set:
    names = set()
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        source = open(path, encoding="utf-8").read()
        names |= set(re.findall(r"""paths\.resource\(\s*["']([^"']+)["']""", source))
    return names


def test_every_file_read_from_the_engine_folder_is_packaged():
    spec = open(os.path.join(ROOT, "jervis-backend.spec"), encoding="utf-8").read()
    packaged = set(re.findall(r"""\(\s*["']([^"']+)["']\s*,\s*["']\.["']\s*\)""", spec))
    names = _resource_names()
    assert {"phone_client.html", "phone_sw.js", "confirm.html"} <= names
    assert names - packaged == set()


def test_the_installed_selftest_checks_them_too():
    assert _resource_names() <= set(selftest.BUNDLED_FILES)
    for name in selftest.BUNDLED_FILES:
        assert os.path.isfile(os.path.join(ROOT, name)), name
