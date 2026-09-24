"""Letting the computer-control loop look at the screen with a vision model: "what does this say?", "where is X?".

Uses Jervis's own image understanding (images.py): Groq's vision model with a key, otherwise the local one (on
computers that have it). Only offered to the loop when one of them is actually available.
"""
import json
import os
import re
import tempfile

import images

GROUNDING_WIDTH = 1024   # the screenshot is scaled to this width, so coordinates map back exactly


def available() -> bool:
    if not images._use_local_vision():
        return True   # Groq's vision model, with the key
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


def _save(image) -> tuple:
    scale = GROUNDING_WIDTH / image.width if image.width > GROUNDING_WIDTH else 1.0
    small = image.resize((int(image.width * scale), int(image.height * scale))) if scale != 1.0 else image
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    small.save(path)
    return path, small.size


class ScreenVision:
    def look(self, image, question: str) -> str:
        path, _ = _save(image)
        try:
            return images._vision_call([path], f"This is a screenshot of the user's screen. {question} "
                                               "Answer briefly and exactly.", max_tokens=300)
        finally:
            os.remove(path)

    def locate(self, image, description: str, screen_size) -> tuple:
        """The screen point (in click coordinates) of something visible, or None."""
        path, (w, h) = _save(image)
        try:
            answer = images._vision_call([path], (
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
        if not box or len(box) != 4:
            return None
        x = (box[0] + box[2]) / 2
        y = (box[1] + box[3]) / 2
        screen_w, screen_h = screen_size if screen_size and screen_size[0] else (w, h)
        return (int(x * screen_w / w), int(y * screen_h / h))
