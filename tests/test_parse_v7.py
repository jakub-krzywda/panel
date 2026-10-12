"""Regresja parsera v7 na ręcznie zweryfikowanych stronach.

Obrazy stron i oczekiwane wyniki są prywatne (data/ w .gitignore) — bez nich testy się pomijają.
Pola tekstowe (poza datą) sprawdzamy tylko pod kątem has_ink — OCR pisma jest best effort.
"""

import json
from pathlib import Path

import pytest

from dziennik.classify import detect_layout
from dziennik.parse import ROOT, load_all_layouts, load_layout, load_page, parse_page

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
    assert result["data"]["date"] == expected["date"]
    assert result["low_confidence"] == []


@pytest.mark.parametrize("case", _cases(), ids=lambda p: p.stem)
def test_detects_v7(case: Path, layout):
    image = PAGES_DIR / json.loads(case.read_text())["file"]
    if not image.exists():
        pytest.skip(f"brak strony {image}")
    detected, _ = detect_layout(load_page(image), load_all_layouts())
    assert detected is not None and detected.name == "v7"
