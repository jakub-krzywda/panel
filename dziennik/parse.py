"""Parsowanie jednej strony dziennika (eksport JPG z GoodNotes) według układu templatu."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import yaml

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS_DIR = Path(__file__).parent / "layouts"

# Piksel jest "tuszem", jeśli różni się od czystego templatu w którymkolwiek kanale o więcej niż tyle.
INK_DIFF = 80
LOW_CONFIDENCE = 0.6

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Layout:
    name: str
    template_pdf: Path
    template_page: int
    checkbox_margin_pt: float
    checkbox_threshold: float
    text_ink_threshold: float
    checkboxes: dict[str, Box]
    text_fields: dict[str, Box]


def load_layout(name: str) -> Layout:
    raw = yaml.safe_load((LAYOUTS_DIR / f"{name}.yaml").read_text())
    return Layout(
        name=raw["name"],
        template_pdf=ROOT / raw["template_pdf"],
        template_page=raw["template_page"],
        checkbox_margin_pt=raw["checkbox_margin_pt"],
        checkbox_threshold=raw["checkbox_threshold"],
        text_ink_threshold=raw["text_ink_threshold"],
        checkboxes={k: tuple(v) for k, v in raw["checkboxes"].items()},
        text_fields={k: tuple(v) for k, v in raw["text_fields"].items()},
    )


@lru_cache(maxsize=8)
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


def _ink_ratio(mask: np.ndarray, box: Box, scale: float, margin: float = 0.0) -> float:
    x0, y0, x1, y1 = box
    roi = mask[int((y0 - margin) * scale) : int((y1 + margin) * scale), int((x0 - margin) * scale) : int((x1 + margin) * scale)]
    return float(roi.mean()) if roi.size else 0.0


def _confidence(ratio: float, threshold: float) -> float:
    # 0 na progu, 1 przy wartości 2x odległej od progu (lub przy zerowym tuszu).
    return round(min(1.0, abs(ratio - threshold) / threshold), 2)


def _set_nested(d: dict, dotted: str, value) -> None:
    *path, last = dotted.split(".")
    for key in path:
        d = d.setdefault(key, {})
    d[last] = value


def parse_page(image_path: Path, layout: Layout) -> dict:
    page = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
    h, w = page.shape[:2]
    template = render_template(layout.template_pdf, layout.template_page, w, h)
    scale = w / pymupdf.open(layout.template_pdf)[layout.template_page].rect.width
    mask = ink_mask(page, template)

    fields: dict[str, dict] = {}
    for name, box in layout.checkboxes.items():
        ratio = _ink_ratio(mask, box, scale, layout.checkbox_margin_pt)
        fields[name] = {
            "value": ratio >= layout.checkbox_threshold,
            "ink": round(ratio, 4),
            "confidence": _confidence(ratio, layout.checkbox_threshold),
        }
    for name, box in layout.text_fields.items():
        ratio = _ink_ratio(mask, box, scale)
        has_ink = ratio >= layout.text_ink_threshold
        fields[name] = {
            "value": None,
            "has_ink": has_ink,
            "ink": round(ratio, 4),
            "status": "needs_ocr" if has_ink else "empty",
        }

    data: dict = {}
    for name, f in fields.items():
        if not name.startswith("pomodoro."):
            _set_nested(data, name, f["value"])
    data["pomodoro_count"] = sum(f["value"] for n, f in fields.items() if n.startswith("pomodoro."))
    data["habits"]["suma_dnia"] = sum(data["habits"].values())

    return {
        "source": {"file": image_path.name, "layout": layout.name},
        "data": data,
        "fields": fields,
        "low_confidence": [n for n, f in fields.items() if f.get("confidence", 1.0) < LOW_CONFIDENCE],
    }


def draw_debug(image_path: Path, layout: Layout, result: dict, out: Path) -> None:
    """Podgląd ROI: zielone = zaznaczone, szare = puste, niebieskie = tekst do OCR, czerwone = niska pewność."""
    img = cv2.imread(str(image_path))
    scale = img.shape[1] / pymupdf.open(layout.template_pdf)[layout.template_page].rect.width
    for name, box in {**layout.checkboxes, **layout.text_fields}.items():
        f = result["fields"][name]
        margin = layout.checkbox_margin_pt if name in layout.checkboxes else 0.0
        if name in result["low_confidence"]:
            color = (0, 0, 255)
        elif f.get("value") is True:
            color = (0, 170, 0)
        elif f.get("has_ink"):
            color = (255, 120, 0)
        else:
            color = (170, 170, 170)
        x0, y0, x1, y1 = box
        p0 = (int((x0 - margin) * scale), int((y0 - margin) * scale))
        p1 = (int((x1 + margin) * scale), int((y1 + margin) * scale))
        cv2.rectangle(img, p0, p1, color, 4)
    cv2.imwrite(str(out), img)
