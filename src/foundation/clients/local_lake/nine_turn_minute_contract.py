from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from datetime import date, datetime
from datetime import time as clock_time
import json
from pathlib import Path
from typing import Any, Final


MAX_NINE_TURN_RESPONSE_BYTES: Final = 5_000_000
NINE_TURN_MINUTE_CURSOR_VERSION: Final = 1


def encode_nine_turn_minute_cursor(
    *,
    dataset: str,
    subject_type: str,
    ts_code: str,
    freq: int,
    start_date: date | None,
    end_date: date | None,
    before_trade_date: date,
    before_trade_time: datetime,
) -> str:
    payload = {
        "v": NINE_TURN_MINUTE_CURSOR_VERSION,
        "dataset": dataset,
        "subjectType": subject_type,
        "tsCode": ts_code,
        "freq": freq,
        "startDate": start_date.isoformat() if start_date else None,
        "endDate": end_date.isoformat() if end_date else None,
        "beforeTradeDate": before_trade_date.isoformat(),
        "beforeTradeTime": before_trade_time.strftime("%H:%M:%S.%f"),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    return encoded.rstrip("=")


def decode_nine_turn_minute_cursor(
    value: str | None,
    *,
    dataset: str,
    subject_type: str,
    ts_code: str,
    freq: int,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (
        ValueError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("cursor 不合法。") from exc
    required = {
        "v",
        "dataset",
        "subjectType",
        "tsCode",
        "freq",
        "startDate",
        "endDate",
        "beforeTradeDate",
        "beforeTradeTime",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("cursor 字段不完整或包含未知字段。")
    expected = {
        "v": NINE_TURN_MINUTE_CURSOR_VERSION,
        "dataset": dataset,
        "subjectType": subject_type,
        "tsCode": ts_code,
        "freq": freq,
        "startDate": start_date.isoformat() if start_date else None,
        "endDate": end_date.isoformat() if end_date else None,
    }
    for key, expected_value in expected.items():
        if payload.get(key) != expected_value:
            raise ValueError(f"cursor 与当前 {key} 不匹配。")
    try:
        date.fromisoformat(payload["beforeTradeDate"])
        clock_time.fromisoformat(payload["beforeTradeTime"])
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor 时间边界不合法。") from exc
    return payload


def existing_safe_partition_paths(
    *,
    lake_root: Path,
    dataset_root: Path,
    candidates: Sequence[Path],
) -> tuple[Path, ...]:
    formal_root = lake_root.expanduser().resolve()
    bounded_dataset_root = dataset_root.expanduser().resolve()
    if not bounded_dataset_root.is_relative_to(formal_root):
        raise ValueError("九转分钟数据集路径越界。")
    safe_paths: list[Path] = []
    for candidate in candidates:
        if candidate.is_symlink() or _contains_symlink(candidate, stop=formal_root):
            raise ValueError("九转分钟分区不允许符号链接。")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(bounded_dataset_root):
            raise ValueError("九转分钟分区路径越界。")
        if resolved.is_file():
            safe_paths.append(resolved)
    return tuple(safe_paths)


def _contains_symlink(path: Path, *, stop: Path) -> bool:
    current = path
    while current != stop and current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


__all__ = [
    "MAX_NINE_TURN_RESPONSE_BYTES",
    "decode_nine_turn_minute_cursor",
    "encode_nine_turn_minute_cursor",
    "existing_safe_partition_paths",
]
