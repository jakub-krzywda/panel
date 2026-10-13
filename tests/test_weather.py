"""Pogoda z Open-Meteo — HTTP zamockowany (httpx.MockTransport)."""

import asyncio
import datetime as dt

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app import weather
from app.models import Day

TODAY = dt.date(2026, 10, 13)


def daily_payload(dates: list[str]) -> dict:
    n = len(dates)
    return {"daily": {"time": dates, "weather_code": [3] * n, "temperature_2m_max": [12.0] * n,
                      "temperature_2m_min": [7.5] * n, "precipitation_sum": [0.4] * n,
                      "sunshine_duration": [3600.0] * n, "wind_speed_10m_max": [10.0] * n,
                      "pressure_msl_mean": [1019.3] * n}}


def date_range(start: str, end: str) -> list[str]:
    a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


@pytest.fixture
def api(monkeypatch):
    """Fałszywe Open-Meteo; zwraca listę zapytań do asercji."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        p = request.url.params
        assert "Katowice" not in str(request.url) and p["latitude"] == "50.2649"
        if "current" in p:
            return httpx.Response(200, json={"current": {"time": "2026-10-13T08:00", "temperature_2m": 9.1,
                                                         "apparent_temperature": 6.7, "weather_code": 3,
                                                         "pressure_msl": 1024.6, "relative_humidity_2m": 76}})
        return httpx.Response(200, json=daily_payload(date_range(p["start_date"], p["end_date"])))

    monkeypatch.setattr(weather, "TRANSPORT", httpx.MockTransport(handler))
    return calls


def run(coro):
    return asyncio.run(coro)


def test_snapshot_today_has_daily_and_current(api):
    snap = run(weather.snapshot(TODAY, TODAY))
    assert snap["daily"]["temperature_2m_max"] == 12.0
    assert snap["current"]["temperature_2m"] == 9.1
    assert snap["location"] == "Katowice"


def test_snapshot_past_day_without_current(api):
    snap = run(weather.snapshot(dt.date(2026, 10, 1), TODAY))
    assert snap["current"] is None
    assert all(r.url.host == "api.open-meteo.com" for r in api)


def test_range_split_between_archive_and_forecast(api):
    out = run(weather.fetch_daily(dt.date(2026, 6, 11), dt.date(2026, 10, 12), TODAY))
    assert len(out) == (dt.date(2026, 10, 12) - dt.date(2026, 6, 11)).days + 1
    hosts = {r.url.host: (r.url.params["start_date"], r.url.params["end_date"]) for r in api}
    border = TODAY - dt.timedelta(days=weather.ARCHIVE_OLDER_THAN_DAYS)
    assert hosts["archive-api.open-meteo.com"] == ("2026-06-11", (border - dt.timedelta(days=1)).isoformat())
    assert hosts["api.open-meteo.com"] == (border.isoformat(), "2026-10-12")


def test_cache_avoids_second_request(api):
    run(weather.snapshot(dt.date(2026, 10, 1), TODAY))
    run(weather.snapshot(dt.date(2026, 10, 1), TODAY))
    assert len(api) == 1


def test_network_error_returns_none():
    assert run(weather.snapshot(TODAY, TODAY)) is None  # conftest: sieć wyłączona


def test_far_future_skipped(api):
    assert run(weather.snapshot(TODAY + dt.timedelta(days=30), TODAY)) is None
    assert api == []


def test_backfill_fills_only_missing(api, engine):
    with Session(engine) as s:
        s.add_all([Day(date=dt.date(2026, 10, 1), source="pdf_import"),
                   Day(date=dt.date(2026, 10, 2), source="pdf_import", weather_api={"keep": True})])
        s.commit()
        assert run(weather.backfill(s, TODAY, dry_run=True)) == 1
        assert s.scalar(select(Day).where(Day.date == dt.date(2026, 10, 1))).weather_api is None
        assert run(weather.backfill(s, TODAY, dry_run=False)) == 1
        days = {d.date.day: d.weather_api for d in s.scalars(select(Day))}
        assert days[1]["daily"]["pressure_msl_mean"] == 1019.3
        assert days[2] == {"keep": True}


@pytest.fixture
def client(engine, monkeypatch):
    def get_session():
        with Session(engine) as s:
            yield s

    main.app.dependency_overrides[main.get_session] = get_session
    monkeypatch.setattr(main, "today", lambda: TODAY)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_form_save_stores_weather_and_shows_it(api, client, engine):
    client.post(f"/day/{TODAY}", data={})
    with Session(engine) as s:
        day = s.scalar(select(Day))
        assert day.weather_api["current"]["temperature_2m"] == 9.1
        assert day.weather_fetched_at is not None
    page = client.get(f"/day/{TODAY}").text
    assert "Pogoda" in page and "pochmurno" in page and "1019 hPa" in page


def test_form_save_without_network_still_saves(client, engine):
    r = client.post(f"/day/{TODAY}", data={"pomodoro_count": "2"}, follow_redirects=False)
    assert r.status_code == 303
    with Session(engine) as s:
        day = s.scalar(select(Day))
        assert day.pomodoro_count == 2 and day.weather_api is None


def test_past_day_with_weather_is_not_refetched(api, client, engine):
    with Session(engine) as s:
        s.add(Day(date=dt.date(2026, 10, 1), source="pdf_import", weather_api={"daily": {"weather_code": 0}, "location": "Katowice", "current": None}))
        s.commit()
    client.post("/day/2026-10-01", data={})
    assert api == []


def test_today_page_shows_forecast(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        hours = [f"2026-10-13T{h:02d}:00" for h in range(24)]
        return httpx.Response(200, json={
            "daily": {"weather_code": [61], "temperature_2m_max": [12.4], "temperature_2m_min": [6.8],
                      "precipitation_sum": [2.1], "precipitation_probability_max": [70],
                      "sunrise": ["2026-10-13T07:02"], "sunset": ["2026-10-13T18:11"]},
            "hourly": {"time": hours, "temperature_2m": [float(h) for h in range(24)],
                       "precipitation_probability": [10] * 24, "weather_code": [3] * 24},
        })

    monkeypatch.setattr(weather, "TRANSPORT", httpx.MockTransport(handler))
    html = client.get(f"/day/{TODAY}").text
    assert "7–12 °C" in html and "lekki deszcz" in html and "70%" in html and "07:02" in html
    assert html.count("<li>") >= 6 and "21:00" in html and "03:00" not in html


def test_forecast_unavailable_offline(client):
    assert "Prognoza niedostępna" in client.get(f"/day/{TODAY}").text


def test_no_forecast_on_past_day(api, client):
    assert "Prognoza" not in client.get("/day/2026-10-01").text
