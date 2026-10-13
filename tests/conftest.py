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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Żaden test nie idzie do sieci: domyślnie każde zapytanie o pogodę kończy się błędem połączenia."""
    import httpx

    from app import weather

    def refuse(request):
        raise httpx.ConnectError("sieć wyłączona w testach", request=request)

    monkeypatch.setattr(weather, "TRANSPORT", httpx.MockTransport(refuse))
    weather._cache.clear()


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Testy nie piszą do data/ i nie wymagają hasła (chyba że test ustawi je sam)."""
    monkeypatch.setenv("DZIENNIK_SCREENSHOTS_DIR", str(tmp_path / "screenshots"))
    monkeypatch.delenv("DZIENNIK_PASSWORD", raising=False)
    monkeypatch.delenv("DZIENNIK_USER", raising=False)
