from __future__ import annotations

from datetime import date
import math
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.models import LakeDatasetDefinition
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.stk_mins_windowing import (
    STK_MINS_ROWS_PER_TRADE_DAY,
    build_current_month_windows,
    get_trade_days_per_window,
)
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates
from lake_console.backend.app.sync.plans import LakeSyncPlan

STK_MINS_DEFAULT_DAILY_QUOTA_LIMIT = 250_000


def build_stk_mins_plan(
    definition: LakeDatasetDefinition,
    *,
    lake_root: Path,
    stk_mins_request_window_days: int,
    trade_date: date | None,
    start_date: date | None,
    end_date: date | None,
    ts_code: str | None,
    all_market: bool,
    freq: int | None,
    freqs: list[int] | None,
    daily_quota_limit: int,
) -> LakeSyncPlan:
    if trade_date and (start_date or end_date):
        raise ValueError("stk_mins 计划预估中，trade_date 与 start/end date 不能同时传。")
    selected_freqs = _resolve_stk_mins_freqs(freq=freq, freqs=freqs)
    if all_market and ts_code:
        raise ValueError("stk_mins 计划预估中，--all-market 与 --ts-code 不能同时传。")
    if not all_market and not ts_code:
        raise ValueError("stk_mins 计划预估必须传 --all-market 或 --ts-code。")
    if daily_quota_limit <= 0:
        raise ValueError("--daily-quota-limit 必须大于 0。")

    symbol_count = _load_stock_universe_size(lake_root=lake_root) if all_market else 1
    if trade_date:
        trade_dates = [trade_date]
    else:
        if start_date is None or end_date is None:
            raise ValueError("stk_mins 计划预估必须传 --trade-date 或 --start-date/--end-date。")
        if end_date < start_date:
            raise ValueError("--end-date 不能早于 --start-date。")
        trade_dates = load_open_trade_dates(lake_root=lake_root, start_date=start_date, end_date=end_date)
        if not trade_dates:
            raise RuntimeError(f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。")

    current_windows = build_current_month_windows(
        trade_dates=trade_dates,
        max_window_days=stk_mins_request_window_days,
    )
    per_freq_estimates: list[dict[str, Any]] = []
    target_request_count = 0
    for current_freq in selected_freqs:
        rows_per_trade_day = STK_MINS_ROWS_PER_TRADE_DAY[current_freq]
        trade_days_per_window = get_trade_days_per_window(current_freq)
        target_window_count = max(1, math.ceil(len(trade_dates) / trade_days_per_window))
        target_request_count += symbol_count * target_window_count
        per_freq_estimates.append(
            {
                "freq": current_freq,
                "rows_per_trade_day": rows_per_trade_day,
                "trade_days_per_window": trade_days_per_window,
                "rows_per_request_estimate": rows_per_trade_day * min(trade_days_per_window, len(trade_dates)),
                "window_count": target_window_count,
                "request_count": symbol_count * target_window_count,
            }
        )

    current_request_count = symbol_count * len(selected_freqs) * len(current_windows)
    current_partition_count = len(selected_freqs) * len(trade_dates)
    estimated_days = max(1, math.ceil(target_request_count / daily_quota_limit))
    parameters = {
        "trade_date": trade_date.isoformat() if trade_date else None,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "ts_code": ts_code,
        "all_market": all_market,
        "freqs": selected_freqs,
        "daily_quota_limit": daily_quota_limit,
    }
    notes = [
        "当前 plan-sync 对 stk_mins 同时输出历史月窗口径与现行按 freq 定窗口径，便于对比请求量。",
        "sync-stk-mins-range 的真实执行已切到按 freq 定交易日窗；quota exceeded 的可恢复停机语义仍待后续收口。",
        "全市场模式依赖本地股票池和本地交易日历 manifest，不访问远程数据库。",
    ]
    estimate = {
        "implementation_status": "execution_aligned_target_windowing",
        "symbol_scope": "all_market" if all_market else "single_symbol",
        "symbol_count": symbol_count,
        "trade_date_count": len(trade_dates),
        "current_strategy": {
            "strategy_key": "historical_month_window_baseline",
            "request_window_days": stk_mins_request_window_days,
            "window_count": len(current_windows),
            "request_count": current_request_count,
        },
        "target_strategy": {
            "strategy_key": "per_freq_trade_day_window",
            "request_count": target_request_count,
            "estimated_days_at_daily_quota": estimated_days,
            "per_freq": per_freq_estimates,
        },
    }
    return LakeSyncPlan(
        dataset_key=definition.dataset_key,
        display_name=definition.display_name,
        source=definition.source,
        api_name=definition.api_name,
        mode="minute_history",
        request_strategy_key=definition.dataset_key,
        request_count=target_request_count,
        partition_count=current_partition_count,
        write_policy=definition.write_policy,
        write_paths=tuple(layer.path for layer in definition.layers),
        required_manifests=(
            "manifest/security_universe/tushare_stock_basic.parquet",
            "manifest/trading_calendar/tushare_trade_cal.parquet",
        ),
        parameters=parameters,
        notes=tuple(notes),
        estimate=estimate,
    )


def _resolve_stk_mins_freqs(*, freq: int | None, freqs: list[int] | None) -> list[int]:
    if freqs:
        selected = sorted(set(freqs))
    elif freq is not None:
        selected = [freq]
    else:
        raise ValueError("stk_mins 计划预估必须传 --freq 或 --freqs。")
    invalid = sorted(set(selected) - set(STK_MINS_ROWS_PER_TRADE_DAY))
    if invalid:
        allowed = ", ".join(str(item) for item in sorted(STK_MINS_ROWS_PER_TRADE_DAY))
        raise ValueError(f"不支持的 freq={invalid}，允许值：{allowed}")
    return selected


def _load_stock_universe_size(*, lake_root: Path) -> int:
    universe_file = lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet"
    if not universe_file.exists():
        raise RuntimeError(
            "缺少本地股票池 manifest/security_universe/tushare_stock_basic.parquet。"
            "请先执行 sync-stock-basic。"
        )
    rows = read_parquet_rows(universe_file)
    codes = {
        str(row.get("ts_code")).strip()
        for row in rows
        if row.get("ts_code") and str(row.get("list_status") or "L").strip() == "L"
    }
    if not codes:
        raise RuntimeError("本地股票池中没有 list_status=L 的有效 ts_code。")
    return len(codes)
