from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("src/platform", "src/ops", "src/biz", "src/foundation", "src/operations")
DISALLOWED_IMPORT_PREFIXES = (
    "from src.web.",
    "import src.web.",
    "from src.services.",
    "import src.services.",
    "from src.dao.",
    "import src.dao.",
    "from src.clients.",
    "import src.clients.",
    "from src.config.",
    "import src.config.",
    "from src.models.",
    "import src.models.",
)

ALLOWED_LINE_OVERRIDES: set[tuple[str, str]] = set()


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        base = REPO_ROOT / root
        files.extend(path for path in base.rglob("*.py") if path.is_file())
    return files


def test_virtual_split_boundaries_no_legacy_web_or_models_imports() -> None:
    violations: list[str] = []
    for file_path in _iter_python_files():
        rel_path = str(file_path.relative_to(REPO_ROOT))
        for line_no, raw_line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            if any(line.startswith(prefix) for prefix in DISALLOWED_IMPORT_PREFIXES):
                if (rel_path, line) in ALLOWED_LINE_OVERRIDES:
                    continue
                violations.append(f"{rel_path}:{line_no} -> {line}")
    assert not violations, "发现违反虚拟拆仓边界的导入:\n" + "\n".join(sorted(violations))
