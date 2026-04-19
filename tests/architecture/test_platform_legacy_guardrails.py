from __future__ import annotations

import ast
from pathlib import Path

from src.app.web.settings import STATIC_DIR


REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("src", "tests", "scripts")
PLATFORM_ROOT = REPO_ROOT / "src/platform"


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


def _is_platform_module(module: str) -> bool:
    return module == "src.platform" or module.startswith("src.platform.")


def test_no_runtime_imports_from_platform_legacy_package() -> None:
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = REPO_ROOT / scan_root
        for file_path in _iter_python_files(root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            if rel_path.startswith("src/platform/"):
                continue
            for module in _iter_import_modules(file_path):
                if _is_platform_module(module):
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "运行代码/测试代码仍依赖 legacy src.platform 路径:\n" + "\n".join(sorted(violations))


def test_platform_contains_no_python_files() -> None:
    if not PLATFORM_ROOT.exists():
        return
    current_python_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _iter_python_files(PLATFORM_ROOT)
    }
    assert not current_python_files, "src/platform 不应存在 Python 源文件:\n" + "\n".join(sorted(current_python_files))


def test_web_static_assets_path_is_converged_to_app_web() -> None:
    static_dir = STATIC_DIR.resolve()
    expected_static_dir = (REPO_ROOT / "src/app/web/static").resolve()
    legacy_static_dir = (REPO_ROOT / "src/platform/web/static").resolve()
    assert static_dir == expected_static_dir, f"STATIC_DIR 应指向 {expected_static_dir}, 当前为 {static_dir}"
    assert not legacy_static_dir.exists(), f"legacy 静态资源目录不应存在: {legacy_static_dir}"
