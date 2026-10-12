"""Połączenie z bazą SQLite. Ścieżkę można nadpisać zmienną DZIENNIK_DB_URL (np. w testach)."""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get("DZIENNIK_DB_URL", f"sqlite:///{ROOT / 'data' / 'dziennik.sqlite'}")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    # SQLite domyślnie ignoruje klucze obce.
    dbapi_conn.execute("PRAGMA foreign_keys = ON")
