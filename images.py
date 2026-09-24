"""Image intelligence for Jervis: understanding pictures (description, questions, OCR, comparison) and creating or
editing them.

Understanding uses the same account as the rest of Jervis's AI (a vision-capable model on Groq, GROQ_API_KEY) —
nothing extra to set up. Generating a picture works out of the box too, through Pollinations.ai (no key, genuinely
free, no billing) — OpenAI's image API (OPENAI_API_KEY, optional) is used instead when it's configured and working,
since it also supports editing an existing picture, which Pollinations' simple endpoint does not. If OpenAI is
configured but a request to it fails (no credits, bad key, service issue), generation quietly falls back to
Pollinations rather than giving up — but says so, so nothing is hidden from the user.

Every image that passes through Jervis (attached by the user, or made/edited by him) is saved under images/ and kept
in a short rolling memory (`_recent`) so the conversation can refer to "it", "this image", or compare "these two" —
the same idea as `last_function`/`last_document` in app.py, just for pictures.
"""
import base64
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from urllib.parse import quote as _urlquote

import requests
from PIL import Image, UnidentifiedImageError
from groq import Groq
import paths

try:
    from openai import OpenAI
except ImportError:  # the package ships in requirements.txt, but keep this module importable even if it's missing
    OpenAI = None

try:  # optional, heavy, opt-in (see requirements-local-images.txt / run.py --local-images): genuinely unlimited,
    # free, private image generation on this machine's own GPU, instead of a cloud service. The actual generation
    # runs in a separate process (local_image_worker.py, via _generate_local) so a hang or crash there can never
    # affect Jervis itself — torch is only imported here to check it's installed and to pick mps/cuda/cpu.
    import torch
    import diffusers  # noqa: F401 — presence check only; the worker process does the real import
except ImportError:
    torch = None
    diffusers = None

APP_DIR = paths.RESOURCE_DIR
IMAGES_DIR = os.path.join(paths.DATA_DIR, "images")
UPLOADS_DIR = os.path.join(IMAGES_DIR, "uploads")
GENERATED_DIR = os.path.join(IMAGES_DIR, "generated")
EDITED_DIR = os.path.join(IMAGES_DIR, "edited")
for _d in (UPLOADS_DIR, GENERATED_DIR, EDITED_DIR):
    os.makedirs(_d, exist_ok=True)

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # older Pillow
    RESAMPLE = Image.LANCZOS

GROQ_MAX_IMAGES_PER_CALL = 3          # Groq's own limit per request
_VALID_SIZES = {"1024x1024", "1536x1024", "1024x1536", "auto"}

MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # a sane ceiling for a personal assistant; also under Groq's per-image limit
MAX_API_DIMENSION = 1536              # downscaled to this before being sent to any AI: plenty of detail, far less data
MAX_DISPLAY_DIMENSION = 1600          # downscaled to this before being sent to the window, so huge files don't clog the socket
MAX_CONTEXT_IMAGES = 12               # how many recent images the conversation remembers
PENDING_WINDOW_SECONDS = 60 * 60      # how long an image stays "the one we're talking about" for follow-up questions

SUPPORTED_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif", "BMP": "bmp"}

_groq_client = None
_openai_client = None
_recent = []  # [{id, path, kind, caption, prompt, at}], oldest first, kind: "upload" | "generated" | "edited"


class ImageError(Exception):
    """A problem worth telling the user about, in plain words: bad file, missing provider, API failure."""


# ---------- configuration ----------
# Read lazily (not as module-level constants) because app.py imports this module before it calls load_dotenv() —
# reading os.getenv() at import time would always see an empty environment and "forget" a real key in .env.
def _groq_key() -> str:
    return (os.getenv("GROQ_API_KEY") or "").strip().strip("\"'")


def _groq_vision_model() -> str:
    # Groq's current vision-capable chat model (accepts image_url content parts, base64 or hosted URLs).
    return (os.getenv("GROQ_VISION_MODEL") or "qwen/qwen3.8-27b").strip()


def _openai_key() -> str:
    return (os.getenv("OPENAI_API_KEY") or "").strip().strip("\"'")


def _openai_image_model() -> str:
    return (os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()


def _local_image_model() -> str:
    return (os.getenv("LOCAL_IMAGE_MODEL") or "stabilityai/sd-turbo").strip()


def vision_configured() -> bool:
    return bool(_groq_key())


def generation_configured() -> bool:
    return bool(_openai_key()) and OpenAI is not None


def local_generation_configured() -> bool:
    """Whether torch + diffusers are installed (see requirements-local-images.txt) — the model itself downloads
    on first use, so this doesn't check for that, only that generating locally is possible at all."""
    return torch is not None and diffusers is not None


def _groq() -> Groq:
    global _groq_client
    key = _groq_key()
    if not key:
        raise ImageError("Image understanding needs GROQ_API_KEY, the same key the rest of Jervis's AI uses — "
                          "add it to your .env file (free at console.groq.com) and restart Jervis.")
    if _groq_client is None:
        _groq_client = Groq(api_key=key)
    return _groq_client


def _openai():
    global _openai_client
    if OpenAI is None:
        raise ImageError("The 'openai' package isn't installed. Run:  pip install -r requirements.txt   and restart Jervis.")
    key = _openai_key()
    if not key:
        raise ImageError("Generating or editing images needs an OPENAI_API_KEY in your .env file (create one at "
                          "platform.openai.com, then restart Jervis). Without it I can still look at, describe and "
                          "read text from images.")
    if _openai_client is None:
        _openai_client = OpenAI(api_key=key)
    return _openai_client


# ---------- validation, storage, metadata ----------
def validate_image_bytes(data: bytes, max_bytes: int = MAX_UPLOAD_BYTES) -> Image.Image:
    """Open and verify image bytes are a real, undamaged image Jervis can work with. Raises ImageError otherwise."""
    if not data:
        raise ImageError("That file was empty.")
    if len(data) > max_bytes:
        raise ImageError(f"That image is too large ({len(data) / 1024 / 1024:.1f} MB). The limit is {max_bytes / 1024 / 1024:.0f} MB.")
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()  # checks integrity; the file object is unusable after this, so reopen it to actually use it
    except UnidentifiedImageError:
        raise ImageError("That doesn't look like a valid image file.")
    except Exception as e:
        raise ImageError(f"That image file is corrupted or unreadable ({e}).")
    img = Image.open(io.BytesIO(data))
    img.load()
    fmt = (img.format or "").upper()
    if fmt not in SUPPORTED_FORMATS:
        raise ImageError(f"Unsupported image format: {fmt or 'unknown'}. Use PNG, JPEG, WEBP, GIF or BMP.")
    return img


def get_metadata(img: Image.Image, path: str = None) -> dict:
    data = {"width": img.width, "height": img.height, "format": img.format, "mode": img.mode}
    if path and os.path.exists(path):
        data["bytes"] = os.path.getsize(path)
    return data


def _safe_name(hint: str, ext: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", (hint or "image")).strip("-")[:40] or "image"
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{stem}_{uuid.uuid4().hex[:8]}.{ext}"


def _try_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _save(img: Image.Image, directory: str, hint: str, fmt: str = "PNG") -> str:
    fmt = (fmt or "PNG").upper()
    ext = SUPPORTED_FORMATS.get(fmt, "png")
    path = os.path.join(directory, _safe_name(hint, ext))
    to_save = img.convert("RGB") if fmt in ("JPEG",) and img.mode in ("RGBA", "P", "LA") else img
    to_save.save(path, format=fmt)
    return path


def _encode_for_transport(img: Image.Image, max_dim: int) -> tuple:
    """Downscale (if needed) and encode as JPEG, or PNG when transparency matters. Returns (bytes, mime)."""
    work = img
    if max(img.size) > max_dim:
        work = img.copy()
        work.thumbnail((max_dim, max_dim), RESAMPLE)
    keep_png = img.mode in ("RGBA", "LA", "P") or img.format == "PNG"
    buf = io.BytesIO()
    if keep_png:
        work.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    if work.mode not in ("RGB", "L"):
        work = work.convert("RGB")
    work.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), "image/jpeg"


def _data_url_for_api(path: str) -> str:
    data, mime = _encode_for_transport(Image.open(path), MAX_API_DIMENSION)
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def display_data_url(path: str) -> str:
    """A base64 data URL sized for showing in the window's chat (not for sending to an AI)."""
    data, mime = _encode_for_transport(Image.open(path), MAX_DISPLAY_DIMENSION)
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


# ---------- conversation memory ----------
def remember(path: str, kind: str, caption: str = "", prompt: str = "") -> dict:
    entry = {"id": uuid.uuid4().hex[:10], "path": path, "kind": kind, "caption": caption, "prompt": prompt, "at": time.time()}
    _recent.append(entry)
    del _recent[:-MAX_CONTEXT_IMAGES]
    return entry


def last_image(n: int = 1) -> list:
    """The n most recent images (oldest of the n first), or [] if there are none."""
    return _recent[-n:] if _recent else []


def has_pending_context(window_seconds: int = PENDING_WINDOW_SECONDS) -> bool:
    return bool(_recent) and time.time() - _recent[-1]["at"] < window_seconds


FORCE_WINDOW_SECONDS = 180  # a message within 3 minutes of an image is almost certainly about it


def just_received_image(window_seconds: int = FORCE_WINDOW_SECONDS) -> bool:
    """True right after an image arrived — used to steer the AI toward actually looking at it instead of
    guessing or apologizing, without forcing an image tool on unrelated chat later in a long conversation."""
    return bool(_recent) and time.time() - _recent[-1]["at"] < window_seconds


def context_note() -> str:
    """A system-message hint for the AI: an image is part of this conversation, so tool calls about "it" make sense."""
    if not has_pending_context():
        return ""
    last = _recent[-1]
    phrase = {"upload": "The user attached an image", "generated": "Jervis just generated an image",
              "edited": "Jervis just edited an image"}.get(last["kind"], "There is an image")
    extra = f' ("{last["caption"]}")' if last.get("caption") else (f' (prompt: "{last["prompt"]}")' if last.get("prompt") else "")
    more = f" There are {len(_recent)} images total in this conversation, which compare_images can use." if len(_recent) > 1 else ""
    return (f"Context: {phrase}{extra} earlier in this conversation; it has not yet been described in words to the "
            f"user. You cannot see it yourself — if the user asks about it, \"this\", or \"that image\", call "
            f"analyze_image, extract_image_text, compare_images or edit_image as appropriate.{more}")


def ingest_upload(data_url_or_b64: str, filename: str = "") -> dict:
    """Validate and store an image sent from the window (a data: URL or raw base64). Returns its metadata."""
    raw_field = data_url_or_b64 or ""
    b64 = raw_field.split(",", 1)[1] if raw_field.startswith("data:") else raw_field
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise ImageError("That image data was corrupted on the way here.")
    img = validate_image_bytes(raw)
    path = _save(img, UPLOADS_DIR, os.path.splitext(filename or "")[0], fmt=img.format or "PNG")
    entry = remember(path, "upload", caption=(filename or "").strip())
    return {"path": path, "id": entry["id"], **get_metadata(img, path)}


def save_copy(which: int = 1) -> str:
    """Copy the most recent image to the user's Desktop (or Downloads/home), never overwriting an existing file."""
    imgs = last_image(which)
    if not imgs:
        raise ImageError("There's no image to save yet.")
    src = imgs[-1]["path"]
    if not os.path.exists(src):
        raise ImageError("That image is no longer available.")
    dest_dir = next((c for c in (os.path.expanduser("~/Desktop"), os.path.expanduser("~/Downloads"), os.path.expanduser("~"))
                      if os.path.isdir(c)), None)
    if not dest_dir:
        raise ImageError("I couldn't find a folder on this computer to save into.")
    dest = os.path.join(dest_dir, os.path.basename(src))
    base, ext = os.path.splitext(dest)
    n = 1
    while os.path.exists(dest):
        dest = f"{base}_{n}{ext}"
        n += 1
    shutil.copy2(src, dest)
    return dest


# ---------- understanding: analysis, OCR, comparison (Groq vision) ----------
def _vision_call(image_paths: list, prompt: str, max_tokens: int = 700) -> str:
    if not image_paths:
        raise ImageError("There's no image in our conversation yet. Attach or upload one first.")
    image_paths = image_paths[-GROQ_MAX_IMAGES_PER_CALL:]
    content = [{"type": "text", "text": prompt}]
    for p in image_paths:
        if not os.path.exists(p):
            raise ImageError("That image is no longer available (it may have been cleared).")
        content.append({"type": "image_url", "image_url": {"url": _data_url_for_api(p)}})
    client = _groq()
    try:
        response = client.chat.completions.create(
            model=_groq_vision_model(), messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens, temperature=0.2,
        )
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            raise ImageError("The AI service rejected the key while looking at the image. Check GROQ_API_KEY.")
        if status == 429:
            raise ImageError("Image analysis is rate-limited right now. Try again in a few seconds.")
        raise ImageError(f"Looking at the image failed: {e}")
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ImageError("The AI didn't return anything for that image. Try again.")
    return text


def analyze(question: str = "") -> str:
    """Describe the most recent image, or answer a specific question about it."""
    imgs = last_image(1)
    if not imgs:
        raise ImageError("There's no image in our conversation yet. Attach or upload one first.")
    q = (question or "").strip()
    prompt = (
        f"Look at this image carefully and answer the user's question, based only on what is actually visible in "
        f"it. If something can't be determined from the image, say so plainly instead of guessing.\nQuestion: {q}"
        if q else
        "Describe this image in clear, useful detail: what it shows (objects, scene, people if any, visible text, "
        "layout), and anything notable. If it is a screenshot, a UI, a chart, a diagram or a document, say so and "
        "explain what it is showing. Be specific and concrete, not vague filler."
    )
    return _vision_call([imgs[-1]["path"]], prompt, max_tokens=700)


def extract_text(which: int = 1) -> str:
    """OCR: transcribe the text visible in the most recent image."""
    imgs = last_image(which)
    if not imgs:
        raise ImageError("There's no image to read text from yet. Attach or upload one first.")
    prompt = ("Transcribe ALL text visible in this image, exactly as written, preserving line breaks and reading "
              "order (top to bottom, left to right). Write each distinct piece of text exactly ONCE — never repeat "
              "or restate any line. If there is no readable text, say clearly that no text was found. Do not "
              "summarize, translate, or add commentary — reply with only the transcribed text itself.")
    return _vision_call([imgs[-1]["path"]], prompt, max_tokens=1200)


def compare(question: str = "") -> str:
    """Compare the most recent images (at least two must exist)."""
    imgs = last_image(GROQ_MAX_IMAGES_PER_CALL)
    if len(imgs) < 2:
        raise ImageError("I need at least two images in our conversation to compare. Attach another one first.")
    q = (question or "").strip() or "Compare these images: what is different between them, and what do they have in common?"
    prompt = f"These are {len(imgs)} images from the same conversation, in order (oldest first). {q}"
    return _vision_call([i["path"] for i in imgs], prompt, max_tokens=800)


# ---------- creation: generation and editing (OpenAI images) ----------
def _openai_error_detail(e: Exception) -> str:
    """The openai SDK's exception.body is sometimes {"error": {"message": ...}} and sometimes the inner error
    object directly (flat, no "error" wrapper) — different error paths in the SDK shape it differently, so check
    both instead of assuming one."""
    body = getattr(e, "body", None)
    if not isinstance(body, dict):
        return ""
    inner = body.get("error") if isinstance(body.get("error"), dict) else body
    return str(inner.get("message") or "").strip()


def _openai_error_message(e: Exception, action: str) -> str:
    status = getattr(e, "status_code", None)
    detail = _openai_error_detail(e)
    if status in (401, 403):
        return "The image service rejected the API key. Check OPENAI_API_KEY in your .env file."
    if status == 400 and re.search(r"content.?polic|safety", detail, re.I):
        return f"That request was blocked by the image service's safety rules. Try rephrasing what you want to {action}."
    if status == 429:
        # detail usually says exactly what's wrong (no credits, rate limit, etc.) — much more useful than a guess.
        return detail or "The image service's rate or spending limit was reached. Try again shortly, or check your OpenAI account's usage."
    if detail:
        return f"The image service couldn't {action} that image: {detail}"
    return f"The image service couldn't {action} that image ({e})."


def _size_to_pixels(size: str) -> tuple:
    if size and "x" in size:
        try:
            w, h = size.lower().split("x", 1)
            return max(64, min(1536, int(w))), max(64, min(1536, int(h)))
        except ValueError:
            pass
    return 1024, 1024


def _generate_openai(prompt: str, size: str) -> dict:
    client = _openai()
    try:
        response = client.images.generate(model=_openai_image_model(), prompt=prompt,
                                           size=size if size in _VALID_SIZES else "auto", quality="auto", n=1)
    except Exception as e:
        raise ImageError(_openai_error_message(e, "generate"))
    b64 = getattr(response.data[0], "b64_json", None) if response.data else None
    if not b64:
        raise ImageError("The image generator didn't return any image data.")
    img = validate_image_bytes(base64.b64decode(b64), max_bytes=50 * 1024 * 1024)
    path = _save(img, GENERATED_DIR, prompt, fmt="PNG")
    entry = remember(path, "generated", prompt=prompt)
    return {"path": path, "id": entry["id"], "prompt": prompt, "provider": "openai", **get_metadata(img, path)}


def _generate_pollinations(prompt: str, size: str) -> dict:
    """Pollinations.ai: a free, keyless text-to-image service (https://pollinations.ai). No account needed; a free
    registration at auth.pollinations.ai raises the rate limit and drops the small watermark, but isn't required."""
    width, height = _size_to_pixels(size)
    seed = int(time.time() * 1000) % 1_000_000  # a fresh seed each call, so asking twice doesn't return the same picture
    url = (f"https://image.pollinations.ai/prompt/{_urlquote(prompt)}"
           f"?width={width}&height={height}&seed={seed}&nologo=true")
    try:
        response = requests.get(url, timeout=90)
        response.raise_for_status()
    except requests.RequestException as e:
        raise ImageError(f"The free image service (Pollinations.ai) couldn't be reached: {e}")
    if "image" not in response.headers.get("content-type", ""):
        raise ImageError("The free image service didn't return a picture (it may be temporarily overloaded). Try again in a moment.")
    img = validate_image_bytes(response.content, max_bytes=50 * 1024 * 1024)
    path = _save(img, GENERATED_DIR, prompt, fmt="JPEG" if img.format == "JPEG" else "PNG")
    entry = remember(path, "generated", prompt=prompt)
    return {"path": path, "id": entry["id"], "prompt": prompt, "provider": "pollinations", **get_metadata(img, path)}


def _local_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"  # works, but genuinely slow (minutes per image) — mps/cuda is what makes this practical


LOCAL_WORKER_SCRIPT = os.path.join(APP_DIR, "local_image_worker.py")
LOCAL_LOAD_TIMEOUT = 900    # generous: a first-ever call also downloads the model (a few GB) over the network
LOCAL_INFER_TIMEOUT = 120   # tight: once downloaded, this should take seconds; a machine that can't finish in time
                             # (not enough free memory, thrashing) is killed and Jervis falls back automatically


def _local_model_cached(model: str) -> bool:
    try:
        from huggingface_hub import scan_cache_dir
        return any(repo.repo_id == model for repo in scan_cache_dir().repos)
    except Exception:
        return False


def _generate_local(prompt: str) -> dict:
    """Runs in a genuinely separate OS process (local_image_worker.py), not just a thread or a Python-level
    timeout: torch's MPS/CUDA calls can hold Python's GIL for a very long time, or the GPU driver itself can stall,
    in a way nothing inside this same process can reliably interrupt. Only killing the whole process — which
    subprocess.run(..., timeout=...) does, unconditionally, regardless of what that process is stuck on — can
    guarantee generating locally never hangs the rest of Jervis."""
    model = _local_image_model()
    device = _local_device()
    timeout = LOCAL_INFER_TIMEOUT if _local_model_cached(model) else LOCAL_LOAD_TIMEOUT
    fd, output_path = tempfile.mkstemp(suffix=".png", dir=GENERATED_DIR)
    os.close(fd)
    try:
        result = subprocess.run([sys.executable, LOCAL_WORKER_SCRIPT, model, device, output_path, prompt],
                                 timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        _try_remove(output_path)
        raise ImageError(f"Local image generation took too long (over {int(timeout)}s) and was stopped — this "
                          f"computer may not have enough free memory to run it comfortably right now.")
    if result.returncode != 0 or not os.path.getsize(output_path):
        _try_remove(output_path)
        lines = (result.stderr or "").strip().splitlines()
        raise ImageError(f"Local image generation failed: {lines[-1] if lines else 'no image was produced'}")
    with open(output_path, "rb") as f:
        raw = f.read()
    _try_remove(output_path)
    img = validate_image_bytes(raw, max_bytes=50 * 1024 * 1024)
    path = _save(img, GENERATED_DIR, prompt, fmt="PNG")
    entry = remember(path, "generated", prompt=prompt)
    return {"path": path, "id": entry["id"], "prompt": prompt, "provider": "local", **get_metadata(img, path)}


def generate(prompt: str, size: str = "auto") -> dict:
    """Tries, in order: the local model (unlimited, free, private, if installed — see requirements-local-images.txt),
    then OpenAI (if configured), then the free Pollinations.ai service (always available, no setup). Whichever one
    actually succeeds is used; if an earlier, normally-preferred one failed first, the result says so."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageError("Tell me what to draw, for example: generate an image of a futuristic city at night.")
    providers = []
    if local_generation_configured():
        providers.append(("the local model", lambda: _generate_local(prompt)))
    if generation_configured():
        providers.append(("OpenAI", lambda: _generate_openai(prompt, size)))
    providers.append(("the free Pollinations.ai service", lambda: _generate_pollinations(prompt, size)))

    failures = []
    for label, make in providers:
        try:
            result = make()
        except ImageError as e:
            failures.append(f"{label} ({e})")
            continue
        if failures:
            result["note"] = f"Used {label} after {' and '.join(failures)} didn't work."
        return result
    raise ImageError("Every image generator failed: " + "; ".join(failures))


def edit(instruction: str, size: str = "auto") -> dict:
    """Edit the most recent image. The original file on disk is never modified — the result is saved separately."""
    instruction = (instruction or "").strip()
    if not instruction:
        raise ImageError("Tell me how to edit the image, for example: remove the person in the background.")
    imgs = last_image(1)
    if not imgs:
        raise ImageError("There's no image to edit yet. Attach or upload one first.")
    source_path = imgs[-1]["path"]
    if not os.path.exists(source_path):
        raise ImageError("That image is no longer available.")
    client = _openai()
    try:
        with open(source_path, "rb") as f:
            response = client.images.edit(model=_openai_image_model(), image=f, prompt=instruction,
                                           size=size if size in _VALID_SIZES else "auto", quality="auto",
                                           input_fidelity="high", n=1)
    except Exception as e:
        raise ImageError(_openai_error_message(e, "edit"))
    b64 = getattr(response.data[0], "b64_json", None) if response.data else None
    if not b64:
        raise ImageError("The image editor didn't return any image data.")
    raw = base64.b64decode(b64)
    img = validate_image_bytes(raw, max_bytes=50 * 1024 * 1024)
    path = _save(img, EDITED_DIR, instruction, fmt="PNG")
    entry = remember(path, "edited", prompt=instruction)
    return {"path": path, "id": entry["id"], "instruction": instruction, "source": source_path, **get_metadata(img, path)}


# ---------- voice/text intent detection (mirrors app.py's is_*_command style) ----------
_GEN_VERBS_RE = re.compile(r"\b(?:generate|create|make|draw|paint|design|render)\b")
_IMG_NOUN_RE = re.compile(r"\b(?:image|picture|photo|photograph|drawing|painting|artwork|illustration|graphic|wallpaper|poster|logo|icon|avatar|pic)s?\b")
_EDIT_VERBS_RE = re.compile(
    r"\b(?:edit|remove|delete|erase|replace|swap|add|insert|change|alter|modify|recolor|recolour|colorize|colourize|"
    r"upscale|enhance|crop|resize|blur|sharpen|brighten|darken|desaturate)\b")
_IMAGE_WORD_RE = re.compile(r"\b(?:image|picture|photo|photograph|screenshot|background|sky)\b")
_OCR_RE = re.compile(
    r"\b(?:read|extract|transcribe)\b.{0,20}\b(?:text|words|writing)\b"
    r"|\bwhat\s+(?:does|do)\s+.{0,25}\bsay\b"
    r"|\bwhat'?s?\s+the\s+(?:text|error\s*message|error)\s+(?:in|on|says?)\b"
    r"|\bocr\b")
_COMPARE_RE = re.compile(r"\bcompar(?:e|ison|ing)\b|\bwhat'?s?\s+different\b|\bwhat\s+changed\b|\bdifferences?\s+between\b")
_ANALYZE_RE = re.compile(
    r"\b(?:analy[sz]e|describe)\b"
    r"|\bwhat'?s?\s+(?:in|on|wrong\s+with|happening\s+in)\s+(?:this|that|the)\b"
    r"|\bwhat\s+(?:do\s+you\s+see|is\s+this|is\s+in\s+(?:this|the))\b"
    r"|\blook\s+at\s+this\b"
    r"|\bexplain\s+this\s+(?:image|picture|photo|screenshot|chart|diagram)\b"
    r"|\b(?:image|picture|photo|photograph|screenshot|diagram|chart)\b")


def is_image_generation_command(text: str) -> bool:
    n = (text or "").lower()
    return bool(_GEN_VERBS_RE.search(n) and _IMG_NOUN_RE.search(n))


def is_image_edit_command(text: str) -> bool:
    n = (text or "").lower()
    if not _EDIT_VERBS_RE.search(n):
        return False
    return bool(_IMAGE_WORD_RE.search(n)) or has_pending_context()


def is_image_ocr_command(text: str) -> bool:
    return bool(_OCR_RE.search((text or "").lower()))


def is_image_compare_command(text: str) -> bool:
    return bool(_COMPARE_RE.search((text or "").lower()))


def is_image_analyze_command(text: str) -> bool:
    return bool(_ANALYZE_RE.search((text or "").lower()))


def is_image_command(text: str) -> bool:
    return (is_image_generation_command(text) or is_image_edit_command(text) or is_image_ocr_command(text)
            or is_image_compare_command(text) or is_image_analyze_command(text))
