"""Import ze zrzutu w aplikacji: wgranie → wypełniony formularz (bez zapisu) → zapis jako screenshot_import."""

import datetime as dt
import re

import cv2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.models import Day, PracticeItem
from app.screenshot_import import match_practice
from dziennik.parse import ROOT
from tests.helpers.synthetic import make_screenshot

TODAY = dt.date(2026, 10, 13)
needs_template = pytest.mark.skipif(
    not (ROOT / "data" / "_GoodNotes templates" / "Tydzien_Template_v8.pdf").exists(), reason="brak templatu v8"
)


@pytest.fixture
def client(engine, monkeypatch):
    def get_session():
        with Session(engine) as s:
            yield s

    main.app.dependency_overrides[main.get_session] = get_session
    monkeypatch.setattr(main, "today", lambda: TODAY)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def png(**kwargs) -> bytes:
    rgb = make_screenshot(**kwargs)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return buf.tobytes()


def checked(html: str, name: str, value: str | None = None) -> bool:
    attr = f'name="{name}"' + (f' value="{value}"' if value is not None else "")
    m = re.search(rf"<input[^>]*{re.escape(attr)}[^>]*>", html)
    return bool(m) and " checked" in m.group(0)


@needs_template
def test_upload_prefills_form_without_saving(client, engine):
    r = client.post(f"/day/{TODAY}/screenshot", files={"file": ("shot.png", png(), "image/png")})
    assert r.status_code == 200
    html = r.text
    assert "Wczytano ze zrzutu" in html
    assert checked(html, "habit.trening") and checked(html, "habit.czytanie") and not checked(html, "habit.muzyka")
    assert checked(html, "pomodoro_count", "3")
    assert checked(html, "walk_1300") and not checked(html, "walk_2000")
    assert 'name="_source" value="screenshot_import"' in html
    with Session(engine) as s:
        assert s.scalar(select(Day)) is None


@needs_template
def test_fields_outside_screenshot_keep_saved_values(client, engine):
    with Session(engine) as s:
        s.add(Day(date=TODAY, source="manual", sleep_from=dt.time(23, 30), pomodoro_count=1))
        s.commit()
    html = client.post(f"/day/{TODAY}/screenshot", files={"file": ("s.png", png(pomodoro=6), "image/png")}).text
    assert 'value="23:30"' in html  # sen jest nad separatorem — bez zmian
    assert checked(html, "pomodoro_count", "6")  # pomodoro ze zrzutu nadpisuje zapisane


def test_save_after_import_marks_source(client, engine):
    client.post(f"/day/{TODAY}", data={"_source": "screenshot_import", "pomodoro_count": "3"})
    with Session(engine) as s:
        day = s.scalar(select(Day))
        assert day.source == "screenshot_import" and day.pomodoro_count == 3


def test_unknown_source_falls_back_to_manual(client, engine):
    client.post(f"/day/{TODAY}", data={"_source": "pdf_import"})
    with Session(engine) as s:
        assert s.scalar(select(Day)).source == "manual"


@pytest.mark.parametrize("content, message", [
    pytest.param(b"", "Nie wybrano pliku", id="empty"),
    pytest.param(b"not an image", "Nie udało się odczytać obrazu", id="garbage"),
    pytest.param(cv2.imencode(".png", 255 * __import__("numpy").ones((300, 900, 3), "uint8"))[1].tobytes(),
                 "pusty", id="blank_image"),
])
def test_bad_uploads(client, content, message):
    r = client.post(f"/day/{TODAY}/screenshot", files={"file": ("x.png", content, "image/png")})
    assert r.status_code == 400
    assert message in r.text


@pytest.mark.parametrize("text, expected", [
    ("KARMA POLICE - piano cover, gamy", ["Karma Police", "Gamy"]),
    ("Karna Polica", ["Karma Police"]),  # pomyłki OCR
    ("pasaże lewa ręka", []),
    (None, []),
])
def test_match_practice(text, expected):
    items = [PracticeItem(id=i, category="music", label=l) for i, l in enumerate(["Karma Police", "Gamy", "Etiuda"])]
    assert [i.label for i in match_practice(text, items)] == expected


def test_uploads_are_saved_even_when_unreadable(client, tmp_path):
    client.post(f"/day/{TODAY}/screenshot", files={"file": ("x.png", b"not an image", "image/png")})
    saved = list((tmp_path / "screenshots").iterdir())
    assert len(saved) == 1 and saved[0].name.startswith(f"{TODAY}_") and saved[0].suffix == ".bin"


@needs_template
def test_saved_upload_keeps_png_extension(client, tmp_path):
    client.post(f"/day/{TODAY}/screenshot", files={"file": ("s.png", png(), "image/png")})
    assert [p.suffix for p in (tmp_path / "screenshots").iterdir()] == [".png"]


def test_empty_upload_is_not_saved(client, tmp_path):
    client.post(f"/day/{TODAY}/screenshot", files={"file": ("x.png", b"", "image/png")})
    assert not (tmp_path / "screenshots").exists()
