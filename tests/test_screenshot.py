"""Zrzut dolnej części strony v8 → dane dnia (syntetyczne zrzuty, tests/helpers/synthetic.py)."""

import sys

import numpy as np
import pytest

from dziennik.parse import ROOT, load_layout, render_template
from dziennik.screenshot import AlignmentError, align, parse_screenshot
from tests.helpers.synthetic import make_screenshot

pytestmark = pytest.mark.skipif(
    not (ROOT / "data" / "_GoodNotes templates" / "Tydzien_Template_v8.pdf").exists(), reason="brak templatu v8"
)
needs_ocr = pytest.mark.skipif(sys.platform != "darwin", reason="OCR (Apple Vision) tylko na macOS")


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="retina_2x"),
        pytest.param({"px_per_pt": 1.3}, id="low_res"),
        pytest.param({"px_per_pt": 3.1, "jpeg_quality": 70}, id="hi_res_jpeg"),
        pytest.param({"px_per_pt": 2.4, "crop_pt": (30, 548, 566, 753)}, id="tight_crop"),
        pytest.param({"crop_pt": (10, 520, 585, 790)}, id="loose_crop"),
    ],
)
def test_alignment_recovers_crop_and_scale(kwargs):
    px_per_pt = kwargs.get("px_per_pt", 2.0)
    crop = kwargs.get("crop_pt", (26.0, 544.0, 569.0, 757.0))
    a = align(make_screenshot(**kwargs), load_layout("v8"))
    assert a.x0 == pytest.approx(crop[0], abs=1.0)
    assert a.y0 == pytest.approx(crop[1], abs=1.0)
    assert a.pt_per_px == pytest.approx(1 / px_per_pt, rel=0.01)
    assert a.score >= 0.8


def test_checkboxes_from_screenshot():
    r = parse_screenshot(make_screenshot(habits=("muzyka", "nie_palenie"), pomodoro=5, walks=("2000",)), ocr=False)
    d = r["data"]
    assert {k: v for k, v in d["habits"].items() if k != "suma_dnia"} == {
        "trening": False, "muzyka": True, "czytanie": False, "sen_przed_0": False, "nie_palenie": True,
    }
    assert d["pomodoro_count"] == 5
    assert (d["walks"]["1300"], d["walks"]["2000"]) == (False, True)
    assert r["low_confidence"] == []
    assert r["missing"] == ["date", "sleep_from", "sleep_hours", "sleep_to"]  # nad separatorem


@needs_ocr
def test_blood_pressure_ocr():
    r = parse_screenshot(make_screenshot(bp_morning="131 77 59"))
    assert r["data"]["bp"]["morning"] == {"sys": 131, "dia": 77, "pulse": 59}
    assert r["data"]["bp"]["evening"] == {"sys": None, "dia": None, "pulse": None}


def test_partial_screenshot_reports_missing_fields():
    # zrzut z uciętym dołem — pasek nawyków poza kadrem
    r = parse_screenshot(make_screenshot(crop_pt=(26, 544, 569, 715)), ocr=False)
    assert {f"habits.{h}" for h in ("trening", "nie_palenie")} <= set(r["missing"])
    assert "habits.trening" not in r["fields"]
    assert r["data"]["pomodoro_count"] == 3


def test_too_narrow_screenshot_is_rejected():
    with pytest.raises(AlignmentError):
        align(make_screenshot(crop_pt=(26, 544, 300, 757)), load_layout("v8"))


def _bottom_of(layout_name: str, y0: float, y1: float) -> np.ndarray:
    layout = load_layout(layout_name)
    page = render_template(layout.template_pdf, 0, 1190, 1684)
    return page[int(y0 * 2) : int(y1 * 2), 52:1130].copy()


@pytest.mark.parametrize(
    "image",
    [
        pytest.param(np.full((400, 1000, 3), 255, np.uint8), id="blank"),
        pytest.param(np.random.default_rng(0).integers(0, 255, (400, 1000, 3), dtype=np.uint8), id="noise"),
        pytest.param(_bottom_of("v7", 690, 806), id="v7_bottom"),
        pytest.param(_bottom_of("v8", 50, 250), id="v8_private_top"),
    ],
)
def test_rejects_non_matching_images(image):
    with pytest.raises(AlignmentError):
        align(image, load_layout("v8"))
