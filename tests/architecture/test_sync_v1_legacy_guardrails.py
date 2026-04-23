from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("src", "tests", "scripts")
LEGACY_SYNC_ROOT = REPO_ROOT / "src/foundation/services/sync"


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


def _is_legacy_sync_module(module: str) -> bool:
    return module == "src.foundation.services.sync" or module.startswith("src.foundation.services.sync.")


def test_no_runtime_imports_from_sync_v1_legacy_package() -> None:
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = REPO_ROOT / scan_root
        for file_path in _iter_python_files(root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            if rel_path.startswith("src/foundation/services/sync/"):
                continue
            for module in _iter_import_modules(file_path):
                if _is_legacy_sync_module(module):
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "运行代码/测试代码仍依赖 legacy src.foundation.services.sync 路径:\n" + "\n".join(
        sorted(violations)
    )


def test_sync_v1_legacy_package_contains_no_python_files() -> None:
    if not LEGACY_SYNC_ROOT.exists():
        return
    current_python_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _iter_python_files(LEGACY_SYNC_ROOT)
    }
    assert not current_python_files, "src/foundation/services/sync 不应存在 Python 源文件:\n" + "\n".join(
        sorted(current_python_files)
    )
