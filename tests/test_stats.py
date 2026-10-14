"""Agregacje do wykresów — na obiektach w pamięci, bez bazy."""

import datetime as dt

import pytest

from app import stats
from app.models import Day, HabitEntry


def day(date: str, habits: dict[str, float] | None = None, **kw) -> Day:
    return Day(date=dt.date.fromisoformat(date), source="manual",
               habits=[HabitEntry(habit=h, value=v) for h, v in (habits or {}).items()], **kw)


@pytest.mark.parametrize("date, period, start", [
    ("2026-10-14", "week", "2026-10-12"),
    ("2026-10-12", "week", "2026-10-12"),
    ("2026-10-18", "week", "2026-10-12"),
    ("2026-10-14", "month", "2026-10-01"),
    ("2026-10-14", "day", "2026-10-14"),
])
def test_period_start(date, period, start):
    assert stats.period_start(dt.date.fromisoformat(date), period) == dt.date.fromisoformat(start)


def test_habit_rates_skip_untracked_periods():
    days = [
        day("2026-09-28", {"trening": 1, "dieta": 0.5}),
        day("2026-09-29", {"trening": 0, "dieta": 1}),
        # tydzień 05.10 bez wpisów
        day("2026-10-12", {"trening": 1}),
    ]
    r = stats.habit_rates(days, "week")
    assert r["labels"] == ["T40/2026 · 28.09–04.10", "T41/2026 · 05.10–11.10", "T42/2026 · 12.10–18.10"]
    assert r["ticks"] == ["T40", "T41", "T42"]
    assert r["dates"] == ["2026-09-28", "2026-10-05", "2026-10-12"]
    assert r["series"]["trening"] == [50, None, 100]
    assert r["series"]["dieta"] == [75, None, None]
    assert r["counts"]["trening"] == [1, None, 1]
    assert r["counts"]["dieta"] == [1.5, None, None]


def test_activity_by_month():
    days = [
        day("2026-09-30", pomodoro_count=4, walk_1300=True, walk_2000=True),
        day("2026-10-01", pomodoro_count=None, walk_1300=True),
        day("2026-10-02", pomodoro_count=3, walk_2000=False),
    ]
    r = stats.activity(days, "month")
    assert r == {"labels": ["wrz 2026", "paź 2026"], "ticks": ["wrz", "paź"], "dates": ["2026-09-01", "2026-10-01"],
                 "pomodoro": [4, 3], "walk_1300": [1, 1],
                 "walk_2000": [1, 0], "days": [1, 2]}


def test_calendar_grid():
    days = [day("2026-10-07", {"a": 1, "b": 1}), day("2026-10-08", {"a": 0, "b": 0}), day("2026-10-09")]
    weeks = stats.calendar(days, end=dt.date(2026, 10, 13))
    assert len(weeks) == 2 and all(len(w) == 7 for w in weeks)
    assert weeks[0][:2] == [None, None]  # pon, wt przed pierwszym wpisem
    wed, thu, fri, sat = weeks[0][2:6]
    assert (wed["level"], thu["level"], fri["level"], sat["level"]) == (4, 1, 1, 0)
    assert fri["score"] is None and fri["has_entry"]
    assert weeks[1][1]["date"] == dt.date(2026, 10, 13) and weeks[1][2] is None  # po `end`


def test_empty():
    assert stats.calendar([], dt.date(2026, 10, 13)) == []
    assert stats.habit_rates([], "week") == {"labels": [], "ticks": [], "dates": [], "series": {},
                                               "counts": {}}
    assert stats.weekly_summary([], ["trening"]) == []


def test_weather_by_week():
    def w(t, p):
        return {"daily": {"temperature_2m_max": t, "precipitation_sum": p}}

    days = [day("2026-10-05", weather_api=w(10.0, 1.0)), day("2026-10-06", weather_api=w(14.0, 0.5)),
            day("2026-10-12", weather_api=None), day("2026-10-13", weather_api=w(None, None))]
    r = stats.weather(days, "week")
    assert r["temp_max"] == [12.0, None]
    assert r["precip"] == [1.5, None]


def test_week_number_uses_iso_year_at_year_boundary():
    start = dt.date(2025, 12, 29)  # poniedziałek; ISO: 1. tydzień 2026
    assert stats.period_tick(start, "week") == "T1"
    assert stats.period_label(start, "week") == "T1/2026 · 29.12–04.01"


def test_habit_rates_by_day_is_continuous():
    days = [day("2026-10-12", {"trening": 1}), day("2026-10-14", {"trening": 0})]
    r = stats.habit_rates(days, "day")
    assert r["dates"] == ["2026-10-12", "2026-10-13", "2026-10-14"]
    assert r["labels"] == ["pn 12.10.2026", "wt 13.10.2026", "śr 14.10.2026"]
    assert r["ticks"] == ["pn 12.10", "wt 13.10", "śr 14.10"]
    assert r["weeks"] == ["T42", "T42", "T42"]
    assert r["series"]["trening"] == [100, None, 0]
    assert r["counts"]["trening"] == [1, None, 0]


def test_blood_pressure_by_day_on_day_axis():
    days = [day("2026-10-12", bp_morning_sys=120, bp_morning_dia=80), day("2026-10-14"),
            day("2026-10-15", bp_evening_sys=130, bp_evening_dia=85)]
    r = stats.blood_pressure(days, "day")
    assert r["dates"] == ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"]
    assert r["morning_sys"] == [120, None, None, None]
    assert r["evening_dia"] == [None, None, None, 85]
    # bez okresu — jak dotąd tylko dni z pomiarem
    assert stats.blood_pressure(days)["labels"] == ["12.10", "15.10"]


def test_weekly_summary():
    days = [
        day("2026-09-28", {"trening": 1, "dieta": 1}, pomodoro_count=4, walk_1300=True,
            bp_morning_sys=120, bp_morning_dia=80),
        day("2026-09-30", {"trening": 0}, pomodoro_count=2, walk_2000=True, bp_morning_sys=130, bp_morning_dia=85,
            weather_api={"daily": {"temperature_2m_max": 15.0}}),
        # tydzień T41 bez wpisów — pominięty
        day("2026-10-13", {"trening": 1}),
    ]
    rows = stats.weekly_summary(days, ["trening", "czytanie"])
    assert [r["week"] for r in rows] == ["T42", "T40"]  # od najnowszego
    t42, t40 = rows
    assert t42["start"] == dt.date(2026, 10, 12) and t42["days"] == 1
    assert t42["habits"] == {"trening": 100, "czytanie": None}
    assert t42["bp_morning"] is None
    assert t40["label"] == "T40/2026 · 28.09–04.10"
    assert t40["days"] == 2 and t40["pomodoro"] == 6
    assert (t40["walk_1300"], t40["walk_2000"]) == (1, 1)
    assert t40["habits"] == {"trening": 50, "czytanie": None}  # dawne nawyki (dieta) nie są pokazywane
    assert t40["bp_morning"] == "125/82" and t40["bp_evening"] is None
    assert t40["temp_max"] == 15.0
