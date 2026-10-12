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


class PracticeCategory(StrEnum):
    SPORT = "sport"
    MUSIC = "music"


def utcnow() -> dt.datetime:
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

    # Snapshot z Open-Meteo zapisany razem z dniem (app/weather.py) — nie pobierany na żywo z dashboardu.
    weather_api: Mapped[dict | None] = mapped_column(JSON)
    weather_fetched_at: Mapped[dt.datetime | None]

    # Kiedy dzień został wypełniony (formularz); dla importu historycznego nieznane.
    fill_timestamp: Mapped[dt.datetime | None]
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    habits: Mapped[list["HabitEntry"]] = relationship(back_populates="day", cascade="all, delete-orphan")
    practice: Mapped[list["PracticeLog"]] = relationship(back_populates="day", cascade="all, delete-orphan")


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


class PracticeItem(Base):
    """Pozycja „co ćwiczę” (np. „Karma Police — piano cover”). Nie kasujemy — tylko ukrywamy (active=False),
    żeby historia i przyszłe rekomendacje miały do czego się odwoływać."""

    __tablename__ = "practice_items"
    __table_args__ = (
        UniqueConstraint("category", "label", name="uq_practice_items_category_label"),
        CheckConstraint(
            f"category IN ({', '.join(repr(c.value) for c in PracticeCategory)})", name="category"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(default=True)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class PracticeLog(Base):
    """Pozycja odhaczona w danym dniu (brak wiersza = nie ćwiczone)."""

    __tablename__ = "practice_log"
    __table_args__ = (UniqueConstraint("day_id", "item_id", name="uq_practice_log_day_id_item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("days.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("practice_items.id", ondelete="RESTRICT"), index=True)

    day: Mapped[Day] = relationship(back_populates="practice")
    item: Mapped[PracticeItem] = relationship()
