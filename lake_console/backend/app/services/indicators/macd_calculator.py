from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from lake_console.backend.app.services.indicators.macd_spec import DEFAULT_MACD_PARAMS
from lake_console.backend.app.services.indicators.models import MacdCalculationResult, MacdParams, MacdState


def calculate_macd(
    rows: Iterable[Mapping[str, Any]],
    *,
    params: MacdParams = DEFAULT_MACD_PARAMS,
    initial_state: MacdState | None = None,
) -> MacdCalculationResult:
    """Calculate MACD for one ts_code + freq stream ordered by trade_time."""
    _validate_params(params)
    bars = sorted((_normalize_bar(row) for row in rows), key=lambda item: item["trade_time"])
    if not bars:
        return MacdCalculationResult(rows=[], final_state=initial_state)

    ts_code = bars[0]["ts_code"]
    freq = bars[0]["freq"]
    for bar in bars:
        if bar["ts_code"] != ts_code or bar["freq"] != freq:
            raise ValueError("MACD 计算一次只能处理一个 ts_code + freq。")

    if initial_state is not None:
        if initial_state.ts_code != ts_code or initial_state.freq != freq:
            raise ValueError("initial_state 与输入 K 线的 ts_code/freq 不一致。")
        bars = [bar for bar in bars if bar["trade_time"] > initial_state.last_trade_time]
        if not bars:
            return MacdCalculationResult(rows=[], final_state=initial_state)

    alpha_fast = 2.0 / (params.fast + 1)
    alpha_slow = 2.0 / (params.slow + 1)
    alpha_signal = 2.0 / (params.signal + 1)

    output_rows: list[dict[str, Any]] = []
    ema_fast = initial_state.ema_fast if initial_state else None
    ema_slow = initial_state.ema_slow if initial_state else None
    dea = initial_state.dea if initial_state else None
    last_trade_time: datetime | None = initial_state.last_trade_time if initial_state else None

    for bar in bars:
        close = bar["close"]
        trade_time = bar["trade_time"]
        if ema_fast is None or ema_slow is None or dea is None:
            ema_fast = close
            ema_slow = close
            dif = 0.0
            dea = 0.0
        else:
            ema_fast = _ema(previous=ema_fast, value=close, alpha=alpha_fast)
            ema_slow = _ema(previous=ema_slow, value=close, alpha=alpha_slow)
            dif = ema_fast - ema_slow
            dea = _ema(previous=dea, value=dif, alpha=alpha_signal)

        macd_bar = 2.0 * (dif - dea)
        output_rows.append(
            {
                "ts_code": ts_code,
                "freq": freq,
                "trade_time": trade_time,
                "dif": dif,
                "dea": dea,
                "macd_bar": macd_bar,
                "params_key": params.params_key,
                "indicator_version": params.indicator_version,
            }
        )
        last_trade_time = trade_time

    final_state = MacdState(
        ts_code=ts_code,
        freq=freq,
        last_trade_time=last_trade_time,
        ema_fast=float(ema_fast),
        ema_slow=float(ema_slow),
        dea=float(dea),
    )
    return MacdCalculationResult(rows=output_rows, final_state=final_state)


def _ema(*, previous: float, value: float, alpha: float) -> float:
    return previous * (1.0 - alpha) + value * alpha


def _normalize_bar(row: Mapping[str, Any]) -> dict[str, Any]:
    ts_code = str(row.get("ts_code") or "").strip()
    if not ts_code:
        raise ValueError("MACD 输入缺少 ts_code。")

    freq = row.get("freq")
    if freq is None:
        raise ValueError("MACD 输入缺少 freq。")
    freq_value = int(freq)
    if freq_value <= 0:
        raise ValueError("MACD 输入 freq 必须大于 0。")

    trade_time = _parse_trade_time(row.get("trade_time"))
    close = _parse_number(row.get("close"), field_name="close")
    return {
        "ts_code": ts_code,
        "freq": freq_value,
        "trade_time": trade_time,
        "close": close,
    }


def _parse_trade_time(value: Any) -> datetime:
    if value is None:
        raise ValueError("MACD 输入缺少 trade_time。")
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(tzinfo=None)
    raw_value = str(value).strip()
    if not raw_value:
        raise ValueError("MACD 输入 trade_time 为空。")
    try:
        return datetime.fromisoformat(raw_value.replace("T", " "))
    except ValueError as exc:
        raise ValueError(f"MACD 输入 trade_time 格式无效：{raw_value}") from exc


def _parse_number(value: Any, *, field_name: str) -> float:
    if value is None:
        raise ValueError(f"MACD 输入缺少 {field_name}。")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"MACD 输入 {field_name} 不是有限数值。")
    return number


def _validate_params(params: MacdParams) -> None:
    if params.fast <= 0 or params.slow <= 0 or params.signal <= 0:
        raise ValueError("MACD 参数必须大于 0。")
    if params.fast >= params.slow:
        raise ValueError("MACD fast 必须小于 slow。")
    if not params.params_key:
        raise ValueError("MACD params_key 不能为空。")
