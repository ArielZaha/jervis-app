"""Features reported broken on 2026-10-09, each checked with the user's own words: the distance globe, graphs, planet
models, calendar events, stories in Google Docs and Netflix trailers. Nothing opens or plays for real here."""
import datetime as dt
import types

import pytest

import netflix
import sandbox

app = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def screen(monkeypatch):
    sent = []
    monkeypatch.setattr(app, "send_ui_update_once", lambda message: sent.append(message.get("type")))
    monkeypatch.setattr(app, "speak", lambda *a, **k: None)
    for name in ("pending_calendar_event", "pending_calendar_choice", "pending_dictation", "last_document"):
        monkeypatch.setattr(app, name, None)
    monkeypatch.setattr(app, "pending_earth_places", {"at": 0.0})
    return sent


# ---------------------------------------------------------------- typos
@pytest.mark.parametrize("said, fixed", [
    ("What is the distence between Tel Aviv and New York", "What is the distance between Tel Aviv and New York"),
    ("drew the greph", "draw the graph"), ("tell my about saturn", "tell me about saturn"),
    ("set a timer for 30 seconeds", "set a timer for 30 seconds"), ("wrtie a short story", "write a short story"),
    ("I drew a plant yesterday", "I drew a plant yesterday"),   # real words stay as they are
])
def test_misspellings_are_fixed_and_real_words_are_left_alone(said, fixed):
    assert app.fix_typos(said) == fixed


# ---------------------------------------------------------------- the globe
@pytest.fixture
def places(monkeypatch):
    known = {"tel aviv": (32.08, 34.78), "new york": (40.71, -74.0), "israel": (31.5, 34.8), "usa": (39.8, -98.6)}
    monkeypatch.setattr(app.earth, "geocode", lambda name: {"name": name.title(), "country": "", "lat": known[name.lower()][0],
                                                            "lon": known[name.lower()][1], "timezone": ""} if name.lower() in known else None)


def test_the_reported_distance_question_shows_the_globe(places, screen):
    reply = app.handle_direct_command("What is the distence between Tel Aviv and New York")
    assert "globe" in screen and "km" in reply.lower()


def test_show_it_on_the_globe_after_the_ai_answered_in_words(places, screen, monkeypatch):
    monkeypatch.setattr(app, "chat_history", [{"role": "user", "content": "What is the distence between Tel Aviv and New York"},
                                              {"role": "assistant", "content": "About 9,100 km."}])
    app.handle_direct_command("show me on earth model")
    assert "globe" in screen


def test_which_two_places_then_the_answer(places, screen, monkeypatch):
    monkeypatch.setattr(app, "chat_history", [])
    assert app.handle_direct_command("show me on earth model").startswith("Which two places?")
    app.handle_direct_command("isreal and usa")
    assert "globe" in screen


# ---------------------------------------------------------------- graphs and planets
def test_solve_and_draw_in_one_sentence(screen):
    reply = app.handle_direct_command("what is 2x + 6 = 0 drew the greph")
    assert "x equals negative 3" in reply and "I drew its graph too" in reply and "graph" in screen


def test_a_formula_then_plot_it(screen):
    assert "parabola" in app.handle_direct_command("y = x^2 - 4, plot it") and "graph" in screen


@pytest.mark.parametrize("said", ["tell my about saturn", "tell my about the sun and drew the model"])
def test_planets_show_their_model(said, screen):
    reply = app.handle_direct_command(said)
    assert "planet" in screen and reply[0].isupper()


# ---------------------------------------------------------------- calendar
@pytest.fixture
def calendar(monkeypatch):
    made = []
    monkeypatch.setenv("JARVIS_CALENDAR", "google")
    monkeypatch.setattr(app.calendar_api, "configured", lambda: True)
    monkeypatch.setattr(app.calendar_api, "create_event", lambda title, start, end, reminders=(): made.append(
        (title, start, end)) or {"start": start, "end": end})
    return made


@pytest.mark.parametrize("said, title, hour, minutes", [
    ("add a dentist appointment tomorrow at 5pm", "Dentist appointment", 17, 60),
    ("make a dentist appointment on friday at 3:30 pm for 2 hours", "Dentist appointment", 15, 120),
    ("create an event called Team sync next monday at 10am", "Team sync", 10, 60),
    ("schedule a meeting with Noa tomorrow from 2pm to 3:30pm", "Meeting with Noa", 14, 90),
])
def test_one_sentence_makes_the_whole_event(calendar, said, title, hour, minutes):
    assert app.handle_direct_command(said).startswith("Do you want a reminder?")
    assert app.handle_direct_command("no").startswith("Done.")
    made_title, start, end = calendar[0]
    assert (made_title, start.hour, (end - start).seconds // 60) == (title, hour, minutes)


def test_only_what_is_missing_is_asked(calendar):
    assert app.handle_direct_command("add an event to my calendar tomorrow at 5pm") == "Sure, what should I call the event?"
    assert app.handle_direct_command("Dinner with Dana").startswith("Do you want a reminder?")
    assert app.handle_direct_command("no thanks").startswith("Done.")
    assert calendar[0][0] == "Dinner with Dana"


def test_make_a_new_one_after_open_my_calendar_a_while_later(calendar, monkeypatch):
    monkeypatch.setattr(app, "pending_calendar_choice", {"at": app.time.time() - 100})
    assert app.handle_direct_command("make a new one") == "Sure, what should I call the event?"


def test_without_calendar_setup_the_event_is_saved_in_the_browser(monkeypatch):
    saved = []
    monkeypatch.setenv("JARVIS_CALENDAR", "google")
    monkeypatch.setattr(app.calendar_api, "configured", lambda: False)
    monkeypatch.setattr(app.calendar_api, "create_event_in_browser", lambda *a: saved.append(a) or True)
    assert "Google Calendar" in app.handle_direct_command("add a dentist appointment tomorrow at 5pm without a reminder")
    assert saved[0][0] == "Dentist appointment"


def test_the_calendar_link_fills_in_the_event():
    start = dt.datetime(2026, 10, 10, 14, 0, tzinfo=dt.timezone(dt.timedelta(hours=3)))
    link = app.calendar_api.event_link("Weekly Review", start, start + dt.timedelta(hours=1))
    assert "action=TEMPLATE" in link and "text=Weekly+Review" in link and "20261010T110000Z%2F20261010T120000Z" in link


# ---------------------------------------------------------------- Google Docs
@pytest.fixture
def docs(monkeypatch):
    log = {"asked": [], "doc": []}
    monkeypatch.setattr(app, "groq_chat", lambda **kw: log["asked"].append(kw["messages"][-1]["content"]) or types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="The Little Fox\n\nOnce upon a time..."))]))
    monkeypatch.setattr(app.documents, "insert", lambda key, title, body, context="": log["doc"].append(("new", key)) or
                        app.documents.GDOCS_PASTED)
    monkeypatch.setattr(app.documents, "update", lambda key, ref, title, body: log["doc"].append(("into open", key)) or key)
    monkeypatch.setattr(app.documents, "create_blank", lambda key, context="": log["doc"].append(("blank", key)) or "")
    return log


@pytest.mark.parametrize("said", ["wrtie a short story in hebrew on google drive file",
                                  "create a file on google drive and write a short story"])
def test_a_story_is_written_into_a_new_google_doc(docs, said):
    assert app.handle_direct_command(said) == "Done. I wrote The Little Fox in a new Google Doc."
    assert docs["doc"] == [("new", "gdocs")] and "short story" in docs["asked"][0]


def test_open_a_new_doc_then_ask_for_a_story(docs):
    assert "What would you like to write?" in app.handle_direct_command("open google drive and create a new file")
    assert app.handle_direct_command("write a short story") == "Done. I wrote The Little Fox in the document I opened."
    assert docs["doc"] == [("blank", "gdocs"), ("into open", "gdocs")]
    assert docs["asked"] == ["write a short story"]   # an instruction to write, not words to copy in


def test_write_in_the_file_you_opened(docs):
    app.handle_direct_command("create a new google doc")
    assert app.handle_direct_command("write in the file that you opened a short story").endswith("in the document I opened.")


# ---------------------------------------------------------------- Netflix trailers
_NEW_PAGE = ('"trailers":{"__typename":"SupplementalsConnection","edges":[{"__typename":"SupplementalEdge","node":'
             '{"__typename":"Supplemental","artwork":{"url":"x"},"runtimeSec":135,"title":"Franchise\\x20Trailer:\\x20Stranger'
             '\\x20Things","type":"TRAILER","videoId":82779520}},{"__typename":"SupplementalEdge","node":{"__typename":'
             '"Supplemental","runtimeSec":117,"title":"Trailer\\x20Part\\x202","type":"TRAILER","videoId":82182567}}]}')
_PROMO_ONLY = ('"promoVideo":{"__typename":"PromoVideo","id":81167706,"video":{"__typename":"Supplemental","videoId":81167706},'
               '"displayRuntimeMs":69000}},"trailers":{"__typename":"SupplementalsConnection","edges":[]}')


def test_netflix_trailers_are_read_from_the_current_page_layout():
    trailers = netflix.parse_trailers(_NEW_PAGE)
    assert [t["id"] for t in trailers] == ["82779520", "82182567"]
    assert trailers[0] == {"id": "82779520", "title": "Franchise Trailer: Stranger Things", "seconds": 135}


def test_a_show_with_only_a_promo_video_still_has_a_trailer():
    assert netflix.parse_trailers(_PROMO_ONLY) == [{"id": "81167706", "title": "Trailer", "seconds": 69}]


@pytest.fixture
def media(monkeypatch):
    opened = []
    monkeypatch.setattr(app.netflix, "find_title", lambda q: ("70143836", "Breaking Bad"))
    monkeypatch.setattr(app.netflix, "find_trailers", lambda title_id: [{"id": "81167706", "title": "Trailer", "seconds": 69}])
    monkeypatch.setattr(app, "open_in_site_tab", lambda url, host, context="": opened.append(url))
    monkeypatch.setattr(app, "play_youtube_video", lambda q, new_tab=False: opened.append("youtube") or
                        "Playing Breaking Bad Trailer on YouTube.")
    return opened


def test_a_youtube_trailer_offers_netflix_and_the_follow_up_plays_it_there(media):
    reply = app.handle_direct_command("show me the trailer of Breaking Bad")
    assert reply.startswith("Here's the trailer for Breaking Bad:") and "show it on Netflix" in reply
    assert app.handle_direct_command("can you show it on netflix") == "Playing the trailer for Breaking Bad on Netflix."
    assert media == ["youtube", "https://www.netflix.com/watch/81167706"]


def test_trailers_can_play_on_netflix_by_default(media, monkeypatch):
    monkeypatch.setenv("JARVIS_TRAILERS", "netflix")
    assert app.handle_direct_command("show me the trailer of Breaking Bad").endswith("on Netflix.")
    assert "youtube" in app.handle_direct_command("show me the trailer of Breaking Bad on youtube").lower()


# ================================================================ second round (2026-10-09 afternoon)
def test_the_reported_ramat_gan_question_shows_the_globe(screen, monkeypatch):
    monkeypatch.setattr(app.earth, "geocode", lambda name: {"name": name.title(), "country": "", "lat": 32.0, "lon": 34.8,
                                                            "timezone": ""} if "ramat" in name else
                        {"name": "London", "country": "", "lat": 51.5, "lon": -0.12, "timezone": ""})
    app.handle_direct_command("what is the distence bettwen Ramat gan to London?")
    assert "globe" in screen


@pytest.mark.parametrize("said, places", [
    ("what is the distence bettwen Ramat gan to London?", ("ramat gan", "london")),
    ("whats the distance in km between paris and rome", ("paris", "rome")),
    ("can you tell me how farr is it from haifa to eilat", ("haifa", "eilat")),
    ("the distanse betwen tokyo and seoul please", ("tokyo", "seoul")),
    ("an instance between a and b", None), ("how far did you get with the homework", None),
])
def test_distance_questions_however_they_are_typed(said, places):
    request = app.earth.parse_request(said)
    assert (request and (request["a"], request["b"])) == places or (places is None and request is None)


def test_the_ai_can_show_the_globe_too(screen, monkeypatch):
    monkeypatch.setattr(app.earth, "geocode", lambda name: {"name": name, "country": "", "lat": 1.0 + len(name), "lon": 2.0, "timezone": ""})
    assert app.is_distance_question("how far is it from ramat gan to london in km")
    app.TOOL_FUNCTIONS["show_distance"](place_a="Ramat Gan", place_b="London")
    assert "globe" in screen


# ---------------------------------------------------------------- reminders, Apple Calendar
@pytest.mark.parametrize("said, minutes", [("10 minutes before", [10]), ("1 hour and 1 day", [60, 1440]), ("no", []),
                                           ("no thanks", []), ("yes", [30]), ("at the time and 15 minutes before", [0, 15]),
                                           ("half an hour", [30]), ("a week before", [10080]), ("banana", None)])
def test_reminder_answers(said, minutes):
    assert app.parse_reminders(said) == minutes


@pytest.fixture
def apple(monkeypatch):
    made = []
    monkeypatch.setenv("JARVIS_CALENDAR", "apple")
    monkeypatch.setattr(app.osal, "IS_MAC", True)
    monkeypatch.setattr(app.apple_calendar, "create_event", lambda title, start, end, all_day=False, reminders=(),
                        calendar_name="": made.append((title, start.hour, list(reminders))) or "Home")
    return made


def test_the_event_asks_about_reminders_and_goes_to_apple_calendar(apple):
    assert app.handle_direct_command("add a dentist appointment tomorrow at 5pm").startswith("Do you want a reminder?")
    reply = app.handle_direct_command("30 minutes and 1 day before")
    assert reply.endswith("with a reminder 30 minutes before and 1 day before.") and "your Calendar" in reply
    assert apple == [("Dentist appointment", 17, [30, 1440])]


@pytest.mark.parametrize("said, made", [
    ("make a meeting with Noa on sunday at 10am for 2 hours and remind me 15 minutes before", ("Meeting with Noa", 10, [15])),
    ("schedule gym tomorrow at 7am with no reminder", ("Gym", 7, [])),
    ("add football practice to my calendar tomorrow at 6pm without a reminder", ("Football practice", 18, [])),
])
def test_reminders_said_with_the_event_need_no_question(apple, said, made):
    assert app.handle_direct_command(said).startswith("Done.")
    assert apple == [made]


def test_the_calendar_setting_switches_to_google(apple, monkeypatch):
    sent = []
    monkeypatch.setenv("JARVIS_CALENDAR", "google")
    monkeypatch.setattr(app.calendar_api, "configured", lambda: True)
    monkeypatch.setattr(app.calendar_api, "create_event", lambda title, start, end, reminders=(): sent.append(list(reminders))
                        or {"start": start, "end": end})
    app.handle_direct_command("add a dentist appointment tomorrow at 5pm with a reminder 1 hour before")
    assert sent == [[60]] and apple == []


def test_apple_calendar_scripts_take_numbers_not_dates():
    import apple_calendar
    start = dt.datetime(2026, 10, 10, 17, 5)
    assert apple_calendar._parts(start) == ["2026", "10", "10", "17", "5"]


# ---------------------------------------------------------------- sleeping by mistake, hearing while muted
class _Clip:
    def get_wav_data(self, **kw):
        return b""


@pytest.fixture
def engines(monkeypatch):
    monkeypatch.setattr(app, "GROQ_KEY", "key")
    monkeypatch.setattr(app, "groq_down_until", 0)
    monkeypatch.setattr(app.stt_local, "ready", lambda: False)
    def use(whisper, google):
        monkeypatch.setattr(app, "transcribe_groq", lambda wav: whisper)
        monkeypatch.setattr(app, "transcribe_google", lambda audio: google)
    return use


def test_a_goodbye_whisper_made_up_from_silence_is_ignored(engines):
    engines("Goodbye.", "")
    assert app.transcribe(_Clip()) == ""


def test_a_real_goodbye_still_counts(engines):
    engines("Goodbye.", "goodbye")
    assert app.transcribe(_Clip()) == "Goodbye."


def test_ordinary_requests_need_no_second_opinion(engines):
    engines("Open Spotify.", "")
    assert app.transcribe(_Clip()) == "Open Spotify."


def test_jarvis_does_not_answer_his_own_voice(monkeypatch):
    monkeypatch.setattr(app, "last_spoken", {"text": "I'm ready to help with whatever you need.", "at": app.time.time()})
    assert app.is_own_echo("you need.") and not app.is_own_echo("open spotify")


# ---------------------------------------------------------------- pictures
@pytest.mark.parametrize("said, what", [
    ("genearte an image of a dog in the space.", "a dog in the space"),
    ("make a new image: a red sports car on a mountain road at sunset", "a red sports car on a mountain road at sunset"),
    ("draw me a dragon", "a dragon"), ("Generate an image of a dog.", "a dog"),
])
def test_picture_requests_go_straight_to_the_generator(monkeypatch, said, what):
    asked = []
    monkeypatch.setattr(app.images, "generate", lambda prompt, size="auto": asked.append(prompt) or {"path": "x.png"})
    monkeypatch.setattr(app.images, "display_data_url", lambda path: "data:")
    monkeypatch.setattr(app, "broadcast", lambda *a, **k: None)
    assert app.handle_direct_command(said).startswith("Here's your picture")
    assert asked == [what]


def test_drawing_a_graph_is_not_a_picture(monkeypatch, screen):
    monkeypatch.setattr(app.images, "generate", lambda *a, **k: pytest.fail("made a picture"))
    app.handle_direct_command("draw the graph of x squared")
    assert "graph" in screen


def test_the_slow_local_model_is_only_for_no_internet(monkeypatch):
    import images
    tried = []
    monkeypatch.setattr(images, "enhance_prompt", lambda p: p)
    monkeypatch.setattr(images, "generation_configured", lambda: False)
    monkeypatch.setattr(images, "cloudflare_configured", lambda: False)
    monkeypatch.setattr(images, "local_generation_configured", lambda: True)
    monkeypatch.setattr(images, "_generate_local", lambda p: tried.append("local") or {"path": "l.png"})
    def busy(p, size):
        tried.append("pollinations")
        raise images.ImageError("busy")
    monkeypatch.setattr(images, "_generate_pollinations", busy)
    with pytest.raises(images.ImageError):
        images.generate("a dog")
    assert tried == ["pollinations"]
    def offline(p, size):
        tried.append("pollinations")
        raise images.PollinationsOffline("no internet")
    monkeypatch.setattr(images, "_generate_pollinations", offline)
    assert images.generate("a dog")["path"] == "l.png"


def test_a_rejected_openai_key_is_not_tried_again(monkeypatch):
    import images
    calls = []
    monkeypatch.setattr(images, "_openai_rejected", [False])
    monkeypatch.setattr(images, "enhance_prompt", lambda p: p)
    monkeypatch.setattr(images, "generation_configured", lambda: True)
    monkeypatch.setattr(images, "cloudflare_configured", lambda: False)
    def rejected(p, size):
        calls.append("openai")
        raise images.ImageError("The image service rejected the API key.")
    monkeypatch.setattr(images, "_generate_openai", rejected)
    monkeypatch.setattr(images, "_generate_pollinations", lambda p, size: {"path": "p.png"})
    images.generate("a dog")
    images.generate("a cat")
    assert calls == ["openai"]
