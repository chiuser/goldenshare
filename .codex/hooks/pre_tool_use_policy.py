#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shlex
import sys
from typing import Any


BLOCK_EXIT_CODE = 2


def main() -> int:
    payload = _read_payload()
    tool_name = _tool_name(payload)
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else payload
    text = _flatten_text(payload)
    command = _command_text(tool_input)

    findings: list[str] = []
    findings.extend(_detect_destructive_shell(command))
    findings.extend(_detect_unbounded_or_destructive_db(command))
    findings.extend(_detect_unbounded_lake_run(command))
    findings.extend(_detect_secret_exposure(text))
    findings.extend(_detect_risky_patch(tool_name=tool_name, text=text))

    if not findings:
        return 0

    message = "\n".join(f"- {item}" for item in findings)
    sys.stderr.write(
        "Goldenshare PreToolUse hook blocked this action.\n"
        "Reason:\n"
        f"{message}\n\n"
        "Adjust the plan/command, use a bounded read-only validation path, or ask the user for explicit approval.\n"
    )
    return BLOCK_EXIT_CODE


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_stdin": raw}
    return data if isinstance(data, dict) else {"payload": data}


def _tool_name(payload: dict[str, Any]) -> str:
    for key in ("tool_name", "name", "tool", "recipient_name"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _command_text(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("cmd", "command", "script"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return ""


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    return ""


def _detect_destructive_shell(command: str) -> list[str]:
    if not command:
        return []
    compact = _compact(command)
    findings: list[str] = []

    destructive_patterns = (
        (r"\bgit\s+reset\s+--hard\b", "禁止执行 `git reset --hard`，除非用户在当前轮明确要求。"),
        (r"\bgit\s+clean\b.*(?:-[^\s]*f|--force)", "禁止执行 `git clean` 强制清理，除非用户明确要求并列出清理范围。"),
        (r"\bgit\s+checkout\s+--\b", "禁止用 `git checkout --` 回滚文件，避免覆盖用户未提交改动。"),
        (r"\brm\s+-[^\n;|&]*r[^\n;|&]*f\b", "禁止直接执行 `rm -rf`；需要先说明范围、原因和用户授权。"),
    )
    for pattern, message in destructive_patterns:
        if re.search(pattern, compact):
            findings.append(message)

    return findings


def _detect_unbounded_or_destructive_db(command: str) -> list[str]:
    if not command:
        return []
    lowered = command.lower()
    if not _looks_like_db_command(lowered):
        return []

    findings: list[str] = []
    destructive_sql = (
        " drop ",
        " truncate ",
        " delete ",
        " update ",
        " insert ",
        " alter ",
        " create ",
        " reindex ",
        " vacuum full",
    )
    normalized = f" {_compact(lowered)} "
    if any(token in normalized for token in destructive_sql):
        findings.append("数据库命令疑似包含写入/DDL/破坏性 SQL；当前仓库默认只允许经确认的只读核验。")

    if "select *" in normalized and ("limit" not in normalized or re.search(r"\blimit\s+(?:[5-9]\d{4,}|\d{6,})\b", normalized)):
        findings.append("数据库命令疑似使用无边界 `select *`；必须改为字段投影、过滤条件和小 limit。")

    if "goldenshare-prod" in normalized and "select" not in normalized:
        findings.append("生产库/生产机命令必须说明只读目标、白名单表、字段投影和验证范围。")

    return findings


def _detect_unbounded_lake_run(command: str) -> list[str]:
    if not command:
        return []
    lowered = _compact(command.lower())
    findings: list[str] = []

    heavy_keywords = (
        "sync-stk-mins",
        "stk_mins",
        "index_mins",
        "backfill",
        "bootstrap",
        "materialize",
        "prod-db export",
        "prod-raw-db",
        "duckdb_compute",
    )
    if not any(keyword in lowered for keyword in heavy_keywords):
        return []

    has_dry_run = any(flag in lowered for flag in ("--dry-run", " dry_run", "dry-run", "preview", "audit"))
    has_full_range = (
        "--all" in lowered
        or re.search(r"(?<![a-z0-9_])full(?![a-z0-9_])", lowered) is not None
        or any(flag in lowered for flag in ("全量", "全市场", "bootstrap", "backfill"))
    )
    has_range_dates = "--start-date" in lowered and "--end-date" in lowered
    has_minutes = "stk_mins" in lowered or "sync-stk-mins" in lowered or "分钟" in lowered

    if has_minutes and (has_full_range or has_range_dates) and not has_dry_run:
        findings.append("分钟线/全市场/跨日期任务必须先做性能测算与 dry-run/小样本验证，禁止直接进入全量执行。")
    if "prod-raw-db" in lowered and not has_dry_run and not _has_limit_or_partition(lowered):
        findings.append("prod-raw-db 导出必须先列白名单、字段投影、分区/批次或 dry-run，禁止无边界导出。")
    if "duckdb" in lowered and "copy" in lowered and "parquet" in lowered and not has_dry_run and has_full_range:
        findings.append("大体量 DuckDB/Parquet 写入必须先说明 scan/write 数据量、spilling、临时目录和原子替换策略。")

    return findings


def _detect_secret_exposure(text: str) -> list[str]:
    if not text:
        return []
    findings: list[str] = []
    lowered = text.lower()
    if "tushare_token" in lowered and re.search(r"tushare_token\s*=\s*['\"]?[a-z0-9]{20,}", lowered):
        findings.append("疑似把 Tushare token 写入命令或文件；token 不得进入代码、文档、日志或 metadata。")
    if re.search(r"postgres(?:ql)?://[^@\s]+:[^@\s]+@", text):
        findings.append("疑似暴露数据库连接串密码；禁止把 DB 密码写入命令、代码或文档。")
    return findings


def _detect_risky_patch(*, tool_name: str, text: str) -> list[str]:
    if not text:
        return []
    lowered_tool = tool_name.lower()
    if "apply_patch" not in lowered_tool and "*** begin patch" not in text.lower():
        return []

    findings: list[str] = []
    if re.search(r"^\*\*\* (?:Add|Update) File: .*config\.local\.toml", text, flags=re.MULTILINE):
        findings.append("禁止提交或修改真实 `config.local.toml`；请只改 example 或文档模板。")
    if re.search(r"^\+.*(?:tushare_token|postgres://|postgresql://)", text, flags=re.MULTILINE | re.IGNORECASE):
        findings.append("补丁疑似新增 token 或数据库连接串；禁止把秘密写入仓库。")
    if re.search(r"^\*\*\* (?:Add|Update) File: .*src/(?:platform|operations)/", text, flags=re.MULTILINE):
        findings.append("`src/platform` / `src/operations` 是 legacy 冻结目录；新增或修改前必须单独说明兼容清理依据。")
    return findings


def _looks_like_db_command(lowered: str) -> bool:
    indicators = (
        "psql",
        "createdb",
        "dropdb",
        "goldenshare-prod",
        "scripts/psql-remote.sh",
        "postgres://",
        "postgresql://",
        "raw_tushare.",
        "core_serving",
    )
    return any(indicator in lowered for indicator in indicators)


def _has_limit_or_partition(lowered: str) -> bool:
    return any(token in lowered for token in ("--trade-date", "--event-date", "--limit", " limit ", "where "))


def _compact(value: str) -> str:
    try:
        # Keep quoted command text recognizable while normalizing shell whitespace.
        return " ".join(shlex.split(value))
    except ValueError:
        return " ".join(value.split())


if __name__ == "__main__":
    raise SystemExit(main())
