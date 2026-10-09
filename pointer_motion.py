"""How Jervis moves the mouse pointer: a short, smooth glide to the target instead of a jump.

A person watching should be able to follow where the pointer goes before it clicks, so the movement:
  - takes time that grows with the distance, the way a hand's does (Fitts's law: ~0.15 s for a nudge, ~0.6 s
    across a big screen), never long enough to feel slow;
  - speeds up and slows down smoothly (a minimum-jerk profile), and lands exactly on the target;
  - follows a gentle arc (a hand never moves in a ruler-straight line), bending the same way for the same move, so
    repeated runs behave identically.

Pure functions only (no OS calls): winctl (Windows) and screen_mac (macOS) drive the real pointer with them.
"""
import math

RATE_HZ = 120           # pointer updates per second
MIN_SECONDS = 0.12
MAX_SECONDS = 0.65
NUDGE_PIXELS = 4        # closer than this: just set it, there's nothing to watch


def duration_for(distance: float) -> float:
    """Seconds for a move of this many pixels."""
    if distance <= NUDGE_PIXELS:
        return 0.0
    return max(MIN_SECONDS, min(MAX_SECONDS, 0.07 + 0.11 * math.log2(1 + distance / 40)))


def ease(t: float) -> float:
    """Minimum-jerk position profile: 0 -> 1 with zero speed and acceleration at both ends."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (10 - 15 * t + 6 * t * t)


def path(start, end, rate_hz: int = RATE_HZ) -> list:
    """The pointer positions (integer pixels) from just after `start` up to exactly `end`, one per tick."""
    (x0, y0), (x1, y1) = (float(start[0]), float(start[1])), (float(end[0]), float(end[1]))
    dx, dy = x1 - x0, y1 - y0
    distance = math.hypot(dx, dy)
    seconds = duration_for(distance)
    if seconds == 0.0:
        return [(int(round(x1)), int(round(y1)))]
    ticks = max(2, int(seconds * rate_hz))
    # The arc: a quadratic Bezier whose control point sits off the straight line by ~7% of the distance (capped),
    # on a side that depends only on the move itself.
    bulge = min(60.0, 0.07 * distance) * (1 if (int(x0) * 7 + int(y0) * 13 + int(x1) * 3 + int(y1)) % 2 else -1)
    cx = (x0 + x1) / 2 - dy / distance * bulge
    cy = (y0 + y1) / 2 + dx / distance * bulge
    points = []
    for i in range(1, ticks + 1):
        s = ease(i / ticks)
        u = 1 - s
        x = u * u * x0 + 2 * u * s * cx + s * s * x1
        y = u * u * y0 + 2 * u * s * cy + s * s * y1
        point = (int(round(x)), int(round(y)))
        if not points or point != points[-1]:
            points.append(point)
    points[-1] = (int(round(x1)), int(round(y1)))
    return points


class PointerTakenOver(Exception):
    """The user moved the mouse while Jervis was moving it: stop at once, they're taking over."""


def glide(start, end, set_position, get_position, sleep, abort_pixels: int = 25, rate_hz: int = RATE_HZ) -> None:
    """Move the pointer from `start` to `end` along path(), through the platform's own functions. Raises
    PointerTakenOver as soon as the pointer is somewhere Jervis didn't put it (the user grabbed the mouse)."""
    last = (int(start[0]), int(start[1]))
    for point in path(start, end, rate_hz):
        now = get_position()
        if now is not None and math.hypot(now[0] - last[0], now[1] - last[1]) > abort_pixels:
            raise PointerTakenOver("You moved the mouse, so I stopped moving it.")
        set_position(*point)
        last = point
        sleep(1.0 / rate_hz)
