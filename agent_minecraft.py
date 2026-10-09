"""The agent's Minecraft (Java Edition) adapter: act with chat commands, verify with the game's own answers.

  Act:     each command is typed into the game's chat (T, the command, Enter). Needs cheats on: "Allow Cheats" for a
           single-player world, or operator rights on a server.
  Observe: Minecraft writes every chat/command reply into .minecraft/logs/latest.log, so the new lines after a
           command say exactly whether it worked ("Successfully filled 125 block(s)") or why not ("Unknown or
           incomplete command").
  Verify:  `/execute if block X Y Z <block>` makes the game itself answer "Test passed" / "Test failed".
  Place:   the AI writes coordinates relative to the player (~dx ~dy ~dz). The player's position is read once per
           request (/data get entity @s Pos) and every relative coordinate becomes an absolute one, so the whole
           build lands in one place even if the player walks away meanwhile.

Same shape as agent_blender.BlenderAdapter: app.py runs it through agent_core.AgentTask unchanged. Not yet run
against a real Minecraft (none was installed where this was written) — the log parsing and command handling are
covered by tests/test_agent_minecraft.py with a fake game.
"""
import math
import os
import re
import sys
import time

from agent_core import AppAdapter

MAX_COMMANDS = 60
FEEDBACK_SECONDS = 1.5
_ERRORS = re.compile(r"Unknown or incomplete command|Incorrect argument|Expected |<--\[HERE\]|Unknown block|"
                     r"No (?:player|entity) was found|That position is not loaded|Could not set the block|"
                     r"Too many blocks|cannot be placed|You do not have permission|Invalid|Unknown item|"
                     r"Can't place|is not loaded|failed", re.I)
_POSITION = re.compile(r"has the following entity data: \[(-?[\d.]+)d, (-?[\d.]+)d, (-?[\d.]+)d\]")
_TRIPLET = re.compile(r"(?<![\w^])~(-?\d+(?:\.\d+)?)?\s+~(-?\d+(?:\.\d+)?)?\s+~(-?\d+(?:\.\d+)?)?(?![\w.])")
_RISKY = re.compile(r"^/?(?:kill|stop|op|deop|ban|ban-ip|pardon|kick|whitelist|gamerule|difficulty|worldborder|"
                    r"save-off|clear|reload|forceload|publish|defaultgamemode)\b", re.I)
_CHAT_LINE = re.compile(r"\[(?:Render thread|Server thread)/INFO\]: (?:\[System\] )?(?:\[CHAT\] )?(.*)$")

INSTRUCTIONS = """App: Minecraft Java Edition, driven by chat commands (cheats are on). Each line of "code" is ONE command, \
with or without the leading slash; comments start with #. At most 60 commands per step.
Coordinates: write them relative to the player: ~dx ~dy ~dz (x = east+, y = up+, z = south+). ~0 ~0 ~0 is the block \
the player stands in; ~0 ~-1 ~0 is the ground under them. Build a few blocks away (e.g. starting at ~3 ~0 ~3) so \
nothing is built inside the player. Every ~ position is turned into a fixed world position before running.
Useful commands:
  fill ~3 ~0 ~3 ~9 ~4 ~9 minecraft:oak_planks hollow     a hollow box (walls, floor, ceiling); "outline" keeps the inside
  fill x1 y1 z1 x2 y2 z2 minecraft:air                     clear an area      setblock ~4 ~1 ~3 minecraft:oak_door[half=lower]
  summon minecraft:pig ~2 ~0 ~2    give @s minecraft:diamond 5    time set day|night    weather clear|rain
  tp @s ~0 ~10 ~0    effect give @s minecraft:night_vision 600    clone ...
Blocks: minecraft:stone, cobblestone, oak_planks, oak_log, spruce_planks, bricks, glass, glass_pane, red_wool,
white_wool, red_concrete, oak_stairs, oak_slab, torch, oak_door, water, lava, sand, dirt, grass_block, gold_block...
Rules: never kill, clear inventories, change game rules or affect other players unless the user asked. A fill may \
change at most 32768 blocks. Commands can't be undone, so build only what was asked.

Checks:
  {"type": "block", "object": "minecraft:oak_planks", "value": "~3 ~0 ~3"}   the game confirms that block is there
  {"type": "no_errors"}                                                       every command was accepted
Example — "build a small stone hut":
{"understanding": "Build a small hollow stone hut with a door in front of the player.", "question": "",
 "steps": [{"title": "Build the walls and roof", "code": "fill ~3 ~0 ~3 ~7 ~3 ~7 minecraft:cobblestone hollow\\nsetblock ~5 ~0 ~3 minecraft:air\\nsetblock ~5 ~1 ~3 minecraft:air",
            "checks": [{"type": "block", "object": "minecraft:cobblestone", "value": "~3 ~0 ~3"}, {"type": "block", "object": "minecraft:air", "value": "~5 ~0 ~3"}]}],
 "final_checks": [{"type": "block", "object": "minecraft:cobblestone", "value": "~7 ~3 ~7"}]}"""


def default_log_path() -> str:
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", ""), ".minecraft")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/minecraft")
    else:
        base = os.path.expanduser("~/.minecraft")
    return os.path.join(base, "logs", "latest.log")


def _keyboard():
    import winctl
    return winctl.press, winctl.type_text


def _windows():
    import app_launcher
    return app_launcher.app_windows("Minecraft")


def _focus(hwnd) -> bool:
    import winctl
    return winctl.focus(hwnd)


def absolute(command: str, origin) -> str:
    """Turn every ~dx ~dy ~dz triplet into fixed world coordinates around `origin` (the player's block)."""
    if origin is None:
        return command

    def fix(m):
        return " ".join(str(int(math.floor(base + float(off or 0)))) for base, off in zip(origin, m.groups()))
    return _TRIPLET.sub(fix, command)


def commands_in(code: str) -> list:
    lines = []
    for raw in (code or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line.lstrip("/").strip())
    return lines


class MinecraftAdapter(AppAdapter):
    name = "minecraft"
    label = "Minecraft"
    uses_input = True
    check_types = ("block", "no_errors")

    def __init__(self, log_path: str = None, keyboard=None, windows=None, focus=None, sleep=time.sleep):
        self.log_path = log_path or default_log_path()
        self.press, self.type_text = keyboard or _keyboard()
        self.windows = windows or _windows
        self.focus = focus or _focus
        self.sleep = sleep
        self.origin = None
        self.recent = []

    def available(self) -> tuple:
        if not self.windows():
            return False, "Minecraft isn't open, so there's nothing for me to build in."
        if not os.path.exists(self.log_path):
            return False, "I can't find Minecraft's log file, which is how I read the game's answers."
        return True, ""

    # ---------- talking to the game ----------
    def _log_size(self) -> int:
        try:
            return os.path.getsize(self.log_path)
        except OSError:
            return 0

    def _new_lines(self, offset: int) -> list:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                text = f.read()
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            m = _CHAT_LINE.search(line)
            if m and m.group(1).strip():
                out.append(m.group(1).strip())
        return out

    def _send(self, command: str) -> list:
        """Type one command into the chat and return the game's reply lines."""
        windows = self.windows()
        if windows:
            self.focus(windows[0][0])
            self.sleep(0.15)
        offset = self._log_size()
        self.press("t")
        self.sleep(0.25)          # the chat box needs a moment to open, or the first characters are lost
        self.type_text("/" + command)
        self.sleep(0.05)
        self.press("enter")
        deadline = time.time() + FEEDBACK_SECONDS
        lines = []
        while time.time() < deadline:
            self.sleep(0.1)
            lines = self._new_lines(offset)
            if lines:
                self.sleep(0.15)  # a command can answer with several lines
                return self._new_lines(offset)
        return lines

    def prepare(self) -> None:
        reply = self._send("data get entity @s Pos")
        for line in reply:
            m = _POSITION.search(line)
            if m:
                self.origin = tuple(math.floor(float(v)) for v in m.groups())
                return
        problem = next((l for l in reply if _ERRORS.search(l)), "")
        raise RuntimeError("Minecraft didn't tell me where you are" + (f" (it said: {problem})" if problem else "")
                           + ". Commands need cheats on: open the world to LAN with \"Allow Cheats\" on, or ask for "
                             "operator rights on a server.")

    def observe(self) -> dict:
        return {"origin": self.origin, "recent": self.recent[-8:]}

    def describe(self, state: dict) -> str:
        where = f"The player stands at block {state.get('origin')} (that's ~0 ~0 ~0)."
        recent = state.get("recent") or []
        return where + ("\nLatest game messages: " + " | ".join(recent) if recent else "")

    def instructions(self) -> str:
        return INSTRUCTIONS

    def execute(self, code: str) -> dict:
        commands = commands_in(code)
        if not commands:
            return {"ok": False, "output": "", "error": "there were no commands in the code"}
        if len(commands) > MAX_COMMANDS:
            return {"ok": False, "output": "", "error": f"too many commands at once ({len(commands)}); split it"}
        replies = []
        for command in commands:
            command = absolute(command, self.origin)
            reply = self._send(command)
            self.recent += reply
            problem = next((l for l in reply if _ERRORS.search(l)), None)
            if problem:
                return {"ok": False, "output": " | ".join(replies),
                        "error": f"Minecraft rejected /{command}: {problem}"}
            replies += reply[-1:]
        return {"ok": True, "output": " | ".join(replies[-3:]), "error": ""}

    def evaluate(self, check: dict, state: dict) -> tuple:
        kind = check.get("type")
        if kind == "no_errors":
            return True, "every command was accepted"
        if kind == "block":
            where = absolute(str(check.get("value") or ""), self.origin)
            block = str(check.get("object") or "").strip()
            if not re.fullmatch(r"-?\d+ -?\d+ -?\d+", where) or not block:
                return None, f"can't check a block at '{check.get('value')}'"
            reply = " ".join(self._send(f"execute if block {where} {block}"))
            if "passed" in reply.lower():
                return True, f"{block} is at {where}"
            if "failed" in reply.lower():
                return False, f"{block} is not at {where}"
            return None, f"Minecraft didn't answer the check at {where}"
        return None, f"unknown check type {kind!r}"

    def risk(self, code: str) -> str:
        risky = next((c for c in commands_in(code) if _RISKY.match(c)), None)
        return f"run the Minecraft command /{risky}" if risky else ""
