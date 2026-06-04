#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from typing import Any


def main() -> int:
    payload = _read_payload()
    text = _flatten_text(payload)
    if not text.strip():
        _print_default_gate()
        return 0

    reminders = _missing_delivery_items(text)
    if reminders:
        sys.stdout.write(
            "[Goldenshare Hook] 结束前交付检查：\n"
            + "\n".join(f"- {item}" for item in reminders)
            + "\n"
        )
    return 0


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return data if isinstance(data, dict) else {"payload": data}


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    return ""


def _print_default_gate() -> None:
    sys.stdout.write(
        "[Goldenshare Hook] 结束前请确认：目标与依据、改动文件、边界/依赖影响、验证结果、风险/下一步。"
        "若涉及 CodeGraph/Tushare/Lake 性能门禁，请说明已用工具和仍需人工确认的边界。\n"
    )


def _missing_delivery_items(text: str) -> list[str]:
    lowered = text.lower()
    missing: list[str] = []
    checks = (
        ("目标与依据", (r"目标", r"依据")),
        ("改动文件", (r"改动文件", r"修改了", r"changed", r"file")),
        ("边界/依赖影响", (r"边界", r"依赖", r"影响")),
        ("验证结果", (r"验证", r"通过", r"test", r"check")),
        ("风险或下一步", (r"风险", r"下一步", r"后续")),
    )
    for label, patterns in checks:
        if not any(re.search(pattern, lowered) for pattern in patterns):
            missing.append(f"交付说明缺少 `{label}`。")

    if _mentions_codegraph_scope(lowered) and "codegraph" not in lowered:
        missing.append("涉及架构/重构/contract/service 等高风险范围时，交付说明需要写明 CodeGraph 分析范围。")
    if _mentions_lake_or_tushare(lowered) and not any(term in lowered for term in ("性能", "样本", "dry-run", "tusharemcp")):
        missing.append("涉及 Lake/Tushare/同步时，交付说明需要包含性能测算、样本验证或 tushareMcp 实测信息。")
    return missing


def _mentions_codegraph_scope(text: str) -> bool:
    return any(term in text for term in ("架构", "重构", "contract", "dispatcher", "worker", "service", "契约"))


def _mentions_lake_or_tushare(text: str) -> bool:
    return any(term in text for term in ("lake", "tushare", "duckdb", "parquet", "同步", "导出"))


if __name__ == "__main__":
    raise SystemExit(main())
