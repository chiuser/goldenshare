from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Protocol

from src.biz.services.wealth.market.detail_volume_display import format_daily_volume_display
from src.biz.schemas.wealth.market.index_detail import (
    IndexBollDto, IndexTrendChannelFactorsDto, IndexSseDailyKlineBarDto, IndexSseDailyKlineFactorsDto,
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


def build_quote(row: Mapping[str, Any], *, vol: Any, amount: Any) -> IndexDetailQuoteDto:
    change_pct = to_float(row.get("pct_chg"))
    vol = to_float(vol)
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
        vol=vol,
        volDisplay=format_daily_volume_display(vol),
        amount=to_float(amount),
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



def build_index_ma_factors(row):
    return IndexMovingAverageDto(**{f"ma{n}": to_float(row.get(f"ma_bfq_{n}"))
                                    for n in (5, 10, 20, 30, 60, 90, 250)})


def build_index_boll_factors(row):
    return IndexBollDto(upper=to_float(row.get("boll_upper_bfq")),
                        middle=to_float(row.get("boll_mid_bfq")), lower=to_float(row.get("boll_lower_bfq")))


def build_index_macd_factors(row):
    return IndexMacdDto(dif=to_float(row.get("macd_dif_bfq")), dea=to_float(row.get("macd_dea_bfq")),
                        macd=to_float(row.get("macd_bfq")))


def build_index_kdj_factors(row):
    return IndexKdjDto(k=to_float(row.get("kdj_k_bfq")), d=to_float(row.get("kdj_d_bfq")),
                       j=to_float(row.get("kdj_bfq")))


def build_index_common_factors(row):
    return dict(ma=build_index_ma_factors(row), boll=build_index_boll_factors(row),
                macd=build_index_macd_factors(row), kdj=build_index_kdj_factors(row))


def build_index_trend_channel_factors(fields, index):
    return IndexTrendChannelFactorsDto(
        shortUpper=fields["short_upper"][index], shortLower=fields["short_lower"][index],
        longUpper=fields["long_upper"][index], longLower=fields["long_lower"][index],
    )


def build_index_kline_bar_fields(row):
    high, low, pre_close, vol = (to_float(row.get(name)) for name in ("high", "low", "pre_close", "vol"))
    return dict(
        tradeDate=row["trade_date"], open=to_float(row.get("open")), high=high, low=low,
        close=to_float(row.get("close")), preClose=pre_close,
        change=to_float(row.get("change")), changePct=to_float(row.get("pct_change")),
        amplitude=calculate_amplitude(high=high, low=low, pre_close=pre_close),
        vol=vol, volDisplay=format_daily_volume_display(vol), amount=to_float(row.get("amount")),
    )


def build_kline_bar(row: Mapping[str, Any]) -> IndexKlineBarDto:
    return IndexKlineBarDto(**build_index_kline_bar_fields(row), factors=IndexKlineFactorsDto(**build_index_common_factors(row)))


def build_index_sse_daily_kline_bar(row, trend_factors):
    return IndexSseDailyKlineBarDto(**build_index_kline_bar_fields(row),
                                  factors=IndexSseDailyKlineFactorsDto(**build_index_common_factors(row), trendChannel=trend_factors))
