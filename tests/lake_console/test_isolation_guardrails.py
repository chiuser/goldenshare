from __future__ import annotations

from pathlib import Path


PROHIBITED_SNIPPETS = (
    "from src.ops",
    "import src.ops",
    "from src.app",
    "import src.app",
    "from frontend.src",
    "import frontend.src",
    "psql-remote.sh",
)


def test_lake_console_does_not_import_production_runtime_code():
    root = Path("lake_console")
    checked_files = [
        *root.glob("backend/**/*.py"),
        *root.glob("frontend/src/**/*.ts"),
        *root.glob("frontend/src/**/*.tsx"),
    ]

    violations: list[str] = []
    for path in checked_files:
        content = path.read_text(encoding="utf-8")
        for snippet in PROHIBITED_SNIPPETS:
            if snippet in content:
                violations.append(f"{path}: {snippet}")

    assert violations == []
