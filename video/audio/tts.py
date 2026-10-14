"""Narration: each line of narration.json spoken by Groq's Orpheus voice (the same Groq key Jarvis already uses), saved
as audio/voice/<id>.wav. Lines already on disk with the same text and voice are kept, so re-running costs nothing.

    venv/bin/python video/audio/tts.py            # make what's missing
    venv/bin/python video/audio/tts.py --check    # also transcribe each file back and compare with the script
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "voice")
API = "https://api.groq.com/openai/v1"
MODEL = "canopylabs/orpheus-v1-english"


def groq_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
            if line.strip().startswith("GROQ_API_KEY"):
                key = line.split("=", 1)[1].strip().strip("\"'")
    if not key:
        sys.exit("No GROQ_API_KEY (in the environment or the project's .env).")
    return key


def speak(text: str, voice: str, path: str) -> None:
    body = json.dumps({"model": MODEL, "voice": voice, "input": text, "response_format": "wav"}).encode()
    request = urllib.request.Request(f"{API}/audio/speech", data=body, headers={
        "Authorization": f"Bearer {groq_key()}", "Content-Type": "application/json", "User-Agent": "curl/8"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            with open(path, "wb") as f:
                f.write(data)
            return
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429 and attempt < 5:
                wait = float(e.headers.get("retry-after") or 20)
                print(f"  rate limit, waiting {wait:.0f} s", flush=True)
                time.sleep(min(wait + 1, 120))
                continue
            sys.exit(f"Speech failed ({e.code}): {detail}")


def transcribe(path: str) -> str:
    boundary = "----jarvisfilm"
    with open(path, "rb") as f:
        audio = f.read()
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-large-v3-turbo\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
             f'Content-Type: audio/wav\r\n\r\n'.encode() + audio + b"\r\n", f"--{boundary}--\r\n".encode()]
    request = urllib.request.Request(f"{API}/audio/transcriptions", data=b"".join(parts), headers={
        "Authorization": f"Bearer {groq_key()}", "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "curl/8"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response).get("text", "").strip()


def main() -> None:
    script = json.load(open(os.path.join(HERE, "narration.json"), encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    stamps_path = os.path.join(OUT, "made.json")
    stamps = json.load(open(stamps_path)) if os.path.exists(stamps_path) else {}
    for line in script["lines"]:
        path = os.path.join(OUT, line["id"] + ".wav")
        voice = line.get("voice", script["voice"])
        stamp = hashlib.sha1(f"{voice}|{line['say']}".encode()).hexdigest()
        if not (os.path.exists(path) and stamps.get(line["id"]) == stamp) or line["id"] in sys.argv:
            print(f"speaking {line['id']}: {line['say']}", flush=True)
            speak(line["say"], voice, path)
            stamps[line["id"]] = stamp
            json.dump(stamps, open(stamps_path, "w"), indent=1)
        if "--check" in sys.argv:
            print(f"{line['id']}: heard: {transcribe(path)}", flush=True)


if __name__ == "__main__":
    main()
