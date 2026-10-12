"""CLI parsera dziennika.

Jedna strona (JSON na stdout):
    uv run python -m dziennik.cli page "data/dziennik_2026/Dziennik 2026-230.jpg" [--layout v7] [--debug-png out.png]
Cały folder (pliki wynikowe nadpisywane przy każdym uruchomieniu — idempotentne):
    uv run python -m dziennik.cli batch data/dziennik_2026 --out data/parsed
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from dziennik.classify import detect_layout
from dziennik.parse import draw_debug, load_all_layouts, load_layout, load_page, parse_page


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}."))
        else:
            out[key] = v
    return out


def cmd_page(args) -> int:
    if args.layout:
        layout = load_layout(args.layout)
    else:
        layout, scores = detect_layout(load_page(args.image), load_all_layouts())
        if layout is None:
            print(f"Nie rozpoznano układu strony: {scores}", file=sys.stderr)
            return 1
    result = parse_page(args.image, layout, default_year=args.year)
    if args.debug_png:
        draw_debug(args.image, layout, result, args.debug_png)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


def _resolve_dates(results: list[dict]) -> None:
    """Weryfikuje daty względem kolejności stron.

    Kotwice = strony, gdzie data zgadza się z dniem tygodnia. Pozostałe muszą leżeć między sąsiednimi
    kotwicami; jeśli nie leżą (albo daty brak), a między kotwicami jest dokładnie jeden dzień pasujący do
    odczytanego dnia tygodnia — przyjmujemy go jako `inferred`. Strona bez daty tuż po stronie z dniem
    pon–czw dostaje następny dzień (strony dzienne idą po kolei, weekend jest na osobnej stronie).
    Reszta trafia do weryfikacji.
    """
    def flag(r: dict) -> None:
        if "date" not in r["low_confidence"]:
            r["low_confidence"].append("date")

    def infer(r: dict, value: date, confidence: float) -> None:
        f = r["fields"]["date"]
        f["ocr_value"], f["value"] = f["value"], value.isoformat()
        f["inferred"], f["confidence"] = True, confidence
        r["data"]["date"] = f["value"]
        if "date" in r["low_confidence"]:
            r["low_confidence"].remove("date")

    anchors = [i for i, r in enumerate(results) if r["fields"]["date"].get("confidence") == 1.0]
    for i, r in enumerate(results):
        f = r["fields"]["date"]
        if i in anchors:
            continue
        if not f.get("has_ink"):
            before = results[i - 1] if i else None
            if before and before["source"]["index"] == r["source"]["index"] - 1 and before["data"].get("date"):
                d_before = date.fromisoformat(before["data"]["date"])
                if d_before.weekday() < 4:
                    infer(r, d_before + timedelta(days=1), 0.6)
            continue
        prev = next((date.fromisoformat(results[j]["data"]["date"]) for j in reversed(anchors) if j < i), None)
        nxt = next((date.fromisoformat(results[j]["data"]["date"]) for j in anchors if j > i), None)
        d = date.fromisoformat(f["value"]) if f["value"] else None
        fits = d is not None and (prev is None or d > prev) and (nxt is None or d < nxt)
        if fits and f["confidence"] >= 0.8:
            continue
        if prev and nxt:
            weekday = f.get("weekday_ocr")
            candidates = [prev + timedelta(days=k) for k in range(1, (nxt - prev).days)]
            candidates = [c for c in candidates if weekday is None or c.weekday() == weekday]
            if len(candidates) == 1:
                infer(r, candidates[0], 0.7)
                continue
        f["confidence"] = 0.0
        if not fits:
            f["order_violation"] = True
        flag(r)

    seen = Counter(r["data"]["date"] for r in results if r["data"].get("date"))
    for r in results:
        if r["data"].get("date") and seen[r["data"]["date"]] > 1:
            r["fields"]["date"]["duplicate"] = True
            flag(r)


def cmd_batch(args) -> int:
    layouts = load_all_layouts()
    args.out.mkdir(parents=True, exist_ok=True)
    results, skipped = [], Counter()
    images = sorted(args.folder.glob("*.jpg"))
    for i, image in enumerate(images, 1):
        layout, scores = detect_layout(load_page(image), layouts)
        if layout is None:
            skipped["dark_page" if scores.get("reason") == "dark_page" else "unknown_layout"] += 1
            continue
        print(f"[{i}/{len(images)}] {image.name} → {layout.name}", file=sys.stderr)
        result = parse_page(image, layout, default_year=args.year)
        if not any(f.get("ink", 0) > 0 for f in result["fields"].values()):
            skipped["empty_page"] += 1
            continue
        result["source"]["index"] = i
        results.append(result)

    _resolve_dates(results)

    with open(args.out / "pages.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    rows = [{"file": r["source"]["file"], "layout": r["source"]["layout"], **_flatten(r["data"]),
             "low_confidence": ";".join(r["low_confidence"])} for r in results]
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with open(args.out / "days.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)

    review = [r for r in results if r["low_confidence"]]
    print(f"Sparsowane strony: {len(results)} ({dict(Counter(r['source']['layout'] for r in results))})")
    print(f"Pominięte: {dict(skipped)}")
    print(f"Bez daty: {sum(1 for r in results if not r['data'].get('date'))}")
    print(f"Do weryfikacji: {len(review)} stron — pola: {dict(Counter(n for r in review for n in r['low_confidence']))}")
    print(f"Wyniki: {args.out / 'pages.jsonl'}, {args.out / 'days.csv'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parser stron dziennika.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("page", help="jedna strona → JSON")
    p.add_argument("image", type=Path)
    p.add_argument("--layout", help="wymuś układ (domyślnie wykrywany)")
    p.add_argument("--debug-png", type=Path, help="zapisz podgląd ROI")
    p.add_argument("--year", type=int, default=2026, help="rok, gdy data na stronie go nie ma")
    p.set_defaults(func=cmd_page)

    b = sub.add_parser("batch", help="folder JPG → pages.jsonl + days.csv")
    b.add_argument("folder", type=Path)
    b.add_argument("--out", type=Path, default=Path("data/parsed"))
    b.add_argument("--year", type=int, default=2026)
    b.set_defaults(func=cmd_batch)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
