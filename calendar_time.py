"""Turning what someone says into a date, a time of day, or a length: "next Monday", "3pm", "half an hour". Used to
build a calendar event from a few short spoken answers (see handle_calendar_command in app.py).
"""
import calendar
import datetime as dt
import re

_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}  # monday -> 0 ... sunday -> 6
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_ORDINAL = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b")
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
                 "fifty": 50, "a": 1, "an": 1, "half": 0.5}


def _clean(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9.:/\-' ]", " ", (text or "").lower().replace("’", "'")).split())


def parse_date(text: str, today: dt.date = None):
    """A date from a spoken/typed answer, or None if none was understood. `today` is injectable for testing."""
    today = today or dt.date.today()
    n = _ordinal_strip(_clean(text))
    if re.search(r"\btoday\b|\btonight\b", n):
        return today
    if re.search(r"\bday after tomorrow\b", n):
        return today + dt.timedelta(days=2)
    if re.search(r"\btomorrow\b", n):
        return today + dt.timedelta(days=1)
    m = re.search(r"\b(next|this|coming)?\s*(" + "|".join(_WEEKDAYS) + r")\b", n)
    if m:
        target = _WEEKDAYS[m.group(2)]
        delta = (target - today.weekday()) % 7
        if delta == 0 and m.group(1) == "next":   # "next monday" said on a monday: a week from now, not today
            delta = 7
        return today + dt.timedelta(days=delta)
    # "october 3", "3 october", "3rd of october", "10/3", "10-3", "2026-10-03", each optionally with a year
    m = re.search(r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b", n)
    if not m:
        m2 = re.search(r"\b(\d{1,2})\s+(?:of\s+)?(" + "|".join(_MONTHS) + r")\.?(?:\s*,?\s*(\d{4}))?\b", n)
        if m2:
            m = type("M", (), {"group": lambda self, i, m2=m2: (m2.group(2), m2.group(1), m2.group(3))[i - 1]})()
    if m:
        month, day, year = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3)) if m.group(3) else None
        return _next_or_this_year(month, day, year, today)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", n)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/](\d{1,2})(?:[/](\d{2,4}))?\b", n)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        if year and year < 100:
            year += 2000
        return _next_or_this_year(month, day, year, today)
    return None


def _ordinal_strip(n: str) -> str:
    return _ORDINAL.sub(r"\1", n)


def _next_or_this_year(month: int, day: int, year, today: dt.date):
    try:
        if year:
            return dt.date(year, month, day)
        candidate = dt.date(today.year, month, day)
        return candidate if candidate >= today else dt.date(today.year + 1, month, day)
    except ValueError:
        return None


def parse_time(text: str):
    """(hour, minute) in 24-hour time from a spoken/typed answer, or None if nothing usable was said."""
    n = _clean(text)
    if re.search(r"\bnoon\b", n):
        return 12, 0
    if re.search(r"\bmidnight\b", n):
        return 0, 0
    quarter_to = re.search(r"\bquarter\s+to\s+(\d{1,2})(a\.?m\.?|p\.?m\.?)?\b", n)
    if quarter_to:
        n = n[:quarter_to.start()] + f"{int(quarter_to.group(1)) - 1}:45{quarter_to.group(2) or ''}" + n[quarter_to.end():]
    else:
        n = re.sub(r"\bhalf\s+past\s+(\d{1,2})(a\.?m\.?|p\.?m\.?)?\b", r"\1:30\2", n)
        n = re.sub(r"\bquarter\s+past\s+(\d{1,2})(a\.?m\.?|p\.?m\.?)?\b", r"\1:15\2", n)
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b", n)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
    if hour > 23 or minute > 59:
        return None
    ampm = (m.group(3) or "").replace(".", "")
    has_colon = m.group(2) is not None
    has_oclock = bool(re.search(r"\bo'?\s*clock\b", n))
    if not ampm:
        if re.search(r"\bmorning\b", n):
            ampm = "am"
        elif re.search(r"\b(?:afternoon|evening|night|tonight)\b", n):
            ampm = "pm"
    # A bare hour with no am/pm word, no colon and no "o'clock" ("at 7") is too ambiguous to guess: ask again instead.
    if not ampm and not has_colon and not has_oclock:
        return None
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


_TENS_WORDS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
_ONES_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


def _combine_tens(n: str) -> str:
    """"Forty five" -> "45": without this, a compound number word would be read as two separate ones (badly wrong,
    not just imprecise: "forty five minutes" would otherwise come out as 5 minutes, not 45)."""
    return re.sub(r"\b(twenty|thirty|forty|fifty)[\s-]+(one|two|three|four|five|six|seven|eight|nine)\b",
                  lambda m: str(_TENS_WORDS[m.group(1)] + _ONES_WORDS[m.group(2)]), n)


def parse_duration(text: str):
    """Minutes for a spoken length ("half an hour", "90 minutes", "2 hours"), or None if nothing was said.
    "all day" returns the string "all_day" instead of a number."""
    n = _combine_tens(_clean(text))
    if re.search(r"\ball\s*day\b", n):
        return "all_day"
    if re.fullmatch(r"(?:default|skip|nothing|never ?mind|the usual|normal|standard)", n):
        return 60
    if re.search(r"\bhalf\s+(?:an?\s+)?hour\b", n):   # checked first: "half an hour" would otherwise match "an hour" below
        return 30
    if re.fullmatch(r"an?\s+hour", n):
        return 60
    total, found = 0.0, False
    for qty, unit in re.findall(r"\b(\d+(?:\.\d+)?|" + "|".join(w for w in _NUMBER_WORDS if w != "half") + r")\s*(hours?|hrs?|minutes?|mins?)\b", n):
        value = float(qty) if re.fullmatch(r"\d+(?:\.\d+)?", qty) else _NUMBER_WORDS[qty]
        total += value * (60 if unit.startswith(("h", "hr")) else 1)
        found = True
    if found and re.search(r"\band\s+(?:a\s+)?half\b", n):   # "an hour and a half" (the trailing "half" isn't its own unit)
        total += 30
    return round(total) if found and total > 0 else None


def combine(date: dt.date, hour: int, minute: int) -> dt.datetime:
    return dt.datetime.combine(date, dt.time(hour, minute)).astimezone()


def format_when(start: dt.datetime, end: dt.datetime = None, all_day: bool = False) -> str:
    """"Tuesday, October 6 at 3:00 PM" (or with an end time / "all day"), for speech and for the screen."""
    day = start.strftime("%A, %B %-d" if hasattr(start, "strftime") else "")
    if all_day:
        return f"{day} (all day)"
    time_str = start.strftime("%-I:%M %p").lstrip("0")
    if end and end.date() == start.date() and (end.hour, end.minute) != (start.hour, start.minute):
        time_str += f" to {end.strftime('%-I:%M %p').lstrip('0')}"
    return f"{day} at {time_str}"
