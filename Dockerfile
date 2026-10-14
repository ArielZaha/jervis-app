# Builds relay/server.py — the small, secret-free router that lets a paired phone reach Jarvis from anywhere (see
# relay/server.py's own docstring and relay/README.md). This is the only part of Jarvis that's containerized; the
# app itself isn't. Lives at the repo root (not relay/Dockerfile) because Render's CLI-driven deploys need the
# Dockerfile and its build context in the same directory — unlike Fly, which lets them differ — and the context
# has to be the repo root either way, so the relay can COPY phone_client.html/phone_sw.js/confirm.html straight
# from the one canonical copy the local phone server also serves (phone_control.py), instead of keeping second
# copies that could drift out of sync. Deploy steps for both Render and Fly: relay/README.md.
FROM python:3.12-slim
WORKDIR /app
COPY relay/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY relay/server.py .
COPY phone_client.html phone_sw.js confirm.html phone_manifest.webmanifest phone_agent.js ./
COPY phone_icons ./phone_icons
# graphs, the 3D globe and planets on the phone (relay/server.py's VISUAL_FILES)
COPY sphere_gl.js graph.js earth.js planet.js ./
COPY vendor/earth ./vendor/earth
COPY vendor/planets ./vendor/planets
COPY vendor/jsqr ./vendor/jsqr
COPY vendor/fonts ./vendor/fonts
# Jarvis's brain for the phone (relay/server.py's BRAIN): the worker that runs it, the modules, the map data
COPY phone_brain_worker.js ./
COPY typos.py functions.py equations.py graphs.py geo.py earth.py planets.py timers.py forecast.py music.py phone_brain.py ./brain/
COPY geo_data/countries_50m.json geo_data/places_10m.json ./brain/geo_data/
EXPOSE 8080
CMD ["python", "server.py"]
