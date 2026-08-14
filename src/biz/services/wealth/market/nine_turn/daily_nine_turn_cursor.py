from __future__ import annotations

import base64
import binascii
from datetime import date
import json


def encode_daily_nine_turn_cursor(
    *,
    dataset: str,
    subject_type: str,
    ts_code: str,
    start_date: date | None,
    end_date: date,
    before_trade_date: date,
) -> str:
    payload = {
        "v": 1,
        "dataset": dataset,
        "subjectType": subject_type,
        "tsCode": ts_code,
        "period": "day",
        "startDate": start_date.isoformat() if start_date else None,
        "endDate": end_date.isoformat(),
        "beforeTradeDate": before_trade_date.isoformat(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    return encoded.rstrip("=")


def decode_daily_nine_turn_cursor(
    value: str | None,
    *,
    dataset: str,
    subject_type: str,
    ts_code: str,
    start_date: date | None,
    end_date: date,
) -> date | None:
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
    expected_keys = {
        "v",
        "dataset",
        "subjectType",
        "tsCode",
        "period",
        "startDate",
        "endDate",
        "beforeTradeDate",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("cursor 字段不完整或包含未知字段。")
    expected = {
        "v": 1,
        "dataset": dataset,
        "subjectType": subject_type,
        "tsCode": ts_code,
        "period": "day",
        "startDate": start_date.isoformat() if start_date else None,
        "endDate": end_date.isoformat(),
    }
    if any(
        payload.get(key) != expected_value for key, expected_value in expected.items()
    ):
        raise ValueError("cursor 与当前对象、代码或日期窗口不匹配。")
    try:
        return date.fromisoformat(payload["beforeTradeDate"])
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor 时间边界不合法。") from exc


__all__ = ["decode_daily_nine_turn_cursor", "encode_daily_nine_turn_cursor"]
