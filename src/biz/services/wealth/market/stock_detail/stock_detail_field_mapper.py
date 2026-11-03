from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from src.biz.services.wealth.market.detail_volume_display import format_daily_volume_display
from src.biz.schemas.wealth.market.stock_detail import (
    StockDetailDataStatusDto,
    StockKlineBarDto,
    StockKlineFactorDto,
    StockQuoteSnapshotDto,
)

from src.biz.schemas.wealth.market.context import MarketPageContextDto
from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext
from .stock_daily_kline_contracts import StockDailyKlineRow


def build_page_context(context: MarketPageContext) -> MarketPageContextDto:
    return MarketPageContextDto(
        market="CN_A", tradeDate=context.trade_date, prevTradeDate=context.prev_trade_date,
        isTradingDay=context.is_trading_day, sessionStatus=context.session_status,
        timezone="Asia/Shanghai", generatedAt=context.generated_at, source=context.source,
    )


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 10)


def resolve_direction(change_pct: float | None) -> str:
    if change_pct is None:
        return "UNKNOWN"
    if change_pct > 0:
        return "UP"
    if change_pct < 0:
        return "DOWN"
    return "FLAT"


def calculate_amplitude(*, high: float | None, low: float | None, pre_close: float | None) -> float | None:
    if high is None or low is None or pre_close is None or pre_close == 0:
        return None
    return round(((high - low) / pre_close) * 100, 10)


def build_data_status(*, expected_trade_date: date, observed_trade_date: date | None) -> StockDetailDataStatusDto:
    if observed_trade_date is None:
        return StockDetailDataStatusDto(
            status="EMPTY",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=None,
            note="stock detail source is empty",
        )
    if observed_trade_date < expected_trade_date:
        return StockDetailDataStatusDto(
            status="DELAYED",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            note="stock detail source date lagged",
        )
    return StockDetailDataStatusDto(
        status="READY",
        expectedTradeDate=expected_trade_date,
        observedTradeDate=observed_trade_date,
        note="stock detail source ready",
    )


def build_quote(row: Mapping[str, Any]) -> StockQuoteSnapshotDto:
    change_pct = to_float(row.get("pct_chg"))
    close = to_float(row.get("close_qfq"))
    vol = to_float(row.get("vol"))
    return StockQuoteSnapshotDto(
        tradeDate=row["trade_date"],
        price=close,
        change=to_float(row.get("change")),
        changePct=change_pct,
        direction=resolve_direction(change_pct),  # type: ignore[arg-type]
        open=to_float(row.get("open_qfq")),
        high=to_float(row.get("high_qfq")),
        low=to_float(row.get("low_qfq")),
        close=close,
        preClose=to_float(row.get("pre_close")),
        turnoverRate=to_float(row.get("turnover_rate")),
        volumeRatio=to_float(row.get("volume_ratio")),
        vol=vol,
        volDisplay=format_daily_volume_display(vol),
        amount=to_float(row.get("amount")),
    )


def build_kline_bar(row: StockDailyKlineRow, factors: StockKlineFactorDto) -> StockKlineBarDto:
    open_price = to_float(row.open_qfq)
    high_price = to_float(row.high_qfq)
    low_price = to_float(row.low_qfq)
    close_price = to_float(row.close_qfq)
    pre_close = to_float(row.pre_close)
    change_pct = to_float(row.pct_chg)
    vol = to_float(row.vol)
    return StockKlineBarDto(
        tradeDate=row.trade_date,
        open=open_price, high=high_price, low=low_price, close=close_price,
        preClose=pre_close, change=to_float(row.change), changePct=change_pct,
        amplitude=calculate_amplitude(high=high_price, low=low_price, pre_close=pre_close),
        vol=vol, volDisplay=format_daily_volume_display(vol), amount=to_float(row.amount),
        turnoverRate=to_float(row.turnover_rate), volumeRatio=to_float(row.volume_ratio),
        factors=factors,
    )
