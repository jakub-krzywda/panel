"""OCR pól odręcznych przez Apple Vision (ocrmac, tylko macOS, lokalnie) + normalizacja wyników."""

import re
import warnings
from datetime import date
from difflib import SequenceMatcher

from PIL import Image

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from ocrmac import ocrmac

WEEKDAYS = ["PONIEDZIAŁEK", "WTOREK", "ŚRODA", "CZWARTEK", "PIĄTEK", "SOBOTA", "NIEDZIELA"]

# Typowe pomyłki Apple Vision na cyfrach pisanych ręcznie.
DIGIT_FIXES = str.maketrans({"%": "9", "g": "9", "G": "9", "o": "0", "O": "0", "°": "0", "l": "1", "I": "1", "|": "1"})

BP_RANGES = {"sys": (80, 200), "dia": (40, 130), "pulse": (40, 150)}


def recognize(img: Image.Image, order: str = "y") -> list[str]:
    """Rozpoznane fragmenty tekstu: od góry do dołu (order="y") albo od lewej do prawej (order="x")."""
    res = ocrmac.OCR(img, recognition_level="accurate", language_preference=["pl-PL"]).recognize()
    # bbox: (x, y, w, h) znormalizowane, y od dołu
    key = (lambda r: r[2][0]) if order == "x" else (lambda r: -r[2][1])
    return [text for text, _, _ in sorted(res, key=key)]


def _strip_accents(s: str) -> str:
    return s.upper().translate(str.maketrans("ĄĆĘŁŃÓŚŹŻ", "ACELNOSZZ"))


def match_weekday(text: str) -> int | None:
    """Najbardziej podobny dzień tygodnia (0=pon) albo None. Tolerancyjne na pojedyncze błędy OCR."""
    t = re.sub(r"[^A-Z]", "", _strip_accents(text))
    if len(t) < 4:
        return None
    scores = [SequenceMatcher(None, t, _strip_accents(day)).ratio() for day in WEEKDAYS]
    best = max(range(7), key=scores.__getitem__)
    return best if scores[best] >= 0.6 else None


def parse_date(lines: list[str], year: int) -> tuple[date | None, int | None]:
    """Z pola DATA wyciąga (data, dzień tygodnia z napisu obok).

    Rok zawsze = `year`: w notesie jest tylko jeden rok, a OCR często myli rok (2022, 2016, 202).
    """
    found, weekday = None, None
    for line in lines:
        m = re.search(r"(\d{1,2})\s*[.,/-]\s*(\d{1,2})", line)
        if m and found is None:
            try:
                found = date(year, int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
            line = line[: m.start()]  # dzień tygodnia bywa w tej samej linii przed datą
        if weekday is None:
            weekday = match_weekday(line)
    return found, weekday


def parse_bp_row(lines: list[str]) -> list[int | None]:
    """Wiersz ciśnienia 'SYS DIA PULS' → 3 liczby (None, gdy brak / poza zakresem)."""
    tokens = re.findall(r"[\d%gGoO°lI|]{2,3}", " ".join(lines))
    nums = []
    for t in tokens:
        digits = t.translate(DIGIT_FIXES)
        if digits.isdigit():
            nums.append(int(digits))
    out: list[int | None] = []
    for (key, (lo, hi)), n in zip(BP_RANGES.items(), nums + [None] * 3):
        out.append(n if n is not None and lo <= n <= hi else None)
    return out


def parse_time(lines: list[str]) -> str | None:
    """Godzina typu '~1³⁰' rozpoznana jako '~130' → '01:30'. Wynik zawsze do weryfikacji."""
    text = "".join(lines).translate(DIGIT_FIXES)
    digits = re.sub(r"\D", "", text)
    if len(digits) == 3:
        h, m = int(digits[0]), int(digits[1:])
    elif len(digits) == 4:
        h, m = int(digits[:2]), int(digits[2:])
    elif len(digits) in (1, 2):
        h, m = int(digits), 0
    else:
        return None
    return f"{h:02d}:{m:02d}" if h < 24 and m < 60 else None


def is_half(lines: list[str]) -> bool:
    return any("1/2" in l.replace(" ", "") or "½" in l for l in lines)
