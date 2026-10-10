import datetime
import importlib.util

import pytest

from tests.agentic.conftest import REPO

CAL_PATH = REPO / "builder" / "agentic" / "skill" / "build-collections-agent" / "templates" / "calendar.py"
spec = importlib.util.spec_from_file_location("skill_calendar", CAL_PATH)
cal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cal)

D = datetime.date.fromisoformat


def test_no_double_braces_and_stdlib_only():
    text = CAL_PATH.read_text()
    assert "{{" not in text and "}}" not in text
    imports = {line.split()[1] for line in text.splitlines() if line.startswith("import ")}
    assert imports <= {"datetime", "json", "re"}


def test_weekend_and_next_business_day():
    assert not cal.is_business_day(D("2031-03-08"), set())  # Saturday
    assert cal.next_business_day(D("2031-03-08"), set()) == D("2031-03-10")
    assert cal.next_business_day(D("2031-03-07"), set(), include_today=True) == D("2031-03-07")


def test_add_business_days_skips_holidays_and_chains():
    assert cal.add_business_days(D("2031-03-03"), 5, set()) == D("2031-03-10")
    assert cal.add_business_days(D("2031-03-03"), 5, {D("2031-03-05")}) == D("2031-03-11")
    chain = cal.parse_holidays(["2031-12-25", "2031-12-26", "not a date"])
    assert chain == {D("2031-12-25"), D("2031-12-26")}
    assert cal.add_business_days(D("2031-12-24"), 1, chain) == D("2031-12-29")
    assert cal.add_business_days(D("2031-03-03"), 0, set()) == D("2031-03-03")


def test_end_of_month_and_nth_across_a_holiday():
    assert cal.add_business_days(D("2031-01-31"), 1, set()) == D("2031-02-03")
    assert cal.nth_business_day_after(D("2031-03-07"), 1, {D("2031-03-10")}) == D("2031-03-11")
    assert cal.nth_business_day_after(D("2031-03-07"), 3, {D("2031-03-10")}) == D("2031-03-13")


def test_last_business_day_of_week():
    assert cal.last_business_day_of_week(D("2031-03-12"), set()) == D("2031-03-14")
    assert cal.last_business_day_of_week(D("2031-03-12"), {D("2031-03-14")}) == D("2031-03-13")  # Friday is a holiday
    week = {D("2031-03-10") + datetime.timedelta(days=i) for i in range(5)}
    assert cal.last_business_day_of_week(D("2031-03-12"), week) is None


def test_counting_and_weekdays():
    assert cal.business_days_between(D("2031-03-07"), D("2031-03-14"), set()) == 5
    assert cal.business_days_between(D("2031-03-07"), D("2031-03-07"), set()) == 0
    assert cal.weekday_in_week(D("2031-03-07"), "Friday") == D("2031-03-07")
    assert cal.weekday_in_week(D("2031-03-07"), "friday", 1) == D("2031-03-14")  # "next Friday" said on a Friday


@pytest.mark.parametrize("raw", ["2031-03-07T11:00", "2031-03-07 11:00:00", "2031-03-07T11:00:00Z"])
def test_parse_now(raw):
    assert cal.parse_now(raw) == datetime.datetime(2031, 3, 7, 11, 0)


def test_parse_now_date_only_and_garbage():
    assert cal.parse_now("2031-03-07") == datetime.datetime(2031, 3, 7)
    with pytest.raises(ValueError):
        cal.parse_now("tomorrow")


def test_words_and_money():
    today = D("2031-03-03")
    assert cal.spoken_date(D("2031-03-07")) == "Friday 7 March"
    assert cal.parse_date_words("the 7th of March", today) == D("2031-03-07")
    assert cal.parse_date_words("March 2nd", today) == D("2032-03-02")  # already past this year
    assert cal.parse_date_words("07/03/2031", today) == D("2031-03-07")  # day first
    assert cal.parse_date_words("whenever", today) is None
    assert cal.to_cents(19.99) == 1999 and cal.to_cents("1,234.5") == 123450 and cal.from_cents(1999) == 19.99
    assert cal.money(1234.5) == "1,234.50" and cal.money(80, "$") == "$80"
    assert cal.parse_hhmm("9:30") == datetime.time(9, 30) and cal.in_window(datetime.time(19, 0), datetime.time(10), datetime.time(19))
    assert cal.as_list('[{"a": 1}]') == [{"a": 1}] and cal.as_list({"a": 1}) == [{"a": 1}] and cal.as_list(None) == []
