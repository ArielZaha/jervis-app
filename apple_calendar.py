"""The Mac's own Calendar app (and every account in it: iCloud, Google, Exchange): adding an event with its reminders,
and reading what's coming up. Through AppleScript, so nothing to sign in to; the first time, macOS asks once whether
Jarvis may control Calendar.

Dates are passed as numbers and assembled inside the script, so the user's date format and language never matter.
"""
import datetime as dt
import subprocess

import osal


class AppleCalendarUnavailable(Exception):
    """Not a Mac, or Calendar wouldn't do it (usually: Jarvis isn't allowed to control Calendar)."""


_PERMISSION = ("Jarvis isn't allowed to use Calendar yet. Open System Settings, Privacy & Security, Automation (and "
               "Calendars), allow Jarvis to control Calendar, then ask me again.")

_MAKE_DATE = '''
on makeDate(y, mo, d, h, mi)
    set t to current date
    set day of t to 1
    set year of t to y
    set month of t to mo
    set day of t to d
    set time of t to (h * 3600 + mi * 60)
    return t
end makeDate
'''

_CREATE = _MAKE_DATE + '''
on run argv
    set theTitle to item 1 of argv
    set startDate to makeDate((item 2 of argv) as integer, (item 3 of argv) as integer, (item 4 of argv) as integer, (item 5 of argv) as integer, (item 6 of argv) as integer)
    set endDate to makeDate((item 7 of argv) as integer, (item 8 of argv) as integer, (item 9 of argv) as integer, (item 10 of argv) as integer, (item 11 of argv) as integer)
    set isAllDay to (item 12 of argv) is "1"
    set wantedCalendar to item 13 of argv
    set alarmList to {}
    if (count of argv) > 13 then set alarmList to items 14 thru -1 of argv
    tell application "Calendar"
        set theCal to missing value
        if wantedCalendar is not "" then
            try
                set theCal to first calendar whose name is wantedCalendar
            end try
        end if
        if theCal is missing value then
            repeat with c in calendars
                if writable of c then
                    set theCal to c
                    exit repeat
                end if
            end repeat
        end if
        tell theCal
            set newEvent to make new event with properties {summary:theTitle, start date:startDate, end date:endDate, allday event:isAllDay}
        end tell
        repeat with minutesBefore in alarmList
            tell newEvent to make new display alarm at end with properties {trigger interval:-((minutesBefore as integer))}
        end repeat
        return name of theCal
    end tell
end run
'''

_UPCOMING = '''
on run argv
    set fromDate to current date
    set toDate to fromDate + ((item 1 of argv) as integer) * days
    set out to ""
    tell application "Calendar"
        repeat with c in calendars
            try
                repeat with e in (every event of c whose start date is greater than or equal to fromDate and start date is less than toDate)
                    set s to start date of e
                    set en to end date of e
                    set out to out & (summary of e) & tab & my stamp(s) & tab & my stamp(en) & tab & (allday event of e) & linefeed
                end repeat
            end try
        end repeat
    end tell
    return out
end run
on stamp(d)
    return ((year of d) as text) & "-" & ((month of d) as integer) & "-" & (day of d) & "-" & (hours of d) & "-" & (minutes of d)
end stamp
'''


def _run(script: str, *args: str, timeout: float = 45) -> str:
    if not osal.IS_MAC:
        raise AppleCalendarUnavailable("Apple Calendar is only on a Mac. Choose Google Calendar in Settings instead.")
    try:
        result = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AppleCalendarUnavailable("Calendar took too long to answer. Open the Calendar app once, then try again.")
    if result.returncode != 0:
        error = result.stderr.strip()
        if "-1743" in error or "not allowed" in error.lower() or "-10004" in error:
            raise AppleCalendarUnavailable(_PERMISSION)
        raise AppleCalendarUnavailable(f"Calendar couldn't do that: {error or 'no reason given'}")
    return result.stdout.strip()


def _parts(when: dt.datetime) -> list:
    when = when.astimezone() if when.tzinfo else when   # the Mac's own clock time, which is what Calendar shows
    return [str(when.year), str(when.month), str(when.day), str(when.hour), str(when.minute)]


def create_event(title: str, start: dt.datetime, end: dt.datetime, all_day: bool = False, reminders=(),
                 calendar_name: str = "") -> str:
    """Add the event (with a reminder alert for each number of minutes before it). Returns the calendar's name."""
    args = [title, *_parts(start), *_parts(end), "1" if all_day else "0", calendar_name or "",
            *[str(int(m)) for m in reminders]]
    return _run(_CREATE, *args)


def list_upcoming(count: int = 5, days: int = 30) -> list:
    """The next events across every calendar in the app: [{"title", "start", "end", "all_day"}], soonest first."""
    events = []
    for line in _run(_UPCOMING, str(days), timeout=60).splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            start = dt.datetime(*map(int, parts[1].split("-")))
            end = dt.datetime(*map(int, parts[2].split("-")))
        except ValueError:
            continue
        events.append({"title": parts[0], "start": start, "end": end, "all_day": parts[3] == "true", "location": ""})
    return sorted(events, key=lambda e: e["start"])[:count]
