"""Agregacje do wykresów: tydzień / miesiąc + kalendarz dni."""

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence

from app.models import Day

PERIODS = {"week": "Tygodnie", "month": "Miesiące"}
MONTHS_PL = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


def period_start(d: dt.date, period: str) -> dt.date:
    if period == "month":
        return d.replace(day=1)
    return d - dt.timedelta(days=d.weekday())  # poniedziałek


def _next_period(d: dt.date, period: str) -> dt.date:
    if period == "month":
        return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return d + dt.timedelta(days=7)


def period_label(start: dt.date, period: str) -> str:
    if period == "month":
        return f"{MONTHS_PL[start.month - 1]} {start.year}"
    return f"{start.strftime('%d.%m')}–{(start + dt.timedelta(days=6)).strftime('%d.%m')}"


def period_tick(start: dt.date, period: str) -> str:
    """Krótki podpis osi X (pełny zakres jest w tooltipie)."""
    if period == "month":
        return MONTHS_PL[start.month - 1]
    return start.strftime("%d.%m")


def _axis(periods: list[dt.date], period: str) -> dict:
    return {"labels": [period_label(p, period) for p in periods], "ticks": [period_tick(p, period) for p in periods]}


def _periods(days: Sequence[Day], period: str) -> list[dt.date]:
    """Wszystkie okresy od pierwszego do ostatniego dnia — także puste, żeby oś czasu była ciągła."""
    if not days:
        return []
    first = period_start(min(d.date for d in days), period)
    last = period_start(max(d.date for d in days), period)
    out, p = [], first
    while p <= last:
        out.append(p)
        p = _next_period(p, period)
    return out


def habit_rates(days: Sequence[Day], period: str) -> dict:
    """% wykonania nawyku w okresie = suma wartości / liczba dni, w których nawyk był śledzony.

    Nawyki zmieniały się między templatami, więc okres bez wpisów danego nawyku = brak punktu (None).
    """
    periods = _periods(days, period)
    totals: dict[str, dict[dt.date, list[float]]] = defaultdict(lambda: defaultdict(list))
    for day in days:
        for h in day.habits:
            totals[h.habit][period_start(day.date, period)].append(h.value)
    series = {
        habit: [round(100 * sum(v) / len(v)) if (v := by_period.get(p)) else None for p in periods]
        for habit, by_period in sorted(totals.items())
    }
    return {**_axis(periods, period), "series": series}


def activity(days: Sequence[Day], period: str) -> dict:
    """Suma pomodoro i liczba spacerów (13:00, 20:00) w okresie + liczba dni z wpisem."""
    periods = _periods(days, period)
    index = {p: i for i, p in enumerate(periods)}
    pomodoro, walk_1300, walk_2000, days_count = ([0] * len(periods) for _ in range(4))
    for day in days:
        i = index[period_start(day.date, period)]
        pomodoro[i] += day.pomodoro_count or 0
        walk_1300[i] += bool(day.walk_1300)
        walk_2000[i] += bool(day.walk_2000)
        days_count[i] += 1
    return {
        **_axis(periods, period),
        "pomodoro": pomodoro,
        "walk_1300": walk_1300,
        "walk_2000": walk_2000,
        "days": days_count,
    }


def day_score(day: Day) -> float | None:
    """Udział wykonanych nawyków w dniu (0–1) albo None, gdy dzień nie ma nawyków."""
    if not day.habits:
        return None
    return sum(h.value for h in day.habits) / len(day.habits)


def calendar(days: Sequence[Day], end: dt.date) -> list[list[dict | None]]:
    """Siatka tygodni (kolumny) × dni pon–nd (wiersze) od pierwszego wpisu do `end`.

    Komórka: {"date", "score" (0–1 | None), "level" (0 = brak wpisu, 1–4 wg score)}; None = poza zakresem.
    """
    if not days:
        return []
    by_date = {d.date: d for d in days}
    start = period_start(min(by_date), "week")
    first = min(by_date)
    weeks = []
    week_start = start
    while week_start <= end:
        week = []
        for offset in range(7):
            date = week_start + dt.timedelta(days=offset)
            if date < first or date > end:
                week.append(None)
                continue
            day = by_date.get(date)
            score = day_score(day) if day else None
            level = 0 if day is None else 1 if not score else min(4, 1 + round(score * 3))
            week.append({"date": date, "score": score, "level": level, "has_entry": day is not None})
        weeks.append(week)
        week_start += dt.timedelta(days=7)
    return weeks


def blood_pressure(days: Sequence[Day]) -> dict:
    """Pomiary ciśnienia — tylko dni z odczytem (oś kategorii po datach, bez okresów)."""
    measured = [d for d in days if d.bp_morning_sys or d.bp_evening_sys]
    return {
        "labels": [d.date.strftime("%d.%m") for d in measured],
        "morning_sys": [d.bp_morning_sys for d in measured],
        "morning_dia": [d.bp_morning_dia for d in measured],
        "evening_sys": [d.bp_evening_sys for d in measured],
        "evening_dia": [d.bp_evening_dia for d in measured],
    }


def weather(days: Sequence[Day], period: str) -> dict:
    """Średnia temperatura maksymalna i suma opadów w okresie (z zapisanych snapshotów Open-Meteo)."""
    periods = _periods(days, period)
    index = {p: i for i, p in enumerate(periods)}
    temps: list[list[float]] = [[] for _ in periods]
    precip: list[float | None] = [None] * len(periods)
    for day in days:
        daily = (day.weather_api or {}).get("daily") or {}
        i = index[period_start(day.date, period)]
        if isinstance(t := daily.get("temperature_2m_max"), int | float):
            temps[i].append(t)
        if isinstance(p := daily.get("precipitation_sum"), int | float):
            precip[i] = round((precip[i] or 0) + p, 1)
    return {
        **_axis(periods, period),
        "temp_max": [round(sum(t) / len(t), 1) if t else None for t in temps],
        "precip": precip,
    }
