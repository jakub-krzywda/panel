"""Formularz dnia i historia przez TestClient na tymczasowej bazie."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.forms import sleep_duration
from app.models import Day, HabitEntry

DATE = "2026-09-23"


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine, monkeypatch):
    def get_session():
        with Session(engine) as s:
            yield s

    main.app.dependency_overrides[main.get_session] = get_session
    monkeypatch.setattr(main, "today", lambda: dt.date(2026, 9, 24))
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _day(session: Session, date: str = DATE) -> Day:
    session.expire_all()
    return session.scalar(select(Day).where(Day.date == dt.date.fromisoformat(date)))


def test_index_redirects_to_today(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/day/2026-09-24"


def test_empty_form(client):
    r = client.get(f"/day/{DATE}")
    assert r.status_code == 200
    assert "Środa, 23.09.2026" in r.text
    assert 'name="habit.nie_palenie"' in r.text


def test_save_new_day(client, session):
    r = client.post(f"/day/{DATE}", data={
        "sleep_from": "23:30", "sleep_to": "07:00", "pomodoro_count": "4",
        "habit.trening": "on", "habit.czytanie": "on",
        "walk_1300": "on", "walk_1300_note": "las",
        "bp_morning_sys": "128", "bp_morning_dia": "76", "bp_morning_pulse": "60",
        "music_text": "Karma Police",
    }, follow_redirects=False)
    assert r.status_code == 303

    day = _day(session)
    assert day.source == "manual"
    assert day.fill_timestamp is not None
    assert day.sleep_hours == 7.5
    assert (day.pomodoro_count, day.walk_1300, day.walk_2000, day.walk_1300_note) == (4, True, False, "las")
    assert (day.bp_morning_sys, day.bp_morning_dia, day.bp_morning_pulse) == (128, 76, 60)
    assert day.bp_evening_sys is None
    assert day.music_text == "Karma Police"
    assert {h.habit: h.value for h in day.habits} == {
        "trening": 1.0, "muzyka": 0.0, "czytanie": 1.0, "sen_przed_0": 0.0, "nie_palenie": 0.0,
    }
    assert "Zapisano." in client.get(r.headers["location"]).text


def test_validation_error_keeps_input(client, session):
    r = client.post(f"/day/{DATE}", data={"bp_morning_sys": "abc", "pomodoro_count": "12", "music_text": "x"})
    assert r.status_code == 400
    assert "nie liczba" in r.text and "poza zakresem" in r.text
    assert ">x</textarea>" in r.text
    assert _day(session) is None


def test_saving_imported_day_makes_it_manual_and_keeps_half(client, session):
    session.add(Day(date=dt.date(2026, 9, 23), source="pdf_import", template_version="v5",
                    habits=[HabitEntry(habit="dieta", value=0.5), HabitEntry(habit="trening", value=1)]))
    session.commit()

    page = client.get(f"/day/{DATE}").text
    assert 'name="habit.dieta"' in page  # nawyk ze starego templatu nadal edytowalny
    assert 'name="habit.nie_palenie"' not in page  # nie było go na templacie v5
    assert "(½)" in page

    client.post(f"/day/{DATE}", data={"habit.dieta": "on"})
    day = _day(session)
    assert day.source == "manual"
    assert {h.habit: h.value for h in day.habits} == {"dieta": 0.5, "trening": 0.0}


def test_history_lists_days(client, session):
    for d in ("2026-09-22", "2026-09-23"):
        session.add(Day(date=dt.date.fromisoformat(d), source="pdf_import", pomodoro_count=3))
    session.commit()
    r = client.get("/history")
    assert r.status_code == 200
    assert "· 2 dni" in r.text
    assert r.text.index("23.09") < r.text.index("22.09")


@pytest.mark.parametrize("start, end, hours", [("23:30", "07:00", 7.5), ("01:00", "09:00", 8.0), ("00:00", "00:00", 0.0)])
def test_sleep_duration(start, end, hours):
    assert sleep_duration(dt.time.fromisoformat(start), dt.time.fromisoformat(end)) == hours


def test_stats_page(client, session):
    session.add(Day(date=dt.date(2026, 9, 23), source="manual", pomodoro_count=2,
                    habits=[HabitEntry(habit="trening", value=1)]))
    session.commit()
    for period in ("day", "week", "month", "nonsense"):
        assert client.get(f"/stats?period={period}").status_code == 200
    # wykresy per nawyk tylko w miesiącach; dzień = kratki, tydzień = jedna linia sumy
    assert 'data-habit="trening"' in client.get("/stats?period=month").text
    assert 'data-habit="trening"' not in client.get("/stats?period=week").text
    assert 'class="timeline" data-timeline' in client.get("/stats?period=day").text
    assert 'class="timeline" data-timeline' not in client.get("/stats?period=week").text
    assert 'id="habit-grid"' in client.get("/stats?period=day").text
    assert 'id="checked"' in client.get("/stats?period=week").text


def test_stats_page_weekly_summary(client, session):
    session.add(Day(date=dt.date(2026, 9, 23), source="manual", pomodoro_count=5,
                    habits=[HabitEntry(habit="trening", value=1)]))
    session.commit()
    week = client.get("/stats?period=week").text
    assert "Zestawienie tygodniowe" in week and "<strong>T39</strong>" in week
    assert "bieżący" in week  # 23.09 w tym samym tygodniu co `today` z fixture (24.09)
    assert "Zestawienie tygodniowe" not in client.get("/stats?period=month").text
    assert client.get("/static/chart-4.4.7.umd.min.js").status_code == 200


def test_stats_page_hides_legacy_habits_by_default(client, session):
    session.add(Day(date=dt.date(2026, 9, 23), source="pdf_import",
                    habits=[HabitEntry(habit="trening", value=1), HabitEntry(habit="dieta", value=0.5)]))
    session.commit()
    html = client.get("/stats?period=month").text
    before_legacy, legacy = html.split('<details id="legacy"', 1)
    assert 'data-habit="trening"' in before_legacy
    assert 'data-habit="dieta"' not in before_legacy
    assert 'data-habit="dieta" data-lazy' in legacy


def test_stats_widget_only_on_today(client, session):
    session.add(Day(date=dt.date(2026, 9, 23), source="manual", habits=[HabitEntry(habit="trening", value=1)]))
    session.commit()
    today_page = client.get("/day/2026-09-24").text  # today w fixture
    assert 'class="slot-view"' in today_page and 'class="cal"' in today_page
    assert today_page.index('id="widget"') < today_page.index('name="pomodoro_count"')  # statystyki nad formularzem
    assert 'class="slot-view"' not in client.get("/day/2026-09-23").text


def test_page_title_is_clean(client):
    html = client.get("/day/2026-09-24").text
    title = html[html.index("<title>") : html.index("</title>")]
    assert "<script" not in title and title.endswith("— Dziennik")


def test_screenshot_import_script_included_once(client):
    html = client.get("/day/2026-09-24").text
    assert html.count('addEventListener("paste"') == 1
    assert html.index('addEventListener("paste"') > html.index('id="shot-form"')  # skrypt po formularzu
