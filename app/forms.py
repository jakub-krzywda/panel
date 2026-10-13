"""Formularz dnia: parsowanie danych z POST i zapis jako wpis ręczny."""

import datetime as dt
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Day, HabitEntry, Source, utcnow
from app.practice import set_day_practice

# Nawyki z aktualnego templatu (v8), w kolejności z paska na stronie.
CURRENT_HABITS = {
    "trening": "Trening",
    "muzyka": "Muzyka",
    "czytanie": "Czytanie",
    "sen_przed_0": "Sen przed 0:00",
    "nie_palenie": "Nie palenie",
}
# Nawyki ze starszych templatów (v2–v6) — tylko etykiety do wyświetlania historii.
LEGACY_HABITS = {
    "brak_slodyczy": "Brak słodyczy",
    "dieta": "Dieta",
    "sen_ok_1": "Sen ok. 1:00",
    "sen_przed_030": "Sen przed 0:30",
    "umiar_w_przek": "Umiar w przekąskach",
    "medytacja": "Medytacja",
}
POMODORO_MAX = 8
BP_FIELDS = {
    "bp_morning_sys": (60, 250), "bp_morning_dia": (30, 150), "bp_morning_pulse": (30, 200),
    "bp_evening_sys": (60, 250), "bp_evening_dia": (30, 150), "bp_evening_pulse": (30, 200),
}
TEXT_FIELDS = ("walk_1300_note", "walk_2000_note", "sport_text", "music_text")


def habit_label(name: str) -> str:
    return CURRENT_HABITS.get(name) or LEGACY_HABITS.get(name) or name.replace("_", " ").capitalize()


def habit_order(name: str) -> tuple[int, str]:
    """Aktualne nawyki najpierw (w kolejności z templatu), potem pozostałe alfabetycznie."""
    order = list(CURRENT_HABITS)
    return (order.index(name) if name in order else len(order), name)


def habits_for_form(day: Day | None) -> list[str]:
    """Nawyki, które dzień już ma (np. z importu starszego templatu), a dla nowego dnia — aktualne.

    Nie dokładamy aktualnych nawyków do starego dnia: zapis dałby 0 („nie zrobione”)
    zamiast braku wpisu („nie śledzone”).
    """
    if day and day.habits:
        return sorted((h.habit for h in day.habits), key=habit_order)
    return list(CURRENT_HABITS)


def _int(form: Mapping[str, str], name: str, lo: int, hi: int, errors: list[str]) -> int | None:
    raw = (form.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name}: „{raw}” to nie liczba")
        return None
    if not lo <= value <= hi:
        errors.append(f"{name}: {value} poza zakresem {lo}–{hi}")
        return None
    return value


def _time(form: Mapping[str, str], name: str, errors: list[str]) -> dt.time | None:
    raw = (form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return dt.time.fromisoformat(raw)
    except ValueError:
        errors.append(f"{name}: „{raw}” to nie godzina")
        return None


def sleep_duration(start: dt.time, end: dt.time) -> float:
    """Długość snu w godzinach, przez północ (23:30 → 7:00 = 7.5)."""
    minutes = (end.hour * 60 + end.minute - start.hour * 60 - start.minute) % (24 * 60)
    return round(minutes / 60, 2)


def parse_day_form(form: Mapping[str, str], habit_names: list[str]) -> tuple[dict, dict[str, float], list[str]]:
    """POST formularza → (kolumny dnia, nawyki, błędy). Niezaznaczony nawyk = 0."""
    errors: list[str] = []
    columns: dict = {
        "sleep_from": _time(form, "sleep_from", errors),
        "sleep_to": _time(form, "sleep_to", errors),
        "pomodoro_count": _int(form, "pomodoro_count", 0, POMODORO_MAX, errors) or 0,
        "walk_1300": "walk_1300" in form,
        "walk_2000": "walk_2000" in form,
    }
    raw_hours = (form.get("sleep_hours") or "").strip().replace(",", ".")
    if raw_hours:
        try:
            columns["sleep_hours"] = float(raw_hours)
        except ValueError:
            errors.append(f"sleep_hours: „{raw_hours}” to nie liczba")
            columns["sleep_hours"] = None
    elif columns["sleep_from"] and columns["sleep_to"]:
        columns["sleep_hours"] = sleep_duration(columns["sleep_from"], columns["sleep_to"])
    else:
        columns["sleep_hours"] = None

    for name, (lo, hi) in BP_FIELDS.items():
        columns[name] = _int(form, name, lo, hi, errors)
    for name in TEXT_FIELDS:
        columns[name] = (form.get(name) or "").strip() or None

    habits = {name: 1.0 if f"habit.{name}" in form else 0.0 for name in habit_names}
    return columns, habits, errors


def save_manual_day(
    session: Session,
    date: dt.date,
    columns: dict,
    habits: dict[str, float],
    practice: tuple[set[int], dict[str, str]] = (set(), {}),
    weather: dict | None = None,
    source: Source = Source.MANUAL,
) -> Day:
    """Zapis z formularza. Dzień staje się `manual` — kolejne importy go nie nadpiszą.

    Nawyk „1/2” z importu zostaje 0.5, jeśli checkbox nadal jest zaznaczony.
    `practice` = (id odhaczonych pozycji „co ćwiczę”, {kategoria: nowa pozycja}).
    `weather` = snapshot z Open-Meteo; None zostawia dotychczasową pogodę bez zmian.
    `source` = screenshot_import, gdy formularz był wypełniony ze zrzutu i zatwierdzony przez użytkownika.
    """
    day = session.scalar(select(Day).where(Day.date == date))
    if day is None:
        day = Day(date=date)
        session.add(day)
    previous = {h.habit: h.value for h in day.habits}

    day.source = source
    day.fill_timestamp = utcnow()
    for col, value in columns.items():
        setattr(day, col, value)
    if weather is not None:
        day.weather_api = weather
        day.weather_fetched_at = utcnow()

    day.habits.clear()
    session.flush()
    day.habits.extend(
        HabitEntry(habit=name, value=previous[name] if value and previous.get(name) == 0.5 else value)
        for name, value in habits.items()
    )
    set_day_practice(session, day, *practice)
    session.commit()
    return day
