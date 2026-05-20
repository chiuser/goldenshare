from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path


SUSPEND_FULL_DAY_PATCH_VERSION = "2026-05-21.full_day.v1"
SUSPEND_FULL_DAY_PATCH_SOURCE = (
    "audited stock_daily missing ranges marked S; raw suspend_d remains source mirror"
)
SUSPEND_FULL_DAY_RAW_OVERRIDE_VERSION = "2026-05-21.full_day_raw_override.v1"
SUSPEND_FULL_DAY_RAW_OVERRIDE_SOURCE = (
    "audited raw suspend_d conflict rows corrected in silver to S + NULL"
)

_PATCH_CSV_PATH = Path(__file__).with_name("suspend_full_day_ranges.csv")


@dataclass(frozen=True)
class SuspendFullDayRange:
    ts_code: str
    name: str
    start_date: str
    end_date: str


@dataclass(frozen=True)
class SuspendFullDayRawOverride:
    trade_date: str
    ts_code: str
    name: str
    suspend_type: str = "S"
    suspend_timing: str | None = None


SUSPEND_FULL_DAY_RAW_OVERRIDES: tuple[SuspendFullDayRawOverride, ...] = (
    SuspendFullDayRawOverride("2025-11-26", "688766.SH", "普冉股份"),
    SuspendFullDayRawOverride("2026-01-16", "688005.SH", "容百科技"),
)


@cache
def suspend_full_day_ranges() -> tuple[SuspendFullDayRange, ...]:
    with _PATCH_CSV_PATH.open(newline="", encoding="utf-8") as file:
        return tuple(
            SuspendFullDayRange(
                ts_code=row["ts_code"],
                name=row["name"],
                start_date=row["start_date"],
                end_date=row["end_date"],
            )
            for row in csv.DictReader(file)
        )


def _sql_string(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def suspend_full_day_ranges_values_sql(
    ranges: Iterable[SuspendFullDayRange] | None = None,
) -> str:
    patch_ranges = tuple(ranges or suspend_full_day_ranges())
    rows = [
        (
            _sql_string(patch_range.ts_code),
            _sql_string(patch_range.name),
            f"DATE {_sql_string(patch_range.start_date)}",
            f"DATE {_sql_string(patch_range.end_date)}",
        )
        for patch_range in patch_ranges
    ]
    if not rows:
        return "VALUES (NULL::VARCHAR, NULL::VARCHAR, NULL::DATE, NULL::DATE)"
    return "VALUES\n" + ",\n".join(f"  ({', '.join(row)})" for row in rows)


def suspend_full_day_raw_overrides_values_sql(
    overrides: Iterable[SuspendFullDayRawOverride] = SUSPEND_FULL_DAY_RAW_OVERRIDES,
) -> str:
    rows = [
        (
            _sql_string(override.ts_code),
            _sql_string(override.name),
            f"DATE {_sql_string(override.trade_date)}",
            _sql_string(override.suspend_type),
            "NULL::VARCHAR"
            if override.suspend_timing is None
            else _sql_string(override.suspend_timing),
        )
        for override in overrides
    ]
    if not rows:
        return "VALUES (NULL::VARCHAR, NULL::VARCHAR, NULL::DATE, NULL::VARCHAR, NULL::VARCHAR)"
    return "VALUES\n" + ",\n".join(f"  ({', '.join(row)})" for row in rows)


def suspend_full_day_range_samples(limit: int = 10) -> list[dict[str, str]]:
    return [
        {
            "ts_code": patch_range.ts_code,
            "name": patch_range.name,
            "start_date": patch_range.start_date,
            "end_date": patch_range.end_date,
        }
        for patch_range in suspend_full_day_ranges()[:limit]
    ]


def suspend_full_day_raw_override_samples(limit: int = 10) -> list[dict[str, str | None]]:
    return [
        {
            "trade_date": override.trade_date,
            "ts_code": override.ts_code,
            "name": override.name,
            "suspend_type": override.suspend_type,
            "suspend_timing": override.suspend_timing,
        }
        for override in SUSPEND_FULL_DAY_RAW_OVERRIDES[:limit]
    ]
