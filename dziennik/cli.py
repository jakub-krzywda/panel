"""CLI: uv run python -m dziennik.cli STRONA.jpg [--layout v7] [--debug-png out.png]"""

import argparse
import json
import sys
from pathlib import Path

from dziennik.parse import draw_debug, load_layout, parse_page


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parsuje stronę dziennika do JSON.")
    ap.add_argument("image", type=Path)
    ap.add_argument("--layout", default="v7")
    ap.add_argument("--debug-png", type=Path, help="zapisz podgląd ROI")
    args = ap.parse_args(argv)

    layout = load_layout(args.layout)
    result = parse_page(args.image, layout)
    if args.debug_png:
        draw_debug(args.image, layout, result, args.debug_png)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
