from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OPERATIONS_SERVICES_ROOT = REPO_ROOT / "src/operations/services"
OPERATIONS_RUNTIME_ROOT = REPO_ROOT / "src/operations/runtime"
OPERATIONS_SPECS_ROOT = REPO_ROOT / "src/operations/specs"
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


def test_operations_runtime_contains_only_package_init() -> None:
    expected_files: set[str] = set()
    current_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in OPERATIONS_RUNTIME_ROOT.glob("*")
        if path.is_file()
    }
    unexpected = sorted(current_files - expected_files)
    assert not unexpected, "operations/runtime 出现了计划外文件:\n" + "\n".join(unexpected)


def test_no_legacy_runtime_submodule_imports() -> None:
    forbidden_modules = {
        "src.operations.runtime",
        "src.operations.runtime.dispatcher",
        "src.operations.runtime.scheduler",
        "src.operations.runtime.worker",
    }
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = REPO_ROOT / scan_root
        for file_path in _iter_python_files(root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            for module in _iter_import_modules(file_path):
                if module in forbidden_modules:
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "发现对 operations/runtime 已删除 shim 的旧路径引用:\n" + "\n".join(sorted(violations))


def test_operations_specs_contains_only_package_init() -> None:
    expected_files: set[str] = set()
    current_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in OPERATIONS_SPECS_ROOT.glob("*")
        if path.is_file()
    }
    unexpected = sorted(current_files - expected_files)
    assert not unexpected, "operations/specs 出现了计划外文件:\n" + "\n".join(unexpected)


def test_no_legacy_specs_submodule_imports() -> None:
    forbidden_modules = {
        "src.operations.specs",
        "src.operations.specs.dataset_freshness_spec",
        "src.operations.specs.job_spec",
        "src.operations.specs.observed_dataset_registry",
        "src.operations.specs.registry",
        "src.operations.specs.workflow_spec",
    }
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = REPO_ROOT / scan_root
        for file_path in _iter_python_files(root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            for module in _iter_import_modules(file_path):
                if module in forbidden_modules:
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "发现对 operations/specs 已删除 shim 的旧路径引用:\n" + "\n".join(sorted(violations))


def test_no_legacy_dataset_status_projection_imports() -> None:
    forbidden_modules = {"src.operations.dataset_status_projection"}
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = REPO_ROOT / scan_root
        for file_path in _iter_python_files(root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            if rel_path == "src/operations/dataset_status_projection.py":
                continue
            for module in _iter_import_modules(file_path):
                if module in forbidden_modules:
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "发现对 operations/dataset_status_projection 旧路径引用:\n" + "\n".join(sorted(violations))
