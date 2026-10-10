"""Two functions on one graph: reading the request however it is put, what is said about each, and how they relate
(where they meet, which is higher, parallel / perpendicular / tangent, the same shape moved, mirror images, the area
between them). The numbers are checked against the mathematics, not against the code's own output."""
import json
import math

import pytest

import graphs


def pair_for(sentence):
    request = graphs.parse_request(sentence)
    assert request and request["action"] == "several", sentence
    return graphs.build_pair(request["requests"], request["names"])


@pytest.mark.parametrize("sentence, labels", [
    ("graph y = x^2 and y = x + 1", ["f(x) = x²", "g(x) = x + 1"]),
    ("create a graph y=x^2 and g = x+ 1", ["f(x) = x²", "g(x) = x + 1"]),
    ("y = x^2 and y = x + 1", ["f(x) = x²", "g(x) = x + 1"]),
    ("compare y = x^2 and y = x + 1", ["f(x) = x²", "g(x) = x + 1"]),
    ("draw x squared and x plus 1 on the same graph", ["f(x) = x²", "g(x) = x + 1"]),
    ("plot x squared vs x plus 1", ["f(x) = x²", "g(x) = x + 1"]),
    ("graph both x squared and x plus 1 together", ["f(x) = x²", "g(x) = x + 1"]),
    ("graph h(x) = x^2 and p(x) = x + 1", ["h(x) = x²", "p(x) = x + 1"]),
    ("graph sine of x and cosine of x", ["f(x) = sin(x)", "g(x) = cos(x)"]),
])
def test_two_functions_are_read_however_they_are_asked_for(sentence, labels):
    assert [f["label"] for f in pair_for(sentence)["functions"]] == labels


@pytest.mark.parametrize("sentence", ["graph x squared", "graph a 1, b 2 and c 3", "compare apples and oranges", "graph x squared times 3"])
def test_one_function_stays_one_function(sentence):
    request = graphs.parse_request(sentence)
    assert request is None or request["action"] != "several"


def test_a_parabola_and_a_line_that_cuts_it():
    pair = pair_for("graph y = x^2 and y = x + 1")
    golden = (1 + math.sqrt(5)) / 2
    assert [(p["x"], p["y"]) for p in pair["meet"]] == [(round(1 - golden, 6), round(2 - golden, 6)), (round(golden, 6), round(golden + 1, 6))]
    relation = pair["relation"]
    assert relation["notes"] == ["The line cuts through the parabola at two points"]
    assert [(h["who"], h["from"], h["to"]) for h in relation["higher"]] == [("f", None, -0.618034), ("g", -0.618034, 1.618034), ("f", 1.618034, None)]
    assert relation["area"] == pytest.approx(5 * math.sqrt(5) / 6, abs=1e-5)      # ∫ (x + 1 − x²) between the roots
    text = graphs.describe_pair(pair)
    assert text.startswith("Here are both on one graph. f is a parabola and g is a straight line. They meet at two points: "
                           "x equals negative 0.62 and x equals 1.62.")
    for part in ("### f(x) = x²", "- **Vertex:** $(0,\\ 0)$", "### g(x) = x + 1", "- **Slope:** $1$", "### How they relate",
                 "- **Meet at:** $(-0.618,\\ 0.382)$, $(1.618,\\ 2.618)$", "- **Area between them:** $\\approx 1.8634$ square units"):
        assert part in text, part
    json.dumps(pair, allow_nan=False)        # everything in it can be sent to the window


@pytest.mark.parametrize("sentence, note, meets", [
    ("graph y = 2x + 1 and y = 2x - 3", "The lines are parallel: both have slope 2, so they never meet. They stay 1.7889 apart", 0),
    ("graph y = 2x and y = -0.5x + 4", "The lines are perpendicular: they cross at a right angle (their slopes multiply to −1)", 1),
    ("graph y = x and y = 3x", "The lines cross at an angle of 26.6°", 1),
    ("graph y = x^2 and y = 2x - 1", "The line is tangent to the parabola: it touches it at exactly one point", 1),
    ("graph y = x^2 and y = x - 5", "The line never touches the parabola", 0),
    ("graph y = x^2 and g = (x-2)^2 + 1", "The parabolas have the same shape: g is f moved 2 to the right and 1 up", 1),
    ("graph y = x^2 and y = -x^2", "They are mirror images of each other across the x-axis (g is −f)", 1),
    ("graph y = x^3 and y = (-x)^3 + 0x", "They are mirror images of each other across the x-axis (g is −f)", 1),
    ("graph y = 2^x and y = 2^(-x)", "They are mirror images of each other across the y-axis", 1),
    ("graph y = x^3 and y = x^3 + 2", "g is f moved 2 up: they are always exactly that far apart", 0),
])
def test_what_is_special_about_the_pair(sentence, note, meets):
    pair = pair_for(sentence)
    assert note in pair["relation"]["notes"], pair["relation"]["notes"]
    assert len(pair["meet"]) == meets


def test_the_same_function_twice_is_said_to_be_one():
    pair = pair_for("graph y = x^2 and y = x*x")
    assert pair["relation"]["same"] and "They are the same function" in graphs.describe_pair(pair)


def test_curves_that_meet_for_ever_are_looked_at_where_they_are_drawn():
    pair = pair_for("graph sine of x and cosine of x")
    view = pair["view"]
    assert -8 < view["xmin"] < -4 and 4 < view["xmax"] < 8
    assert [round(p["x"], 4) for p in pair["meet"]] == [round(math.pi / 4 + k * math.pi, 4) for k in (-2, -1, 0, 1)]
    assert all(view["xmin"] <= p["x"] <= view["xmax"] for p in pair["meet"])


def test_a_curve_with_a_gap_is_compared_on_each_side_of_it():
    higher = pair_for("graph y = 1/x and y = x")["relation"]["higher"]
    assert [(h["who"], h["from"], h["to"]) for h in higher] == [("f", None, -1.0), ("g", -1.0, 0.0), ("f", 0.0, 1.0), ("g", 1.0, None)]
    assert pair_for("graph y = 1/x and y = x")["relation"]["area"] is None      # nothing is enclosed across the gap


def test_three_functions_share_the_axes_with_every_meeting_point_once():
    pair = pair_for("graph x^3 and x and x^2")
    assert len(pair["functions"]) == 3 and pair["relation"] is None
    assert [(p["x"], p["y"]) for p in pair["meet"]] == [(-1.0, -1.0), (0.0, 0.0), (1.0, 1.0)]
    assert graphs.describe_pair(pair).startswith("Here are all 3 on one graph.")


def test_the_view_holds_every_point_that_matters():
    for sentence in ("graph y = x^2 and y = x + 1", "graph y = x^2 - 9 and y = 2x + 6", "graph y = -x^2 + 4 and y = x^2 - 4"):
        pair = pair_for(sentence)
        view = pair["view"]
        points = [(p["x"], p["y"]) for p in pair["meet"]] + [(r, 0) for f in pair["functions"] for r in f["roots"]] \
            + [tuple(f["vertex"]) for f in pair["functions"] if f.get("vertex")]
        assert points and all(view["xmin"] < x < view["xmax"] and view["ymin"] < y < view["ymax"] for x, y in points), (sentence, view)


@pytest.mark.parametrize("question, answer", [
    ("where do they meet?", "They meet at $(-0.618,\\ 0.382)$, $(1.618,\\ 2.618)$."),
    ("which one is higher?", "F is higher for x below $-0.618$ and for x above $1.618$; g is higher between x = $-0.618$ and x = $1.618$."),
    ("what is the area between them?", "The area between them, from the first meeting point to the last, is about $1.8634$ square units."),
    ("how are they related?", "The line cuts through the parabola at two points."),
    ("what's the area of a circle?", None),
    ("what time is it", None),
])
def test_questions_about_the_two_just_drawn(question, answer):
    assert graphs.pair_followup(question, pair_for("graph y = x^2 and y = x + 1")) == answer
