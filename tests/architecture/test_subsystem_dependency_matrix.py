from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WhitelistEntry:
    reason: str
    allowed_modules: tuple[str, ...]


@dataclass(frozen=True)
class DependencyRule:
    name: str
    source_root: str
    banned_prefixes: tuple[str, ...]
    whitelist: dict[str, WhitelistEntry]


def _wl(reason: str, *allowed_modules: str) -> WhitelistEntry:
    return WhitelistEntry(reason=reason, allowed_modules=tuple(sorted(set(allowed_modules))))


FOUNDATION_WHITELIST: dict[str, WhitelistEntry] = {
}

OPERATIONS_WHITELIST: dict[str, WhitelistEntry] = {
}


RULES = (
    DependencyRule(
        name="foundation_no_upper",
        source_root="src/foundation",
        banned_prefixes=("src.ops", "src.operations", "src.biz", "src.platform", "src.app"),
        whitelist=FOUNDATION_WHITELIST,
    ),
    DependencyRule(
        name="ops_no_biz",
        source_root="src/ops",
        banned_prefixes=("src.biz",),
        whitelist={},
    ),
    DependencyRule(
        name="operations_no_biz",
        source_root="src/operations",
        banned_prefixes=("src.biz",),
        whitelist=OPERATIONS_WHITELIST,
    ),
    DependencyRule(
        name="biz_no_ops_or_operations",
        source_root="src/biz",
        banned_prefixes=("src.ops", "src.operations"),
        whitelist={},
    ),
)


def _iter_python_files(source_root: str) -> list[Path]:
    root = REPO_ROOT / source_root
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _iter_import_modules(file_path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    modules: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append((node.lineno, node.module))
    return modules


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _is_banned_module(module: str, banned_prefixes: tuple[str, ...]) -> bool:
    return any(_matches_prefix(module, prefix) for prefix in banned_prefixes)


def _validate_rule_config(rule: DependencyRule) -> list[str]:
    errors: list[str] = []
    for file_path, entry in rule.whitelist.items():
        if "*" in file_path or file_path.endswith("/"):
            errors.append(f"{rule.name}: 白名单必须按文件粒度，禁止目录/通配符: {file_path}")
        if not file_path.startswith(f"{rule.source_root}/"):
            errors.append(f"{rule.name}: 白名单文件不在规则作用域内: {file_path}")
        if not file_path.endswith(".py"):
            errors.append(f"{rule.name}: 白名单仅允许 Python 文件: {file_path}")
        if not entry.reason.strip():
            errors.append(f"{rule.name}: 白名单缺少原因说明: {file_path}")
        if not entry.allowed_modules:
            errors.append(f"{rule.name}: 白名单缺少允许模块列表: {file_path}")
        for module in entry.allowed_modules:
            if not _is_banned_module(module, rule.banned_prefixes):
                errors.append(f"{rule.name}: 白名单模块不属于本规则禁用集合: {file_path} -> {module}")
    return errors


def _scan_rule(rule: DependencyRule) -> list[str]:
    violations: list[str] = []
    seen_modules = {path: set() for path in rule.whitelist}

    for file_path in _iter_python_files(rule.source_root):
        rel_path = file_path.relative_to(REPO_ROOT).as_posix()
        for line_no, module in _iter_import_modules(file_path):
            if not _is_banned_module(module, rule.banned_prefixes):
                continue
            whitelist_entry = rule.whitelist.get(rel_path)
            if whitelist_entry is None:
                violations.append(f"{rule.name}: {rel_path}:{line_no} -> {module}")
                continue
            if module not in whitelist_entry.allowed_modules:
                violations.append(f"{rule.name}: {rel_path}:{line_no} -> {module} (未在白名单允许模块中)")
                continue
            seen_modules[rel_path].add(module)

    for path, entry in rule.whitelist.items():
        abs_path = REPO_ROOT / path
        if not abs_path.exists():
            violations.append(f"{rule.name}: 白名单文件不存在: {path}")
            continue
        missing_modules = sorted(set(entry.allowed_modules) - seen_modules[path])
        if missing_modules:
            violations.append(f"{rule.name}: 白名单模块已不存在，请清理 {path}: {missing_modules}")

    return violations


def test_subsystem_dependency_matrix_rule_config_is_valid() -> None:
    errors: list[str] = []
    for rule in RULES:
        errors.extend(_validate_rule_config(rule))
    assert not errors, "依赖矩阵白名单配置错误:\n" + "\n".join(sorted(errors))


def test_subsystem_dependency_matrix() -> None:
    violations: list[str] = []
    for rule in RULES:
        violations.extend(_scan_rule(rule))
    assert not violations, "发现违反子系统依赖矩阵的导入:\n" + "\n".join(sorted(violations))
