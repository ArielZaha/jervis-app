"""The files the phone app needs to show graphs, the 3D globe and planet models exactly as the computer's window does:
the window's own drawing scripts and their imagery. A fixed list, served by path: never a path taken from a request.
(Jarvis Wake and the relay keep the same list; tests/test_phone_visuals.py checks they agree.)"""

SCRIPTS = ("sphere_gl.js", "graph.js", "earth.js", "planet.js")
IMAGES = (
    "vendor/earth/blue_marble_5400.jpg", "vendor/earth/clouds_2048.jpg", "vendor/earth/night_lights_3600.jpg",
    "vendor/earth/earth_atmos_2048.jpg",
    "vendor/planets/2k_sun.jpg", "vendor/planets/2k_mercury.jpg", "vendor/planets/2k_venus_surface.jpg",
    "vendor/planets/2k_mars.jpg", "vendor/planets/2k_jupiter.jpg", "vendor/planets/2k_saturn.jpg",
    "vendor/planets/2k_saturn_ring_alpha.png", "vendor/planets/2k_uranus.jpg", "vendor/planets/2k_neptune.jpg",
    "vendor/planets/2k_moon.jpg",
)
WEEK = "public, max-age=604800"


def files() -> dict:
    """URL path -> (project file, content type, cache control)."""
    out = {f"/{name}": (name, "text/javascript; charset=utf-8", "no-cache") for name in SCRIPTS}
    for name in IMAGES:
        out[f"/{name}"] = (name, "image/png" if name.endswith(".png") else "image/jpeg", WEEK)
    return out
