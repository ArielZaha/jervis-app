"""What Jervis knows about the scene he is working on — two things kept apart:

REFERENCE: the picture a scene was rebuilt from, what was seen in it (its VisualScene) and which object rebuilt which
element. It is kept (on disk, keyed by an id stored in the .blend) so the picture can still be consulted — "make it
look more like the photo" — but it is never re-applied by itself.

CURRENT: the scene as it is NOW, read fresh from Blender every time: each thing's meaning (its semantic tag), where
it is, its lights and motion; the environment Jervis set (time, weather, fog, water, wind); the cameras. After the
user changes something ("make it sunrise"), the current scene is what every next edit starts from — the reference's
night doesn't come back.

And the words people use for things in it: "the pool", "the main house", "the left palm", "that tree" (the one
spoken about last), "those chairs" (all of them), "the second camera" — resolved by meaning, position as the camera
sees it and the conversation, never only by object names."""
import json
import os
import re
import time
import uuid

import paths
import semantics

STORE = os.path.join(paths.DATA_DIR, "scenes")


# ---------- the reference, kept ----------

def save_reference(scene: dict, built: dict, image_path: str, scene_id: str = None) -> str:
    """Keep a rebuilt picture's reference; returns its id (stored on the Blender scene by the caller)."""
    os.makedirs(STORE, exist_ok=True)
    scene_id = scene_id or uuid.uuid4().hex[:12]
    with open(os.path.join(STORE, f"{scene_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"id": scene_id, "saved": time.time(), "image": image_path, "built": built,
                   "visual_scene": scene, "edits": []}, f, default=str)
    return scene_id


def load_reference(scene_id: str):
    try:
        with open(os.path.join(STORE, f"{scene_id}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def note_edit(scene_id: str, request: str, result: str) -> None:
    """The edit history of a scene (what the user asked, what happened) — relevant history, kept with it."""
    ref = load_reference(scene_id) if scene_id else None
    if ref is None:
        return
    ref.setdefault("edits", []).append({"at": time.time(), "request": request, "result": result[:300]})
    ref["edits"] = ref["edits"][-50:]
    with open(os.path.join(STORE, f"{scene_id}.json"), "w", encoding="utf-8") as f:
        json.dump(ref, f, default=str)


# ---------- the current scene, read from Blender ----------

CURRENT_CODE = ("import json\n"
                "_s = bpy.context.scene\n"
                "RESULT = json.dumps({'things': json.loads(semantic_registry()), 'env': json.loads(env_state()),\n"
                "                     'cameras': json.loads(cameras()), 'scene_id': _s.get('jervis_scene_id'),\n"
                "                     'frames': json.loads(thing_frames()) if _s.camera else {}})")


def read_current(bridge) -> dict:
    """The scene as it is now: {"things": [...], "env": {...}, "cameras": [...], "scene_id", "frames"} — {} when
    Blender can't be asked."""
    try:
        response = bridge.run(CURRENT_CODE, timeout=20)
        return json.loads(response.get("output") or "{}") if response.get("ok") else {}
    except (ValueError, TypeError, AttributeError):
        return {}


# ---------- what words point at ----------

_ORDINAL = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "last": -1, "other": 1}
_SIDES = ("left", "right", "front", "back", "middle", "center", "centre", "nearest", "closest", "farthest",
          "furthest", "biggest", "largest", "smallest", "tallest", "main", "front-most")
_PLURAL_REF = re.compile(r"\b(?:those|these|all(?: the)?|every|each)\b", re.I)
_PRONOUN = re.compile(r"^(?:it|that|this|that one|this one|the same|them|they)$", re.I)


class Resolver:
    """Turns "the left palm", "that tree", "those chairs", "the pool", "the second camera" into the objects meant,
    using the current scene's semantic tags, positions as the active camera sees them, and what was talked about
    last. Returns (names, confidence, question): a question instead of a guess when it really can't tell."""

    def __init__(self):
        self.last = []        # what the last command was about (names)

    def remember(self, names):
        if names:
            self.last = list(names)

    def resolve(self, phrase: str, current: dict, want_camera: bool = False):
        text = " ".join(str(phrase or "").lower().replace("-", " ").split())
        text = re.sub(r"^(?:the|a|an|my|our)\s+", "", text)
        things = current.get("things") or []
        if want_camera or re.search(r"\bcamera\b", text):
            return self._camera(text, current)
        if not text or _PRONOUN.match(text):
            if self.last:
                return self.last, 0.8, None
            return [], 0.0, "Which one do you mean?"
        last_word = text.split()[-1] if text.split() else ""
        plural = bool(_PLURAL_REF.search(text)) or (
            last_word.endswith("s") and not last_word.endswith(("ss", "us")) and last_word not in ("grass", "glass")
            and semantics.canonical(last_word[:-1]) is not None)
        kind = semantics.canonical(text)
        cands = [t for t in things if kind and (t.get("kind") == kind or semantics.canonical(t.get("kind") or "")
                                               == kind or kind in str(t.get("kind")))]
        if kind in ("house", "building", "villa"):
            # "the house" in a rebuilt photo: any building may be the one meant (the photo's villa was tagged a
            # 'building', its neighbour a 'house') — the main one settles it below unless more is said
            more = [t for t in things if t not in cands and semantics.canonical(t.get("kind") or "")
                    in ("house", "building", "villa")]
            cands = cands + more
        exact = [t for t in things if t["name"].lower() == text]
        if exact and len(cands) <= 1:   # a name — unless it's also the kind of several things ("the palm tree")
            return [exact[0]["name"]], 1.0, None
        if not cands and kind:   # "the house" for a villa, "the building" for the shop: by category
            cat = semantics.category(kind)
            cands = [t for t in things if semantics.category(semantics.canonical(t.get("kind") or "") or "") == cat
                     and cat not in ("object", "ignore")]
        if not cands:
            words = set(re.findall(r"[a-z]+", text)) - {"the", "a", "left", "right", "front", "back", "main"}
            cands = [t for t in things if words & set(re.findall(r"[a-z]+", t["name"].lower()))]
        if not cands:
            return [], 0.0, f"I can't find {phrase!r} in the scene."
        qualified = re.search(r"\b(?:left|right|middle|center|centre|front|back|near|far|nearest|closest|farthest|"
                              r"furthest|behind|biggest|largest|tallest|smallest|other|first|second|third|last|"
                              r"neighbou?r'?s?)\b", text)
        main = [t for t in cands if "main" in str(t.get("role") or "")]
        if main and len(main) == 1 and ("main" in text.split() or (len(cands) > 1 and not qualified and not plural)):
            return [main[0]["name"]], 0.9, None
        if plural or re.search(r"\b(?:all|every|both)\b", text):
            return [t["name"] for t in cands], 0.85, None
        if len(cands) == 1:
            return [cands[0]["name"]], 0.95, None
        frames = current.get("frames") or {}
        pick = self._by_position(text, cands, frames)
        if pick:
            return [pick], 0.85, None
        ordinal = next((v for w, v in _ORDINAL.items() if re.search(rf"\b{w}\b", text)), None)
        if ordinal is not None:
            ordered = sorted(cands, key=lambda t: (frames.get(t["name"], [0.5])[0], t["name"]))
            return [ordered[ordinal]["name"]], 0.7, None
        recent = [t["name"] for t in cands if t["name"] in self.last]
        if recent:
            return [recent[0]], 0.75, None
        # a role ("the pool" when one is the pool of the reference) settles it; otherwise the biggest, if clearly so
        sizes = sorted(cands, key=lambda t: -(t.get("size") or [0, 0, 0])[0] * (t.get("size") or [0, 0, 0])[1])
        a = sizes[0].get("size") or [0, 0, 0]
        b = sizes[1].get("size") or [0, 0, 0]
        if a[0] * a[1] > 2.5 * max(0.01, b[0] * b[1]):
            return [sizes[0]["name"]], 0.65, None
        listed = ", ".join(t["name"] for t in cands[:5])
        return [], 0.3, f"There are {len(cands)} of those ({listed}) — which one: the left, the right, or all of them?"

    @staticmethod
    def _by_position(text, cands, frames):
        seen = [(t, frames.get(t["name"])) for t in cands if frames.get(t["name"])]
        if len(seen) < 2:
            return None
        cx = lambda f: (f[0] + f[2]) / 2
        if re.search(r"\bleft(?:most)?\b", text):
            return min(seen, key=lambda p: cx(p[1]))[0]["name"]
        if re.search(r"\bright(?:most)?\b", text):
            return max(seen, key=lambda p: cx(p[1]))[0]["name"]
        if re.search(r"\b(?:middle|center|centre)\b", text):
            return min(seen, key=lambda p: abs(cx(p[1]) - 0.5))[0]["name"]
        if re.search(r"\b(?:front|nearest|closest)\b", text):   # nearer = lower in the picture
            return max(seen, key=lambda p: p[1][3])[0]["name"]
        if re.search(r"\b(?:back|farthest|furthest|behind)\b", text):
            return min(seen, key=lambda p: p[1][3])[0]["name"]
        if re.search(r"\b(?:biggest|largest|tallest)\b", text):
            return max(seen, key=lambda p: (p[1][2] - p[1][0]) * (p[1][3] - p[1][1]))[0]["name"]
        if re.search(r"\bsmallest\b", text):
            return min(seen, key=lambda p: (p[1][2] - p[1][0]) * (p[1][3] - p[1][1]))[0]["name"]
        return None

    def _camera(self, text, current):
        cams = current.get("cameras") or []
        if not cams:
            return [], 0.0, "There's no camera in the scene yet."
        for c in sorted(cams, key=lambda c: -len(c["name"])):   # "camera 2" before "camera"; "camera" alone
            if re.search(rf"\b{re.escape(c['name'].lower())}\b(?!\s*\d)", text) and not re.search(
                    r"\b(?:other|second|third|next|another|2nd|3rd)\b", text):
                return [c["name"]], 1.0, None
        ordinal = next((v for w, v in _ORDINAL.items() if re.search(rf"\b{w}\b", text)), None)
        ordered = sorted(cams, key=lambda c: c["name"])
        if ordinal is not None and (ordinal < len(ordered) or ordinal == -1):
            if "other" in text:
                rest = [c for c in ordered if not c.get("active")]
                return ([rest[0]["name"]], 0.85, None) if rest else ([], 0.2, "There's only one camera.")
            return [ordered[ordinal]["name"]], 0.85, None
        active = [c for c in cams if c.get("active")]
        return [(active or ordered)[0]["name"]], 0.9, None
