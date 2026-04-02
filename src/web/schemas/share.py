from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ShareMarketRow(BaseModel):
    ts_code: str
    name: str | None = None
    trade_date: date | None = None
    close: Decimal | None = None
    pct_change: Decimal | None = None
    amount: Decimal | None = None


class ShareMarketSummary(BaseModel):
    as_of_date: date | None = None
    total_symbols: int
    up_count: int | None = None
    down_count: int | None = None
    flat_count: int | None = None
    avg_pct_change: Decimal | None = None
    total_amount: Decimal | None = None


class ShareMarketOverviewResponse(BaseModel):
    available: bool
    unavailable_reason: str | None = None
    summary: ShareMarketSummary | None = None
    top_by_amount: list[ShareMarketRow] = []
    top_gainers: list[ShareMarketRow] = []
    top_losers: list[ShareMarketRow] = []
