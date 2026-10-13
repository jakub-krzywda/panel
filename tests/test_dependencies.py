"""Każdy pakiet importowany przez app/ i dziennik/ musi być bezpośrednią zależnością w pyproject.toml.

Regresja: Pillow przychodziło tylko z ocrmac (macOS), więc na RPi (Linux) aplikacja nie startowała.
"""

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# moduł → nazwa paczki, gdy się różnią
DIST = {"PIL": "pillow", "cv2": "opencv-python-headless", "yaml": "pyyaml", "multipart": "python-multipart"}
# importowane tylko w kodzie, który sam sprawdza dostępność (OCR na macOS)
OPTIONAL = {"ocrmac"}
LOCAL = {"app", "dziennik", "tests"}


def _imports() -> set[str]:
    found = set()
    for path in [*ROOT.glob("app/**/*.py"), *ROOT.glob("dziennik/**/*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found - LOCAL - set(sys.stdlib_module_names)


def test_third_party_imports_are_unconditional_dependencies():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    unconditional = {re.split(r"[<>=;\[ ]", d, maxsplit=1)[0].lower() for d in deps if ";" not in d}
    missing = {m for m in _imports() - OPTIONAL if DIST.get(m, m).lower() not in unconditional}
    assert not missing, f"brak w [project.dependencies] (albo tylko z markerem platformy): {sorted(missing)}"
