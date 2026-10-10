"""The files the phone app needs to show graphs, the 3D globe and planet models exactly as the computer's window does:
the window's own drawing scripts and their imagery. A fixed list, served by path: never a path taken from a request.
(Jarvis Wake and the relay keep the same list; tests/test_phone_visuals.py checks they agree.)"""

# jsQR: the in-app code scanner. phone_brain_worker.js: Jarvis's own brain running on the phone (see BRAIN).
SCRIPTS = ("sphere_gl.js", "graph.js", "earth.js", "planet.js", "vendor/jsqr/jsQR.js", "phone_brain_worker.js")
FONTS = ("vendor/fonts/orbitron-latin.woff2",)   # the window's display face, so the phone reads as the same Jarvis
IMAGES = (
    "vendor/earth/blue_marble_5400.jpg", "vendor/earth/clouds_2048.jpg", "vendor/earth/night_lights_3600.jpg",
    "vendor/earth/earth_atmos_2048.jpg",
    "vendor/planets/2k_sun.jpg", "vendor/planets/2k_mercury.jpg", "vendor/planets/2k_venus_surface.jpg",
    "vendor/planets/2k_mars.jpg", "vendor/planets/2k_jupiter.jpg", "vendor/planets/2k_saturn.jpg",
    "vendor/planets/2k_saturn_ring_alpha.png", "vendor/planets/2k_uranus.jpg", "vendor/planets/2k_neptune.jpg",
    "vendor/planets/2k_moon.jpg",
)
# Jarvis's brain for the phone: the modules that work things out (math, graphs, the globe, planets, weather, timers,
# music requests) and the map data, loaded into Python inside the phone's browser by phone_brain_worker.js. Pure
# calculation, no secrets and nothing that acts on a computer. Served under /brain/.
BRAIN = ("typos.py", "functions.py", "equations.py", "graphs.py", "geo.py", "earth.py", "planets.py", "timers.py",
         "forecast.py", "music.py", "phone_brain.py", "geo_data/countries_50m.json", "geo_data/places_10m.json")
WEEK = "public, max-age=604800"


def files() -> dict:
    """URL path -> (project file, content type, cache control)."""
    out = {f"/{name}": (name, "text/javascript; charset=utf-8", "no-cache") for name in SCRIPTS}
    for name in IMAGES:
        out[f"/{name}"] = (name, "image/png" if name.endswith(".png") else "image/jpeg", WEEK)
    for name in FONTS:
        out[f"/{name}"] = (name, "font/woff2", WEEK)
    for name in BRAIN:
        out[f"/brain/{name}"] = (name, "application/json" if name.endswith(".json") else "text/x-python; charset=utf-8",
                                 WEEK if name.endswith(".json") else "no-cache")
    return out
