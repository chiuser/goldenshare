"""Source-preserving monthly Raw contracts; no resource or filesystem access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum


class StockMonthlySource(str, Enum):
    PRIMARY_ADJUSTED = "primary_adjusted"


def normalize_month_key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ValueError("month_key_must_be_yyyy_mm")
    date.fromisoformat(value + "-01")
    return value


def monthly_source_api(source):
    StockMonthlySource(source)
    return "stk_week_month_adj"


def monthly_column_specs(source: StockMonthlySource) -> tuple[tuple[str, str], ...]:
    source = StockMonthlySource(source)
    names = (
        "ts_code",
        "trade_date",
        "end_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
    )
    if source is StockMonthlySource.PRIMARY_ADJUSTED:
        names += (
            "open_qfq",
            "high_qfq",
            "low_qfq",
            "close_qfq",
            "open_hfq",
            "high_hfq",
            "low_hfq",
            "close_hfq",
        )
    names += ("vol", "amount", "change", "pct_chg")
    return tuple(
        (
            name,
            "VARCHAR"
            if name in ("ts_code", "trade_date", "end_date", "freq")
            else "DECIMAL(20,4)"
            if name in ("vol", "amount")
            else "DECIMAL(10,4)"
            if name == "pct_chg"
            else "DECIMAL(18,4)",
        )
        for name in names
    )


STOCK_MONTHLY_PARTITIONS = "cn_a_stock_months"


def monthly_dataset_id(source):
    StockMonthlySource(source)
    return "stk_period_bar_adj_month"


def monthly_asset_key(source):
    return "raw_tushare_" + monthly_dataset_id(source)


def monthly_job_name(source):
    return "raw_" + monthly_dataset_id(source) + "_update_job"


def monthly_check_names(source):
    return tuple(
        monthly_asset_key(source) + "_" + kind + "_check"
        for kind in ("file_contract", "key_partition", "delivery_reconciliation")
    )


def monthly_data_contract(source):
    return monthly_dataset_id(source) + "@1"


def monthly_source_doc(source):
    StockMonthlySource(source)
    return "https://tushare.pro/document/2?doc_id=365"


@dataclass(frozen=True, slots=True)
class MonthlyUpdatePolicy:
    timezone: str = "Asia/Shanghai"
    daily_start_time: str = "19:30"
    tick_min_seconds: int = 60

    def __post_init__(self):
        if self.timezone != "Asia/Shanghai" or self.daily_start_time != "19:30":
            raise ValueError("monthly_update_policy_invalid")
        if type(self.tick_min_seconds) is not int or self.tick_min_seconds <= 0:
            raise ValueError("monthly_update_budget_invalid:tick_min_seconds")


MONTHLY_UPDATE_POLICY = MonthlyUpdatePolicy()
