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
# graphs, the 3D globe and planets on the phone (relay/server.py's VISUAL_FILES). On this branch the three drawing
# scripts the phone needs live in relay/web/: they are newer than this branch's desktop window (index.html) expects,
# so the window's own copies at the repo root are left exactly as they are.
COPY sphere_gl.js ./
COPY relay/web/graph.js relay/web/earth.js relay/web/planet.js ./
COPY vendor/earth ./vendor/earth
COPY vendor/planets ./vendor/planets
# the phone app's code scanner (pairing inside the app) and its display font
COPY vendor/jsqr ./vendor/jsqr
COPY vendor/fonts ./vendor/fonts
# Jarvis's brain for the phone (relay/server.py's BRAIN): the worker that runs it in the phone's browser, and the
# modules and map data it loads. Kept under relay/web/brain here so the relay serves the versions the phone app
# was built against, whatever the engine's own copies are.
COPY phone_brain_worker.js ./
COPY relay/web/brain ./brain
EXPOSE 8080
CMD ["python", "server.py"]
