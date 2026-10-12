import datetime as dt
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Nazwane constrainty — w SQLite Alembic (batch mode) nie zmieni constraintu bez nazwy.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Source(StrEnum):
    MANUAL = "manual"
    PDF_IMPORT = "pdf_import"
    SCREENSHOT_IMPORT = "screenshot_import"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class Day(Base):
    """Jeden dzień dziennika. Czasy (fill_timestamp, updated_at) w UTC."""

    __tablename__ = "days"
    __table_args__ = (
        CheckConstraint(f"source IN ({', '.join(repr(s.value) for s in Source)})", name="source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(unique=True)
    source: Mapped[str] = mapped_column(String(32))
    template_version: Mapped[str | None] = mapped_column(String(16))

    sleep_from: Mapped[dt.time | None]
    sleep_to: Mapped[dt.time | None]
    sleep_hours: Mapped[float | None]

    pomodoro_count: Mapped[int | None]
    walk_1300: Mapped[bool | None]
    walk_2000: Mapped[bool | None]
    walk_1300_note: Mapped[str | None] = mapped_column(Text)
    walk_2000_note: Mapped[str | None] = mapped_column(Text)

    bp_morning_sys: Mapped[int | None]
    bp_morning_dia: Mapped[int | None]
    bp_morning_pulse: Mapped[int | None]
    bp_evening_sys: Mapped[int | None]
    bp_evening_dia: Mapped[int | None]
    bp_evening_pulse: Mapped[int | None]

    sport_text: Mapped[str | None] = mapped_column(Text)
    music_text: Mapped[str | None] = mapped_column(Text)

    # Dla importów: plik źródłowy, pewności pól, flagi inferred/unverified.
    import_meta: Mapped[dict | None] = mapped_column(JSON)

    # Kiedy dzień został wypełniony (formularz); dla importu historycznego nieznane.
    fill_timestamp: Mapped[dt.datetime | None]
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    habits: Mapped[list["HabitEntry"]] = relationship(back_populates="day", cascade="all, delete-orphan")


class HabitEntry(Base):
    """Nawyk w danym dniu. Nazwa jak na templacie (zestaw zmienia się między wersjami); 0.5 = „1/2”."""

    __tablename__ = "habit_entries"
    __table_args__ = (
        UniqueConstraint("day_id", "habit", name="uq_habit_entries_day_id_habit"),
        CheckConstraint("value IN (0, 0.5, 1)", name="value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("days.id", ondelete="CASCADE"), index=True)
    habit: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)

    day: Mapped[Day] = relationship(back_populates="habits")
