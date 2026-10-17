"""Fingerprint the supplement's real local imports, without importing them."""

import ast
import hashlib
from pathlib import Path

from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

PROJECT = Path(__file__).resolve().parents[4]
ROOT_MODULES = (
    "orchestrator.defs.bootstrap.moneyflow_history_supplement",
    "orchestrator.defs.bootstrap.moneyflow_history_source",
    "orchestrator.defs.bootstrap.daily_basic_event_instance",
    "orchestrator.moneyflow_continuation.state",
)


def _require(condition, reason):
    if not condition:
        raise MoneyflowContractError("supplement_code_" + reason)


def _module_path(base, name):
    candidate = base.joinpath(*name.split("."))
    leaf = candidate.with_suffix(".py")
    return leaf if leaf.is_file() else candidate / "__init__.py"


def dependency_paths(project):
    """Include complete shared modules and every executing package initializer."""
    base = project / "src"
    pending = [_module_path(base, module) for module in ROOT_MODULES]
    visited = set()
    size = 0
    while pending:
        path = pending.pop()
        _require(path.is_relative_to(base), "path")
        _require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink")
        _require(path.is_file(), "dependency_missing")
        if path in visited:
            continue
        visited.add(path)
        _require(len(visited) <= 150, "dependency_limit")
        _require(path.stat().st_size <= 2 * 1024**2, "file_size")
        size += path.stat().st_size
        _require(size <= 16 * 1024**2, "total_size")
        for parent in path.parents:
            if parent == base:
                break
            initializer = parent / "__init__.py"
            if initializer.is_file():
                pending.append(initializer)
        for node in ast.walk(ast.parse(path.read_bytes())):
            if isinstance(node, ast.Import):
                modules = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                _require(node.level == 0, "relative_import_needs_audit")
                module = node.module or ""
                modules = [module]
                if module == "orchestrator" or module.startswith("orchestrator."):
                    _require(_module_path(base, module).is_file(), "dependency_missing")
                    modules += [
                        module + "." + n.name
                        for n in node.names
                        if _module_path(base, module + "." + n.name).is_file()
                    ]
            else:
                continue
            for module in modules:
                if module == "orchestrator" or module.startswith("orchestrator."):
                    pending.append(_module_path(base, module))
    return sorted(visited)


def supplement_code_identity():
    paths = {str(path.relative_to(PROJECT)): path for path in dependency_paths(PROJECT)}
    paths.update(
        {
            name: PROJECT / name
            for name in (
                "pyproject.toml",
                "uv.lock",
                "src/orchestrator/seeds/market/major_indices.cn_a.csv",
            )
        }
    )
    paths["repo:scripts/psql-remote.sh"] = PROJECT.parents[1] / "scripts/psql-remote.sh"
    result, size = {}, 0
    for name, path in sorted(paths.items()):
        _require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink")
        _require(path.is_file() and path.stat().st_size <= 2 * 1024**2, "file_size")
        size += path.stat().st_size
        _require(size <= 16 * 1024**2, "total_size")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
