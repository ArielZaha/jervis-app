"""Writing where the cursor is: when a request means "type it here", what gets typed, and how it's checked.
No real typing happens here (see test_write_here_app for the app side, with a fake target)."""
import pytest

import write_here as wh


def target(editable=True, password=False, app="notepad", title="Untitled - Notepad"):
    return wh.Target(hwnd=1, app=app, title=title, control="DocumentControl", editable=editable, password=password)


@pytest.mark.parametrize("said", ["write it here", "type a thank-you note right here",
                                  "write a story about a secret island where my cursor is",
                                  "write me a short reply in this email", "draft a paragraph into this document",
                                  "write the function at my cursor"])
def test_explicit_requests_to_write_here(said):
    assert wh.wants_here(said, target(editable=False))


def test_a_plain_write_request_types_only_when_a_text_field_has_the_focus():
    assert wh.wants_here("write me a story about someone who discovers a secret island", target(editable=True))
    assert not wh.wants_here("write me a story about someone who discovers a secret island", target(editable=False))


def test_with_a_text_app_behind_jervis_a_spoken_request_is_for_it_but_a_typed_one_is_chat():
    maybe = target(editable=None)
    assert wh.wants_here("write me a poem about the sea", maybe, spoken=True)
    assert not wh.wants_here("write me a poem about the sea", maybe, spoken=False)


def test_never_into_a_password_field():
    assert not wh.wants_here("type my message here", target(password=True))


def test_a_named_app_is_the_document_writer_not_the_cursor():
    assert not wh.wants_here("write a story in Word", target(editable=True))
    assert not wh.wants_here("write a letter in google docs", target(editable=True))


@pytest.mark.parametrize("said", ["what did you write?", "can you hear me", "open notepad"])
def test_other_sentences_are_not_writing(said):
    assert not wh.wants_here(said, target(editable=True))


def test_no_target_no_typing():
    assert not wh.wants_here("write it here", None)


def test_the_ai_lead_in_and_fences_never_reach_the_document():
    assert wh.clean("Sure! Here's your story:\n\nOnce upon a time.") == "Once upon a time."
    assert wh.clean("```python\nprint('hi')\n```") == "print('hi')"
    assert wh.clean("Plain text.\r\nSecond line.") == "Plain text.\nSecond line."


def test_code_editors_get_code_only_instructions():
    prompt = wh.writing_prompt(target(app="code", title="main.py - Visual Studio Code"))
    assert "code editor" in prompt and "```" in prompt
    assert "code editor" not in wh.writing_prompt(target())


def test_landed_requires_the_text_to_really_be_there():
    body = "Once upon a time, a girl found a secret island far out at sea. " * 3
    assert wh.landed("Dear Sam,\n", "Dear Sam,\n" + body, body) is True
    assert wh.landed("Dear Sam,\n", "Dear Sam,\n", body) is False               # nothing arrived
    assert wh.landed("Dear Sam,\n", "Dear Sam,\nOnce upon a", body) is False    # only the start arrived
    assert wh.landed("x", None, body) is None                                   # can't be read: say so, don't claim


def test_insert_refuses_when_the_cursor_left_the_text_field(monkeypatch):
    import types
    import sys
    fake_winctl = types.SimpleNamespace(focus=lambda hwnd: True)
    monkeypatch.setitem(sys.modules, "winctl", fake_winctl)
    monkeypatch.setattr(wh, "_focused_control", lambda: None)
    monkeypatch.setattr(wh.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="isn't in a text field"):
        wh.insert(target(), "hello")


def test_insert_types_short_text_and_reports_it_checked(monkeypatch):
    import sys
    import types
    typed = []
    texts = iter(["Hi ", "Hi there friend, how are you doing today?"])
    control = types.SimpleNamespace(Element=types.SimpleNamespace(CurrentIsPassword=False))
    monkeypatch.setitem(sys.modules, "winctl", types.SimpleNamespace(
        focus=lambda hwnd: True, type_text=lambda t, strict=False: typed.append(t),
        press=lambda *k, strict=False: typed.append(k)))
    monkeypatch.setattr(wh, "_focused_control", lambda: control)
    monkeypatch.setattr(wh, "_editable", lambda c: True)
    monkeypatch.setattr(wh, "_read", lambda c: next(texts))
    monkeypatch.setattr(wh.time, "sleep", lambda s: None)
    result = wh.insert(target(), "there friend, how are you doing today?")
    assert typed == ["there friend, how are you doing today?"]
    assert "checked" in result


def test_insert_pastes_long_text_and_puts_the_clipboard_back(monkeypatch):
    import sys
    import types
    import osal
    body = "A long paragraph about islands. " * 20
    clip = {"now": "the user's own clipboard"}
    keys = []
    control = types.SimpleNamespace(Element=types.SimpleNamespace(CurrentIsPassword=False))
    monkeypatch.setitem(sys.modules, "winctl", types.SimpleNamespace(
        focus=lambda hwnd: True, type_text=lambda t, strict=False: keys.append("typed"),
        press=lambda *k, strict=False: keys.append(k)))
    monkeypatch.setattr(osal, "get_clipboard", lambda: clip["now"])
    monkeypatch.setattr(osal, "set_clipboard", lambda t: clip.update(now=t))
    reads = iter(["", body])
    monkeypatch.setattr(wh, "_focused_control", lambda: control)
    monkeypatch.setattr(wh, "_editable", lambda c: True)
    monkeypatch.setattr(wh, "_read", lambda c: next(reads))
    monkeypatch.setattr(wh.time, "sleep", lambda s: None)
    wh.insert(target(), body)
    assert ("ctrl", "v") in keys and "typed" not in keys
    assert clip["now"] == "the user's own clipboard"


def test_insert_says_so_when_the_text_did_not_arrive(monkeypatch):
    import sys
    import types
    control = types.SimpleNamespace(Element=types.SimpleNamespace(CurrentIsPassword=False))
    monkeypatch.setitem(sys.modules, "winctl", types.SimpleNamespace(
        focus=lambda hwnd: True, type_text=lambda t, strict=False: None, press=lambda *k, strict=False: None))
    monkeypatch.setattr(wh, "_focused_control", lambda: control)
    monkeypatch.setattr(wh, "_editable", lambda c: True)
    monkeypatch.setattr(wh, "_read", lambda c: "unchanged")
    monkeypatch.setattr(wh.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="wasn't there"):
        wh.insert(target(), "some words that never arrived")


def test_put_something_somewhere_is_not_writing_text():
    assert not wh.wants_here("put a palm tree next to the house", target(editable=None))
    assert not wh.wants_here("insert a cube", target(editable=True))
    assert wh.wants_here("paste a short greeting here", target(editable=None))
