from __future__ import annotations

import ast
from pathlib import Path


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


def test_platform_contains_only_package_skeleton_python_files() -> None:
    if not PLATFORM_ROOT.exists():
        return
    allowed_python_files = {
        "src/platform/__init__.py",
        "src/platform/api/__init__.py",
        "src/platform/api/v1/__init__.py",
        "src/platform/models/__init__.py",
        "src/platform/queries/__init__.py",
        "src/platform/schemas/__init__.py",
        "src/platform/services/__init__.py",
        "src/platform/web/__init__.py",
    }
    current_python_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _iter_python_files(PLATFORM_ROOT)
    }
    unexpected = sorted(current_python_files - allowed_python_files)
    assert not unexpected, "src/platform 出现了非兼容骨架 Python 文件:\n" + "\n".join(unexpected)
