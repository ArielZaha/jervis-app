"""The diagnostic log must never contain what the user said or what Jervis answered."""
import logbook


def test_spoken_and_typed_text_is_redacted():
    assert logbook.redact("Recognized: play my secret playlist") == "Recognized: [not logged]"
    assert logbook.redact("Speaking: Your bank PIN is 1234") == "Speaking: [not logged]"
    assert logbook.redact("  Typed: hello there") == "  Typed: [not logged]"


def test_diagnostics_are_kept():
    line = "Local AI ready: llama3.2 at http://127.0.0.1:11435"
    assert logbook.redact(line) == line
    assert logbook.redact("Window connected (1 open).") == "Window connected (1 open)."


def test_a_console_that_cant_show_hebrew_still_gets_the_line():
    import io
    import logbook
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    tee = logbook._Tee(console)
    tee.write("data folder: C:\\Users\\\u05d0\u05e8\u05d9\u05d0\u05dc\n")
    tee.flush()
    shown = raw.getvalue().decode("cp1252")
    assert "data folder: C:\\Users\\" in shown and "\\u05d0" in shown
