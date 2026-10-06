"""A real text message when Jarvis wants to reach you — no page, no app, no one-time setup on the phone at all,
unlike push.py's web notifications. Sent through Twilio's SMS API (twilio.com), a paid third-party service the
user sets up themselves (Settings, Optional services): nothing here creates an account or costs anything on its
own, and nothing is sent unless all four Twilio settings are filled in.
"""
import os

import requests

TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
MAX_LENGTH = 1600   # Twilio's own limit on a single message body


def _credentials():
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    to_number = os.getenv("TWILIO_TO_NUMBER", "").strip()
    if sid and token and from_number and to_number:
        return sid, token, from_number, to_number
    return None


def configured() -> bool:
    return _credentials() is not None


def send(body: str) -> str:
    """Sends `body` as a text message. Returns "" on success, or why it failed — this never raises, so a failed
    text (a typo'd number, an expired trial, Twilio being down) never takes down whatever was trying to reach the
    phone."""
    credentials = _credentials()
    if credentials is None:
        return "Text messages aren't set up (Settings, Optional services, Twilio)."
    sid, token, from_number, to_number = credentials
    try:
        response = requests.post(
            TWILIO_API.format(sid=sid), auth=(sid, token),
            data={"From": from_number, "To": to_number, "Body": body[:MAX_LENGTH]}, timeout=10)
    except requests.RequestException as e:
        return f"Couldn't send the text: {e}"
    if response.status_code >= 300:
        try:
            detail = response.json().get("message") or response.text[:200]
        except ValueError:
            detail = response.text[:200]
        return f"Couldn't send the text: {detail}"
    return ""
