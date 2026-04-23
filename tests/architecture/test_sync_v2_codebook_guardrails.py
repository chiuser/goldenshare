from __future__ import annotations

import ast
import re
from pathlib import Path

from src.foundation.services.sync_v2.codebook import SYNC_ERROR_CODEBOOK, SYNC_REASON_CODEBOOK


REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_V2_ROOT = REPO_ROOT / "src/foundation/services/sync_v2"
DISPATCHER_PATH = REPO_ROOT / "src/ops/runtime/dispatcher.py"
WORKER_PATH = REPO_ROOT / "src/ops/runtime/worker.py"
NORMALIZER_PATH = SYNC_V2_ROOT / "normalizer.py"

ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+(?::[a-z0-9_]+)?$")


def _read_ast(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value.strip()
        return text or None
    return None


def _collect_string_literals(node: ast.AST) -> list[str]:
    value = _literal_string(node)
    if value is not None:
        return [value]
    if isinstance(node, ast.BoolOp):
        literals: list[str] = []
        for child in node.values:
            literals.extend(_collect_string_literals(child))
        return literals
    return []


def _looks_like_error_code(text: str) -> bool:
    return "_" in text and bool(ERROR_CODE_PATTERN.fullmatch(text))


def _extract_error_codes_from_file(path: Path) -> set[str]:
    module = _read_ast(path)
    codes: set[str] = set()

    for node in ast.walk(module):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg != "error_code":
                    continue
                literal = _literal_string(keyword.value)
                if literal is not None and _looks_like_error_code(literal):
                    codes.add(literal)

            call_name = _call_name(node.func)
            if call_name == "_error" and node.args:
                literal = _literal_string(node.args[0])
                if literal is not None and _looks_like_error_code(literal):
                    codes.add(literal)

        if isinstance(node, ast.Assign):
            target_names: set[str] = set()
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_names.add(target.id)
                elif isinstance(target, ast.Attribute):
                    target_names.add(target.attr)
            if not target_names.intersection({"code", "error_code"}):
                continue
            for literal in _collect_string_literals(node.value):
                if _looks_like_error_code(literal):
                    codes.add(literal)
    return codes


def _extract_reason_codes_from_normalizer(path: Path) -> set[str]:
    module = _read_ast(path)
    reason_codes: set[str] = set()

    for node in ast.walk(module):
        if isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name not in {"_increase_reason", "_with_field"}:
                continue
            for arg in node.args:
                literal = _literal_string(arg)
                if literal is not None and REASON_CODE_PATTERN.fullmatch(literal):
                    reason_codes.add(literal)
        if isinstance(node, ast.Return):
            literal = _literal_string(node.value)
            if literal is not None and REASON_CODE_PATTERN.fullmatch(literal):
                reason_codes.add(literal)
    return reason_codes


def _strip_reason_field_suffix(reason_code: str) -> str:
    return reason_code.split(":", 1)[0]


def test_sync_error_codes_in_runtime_must_exist_in_codebook() -> None:
    produced_error_codes: set[str] = set()
    for path in sorted(SYNC_V2_ROOT.rglob("*.py")):
        produced_error_codes.update(_extract_error_codes_from_file(path))
    produced_error_codes.update(_extract_error_codes_from_file(DISPATCHER_PATH))
    produced_error_codes.update(_extract_error_codes_from_file(WORKER_PATH))

    codebook_error_codes = {entry.code for entry in SYNC_ERROR_CODEBOOK}
    missing = sorted(produced_error_codes - codebook_error_codes)
    assert not missing, (
        "检测到 sync 运行链路中出现未登记的 error_code。"
        "请先补齐 src/foundation/services/sync_v2/codebook.py:\n" + "\n".join(missing)
    )


def test_sync_reason_codes_in_runtime_must_exist_in_codebook() -> None:
    produced_reason_codes = _extract_reason_codes_from_normalizer(NORMALIZER_PATH)
    produced_reason_roots = {_strip_reason_field_suffix(code) for code in produced_reason_codes}

    codebook_reason_codes = {entry.code for entry in SYNC_REASON_CODEBOOK}
    missing = sorted(produced_reason_roots - codebook_reason_codes)
    assert not missing, (
        "检测到 sync 运行链路中出现未登记的 reason_code。"
        "请先补齐 src/foundation/services/sync_v2/codebook.py:\n" + "\n".join(missing)
    )


def test_sync_codebook_codes_are_unique() -> None:
    error_codes = [entry.code for entry in SYNC_ERROR_CODEBOOK]
    reason_codes = [entry.code for entry in SYNC_REASON_CODEBOOK]
    assert len(error_codes) == len(set(error_codes)), "SYNC_ERROR_CODEBOOK 存在重复 code"
    assert len(reason_codes) == len(set(reason_codes)), "SYNC_REASON_CODEBOOK 存在重复 code"
