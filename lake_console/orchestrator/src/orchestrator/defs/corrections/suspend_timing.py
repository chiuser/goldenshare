from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


SUSPEND_TIMING_CORRECTION_VERSION = "2026-05-21.v1"


@dataclass(frozen=True)
class SuspendTimingCorrection:
    trade_date: str
    ts_code: str
    suspend_timing: str


SUSPEND_TIMING_CORRECTIONS: tuple[SuspendTimingCorrection, ...] = (
    SuspendTimingCorrection("2014-01-02", "000566.SZ", "13:55-15:00"),
    SuspendTimingCorrection("2014-03-13", "000678.SZ", "13:02-15:00"),
    SuspendTimingCorrection("2015-03-20", "000078.SZ", "10:29-15:00"),
    SuspendTimingCorrection("2015-04-27", "000609.SZ", "10:16-15:00"),
    SuspendTimingCorrection("2015-05-21", "000655.SZ", "11:07-15:00"),
    SuspendTimingCorrection("2015-07-06", "000055.SZ", "10:36-15:00"),
    SuspendTimingCorrection("2016-02-22", "000159.SZ", "10:55-15:00"),
    SuspendTimingCorrection("2016-03-16", "000510.SZ", "14:43-15:00"),
    SuspendTimingCorrection("2016-03-25", "000533.SZ", "13:48-15:00"),
    SuspendTimingCorrection("2016-08-18", "000659.SZ", "13:44-15:00"),
    SuspendTimingCorrection("2016-10-19", "000711.SZ", "13:15-15:00"),
    SuspendTimingCorrection("2017-08-14", "300272.SZ", "10:02-15:00"),
    SuspendTimingCorrection("2017-08-16", "000498.SZ", "09:48-15:00"),
    SuspendTimingCorrection("2017-12-08", "300731.SZ", "09:30-10:00"),
)


def _sql_string(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def suspend_timing_corrections_values_sql(
    corrections: Iterable[SuspendTimingCorrection] = SUSPEND_TIMING_CORRECTIONS,
) -> str:
    rows = [
        (
            _sql_string(correction.ts_code),
            f"DATE {_sql_string(correction.trade_date)}",
            _sql_string(correction.suspend_timing),
        )
        for correction in corrections
    ]
    if not rows:
        return "VALUES (NULL::VARCHAR, NULL::DATE, NULL::VARCHAR)"
    return "VALUES\n" + ",\n".join(f"  ({', '.join(row)})" for row in rows)


def suspend_timing_correction_samples(limit: int = 10) -> list[dict[str, str]]:
    return [
        {
            "trade_date": correction.trade_date,
            "ts_code": correction.ts_code,
            "suspend_timing": correction.suspend_timing,
        }
        for correction in SUSPEND_TIMING_CORRECTIONS[:limit]
    ]
