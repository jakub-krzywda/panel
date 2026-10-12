"""Import wyników parsera (pages.jsonl) do bazy.

    uv run python -m app.importer data/parsed/pages.jsonl

Upsert po dacie, idempotentny: dzień z importu jest nadpisywany w całości (razem z nawykami),
dzień wpisany ręcznie (source=manual) nigdy nie jest ruszany.
"""

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Day, HabitEntry, Source

# Kolumny dnia ← ścieżki w result["data"]. Godzin snu celowo brak: OCR ma ~40% trafności,
# surowy odczyt zostaje w import_meta.
COLUMNS = {
    "pomodoro_count": "pomodoro_count",
    "walk_1300": "walks.1300",
    "walk_2000": "walks.2000",
    "walk_1300_note": "walks.1300_note",
    "walk_2000_note": "walks.2000_note",
    "bp_morning_sys": "bp.morning.sys",
    "bp_morning_dia": "bp.morning.dia",
    "bp_morning_pulse": "bp.morning.pulse",
    "bp_evening_sys": "bp.evening.sys",
    "bp_evening_dia": "bp.evening.dia",
    "bp_evening_pulse": "bp.evening.pulse",
    "sport_text": "sport_text",
    "music_text": "music_text",
}


def _get(data: dict, dotted: str):
    for key in dotted.split("."):
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def day_values(result: dict) -> tuple[dt.date, dict, dict[str, float], dict]:
    """Wynik parsera strony → (data, kolumny dnia, nawyki, import_meta)."""
    data, fields = result["data"], result["fields"]
    day = dt.date.fromisoformat(data["date"])
    columns = {col: _get(data, path) for col, path in COLUMNS.items()}

    habits = {}
    for name, done in data.get("habits", {}).items():
        if name == "suma_dnia":
            continue
        partial = fields.get(f"habits.{name}", {}).get("partial", False)
        habits[name] = 0.5 if done and partial else float(bool(done))

    date_field = fields.get("date", {})
    meta = {
        "file": result["source"]["file"],
        "low_confidence": result["low_confidence"],
        "date": {k: date_field[k] for k in ("confidence", "inferred", "ocr_value") if k in date_field},
        "unverified": sorted(n for n, f in fields.items() if f.get("unverified")),
        "sleep_ocr": {n: fields[n].get("ocr") for n in ("sleep_from", "sleep_to") if fields.get(n, {}).get("ocr")},
    }
    return day, columns, habits, meta


def import_results(session: Session, results: Iterable[dict]) -> Counter:
    stats: Counter = Counter()
    seen: set[dt.date] = set()
    for result in results:
        if not result["data"].get("date"):
            stats["skipped_no_date"] += 1
            continue
        date, columns, habits, meta = day_values(result)
        if date in seen:
            stats["skipped_duplicate_in_input"] += 1
            continue
        seen.add(date)

        day = session.scalar(select(Day).where(Day.date == date))
        if day is not None and day.source == Source.MANUAL:
            stats["skipped_manual"] += 1
            continue
        if day is None:
            day = Day(date=date)
            session.add(day)
            stats["inserted"] += 1
        else:
            stats["updated"] += 1

        day.source = Source.PDF_IMPORT
        day.template_version = result["source"]["layout"]
        for col, value in columns.items():
            setattr(day, col, value)
        day.import_meta = meta
        # Zastąp nawyki w całości — po flush, żeby nie złamać UNIQUE(day_id, habit).
        day.habits.clear()
        session.flush()
        day.habits.extend(HabitEntry(habit=h, value=v) for h, v in habits.items())
    session.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import pages.jsonl z parsera do bazy.")
    ap.add_argument("jsonl", type=Path)
    args = ap.parse_args(argv)

    with args.jsonl.open() as f:
        results = [json.loads(line) for line in f if line.strip()]
    with SessionLocal() as session:
        stats = import_results(session, results)
    print(dict(stats), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
