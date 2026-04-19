from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OPERATIONS_SERVICES_ROOT = REPO_ROOT / "src/operations/services"
OPERATIONS_RUNTIME_ROOT = REPO_ROOT / "src/operations/runtime"
OPERATIONS_SPECS_ROOT = REPO_ROOT / "src/operations/specs"
OPERATIONS_ROOT = REPO_ROOT / "src/operations"
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
    }
    current_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in OPERATIONS_SERVICES_ROOT.glob("*")
        if path.is_file()
    }
    unexpected = sorted(current_files - expected_files)
    assert not unexpected, "operations/services 出现了计划外文件:\n" + "\n".join(unexpected)


def test_operations_root_contains_no_python_files() -> None:
    if not OPERATIONS_ROOT.exists():
        return
    current_python_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _iter_python_files(OPERATIONS_ROOT)
    }
    expected = set()
    unexpected = sorted(current_python_files - expected)
    assert not unexpected, "operations 根目录不应出现 Python 文件:\n" + "\n".join(unexpected)


def test_no_legacy_operations_services_imports() -> None:
    forbidden_prefixes = ("src.operations.services",)
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = REPO_ROOT / scan_root
        for file_path in _iter_python_files(root):
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            if rel_path.startswith("src/operations/services/"):
                continue
            for module in _iter_import_modules(file_path):
                if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "发现对 operations/services legacy 路径的旧引用:\n" + "\n".join(sorted(violations))


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
            for module in _iter_import_modules(file_path):
                if module in forbidden_modules:
                    violations.append(f"{rel_path} -> {module}")
    assert not violations, "发现对 operations/dataset_status_projection 旧路径引用:\n" + "\n".join(sorted(violations))


def test_operations_dataset_status_projection_shim_removed() -> None:
    legacy_projection = REPO_ROOT / "src/operations/dataset_status_projection.py"
    assert not legacy_projection.exists(), "operations/dataset_status_projection.py 已删除，不应回流"
