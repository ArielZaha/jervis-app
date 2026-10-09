"""The project's own source files hold no stray control characters. A backspace once replaced the \\b of a regex
(r"\\bblender\\b" became r"<BS>blender<BS>"), silently turning a guard into one that never matched."""
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_control_characters_in_source():
    found = []
    for pattern in ("*.py", "tests/*.py", "*.js", "*.html", "*.md"):
        for path in glob.glob(os.path.join(ROOT, pattern)):
            with open(path, encoding="utf-8", errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if any(ord(c) < 32 and c not in "\t\r\n" for c in line):
                        found.append(f"{os.path.relpath(path, ROOT)}:{n}")
    assert not found, found


def test_no_invisible_format_characters_in_python_source():
    """Right-to-left marks and other invisible characters (Unicode "format" characters) belong in the code as
    escape sequences, never as themselves: they can't be seen, and they make code read differently from how it
    runs."""
    import unicodedata
    found = []
    for pattern in ("*.py", "tests/*.py"):
        for path in glob.glob(os.path.join(ROOT, pattern)):
            with open(path, encoding="utf-8", errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if any(unicodedata.category(c) == "Cf" for c in line):
                        found.append(f"{os.path.relpath(path, ROOT)}:{n}")
    assert not found, found


def test_the_kit_modules_never_redefine_each_others_names():
    """blender_kit, blender_assets and blender_motion run in ONE namespace inside Blender: a function defined twice
    silently replaces the first (a door helper called _lift once broke every box() the kit made)."""
    import ast
    seen = {}
    clashes = []
    for name in ("blender_kit.py", "blender_assets.py", "blender_motion.py", "blender_places.py",
                 "blender_nature.py", "blender_props.py", "blender_world.py"):
        tree = ast.parse(open(os.path.join(ROOT, name), encoding="utf-8").read())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name in seen and seen[node.name] != name:
                    clashes.append(f"{node.name}: {seen[node.name]} and {name}")
                seen.setdefault(node.name, name)
    assert not clashes, clashes
