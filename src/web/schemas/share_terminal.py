from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ShareKlineItem(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pre_close: Decimal | None = None
    pct_chg: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    turnover_rate: Decimal | None = None


class ShareKlineResponse(BaseModel):
    ts_code: str
    period: str
    adjust_mode: str
    items: list[ShareKlineItem]


class ShareQuoteResponse(BaseModel):
    ts_code: str
    name: str | None = None
    trade_date: date | None = None
    prev_close: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    change_amount: Decimal | None = None
    change_pct: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    turnover_rate: Decimal | None = None
    turnover_rate_f: Decimal | None = None
    volume_ratio: Decimal | None = None
    pe_ttm: Decimal | None = None
    dv_ratio: Decimal | None = None
    dv_ttm: Decimal | None = None
    total_share: Decimal | None = None
    float_share: Decimal | None = None
    free_share: Decimal | None = None
    pb: Decimal | None = None
    total_mv: Decimal | None = None
    circ_mv: Decimal | None = None


class ShareNewsItem(BaseModel):
    id: str
    occurred_at: date
    tag: str
    title: str
    summary: str | None = None


class ShareNewsResponse(BaseModel):
    ts_code: str
    items: list[ShareNewsItem]


class ShareSecuritySuggestionItem(BaseModel):
    ts_code: str
    symbol: str | None = None
    name: str
    cnspell: str | None = None
    market: str | None = None


class ShareSecuritySuggestionsResponse(BaseModel):
    query: str
    items: list[ShareSecuritySuggestionItem]
