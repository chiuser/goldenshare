from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class QuoteInstrument(BaseModel):
    instrument_id: str
    ts_code: str
    symbol: str
    name: str | None = None
    market: str | None = None
    security_type: str
    exchange: str | None = None
    industry: str | None = None
    list_status: str | None = None


class QuotePriceSummary(BaseModel):
    trade_date: date | None = None
    latest_price: Decimal | None = None
    pre_close: Decimal | None = None
    change_amount: Decimal | None = None
    pct_chg: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    vol: Decimal | None = None
    amount: Decimal | None = None
    turnover_rate: Decimal | None = None
    volume_ratio: Decimal | None = None
    pe_ttm: Decimal | None = None
    pb: Decimal | None = None
    total_mv: Decimal | None = None
    circ_mv: Decimal | None = None


class QuoteDefaultChart(BaseModel):
    default_period: str
    default_adjustment: str


class QuoteChartHeaderDefaults(BaseModel):
    ma5: Decimal | None = None
    ma10: Decimal | None = None
    ma15: Decimal | None = None
    ma20: Decimal | None = None
    ma30: Decimal | None = None
    ma60: Decimal | None = None
    ma120: Decimal | None = None
    ma250: Decimal | None = None
    volume_ma5: Decimal | None = None
    volume_ma10: Decimal | None = None
    macd: Decimal | None = None
    dif: Decimal | None = None
    dea: Decimal | None = None
    k: Decimal | None = None
    d: Decimal | None = None
    j: Decimal | None = None


class QuotePageInitResponse(BaseModel):
    instrument: QuoteInstrument
    price_summary: QuotePriceSummary
    default_chart: QuoteDefaultChart
    chart_header_defaults: QuoteChartHeaderDefaults


class QuoteKlineBar(BaseModel):
    trade_date: date
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    pre_close: Decimal | None = None
    change_amount: Decimal | None = None
    pct_chg: Decimal | None = None
    vol: Decimal | None = None
    amount: Decimal | None = None
    turnover_rate: Decimal | None = None
    ma5: Decimal | None = None
    ma10: Decimal | None = None
    ma15: Decimal | None = None
    ma20: Decimal | None = None
    ma30: Decimal | None = None
    ma60: Decimal | None = None
    ma120: Decimal | None = None
    ma250: Decimal | None = None
    volume_ma5: Decimal | None = None
    volume_ma10: Decimal | None = None
    macd: Decimal | None = None
    dif: Decimal | None = None
    dea: Decimal | None = None
    k: Decimal | None = None
    d: Decimal | None = None
    j: Decimal | None = None


class QuoteKlineMeta(BaseModel):
    bar_count: int
    has_more_history: bool
    next_start_date: date | None = None


class QuoteKlineResponse(BaseModel):
    instrument: QuoteInstrument
    period: str
    adjustment: str
    bars: list[QuoteKlineBar]
    meta: QuoteKlineMeta


class QuoteRelatedInfoItem(BaseModel):
    type: str
    title: str
    value: str
    action_target: str | None = None


class QuoteRelatedInfoCapability(BaseModel):
    related_etf: str | None = None


class QuoteRelatedInfoResponse(BaseModel):
    items: list[QuoteRelatedInfoItem]
    capability: QuoteRelatedInfoCapability | None = None


class QuoteAnnouncementsCapability(BaseModel):
    status: str
    reason: str


class QuoteAnnouncementItem(BaseModel):
    id: str
    title: str
    ann_date: date
    category: str | None = None
    source: str | None = None


class QuoteAnnouncementsResponse(BaseModel):
    items: list[QuoteAnnouncementItem]
    capability: QuoteAnnouncementsCapability


class MarketTradeCalendarItem(BaseModel):
    trade_date: date
    is_open: bool
    pretrade_date: date | None = None


class MarketTradeCalendarResponse(BaseModel):
    exchange: str
    items: list[MarketTradeCalendarItem]
