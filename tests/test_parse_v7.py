"""Regresja parsera v7 na ręcznie zweryfikowanych stronach.

Obrazy stron i oczekiwane wyniki są prywatne (data/ w .gitignore) — bez nich testy się pomijają.
Pola tekstowe sprawdzamy tylko pod kątem has_ink, dopóki nie ma OCR.
"""

import json
from pathlib import Path

import pytest

from dziennik.parse import ROOT, load_layout, parse_page

PAGES_DIR = ROOT / "data" / "dziennik_2026"
EXPECTED_DIR = ROOT / "data" / "test_expected"


def _cases():
    return sorted(EXPECTED_DIR.glob("v7_*.json"))


@pytest.fixture(scope="module")
def layout():
    layout = load_layout("v7")
    if not layout.template_pdf.exists():
        pytest.skip(f"brak templatu {layout.template_pdf}")
    return layout


@pytest.mark.parametrize("case", _cases(), ids=lambda p: p.stem)
def test_page(case: Path, layout):
    expected = json.loads(case.read_text())
    image = PAGES_DIR / expected["file"]
    if not image.exists():
        pytest.skip(f"brak strony {image}")

    result = parse_page(image, layout)
    fields = result["fields"]

    for name, value in expected["checkboxes"].items():
        assert fields[name]["value"] is value, f"{name}: ink={fields[name]['ink']}"
    for name, has_ink in expected["has_ink"].items():
        assert fields[name]["has_ink"] is has_ink, f"{name}: ink={fields[name]['ink']}"
    assert result["data"]["pomodoro_count"] == expected["pomodoro_count"]
    assert result["low_confidence"] == []
