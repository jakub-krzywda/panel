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
    assert r["labels"] == ["28.09–04.10", "05.10–11.10", "12.10–18.10"]
    assert r["ticks"] == ["28.09", "05.10", "12.10"]
    assert r["series"]["trening"] == [50, None, 100]
    assert r["series"]["dieta"] == [75, None, None]


def test_activity_by_month():
    days = [
        day("2026-09-30", pomodoro_count=4, walk_1300=True, walk_2000=True),
        day("2026-10-01", pomodoro_count=None, walk_1300=True),
        day("2026-10-02", pomodoro_count=3, walk_2000=False),
    ]
    r = stats.activity(days, "month")
    assert r == {"labels": ["wrz 2026", "paź 2026"], "ticks": ["wrz", "paź"], "pomodoro": [4, 3], "walk_1300": [1, 1],
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
    assert stats.habit_rates([], "week") == {"labels": [], "ticks": [], "series": {}}
