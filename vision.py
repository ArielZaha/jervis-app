"""Seeing, for Jervis: a local vision-language model (Ollama) asked focused questions about a picture, answering in
machine-usable form — JSON attributes, and object boxes in the picture's own pixels.

Why it is built this way (measured on an RTX 4060 8 GB, Ollama 0.35):
- Qwen2.5-VL 7B is the strongest vision model that fits beside nothing else on the card (6.4 GB, ~85% on the GPU):
  ~15 s per question at ~1 megapixel, and it can LOCATE things (boxes). gemma3:4b describes well but can't place
  boxes; Qwen2.5-VL 3B places boxes less well and often breaks its JSON. So: the 7B, else the 3B, else nothing —
  never a text-only model pretending to see.
- Qwen2.5-VL answers boxes in the pixels of the image it was given — but Ollama scales small images UP to about a
  megapixel first, so a 896 px picture came back with every box 1.25x too big. Pictures are therefore sent at ~1 MP
  (long side 1288, both sides multiples of the model's 28 px patch), where its boxes are the picture's own pixels;
  a box that still overruns the picture is rescaled, not trusted blindly.
- Boxes come from the model's NATIVE grounding prompt ("Locate ... output bbox_2d"): forcing them through a JSON
  schema made all three models place them badly.
- One focused question per pass (the whole scene, then where things are, then each important thing up close)
  beats one giant question: the model drops fields and invents counts when asked for everything at once.
"""
import base64
import io
import json
import os
import re
import time

import requests
from PIL import Image

LONG_SIDE = 1288          # ~1 MP for 3:2; 46 patches of 28 px
PATCH = 28
PREFERRED = ["qwen2.5vl:7b", "qwen2.5vl", "qwen2.5vl:3b"]
NUM_CTX = 8192            # a ~1 MP picture is ~1,200 tokens; the answers are short
TIMEOUT = 300


class VisionUnavailable(Exception):
    """No local vision model (or Ollama not running): say so plainly instead of guessing what a picture shows."""


def model() -> str:
    """The vision model to use: OLLAMA_VISION_MODEL if it's installed, else the best installed Qwen2.5-VL."""
    import local_llm
    models = local_llm.installed_models() or []
    wanted = (os.getenv("OLLAMA_VISION_MODEL") or "").strip()
    if wanted:
        found = local_llm._match(models, wanted)
        if found and _can_see(found):
            return found
    for name in PREFERRED:
        found = local_llm._match(models, name)
        if found:
            return found
    return None


def _can_see(name: str) -> bool:
    return any(k in name.lower() for k in ("vl", "vision", "llava", "gemma3", "minicpm-v", "moondream"))


def available() -> bool:
    try:
        return model() is not None
    except Exception:
        return False


# ---------- the picture as the model gets it ----------

def load(path_or_image) -> Image.Image:
    img = path_or_image if isinstance(path_or_image, Image.Image) else Image.open(path_or_image)
    img.load()
    return img.convert("RGB")


def prepare(img: Image.Image, crop=None) -> tuple:
    """(JPEG base64, (sent w, sent h), (x0, y0, sx, sy)): the picture (or a crop of it, in its own pixels) resized
    to ~1 MP on the patch grid, and how to map the model's pixels back: original = x0 + x * sx."""
    x0 = y0 = 0
    if crop:
        x1, y1, x2, y2 = [int(round(v)) for v in crop]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        if x2 - x1 < 8 or y2 - y1 < 8:
            raise ValueError("crop too small")
        img, x0, y0 = img.crop((x1, y1, x2, y2)), x1, y1
    s = LONG_SIDE / max(img.size)
    w = max(PATCH * 2, round(img.width * s / PATCH) * PATCH)
    h = max(PATCH * 2, round(img.height * s / PATCH) * PATCH)
    sent = img.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    sent.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii"), (w, h), (x0, y0, img.width / w, img.height / h)


def _post(prompt: str, images: list, fmt=None, max_tokens: int = 1500, temperature: float = 0.1) -> str:
    import local_llm
    name = model()
    if not name:
        raise VisionUnavailable("there's no vision model on this computer (Qwen2.5-VL: `ollama pull qwen2.5vl:7b`), "
                                "so I can't look at pictures")
    started = time.time()
    try:
        with local_llm.gpu_slot(name, NUM_CTX) as fit:
            payload = {"model": name, "stream": False, "keep_alive": "10m",
                       "messages": [{"role": "user", "content": prompt, "images": images}],
                       "options": {"temperature": temperature, "num_ctx": NUM_CTX, "num_predict": max_tokens,
                                   "repeat_penalty": 1.12, **fit}}
            if fmt is not None:
                payload["format"] = fmt
            response = requests.post(f"{local_llm.URL}/api/chat", json=payload, timeout=TIMEOUT)
    except requests.Timeout as e:
        raise VisionUnavailable("looking at the picture took too long") from e
    except requests.RequestException as e:
        raise VisionUnavailable("the local AI (Ollama) isn't running") from e
    if response.status_code != 200:
        raise VisionUnavailable(f"the vision model answered with an error ({response.status_code})")
    text = ((response.json().get("message") or {}).get("content") or "").strip()
    print(f"Vision ({name}) answered in {time.time() - started:.1f}s", flush=True)
    return text


# ---------- questions ----------

def ask_json(img, prompt: str, crop=None, max_tokens: int = 1500) -> dict:
    """A JSON answer about the picture (or a crop of it). {} when the model's answer can't be read as JSON."""
    img = load(img)
    b64, _, _ = prepare(img, crop)
    return parse_json(_post(prompt, [b64], fmt="json", max_tokens=max_tokens))


def ask_text(img, prompt: str, crop=None, max_tokens: int = 600) -> str:
    img = load(img)
    b64, _, _ = prepare(img, crop)
    return _post(prompt, [b64], max_tokens=max_tokens)


def compare_json(images: list, prompt: str, max_tokens: int = 1200) -> dict:
    """A JSON answer about several pictures at once (a reference and a render, in that order)."""
    encoded = [prepare(load(i))[0] for i in images]
    return parse_json(_post(prompt, encoded, fmt="json", max_tokens=max_tokens))


def ground(img, labels, crop=None, max_tokens: int = 1100) -> list:
    """Where things are: [{"label", "box": (x1, y1, x2, y2)}] in the ORIGINAL picture's pixels, one per instance the
    model found. `labels`: what to look for ("the house", "every palm tree"...)."""
    img = load(img)
    b64, (w, h), (x0, y0, sx, sy) = prepare(img, crop)
    what = labels if isinstance(labels, str) else ", ".join(labels)
    text = _post(f"Locate {what} in the image, and output their bbox coordinates in JSON format with keys bbox_2d "
                 "and label.", [b64], max_tokens=max_tokens, temperature=0.0)
    return boxes_from(text, (w, h), (x0, y0, sx, sy), (img.width, img.height))


def boxes_from(text: str, sent_size, mapping, original_size) -> list:
    """The boxes in a grounding answer, mapped to the original picture: tolerant of the model's JSON slips (a
    missing comma, an answer cut off mid-list), rescaled when the model clearly answered in a bigger frame."""
    w, h = sent_size
    x0, y0, sx, sy = mapping
    found = []
    for m in re.finditer(r"\{[^{}]*?\"bbox_2d\"\s*:\s*\[([^\]]*)\][^{}]*?\}", text or "", re.S):
        nums = re.findall(r"-?\d+(?:\.\d+)?", m.group(1))
        lab = re.search(r"\"label\"\s*:\s*\"([^\"]*)\"", m.group(0))
        if len(nums) != 4:
            continue
        found.append(([float(v) for v in nums], (lab.group(1) if lab else "").strip()))
    if not found:
        return []
    # A frame bigger than what was sent (Ollama scaled it up): every box overruns the same way — scale them back.
    max_x = max(b[2] for b, _ in found)
    max_y = max(b[3] for b, _ in found)
    kx = w / max_x if max_x > w * 1.04 else 1.0
    ky = h / max_y if max_y > h * 1.04 else 1.0
    k = min(kx, ky) if kx < 1 and ky < 1 else (kx if kx < 1 else ky)   # one scale for both: the aspect is kept
    out = []
    W, H = original_size
    for (x1, y1, x2, y2), label in found:
        x1, x2 = sorted((x1 * k, x2 * k))
        y1, y2 = sorted((y1 * k, y2 * k))
        box = (x0 + x1 * sx, y0 + y1 * sy, x0 + x2 * sx, y0 + y2 * sy)
        box = (max(0.0, min(W, box[0])), max(0.0, min(H, box[1])), max(0.0, min(W, box[2])), max(0.0, min(H, box[3])))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            continue
        out.append({"label": label, "box": tuple(round(v, 1) for v in box)})
    return out


def parse_json(text: str) -> dict:
    """The JSON object in a model's answer, or {}: tolerant of code fences, prose around it and a cut-off end."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start = text.find("{")
    if start < 0:
        return {}
    body = text[start:]
    for attempt in range(3):
        try:
            value = json.loads(body)
            return value if isinstance(value, dict) else {}
        except ValueError:
            if attempt == 0:
                end = body.rfind("}")
                body = body[:end + 1] if end > 0 else body
            elif attempt == 1:
                body = _close_json(text[start:])
    return {}


def _close_json(text: str) -> str:
    """A cut-off JSON answer closed where it stopped: unfinished string and value dropped, brackets closed."""
    stack, in_str, esc, last_ok = [], False, False, 0
    for i, c in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
            last_ok = i + 1
        elif c == ",":
            last_ok = i
    body = text[:last_ok].rstrip().rstrip(",")
    # recount what's open in the kept part
    stack, in_str, esc = [], False, False
    for c in body:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]" and stack:
            stack.pop()
    return body + "".join(reversed(stack))
