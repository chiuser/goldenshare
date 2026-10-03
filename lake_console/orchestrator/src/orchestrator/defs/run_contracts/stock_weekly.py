"""Immutable contracts for source-preserving weekly Raw delivery; no IO."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum


class StockWeeklySource(str, Enum):
    PRIMARY_UNADJUSTED = "primary_unadjusted"
    PRIMARY_ADJUSTED = "primary_adjusted"
    ALTERNATE_WEEKLY = "weekly"


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
ALTERNATE_WEEKLY_FIELDS = (
    "ts_code",
    "trade_date",
    "close",
    "open",
    "high",
    "low",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)


def weekly_dataset_id(source: StockWeeklySource) -> str:
    source = StockWeeklySource(source)
    if source is StockWeeklySource.PRIMARY_UNADJUSTED:
        return "stk_period_bar_week"
    if source is StockWeeklySource.PRIMARY_ADJUSTED:
        return "stk_period_bar_adj_week"
    return "weekly"


def weekly_source_api(source: StockWeeklySource) -> str:
    source = StockWeeklySource(source)
    if source is StockWeeklySource.PRIMARY_UNADJUSTED:
        return "stk_weekly_monthly"
    if source is StockWeeklySource.PRIMARY_ADJUSTED:
        return "stk_week_month_adj"
    return "weekly"


def weekly_column_specs(source: StockWeeklySource) -> tuple[tuple[str, str, str], ...]:
    source = StockWeeklySource(source)
    fields = (
        PRIMARY_WEEKLY_FIELDS
        if source is StockWeeklySource.PRIMARY_UNADJUSTED
        else ADJUSTED_WEEKLY_FIELDS
        if source is StockWeeklySource.PRIMARY_ADJUSTED
        else ALTERNATE_WEEKLY_FIELDS
    )
    specs = []
    for field in fields:
        if field in ("ts_code", "trade_date", "end_date", "freq"):
            type_name = "VARCHAR"
        elif source is StockWeeklySource.ALTERNATE_WEEKLY:
            type_name = "DOUBLE"
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


def weekly_key_columns(source: StockWeeklySource) -> tuple[str, ...]:
    source = StockWeeklySource(source)
    return (
        ("ts_code", "trade_date")
        if source is StockWeeklySource.ALTERNATE_WEEKLY
        else ("ts_code", "trade_date", "freq")
    )


def weekly_required_columns(source: StockWeeklySource) -> tuple[str, ...]:
    source = StockWeeklySource(source)
    if source is StockWeeklySource.ALTERNATE_WEEKLY:
        return (
            "ts_code",
            "trade_date",
            "close",
            "open",
            "high",
            "low",
            "vol",
            "amount",
        )
    return weekly_key_columns(source)


def normalize_week_key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("week_key_must_be_iso_friday")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or parsed.weekday() != 4:
        raise ValueError("week_key_must_be_iso_friday")
    return value


def normalize_weekly_code(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", value):
        raise ValueError("invalid_source_ts_code")
    return value


class WeeklyAvailability(str, Enum):
    AVAILABLE = "source_available"
    EMPTY_CONFIRMED = "source_empty_confirmed"
    FAILED = "source_failed"
    UNCHECKED = "source_unchecked"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    CONTRACT_BLOCKED = "source_contract_blocked"


@dataclass(frozen=True, slots=True)
class WeeklyBudget:
    source_concurrency: int = 1
    minimum_interval_seconds: float = 1.0
    max_retries: int = 2
    call_timeout_seconds: int = 20
    prod_code_batch: int = 300
    fetch_batch_rows: int = 10_000
    prod_statement_timeout_ms: int = 30_000
    prod_unit_seconds: int = 45
    prod_work_mem: str = "32MB"
    prod_max_connections: int = 1
    max_source_rows_per_prod_unit: int = 30_000
    max_codes: int = 10_000
    max_candidate_keys: int = 250_000
    objects_per_batch: int = 20
    duckdb_memory_limit: str = "512MiB"
    duckdb_threads: int = 2
    duckdb_max_temp: str = "2GiB"
    max_phase_rows: int = 12_000_000
    max_phase_files: int = 3_000
    event_partition_batch: int = 100
    event_write_batch: int = 100
    event_record_read_cap: int = 20_000
    event_write_cap: int = 12_000
    failure_sample_limit: int = 10
    progress_interval_seconds: int = 10

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name == "minimum_interval_seconds":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("invalid_request_interval")
                if not math.isfinite(value) or value < 1:
                    raise ValueError("invalid_request_interval")
            elif name in ("prod_work_mem", "duckdb_memory_limit", "duckdb_max_temp"):
                if not isinstance(value, str) or not re.fullmatch(
                    r"[1-9][0-9]*(MiB|GiB|MB|GB)", value
                ):
                    raise ValueError(f"invalid_size_budget:{name}")
            elif (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (0 if name == "max_retries" else 1)
            ):
                raise ValueError(f"invalid_integer_budget:{name}")
        if self.source_concurrency != 1 or self.prod_max_connections != 1:
            raise ValueError("weekly_source_concurrency_must_be_one")
        if self.fetch_batch_rows > self.max_source_rows_per_prod_unit:
            raise ValueError("fetch_batch_exceeds_unit_rows")
        if self.prod_statement_timeout_ms > self.prod_unit_seconds * 1000:
            raise ValueError("statement_timeout_exceeds_unit_deadline")


@dataclass(frozen=True, slots=True)
class WeeklyCandidate:
    ts_code: str
    week_key: str
    availability: WeeklyAvailability
    source_evidence_ref: str | None = None
    source_evidence_hash: str | None = None

    def __post_init__(self) -> None:
        normalize_weekly_code(self.ts_code)
        normalize_week_key(self.week_key)
        object.__setattr__(self, "availability", WeeklyAvailability(self.availability))
        if self.availability in (
            WeeklyAvailability.AVAILABLE,
            WeeklyAvailability.EMPTY_CONFIRMED,
        ):
            if (
                not self.source_evidence_ref
                or not isinstance(self.source_evidence_hash, str)
                or not re.fullmatch(r"[a-f0-9]{64}", self.source_evidence_hash)
            ):
                raise ValueError("availability_requires_source_evidence")


@dataclass(frozen=True, slots=True)
class WeeklyHistoryScope:
    anchor_start: str
    anchor_end: str
    candidates: tuple[WeeklyCandidate, ...]
    expected_key_ref: str
    expected_key_hash: str
    excluded_week_keys: tuple[str, ...] = ()
    budget: WeeklyBudget = WeeklyBudget()

    def __post_init__(self) -> None:
        normalize_week_key(self.anchor_start)
        normalize_week_key(self.anchor_end)
        if self.anchor_start > self.anchor_end:
            raise ValueError("reversed_week_scope")
        if not self.expected_key_ref or not re.fullmatch(
            r"[a-f0-9]{64}", self.expected_key_hash
        ):
            raise ValueError("expected_evidence_required")
        candidates = tuple(self.candidates)
        if len(candidates) > self.budget.max_candidate_keys:
            raise ValueError("candidate_key_budget_exceeded")
        if len({c.ts_code for c in candidates}) > self.budget.max_codes:
            raise ValueError("code_budget_exceeded")
        keys = [(c.ts_code, c.week_key) for c in candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_candidate_key")
        if any(
            not self.anchor_start <= c.week_key <= self.anchor_end for c in candidates
        ):
            raise ValueError("candidate_outside_scope")
        excluded = tuple(sorted(set(self.excluded_week_keys)))
        for key in excluded:
            normalize_week_key(key)
        object.__setattr__(
            self,
            "candidates",
            tuple(sorted(candidates, key=lambda c: (c.ts_code, c.week_key))),
        )
        object.__setattr__(self, "excluded_week_keys", excluded)


@dataclass(frozen=True, slots=True)
class ProdYearInventory:
    year: int
    codes: tuple[str, ...]
    source_rows: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.year, bool)
            or not isinstance(self.year, int)
            or not 1 <= self.year <= 9998
        ):
            raise ValueError("invalid_inventory_year")
        codes = tuple(sorted(self.codes))
        for code in codes:
            normalize_weekly_code(code)
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate_inventory_code")
        if (
            isinstance(self.source_rows, bool)
            or not isinstance(self.source_rows, int)
            or self.source_rows < len(codes)
        ):
            raise ValueError("invalid_inventory_row_count")
        if not codes and self.source_rows:
            raise ValueError("rows_without_inventory_codes")
        object.__setattr__(self, "codes", codes)


@dataclass(frozen=True, slots=True)
class ProdWeeklyScope:
    source: StockWeeklySource
    inventories: tuple[ProdYearInventory, ...]
    inventory_ref: str
    inventory_hash: str
    budget: WeeklyBudget = WeeklyBudget()

    def __post_init__(self) -> None:
        source = StockWeeklySource(self.source)
        if source is StockWeeklySource.ALTERNATE_WEEKLY:
            raise ValueError("alternate_has_no_prod_bootstrap")
        if not self.inventory_ref or not re.fullmatch(
            r"[a-f0-9]{64}", self.inventory_hash
        ):
            raise ValueError("inventory_evidence_required")
        inventories = tuple(sorted(self.inventories, key=lambda x: x.year))
        if len({x.year for x in inventories}) != len(inventories):
            raise ValueError("duplicate_inventory_year")
        if any(len(x.codes) > self.budget.max_codes for x in inventories):
            raise ValueError("code_budget_exceeded")
        if sum(x.source_rows for x in inventories) > self.budget.max_phase_rows:
            raise ValueError("phase_row_budget_exceeded")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "inventories", inventories)


@dataclass(frozen=True, slots=True)
class WeeklySourceUnit:
    unit_id: str
    source: StockWeeklySource
    ts_code: str
    anchor_start: str
    anchor_end: str
    request_start: date
    request_end: date
    expected_key_ref: str
    expected_key_hash: str
    expected_key_count: int
    max_rows: int
    excluded_week_keys: tuple[str, ...]
    source_evidence: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ProdWeeklyUnit:
    unit_id: str
    source: StockWeeklySource
    sorted_codes: tuple[str, ...]
    source_date_start: date
    source_date_end: date  # exclusive
    schema_hash: str
    max_rows: int


@dataclass(frozen=True, slots=True)
class WeeklyPlanManifest:
    plan_hash: str
    source: StockWeeklySource
    evidence_ref: str
    evidence_hash: str
    units: tuple[WeeklySourceUnit | ProdWeeklyUnit, ...]
    budget: WeeklyBudget
    request_cap: int
    planned_key_count: int
    skipped_key_count: int
    skipped_reason_counts: tuple[tuple[str, int], ...]
