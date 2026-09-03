from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timezone
from decimal import Decimal
from typing import Any

from src.biz.schemas.wealth.market.watchlist import (
    WatchlistActivityDto,
    WatchlistDataStatusDto,
    WatchlistDirection,
    WatchlistItemDto,
    WatchlistMoneyFlowDto,
    WatchlistQuoteDto,
    WatchlistStockDto,
    WatchlistValuationDto,
)


def resolve_direction(value: Decimal | float | None) -> WatchlistDirection:
    if value is None:
        return "UNKNOWN"
    return "UP" if value > 0 else "DOWN" if value < 0 else "FLAT"


def build_watchlist_item(row: Mapping[str, Any]) -> WatchlistItemDto:
    fields = {
        "stock.name": row["name"],
        "stock.industry": row["industry"],
        "stock.listStatus": row["list_status"],
        "quote.price": row["price"],
        "quote.changePct": row["pct_chg"],
        "quote.vol": row["vol"],
        "valuation.peTtm": row["pe_ttm"],
        "valuation.pb": row["pb"],
        "activity.volumeRatio": row["volume_ratio"],
        "activity.turnoverRate": row["turnover_rate"],
        "moneyFlow.netAmount": row["net_mf_amount"],
    }
    added_at = row["created_at"]
    if added_at.tzinfo is None:
        added_at = added_at.replace(tzinfo=timezone.utc)
    return WatchlistItemDto(
        id=row["id"],
        addedAt=added_at,
        stock=WatchlistStockDto(
            tsCode=row["ts_code"],
            name=row["name"] or "--",
            industry=row["industry"],
            listStatus=row["list_status"],
        ),
        quote=WatchlistQuoteDto(
            price=row["price"],
            changePct=row["pct_chg"],
            vol=row["vol"],
            direction=resolve_direction(row["pct_chg"]),
        ),
        valuation=WatchlistValuationDto(peTtm=row["pe_ttm"], pb=row["pb"]),
        activity=WatchlistActivityDto(
            volumeRatio=row["volume_ratio"], turnoverRate=row["turnover_rate"]
        ),
        moneyFlow=WatchlistMoneyFlowDto(
            netAmount=row["net_mf_amount"],
            direction=resolve_direction(row["net_mf_amount"]),
        ),
        missingFields=[key for key, value in fields.items() if value is None],
    )


def build_watchlist_status(
    *,
    total_count: int,
    items: Sequence[WatchlistItemDto],
    expected_trade_date: date,
    observed_trade_date: date | None,
) -> WatchlistDataStatusDto:
    if total_count == 0:
        status = "EMPTY"
    elif observed_trade_date is None or any(item.missingFields for item in items):
        status = "PARTIAL"
    elif observed_trade_date < expected_trade_date:
        status = "DELAYED"
    else:
        status = "READY"
    return WatchlistDataStatusDto(
        status=status,
        expectedTradeDate=expected_trade_date,
        observedTradeDate=observed_trade_date,
    )
