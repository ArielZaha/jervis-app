"""The agent loop (agent_core.AgentTask) with a fake app and a scripted fake AI: plan -> act -> verify -> repair ->
fix-up -> honest summary. No model, no Blender."""
import pytest

import agent_core
import agent_memory


class FakeApp(agent_core.AppAdapter):
    """A tiny "app" whose state is a set of names; code is `make A B` / `fail <message>` / `noop`."""
    name = "fake"
    label = "FakeApp"
    check_types = ("exists", "near")
    relational_checks = ("near",)

    def __init__(self):
        self.things = set()
        self.ran = []
        self.rollbacks = 0
        self.floating = set()

    def observe(self):
        return {"things": sorted(self.things)}

    def describe(self, state):
        return ", ".join(state["things"]) or "(empty)"

    def execute(self, code):
        self.ran.append(code)
        word, _, rest = code.partition(" ")
        if word == "fail":
            return {"ok": False, "output": "", "error": rest}
        if word == "make":
            self.things |= set(rest.split())
        return {"ok": True, "output": "", "error": ""}

    def snapshot(self):
        return set(self.things)

    def rollback(self, snapshot):
        self.rollbacks += 1
        self.things = set(snapshot)

    def evaluate(self, check, state):
        if check["type"] == "exists":
            ok = check["object"] in state["things"]
            return ok, f"{check['object']} {'exists' if ok else 'is missing'}"
        if check["type"] == "near":
            return False, f"{check['object']} is too far from {check['other']}"
        return None, "?"

    def auto_checks(self, code):
        word, _, rest = code.partition(" ")
        return [{"type": "exists", "object": n} for n in rest.split()] if word == "make" else []

    def made(self, before, state):
        return sorted(set(state["things"]) - set(before or ()))


def scripted(*answers):
    """A fake ask_json that returns the given answers in order (and records what it was asked)."""
    calls = []

    def ask(messages, schema, **kw):
        calls.append({"messages": messages, "schema": schema, **kw})
        return answers[len(calls) - 1] if len(calls) <= len(answers) else answers[-1]
    ask.calls = calls
    return ask


def plan(*steps, final=()):
    return {"understanding": "Build it.", "question": "",
            "steps": [{"title": t, "code": c, "checks": list(ch)} for t, c, ch in steps], "final_checks": list(final)}


def run(app, ask, goal="build it", **kw):
    task = agent_core.AgentTask(goal, app, ask_json=ask, log=lambda m: None, **kw)
    return task, task.run()


def test_one_call_plan_runs_and_verifies_every_step():
    app = FakeApp()
    ask = scripted(plan(("Walls", "make Walls", []), ("Roof", "make Roof", []),
                        final=[{"type": "exists", "object": "Roof"}]))
    task, result = run(app, ask)
    assert task.state == "completed"
    assert len(ask.calls) == 1                      # the whole request: one model call
    assert app.ran == ["make Walls", "make Roof"]
    assert result.startswith("Done") and "3 of 3 checks passed" in result
    assert "Walls" in result and "Roof" in result


def test_existence_of_named_objects_is_checked_even_without_ai_checks():
    app = FakeApp()
    task, _ = run(app, scripted(plan(("Walls", "make Walls", []))))
    assert task.plan["steps"][0]["checks"] == [{"type": "exists", "object": "Walls"}]


def test_an_error_is_rolled_back_and_repaired():
    app = FakeApp()
    ask = scripted(plan(("Roof", "fail NameError: name 'roofx' is not defined", [])),
                   {"diagnosis": "typo", "code": "make Roof", "checks_were_wrong": False})
    task, result = run(app, ask)
    assert task.state == "completed"
    assert app.rollbacks == 1 and app.ran[-1] == "make Roof"
    repair_prompt = ask.calls[1]["messages"][-1]["content"]
    assert "roofx" in repair_prompt and "COMPLETE code" in repair_prompt   # the AI sees the real error


def test_a_failed_check_is_repaired_with_the_failure_in_the_prompt():
    app = FakeApp()
    ask = scripted(plan(("Two things", "make A", [{"type": "exists", "object": "B"}])),
                   {"diagnosis": "forgot B", "code": "make A B", "checks_were_wrong": False})
    task, _ = run(app, ask)
    assert task.state == "completed"
    assert "B is missing" in ask.calls[1]["messages"][-1]["content"]


def test_a_step_that_never_works_stops_the_rest_and_says_so_honestly():
    app = FakeApp()
    broken = {"diagnosis": "?", "code": "fail still broken", "checks_were_wrong": False}
    ask = scripted(plan(("First", "fail boom", []), ("Second", "make B", [])), broken)
    task, result = run(app, ask)
    assert task.state == "error"
    assert "make B" not in app.ran                     # never ran after its foundation failed
    assert app.things == set()                         # every failed attempt was undone
    assert result.startswith("I couldn't do that") and "nothing is left half-done" in result


def test_the_fix_up_finishes_what_a_failed_step_left_and_counts_as_success():
    app = FakeApp()
    ask = scripted(plan(("First", "fail boom", []), ("Second", "make B", []),
                        final=[{"type": "exists", "object": "A"}, {"type": "exists", "object": "B"}]),
                   {"diagnosis": "x", "code": "fail boom", "checks_were_wrong": False},
                   {"diagnosis": "x", "code": "fail boom", "checks_were_wrong": False},
                   {"diagnosis": "x", "code": "fail boom", "checks_were_wrong": False},
                   {"diagnosis": "do both", "code": "make A B", "checks_were_wrong": False})
    task, result = run(app, ask)
    assert task.state == "completed" and result.startswith("Done")
    prompts = [c["messages"][-1]["content"] for c in ask.calls]
    assert any("never ran" in p and "'Second'" in p for p in prompts)   # the fix-up was told what was skipped


def test_the_ais_own_relational_check_doesnt_block_working_code_forever():
    app = FakeApp()
    near = {"type": "near", "object": "Chair", "other": "Table"}
    ask = scripted(plan(("Chairs", "make Chair Table", [near])),
                   {"diagnosis": "checks fine", "code": "make Chair Table", "checks_were_wrong": False})
    task, result = run(app, ask)
    assert task.state == "completed"
    assert len(ask.calls) == 2      # one repair, then accepted with the check left unconfirmed (not counted)


def test_the_ai_can_correct_its_own_wrong_step_check():
    app = FakeApp()
    ask = scripted(plan(("A", "make A", [{"type": "exists", "object": "Z"}])),
                   {"diagnosis": "Z was a mistake", "code": "make A", "checks_were_wrong": True,
                    "checks": [{"type": "exists", "object": "A"}]})
    task, _ = run(app, ask)
    assert task.state == "completed"


def test_a_question_instead_of_steps_is_asked_back():
    task, result = run(FakeApp(), scripted({"understanding": "?", "question": "Which room?", "steps": [],
                                            "final_checks": []}))
    assert result == "Which room?" and task.state == "completed"


def test_unavailable_app_or_ai_is_reported_plainly():
    class Closed(FakeApp):
        def available(self):
            return False, "FakeApp isn't open."
    task, result = run(Closed(), scripted(plan(("A", "make A", []))))
    assert result == "FakeApp isn't open." and task.state == "error"

    def no_ai(*a, **k):
        raise agent_core.local_llm.LocalAIUnavailable("no local AI model is installed yet")
    task, result = run(FakeApp(), no_ai)
    assert "no local AI model" in result


def test_stop_before_planning_does_nothing():
    app = FakeApp()
    task = agent_core.AgentTask("x", app, ask_json=scripted(plan(("A", "make A", []))), log=lambda m: None)
    task.stop()
    assert task.run().startswith("Stopped") and app.ran == []


def test_successful_requests_are_remembered_and_offered_for_similar_ones(tmp_path):
    memory = agent_memory.Memory(str(tmp_path / "memory.json"))
    run(FakeApp(), scripted(plan(("Walls", "make Walls", []))), goal="build a small red house", memory=memory)
    again = scripted(plan(("Walls", "make Walls", [])))
    run(FakeApp(), again, goal="build a small blue house", memory=memory)
    assert "build a small red house" in again.calls[0]["messages"][-1]["content"]
    assert agent_memory.Memory(str(tmp_path / "memory.json")).similar("small house", "fake")   # persisted


def test_failed_requests_are_not_remembered(tmp_path):
    memory = agent_memory.Memory(str(tmp_path / "memory.json"))
    run(FakeApp(), scripted(plan(("A", "fail x", [])), {"diagnosis": "", "code": "fail x",
                                                        "checks_were_wrong": False}), memory=memory)
    assert memory.similar("build it", "fake") == []


def test_code_fences_from_the_model_are_stripped():
    assert agent_core.clean_code("```python\nmake A\n```") == "make A"


def test_only_layout_guesses_failing_after_the_fix_up_is_not_called_a_failure():
    app = FakeApp()
    near = {"type": "near", "object": "Car", "other": "House"}
    ask = scripted(plan(("Car", "make Car", []), final=[{"type": "exists", "object": "Car"}, near]),
                   {"diagnosis": "", "code": "make Car", "checks_were_wrong": False})
    task, result = run(app, ask)
    assert task.state == "completed" and result.startswith("Done")
    assert "couldn't confirm" in result


def test_a_missing_part_is_still_a_failure_even_with_layout_failures():
    app = FakeApp()
    ask = scripted(plan(("Car", "make Car", []), final=[{"type": "exists", "object": "Wheel"},
                                                          {"type": "near", "object": "Car", "other": "House"}]),
                   {"diagnosis": "", "code": "make Car", "checks_were_wrong": False})
    task, result = run(app, ask)
    assert task.state == "error"


# ---------- quality tiers, inspect-and-refine, scenes ----------

@pytest.mark.parametrize("goal,tier", [("add a tree", "normal"), ("build a detailed realistic house", "high"),
                                       ("a beautiful polished chair", "high"), ("make a quick low poly rock", "simple"),
                                       ("make the roof blue", "normal")])
def test_quality_tier_comes_from_the_request(goal, tier):
    assert agent_core.quality_tier(goal) == tier


class CriticApp(FakeApp):
    """Objects to how plain the build is until a 'Detail' part exists."""
    scene_layout = False

    def quality_issues(self, before, state, goal, tier="normal"):
        return [] if "Detail" in state["things"] else ["too plain: add detail"]


def test_inspection_drives_a_refinement_round_that_is_kept():
    app = CriticApp()
    ask = scripted(plan(("Body", "make Body", [])),
                   {"diagnosis": "add detail", "code": "make Detail", "checks_were_wrong": False})
    task, result = run(app, ask)
    assert task.state == "completed" and "Detail" in app.things
    assert "improved the modelling" in result and task.quality_left == []
    assert "too plain" in ask.calls[1]["messages"][-1]["content"]


def test_a_refinement_that_breaks_the_request_is_undone():
    app = CriticApp()
    ask = scripted(plan(("Body", "make Body", []), final=[{"type": "exists", "object": "Body"}]),
                   {"diagnosis": "rebuild", "code": "remove-body", "checks_were_wrong": False})
    original = app.execute

    def execute(code):
        if code == "remove-body":
            app.things.discard("Body")
            app.things.add("Detail")
            return {"ok": True, "output": "", "error": ""}
        return original(code)
    app.execute = execute
    task, result = run(app, ask)
    assert "Body" in app.things          # the round broke the request's own check, so it was rolled back
    assert task.refined == []


def test_simple_requests_are_not_refined():
    app = CriticApp()
    ask = scripted(plan(("Body", "make Body", [])))
    task, _ = run(app, ask, goal="a quick simple box")
    assert len(ask.calls) == 1 and task.quality_left == ["too plain: add detail"]


def test_a_scene_is_built_thing_by_thing():
    class SceneApp(FakeApp):
        scene_layout = True
    app = SceneApp()
    layout = {"separate_things": True, "things": [{"name": "Bench", "request": "a bench", "x": 0, "y": 0},
                                                  {"name": "Tree 1", "request": "a tree", "x": 4, "y": 0}]}
    ask = scripted(layout, plan(("Bench", "make Bench", [])), plan(("Tree", "make Tree1", [])))
    task, result = run(app, ask, goal="a park with a bench and two trees")
    assert app.things == {"Bench", "Tree1"} and task.state == "completed"
    assert "x=4.0" in ask.calls[2]["messages"][-1]["content"]          # each thing built at its own spot
    assert result.startswith("Done: I built a bench, a tree")


def test_one_detailed_thing_is_not_split_into_a_scene():
    class SceneApp(FakeApp):
        scene_layout = True
    app = SceneApp()
    ask = scripted({"separate_things": False, "things": []}, plan(("House", "make House", [])))
    task, _ = run(app, ask, goal="a house with a red roof, a door and two windows")
    assert app.things == {"House"} and len(ask.calls) == 2


def test_summaries_are_shortened_to_whole_sentences_never_mid_claim():
    text = ("Done: I built a 3.5 m beach and three palm trees, each one checked. I checked how everything stands "
            "together. I also gave it its natural motion: Palm Tree 1 sways in the wind; Palm Tree 2 sways.")
    short = agent_core.sentences(text, 120)
    assert short == "Done: I built a 3.5 m beach and three palm trees, each one checked. I checked how everything " \
                    "stands together."
    assert agent_core.sentences("short", 50) == "short"
    assert agent_core.sentences("x" * 400, 50).endswith("…")
