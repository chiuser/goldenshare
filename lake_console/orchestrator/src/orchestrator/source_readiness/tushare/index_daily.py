from dataclasses import dataclass
from datetime import UTC, datetime

from orchestrator.defs.resources import TushareResource


INDEX_DAILY_READINESS_FIELDS = ("ts_code", "trade_date")
INDEX_DAILY_READINESS_LIMIT = 1
INDEX_DAILY_READINESS_PROBE_TS_CODE = "000001.SH"


@dataclass(frozen=True)
class IndexDailySourceReadiness:
    is_ready: bool
    trade_date: str
    probe_ts_code: str
    row_count: int
    checked_at: str
    reason: str


def check_index_daily_source_readiness(
    *,
    tushare: TushareResource,
    trade_date: str,
    probe_ts_code: str = INDEX_DAILY_READINESS_PROBE_TS_CODE,
    checked_at: datetime | None = None,
) -> IndexDailySourceReadiness:
    """Probe whether Tushare index_daily has published rows for a trade date."""
    compact_trade_date = trade_date.replace("-", "")
    evaluated_at = checked_at or datetime.now(UTC)
    result = tushare.call(
        "index_daily",
        {
            "ts_code": probe_ts_code,
            "start_date": compact_trade_date,
            "end_date": compact_trade_date,
            "limit": INDEX_DAILY_READINESS_LIMIT,
            "offset": 0,
        },
        INDEX_DAILY_READINESS_FIELDS,
    )
    if result.columns != INDEX_DAILY_READINESS_FIELDS and (result.columns or result.rows):
        raise RuntimeError(
            f"Tushare index_daily readiness returned columns {list(result.columns)}, "
            f"expected {list(INDEX_DAILY_READINESS_FIELDS)}."
        )

    invalid_rows = sorted(
        {
            (
                str(row.get("ts_code")),
                str(row.get("trade_date")),
            )
            for row in result.rows
            if str(row.get("ts_code")) != probe_ts_code
            or str(row.get("trade_date")) != compact_trade_date
        }
    )
    if invalid_rows:
        raise RuntimeError(
            "Tushare index_daily readiness returned rows outside the probe code/date: "
            f"{invalid_rows}"
        )

    row_count = len(result.rows)
    if row_count > 0:
        return IndexDailySourceReadiness(
            is_ready=True,
            trade_date=trade_date,
            probe_ts_code=probe_ts_code,
            row_count=row_count,
            checked_at=evaluated_at.isoformat(),
            reason="Tushare index_daily returned rows for the requested probe code/date.",
        )

    return IndexDailySourceReadiness(
        is_ready=False,
        trade_date=trade_date,
        probe_ts_code=probe_ts_code,
        row_count=0,
        checked_at=evaluated_at.isoformat(),
        reason="Tushare index_daily returned no rows for the requested probe code/date.",
    )
