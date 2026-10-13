"""Syntetyczne „zrzuty ekranu” dolnej części strony v8 z dorysowanym pismem."""

import cv2
import numpy as np

from dziennik.parse import load_layout, render_template

INK = (20, 90, 60)  # ciemnozielony, jak długopis w GoodNotes


def _tick(img, box, s):
    x0, y0, x1, y1 = (c * s for c in box)
    pts = np.array([[x0 + 0.15 * (x1 - x0), y0 + 0.55 * (y1 - y0)], [x0 + 0.45 * (x1 - x0), y1 - 0.1 * (y1 - y0)],
                    [x1 + 0.1 * (x1 - x0), y0 - 0.3 * (y1 - y0)]], np.int32)
    cv2.polylines(img, [pts], False, INK, max(2, round(1.2 * s)), cv2.LINE_AA)


def _text(img, text, box, s):
    x0, y0, x1, y1 = box
    scale = (y1 - y0) * s / 30
    cv2.putText(img, text, (int((x0 + 3) * s), int((y1 - 3) * s)), cv2.FONT_HERSHEY_SIMPLEX, scale, INK,
                max(2, round(1.3 * s)), cv2.LINE_AA)


def make_screenshot(
    *,
    px_per_pt: float = 2.0,
    crop_pt: tuple[float, float, float, float] = (26.0, 544.0, 569.0, 757.0),
    habits: tuple[str, ...] = ("trening", "czytanie"),
    pomodoro: int = 3,
    walks: tuple[str, ...] = ("1300",),
    bp_morning: str | None = "128 76 60",
    jpeg_quality: int | None = None,
) -> np.ndarray:
    layout = load_layout("v8")
    w = round(layout.page_width_pt * px_per_pt)
    h = round(layout.page_width_pt * 842 / 595 * px_per_pt)
    page = render_template(layout.template_pdf, layout.template_page, w, h).copy()

    for name in habits:
        _tick(page, layout.checkboxes[f"habits.{name}"], px_per_pt)
    for i in range(1, pomodoro + 1):
        _tick(page, layout.checkboxes[f"pomodoro.{i}"], px_per_pt)
    for walk in walks:
        _tick(page, layout.checkboxes[f"walks.{walk}"], px_per_pt)
    if bp_morning:
        x0, y0, x1, y1 = layout.bp_rows["morning"]
        for value, i in zip(bp_morning.split(), range(3)):
            cell_w = (x1 - x0) / 3
            _text(page, value, (x0 + i * cell_w, y0, x0 + (i + 1) * cell_w, y1), px_per_pt)

    x0, y0, x1, y1 = (round(c * px_per_pt) for c in crop_pt)
    shot = page[y0:y1, x0:x1]
    if jpeg_quality:
        ok, buf = cv2.imencode(".jpg", shot, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        shot = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    return np.ascontiguousarray(shot)
