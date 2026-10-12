"""Serwis www dziennika.

    uv run uvicorn app.main:app --reload            # lokalnie
    uv run uvicorn app.main:app --host 0.0.0.0      # w sieci domowej
"""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import practice, stats, weather
from app.db import SessionLocal
from app.forms import CURRENT_HABITS, POMODORO_MAX, habit_label, habit_order, habits_for_form, parse_day_form, save_manual_day
from app.models import Day, PracticeCategory, PracticeItem

app = FastAPI(title="Dziennik")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["habit_label"] = habit_label
templates.env.globals["weather_desc"] = weather.describe
# Liczba albo „–” (snapshot pogody może nie mieć któregoś pola).
templates.env.filters["num"] = lambda v, digits=0: f"{v:.{digits}f}" if isinstance(v, int | float) else "–"

WEEKDAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
templates.env.filters["weekday"] = lambda d: WEEKDAYS_PL[d.weekday()]
templates.env.filters["weekday_short"] = lambda d: WEEKDAYS_PL[d.weekday()][:3]
# W bazie UTC bez strefy → czas lokalny serwera do wyświetlenia.
templates.env.filters["local"] = lambda t: t.replace(tzinfo=dt.UTC).astimezone()

RECENT_DAYS = 7


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def today() -> dt.date:
    return dt.date.today()


def _day(session: Session, date: dt.date) -> Day | None:
    return session.scalar(select(Day).where(Day.date == date))


def _stats_data(days: list[Day], period: str) -> dict:
    """Dane do wykresów; nawyki podzielone na aktualne (domyślnie widoczne) i dawne (z poprzednich templatów)."""
    habits = stats.habit_rates(days, period)
    names = sorted(habits["series"], key=habit_order)
    habits["current"] = [h for h in names if h in CURRENT_HABITS]
    habits["legacy"] = [h for h in names if h not in CURRENT_HABITS]
    return {"habits": habits, "activity": stats.activity(days, period), "bp": stats.blood_pressure(days)}


def _render_day(request: Request, session: Session, date: dt.date, *, errors=(), form=None, saved=False, status=200):
    day = _day(session, date)
    recent = session.scalars(
        select(Day).where(Day.date <= date, Day.date > date - dt.timedelta(days=RECENT_DAYS)).order_by(Day.date.desc())
    ).all()
    widget = None
    if date == today():  # strona główna: jedna statystyka do wyboru
        all_days = session.scalars(select(Day).order_by(Day.date)).all()
        widget = {
            "widget": {p: _stats_data(all_days, p) for p in stats.PERIODS},
            "calendar": stats.calendar(all_days, today()),
            "months": stats.MONTHS_PL,
            "periods": stats.PERIODS,
        }
    return templates.TemplateResponse(
        request,
        "day.html",
        {
            **(widget or {"widget": None}),
            "date": date,
            "today": today(),
            "day": day,
            "habits": {h.habit: h.value for h in day.habits} if day else {},
            "habit_names": habits_for_form(day),
            "practice": {c: practice.items_for_form(session, day, c) for c in PracticeCategory},
            "practice_done": {log.item_id for log in day.practice} if day else set(),
            "category_labels": practice.CATEGORY_LABELS,
            "pomodoro_max": POMODORO_MAX,
            "recent": recent,
            "errors": errors,
            "form": form,  # po błędzie walidacji: to, co wpisał użytkownik
            "saved": saved,
            "timedelta": dt.timedelta,
        },
        status_code=status,
    )


@app.get("/")
def index():
    return RedirectResponse(f"/day/{today().isoformat()}", status_code=303)


@app.get("/day/{date}", response_class=HTMLResponse)
def day_form(request: Request, date: dt.date, saved: bool = False, session: Session = Depends(get_session)):
    return _render_day(request, session, date, saved=saved)


@app.post("/day/{date}", response_class=HTMLResponse)
async def day_save(request: Request, date: dt.date, session: Session = Depends(get_session)):
    form = await request.form()
    columns, habits, errors = parse_day_form(form, habits_for_form(_day(session, date)))
    if errors:
        return _render_day(request, session, date, errors=errors, form=form, status=400)
    # Pogoda: dziś zawsze świeża (warunki w chwili zapisu), dla innych dni tylko gdy jej brak.
    existing = _day(session, date)
    snapshot = None
    if date == today() or existing is None or existing.weather_api is None:
        snapshot = await weather.snapshot(date, today())
    save_manual_day(session, date, columns, habits, practice.parse_practice_form(form), snapshot)
    return RedirectResponse(f"/day/{date.isoformat()}?saved=1", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request, session: Session = Depends(get_session)):
    days = session.scalars(select(Day).order_by(Day.date.desc())).all()
    return templates.TemplateResponse(request, "history.html", {"days": days})


@app.get("/config", response_class=HTMLResponse)
def config(request: Request, session: Session = Depends(get_session)):
    items = session.scalars(select(PracticeItem).order_by(PracticeItem.position, PracticeItem.id)).all()
    return templates.TemplateResponse(
        request,
        "config.html",
        {
            "items": {c: [i for i in items if i.category == c] for c in PracticeCategory},
            "category_labels": practice.CATEGORY_LABELS,
        },
    )


@app.post("/config/items")
def config_add(category: str = Form(), label: str = Form(), session: Session = Depends(get_session)):
    practice.add_item(session, category, label)
    return RedirectResponse("/config", status_code=303)


@app.post("/config/items/{item_id}")
def config_update(
    item_id: int,
    action: str = Form(),
    label: str = Form(""),
    session: Session = Depends(get_session),
):
    match action:
        case "rename":
            practice.update_item(session, item_id, label=label)
        case "hide" | "show":
            practice.update_item(session, item_id, active=action == "show")
        case "up" | "down":
            practice.move_item(session, item_id, -1 if action == "up" else 1)
    return RedirectResponse("/config", status_code=303)


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, period: str = "week", session: Session = Depends(get_session)):
    if period not in stats.PERIODS:
        period = "week"
    days = session.scalars(select(Day).order_by(Day.date)).all()
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "period": period,
            "periods": stats.PERIODS,
            "data": _stats_data(days, period),
            "calendar": stats.calendar(days, today()),
            "months": stats.MONTHS_PL,
            "day_count": len(days),
        },
    )
