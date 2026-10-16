"""Immutable contracts for source-preserving weekly Raw delivery; no IO."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import Enum


class StockWeeklySource(str, Enum):
    PRIMARY_ADJUSTED = "primary_adjusted"


STOCK_WEEKLY_PARTITIONS = "cn_a_stock_week_ends"
PRIMARY_WEEKLY_FIELDS = (
    "ts_code",
    "trade_date",
    "end_date",
    "freq",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "vol",
    "amount",
    "change",
    "pct_chg",
)
ADJUSTED_WEEKLY_FIELDS = (
    *PRIMARY_WEEKLY_FIELDS[:9],
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "open_hfq",
    "high_hfq",
    "low_hfq",
    "close_hfq",
    *PRIMARY_WEEKLY_FIELDS[9:],
)


def weekly_dataset_id(source: StockWeeklySource):
    StockWeeklySource(source)
    return "stk_period_bar_adj_week"


def weekly_source_api(source: StockWeeklySource):
    StockWeeklySource(source)
    return "stk_week_month_adj"


def weekly_column_specs(source: StockWeeklySource) -> tuple[tuple[str, str, str], ...]:
    source = StockWeeklySource(source)
    fields = ADJUSTED_WEEKLY_FIELDS
    specs = []
    for field in fields:
        if field in ("ts_code", "trade_date", "end_date", "freq"):
            type_name = "VARCHAR"
        elif field in ("vol", "amount"):
            type_name = "DECIMAL(20,4)"
        elif field == "pct_chg":
            type_name = "DECIMAL(10,4)"
        else:
            type_name = "DECIMAL(18,4)"
        description = (
            "Tushare 原始股票代码"
            if field == "ts_code"
            else "Tushare 原始日期，YYYYMMDD 字符串"
            if field in ("trade_date", "end_date")
            else "源频度，固定 week"
            if field == "freq"
            else "Tushare 源行情值，保留原单位与复权口径"
        )
        specs.append((field, type_name, description))
    return tuple(specs)


def stable_weekly_hash(value: object) -> str:
    def encode(item: object) -> str:
        if type(item) is date:
            return item.isoformat()
        raise TypeError(f"unsupported_manifest_type:{type(item).__name__}")

    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=encode,
        ).encode()
    ).hexdigest()


def weekly_schema_hash(source: StockWeeklySource) -> str:
    return stable_weekly_hash(
        [(name, kind) for name, kind, _ in weekly_column_specs(source)]
    )


def weekly_key_columns(source: StockWeeklySource):
    StockWeeklySource(source)
    return ("ts_code", "trade_date", "freq")


def weekly_required_columns(source: StockWeeklySource):
    StockWeeklySource(source)
    return weekly_key_columns(source)


def normalize_week_key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("week_key_must_be_iso_friday")  # noqa: TRY004 -- Preserve validated input error contract.
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or parsed.weekday() != 4:
        raise ValueError("week_key_must_be_iso_friday")
    return value


def weekly_asset_key(source: StockWeeklySource):
    StockWeeklySource(source)
    return "raw_tushare_stk_period_bar_adj_week"


def weekly_check_names(source: StockWeeklySource) -> tuple[str, ...]:
    return tuple(
        f"{weekly_asset_key(source)}_{kind}_check"
        for kind in (
            "file_contract",
            "key_partition",
            "delivery_reconciliation",
        )
    )


def weekly_job_name(source: StockWeeklySource):
    StockWeeklySource(source)
    return "raw_stk_period_bar_adj_week_update_job"


def weekly_data_contract(source: StockWeeklySource):
    StockWeeklySource(source)
    return "tushare_stk_period_bar_adj_week"


def weekly_source_doc(source: StockWeeklySource):
    StockWeeklySource(source)
    return (
        "docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md"
    )
