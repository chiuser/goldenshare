from dataclasses import dataclass
from datetime import UTC, datetime

from orchestrator.defs.resources import TushareResource


STOCK_DAILY_READINESS_FIELDS = ("ts_code", "trade_date")
STOCK_DAILY_READINESS_LIMIT = 1


@dataclass(frozen=True)
class StockDailySourceReadiness:
    is_ready: bool
    trade_date: str
    row_count: int
    checked_at: str
    reason: str


def check_stock_daily_source_readiness(
    *,
    tushare: TushareResource,
    trade_date: str,
    checked_at: datetime | None = None,
) -> StockDailySourceReadiness:
    """Probe whether Tushare daily has published rows for a trade date."""
    compact_trade_date = trade_date.replace("-", "")
    evaluated_at = checked_at or datetime.now(UTC)
    result = tushare.call(
        "daily",
        {
            "trade_date": compact_trade_date,
            "limit": STOCK_DAILY_READINESS_LIMIT,
            "offset": 0,
        },
        STOCK_DAILY_READINESS_FIELDS,
    )
    if result.columns != STOCK_DAILY_READINESS_FIELDS and (result.columns or result.rows):
        raise RuntimeError(
            f"Tushare daily readiness returned columns {list(result.columns)}, "
            f"expected {list(STOCK_DAILY_READINESS_FIELDS)}."
        )

    invalid_trade_dates = sorted(
        {
            str(row.get("trade_date"))
            for row in result.rows
            if str(row.get("trade_date")) != compact_trade_date
        }
    )
    if invalid_trade_dates:
        raise RuntimeError(
            "Tushare daily readiness returned rows for unexpected trade_date values: "
            f"{invalid_trade_dates}"
        )

    row_count = len(result.rows)
    if row_count > 0:
        return StockDailySourceReadiness(
            is_ready=True,
            trade_date=trade_date,
            row_count=row_count,
            checked_at=evaluated_at.isoformat(),
            reason="Tushare daily returned rows for the requested trade_date.",
        )

    return StockDailySourceReadiness(
        is_ready=False,
        trade_date=trade_date,
        row_count=0,
        checked_at=evaluated_at.isoformat(),
        reason="Tushare daily returned no rows for the requested trade_date.",
    )
