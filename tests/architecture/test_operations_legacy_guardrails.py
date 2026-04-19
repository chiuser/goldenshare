from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OPERATIONS_SERVICES_ROOT = REPO_ROOT / "src/operations/services"
SCAN_ROOTS = ("src", "tests", "scripts")


def _iter_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _iter_import_modules(file_path: Path) -> list[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_operations_services_contains_only_special_case_files() -> None:
    expected_files = {
        "src/operations/services/AGENTS.md",
        "src/operations/services/__init__.py",
        "src/operations/services/history_backfill_service.py",
        "src/operations/services/market_mood_walkforward_validation_service.py",
    }
    current_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in OPERATIONS_SERVICES_ROOT.glob("*")
        if path.is_file()
    }
    unexpected = sorted(current_files - expected_files)
    assert not unexpected, "operations/services 出现了计划外文件:\n" + "\n".join(unexpected)


def test_operations_services_imports_are_limited_to_special_cases() -> None:
    allowed_modules = {
        "src.operations.services",
        "src.operations.services.history_backfill_service",
        "src.operations.services.market_mood_walkforward_validation_service",
    }
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = REPO_ROOT / scan_root
        for file_path in _iter_python_files(root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            if rel_path.startswith("src/operations/services/"):
                continue
            for module in _iter_import_modules(file_path):
                if not (module == "src.operations.services" or module.startswith("src.operations.services.")):
                    continue
                if module not in allowed_modules:
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "发现对 operations/services 已收敛模块的旧路径引用:\n" + "\n".join(sorted(violations))
