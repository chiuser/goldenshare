from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Protocol

from src.biz.schemas.wealth.market.index_detail import (
    IndexBollDto,
    IndexDetailDailyBasicDto,
    IndexDetailIdentityDto,
    IndexDetailPageContextDto,
    IndexDetailQuoteDto,
    IndexKdjDto,
    IndexKlineBarDto,
    IndexKlineFactorsDto,
    IndexMacdDto,
    IndexMovingAverageDto,
)


class MarketPageContextLike(Protocol):
    trade_date: date
    prev_trade_date: date | None
    is_trading_day: bool
    session_status: str
    generated_at: datetime
    source: str


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


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
    return ((high - low) / pre_close) * 100


def build_page_context(context: MarketPageContextLike) -> IndexDetailPageContextDto:
    return IndexDetailPageContextDto(
        market="CN_A",
        tradeDate=context.trade_date,
        prevTradeDate=context.prev_trade_date,
        isTradingDay=context.is_trading_day,
        sessionStatus=context.session_status,  # type: ignore[arg-type]
        timezone="Asia/Shanghai",
        generatedAt=context.generated_at,
        source=context.source,  # type: ignore[arg-type]
    )


def build_identity(row: Mapping[str, Any]) -> IndexDetailIdentityDto:
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("index identity name is missing")
    category = row.get("category")
    market = row.get("market")
    tags = [value for value in (category, market) if isinstance(value, str) and value]
    return IndexDetailIdentityDto(
        tsCode=str(row["ts_code"]),
        name=name,
        market=market,
        category=category,
        publisher=row.get("publisher"),
        tags=list(dict.fromkeys(tags)),
    )


def build_quote(row: Mapping[str, Any]) -> IndexDetailQuoteDto:
    change_pct = to_float(row.get("pct_chg"))
    return IndexDetailQuoteDto(
        tradeDate=row["trade_date"],
        point=to_float(row.get("close")),
        change=to_float(row.get("change_amount")),
        changePct=change_pct,
        direction=resolve_direction(change_pct),  # type: ignore[arg-type]
        open=to_float(row.get("open")),
        high=to_float(row.get("high")),
        low=to_float(row.get("low")),
        preClose=to_float(row.get("pre_close")),
        vol=to_float(row.get("factor_vol")),
        amount=to_float(row.get("factor_amount")),
    )


def build_daily_basic(row: Mapping[str, Any]) -> IndexDetailDailyBasicDto:
    return IndexDetailDailyBasicDto(
        tradeDate=row["trade_date"],
        pe=to_float(row.get("pe")),
        peTtm=to_float(row.get("pe_ttm")),
        pb=to_float(row.get("pb")),
        turnoverRate=to_float(row.get("turnover_rate")),
        floatMv=to_float(row.get("float_mv")),
        totalMv=to_float(row.get("total_mv")),
    )


def build_kline_bar(row: Mapping[str, Any]) -> IndexKlineBarDto:
    high = to_float(row.get("high"))
    low = to_float(row.get("low"))
    pre_close = to_float(row.get("pre_close"))
    return IndexKlineBarDto(
        tradeDate=row["trade_date"],
        open=to_float(row.get("open")),
        high=high,
        low=low,
        close=to_float(row.get("close")),
        preClose=pre_close,
        change=to_float(row.get("change")),
        changePct=to_float(row.get("pct_change")),
        amplitude=calculate_amplitude(high=high, low=low, pre_close=pre_close),
        vol=to_float(row.get("vol")),
        amount=to_float(row.get("amount")),
        factors=IndexKlineFactorsDto(
            ma=IndexMovingAverageDto(
                ma5=to_float(row.get("ma_bfq_5")),
                ma10=to_float(row.get("ma_bfq_10")),
                ma20=to_float(row.get("ma_bfq_20")),
                ma30=to_float(row.get("ma_bfq_30")),
                ma60=to_float(row.get("ma_bfq_60")),
                ma90=to_float(row.get("ma_bfq_90")),
                ma250=to_float(row.get("ma_bfq_250")),
            ),
            boll=IndexBollDto(
                upper=to_float(row.get("boll_upper_bfq")),
                middle=to_float(row.get("boll_mid_bfq")),
                lower=to_float(row.get("boll_lower_bfq")),
            ),
            macd=IndexMacdDto(
                dif=to_float(row.get("macd_dif_bfq")),
                dea=to_float(row.get("macd_dea_bfq")),
                macd=to_float(row.get("macd_bfq")),
            ),
            kdj=IndexKdjDto(
                k=to_float(row.get("kdj_k_bfq")),
                d=to_float(row.get("kdj_d_bfq")),
                j=to_float(row.get("kdj_bfq")),
            ),
        ),
    )
