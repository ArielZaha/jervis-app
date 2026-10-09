"""The Minecraft adapter against a fake game: it "runs" commands by appending what real Minecraft would write to
latest.log, so command translation, feedback reading, errors and block checks are all exercised without the game."""
import re

import agent_minecraft as mc

LOG_PREFIX = "[12:00:00] [Render thread/INFO]: [System] [CHAT] "


class FakeGame:
    def __init__(self, log_path, cheats=True):
        self.log_path = log_path
        self.cheats = cheats
        self.blocks = {}
        self.typed = []
        self.chat_open = False
        self.buffer = ""
        log_path.write_text("[12:00:00] [Render thread/INFO]: Loaded world\n", encoding="utf-8")

    def say(self, line):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(LOG_PREFIX + line + "\n")

    def press(self, key):
        if key == "t":
            self.chat_open, self.buffer = True, ""
        elif key == "enter" and self.chat_open:
            self.chat_open = False
            self.typed.append(self.buffer)
            self.run(self.buffer.lstrip("/"))

    def type_text(self, text):
        if self.chat_open:
            self.buffer += text

    def run(self, command):
        if not self.cheats:
            return self.say("Unknown or incomplete command, see below for error")
        if command == "data get entity @s Pos":
            return self.say("Steve has the following entity data: [10.7d, 64.0d, -3.2d]")
        m = re.fullmatch(r"setblock (-?\d+) (-?\d+) (-?\d+) (\S+)", command)
        if m:
            self.blocks[tuple(map(int, m.groups()[:3]))] = m.group(4)
            return self.say(f"Changed the block at {m.group(1)}, {m.group(2)}, {m.group(3)}")
        m = re.fullmatch(r"execute if block (-?\d+) (-?\d+) (-?\d+) (\S+)", command)
        if m:
            found = self.blocks.get(tuple(map(int, m.groups()[:3])))
            return self.say("Test passed" if found == m.group(4) else "Test failed")
        return self.say("Unknown or incomplete command, see below for error")


def adapter_for(game):
    return mc.MinecraftAdapter(log_path=str(game.log_path), keyboard=(game.press, game.type_text),
                               windows=lambda: [(1, "Minecraft 1.21.4")], focus=lambda hwnd: True,
                               sleep=lambda s: None)


def test_relative_coordinates_become_fixed_world_positions():
    assert mc.absolute("fill ~3 ~ ~-2 ~5 ~4 ~0 minecraft:stone", (10, 64, -4)) == \
        "fill 13 64 -6 15 68 -4 minecraft:stone"
    assert mc.absolute("tp @s ^ ^ ^5", (10, 64, -4)) == "tp @s ^ ^ ^5"     # local (^) coordinates left alone


def test_commands_are_read_one_per_line_without_slashes_or_comments():
    assert mc.commands_in("# walls\n/fill ~ ~ ~ ~1 ~1 ~1 stone\n\nsetblock ~ ~ ~ air") == \
        ["fill ~ ~ ~ ~1 ~1 ~1 stone", "setblock ~ ~ ~ air"]


def test_prepare_reads_where_the_player_is(tmp_path):
    game = FakeGame(tmp_path / "latest.log")
    adapter = adapter_for(game)
    adapter.prepare()
    assert adapter.origin == (10, 64, -4)


def test_prepare_explains_that_cheats_are_needed(tmp_path):
    adapter = adapter_for(FakeGame(tmp_path / "latest.log", cheats=False))
    try:
        adapter.prepare()
        assert False, "should have raised"
    except RuntimeError as e:
        assert "Allow Cheats" in str(e)


def test_commands_run_in_the_game_and_blocks_are_verified_by_the_game(tmp_path):
    game = FakeGame(tmp_path / "latest.log")
    adapter = adapter_for(game)
    adapter.prepare()
    result = adapter.execute("setblock ~3 ~0 ~3 minecraft:gold_block")
    assert result["ok"] and game.blocks[(13, 64, -1)] == "minecraft:gold_block"
    assert adapter.evaluate({"type": "block", "object": "minecraft:gold_block", "value": "~3 ~0 ~3"}, {})[0] is True
    assert adapter.evaluate({"type": "block", "object": "minecraft:stone", "value": "~3 ~0 ~3"}, {})[0] is False


def test_a_rejected_command_is_an_error_with_the_games_own_words(tmp_path):
    game = FakeGame(tmp_path / "latest.log")
    adapter = adapter_for(game)
    adapter.prepare()
    result = adapter.execute("setblock ~1 ~0 ~1 minecraft:stone\nfil ~ ~ ~ ~1 ~1 ~1 stone\nsetblock ~2 ~0 ~2 stone")
    assert not result["ok"] and "Unknown or incomplete command" in result["error"]
    assert len(game.typed) == 3      # position, the first setblock, the bad one — and nothing after it


def test_dangerous_commands_need_the_users_ok():
    adapter = mc.MinecraftAdapter(log_path="x", keyboard=(lambda k: None, lambda t: None))
    assert "kill" in adapter.risk("fill ~ ~ ~ ~1 ~1 ~1 stone\n/kill @e")
    assert adapter.risk("fill ~ ~ ~ ~1 ~1 ~1 stone") == ""


def test_not_available_without_the_game(tmp_path):
    adapter = mc.MinecraftAdapter(log_path=str(tmp_path / "none.log"), keyboard=(lambda k: None, lambda t: None),
                                  windows=lambda: [])
    ok, why = adapter.available()
    assert not ok and "isn't open" in why
