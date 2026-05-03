from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.datasets import get_dataset_definition
from lake_console.backend.app.catalog.models import LakeDatasetDefinition
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.stk_mins_windowing import (
    STK_MINS_ROWS_PER_TRADE_DAY,
    build_current_month_windows,
    get_trade_days_per_window,
)
STK_MINS_DEFAULT_DAILY_QUOTA_LIMIT = 250_000


@dataclass(frozen=True)
class LakeSyncPlan:
    dataset_key: str
    display_name: str
    source: str
    api_name: str | None
    mode: str
    request_strategy_key: str
    request_count: int
    partition_count: int
    write_policy: str
    write_paths: tuple[str, ...]
    required_manifests: tuple[str, ...]
    parameters: dict[str, Any]
    notes: tuple[str, ...]
    estimate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_key": self.dataset_key,
            "display_name": self.display_name,
            "source": self.source,
            "api_name": self.api_name,
            "mode": self.mode,
            "request_strategy_key": self.request_strategy_key,
            "request_count": self.request_count,
            "partition_count": self.partition_count,
            "write_policy": self.write_policy,
            "write_paths": list(self.write_paths),
            "required_manifests": list(self.required_manifests),
            "parameters": self.parameters,
            "notes": list(self.notes),
            "estimate": self.estimate,
        }


class LakeSyncPlanner:
    def __init__(self, *, lake_root: Path, stk_mins_request_window_days: int = 31) -> None:
        self.lake_root = lake_root
        self.stk_mins_request_window_days = stk_mins_request_window_days

    def plan(
        self,
        *,
        dataset_key: str,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
        market: str | None = None,
        all_market: bool = False,
        freq: int | None = None,
        freqs: list[int] | None = None,
        daily_quota_limit: int = STK_MINS_DEFAULT_DAILY_QUOTA_LIMIT,
    ) -> LakeSyncPlan:
        definition = get_dataset_definition(dataset_key)
        if dataset_key in {"stock_basic", "trade_cal", "index_basic"}:
            return self._snapshot_plan(definition, start_date=start_date, end_date=end_date, market=market)
        if dataset_key in {"daily", "moneyflow"}:
            return self._trade_date_plan(definition, trade_date=trade_date, start_date=start_date, end_date=end_date, ts_code=ts_code)
        if dataset_key == "stk_mins":
            return self._stk_mins_plan(
                definition,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
                all_market=all_market,
                freq=freq,
                freqs=freqs,
                daily_quota_limit=daily_quota_limit,
            )
        raise ValueError(f"plan-sync 暂不支持数据集：{dataset_key}")

    def _snapshot_plan(
        self,
        definition: LakeDatasetDefinition,
        *,
        start_date: date | None,
        end_date: date | None,
        market: str | None,
    ) -> LakeSyncPlan:
        notes = ["快照类数据集以 current 文件为替换范围。"]
        parameters: dict[str, Any] = {}
        if definition.dataset_key == "trade_cal":
            if start_date is None or end_date is None:
                raise ValueError("trade_cal 计划预览必须传 --start-date 和 --end-date。")
            if end_date < start_date:
                raise ValueError("--end-date 不能早于 --start-date。")
            parameters = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
            notes = ["trade_cal 会双落盘 raw current 与交易日历 manifest。"]
        if market:
            parameters["market"] = _parse_csv(market)
        return LakeSyncPlan(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            source=definition.source,
            api_name=definition.api_name,
            mode="snapshot_refresh",
            request_strategy_key=definition.dataset_key,
            request_count=len(_parse_csv(market)) if market else 1,
            partition_count=len(definition.layers),
            write_policy=definition.write_policy,
            write_paths=tuple(layer.path for layer in definition.layers),
            required_manifests=(),
            parameters=parameters,
            notes=tuple(notes),
        )

    def _trade_date_plan(
        self,
        definition: LakeDatasetDefinition,
        *,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
        ts_code: str | None,
    ) -> LakeSyncPlan:
        if trade_date and (start_date or end_date):
            raise ValueError("trade_date 与 start/end date 不能同时传。")
        if trade_date:
            dates = [trade_date]
        else:
            if start_date is None or end_date is None:
                raise ValueError(f"{definition.dataset_key} 计划预览必须传 --trade-date 或 --start-date/--end-date。")
            if end_date < start_date:
                raise ValueError("--end-date 不能早于 --start-date。")
            dates = self._load_open_trade_dates(start_date=start_date, end_date=end_date)
            if not dates:
                raise RuntimeError(f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。")
        write_paths = tuple(f"{layer.path}/trade_date={item.isoformat()}" for item in dates for layer in definition.layers)
        notes = ["单日计划直接使用指定 trade_date。"] if trade_date else ["区间计划读取本地交易日历，只请求开市交易日。"]
        if ts_code:
            notes.append("传入 ts_code 时作为单标的调试或补数计划，写入仍按返回行 trade_date 分区。")
        return LakeSyncPlan(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            source=definition.source,
            api_name=definition.api_name,
            mode="point_incremental" if trade_date else "range_rebuild",
            request_strategy_key=definition.dataset_key,
            request_count=len(dates),
            partition_count=len(dates),
            write_policy=definition.write_policy,
            write_paths=write_paths,
            required_manifests=() if trade_date else ("manifest/trading_calendar/tushare_trade_cal.parquet",),
            parameters={
                "trade_date": trade_date.isoformat() if trade_date else None,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "ts_code": ts_code,
            },
            notes=tuple(notes),
        )

    def _stk_mins_plan(
        self,
        definition: LakeDatasetDefinition,
        *,
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
        selected_freqs = self._resolve_stk_mins_freqs(freq=freq, freqs=freqs)
        if all_market and ts_code:
            raise ValueError("stk_mins 计划预估中，--all-market 与 --ts-code 不能同时传。")
        if not all_market and not ts_code:
            raise ValueError("stk_mins 计划预估必须传 --all-market 或 --ts-code。")
        if daily_quota_limit <= 0:
            raise ValueError("--daily-quota-limit 必须大于 0。")

        symbol_count = self._load_stock_universe_size() if all_market else 1
        if trade_date:
            trade_dates = [trade_date]
        else:
            if start_date is None or end_date is None:
                raise ValueError("stk_mins 计划预估必须传 --trade-date 或 --start-date/--end-date。")
            if end_date < start_date:
                raise ValueError("--end-date 不能早于 --start-date。")
            trade_dates = self._load_open_trade_dates(start_date=start_date, end_date=end_date)
            if not trade_dates:
                raise RuntimeError(f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。")

        current_windows = build_current_month_windows(
            trade_dates=trade_dates,
            max_window_days=self.stk_mins_request_window_days,
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
                "request_window_days": self.stk_mins_request_window_days,
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

    def _resolve_stk_mins_freqs(self, *, freq: int | None, freqs: list[int] | None) -> list[int]:
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

    def _load_open_trade_dates(self, *, start_date: date, end_date: date) -> list[date]:
        calendar_file = self.lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
        if not calendar_file.exists():
            raise RuntimeError(
                "缺少本地交易日历 manifest/trading_calendar/tushare_trade_cal.parquet。"
                "请先执行 sync-trade-cal。"
            )
        rows = read_parquet_rows(calendar_file)
        trade_dates: list[date] = []
        for row in rows:
            if not bool(row.get("is_open")):
                continue
            current_date = _parse_date(row.get("cal_date"))
            if start_date <= current_date <= end_date:
                trade_dates.append(current_date)
        return sorted(set(trade_dates))

    def _load_stock_universe_size(self) -> int:
        universe_file = self.lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet"
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


def _parse_csv(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _parse_date(value: Any) -> date:
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    if isinstance(value, date):
        return value
    raw_value = str(value).strip()
    if len(raw_value) == 8 and raw_value.isdigit():
        return date(int(raw_value[:4]), int(raw_value[4:6]), int(raw_value[6:]))
    return date.fromisoformat(raw_value)
