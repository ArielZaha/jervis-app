"""Writes a film's words to files, from the film's own timeline (audio/cues.<film>.json):

    out/Jarvis_Showcase_Final.srt, showcase_script.md     venv/bin/python video/audio/subtitles.py
    out/Jarvis_Trailer_Final.srt,  trailer_script.md      venv/bin/python video/audio/subtitles.py trailer

The subtitles hold what the narrator says (trailer), what is asked of Jarvis, and what Jarvis answers (the part of
his reply that is heard). The script is the same, readable, with the on-screen titles.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = os.path.join(HERE, "..")
FILM = sys.argv[1] if len(sys.argv) > 1 else "showcase"
NAME = {"showcase": "Jarvis_Showcase_Final", "trailer": "Jarvis_Trailer_Final"}[FILM]
cues = json.load(open(os.path.join(HERE, f"cues.{FILM}.json"), encoding="utf-8"))


def stamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def heard(text: str, seconds: float, total: float) -> str:
    """The sentences of a reply that fit in the time it is on the soundtrack (the film cuts long replies short)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    keep, used = [], 0.0
    for sentence in sentences:
        share = total * len(sentence) / max(1, len(text))
        if keep and used + share * 0.6 > seconds:
            break
        keep.append(sentence)
        used += share
    return " ".join(keep)


lines = []
for cue in cues["cues"]:
    if cue["kind"] == "ask":
        lines.append((cue["t"], cue["t"] + max(1.2, cue["len"] + 0.5), f"“{cue['text']}”", cue.get("how", "said"), cue["scene"]))
    elif cue["kind"] == "narrate":
        lines.append((cue["t"], cue["t"] + cue["len"] + 0.3, cue["text"], "Narrator", cue["scene"]))
    elif cue["kind"] == "voice":
        footage = json.load(open(os.path.join(VIDEO, "assets", "footage", cue["file"].rsplit("_", 1)[0] + ".json"), encoding="utf-8"))
        full = next(l for l in footage["lines"] if l["file"] == cue["file"])
        lines.append((cue["t"], cue["t"] + cue["len"], "Jarvis: " + heard(cue["text"], cue["len"], full["seconds"]), "Jarvis", cue["scene"]))
lines.sort()
# no subtitle runs into the next one
def tidy(rows):
    return [(a, min(b, rows[i + 1][0] - 0.05) if i + 1 < len(rows) else b, text, who, scene) for i, (a, b, text, who, scene) in enumerate(rows)]


fixed = tidy(lines)
# The trailer's subtitle file holds only what is heard (the narrator and Jarvis); the requests are silent words on
# screen there, and stay in the written script.
in_file = tidy([row for row in lines if row[3] in ("Narrator", "Jarvis")]) if FILM == "trailer" else fixed

os.makedirs(os.path.join(VIDEO, "out"), exist_ok=True)
with open(os.path.join(VIDEO, "out", NAME + ".srt"), "w", encoding="utf-8") as f:
    for n, (a, b, text, _who, _scene) in enumerate(in_file, start=1):
        f.write(f"{n}\n{stamp(a)} --> {stamp(max(b, a + 0.7))}\n{text}\n\n")

TITLES = {
    "wake": "1. “Hey Jarvis” — one sentence, two things done (0:00)",
    "mind": "2. One spoken thread of mathematics",
    "world": "3. The Earth, a sunrise, a planet",
    "link": "4. From the phone, on the computer — and the phone alone",
    "control": "5. With permission, the mouse and keyboard",
    "more": "6. Everything else, one beat each",
    "close": "7. Close",
    "mystery": "Act 1 — Mystery: something asleep in the dark",
    "awakening": "Act 2 — Awakening: his name, and he wakes",
    "power": "Act 3 — Power: speak, ask, watch",
    "escalation": "Act 4 — Escalation: control, the phone, everything",
    "reveal": "Act 5 — The reveal",
}
ON_SCREEN = {
    "wake": "JARVIS — Your personal AI assistant. It listens — and it acts. — Created by Ariel and Shalev",
    "mind": "the question as it is said, and Jarvis's answer as a subtitle",
    "world": "the question as it is said, and Jarvis's answer as a subtitle",
    "link": "Ask on your phone. It happens here. / Or let the phone answer by itself.",
    "control": "He can take the mouse. He asks first.",
    "more": "Music. Trailers. Documents. Pictures. Vision. Calendar. Step by step. Android. Local AI. Paired by code.",
    "close": "JARVIS — One assistant. Your computer. Your phone. — Created by Ariel and Shalev — macOS · Windows 10 and 11 · iPhone · Android",
    "mystery": "the sleeping orb, close, in the dark; three flashes of what is coming",
    "awakening": "the real window asleep, then awake; the wordmark JARVIS",
    "power": "the requests as they are said; Jarvis's answers as subtitles",
    "escalation": "With your permission — He takes the mouse. / Music. Trailers. Documents. Pictures. Calendar. Answers. Android. Weather.",
    "reveal": "JARVIS — YOUR COMPUTER. YOUR COMMAND. — Created by Ariel and Shalev",
}
INTRO = {
    "showcase": "There is no narrator. The only voice is Jarvis's own: the replies he gave in the takes, spoken with the\n"
                "voice the app really uses on this Mac. Requests are shown on screen as they are said or typed.",
    "trailer": "A narrator carries the trailer (bold lines without a name). Jarvis's own voice is heard three times: the\n"
               "replies he gave in the takes. Requests are shown on screen as they are said or typed.",
}
with open(os.path.join(VIDEO, f"{FILM}_script.md"), "w", encoding="utf-8") as f:
    f.write(f"# Jarvis {FILM} — script\n\n{INTRO[FILM]}\nThis file is written by `audio/subtitles.py` from the film's timeline; "
            f"the same lines are in\n`out/{NAME}.srt`.\n")
    for scene in cues["scenes"]:
        f.write(f"\n## {TITLES.get(scene['id'], scene['id'])}\n\n`{stamp(scene['start'])[3:8]}–{stamp(scene['end'])[3:8]}` · on screen: *{ON_SCREEN.get(scene['id'], '')}*\n\n")
        for a, _b, text, who, sc in fixed:
            if sc == scene["id"]:
                shown = f"**{text}**" if who in ("Jarvis", "Narrator") else f"{text} ({who})"
                f.write(f"- `{stamp(a)[3:8]}` {shown}\n")
print(f"{len(in_file)} subtitles -> out/{NAME}.srt; {len(fixed)} lines -> {FILM}_script.md")
