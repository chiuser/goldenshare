from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as clock_time
from pathlib import Path
from typing import Any, Literal

SUPPORTED_MINUTE_FREQS = (1, 5, 15, 30, 60, 90, 120)
MAX_MINUTE_LIMIT = 10_000
MAX_YEAR_FILE_COUNT = 3
TS_CODE_PATTERN = re.compile(r"^[0-9]{6}\.(?:SZ|SH|BJ)$")
CURSOR_VERSION = 1

DatasetName = Literal["bars", "indicators"]

class MinuteReaderError(RuntimeError):
    code = "SM_QUERY_FAILED"


class MinuteRequestError(MinuteReaderError):
    code = "SM_REQUEST_INVALID"


class MinuteSourceContractError(MinuteReaderError):
    code = "SM_SOURCE_CONTRACT_INVALID"


class MinuteQueryError(MinuteReaderError):
    code = "SM_QUERY_FAILED"


@dataclass(frozen=True)
class MinuteReadRequest:
    ts_code: str
    freq: int
    start_date: date | None
    end_date: date | None
    limit: int
    cursor: str | None


@dataclass(frozen=True)
class MinuteReadPage:
    rows: tuple[dict[str, Any], ...]
    count: int
    has_more: bool
    next_cursor: str | None
    observed_start_date: date | None
    observed_end_date: date | None
    scanned_file_count: int
    elapsed_ms: float


def build_stock_mins_qfq_paths(
    lake_root: Path,
    dataset: DatasetName,
    ts_code: str,
    freq: int,
    years: Sequence[int],
) -> tuple[Path, ...]:
    normalized_code = normalize_stock_minute_code(ts_code)
    normalized_freq = validate_stock_minute_frequency(freq)
    normalized_years = tuple(int(year) for year in years)
    if not normalized_years or len(normalized_years) > MAX_YEAR_FILE_COUNT:
        raise MinuteRequestError("分钟查询最多允许涉及 3 个年份文件。")
    if any(year < 2000 or year > 2100 for year in normalized_years):
        raise MinuteRequestError("分钟查询年份不合法。")
    if dataset not in {"bars", "indicators"}:
        raise MinuteRequestError("分钟数据集类型不支持。")

    root = lake_root.expanduser().resolve()
    dataset_path = "stk_mins_qfq" if dataset == "bars" else "stk_mins_qfq_macd_kdj"
    layer_path = "quote" if dataset == "bars" else "indicator"
    paths: list[Path] = []
    for year in normalized_years:
        candidate = (
            root
            / "gold"
            / layer_path
            / dataset_path
            / f"freq={normalized_freq}"
            / f"ts_code={normalized_code}"
            / f"year={year}"
            / "part-000.parquet"
        ).resolve()
        if not candidate.is_relative_to(root):
            raise MinuteRequestError("分钟查询路径越界。")
        if candidate.is_file():
            paths.append(candidate)
    return tuple(paths)


def encode_stock_minute_cursor(*, dataset: DatasetName, request: MinuteReadRequest, before_trade_date: date, before_trade_time: datetime) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "dataset": dataset,
        "tsCode": request.ts_code,
        "freq": request.freq,
        "startDate": request.start_date.isoformat() if request.start_date else None,
        "endDate": request.end_date.isoformat() if request.end_date else None,
        "beforeTradeDate": before_trade_date.isoformat(),
        "beforeTradeTime": before_trade_time.strftime("%H:%M:%S.%f"),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return encoded.rstrip("=")


def decode_stock_minute_cursor(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise MinuteRequestError("cursor 不合法。") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise MinuteRequestError("cursor 版本不支持。")
    required = {"dataset", "tsCode", "freq", "startDate", "endDate", "beforeTradeDate", "beforeTradeTime"}
    if not required.issubset(payload):
        raise MinuteRequestError("cursor 字段不完整。")
    try:
        normalize_stock_minute_code(str(payload["tsCode"]))
        validate_stock_minute_frequency(int(payload["freq"]))
        date.fromisoformat(payload["beforeTradeDate"])
        clock_time.fromisoformat(payload["beforeTradeTime"])
        if payload["startDate"] is not None:
            date.fromisoformat(payload["startDate"])
        if payload["endDate"] is not None:
            date.fromisoformat(payload["endDate"])
    except (TypeError, ValueError) as exc:
        raise MinuteRequestError("cursor 时间边界不合法。") from exc
    if payload["dataset"] not in {"bars", "indicators"}:
        raise MinuteRequestError("cursor 数据集类型不支持。")
    return payload


def normalize_stock_minute_code(value: str) -> str:
    normalized = value.strip().upper()
    if not TS_CODE_PATTERN.fullmatch(normalized):
        raise MinuteRequestError("tsCode 必须是六位代码加 SZ/SH/BJ 后缀。")
    return normalized


def validate_stock_minute_frequency(value: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise MinuteRequestError("freq 必须是整数分钟频率。") from exc
    if normalized not in SUPPORTED_MINUTE_FREQS:
        raise MinuteRequestError("不支持的分钟频率。")
    return normalized
