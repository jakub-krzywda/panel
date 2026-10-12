"""Pozycje „co ćwiczę”: config, przenoszenie na kolejne dni, odhaczanie w formularzu."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app import practice
from app.models import Day, PracticeItem, PracticeLog


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
    monkeypatch.setattr(main, "today", lambda: dt.date(2026, 10, 13))
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _labels(session, category="music", active_only=True):
    session.expire_all()
    q = select(PracticeItem).where(PracticeItem.category == category).order_by(PracticeItem.position)
    return [i.label for i in session.scalars(q) if i.active or not active_only]


def _logged(session, date):
    session.expire_all()
    day = session.scalar(select(Day).where(Day.date == dt.date.fromisoformat(date)))
    return sorted(log.item.label for log in day.practice)


def test_new_item_from_day_form_carries_over(client, session):
    client.post("/day/2026-10-12", data={"practice_new.music": "  Karma   Police  "})
    assert _labels(session) == ["Karma Police"]
    assert _logged(session, "2026-10-12") == ["Karma Police"]

    page = client.get("/day/2026-10-13").text
    item_id = session.scalar(select(PracticeItem.id))
    assert f'name="practice.{item_id}"' in page
    assert "Karma Police" in page


def test_check_items_and_add_another(client, session):
    practice.add_item(session, "music", "Gamy")
    practice.add_item(session, "sport", "Kalistenika")
    gamy, kal = session.scalars(select(PracticeItem).order_by(PracticeItem.id)).all()

    client.post("/day/2026-10-13", data={f"practice.{gamy.id}": "on", "practice_new.sport": "Basen", "music_text": "lewa ręka"})
    assert _logged(session, "2026-10-13") == ["Basen", "Gamy"]

    # ponowny zapis bez zaznaczeń czyści log dnia, pozycje zostają na liście
    client.post("/day/2026-10-13", data={})
    assert _logged(session, "2026-10-13") == []
    assert _labels(session, "sport") == ["Kalistenika", "Basen"]


def test_hidden_item_disappears_from_new_days_but_stays_on_logged_day(client, session):
    practice.add_item(session, "music", "Gamy")
    item = session.scalar(select(PracticeItem))
    client.post("/day/2026-10-12", data={f"practice.{item.id}": "on"})
    client.post(f"/config/items/{item.id}", data={"action": "hide"})

    assert f'name="practice.{item.id}"' not in client.get("/day/2026-10-13").text
    old_day = client.get("/day/2026-10-12").text
    assert f'name="practice.{item.id}"' in old_day and "(ukryta)" in old_day

    # dopisanie ukrytej pozycji z formularza przywraca ją zamiast tworzyć duplikat
    client.post("/day/2026-10-13", data={"practice_new.music": "Gamy"})
    assert _labels(session, active_only=False) == ["Gamy"]
    assert _labels(session) == ["Gamy"]


def test_config_rename_and_move(client, session):
    for label in ("A", "B", "C"):
        client.post("/config/items", data={"category": "music", "label": label})
    a, b, c = session.scalars(select(PracticeItem).order_by(PracticeItem.position)).all()

    client.post(f"/config/items/{c.id}", data={"action": "up"})
    assert _labels(session) == ["A", "C", "B"]
    client.post(f"/config/items/{a.id}", data={"action": "up"})  # już pierwszy — bez zmian
    assert _labels(session) == ["A", "C", "B"]

    client.post(f"/config/items/{b.id}", data={"action": "rename", "label": "B2"})
    client.post(f"/config/items/{a.id}", data={"action": "rename", "label": "C"})  # kolizja nazwy — ignorowana
    assert _labels(session) == ["A", "C", "B2"]
    assert "B2" in client.get("/config").text


def test_item_used_in_log_cannot_be_deleted(session):
    practice.add_item(session, "music", "Gamy")
    item = session.scalar(select(PracticeItem))
    session.add(Day(date=dt.date(2026, 10, 1), source="manual", practice=[PracticeLog(item_id=item.id)]))
    session.commit()
    session.delete(item)
    with pytest.raises(Exception):
        session.commit()
