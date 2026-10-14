"""Real Google Calendar access: the next few events, and creating a new one, through Google's own Calendar API.

Unlike Classroom, Calendar has a proper, supported API for outside apps, so this reads and writes for real (nothing is
guessed from the page). It needs a one-time setup: a free OAuth client from Google Cloud Console, its ID and secret in
.env, and, the first time it's used, signing in once in a browser tab. After that a token is cached locally
(CALENDAR_TOKEN_FILE) and refreshed automatically; nothing needs to be entered again on future runs.
"""
import datetime as dt
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import paths

SCOPES = ["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_FILE = os.path.join(paths.DATA_DIR, ".calendar_token.json")
DEFAULT_DURATION_MIN = 60


class CalendarUnavailable(Exception):
    """No OAuth client configured, or the sign-in flow failed/was refused."""


def configured() -> bool:
    return bool((os.getenv("GOOGLE_CALENDAR_CLIENT_ID") or "").strip() and (os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET") or "").strip())


def _client_config() -> dict:
    return {"installed": {
        "client_id": os.environ["GOOGLE_CALENDAR_CLIENT_ID"].strip(),
        "client_secret": os.environ["GOOGLE_CALENDAR_CLIENT_SECRET"].strip(),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}


def _load_token() -> Credentials:
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        return Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except (ValueError, OSError):
        return None


def _save_token(creds: Credentials) -> None:
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def _authorize() -> Credentials:
    """A cached, valid token if there is one; otherwise runs the one-time sign-in (opens a browser tab)."""
    if not configured():
        raise CalendarUnavailable(
            "Google Calendar isn't set up yet. Add GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET to "
            "the .env file (the README explains how to get them from Google Cloud Console), then try again."
        )
    creds = _load_token()
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except Exception:
            pass  # the refresh token was revoked or expired: fall through to a fresh sign-in
    try:
        flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True,
                                       authorization_prompt_message="Sign in to Google Calendar in the browser tab that just opened.",
                                       success_message="Signed in. You can close this tab and go back to Jarvis.")
    except Exception as e:
        raise CalendarUnavailable(f"I couldn't sign in to Google Calendar: {e}")
    _save_token(creds)
    return creds


def get_service():
    return build("calendar", "v3", credentials=_authorize(), cacheDiscovery=False)


def _to_local(value: dict) -> dt.datetime:
    """A Calendar API event's start/end (either a dateTime or, for an all-day event, just a date) as a local datetime."""
    if "dateTime" in value:
        return dt.datetime.fromisoformat(value["dateTime"])
    return dt.datetime.fromisoformat(value["date"]).replace(tzinfo=dt.datetime.now().astimezone().tzinfo)


def list_upcoming(max_results: int = 5) -> list:
    """The next events on the primary calendar, soonest first: [{"title", "start", "end", "all_day", "location", "link"}]."""
    service = get_service()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        response = service.events().list(calendarId="primary", timeMin=now, maxResults=max_results,
                                          singleEvents=True, orderBy="startTime").execute()
    except HttpError as e:
        raise CalendarUnavailable(f"Google Calendar returned an error: {e}")
    events = []
    for item in response.get("items", []):
        start_raw = item.get("start", {})
        events.append({
            "title": item.get("summary") or "(untitled event)",
            "start": _to_local(start_raw),
            "end": _to_local(item.get("end", start_raw)),
            "all_day": "date" in start_raw and "dateTime" not in start_raw,
            "location": item.get("location", ""),
            "link": item.get("htmlLink", ""),
        })
    return events


def create_event(title: str, start: dt.datetime, end: dt.datetime, location: str = "", description: str = "",
                 reminders=()) -> dict:
    """Create an event on the primary calendar. Returns {"title", "start", "end", "link"}."""
    service = get_service()
    # The offset in each time says the zone; a name like "IDT" isn't one Google accepts, so none is sent.
    body = {"summary": title, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
    if reminders:
        body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(m)} for m in reminders]}
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    try:
        created = service.events().insert(calendarId="primary", body=body).execute()
    except HttpError as e:
        raise CalendarUnavailable(f"Google Calendar wouldn't create the event: {e}")
    return {"title": title, "start": start, "end": end, "link": created.get("htmlLink", "")}


# ---------- without the API: Google Calendar's own "new event" page, filled in from its link, then saved ----------
_SAVE_SCRIPT = '''tell application "Google Chrome" to activate
delay 0.3
tell application "System Events" to keystroke "s" using command down'''


def event_link(title: str, start: dt.datetime, end: dt.datetime, all_day: bool = False) -> str:
    """Google Calendar's documented link that opens a new event with these details filled in."""
    from urllib.parse import urlencode
    if all_day:
        dates = f"{start:%Y%m%d}/{end:%Y%m%d}"
    else:
        utc = dt.timezone.utc
        dates = f"{start.astimezone(utc):%Y%m%dT%H%M%SZ}/{end.astimezone(utc):%Y%m%dT%H%M%SZ}"
    return "https://calendar.google.com/calendar/render?" + urlencode({"action": "TEMPLATE", "text": title, "dates": dates})


def create_event_in_browser(title: str, start: dt.datetime, end: dt.datetime, all_day: bool = False) -> bool:
    """Open the filled-in event in the user's Google account and save it with Calendar's own shortcut (Command+S).
    True once the page has left the event editor (saved); False if it couldn't be confirmed — the event is still
    open and filled in, waiting for Save."""
    import subprocess
    import time
    import google_accounts
    google_accounts.open_page(event_link(title, start, end, all_day), f"calendar event {title}")
    if os.name == "nt":
        return False   # no way to see the tab's address on Windows: leave the Save click to the user
    from youtube_browser import _mac_tabs

    def front_url() -> str:
        try:
            front = [t for t in _mac_tabs() if t.window == 1 and t.active]
        except Exception:
            return ""
        return front[0].url if front else ""

    deadline = time.time() + 20
    while time.time() < deadline and "eventedit" not in front_url():
        time.sleep(0.5)
    if "eventedit" not in front_url():
        return False
    time.sleep(2.5)   # the editor's fields fill in after the address changes
    try:
        subprocess.run(["osascript", "-e", _SAVE_SCRIPT], capture_output=True, timeout=15, check=True)
    except (subprocess.SubprocessError, OSError):
        return False
    deadline = time.time() + 8
    while time.time() < deadline:
        url = front_url()
        if url and "eventedit" not in url and "calendar.google.com" in url:
            return True
        time.sleep(0.5)
    return False
