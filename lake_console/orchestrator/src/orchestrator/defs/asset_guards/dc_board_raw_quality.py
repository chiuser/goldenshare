"""Shared Raw quality predicates for board checks and lake readiness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from orchestrator.defs.paths import raw_dc_daily_path, raw_dc_index_path, raw_dc_member_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_board import DC_DAILY_CATEGORIES, DC_INDEX_TYPES


@dataclass(frozen=True, slots=True)
class RawQualitySpec:
    dataset: str
    check_name: str
    path_builder: Callable[[Path, str], Path]
    schema: Sequence[object]
    key_columns: tuple[str, ...]
    identity_condition: str
    numeric_condition: str
    coverage_column: str | None = None
    coverage_values: tuple[str, ...] = ()


_INDEX_IDENTITY = (
    "ts_code IS NOT NULL AND regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '^BK[0-9]{4}\\.DC$') "
    f"AND idx_type IN ({', '.join(repr(value) for value in DC_INDEX_TYPES)}) "
    "AND name IS NOT NULL AND trim(CAST(name AS VARCHAR)) <> ''"
)
_INDEX_NUMERIC = (
    "(pct_change IS NOT NULL AND NOT isfinite(pct_change)) "
    "OR (leading_pct IS NOT NULL AND NOT isfinite(leading_pct)) "
    "OR (total_mv IS NOT NULL AND (NOT isfinite(total_mv) OR total_mv < 0)) "
    "OR (turnover_rate IS NOT NULL AND (NOT isfinite(turnover_rate) OR turnover_rate < 0)) "
    "OR (up_num IS NOT NULL AND up_num < 0) "
    "OR (down_num IS NOT NULL AND down_num < 0)"
)
_MEMBER_IDENTITY = (
    "ts_code IS NOT NULL AND regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '^BK[0-9]{4}\\.DC$') "
    "AND con_code IS NOT NULL AND regexp_full_match(trim(CAST(con_code AS VARCHAR)), '^[0-9]{6}\\.(SZ|SH|BJ)$') "
    "AND name IS NOT NULL AND trim(CAST(name AS VARCHAR)) <> ''"
)
_DAILY_IDENTITY = (
    "ts_code IS NOT NULL AND regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '^BK[0-9]{4}\\.DC$') "
    f"AND category IN ({', '.join(repr(value) for value in DC_DAILY_CATEGORIES)})"
)
_DAILY_NUMERIC = (
    "(close IS NOT NULL AND (NOT isfinite(close) OR close < 0)) "
    "OR (open IS NOT NULL AND (NOT isfinite(open) OR open < 0)) "
    "OR (high IS NOT NULL AND (NOT isfinite(high) OR high < 0)) "
    "OR (low IS NOT NULL AND (NOT isfinite(low) OR low < 0)) "
    "OR (vol IS NOT NULL AND (NOT isfinite(vol) OR vol < 0)) "
    "OR (amount IS NOT NULL AND (NOT isfinite(amount) OR amount < 0)) "
    "OR (swing IS NOT NULL AND (NOT isfinite(swing) OR swing < 0)) "
    "OR (turnover_rate IS NOT NULL AND (NOT isfinite(turnover_rate) OR turnover_rate < 0)) "
    "OR (change IS NOT NULL AND NOT isfinite(change)) "
    "OR (pct_change IS NOT NULL AND NOT isfinite(pct_change))"
)


RAW_DC_INDEX_QUALITY = RawQualitySpec(
    dataset="dc_index",
    check_name="raw_tushare_dc_index_core_check",
    path_builder=raw_dc_index_path,
    schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
    key_columns=("ts_code", "trade_date"),
    identity_condition=_INDEX_IDENTITY,
    numeric_condition=_INDEX_NUMERIC,
)
RAW_DC_MEMBER_QUALITY = RawQualitySpec(
    dataset="dc_member",
    check_name="raw_tushare_dc_member_core_check",
    path_builder=raw_dc_member_path,
    schema=RAW_TUSHARE_DC_MEMBER_SCHEMA,
    key_columns=("trade_date", "ts_code", "con_code"),
    identity_condition=_MEMBER_IDENTITY,
    numeric_condition="FALSE",
)
RAW_DC_DAILY_QUALITY = RawQualitySpec(
    dataset="dc_daily",
    check_name="raw_tushare_dc_daily_core_check",
    path_builder=raw_dc_daily_path,
    schema=RAW_TUSHARE_DC_DAILY_SCHEMA,
    key_columns=("ts_code", "trade_date", "category"),
    identity_condition=_DAILY_IDENTITY,
    numeric_condition=_DAILY_NUMERIC,
    coverage_column="category",
    coverage_values=DC_DAILY_CATEGORIES,
)

RAW_DC_QUALITY_SPECS = {
    "dc_index": RAW_DC_INDEX_QUALITY,
    "dc_member": RAW_DC_MEMBER_QUALITY,
    "dc_daily": RAW_DC_DAILY_QUALITY,
}


__all__ = [
    "RAW_DC_DAILY_QUALITY",
    "RAW_DC_INDEX_QUALITY",
    "RAW_DC_MEMBER_QUALITY",
    "RAW_DC_QUALITY_SPECS",
    "RawQualitySpec",
]
