"""Import wyników parsera do bazy — dane syntetyczne w formacie pages.jsonl."""

import copy
import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importer import import_results
from app.models import Day, HabitEntry


def page(date="2026-09-23", **overrides) -> dict:
    result = {
        "source": {"file": "Dziennik 2026-223.jpg", "layout": "v7"},
        "data": {
            "date": date,
            "habits": {"trening": False, "muzyka": True, "czytanie": True, "suma_dnia": 2},
            "walks": {"1300": True, "2000": False, "1300_note": "las", "2000_note": None},
            "bp": {"morning": {"sys": 131, "dia": 77, "pulse": 59}},
            "pomodoro_count": 3,
            "sport_text": None,
            "music_text": "Karma Police",
        },
        "fields": {
            "date": {"value": date, "confidence": 1.0},
            "habits.muzyka": {"value": True},
            "habits.czytanie": {"value": True, "partial": True},
            "sleep_from": {"value": "01:30", "ocr": ["~130"], "unverified": True},
            "music_text": {"value": "Karma Police", "unverified": True},
        },
        "low_confidence": [],
    }
    for key, value in overrides.items():
        result["data"][key] = value
    return result


def habits_of(s: Session, date: dt.date) -> dict[str, float]:
    day = s.scalar(select(Day).where(Day.date == date))
    return {h.habit: h.value for h in day.habits}


def test_insert(engine):
    with Session(engine) as s:
        stats = import_results(s, [page()])
        assert stats == {"inserted": 1}
        day = s.scalar(select(Day))
        assert day.date == dt.date(2026, 9, 23)
        assert day.source == "pdf_import"
        assert day.template_version == "v7"
        assert (day.pomodoro_count, day.walk_1300, day.walk_2000, day.walk_1300_note) == (3, True, False, "las")
        assert (day.bp_morning_sys, day.bp_morning_dia, day.bp_morning_pulse) == (131, 77, 59)
        assert day.bp_evening_sys is None
        assert day.sleep_from is None  # OCR godzin nie trafia do kolumn
        assert day.import_meta["sleep_ocr"] == {"sleep_from": ["~130"]}
        assert day.import_meta["unverified"] == ["music_text", "sleep_from"]
        assert habits_of(s, day.date) == {"trening": 0.0, "muzyka": 1.0, "czytanie": 0.5}


def test_reimport_is_idempotent(engine):
    with Session(engine) as s:
        import_results(s, [page(), page("2026-09-24")])
        before = [(d.date, d.pomodoro_count, sorted((h.habit, h.value) for h in d.habits)) for d in s.scalars(select(Day))]
        stats = import_results(s, [page(), page("2026-09-24")])
        after = [(d.date, d.pomodoro_count, sorted((h.habit, h.value) for h in d.habits)) for d in s.scalars(select(Day))]
        assert stats == {"updated": 2}
        assert before == after
        assert s.query(HabitEntry).count() == 6


def test_reimport_replaces_values(engine):
    with Session(engine) as s:
        import_results(s, [page()])
        changed = page(pomodoro_count=5, habits={"trening": True})
        import_results(s, [changed])
        day = s.scalar(select(Day))
        assert day.pomodoro_count == 5
        assert habits_of(s, day.date) == {"trening": 1.0}


def test_manual_day_is_not_overwritten(engine):
    with Session(engine) as s:
        s.add(Day(date=dt.date(2026, 9, 23), source="manual", pomodoro_count=7))
        s.commit()
        stats = import_results(s, [page()])
        assert stats == {"skipped_manual": 1}
        assert s.scalar(select(Day)).pomodoro_count == 7


@pytest.mark.parametrize(
    "results, expected",
    [
        pytest.param([page(date=None)], {"skipped_no_date": 1}, id="no_date"),
        pytest.param([page(), page()], {"inserted": 1, "skipped_duplicate_in_input": 1}, id="duplicate"),
    ],
)
def test_skips(engine, results, expected):
    with Session(engine) as s:
        assert import_results(s, copy.deepcopy(results)) == expected
