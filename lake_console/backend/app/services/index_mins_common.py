from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any


INDEX_MINS_ALLOWED_FREQS = ("1min", "5min", "15min", "30min", "60min")


def normalize_index_mins_freqs(freqs: list[str] | None) -> list[str]:
    if not freqs:
        raise ValueError("index_mins 至少需要一个 freq。")
    normalized = [str(item).strip() for item in freqs if str(item).strip()]
    invalid = sorted(set(normalized) - set(INDEX_MINS_ALLOWED_FREQS))
    if invalid:
        allowed = ", ".join(INDEX_MINS_ALLOWED_FREQS)
        raise ValueError(f"index_mins 不支持的 freqs={invalid}，允许值：{allowed}")
    return list(dict.fromkeys(normalized))


def normalize_index_mins_row(
    row: dict[str, Any],
    *,
    requested_freq: str,
) -> dict[str, Any]:
    trade_time = parse_trade_time(row.get("trade_time"))
    current_time = trade_time.time()
    if not _is_trading_session(current_time):
        raise ValueError(f"指数分钟时间不在交易时段内：{trade_time}")

    freq = str(row.get("freq") or requested_freq or "").strip()
    if freq not in INDEX_MINS_ALLOWED_FREQS:
        raise ValueError(f"指数分钟频率无效：{freq}")

    ts_code = str(row.get("ts_code") or "").strip().upper()
    if not ts_code:
        raise ValueError("指数分钟缺少 ts_code。")

    exchange = row.get("exchange")
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": trade_time,
        "close": _optional_float(row.get("close")),
        "open": _optional_float(row.get("open")),
        "high": _optional_float(row.get("high")),
        "low": _optional_float(row.get("low")),
        "vol": _optional_float(row.get("vol")),
        "amount": _optional_float(row.get("amount")),
        "exchange": str(exchange).strip().upper() if exchange not in (None, "") else None,
        "vwap": _optional_float(row.get("vwap")),
    }


def parse_trade_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def format_tushare_window_start(value: date) -> str:
    return datetime.combine(value, time(9, 0)).strftime("%Y-%m-%d %H:%M:%S")


def format_tushare_window_end(value: date) -> str:
    return datetime.combine(value, time(19, 0)).strftime("%Y-%m-%d %H:%M:%S")


def next_trade_date(value: date) -> date:
    return value + timedelta(days=1)


def _is_trading_session(value: time) -> bool:
    return time(9, 30) <= value <= time(11, 30) or time(13, 0) <= value <= time(15, 0)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(Decimal(str(value)))
