"""Serwis www dziennika.

    uv run uvicorn app.main:app --reload            # lokalnie
    uv run uvicorn app.main:app --host 0.0.0.0      # w sieci domowej
"""

import asyncio
import base64
import datetime as dt
import logging
import secrets
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import practice, settings, stats, weather
from app.db import SessionLocal
from app.forms import CURRENT_HABITS, POMODORO_MAX, habit_label, habit_order, habits_for_form, parse_day_form, save_manual_day
from app.models import Day, PracticeCategory, PracticeItem, Source
from app.screenshot_import import ScreenshotError, decode_image, prefill, save_upload
from dziennik.screenshot import AlignmentError, parse_screenshot

app = FastAPI(title="Dziennik")
log = logging.getLogger(__name__)


def _authorized(header: str | None, user: str, password: str) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        given_user, _, given_password = base64.b64decode(header[6:]).decode().partition(":")
    except ValueError:
        return False
    return secrets.compare_digest(given_user, user) & secrets.compare_digest(given_password, password)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """HTTP Basic dla całej aplikacji, gdy ustawiono DZIENNIK_PASSWORD (na RPi w sieci domowej)."""
    creds = settings.auth_credentials()
    if creds and not _authorized(request.headers.get("authorization"), *creds):
        return Response("Wymagane logowanie.", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="Dziennik", charset="UTF-8"'})
    return await call_next(request)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# ?v=<mtime> — po zmianie pliku przeglądarka nie użyje starej wersji z cache.
templates.env.globals["static"] = lambda name: f"/static/{name}?v={int((STATIC_DIR / name).stat().st_mtime)}"
templates.env.globals["habit_label"] = habit_label
templates.env.globals["weather_desc"] = weather.describe
templates.env.globals["weather_icon"] = weather.icon
# Liczba albo „–” (snapshot pogody może nie mieć któregoś pola).
templates.env.filters["num"] = lambda v, digits=0: f"{v:.{digits}f}" if isinstance(v, int | float) else "–"

WEEKDAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
templates.env.filters["weekday"] = lambda d: WEEKDAYS_PL[d.weekday()]
templates.env.filters["weekday_short"] = lambda d: WEEKDAYS_PL[d.weekday()][:3]
# W bazie UTC bez strefy → czas lokalny serwera do wyświetlenia.
templates.env.filters["local"] = lambda t: t.replace(tzinfo=dt.UTC).astimezone()

RECENT_DAYS = 7
FORECAST_TIMEOUT_S = 3.0  # strona nie czeka dłużej na prognozę, gdy nie ma sieci


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
    data = {"period": period, "habits": habits, "activity": stats.activity(days, period),
            "bp": stats.blood_pressure(days, period), "weather": stats.weather(days, period)}
    if period == "week":  # linia nawyków w widoku tygodniowym ma punkty dzienne
        data["habits_daily"] = stats.habit_rates(days, "day")
    return data


async def _forecast(date: dt.date) -> dict | None:
    if date != today():
        return None
    try:
        return await asyncio.wait_for(weather.forecast(date), FORECAST_TIMEOUT_S)
    except TimeoutError:
        return None


def _render_day(
    request: Request,
    session: Session,
    date: dt.date,
    *,
    errors=(),
    form=None,
    saved=False,
    status=200,
    forecast=None,
    uncertain=frozenset(),
    imported=None,
):
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
            # kolor nawyku = jego pozycja na templacie (stały, niezależny od tego, które są wybrane)
            "habit_slots": {name: i for i, name in enumerate(CURRENT_HABITS)},
            "habit_labels": {name: habit_label(name) for name in CURRENT_HABITS},
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
            "forecast": forecast,
            "uncertain": uncertain,  # pola wypełnione ze zrzutu do sprawdzenia
            "imported": imported,  # info o imporcie ze zrzutu (dopasowanie, brakujące pola)
        },
        status_code=status,
    )


@app.get("/")
def index():
    return RedirectResponse(f"/day/{today().isoformat()}", status_code=303)


@app.get("/day/{date}", response_class=HTMLResponse)
async def day_form(request: Request, date: dt.date, saved: bool = False, session: Session = Depends(get_session)):
    return _render_day(request, session, date, saved=saved, forecast=await _forecast(date))


@app.post("/day/{date}/screenshot", response_class=HTMLResponse)
async def day_screenshot(
    request: Request, date: dt.date, file: UploadFile = File(), session: Session = Depends(get_session)
):
    """Zrzut dolnej części strony v8 → formularz wypełniony do sprawdzenia. Nic nie jest zapisywane."""
    forecast = await _forecast(date)
    data = await file.read()
    if saved_to := save_upload(data, date, settings.screenshots_dir()):
        log.info("Zapisano zrzut %s", saved_to)
    try:
        image = decode_image(data)
        result = await run_in_threadpool(parse_screenshot, image)  # dopasowanie + OCR trwają 1–2 s
    except (ScreenshotError, AlignmentError) as e:
        return _render_day(request, session, date, errors=[str(e)], forecast=forecast, status=400)
    day = _day(session, date)
    items = {c.value: practice.items_for_form(session, day, c) for c in PracticeCategory}
    form, uncertain = prefill(result, day, items)
    imported = {
        "score": result["alignment"]["score"],
        "missing": [m for m in result["missing"] if not m.startswith(("date", "sleep"))],
        "ocr": result.get("ocr", False),
    }
    return _render_day(request, session, date, form=form, forecast=forecast, uncertain=uncertain, imported=imported)


@app.post("/day/{date}", response_class=HTMLResponse)
async def day_save(request: Request, date: dt.date, session: Session = Depends(get_session)):
    form = await request.form()
    columns, habits, errors = parse_day_form(form, habits_for_form(_day(session, date)))
    if errors:
        return _render_day(request, session, date, errors=errors, form=form, forecast=await _forecast(date), status=400)
    # Pogoda: dziś zawsze świeża (warunki w chwili zapisu), dla innych dni tylko gdy jej brak.
    existing = _day(session, date)
    snapshot = None
    if date == today() or existing is None or existing.weather_api is None:
        snapshot = await weather.snapshot(date, today())
    source = Source.SCREENSHOT_IMPORT if form.get("_source") == Source.SCREENSHOT_IMPORT else Source.MANUAL
    save_manual_day(session, date, columns, habits, practice.parse_practice_form(form), snapshot, source)
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
    data = _stats_data(days, period)
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "period": period,
            "periods": stats.PERIODS,
            "data": data,
            "weekly": stats.weekly_summary(days, CURRENT_HABITS) if period == "week" else None,
            "this_week": stats.period_start(today(), "week"),
            "habit_slots": {name: i for i, name in enumerate(CURRENT_HABITS)},
            "habit_labels": {name: habit_label(name) for name in data["habits"]["current"] + data["habits"]["legacy"]},
            "calendar": stats.calendar(days, today()),
            "months": stats.MONTHS_PL,
            "day_count": len(days),
        },
    )
