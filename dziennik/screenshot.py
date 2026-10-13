"""Zrzut ekranu dolnej (parsowalnej) części strony v8 → dane dnia.

Zrzut ma nieznaną skalę i przycięcie (zoom w GoodNotes, ręczne zaznaczenie), ale bez obrotu
i perspektywy. Szukamy skali i przesunięcia dopasowaniem do wyrenderowanego templatu (multi-scale
matchTemplate), wklejamy zrzut w czystą stronę v8 i parsujemy ją tak samo jak eksport z PDF.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from dziennik.parse import Layout, load_layout, parse_image, render_template

# Fragment strony v8, w którym szukamy zrzutu (pt): z zapasem nad separatorem „DANE PARSOWALNE” (y=550)
# i do dołu strony — na wypadek, gdy zaznaczenie obejmie trochę więcej.
SEARCH_AREA_PT = (0.0, 470.0, None, None)  # None = do krawędzi strony
# Minimalna szerokość zrzutu względem obszaru parsowalnego (32–563 pt) — węższy zrzut to nie ten fragment.
MIN_WIDTH_FRACTION = 0.7
COARSE_PX_PER_PT = 1.0
FINE_PX_PER_PT = 2.0
# Syntetyczne zrzuty v8: ≥0.84; dolna część v7: 0.46. Do skalibrowania na prawdziwych zrzutach.
MIN_SCORE = 0.6
# Jednolity obraz (np. pusty) daje zdegenerowane dopasowanie 1.0 — odrzucamy go wcześniej.
MIN_CONTRAST = 8.0
PAGE_WIDTH_PX = 2182  # jak eksport GoodNotes — progi parsera są skalibrowane na tej rozdzielczości


class AlignmentError(ValueError):
    pass


@dataclass(frozen=True)
class Alignment:
    """Piksel zrzutu (u, v) ↦ punkt templatu (x0 + u * pt_per_px, y0 + v * pt_per_px)."""

    x0: float
    y0: float
    pt_per_px: float
    score: float


def _prep(gray: np.ndarray) -> np.ndarray:
    # Lekki blur: tolerancja antyaliasingu i różnic renderowania ekran vs PDF.
    return cv2.GaussianBlur(gray, (3, 3), 0)


def _reference(layout: Layout, px_per_pt: float) -> tuple[np.ndarray, float, float]:
    page_h_pt = layout.page_width_pt * 842 / 595  # A4
    w, h = round(layout.page_width_pt * px_per_pt), round(page_h_pt * px_per_pt)
    page = render_template(layout.template_pdf, layout.template_page, w, h)
    x0, y0, x1, y1 = SEARCH_AREA_PT
    x1 = layout.page_width_pt if x1 is None else x1
    y1 = page_h_pt if y1 is None else y1
    crop = page[int(y0 * px_per_pt) : int(y1 * px_per_pt), int(x0 * px_per_pt) : int(x1 * px_per_pt)]
    return _prep(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)), x0, y0


def _best_match(ref: np.ndarray, shot: np.ndarray, widths_px: np.ndarray) -> tuple[float, float, tuple[int, int]]:
    """Dla kandydatów szerokości zrzutu (w px referencji) → (score, szerokość, położenie)."""
    best = (-1.0, 0.0, (0, 0))
    for width in widths_px:
        k = width / shot.shape[1]
        resized = cv2.resize(shot, None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
        if resized.shape[0] > ref.shape[0] or resized.shape[1] > ref.shape[1] or min(resized.shape) < 8:
            continue
        res = cv2.matchTemplate(ref, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best[0]:
            best = (float(score), float(width), loc)
    return best


def align(shot_rgb: np.ndarray, layout: Layout) -> Alignment:
    shot = _prep(cv2.cvtColor(shot_rgb, cv2.COLOR_RGB2GRAY))
    if shot.std() < MIN_CONTRAST:
        raise AlignmentError("Zrzut jest pusty (jednolity obraz)")
    region_w_pt = 563.3 - 32.0

    # 1) zgrubnie: szerokość zrzutu w pt od 70% obszaru parsowalnego do pełnej szerokości strony
    ref, x0, y0 = _reference(layout, COARSE_PX_PER_PT)
    widths = np.linspace(MIN_WIDTH_FRACTION * region_w_pt, layout.page_width_pt, 60) * COARSE_PX_PER_PT
    _, width, _ = _best_match(ref, shot, widths)

    # 2) dokładnie: ±3% wokół najlepszej szerokości, w wyższej rozdzielczości
    ref, x0, y0 = _reference(layout, FINE_PX_PER_PT)
    width_pt = width / COARSE_PX_PER_PT
    widths = np.linspace(width_pt * 0.97, width_pt * 1.03, 31) * FINE_PX_PER_PT
    score, width, (lx, ly) = _best_match(ref, shot, widths)

    if score < MIN_SCORE:
        raise AlignmentError(f"Zrzut nie pasuje do dolnej części templatu {layout.name} (dopasowanie {score:.2f})")
    pt_per_px = (width / FINE_PX_PER_PT) / shot_rgb.shape[1]
    return Alignment(x0=x0 + lx / FINE_PX_PER_PT, y0=y0 + ly / FINE_PX_PER_PT, pt_per_px=pt_per_px, score=round(score, 3))


def compose_page(shot_rgb: np.ndarray, layout: Layout, a: Alignment) -> np.ndarray:
    """Czysta strona templatu w rozdzielczości eksportu z wklejonym (przeskalowanym) zrzutem."""
    page_px_per_pt = PAGE_WIDTH_PX / layout.page_width_pt
    h = round(layout.page_width_pt * 842 / 595 * page_px_per_pt)
    page = render_template(layout.template_pdf, layout.template_page, PAGE_WIDTH_PX, h).copy()

    f = a.pt_per_px * page_px_per_pt
    shot = cv2.resize(shot_rgb, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    x, y = round(a.x0 * page_px_per_pt), round(a.y0 * page_px_per_pt)
    # przycięcie do strony (zrzut może wystawać o piksel–dwa)
    sh, sw = min(shot.shape[0], h - y), min(shot.shape[1], PAGE_WIDTH_PX - x)
    page[y : y + sh, x : x + sw] = shot[:sh, :sw]
    return page


def _covered(box: tuple[float, float, float, float], a: Alignment, shot_shape: tuple[int, ...]) -> bool:
    x0, y0, x1, y1 = box
    sx1 = a.x0 + shot_shape[1] * a.pt_per_px
    sy1 = a.y0 + shot_shape[0] * a.pt_per_px
    return x0 >= a.x0 - 1 and y0 >= a.y0 - 1 and x1 <= sx1 + 1 and y1 <= sy1 + 1


def parse_screenshot(shot_rgb: np.ndarray, *, layout_name: str = "v8", ocr: bool = True) -> dict:
    """Zrzut → wynik w formacie parsera. Pola, których zrzut nie obejmuje (np. data, sen), są usuwane."""
    layout = load_layout(layout_name)
    a = align(shot_rgb, layout)
    result = parse_image(compose_page(shot_rgb, layout, a), layout, source_name="screenshot", ocr=ocr)

    boxes = {**layout.checkboxes, **layout.habit_cells, **layout.text_fields,
             **{f"bp.{k}": v for k, v in layout.bp_rows.items()}}
    outside = {name for name, box in boxes.items() if not _covered(box, a, shot_rgb.shape)}
    if any(name.startswith("bp.") for name in outside):
        outside |= {f"{row}.{c}" for row in outside if row.startswith("bp.") for c in ("sys", "dia", "pulse")}
    result["fields"] = {n: f for n, f in result["fields"].items() if n not in outside}
    result["low_confidence"] = [n for n in result["low_confidence"] if n not in outside]
    result["missing"] = sorted(outside)
    result["alignment"] = {"score": a.score, "x0": round(a.x0, 1), "y0": round(a.y0, 1), "pt_per_px": round(a.pt_per_px, 4)}
    return result
