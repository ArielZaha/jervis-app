"""Spoken dates and times read the same on every system (Windows has no strftime %-d / %-I)."""
import datetime as dt

import calendar_time


def test_the_clock_reads_like_speech_at_the_edges_of_the_day():
    assert calendar_time.clock(dt.datetime(2026, 10, 6, 0, 5)) == "12:05 AM"
    assert calendar_time.clock(dt.datetime(2026, 10, 6, 9, 0)) == "9:00 AM"
    assert calendar_time.clock(dt.datetime(2026, 10, 6, 12, 0)) == "12:00 PM"
    assert calendar_time.clock(dt.datetime(2026, 10, 6, 23, 59)) == "11:59 PM"


def test_a_single_digit_day_has_no_leading_zero():
    start = dt.datetime(2026, 10, 6, 15, 0)
    assert calendar_time.format_when(start) == "Tuesday, October 6 at 3:00 PM"
    assert calendar_time.format_when(start, dt.datetime(2026, 10, 6, 16, 30)) == "Tuesday, October 6 at 3:00 PM to 4:30 PM"
    assert calendar_time.format_when(start, all_day=True) == "Tuesday, October 6 (all day)"
