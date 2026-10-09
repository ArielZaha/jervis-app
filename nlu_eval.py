"""Jervis language evaluation: realistic commands (English, Hebrew, mixed, speech-recognition slips, follow-ups,
ambiguity, chit-chat) run through the language-understanding layer, scored against the intent that's right.

    python nlu_eval.py                          the deterministic layer + every installed candidate model
    python nlu_eval.py qwen2.5-coder:7b         just these models

A case passes when the intent is right and every expected slot matches (case-insensitively, as a substring).
"Hallucinated action" = the model chose an action where the right answer was chat, ignore or clarify.
"""
import json
import re
import sys
import time

import local_llm
import nlu

BLENDER = {"app_in_front": "Blender", "blender_objects": ["Cube", "Cube.001"], "blender_focus": "Cube.001",
           "last_command": "create a cube"}
SPOTIFY = {"app_in_front": "Spotify", "last_song": "Bohemian Rhapsody — Queen"}

# (said, context, expected intent, expected slots)
CASES = [
    # English
    ("Open Blender.", {}, "open_app", {"app": "blender"}),
    ("Create a cube.", BLENDER, "blender_create", {"shape": "cube"}),
    ("Make it twice as tall.", BLENDER, "object_resize", {"change": "taller", "times": "2"}),
    ("Open Spotify.", {}, "open_app", {"app": "spotify"}),
    ("Play a song.", SPOTIFY, "music_play", {}),
    ("Go back to Blender.", SPOTIFY, "switch_app", {"app": "blender"}),
    ("Move the second cube next to the first one.", BLENDER, "object_move", {"target": "second", "next_to": "first"}),
    ("Undo that.", BLENDER, "undo", {}),
    ("Do that again.", BLENDER, "repeat", {}),
    ("Stop controlling my computer.", {"control_session": True}, "control_stop", {}),
    ("Make it taller.", BLENDER, "object_resize", {"target": "it", "change": "taller"}),
    ("Play Bohemian Rhapsody by Queen on Spotify", {}, "music_play", {"query": "bohemian rhapsody"}),
    ("could you paint the cube red please", BLENDER, "object_color", {"color": "red"}),
    ("build a small wooden house in blender", {}, "blender_build", {"description": "house"}),
    ("set a timer for ten minutes", {}, "timer", {"duration": "10"}),
    # Hebrew
    ("תפתח בלנדר", {}, "open_app", {"app": "blender"}),
    ("תיצור קובייה", BLENDER, "blender_create", {"shape": "cube"}),
    ("תעשה אותה פי שתיים יותר גבוהה", BLENDER, "object_resize", {"change": "taller", "times": "2"}),
    ("תפתח ספוטיפיי", {}, "open_app", {"app": "spotify"}),
    ("תפעיל את השיר הזה", SPOTIFY, "music_play", {}),
    ("תחזור לבלנדר", SPOTIFY, "switch_app", {"app": "blender"}),
    ("תזיז את הקובייה השנייה ליד הראשונה", BLENDER, "object_move", {"target": "second", "next_to": "first"}),
    ("תבטל את זה", BLENDER, "undo", {}),
    ("תעשה את זה שוב", BLENDER, "repeat", {}),
    ("תפסיק לשלוט במחשב", {"control_session": True}, "control_stop", {}),
    ("תצבע את הקובייה בכחול", BLENDER, "object_color", {"color": "blue"}),
    ("תבנה לי בית קטן עם גג אדום בבלנדר", {}, "blender_build", {"description": "house"}),
    ("תכוון טיימר לחמש דקות", {}, "timer", {"duration": "5"}),
    ("מה השעה עכשיו בניו יורק?", {}, "chat", {}),
    # mixed
    ("תפתח Blender", {}, "open_app", {"app": "blender"}),
    ("תיצור cube", BLENDER, "blender_create", {"shape": "cube"}),
    ("תעשה את ה-cube יותר גדול", BLENDER, "object_resize", {"change": "bigger"}),
    ("open Spotify ותפעיל את השיר הזה", {}, "open_app", {"app": "spotify"}),
    ("תחזור ל-Blender", SPOTIFY, "switch_app", {"app": "blender"}),
    # speech-recognition slips
    ("Open blend ever", {}, "open_app", {"app": "blender"}),
    ("Jervis stay control", {}, "control_start", {}),
    ("make the cube girl", BLENDER, "object_resize", {"change": "bigger"}),
    ("open spot if I", {}, "open_app", {"app": "spotify"}),
    # genuinely unclear / not commands
    ("take it to a level", BLENDER, "clarify", {}),
    ("and I will see you in the next video", {}, "ignore|chat", {}),
    ("for Blendale. Oh my god, that's a hot deal.", {}, "ignore|chat", {}),
    ("I installed Chrome yesterday", {}, "chat", {}),
    ("what's the capital of Japan", {}, "chat", {}),
    ("make it", BLENDER, "clarify", {}),
]

# Written after the prompt was tuned on CASES, and never used for tuning: an honest check for overfitting.
HELDOUT = [
    ("launch blender for me", {}, "open_app", {"app": "blender"}),
    ("add a sphere", BLENDER, "blender_create", {"shape": "sphere"}),
    ("shrink it a bit", BLENDER, "object_resize", {"change": "smaller"}),
    ("could you make the cube three times wider", BLENDER, "object_resize", {"change": "wider", "times": "3"}),
    ("put the sphere on the left", BLENDER, "object_move", {"direction": "left"}),
    ("turn it green", BLENDER, "object_color", {"color": "green"}),
    ("skip this song", SPOTIFY, "music_next", {}),
    ("turn the music down", SPOTIFY, "volume", {"direction": "down"}),
    ("close chrome", {}, "close_app", {"app": "chrome"}),
    ("put on some Daft Punk", {}, "music_play", {"query": "daft punk"}),
    ("תגדיל אותה", BLENDER, "object_resize", {"change": "bigger"}),
    ("תוסיף כדור", BLENDER, "blender_create", {"shape": "sphere"}),
    ("תעצור את המוזיקה", SPOTIFY, "music_pause", {}),
    ("תעביר לשיר הבא", SPOTIFY, "music_next", {}),
    ("תסגור את כרום", {}, "close_app", {"app": "chrome"}),
    ("תבנה עץ גדול בבלנדר", {}, "blender_build", {"description": "tree"}),
    ("תשים את ה-sphere משמאל", BLENDER, "object_move", {"direction": "left"}),
    ("open blunder", {}, "open_app", {"app": "blender"}),
    ("make it blew", BLENDER, "object_color", {"color": "blue"}),
    ("do the thing", BLENDER, "clarify", {}),
    ("move it", BLENDER, "clarify", {}),
    ("yeah my brother is coming at five", {}, "ignore|chat", {}),
    ("איזה יום יפה היום", {}, "chat|ignore", {}),
    ("open the", {}, "clarify|ignore", {}),
]

# Written after the fixes HELDOUT prompted, run once: the final unbiased check.
FRESH = [
    ("fire up spotify", {}, "open_app", {"app": "spotify"}),
    ("make the sphere twice as big", BLENDER, "object_resize", {"change": "bigger"}),
    ("paint it yellow", BLENDER, "object_color", {"color": "yellow"}),
    ("delete the second cube", BLENDER, "object_delete", {"target": "second"}),
    ("rotate it 45 degrees", BLENDER, "object_rotate", {"degrees": "45"}),
    ("תוריד את הווליום", SPOTIFY, "volume", {"direction": "down"}),
    ("תעשה אותו קטן יותר", BLENDER, "object_resize", {"change": "smaller"}),
    ("תפתח את יוטיוב", {}, "open_app", {"app": "youtube"}),
    ("תזיז את הכדור למעלה", BLENDER, "object_move", {"direction": "up"}),
    ("תנגן משהו של קווין", {}, "music_play", {"query": "queen"}),
    ("set a time for two minutes", {}, "timer", {"duration": "2"}),
    ("open blender and", {}, "open_app", {"app": "blender"}),
    ("make it nicer", BLENDER, "clarify", {}),
    ("that's so funny haha", {}, "chat|ignore", {}),
    ("he said to open the door", {}, "chat|ignore", {}),
    ("ok so turn", BLENDER, "clarify|ignore", {}),
]


def score(case, got) -> bool:
    _, _, intent, slots = case
    if got.get("intent") not in intent.split("|"):
        return False
    for slot, want in slots.items():
        have = str(got.get(slot) or "").lower()
        want_alts = {want, {"2": "two", "10": "ten", "5": "five"}.get(want, want)}
        if not any(w in have for w in want_alts):
            return False
    return True


def run_model(model: str, cases=None) -> dict:
    cases = CASES if cases is None else cases
    ok = fails = hallucinated = invalid = pipeline = 0
    times, wrong, pipeline_wrong = [], [], []
    try:   # load it into the GPU first, so the first case isn't timed with the model's loading
        local_llm.chat_json([{"role": "user", "content": "hi"}], nlu.SCHEMA, model=model, max_tokens=5)
    except Exception:
        pass
    for case in cases:
        said, ctx, intent, _ = case
        start = time.time()
        try:
            raw = local_llm.chat_json(nlu._messages(said, ctx), nlu.SCHEMA, model=model, max_tokens=160,
                                      temperature=0.0, timeout=60)
            got = nlu.validate(raw)
        except Exception as e:
            got, invalid = {"intent": "error", "error": str(e)[:80]}, invalid + 1
        times.append(time.time() - start)
        good = score(case, got)
        if pipeline_correct(case, got):
            pipeline += 1
        else:
            pipeline_wrong.append((said, intent, nlu.rewrite(said) or nlu.decide(said, got)))
        if good:
            ok += 1
        else:
            fails += 1
            wrong.append((said, intent, got))
            if set(intent.split("|")) & {"chat", "ignore", "clarify"} and got.get("intent") not in ("chat", "ignore",
                                                                                                    "clarify", "error"):
                hallucinated += 1
    times.sort()
    return {"model": model, "correct": ok, "pipeline": pipeline, "total": len(cases), "hallucinated_actions": hallucinated,
            "invalid": invalid, "median_s": round(times[len(times) // 2], 2), "max_s": round(times[-1], 2),
            "wrong": wrong, "pipeline_wrong": pipeline_wrong}


# What a deterministic rewrite must look like to count as the right intent.
CANONICAL = {"open_app": r"^open ", "switch_app": r"^(?:go back to|switch to|open) ", "blender_create": r"^create ",
             "object_resize": r"^make .*(?:taller|bigger|smaller|shorter|wider|narrower|half)",
             "object_color": r"^make .* [a-z]+$", "object_move": r"^move ", "undo": r"^undo$",
             "repeat": r"again$", "control_stop": r"^stop controlling", "control_start": r"(?:stay|be|keep) in control|"
             r"take control", "music_play": r"^(?:play|resume)", "timer": r"^set a timer",
             "blender_build": r"^in blender, build ", "music_next": r"^next song$", "music_pause": r"^pause the music$", "object_rotate": r"^rotate ",
             "object_delete": r"^delete ",
             "close_app": r"^close ", "volume": r"^volume (?:up|down)$"}   # chat / clarify / ignore: never a command


def _command_ok(intent, slots, command) -> bool:
    if not re.search(CANONICAL.get(intent, r"$^"), command, re.I):
        return False
    return all(str(v).lower() in command.lower() or {"2": "two", "5": "five", "10": "ten"}.get(v, "~") in
               command.lower() for k, v in slots.items() if k in ("app", "shape", "color", "duration"))


def pipeline_correct(case, got) -> bool:
    """What Jervis really does: the deterministic rewrite when it recognises the command, else the model's intent
    through nlu.decide (clarify when an action lacks what it needs, chat for an unasked-for search)."""
    said, _, intent, slots = case
    rewritten = nlu.rewrite(said)
    if rewritten:
        return _command_ok(intent, slots, rewritten)
    if not nlu.worth_understanding(said):      # questions and chatter go to the chat model, as before
        return bool(set(intent.split("|")) & {"chat", "ignore"})
    kind, command = nlu.decide(said, got)
    if kind != "command":
        return kind in intent.split("|")
    return _command_ok(intent, slots, command)


def run_rules() -> dict:
    """What the deterministic layer alone gets right (instant, no model)."""
    handled = [(said, nlu.rewrite(said)) for said, *_ in (HELDOUT if "--heldout" in sys.argv else
                                                         FRESH if "--fresh" in sys.argv else CASES)]
    return {"handled": [(s, r) for s, r in handled if r], "unhandled": [s for s, r in handled if not r]}


if __name__ == "__main__":
    rules = run_rules()
    print(f"Deterministic layer: {len(rules['handled'])}/{len(rules['handled']) + len(rules['unhandled'])} rewritten "
          "instantly")
    for said, canonical in rules["handled"]:
        print(f"   {said!r:45} -> {canonical!r}")
    cases = HELDOUT if "--heldout" in sys.argv else FRESH if "--fresh" in sys.argv else CASES
    models = [a for a in sys.argv[1:] if not a.startswith("--")] or [m for m in ("qwen2.5-coder:7b", "qwen3:8b", "qwen3:4b", "gemma3:4b", "llama3.2:latest")
                               if m in local_llm.installed_models()]
    results = []
    for model in models:
        r = run_model(model, cases)
        results.append(r)
        print(f"\n{model}: {r['correct']}/{r['total']} correct alone, {r['pipeline']}/{r['total']} with the "
              f"deterministic layer first, {r['hallucinated_actions']} hallucinated actions, "
              f"{r['invalid']} invalid, median {r['median_s']}s, max {r['max_s']}s")
        for said, want, got in r["wrong"]:
            print(f"   x {said!r:45} wanted {want:15} got {json.dumps(got, ensure_ascii=False)[:150]}")
        for said, want, got in r["pipeline_wrong"]:
            print(f"   PIPELINE x {said!r:45} wanted {want:15} got {got}")
