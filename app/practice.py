"""Pozycje „co ćwiczę”: lista w configu + odhaczanie w formularzu dnia.

Nowa pozycja wpisana w formularzu trafia na listę jako aktywna i pojawia się w kolejnych dniach,
dopóki nie zostanie ukryta w /config.
"""

from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Day, PracticeCategory, PracticeItem, PracticeLog

CATEGORY_LABELS = {PracticeCategory.SPORT: "Sport", PracticeCategory.MUSIC: "Muzyka"}
MAX_LABEL = 200


def items_for_form(session: Session, day: Day | None, category: str) -> list[PracticeItem]:
    """Aktywne pozycje kategorii + ukryte, które ten dzień ma odhaczone (żeby nie zginęły przy zapisie)."""
    logged = {log.item_id for log in day.practice} if day else set()
    items = session.scalars(
        select(PracticeItem).where(PracticeItem.category == category).order_by(PracticeItem.position, PracticeItem.id)
    ).all()
    return [i for i in items if i.active or i.id in logged]


def parse_practice_form(form: Mapping[str, str]) -> tuple[set[int], dict[str, str]]:
    """POST → (id odhaczonych pozycji, {kategoria: nowa pozycja})."""
    checked = {int(key.split(".", 1)[1]) for key in form if key.startswith("practice.") and key.split(".", 1)[1].isdigit()}
    new = {}
    for category in PracticeCategory:
        label = " ".join((form.get(f"practice_new.{category.value}") or "").split())[:MAX_LABEL]
        if label:
            new[category.value] = label
    return checked, new


def get_or_create_item(session: Session, category: str, label: str) -> PracticeItem:
    """Istniejąca pozycja (ukryta zostaje przywrócona) albo nowa na końcu listy."""
    item = session.scalar(select(PracticeItem).where(PracticeItem.category == category, PracticeItem.label == label))
    if item is None:
        last = session.scalar(select(func.max(PracticeItem.position)).where(PracticeItem.category == category))
        item = PracticeItem(category=category, label=label, position=(last or 0) + 1)
        session.add(item)
        session.flush()
    item.active = True
    return item


def set_day_practice(session: Session, day: Day, checked: set[int], new: dict[str, str]) -> None:
    item_ids = set(session.scalars(select(PracticeItem.id).where(PracticeItem.id.in_(checked))))
    item_ids |= {get_or_create_item(session, category, label).id for category, label in new.items()}
    day.practice.clear()
    session.flush()
    day.practice.extend(PracticeLog(item_id=item_id) for item_id in sorted(item_ids))


# --- config ---

def add_item(session: Session, category: str, label: str) -> None:
    label = " ".join(label.split())[:MAX_LABEL]
    if label and category in PracticeCategory._value2member_map_:
        get_or_create_item(session, category, label)
        session.commit()


def update_item(session: Session, item_id: int, *, label: str | None = None, active: bool | None = None) -> None:
    item = session.get(PracticeItem, item_id)
    if item is None:
        return
    if label is not None:
        label = " ".join(label.split())[:MAX_LABEL]
        clash = session.scalar(
            select(PracticeItem).where(PracticeItem.category == item.category, PracticeItem.label == label, PracticeItem.id != item.id)
        )
        if label and clash is None:
            item.label = label
    if active is not None:
        item.active = active
    session.commit()


def move_item(session: Session, item_id: int, direction: int) -> None:
    """Zamiana miejscami z sąsiadem w tej samej kategorii (direction: -1 w górę, +1 w dół)."""
    item = session.get(PracticeItem, item_id)
    if item is None:
        return
    items = session.scalars(
        select(PracticeItem).where(PracticeItem.category == item.category).order_by(PracticeItem.position, PracticeItem.id)
    ).all()
    for pos, it in enumerate(items):  # normalizacja: pozycje 0..n-1
        it.position = pos
    i = items.index(item)
    j = i + direction
    if 0 <= j < len(items):
        items[i].position, items[j].position = items[j].position, items[i].position
    session.commit()
