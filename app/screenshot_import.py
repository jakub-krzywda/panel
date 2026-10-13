"""Import ze zrzutu ekranu → wypełniony formularz dnia (bez zapisu; użytkownik sprawdza i zapisuje)."""

import re
from difflib import SequenceMatcher

import cv2
import numpy as np

from app.models import Day, PracticeItem

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# Podobieństwo etykiety pozycji „co ćwiczę” do odczytanego tekstu, od którego zaznaczamy pozycję.
PRACTICE_MATCH = 0.8

# Pola dnia przenoszone 1:1 z wyniku parsera (klucz formularza ← ścieżka w result["data"]).
FIELD_MAP = {
    "walk_1300_note": "walks.1300_note",
    "walk_2000_note": "walks.2000_note",
    "bp_morning_sys": "bp.morning.sys", "bp_morning_dia": "bp.morning.dia", "bp_morning_pulse": "bp.morning.pulse",
    "bp_evening_sys": "bp.evening.sys", "bp_evening_dia": "bp.evening.dia", "bp_evening_pulse": "bp.evening.pulse",
}


class ScreenshotError(ValueError):
    pass


def decode_image(data: bytes) -> np.ndarray:
    if not data:
        raise ScreenshotError("Nie wybrano pliku.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ScreenshotError("Plik jest za duży (limit 15 MB).")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ScreenshotError("Nie udało się odczytać obrazu — użyj PNG albo JPG (HEIC nie jest obsługiwany).")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _get(data: dict, dotted: str):
    for key in dotted.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def match_practice(text: str | None, items: list[PracticeItem]) -> list[PracticeItem]:
    """Pozycje z listy, których nazwa występuje w odczytanym tekście (dokładnie albo prawie — OCR się myli)."""
    if not text:
        return []
    norm_text = _norm(text)
    matched = []
    for item in items:
        label = _norm(item.label)
        if not label:
            continue
        if label in norm_text:
            matched.append(item)
            continue
        # okno o długości etykiety przesuwane po tekście
        words, n = norm_text.split(), len(label.split())
        windows = [" ".join(words[i : i + n]) for i in range(max(1, len(words) - n + 1))]
        if any(SequenceMatcher(None, label, w).ratio() >= PRACTICE_MATCH for w in windows):
            matched.append(item)
    return matched


def day_to_form(day: Day | None) -> dict[str, str]:
    """Aktualne wartości dnia w formacie formularza (podstawa, na którą nakładamy dane ze zrzutu)."""
    form: dict[str, str] = {}
    if day is None:
        return form
    for col in ("sleep_from", "sleep_to"):
        if (t := getattr(day, col)) is not None:
            form[col] = t.strftime("%H:%M")
    for col in ("sleep_hours", "pomodoro_count", *FIELD_MAP, "sport_text", "music_text"):
        if (v := getattr(day, col)) is not None:
            form[col] = str(v)
    for col in ("walk_1300", "walk_2000"):
        if getattr(day, col):
            form[col] = "on"
    form.update({f"habit.{h.habit}": "on" for h in day.habits if h.value})
    form.update({f"practice.{log.item_id}": "on" for log in day.practice})
    return form


def prefill(result: dict, day: Day | None, practice_items: dict[str, list[PracticeItem]]) -> tuple[dict, set[str]]:
    """Wynik parsera zrzutu → (formularz do wyświetlenia, nazwy pól do sprawdzenia).

    Pola, których zrzut nie obejmuje (`missing`), zostają z bazy. Nawyki ze zrzutu zastępują zapisane.
    """
    form = day_to_form(day)
    fields, data = result["fields"], result["data"]
    uncertain: set[str] = set()

    for name, f in fields.items():
        if name.startswith("habits."):
            key = f"habit.{name.split('.', 1)[1]}"
            form.pop(key, None)
            if f.get("value"):
                form[key] = "on"
            if f.get("confidence", 1.0) < 0.6:
                uncertain.add(key)

    if any(n.startswith("pomodoro.") for n in fields):
        form["pomodoro_count"] = str(data.get("pomodoro_count") or 0)
        if any(n.startswith("pomodoro.") for n in result["low_confidence"]):
            uncertain.add("pomodoro_count")

    for walk in ("1300", "2000"):
        name = f"walks.{walk}"
        if name in fields:
            form.pop(f"walk_{walk}", None)
            if fields[name].get("value"):
                form[f"walk_{walk}"] = "on"

    for key, path in FIELD_MAP.items():
        if path in fields or path.rsplit(".", 1)[0] in fields:  # notatki / wiersze ciśnienia z OCR
            value = _get(data, path)
            if value not in (None, ""):
                form[key] = str(value)
                uncertain.add(key)  # OCR pisma ręcznego — zawsze do sprawdzenia
    for row in ("morning", "evening"):
        if fields.get(f"bp.{row}", {}).get("has_ink") and None in (_get(data, f"bp.{row}.{c}") for c in ("sys", "dia", "pulse")):
            uncertain |= {f"bp_{row}_{c}" for c in ("sys", "dia", "pulse")}

    for category, note in (("sport", "sport_text"), ("music", "music_text")):
        text = _get(data, note)
        if not text:
            continue
        for item in match_practice(text, practice_items.get(category, [])):
            form[f"practice.{item.id}"] = "on"
            uncertain.add(f"practice.{item.id}")
        if not form.get(note):  # odczytany tekst do notatki tylko, gdy notatka jest pusta
            form[note] = text
            uncertain.add(note)

    form["_source"] = "screenshot_import"
    return form, uncertain
