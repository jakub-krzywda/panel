import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event

from app.db import ROOT


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def engine(tmp_path):
    """Pusta baza po wszystkich migracjach."""
    url = f"sqlite:///{tmp_path / 'test.sqlite'}"
    command.upgrade(alembic_config(url), "head")
    eng = create_engine(url)
    event.listen(eng, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys = ON"))
    yield eng
    eng.dispose()
