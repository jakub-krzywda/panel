"""Migracje i constrainty schematu na tymczasowej bazie."""

import datetime as dt

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Day, HabitEntry
from tests.conftest import alembic_config


def test_migration_roundtrip(tmp_path):
    url = f"sqlite:///{tmp_path / 'rt.sqlite'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert {"days", "habit_entries"} <= set(inspect(create_engine(url)).get_table_names())


def test_models_match_migrations(tmp_path):
    url = f"sqlite:///{tmp_path / 'chk.sqlite'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.check(cfg)  # rzuca, jeśli modele różnią się od migracji


def test_day_with_habits(engine):
    with Session(engine) as s:
        day = Day(date=dt.date(2026, 9, 30), source="manual",
                  habits=[HabitEntry(habit="trening", value=1), HabitEntry(habit="muzyka", value=0.5)])
        s.add(day)
        s.commit()
        assert day.updated_at is not None
        assert {(h.habit, h.value) for h in day.habits} == {("trening", 1.0), ("muzyka", 0.5)}

        s.delete(day)
        s.commit()
        assert s.query(HabitEntry).count() == 0


@pytest.mark.parametrize(
    "obj",
    [
        pytest.param(lambda: Day(date=dt.date(2026, 10, 1), source="xxx"), id="unknown_source"),
        pytest.param(lambda: Day(date=dt.date(2026, 10, 1), source="manual",
                                 habits=[HabitEntry(habit="x", value=0.7)]), id="habit_value"),
    ],
)
def test_constraints(engine, obj):
    with Session(engine) as s:
        s.add(obj())
        with pytest.raises(IntegrityError):
            s.commit()


def test_unique_date(engine):
    with Session(engine) as s:
        s.add(Day(date=dt.date(2026, 10, 1), source="manual"))
        s.commit()
        s.add(Day(date=dt.date(2026, 10, 1), source="pdf_import"))
        with pytest.raises(IntegrityError):
            s.commit()
