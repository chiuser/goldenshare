from __future__ import annotations

from datetime import date
from pathlib import Path

from lake_console.backend.app.catalog.models import LakeDatasetDefinition
from lake_console.backend.app.services.prod_core_db import PROD_CORE_DB_SOURCE
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates
from lake_console.backend.app.sync.plans import LakeSyncPlan


def build_trade_date_plan(
    definition: LakeDatasetDefinition,
    *,
    lake_root: Path,
    source: str,
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
        dates = load_open_trade_dates(lake_root=lake_root, start_date=start_date, end_date=end_date)
        if not dates:
            raise RuntimeError(f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。")
    write_paths = tuple(f"{layer.path}/trade_date={item.isoformat()}" for item in dates for layer in definition.layers)
    if source == "prod-raw-db":
        if definition.dataset_key not in {"daily", "adj_factor", "daily_basic", "index_daily_basic"}:
            raise ValueError(f"{definition.dataset_key} 当前不支持 --from prod-raw-db。")
    elif source == PROD_CORE_DB_SOURCE:
        if definition.dataset_key != "index_daily":
            raise ValueError(f"{definition.dataset_key} 当前不支持 --from prod-core-db。")
    elif source != "tushare":
        raise ValueError(f"{definition.dataset_key} 当前不支持 --from {source}。")
    notes = ["单日计划直接使用指定 trade_date。"] if trade_date else ["区间计划读取本地交易日历，只请求开市交易日。"]
    request_strategy_key = definition.dataset_key
    plan_source = definition.source
    if source == "prod-raw-db":
        plan_source = source
        request_strategy_key = f"{definition.dataset_key}:prod-raw-db"
        notes.append(f"从生产库 raw_tushare.{definition.dataset_key} 只读导出，按字段白名单投影，不请求 Tushare。")
    elif source == PROD_CORE_DB_SOURCE:
        plan_source = source
        request_strategy_key = f"{definition.dataset_key}:prod-core-db"
        notes.append("从生产库 core_serving.index_daily_serving 只读导出，显式映射回 Tushare index_daily 字段口径。")
    if ts_code:
        notes.append("传入 ts_code 时作为单标的调试或补数计划，写入仍按返回行 trade_date 分区。")
    return LakeSyncPlan(
        dataset_key=definition.dataset_key,
        display_name=definition.display_name,
        source=plan_source,
        api_name=definition.api_name,
        mode="point_incremental" if trade_date else "range_rebuild",
        request_strategy_key=request_strategy_key,
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
