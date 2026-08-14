from __future__ import annotations

from datetime import date
import re

from fastapi import Request

_ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_TS_CODE_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


class NineTurnParameterError(ValueError):
    pass


def validate_query_shape(request: Request, *, allowed: set[str]) -> None:
    supplied = [key for key, _value in request.query_params.multi_items()]
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise NineTurnParameterError(f"不支持的查询参数：{', '.join(unknown)}")
    duplicated = sorted(key for key in set(supplied) if supplied.count(key) > 1)
    if duplicated:
        raise NineTurnParameterError(f"查询参数不能重复：{', '.join(duplicated)}")


def parse_nine_turn_ts_code(raw_value: str | None) -> str:
    normalized = "" if raw_value is None else raw_value.strip().upper()
    if not _TS_CODE_PATTERN.fullmatch(normalized):
        raise NineTurnParameterError("tsCode 必须是六位代码加 SH/SZ/BJ 后缀。")
    return normalized


def parse_date(raw_value: str | None, *, field_name: str) -> date | None:
    if raw_value is None:
        return None
    if not _ISO_DATE_PATTERN.fullmatch(raw_value):
        raise NineTurnParameterError(f"{field_name} 必须是 YYYY-MM-DD。")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise NineTurnParameterError(f"{field_name} 不是有效日期。") from exc


def parse_limit(raw_value: str | None, *, default: int, maximum: int) -> int:
    value = str(default) if raw_value is None else raw_value
    if not value.isdigit():
        raise NineTurnParameterError("limit 必须是整数。")
    normalized = int(value)
    if not 1 <= normalized <= maximum:
        raise NineTurnParameterError(f"limit 必须在 1 到 {maximum} 之间。")
    return normalized


def parse_cursor(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    if not raw_value.strip():
        raise NineTurnParameterError("cursor 不能为空。")
    return raw_value


def parse_debug(raw_value: str | None) -> bool:
    value = "0" if raw_value is None else raw_value
    if value not in {"0", "1"}:
        raise NineTurnParameterError("debug 只允许 0 或 1。")
    return value == "1"


def parse_stock_nine_turn_freq(raw_value: str | None) -> int:
    value = "" if raw_value is None else raw_value
    if not value.isdigit():
        raise NineTurnParameterError("freq 必须是整数分钟频率。")
    normalized = int(value)
    if normalized not in {30, 60, 90, 120}:
        raise NineTurnParameterError("股票九转 freq 只允许 30/60/90/120。")
    return normalized


def parse_index_nine_turn_freq(raw_value: str | None) -> int:
    value = "" if raw_value is None else raw_value
    if not value.isdigit():
        raise NineTurnParameterError("freq 必须是整数分钟频率。")
    normalized = int(value)
    if normalized not in {5, 15, 30, 60, 90, 120}:
        raise NineTurnParameterError("指数九转 freq 只允许 5/15/30/60/90/120。")
    return normalized
