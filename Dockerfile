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
COPY phone_client.html phone_sw.js confirm.html phone_manifest.webmanifest ./
COPY phone_icons ./phone_icons
EXPOSE 8080
CMD ["python", "server.py"]
