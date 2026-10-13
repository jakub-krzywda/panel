"""Ustawienia z zmiennych środowiskowych (na RPi: plik .env czytany przez systemd, poza repo).

DZIENNIK_DB_URL           baza (domyślnie data/dziennik.sqlite) — patrz app/db.py
DZIENNIK_PASSWORD         hasło HTTP Basic; puste = bez logowania (lokalnie na Macu)
DZIENNIK_USER             login HTTP Basic (domyślnie „kuba”)
DZIENNIK_SCREENSHOTS_DIR  gdzie zapisywać wgrane zrzuty (domyślnie data/screenshots)
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def auth_credentials() -> tuple[str, str] | None:
    password = os.environ.get("DZIENNIK_PASSWORD", "")
    return (os.environ.get("DZIENNIK_USER", "kuba"), password) if password else None


def screenshots_dir() -> Path:
    return Path(os.environ.get("DZIENNIK_SCREENSHOTS_DIR", ROOT / "data" / "screenshots"))
