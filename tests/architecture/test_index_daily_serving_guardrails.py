from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (
    "src/app",
    "src/biz",
    "src/ops",
    "src/foundation/clients",
    "src/foundation/connectors",
    "src/foundation/dao",
    "src/foundation/datasets",
    "src/foundation/ingestion",
    "src/foundation/models",
    "src/foundation/services",
    "src/foundation/serving",
)

LEGACY_MODEL_MODULE = "src.foundation.models.core.index_daily" + "_bar"
LEGACY_CLASS_NAME = "IndexDaily" + "Bar"
LEGACY_TABLE_TOKEN = "core.index_daily" + "_bar"
LEGACY_DAO_ATTR = "index_daily" + "_bar"


def _iter_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _iter_import_modules(file_path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    modules: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append((node.lineno, node.module))
    return modules


def test_runtime_code_does_not_import_legacy_index_daily_bar_model() -> None:
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        for file_path in _iter_python_files(REPO_ROOT / scan_root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            for lineno, module in _iter_import_modules(file_path):
                if module == LEGACY_MODEL_MODULE:
                    violations.append(f"{rel_path}:{lineno}: {module}")

    assert not violations, (
        "运行代码不得再导入遗留指数日线模型；当前事实表是 "
        "core_serving.index_daily_serving:\n" + "\n".join(violations)
    )


def test_runtime_code_does_not_reference_legacy_index_daily_bar_table_or_dao() -> None:
    violations: list[str] = []
    forbidden_tokens = (LEGACY_CLASS_NAME, LEGACY_TABLE_TOKEN, LEGACY_DAO_ATTR)

    for scan_root in SCAN_ROOTS:
        for file_path in _iter_python_files(REPO_ROOT / scan_root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            for lineno, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
                for token in forbidden_tokens:
                    if token in line:
                        violations.append(f"{rel_path}:{lineno}: {line.strip()}")
                        break

    assert not violations, (
        "运行代码不得再引用遗留指数日线表/DAO；当前事实表是 "
        "core_serving.index_daily_serving:\n" + "\n".join(violations)
    )
