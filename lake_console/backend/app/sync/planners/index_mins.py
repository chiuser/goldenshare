from __future__ import annotations

from datetime import date
from pathlib import Path

from lake_console.backend.app.catalog.models import LakeDatasetDefinition
from lake_console.backend.app.services.index_mins_common import normalize_index_mins_freqs
from lake_console.backend.app.services.index_mins_universe_filter import load_index_mins_universe_for_range
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates
from lake_console.backend.app.sync.plans import LakeSyncPlan


def build_index_mins_plan(
    definition: LakeDatasetDefinition,
    *,
    lake_root: Path,
    source: str,
    trade_date: date | None,
    start_date: date | None,
    end_date: date | None,
    ts_code: str | None,
    freqs: list[str] | None,
) -> LakeSyncPlan:
    if source not in {"tushare", "prod-raw-db"}:
        raise ValueError("index_mins 当前只支持 --from tushare 或 --from prod-raw-db。")
    if trade_date and (start_date or end_date):
        raise ValueError("index_mins 计划预览中，trade_date 与 start/end date 不能同时传。")
    if (start_date is None) != (end_date is None):
        raise ValueError("index_mins 计划预览中，start-date 和 end-date 必须同时传入，或同时省略。")
    if trade_date is None and start_date is None:
        raise ValueError("index_mins 计划预览必须传 --trade-date 或 --start-date/--end-date。")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("index_mins 计划预览中，end-date 不能早于 start-date。")

    normalized_freqs = normalize_index_mins_freqs(freqs or [])
    request_start_date = trade_date or start_date
    request_end_date = trade_date or end_date
    assert request_start_date is not None and request_end_date is not None

    trade_dates = load_open_trade_dates(
        lake_root=lake_root,
        start_date=request_start_date,
        end_date=request_end_date,
    )
    if not trade_dates:
        raise RuntimeError("index_mins 计划预览范围内没有开市交易日。")

    universe = load_index_mins_universe_for_range(
        lake_root=lake_root,
        start_date=request_start_date,
        end_date=request_end_date,
        ts_code=ts_code,
    )
    parameters = {
        "trade_date": trade_date.isoformat() if trade_date else None,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "ts_code": ts_code.strip().upper() if ts_code else None,
        "freqs": normalized_freqs,
    }
    notes = [
        "index_mins 双模式共用本地 index_mins active pool 与本地 index_basic 生命周期过滤。",
        "有效期外无数据是正常现象，只有有效期内无数据才应在 completeness/audit 中判定为缺失。",
    ]
    if source == "prod-raw-db":
        notes.append("prod-raw-db 只复用当前远程 raw 已保留的分钟线历史；更早历史应使用 --from tushare。")
        request_count = len(normalized_freqs)
        request_strategy_key = "index_mins_prod_raw_range_query"
    else:
        notes.append("tushare 模式会先做生命周期过滤，再按 code + freq + 有效时间窗口发请求。")
        request_count = len(normalized_freqs) * len(universe.ts_codes)
        request_strategy_key = "index_mins_tushare_code_window"

    effective_counts = [universe.effective_code_count_on(trade_date=current_date) for current_date in trade_dates]
    estimate = {
        "trade_date_count": len(trade_dates),
        "selected_code_count": len(universe.ts_codes),
        "effective_code_count_min": min(effective_counts),
        "effective_code_count_max": max(effective_counts),
        "universe": universe.to_dict(),
    }
    return LakeSyncPlan(
        dataset_key=definition.dataset_key,
        display_name=definition.display_name,
        source=source,
        api_name=definition.api_name,
        mode="minute_history",
        request_strategy_key=request_strategy_key,
        request_count=request_count,
        partition_count=len(normalized_freqs) * len(trade_dates),
        write_policy=definition.write_policy,
        write_paths=tuple(node.path for node in definition.nodes),
        required_manifests=(
            "manifest/index_universe/index_mins_active_pool.parquet",
            "manifest/index_universe/tushare_index_basic.parquet",
            "manifest/trading_calendar/tushare_trade_cal.parquet",
        ),
        parameters=parameters,
        notes=tuple(notes),
        estimate=estimate,
    )
