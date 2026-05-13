from __future__ import annotations

from datetime import date
from pathlib import Path

from lake_console.backend.app.catalog.datasets.moneyflow import MONEYFLOW_KNOWN_SOURCE_GAPS_BY_DATASET
from lake_console.backend.app.catalog.models import LakeDatasetDefinition
from lake_console.backend.app.services.prod_core_db import PROD_CORE_DB_SOURCE
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_ALLOWED_TABLES
from lake_console.backend.app.sync.helpers.dates import (
    INDEX_PERIOD_MONTH_DATASETS,
    INDEX_PERIOD_WEEK_DATASETS,
    STK_PERIOD_BAR_MONTH_DATASETS,
    STK_PERIOD_BAR_WEEK_DATASETS,
    load_expected_partition_dates,
    resolve_expected_partition_date,
)
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
        dates = [resolve_expected_partition_date(lake_root=lake_root, dataset_key=definition.dataset_key, trade_date=trade_date)]
    else:
        if start_date is None or end_date is None:
            raise ValueError(f"{definition.dataset_key} 计划预览必须传 --trade-date 或 --start-date/--end-date。")
        if end_date < start_date:
            raise ValueError("--end-date 不能早于 --start-date。")
        dates = load_expected_partition_dates(
            lake_root=lake_root,
            dataset_key=definition.dataset_key,
            start_date=start_date,
            end_date=end_date,
        )
        if not dates:
            raise RuntimeError(f"{definition.dataset_key} 在 {start_date.isoformat()} ~ {end_date.isoformat()} 范围内没有可导出的锚点日期。")
    write_paths = tuple(f"{node.path}/trade_date={item.isoformat()}" for item in dates for node in definition.nodes)
    if source == "prod-raw-db":
        if definition.dataset_key not in {
            "cyq_perf",
            "daily",
            "adj_factor",
            "daily_basic",
            "dc_daily",
            "dc_hot",
            "dc_index",
            "dc_member",
            "fund_daily",
            "fund_adj",
            "index_daily_basic",
            "stk_factor_pro",
            "stk_nineturn",
            "kpl_concept_cons",
            "kpl_list",
            "limit_cpt_list",
            "limit_list_d",
            "limit_list_ths",
            "limit_step",
            "margin",
            "moneyflow",
            "moneyflow_ths",
            "moneyflow_dc",
            "moneyflow_cnt_ths",
            "moneyflow_ind_ths",
            "moneyflow_ind_dc",
            "moneyflow_mkt_dc",
            "stk_limit",
            "stock_st",
            "suspend_d",
            "stk_period_bar_week",
            "stk_period_bar_month",
            "stk_period_bar_adj_week",
            "stk_period_bar_adj_month",
            "ths_daily",
            "ths_hot",
            "top_list",
        }:
            raise ValueError(f"{definition.dataset_key} 当前不支持 --from prod-raw-db。")
    elif source == PROD_CORE_DB_SOURCE:
        if definition.dataset_key not in {"index_daily", "index_weekly", "index_monthly"}:
            raise ValueError(f"{definition.dataset_key} 当前不支持 --from prod-core-db。")
    elif source != "tushare":
        raise ValueError(f"{definition.dataset_key} 当前不支持 --from {source}。")
    if definition.dataset_key in STK_PERIOD_BAR_WEEK_DATASETS:
        notes = ["单日计划要求自然周周五锚点，且该自然周内必须存在开市交易日。"] if trade_date else [
            "区间计划按自然周周五锚点展开，并过滤掉该自然周内没有开市交易日的周锚点。"
        ]
    elif definition.dataset_key in STK_PERIOD_BAR_MONTH_DATASETS:
        notes = ["单日计划要求自然月月末锚点，且该自然月内必须存在开市交易日。"] if trade_date else [
            "区间计划按自然月月末锚点展开，并过滤掉该自然月内没有开市交易日的月锚点。"
        ]
        notes.append("2020-02 异常月只保留 2020-02-28，忽略 2020-02-29。")
    elif definition.dataset_key in INDEX_PERIOD_WEEK_DATASETS:
        notes = ["单日计划要求使用该自然周的最后开市日锚点。"] if trade_date else [
            "区间计划按自然周分桶，并使用每周最后开市日作为正式分区锚点。"
        ]
    elif definition.dataset_key in INDEX_PERIOD_MONTH_DATASETS:
        notes = ["单日计划要求使用该自然月的最后开市日锚点。"] if trade_date else [
            "区间计划按自然月分桶，并使用每月最后开市日作为正式分区锚点。"
        ]
    else:
        notes = ["单日计划直接使用指定 trade_date。"] if trade_date else ["区间计划读取本地交易日历，只请求开市交易日。"]
    request_strategy_key = definition.dataset_key
    plan_source = definition.source
    if source == "prod-raw-db":
        plan_source = source
        request_strategy_key = f"{definition.dataset_key}:prod-raw-db"
        prod_raw_table = PROD_RAW_DB_ALLOWED_TABLES.get(definition.dataset_key, f"raw_tushare.{definition.dataset_key}")
        notes.append(f"从生产库 {prod_raw_table} 只读导出，按字段白名单投影，不请求 Tushare。")
    elif source == PROD_CORE_DB_SOURCE:
        plan_source = source
        request_strategy_key = f"{definition.dataset_key}:prod-core-db"
        core_table = {
            "index_daily": "core_serving.index_daily_serving",
            "index_weekly": "core_serving.index_weekly_serving",
            "index_monthly": "core_serving.index_monthly_serving",
        }[definition.dataset_key]
        notes.append(f"从生产库 {core_table} 只读导出，显式映射回 Tushare {definition.api_name} 字段口径。")
    if ts_code:
        notes.append("当前 prod-db 日频导出不支持 ts_code 局部筛选，传入后实际执行会拒绝。")
    known_gap_dates = MONEYFLOW_KNOWN_SOURCE_GAPS_BY_DATASET.get(definition.dataset_key, ())
    if known_gap_dates:
        covered_gap_dates = [item for item in dates if item in known_gap_dates]
        if covered_gap_dates:
            joined = ", ".join(item.isoformat() for item in covered_gap_dates)
            notes.append(f"命中已知源站缺口日期：{joined}；执行时会跳过分区替换并标记 skip_reason=source_gap。")
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
        required_manifests=(
            ("manifest/trading_calendar/tushare_trade_cal.parquet",)
            if (
                trade_date is None
                or definition.dataset_key
                in (STK_PERIOD_BAR_WEEK_DATASETS | STK_PERIOD_BAR_MONTH_DATASETS | INDEX_PERIOD_WEEK_DATASETS | INDEX_PERIOD_MONTH_DATASETS)
            )
            else ()
        ),
        parameters={
            "trade_date": trade_date.isoformat() if trade_date else None,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "ts_code": ts_code,
        },
        notes=tuple(notes),
    )
