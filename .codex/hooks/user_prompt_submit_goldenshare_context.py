#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from typing import Any


def main() -> int:
    payload = _read_payload()
    prompt = _prompt_text(payload)
    reminders = _build_reminders(prompt)
    if reminders:
        sys.stdout.write("\n".join(reminders).rstrip() + "\n")
    return 0


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"prompt": raw}
    return data if isinstance(data, dict) else {"prompt": str(data)}


def _prompt_text(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return _flatten_text(payload)


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    return ""


def _build_reminders(prompt: str) -> list[str]:
    text = prompt.lower()
    if not text.strip():
        return []

    reminders: list[str] = []
    if _matches(text, GENERAL_DEV_TERMS):
        reminders.append(
            "[Goldenshare Hook] 开发前先明确：目标、依据文档、改动范围、影响面；"
            "无法确认时先停下汇报，不要直接编码。"
        )

    if _matches(text, CODEGRAPH_TERMS):
        reminders.append(
            "[Goldenshare Hook] 架构分析、重构、依赖边界、共享 contract、dispatcher/worker/service "
            "修改前必须先用 CodeGraph 做上下文与影响面分析，并在交付中说明工具和范围。"
        )

    if _matches(text, TUSHARE_TERMS):
        reminders.append(
            "[Goldenshare Hook] Tushare 相关实现必须按：当前代码 -> docs/sources/tushare/** -> "
            "tushareMcp 实测；字段要区分默认 fields、显式 fields、业务关键 fields。"
        )

    if _matches(text, LAKE_PERFORMANCE_TERMS):
        reminders.append(
            "[Goldenshare Hook] Lake/同步/导出/DuckDB/Parquet/全量任务必须先写性能测算表，"
            "覆盖对象数、分区数、请求/分页、行数、文件数、scan/write 数据量、耗时、配额、阈值和拒绝策略。"
        )

    if _matches(text, DB_TERMS):
        reminders.append(
            "[Goldenshare Hook] DB/生产库只能走本机命令行的明确只读核验路径；"
            "先列白名单表、字段投影、过滤/limit、样本量，禁止无边界全表扫描或写入。"
        )

    if _matches(text, FRONTEND_TERMS):
        reminders.append(
            "[Goldenshare Hook] 前端改动后优先做 typecheck/build；涉及页面交互、布局或数据页时，"
            "用 Browser/Chrome/Playwright 做截图、console 和 network 验证。"
        )

    return reminders


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


GENERAL_DEV_TERMS = (
    r"\bdev\b",
    r"\bimplement\b",
    r"\bfix\b",
    r"\brefactor\b",
    r"开发",
    r"实现",
    r"修复",
    r"修改",
    r"重构",
    r"优化",
)

CODEGRAPH_TERMS = (
    r"contract",
    r"dispatcher",
    r"worker",
    r"service",
    r"taskrun",
    r"datasetdefinition",
    r"resolver",
    r"依赖边界",
    r"调用链",
    r"契约",
    r"架构",
)

TUSHARE_TERMS = (
    r"tushare",
    r"ts_code",
    r"fields",
    r"股票",
    r"行情",
    r"基金",
    r"指数",
    r"分页",
    r"源接口",
)

LAKE_PERFORMANCE_TERMS = (
    r"lake",
    r"lake_console",
    r"sync center",
    r"sync-center",
    r"duckdb",
    r"parquet",
    r"dagster",
    r"backfill",
    r"bootstrap",
    r"prod-raw-db",
    r"prod-db",
    r"全量",
    r"全市场",
    r"分钟线",
    r"性能",
    r"导出",
    r"同步",
)

DB_TERMS = (
    r"\bpsql\b",
    r"postgres",
    r"生产库",
    r"远程库",
    r"goldenshare-db",
    r"prod-db",
    r"prod-raw-db",
    r"raw_tushare",
)

FRONTEND_TERMS = (
    r"frontend",
    r"react",
    r"vite",
    r"页面",
    r"前端",
    r"ui",
    r"布局",
    r"浏览器",
)


if __name__ == "__main__":
    raise SystemExit(main())
