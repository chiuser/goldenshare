from __future__ import annotations

from datetime import date
from pathlib import Path

from lake_console.backend.app.catalog.datasets import get_dataset_definition
from lake_console.backend.app.services.prod_core_db import PROD_CORE_DB_SOURCE
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE
from lake_console.backend.app.sync.planners import (
    STK_MINS_DEFAULT_DAILY_QUOTA_LIMIT,
    build_prod_raw_snapshot_plan,
    build_snapshot_plan,
    build_stk_mins_plan,
    build_trade_date_plan,
)
from lake_console.backend.app.sync.plans import LakeSyncPlan


class LakeSyncPlanner:
    def __init__(self, *, lake_root: Path, stk_mins_request_window_days: int = 31) -> None:
        self.lake_root = lake_root
        self.stk_mins_request_window_days = stk_mins_request_window_days

    def plan(
        self,
        *,
        dataset_key: str,
        source: str = "tushare",
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
        if source == PROD_RAW_DB_SOURCE and dataset_key in {"etf_basic", "etf_index", "ths_index", "ths_member"}:
            return build_prod_raw_snapshot_plan(
                definition,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
                market=market,
                name=None,
                publisher=None,
                category=None,
            )
        if source not in {"tushare", PROD_RAW_DB_SOURCE, PROD_CORE_DB_SOURCE}:
            raise ValueError(f"不支持的来源：{source}")
        if dataset_key in {"stock_basic", "trade_cal", "index_basic"}:
            return build_snapshot_plan(definition, start_date=start_date, end_date=end_date, market=market)
        if dataset_key in {
            "adj_factor",
            "cyq_perf",
            "daily_basic",
            "fund_adj",
            "fund_daily",
            "index_daily_basic",
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
            "top_list",
        } and source != PROD_RAW_DB_SOURCE:
            raise ValueError(f"{dataset_key} 当前只支持 --from prod-raw-db。")
        if dataset_key == "index_daily" and source != PROD_CORE_DB_SOURCE:
            raise ValueError("index_daily 当前只支持 --from prod-core-db。")
        if dataset_key in {
            "daily",
            "moneyflow",
            "moneyflow_ths",
            "moneyflow_dc",
            "moneyflow_cnt_ths",
            "moneyflow_ind_ths",
            "moneyflow_ind_dc",
            "moneyflow_mkt_dc",
            "adj_factor",
            "cyq_perf",
            "daily_basic",
            "fund_adj",
            "fund_daily",
            "index_daily",
            "index_daily_basic",
            "limit_cpt_list",
            "limit_list_d",
            "limit_list_ths",
            "limit_step",
            "margin",
            "stk_limit",
            "stock_st",
            "suspend_d",
            "top_list",
        }:
            return build_trade_date_plan(
                definition,
                lake_root=self.lake_root,
                source=source,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
            )
        if dataset_key == "stk_mins":
            return build_stk_mins_plan(
                definition,
                lake_root=self.lake_root,
                stk_mins_request_window_days=self.stk_mins_request_window_days,
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
