"""Source-preserving monthly Raw contracts; no resource or filesystem access."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum


class StockMonthlySource(str, Enum):
    PRIMARY_UNADJUSTED = "primary_unadjusted"
    PRIMARY_ADJUSTED = "primary_adjusted"


class MonthlyDateDisposition(str, Enum):
    ACCEPTED = "accepted"
    EXCLUDED_VERSION = "excluded_month_version"


def normalize_month_key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ValueError("month_key_must_be_yyyy_mm")
    date.fromisoformat(value + "-01")
    return value


def month_window(month: str) -> tuple[date, date]:
    normalize_month_key(month)
    first = date.fromisoformat(month + "-01")
    following = (
        date(first.year + 1, 1, 1)
        if first.month == 12
        else date(first.year, first.month + 1, 1)
    )
    return first, following


def request_date_for_month(month: str) -> str:
    normalize_month_key(month)
    if month == "2020-02":
        return "20200228"
    first = date.fromisoformat(month + "-01")
    day = calendar.monthrange(first.year, first.month)[1]
    return f"{first.year:04d}{first.month:02d}{day:02d}"


def classify_month_date(value: str) -> tuple[str, MonthlyDateDisposition]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("source_date_must_be_yyyymmdd")
    parsed = date(int(value[:4]), int(value[4:6]), int(value[6:]))
    month = f"{parsed.year:04d}-{parsed.month:02d}"
    if value == "20200229":
        return month, MonthlyDateDisposition.EXCLUDED_VERSION
    if value != request_date_for_month(month):
        raise ValueError("unexpected_month_source_date")
    return month, MonthlyDateDisposition.ACCEPTED


def monthly_source_api(source: StockMonthlySource) -> str:
    return (
        "stk_weekly_monthly"
        if StockMonthlySource(source) is StockMonthlySource.PRIMARY_UNADJUSTED
        else "stk_week_month_adj"
    )


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


def monthly_contract_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class StockMonthlyPolicy:
    prod_code_batch: int = 300
    max_codes: int = 10000
    max_prod_unit_rows: int = 10000
    max_year_rows: int = 120000
    max_capture_rows: int = 4020000
    page_limit: int = 6000
    max_pages: int = 4
    max_retries: int = 2
    max_update_rows: int = 10000

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value < (0 if name == "max_retries" else 1):
                raise ValueError(f"invalid_monthly_budget:{name}")
        if self.prod_code_batch > self.max_codes or self.page_limit > 6000:
            raise ValueError("monthly_batch_budget_invalid")
        if self.max_update_rows < self.page_limit:
            raise ValueError("monthly_update_row_budget_invalid")


def monthly_point_request(month: str, page: int, policy: StockMonthlyPolicy) -> dict:
    if type(page) is not int or not 0 <= page < policy.max_pages:
        raise ValueError("monthly_page_budget_exceeded")
    return {
        "freq": "month",
        "trade_date": request_date_for_month(month),
        "limit": policy.page_limit,
        "offset": page * policy.page_limit,
    }


@dataclass(frozen=True, slots=True)
class MonthlyYearInventory:
    year: int
    codes: tuple[str, ...]
    source_date_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if type(self.year) is not int or not 1 <= self.year <= 9998:
            raise ValueError("invalid_monthly_inventory_year")
        if any(
            not isinstance(c, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", c)
            for c in self.codes
        ):
            raise ValueError("invalid_monthly_inventory_codes")
        codes = tuple(sorted(self.codes))
        if len(codes) != len(set(codes)):
            raise ValueError("invalid_monthly_inventory_codes")
        dates = tuple(
            sorted((value, count) for value, count in self.source_date_counts)
        )
        if len(dates) != len({d for d, _ in dates}):
            raise ValueError("duplicate_monthly_inventory_date")
        for value, count in dates:
            classify_month_date(value)
            if (
                int(value[:4]) != self.year
                or type(count) is not int
                or not 0 < count <= len(codes)
            ):
                raise ValueError("invalid_monthly_date_count")
        if bool(codes) != bool(dates) or sum(count for _, count in dates) < len(codes):
            raise ValueError("monthly_inventory_not_closed")
        object.__setattr__(self, "codes", codes)
        object.__setattr__(self, "source_date_counts", dates)

    @property
    def source_rows(self) -> int:
        return sum(count for _, count in self.source_date_counts)

    @property
    def excluded_rows(self) -> int:
        return sum(
            count
            for value, count in self.source_date_counts
            if classify_month_date(value)[1] is MonthlyDateDisposition.EXCLUDED_VERSION
        )


@dataclass(frozen=True, slots=True)
class MonthlyProdUnit:
    unit_id: str
    source: StockMonthlySource
    sorted_codes: tuple[str, ...]
    source_date_start: str
    source_date_end: str
    max_rows: int


@dataclass(frozen=True, slots=True)
class MonthlyBootstrapPlan:
    plan_hash: str
    source: StockMonthlySource
    inventory_ref: str
    inventory_hash: str
    schema_hash: str
    policy: StockMonthlyPolicy
    source_rows: int
    excluded_rows: int
    accepted_rows: int
    months: tuple[str, ...]
    units: tuple[MonthlyProdUnit, ...]
    first_month: str
    last_month: str
    inventories: tuple[MonthlyYearInventory, ...]


@dataclass(frozen=True, slots=True)
class MonthlyBootstrapIOPolicy:
    prod_statement_timeout_ms: int = 30000
    prod_unit_seconds: int = 45
    prod_work_mem_mb: int = 32
    prod_csv_max_bytes: int = 64 * 1024 * 1024
    control_max_bytes: int = 1024 * 1024
    inventory_max_bytes: int = 16 * 1024 * 1024
    duckdb_memory_mb: int = 512
    duckdb_threads: int = 2
    duckdb_temp_mb: int = 2048
    process_shutdown_seconds: int = 2

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise ValueError("invalid_monthly_io_budget")
        if self.prod_statement_timeout_ms > self.prod_unit_seconds * 1000:
            raise ValueError("monthly_statement_exceeds_unit_timeout")


STOCK_MONTHLY_PARTITIONS = "cn_a_stock_months"


def monthly_dataset_id(source):
    return (
        "stk_period_bar_adj_month"
        if StockMonthlySource(source) is StockMonthlySource.PRIMARY_ADJUSTED
        else "stk_period_bar_month"
    )


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
    doc = (
        365
        if StockMonthlySource(source) is StockMonthlySource.PRIMARY_ADJUSTED
        else 336
    )
    return f"https://tushare.pro/document/2?doc_id={doc}"


@dataclass(frozen=True, slots=True)
class MonthlyUpdatePolicy:
    version: str = "completed-month-v1"
    timezone: str = "Asia/Shanghai"
    daily_start_time: str = "19:30"
    tick_min_seconds: int = 60
    history_verified_through: str = "2026-09"
    call_timeout_seconds: int = 20
    minimum_interval_seconds: int = 1
    max_daily_files: int = 31
    max_reference_rows: int = 320000
    max_reference_sql: int = 80
    max_materialization_versions_per_date: int = 10
    max_upstream_check_records: int = 320
    max_event_records_per_tick: int = 2000

    def __post_init__(self):
        normalize_month_key(self.history_verified_through)
        if (
            self.version != "completed-month-v1"
            or self.timezone != "Asia/Shanghai"
            or self.daily_start_time != "19:30"
        ):
            raise ValueError("monthly_update_policy_invalid")
        for name, value in asdict(self).items():
            if isinstance(value, str):
                continue
            if type(value) is not int or value <= 0:
                raise ValueError("monthly_update_budget_invalid:" + name)
        if (
            self.max_daily_files > 31
            or self.max_reference_rows > 320000
            or self.call_timeout_seconds > 20
            or self.max_materialization_versions_per_date > 10
            or self.max_upstream_check_records > 320
            or self.max_reference_sql > 80
            or self.max_event_records_per_tick > 2000
        ):
            raise ValueError("monthly_update_budget_exceeded")


MONTHLY_UPDATE_POLICY = MonthlyUpdatePolicy()
