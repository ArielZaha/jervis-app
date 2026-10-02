"""Letting the computer-control loop look at the screen with a vision model: "what does this say?", "where is X?".

A screenshot can show far more than the one thing the task needs (other windows, notifications, anything else on
screen), so by default it's only ever looked at by the local model, right here on this computer. Settings, Computer
control, "Look at the screen with" can allow Groq's vision model instead — off unless the user turns it on, since
that means a picture of the whole screen leaving the computer.
"""
import json
import os
import re
import tempfile

import images

# The screenshot is scaled once, to exactly the size the local model is sent (images.LOCAL_VISION_MAX_DIMENSION),
# so the positions it answers with map straight back to the screen.
GROUNDING_MAX = images.LOCAL_VISION_MAX_DIMENSION


def _mode() -> str:
    return (os.getenv("JERVIS_SCREEN_VISION") or "local").strip().lower()


def _local_available() -> bool:
    try:
        import local_ai
        import local_llm
        import requests
        if not local_ai.wants_vision():
            return False
        wanted = os.getenv("OLLAMA_VISION_MODEL") or "qwen2.5vl:3b"
        tags = requests.get(f"{local_llm.URL}/api/tags", timeout=2).json().get("models", [])
        return any(local_ai.LocalAI._has([m.get("name", "")], wanted) for m in tags)
    except Exception:
        return False


def _online_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def available() -> bool:
    mode = _mode()
    if mode == "off":
        return False
    if _local_available():
        return True
    return mode == "online" and _online_available()


def _save(image) -> tuple:
    scale = min(1.0, GROUNDING_MAX / max(image.width, image.height))
    small = image.resize((int(image.width * scale), int(image.height * scale))) if scale != 1.0 else image
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    small.save(path)
    return path, small.size


def _call(image_paths: list, prompt: str, max_tokens: int) -> str:
    """Local model first (private, right here); Groq only when the local one isn't available *and* the user
    explicitly allowed it (Settings, Computer control, "Look at the screen with") — never as a silent fallback."""
    if _local_available():
        return images._local_vision_call(image_paths, prompt, max_tokens)
    if _mode() == "online" and _online_available():
        return images._groq_vision_call(image_paths, prompt, max_tokens)
    raise images.ImageError("I can't look at the screen right now (no local vision model, and online vision isn't "
                            "turned on in Settings, Computer control).")


class ScreenVision:
    def look(self, image, question: str) -> str:
        path, _ = _save(image)
        try:
            return _call([path], f"This is a screenshot of the user's screen. {question} "
                                 "Answer briefly and exactly.", max_tokens=300)
        finally:
            os.remove(path)

    def locate(self, image, description: str, screen_size) -> tuple:
        """The screen point (in click coordinates) of something visible, or None."""
        path, (w, h) = _save(image)
        try:
            answer = _call([path], (
                f"Find this on the screenshot: {description}. Reply with only JSON: "
                f'{{"bbox_2d": [x1, y1, x2, y2]}} in pixels of this {w}x{h} image, or {{"bbox_2d": null}} '
                "if it isn't visible."), max_tokens=80)
        finally:
            os.remove(path)
        match = re.search(r"\{.*\}", answer, re.S)
        try:
            box = json.loads(match.group(0)).get("bbox_2d") if match else None
        except ValueError:
            box = None
        if not box or len(box) != 4 or any(not isinstance(v, (int, float)) for v in box):
            return None   # missing, malformed, or a partial null (some vision models answer that way when unsure)
        x = (box[0] + box[2]) / 2
        y = (box[1] + box[3]) / 2
        if not (0 <= x <= w and 0 <= y <= h):
            return None   # outside the image it was shown: not a real answer, don't click on it
        screen_w, screen_h = screen_size if screen_size and screen_size[0] else (w, h)
        return (int(x * screen_w / w), int(y * screen_h / h))
