"""Parsowanie jednej strony dziennika (eksport JPG z GoodNotes) według układu templatu."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS_DIR = Path(__file__).parent / "layouts"

# Piksel jest "tuszem", jeśli różni się od czystego templatu w którymkolwiek kanale o więcej niż tyle.
INK_DIFF = 80
LOW_CONFIDENCE = 0.6
# Pola, które OCR-ujemy jako tekst (best effort, bez walidacji).
FREE_TEXT_FIELDS = ("walks.1300_note", "walks.2000_note", "walks.note", "sport_text", "music_text")

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Layout:
    name: str
    template_pdf: Path
    template_page: int
    page_width_pt: float
    label_region: Box
    checkbox_margin_pt: float
    checkbox_threshold: float
    cell_threshold: float
    text_ink_threshold: float
    checkboxes: dict[str, Box]
    habit_cells: dict[str, Box]
    text_fields: dict[str, Box]
    bp_rows: dict[str, Box]

    def scale(self, image_width: int) -> float:
        return image_width / self.page_width_pt


def load_layout(name: str) -> Layout:
    raw = yaml.safe_load((LAYOUTS_DIR / f"{name}.yaml").read_text())
    pdf = ROOT / raw["template_pdf"]
    boxes = lambda key: {k: tuple(v) for k, v in (raw.get(key) or {}).items()}  # noqa: E731
    return Layout(
        name=raw["name"],
        template_pdf=pdf,
        template_page=raw["template_page"],
        page_width_pt=pymupdf.open(pdf)[raw["template_page"]].rect.width,
        label_region=tuple(raw["label_region"]),
        checkbox_margin_pt=raw["checkbox_margin_pt"],
        checkbox_threshold=raw["checkbox_threshold"],
        cell_threshold=raw["cell_threshold"],
        text_ink_threshold=raw["text_ink_threshold"],
        checkboxes=boxes("checkboxes"),
        habit_cells=boxes("habit_cells"),
        text_fields=boxes("text_fields"),
        bp_rows=boxes("bp_rows"),
    )


def load_all_layouts() -> list[Layout]:
    return [load_layout(p.stem) for p in sorted(LAYOUTS_DIR.glob("v*.yaml"))]


@lru_cache(maxsize=16)
def render_template(pdf: Path, page: int, width: int, height: int) -> np.ndarray:
    p = pymupdf.open(pdf)[page]
    pix = p.get_pixmap(matrix=pymupdf.Matrix(width / p.rect.width, height / p.rect.height))
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    return cv2.resize(img, (width, height))


def ink_mask(page_rgb: np.ndarray, template_rgb: np.ndarray) -> np.ndarray:
    """Piksele dopisane ręcznie: różne od templatu i nie leżące na liniach templatu (tolerancja antyaliasingu)."""
    diff = np.abs(page_rgb.astype(np.int16) - template_rgb.astype(np.int16)).max(axis=2) > INK_DIFF
    template_lines = cv2.dilate(
        (cv2.cvtColor(template_rgb, cv2.COLOR_RGB2GRAY) < 200).astype(np.uint8), np.ones((5, 5), np.uint8)
    )
    return diff & (template_lines == 0)


def _px(box: Box, scale: float, margin: float = 0.0) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return int((x0 - margin) * scale), int((y0 - margin) * scale), int((x1 + margin) * scale), int((y1 + margin) * scale)


def _ink_ratio(mask: np.ndarray, box: Box, scale: float, margin: float = 0.0) -> float:
    x0, y0, x1, y1 = _px(box, scale, margin)
    roi = mask[y0:y1, x0:x1]
    return float(roi.mean()) if roi.size else 0.0


def _confidence(ratio: float, threshold: float) -> float:
    # 0 na progu, 1 przy wartości 2x odległej od progu (lub przy zerowym tuszu).
    return round(min(1.0, abs(ratio - threshold) / threshold), 2)


def _set_nested(d: dict, dotted: str, value) -> None:
    *path, last = dotted.split(".")
    for key in path:
        d = d.setdefault(key, {})
    d[last] = value


def load_page(image_path: Path) -> np.ndarray:
    return cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)


def parse_page(image_path: Path, layout: Layout, *, default_year: int = 2026, ocr: bool = True) -> dict:
    page = load_page(image_path)
    h, w = page.shape[:2]
    scale = layout.scale(w)
    mask = ink_mask(page, render_template(layout.template_pdf, layout.template_page, w, h))
    pil = Image.fromarray(page)

    def read(box: Box, order: str = "y") -> list[str]:
        from dziennik import ocr as vision  # import leniwy: ocrmac działa tylko na macOS

        return vision.recognize(pil.crop(_px(box, scale)), order)

    fields: dict[str, dict] = {}
    for name, box in layout.checkboxes.items():
        ratio = _ink_ratio(mask, box, scale, layout.checkbox_margin_pt)
        fields[name] = {
            "value": ratio >= layout.checkbox_threshold,
            "ink": round(ratio, 4),
            "confidence": _confidence(ratio, layout.checkbox_threshold),
        }

    for name, box in layout.habit_cells.items():
        ratio = _ink_ratio(mask, box, scale)
        f = {
            "value": ratio >= layout.cell_threshold,
            "ink": round(ratio, 4),
            "confidence": _confidence(ratio, layout.cell_threshold),
        }
        if f["value"] and ocr:
            from dziennik.ocr import is_half

            lines = read(box)
            f["ocr"] = lines
            f["partial"] = is_half(lines)
        fields[name] = f

    for name, box in layout.text_fields.items():
        ratio = _ink_ratio(mask, box, scale)
        has_ink = ratio >= layout.text_ink_threshold
        fields[name] = {"value": None, "has_ink": has_ink, "ink": round(ratio, 4)}
        if has_ink and ocr:
            fields[name]["ocr"] = read(box)

    for row, box in layout.bp_rows.items():
        ratio = _ink_ratio(mask, box, scale)
        values = [None, None, None]
        if ratio >= layout.text_ink_threshold and ocr:
            from dziennik.ocr import parse_bp_row

            lines = read(box, order="x")
            values = parse_bp_row(lines)
            fields[f"bp.{row}"] = {
                "ocr": lines,
                "has_ink": True,
                "unverified": True,
                "confidence": 1.0 if None not in values else 0.0,
            }
        for key, v in zip(("sys", "dia", "pulse"), values):
            fields[f"bp.{row}.{key}"] = {"value": v}

    if ocr:
        _interpret_text(fields, default_year)

    data: dict = {}
    for name, f in fields.items():
        if "value" in f and not name.startswith("pomodoro."):
            _set_nested(data, name, f["value"])
    data["pomodoro_count"] = sum(f["value"] for n, f in fields.items() if n.startswith("pomodoro."))
    data["habits"]["suma_dnia"] = sum(
        0.5 if fields[f"habits.{k}"].get("partial") else 1 for k, v in data["habits"].items() if v
    )

    return {
        "source": {"file": image_path.name, "layout": layout.name},
        "data": data,
        "fields": fields,
        "low_confidence": [n for n, f in fields.items() if f.get("confidence", 1.0) < LOW_CONFIDENCE],
    }


def _interpret_text(fields: dict, default_year: int) -> None:
    from dziennik.ocr import parse_date, parse_time

    f = fields["date"]
    if "ocr" in f:
        d, weekday = parse_date(f["ocr"], default_year)
        f["value"] = d.isoformat() if d else None
        f["weekday_ocr"] = weekday
        # 1.0: dzień tygodnia obok zgadza się z datą; 0.8: dnia tygodnia nie odczytano;
        # 0.3: sprzeczność (pomyłka przy pisaniu albo OCR). Kolejność stron weryfikuje to dalej (cli).
        if d is None:
            f["confidence"] = 0.0
        elif weekday is None:
            f["confidence"] = 0.8
        else:
            f["confidence"] = 1.0 if weekday == d.weekday() else 0.3
    else:
        f["confidence"] = 0.0

    for name in ("sleep_from", "sleep_to"):
        if "ocr" in fields[name]:
            fields[name]["value"] = parse_time(fields[name]["ocr"])
            fields[name]["unverified"] = True

    for name in FREE_TEXT_FIELDS:
        if name in fields and "ocr" in fields[name]:
            fields[name]["value"] = " ".join(fields[name]["ocr"]) or None
            fields[name]["unverified"] = True


def draw_debug(image_path: Path, layout: Layout, result: dict, out: Path) -> None:
    """Podgląd ROI: zielone = zaznaczone, szare = puste, niebieskie = tekst, czerwone = niska pewność."""
    img = cv2.imread(str(image_path))
    scale = layout.scale(img.shape[1])
    regions = {**layout.checkboxes, **layout.habit_cells, **layout.text_fields, **{f"bp.{k}": v for k, v in layout.bp_rows.items()}}
    for name, box in regions.items():
        f = result["fields"].get(name, {})
        margin = layout.checkbox_margin_pt if name in layout.checkboxes else 0.0
        if name in result["low_confidence"]:
            color = (0, 0, 255)
        elif f.get("value") is True:
            color = (0, 170, 0)
        elif f.get("has_ink"):
            color = (255, 120, 0)
        else:
            color = (170, 170, 170)
        x0, y0, x1, y1 = _px(box, scale, margin)
        cv2.rectangle(img, (x0, y0), (x1, y1), color, 4)
    cv2.imwrite(str(out), img)
