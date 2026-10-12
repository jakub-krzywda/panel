"""Rozpoznanie wersji templatu strony przez porównanie z wyrenderowanymi templatami."""

import cv2
import numpy as np

from dziennik.parse import Layout, render_template

# Minimalny udział linii templatu (całej strony / wiersza z nazwami nawyków) widocznych na stronie.
MIN_PAGE_COVERAGE = 0.9
MIN_LABEL_COVERAGE = 0.95
# Strony z ciemnym tłem (notatki) dają fałszywie wysokie pokrycie.
MIN_PAGE_BRIGHTNESS = 200


def _coverage(page_dark: np.ndarray, template_dark: np.ndarray) -> float:
    total = template_dark.sum()
    return float((page_dark & template_dark).sum() / total) if total else 0.0


def detect_layout(page_rgb: np.ndarray, layouts: list[Layout]) -> tuple[Layout | None, dict]:
    """Zwraca najlepiej pasujący układ (albo None) i wyniki dla wszystkich kandydatów."""
    h, w = page_rgb.shape[:2]
    gray = cv2.cvtColor(page_rgb, cv2.COLOR_RGB2GRAY)
    if gray.mean() < MIN_PAGE_BRIGHTNESS:
        return None, {"reason": "dark_page"}
    page_dark = gray < 128

    scores = {}
    for layout in layouts:
        template = render_template(layout.template_pdf, layout.template_page, w, h)
        template_dark = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY) < 128
        x0, y0, x1, y1 = (int(c * layout.scale(w)) for c in layout.label_region)
        scores[layout.name] = {
            "page": round(_coverage(page_dark, template_dark), 3),
            "labels": round(_coverage(page_dark[y0:y1, x0:x1], template_dark[y0:y1, x0:x1]), 3),
        }

    best = max(layouts, key=lambda l: (scores[l.name]["labels"], scores[l.name]["page"]))
    s = scores[best.name]
    if s["page"] < MIN_PAGE_COVERAGE or s["labels"] < MIN_LABEL_COVERAGE:
        return None, scores
    return best, scores
