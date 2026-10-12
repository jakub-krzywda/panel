"""Pogoda z Open-Meteo (bez klucza) dla Katowic — snapshot zapisywany razem z dniem.

Wysyłamy tylko współrzędne i daty; żadne dane z dziennika nie wychodzą na zewnątrz.

    uv run python -m app.weather backfill --dry-run   # uzupełnij pogodę dla dni bez niej
"""

import argparse
import asyncio
import datetime as dt
import logging
import sys
import time

import httpx
from sqlalchemy import select

LOCATION = {"name": "Katowice", "latitude": 50.2649, "longitude": 19.0238, "timezone": "Europe/Warsaw"}
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Archiwum ma kilkudniowe opóźnienie, a forecast sięga ~3 miesiące wstecz — granica z zapasem.
ARCHIVE_OLDER_THAN_DAYS = 60
FORECAST_MAX_AHEAD_DAYS = 15
DAILY_VARS = [
    "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
    "sunshine_duration", "wind_speed_10m_max", "pressure_msl_mean",
]
CURRENT_VARS = ["temperature_2m", "apparent_temperature", "weather_code", "pressure_msl", "relative_humidity_2m"]
TIMEOUT_S = 5.0
CACHE_TTL_S = 3600

# Podmieniany w testach na httpx.MockTransport.
TRANSPORT: httpx.AsyncBaseTransport | None = None

log = logging.getLogger(__name__)
_cache: dict[tuple, tuple[float, dict]] = {}

# WMO weather codes → opis po polsku.
WMO_PL = {
    0: "bezchmurnie", 1: "przeważnie pogodnie", 2: "częściowe zachmurzenie", 3: "pochmurno",
    45: "mgła", 48: "mgła szronowa",
    51: "lekka mżawka", 53: "mżawka", 55: "gęsta mżawka", 56: "marznąca mżawka", 57: "marznąca mżawka",
    61: "lekki deszcz", 63: "deszcz", 65: "ulewa", 66: "marznący deszcz", 67: "marznący deszcz",
    71: "lekki śnieg", 73: "śnieg", 75: "intensywny śnieg", 77: "ziarna śniegu",
    80: "przelotny deszcz", 81: "przelotne opady", 82: "gwałtowne opady",
    85: "przelotny śnieg", 86: "intensywny przelotny śnieg",
    95: "burza", 96: "burza z gradem", 99: "burza z gradem",
}


def describe(code: int | None) -> str:
    return WMO_PL.get(code, "?") if code is not None else "?"


async def _get(url: str, params: dict) -> dict:
    key = (url, tuple(sorted(params.items())))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=TRANSPORT) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    _cache[key] = (time.monotonic(), data)
    return data


def _base_params() -> dict:
    return {k: LOCATION[k] for k in ("latitude", "longitude", "timezone")}


async def fetch_daily(start: dt.date, end: dt.date, today: dt.date) -> dict[dt.date, dict]:
    """Dane dzienne dla zakresu dat → {data: {zmienna: wartość}}. Zakres dzielony na archiwum i forecast."""
    border = today - dt.timedelta(days=ARCHIVE_OLDER_THAN_DAYS)
    ranges = []
    if start < border:
        ranges.append((ARCHIVE_URL, start, min(end, border - dt.timedelta(days=1))))
    if end >= border:
        ranges.append((FORECAST_URL, max(start, border), end))

    out: dict[dt.date, dict] = {}
    for url, a, b in ranges:
        data = await _get(url, {**_base_params(), "start_date": a.isoformat(), "end_date": b.isoformat(),
                                "daily": ",".join(DAILY_VARS)})
        daily = data["daily"]
        for i, day in enumerate(daily["time"]):
            out[dt.date.fromisoformat(day)] = {var: daily[var][i] for var in DAILY_VARS}
    return out


async def snapshot(date: dt.date, today: dt.date) -> dict | None:
    """Snapshot pogody do zapisu z dniem albo None (brak sieci, data poza zasięgiem prognozy)."""
    if date > today + dt.timedelta(days=FORECAST_MAX_AHEAD_DAYS):
        return None
    try:
        daily = (await fetch_daily(date, date, today)).get(date)
        current = None
        if date == today:
            data = await _get(FORECAST_URL, {**_base_params(), "current": ",".join(CURRENT_VARS)})
            current = {k: data["current"].get(k) for k in ["time", *CURRENT_VARS]}
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("Pogoda niedostępna dla %s: %s", date, e)
        return None
    if daily is None:
        return None
    return {"source": "open-meteo", "location": LOCATION["name"], "daily": daily, "current": current}


async def backfill(session, today: dt.date, *, dry_run: bool) -> int:
    """Uzupełnia pogodę dla dni, które jej nie mają (np. z importu). Zwraca liczbę uzupełnionych dni."""
    from app.models import Day, utcnow

    days = session.scalars(select(Day).where(Day.weather_api.is_(None), Day.date <= today).order_by(Day.date)).all()
    if not days:
        return 0
    daily = await fetch_daily(days[0].date, days[-1].date, today)
    filled = 0
    for day in days:
        if (d := daily.get(day.date)) is not None:
            day.weather_api = {"source": "open-meteo", "location": LOCATION["name"], "daily": d, "current": None}
            day.weather_fetched_at = utcnow()
            filled += 1
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return filled


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    ap = argparse.ArgumentParser(description="Pogoda z Open-Meteo.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="uzupełnij pogodę dla dni bez niej")
    b.add_argument("--dry-run", action="store_true", help="pobierz i policz, ale nie zapisuj")
    args = ap.parse_args(argv)

    with SessionLocal() as session:
        n = asyncio.run(backfill(session, dt.date.today(), dry_run=args.dry_run))
    print(f"{'[dry-run] ' if args.dry_run else ''}uzupełniono pogodę dla {n} dni", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
