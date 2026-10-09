"""Questions about the screen: "what's on my screen?", "what does this error say?", "explain this error", "what am I
looking at?". Jervis reads the window the user is working in and answers from what is really there:

  - first the window's own structure (computer_use.Environment.observe: the app, the window title, every dialog,
    button, field and piece of text with its value) — exact, instant, and nothing leaves the computer;
  - only when a window shows almost nothing that way (a custom-drawn app: Blender's viewport, a game, a video), the
    local vision model looks at a screenshot of it (screen_vision, local unless the user allowed online vision).

The answer is the chat model's, told to use only what was read — never to guess what isn't there.
"""
import re

QUESTION = re.compile(
    r"\b(?:what(?:'s| is) (?:on )?(?:my|the|this) screen|what(?:'s| is) on (?:my|the) screen|what am i looking at|"
    r"what(?:'s| is) (?:this|that) (?:window|page|error|app|dialog|popup|message)|read (?:my|the|this) screen|"
    r"(?:look|glance) at (?:my|the) screen|what does (?:this|the|that) (?:error|message|dialog|popup|page|window|"
    r"warning|screen) say|explain (?:this|the|that) (?:error|warning|message)|describe (?:my|the) screen|"
    r"why (?:is|did) (?:this|that|it) (?:error|crash|fail)\w*|can you see (?:my|the) screen)\b", re.I)
FEW_ELEMENTS = 6
MAX_LINES = 90

ANSWER_PROMPT = """You are Jervis, answering a question about what is on the user's screen right now. Below is what
was read from the window they are working in (its app, title, and its controls and text, in reading order; a
"(focused)" item has the keyboard focus). Answer the question in a few short sentences, using ONLY this information:
say what app and window it is and what matters in it. If there is an error or warning, quote its key words, explain
what it means in plain language and what to do about it. If something they ask about isn't in the information, say
you can't see it rather than guessing."""


def is_screen_question(text: str) -> bool:
    return bool(QUESTION.search(text or ""))


def summarize(observation) -> str:
    """The observation as compact text for the AI: what app, which window, and what's in it."""
    lines = [f"App: {observation.app or 'unknown'}", f"Window: {observation.window or '(no title)'}"]
    if observation.note:
        lines.append(f"Note: {observation.note}")
    seen = set()
    for e in observation.elements:
        text = (e.name or "").strip()
        value = "" if e.password else (e.value or "").strip()
        key = (e.role, text, value)
        if key in seen or not (text or value):
            continue
        seen.add(key)
        line = f"- {e.role}: {text[:160]}" if text else f"- {e.role}"
        if value and value != text:
            line += f" = “{value[:300]}”"
        if e.password:
            line += " (password field)"
        if e.focused:
            line += " (focused)"
        lines.append(line)
        if len(lines) >= MAX_LINES:
            lines.append(f"(+ more not shown)")
            break
    return "\n".join(lines)


def needs_vision(observation) -> bool:
    readable = [e for e in observation.elements if (e.name or e.value)]
    return len(readable) < FEW_ELEMENTS and observation.screenshot is not None


def answer(question: str, env, vision, chat) -> str:
    """Read the window and answer `question`. `chat(messages) -> text`."""
    ok, why = env.available()
    if not ok:
        return why
    observation = env.observe()
    if not observation.window and not observation.elements:
        return "I can't see any window to read right now."
    seen = summarize(observation)
    looked = ""
    if needs_vision(observation) and vision is not None:
        try:
            looked = vision.look(observation.screenshot, f"The user asks: {question}. Describe what is on this "
                                                          "screen that answers it, briefly and concretely.")
        except Exception as e:
            print(f"Looking at the screen failed: {e}", flush=True)
    content = seen + (f"\n\nWhat a look at the screenshot showed:\n{looked}" if looked else "")
    reply = chat([{"role": "system", "content": ANSWER_PROMPT},
                  {"role": "user", "content": f"{content}\n\nQuestion: {question}"}])
    return (reply or "").strip() or "I read the screen but couldn't make sense of it."
