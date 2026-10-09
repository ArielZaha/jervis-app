"""Measuring a picture directly (no AI): how bright and warm it is, where the sky ends, what colour a region really
is, and where windows glow. The vision model judges WHAT things are; these numbers check HOW they look — a model
called a lit Tokyo shopfront at night "golden hour" and put a villa's horizon at 80% of the height; the pixels
said otherwise.

Pure numpy + Pillow, so it runs anywhere Jervis does and is cheap (a few ms on a 1 MP picture)."""
import math

import numpy as np
from PIL import Image

WORK = 384    # the long side pictures are measured at: plenty for colours and brightness


def _arr(img: Image.Image, long_side: int = WORK) -> np.ndarray:
    img = img.convert("RGB")
    s = long_side / max(img.size)
    if s < 1:
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def _lum(a: np.ndarray) -> np.ndarray:
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def _hsv(a: np.ndarray):
    mx, mn = a.max(axis=-1), a.min(axis=-1)
    v = mx
    s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    return h, s, v


def stats(img: Image.Image) -> dict:
    """Overall light of the picture: brightness, contrast, warmth, the share of glowing and of dark pixels, and how
    the top (usually sky) compares with the rest — the evidence for day, dusk or night."""
    a = _arr(img)
    lum = _lum(a)
    h, s, v = _hsv(a)
    top = lum[: max(1, lum.shape[0] // 4)]
    bright = lum > 0.85
    warm = (h < 60) & (s > 0.35) & (v > 0.6)
    mean_rgb = a.reshape(-1, 3).mean(axis=0)
    out = {
        "mean": float(lum.mean()), "median": float(np.median(lum)), "p10": float(np.percentile(lum, 10)),
        "p90": float(np.percentile(lum, 90)), "contrast": float(np.percentile(lum, 95) - np.percentile(lum, 5)),
        "top_mean": float(top.mean()), "dark_share": float((lum < 0.12).mean()),
        "bright_share": float(bright.mean()), "warm_light_share": float(warm.mean()),
        "saturation": float(s.mean()),
        "warmth": float((mean_rgb[0] - mean_rgb[2]) / max(1e-3, mean_rgb.mean())),   # >0 warm, <0 cool
        "blue_top": float((a[: max(1, a.shape[0] // 4), :, 2] - a[: max(1, a.shape[0] // 4), :, 0]).mean()),
    }
    out["night_score"] = night_score(out)
    return out


def night_score(st: dict) -> float:
    """0 (broad daylight) .. 1 (night): a dark picture, a dark top, with bright warm lights in it."""
    # Artificial light among darkness is the strongest evidence: a lit shopfront is mid-grey on average (its signs
    # and windows), but a dark forest at noon has no warm glow, and a sunlit orange wall isn't dark.
    dark = max(0.0, min(1.0, (0.32 - st["median"]) / 0.22))
    dark_top = max(0.0, min(1.0, (0.35 - st["top_mean"]) / 0.25))
    lit = max(0.0, min(1.0, (st["warm_light_share"] - 0.02) / 0.05))
    return round(min(1.0, 0.35 * dark + 0.25 * dark_top + 0.4 * lit * (1.0 if st["median"] < 0.4 else 0.2)), 3)


def time_of_day(st: dict, said: str = None) -> tuple:
    """(time of day, confidence): the model's word, checked against the light. A dark picture lit by windows is night
    whatever the model said; a bright one isn't night."""
    said = (said or "").lower().strip()
    n = st["night_score"]
    if n > 0.5:
        guess = "dusk" if st["top_mean"] > 0.22 and st["blue_top"] > 0.05 else "night"
        return (guess, 0.85) if said not in ("night", "dusk") else (said, 0.9)
    if said in ("night",) and n < 0.25 and st["median"] > 0.35:
        return ("dusk" if st["warmth"] > 0.15 else "day", 0.5)
    if said in ("sunset", "golden hour", "dusk", "sunrise") and st["warmth"] < -0.05 and st["median"] > 0.4:
        return ("day", 0.45)
    if said in ("morning", "midday", "afternoon", "day", "noon", "daytime"):
        return (said, 0.75)
    if said:
        return (said, 0.65)
    return ("night" if n > 0.45 else "day", 0.5)


def sky_rows(img: Image.Image) -> dict:
    """Where the sky is: for each column, how far down from the top it reaches (fraction of height), from sky-like
    pixels (bright and blue-grey, or the dark smooth top of a night sky). The skyline at the picture's sides is the
    best evidence for the horizon in an outdoor view."""
    a = _arr(img, 256)
    H, W = a.shape[:2]
    lum = _lum(a)
    h, s, v = _hsv(a)
    blue = (a[..., 2] >= a[..., 0] - 0.02) & (lum > 0.35)
    grey = (s < 0.18) & (lum > 0.55)
    gy = np.abs(np.diff(lum, axis=0, prepend=lum[:1]))
    smooth = gy < 0.06
    skyish = (blue | grey) & smooth
    depth = np.zeros(W)
    for x in range(W):
        col = skyish[:, x]
        if not col[0]:
            continue
        stop = np.argmin(col) if not col.all() else H
        depth[x] = stop / H
    edge = max(1, W // 10)
    sides = np.concatenate([depth[:edge], depth[-edge:]])
    sides = sides[sides > 0.02]   # only columns where the sky really reaches the top (not a tree in the corner)
    open_cols = depth[depth > 0.02]
    # A long level line across the whole picture (sea against sky, a flat plain): the strongest row of horizontal
    # edges, if it is far stronger than the rest.
    row_edges = gy.mean(axis=1)
    row_edges[:2] = row_edges[-2:] = 0
    peak = int(row_edges.argmax())
    level = peak / H if row_edges[peak] > 4 * max(1e-6, float(np.median(row_edges))) and \
        (gy[peak] > 0.03).mean() > 0.6 else None
    # within the sky: the clear blue (its colour, for a sky to match) and how much of it is cloud (white or grey)
    rows = np.arange(H)[:, None] < (depth[None, :] * H)
    clear = rows & (s > 0.12) & (a[..., 2] > a[..., 0] + 0.03)
    cloud = rows & (s < 0.1) & (lum > 0.55)
    n_sky = int(clear.sum() + cloud.sum())
    cover = float(cloud.sum()) / n_sky if n_sky > 50 else None
    high = clear & (np.arange(H)[:, None] < (depth[None, :] * H * 0.5))   # the blue overhead, not the pale horizon
    pick = high if high.sum() > 50 else clear
    clear_rgb = [float(np.median(a[..., i][pick])) for i in range(3)] if pick.sum() > 50 else None
    return {"columns": depth.tolist(), "share": float((depth > 0.02).mean()),
            "cloud_cover": cover, "clear_rgb": clear_rgb,
            "sides": float(np.median(sides)) if sides.size else None,
            "typical": float(np.median(open_cols)) if open_cols.size else None,
            "lowest": float(depth.max()), "level_line": level}


def region(img: Image.Image, box, inner: float = 0.2) -> dict:
    """What a region really looks like: its dominant colour (the biggest of a few colour clusters in its middle),
    brightness, how much of it glows warm, and whether it is lit from inside (windows at night)."""
    W, H = img.size

    def clamp_box(a, b, c, d):
        a, c = sorted((max(0, min(W - 1, int(a))), max(0, min(W - 1, int(c)))))
        b, d = sorted((max(0, min(H - 1, int(b))), max(0, min(H - 1, int(d)))))
        return a, b, max(a + 1, c + 1), max(b + 1, d + 1)
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * inner, (y2 - y1) * inner
    crop = img.crop(clamp_box(x1 + dx, y1 + dy, x2 - dx, y2 - dy))
    if crop.width < 2 or crop.height < 2:
        crop = img.crop(clamp_box(x1, y1, x2, y2))
    a = _arr(crop, 96)
    px = a.reshape(-1, 3)
    lum = _lum(px)
    h, s, v = _hsv(px)
    colour = dominant(px)
    return {"color": to_hex(colour), "rgb": [round(float(c), 3) for c in colour], "brightness": float(lum.mean()),
            "glow_share": float(((lum > 0.75) & (h < 70) & (s > 0.25)).mean()),
            "bright_share": float((lum > 0.85).mean()), "saturation": float(s.mean())}


def dominant(px: np.ndarray, k: int = 3, iterations: int = 8) -> np.ndarray:
    """The most common colour among pixels (k-means on a sample), not the muddy average of all of them."""
    if len(px) == 0:
        return np.array([0.5, 0.5, 0.5])
    if len(px) > 3000:
        px = px[np.linspace(0, len(px) - 1, 3000).astype(int)]
    k = min(k, len(px))
    centres = px[np.linspace(0, len(px) - 1, k).astype(int)].copy()
    for _ in range(iterations):
        d = ((px[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            if (lab == j).any():
                centres[j] = px[lab == j].mean(0)
    counts = np.bincount(lab, minlength=k)
    return centres[counts.argmax()]


def to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(float(c) * 255)))):02x}" for c in rgb[:3])


def glowing_windows(img: Image.Image, box) -> dict:
    """Bright warm patches inside a building's box, as evidence its windows are lit (night/dusk): how many, how much
    of the facade, and how much their brightness varies (some rooms lit, some not)."""
    W, H = img.size
    x1, y1, x2, y2 = [int(v) for v in box]
    crop = img.crop((max(0, x1), max(0, y1), min(W, x2), min(H, y2)))
    if crop.width < 4 or crop.height < 4:
        return {"lit_share": 0.0, "patches": 0, "variation": 0.0}
    a = _arr(crop, 160)
    lum = _lum(a)
    h, s, v = _hsv(a)
    # brighter than the facade's darker parts, and warm: however many of the windows are lit
    lit = (lum > max(0.45, float(np.percentile(lum, 30)) + 0.25)) & (h < 75) & (s > 0.15)
    patches = _count_blobs(lit)
    vals = lum[lit]
    return {"lit_share": float(lit.mean()), "patches": patches,
            "variation": float(vals.std() / max(1e-3, vals.mean())) if vals.size else 0.0,
            "warmth": float(((a[..., 0] - a[..., 2])[lit]).mean()) if vals.size else 0.0}


def _count_blobs(mask: np.ndarray, min_px: int = 6) -> int:
    """Connected patches in a small mask (4-neighbour flood fill)."""
    mask = mask.copy()
    H, W = mask.shape
    n = 0
    for y in range(H):
        for x in range(W):
            if not mask[y, x]:
                continue
            stack, size = [(y, x)], 0
            mask[y, x] = False
            while stack:
                cy, cx = stack.pop()
                size += 1
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx]:
                        mask[ny, nx] = False
                        stack.append((ny, nx))
            if size >= min_px:
                n += 1
    return n


# ---------- comparing two pictures (a reference and a render) ----------

def _lab(a: np.ndarray) -> np.ndarray:
    """sRGB (0-1) to CIE Lab, enough for colour distances."""
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def compare(reference: Image.Image, render: Image.Image, grid=(8, 6)) -> dict:
    """How alike two pictures are, in numbers: colour layout (Lab distance per grid cell), brightness, and
    structure (edge-map correlation). 0 distance / 1 correlation = the same. The worst cells say WHERE they differ."""
    gw, gh = grid
    ref = reference.convert("RGB").resize((gw * 16, gh * 16), Image.BILINEAR)
    ren = render.convert("RGB").resize((gw * 16, gh * 16), Image.BILINEAR)
    a, b = np.asarray(ref, np.float32) / 255, np.asarray(ren, np.float32) / 255
    la, lb = _lab(a), _lab(b)
    cells = np.zeros((gh, gw))
    for j in range(gh):
        for i in range(gw):
            ca = la[j * 16:(j + 1) * 16, i * 16:(i + 1) * 16].reshape(-1, 3).mean(0)
            cb = lb[j * 16:(j + 1) * 16, i * 16:(i + 1) * 16].reshape(-1, 3).mean(0)
            cells[j, i] = float(np.linalg.norm(ca - cb))
    ea, eb = _edges(_lum(a)), _edges(_lum(b))
    ea, eb = ea - ea.mean(), eb - eb.mean()
    corr = float((ea * eb).sum() / max(1e-6, math.sqrt((ea ** 2).sum() * (eb ** 2).sum())))
    worst = sorted(((cells[j, i], i, j) for j in range(gh) for i in range(gw)), reverse=True)[:4]
    return {"color_distance": float(cells.mean()), "brightness_ref": float(_lum(a).mean()),
            "brightness_render": float(_lum(b).mean()), "structure": corr,
            "worst_cells": [{"x": (i + 0.5) / gw, "y": (j + 0.5) / gh, "distance": round(float(d), 1)}
                            for d, i, j in worst],
            "score": round(max(0.0, 1 - cells.mean() / 60) * 0.6 + max(0.0, corr) * 0.4, 4)}


def _edges(l: np.ndarray) -> np.ndarray:
    gx = np.abs(np.diff(l, axis=1, prepend=l[:, :1]))
    gy = np.abs(np.diff(l, axis=0, prepend=l[:1]))
    e = gx + gy
    # blur a little so a line one pixel off still counts as the same line
    k = np.ones(5) / 5
    e = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, e)
    return np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, e)
