from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.stock_detail.stock_detail_query import (
    StockDetailQuery,
)
from src.biz.schemas.wealth.market.stock_detail_trend_channel import (
    StockTrendChannelBandDto,
    StockTrendChannelBarDto,
    StockTrendChannelDataStatusDto,
    StockTrendChannelFormulaDto,
    StockTrendChannelMetaDto,
    StockTrendChannelResponseDto,
    StockTrendChannelStockRefDto,
)
from src.foundation.clients.local_lake.stock_daily_trend_channel_contract import (
    DEFAULT_TREND_CHANNEL_LIMIT,
    FORMULA_KEY,
    FORMULA_VERSION,
    LONG_PERIOD,
    MAX_TREND_CHANNEL_LIMIT,
    SHORT_PERIOD,
    STOCK_TS_CODE_PATTERN,
)
from src.foundation.clients.local_lake.stock_daily_trend_channel_reader import (
    StockDailyTrendChannelLakeReader,
    StockDailyTrendChannelReadRequest,
)


class StockTrendChannelNotFoundError(ValueError):
    """Raised when the requested stock is not present in the serving master."""


class StockDetailTrendChannelQueryService:
    def __init__(
        self,
        lake_root: Path,
        *,
        reader: StockDailyTrendChannelLakeReader | None = None,
    ) -> None:
        self._reader = reader or StockDailyTrendChannelLakeReader(lake_root)
        self._stock_query = StockDetailQuery()
        self._context_query = MarketPageContextQuery()

    def close(self) -> None:
        self._reader.close()

    def read(
        self,
        session: Session,
        *,
        ts_code: str,
        end_date: date | None,
        limit: int = DEFAULT_TREND_CHANNEL_LIMIT,
    ) -> StockTrendChannelResponseDto:
        normalized_code = ts_code.strip().upper()
        if not STOCK_TS_CODE_PATTERN.fullmatch(normalized_code):
            raise ValueError("tsCode 必须是六位代码加 SH/SZ/BJ 后缀。")
        if not 1 <= limit <= MAX_TREND_CHANNEL_LIMIT:
            raise ValueError("limit 必须在 1 到 2000 之间。")

        security = self._stock_query.load_security(
            session,
            ts_code=normalized_code,
        )
        if security is None or security.security_type != "EQUITY":
            raise StockTrendChannelNotFoundError(
                f"未找到股票标的：{normalized_code}"
            )
        query_end_date = end_date or self._context_query.resolve_context(
            session,
            market="CN_A",
            requested_trade_date=None,
        ).trade_date
        result = self._reader.read(
            StockDailyTrendChannelReadRequest(
                ts_code=normalized_code,
                end_date=query_end_date,
                limit=limit,
            )
        )
        bars = [_to_bar(row) for row in result.rows]
        return StockTrendChannelResponseDto(
            stockRef=StockTrendChannelStockRefDto(
                tsCode=normalized_code,
                name=security.name,
            ),
            formula=StockTrendChannelFormulaDto(
                key=FORMULA_KEY,
                version=FORMULA_VERSION,
                shortPeriod=SHORT_PERIOD,
                longPeriod=LONG_PERIOD,
                seed="first_observation",
                stateRule="strict_close_breakout_inside_retention",
            ),
            bars=bars,
            meta=StockTrendChannelMetaDto(
                count=len(bars),
                limit=limit,
                endDate=query_end_date,
            ),
            dataStatus=StockTrendChannelDataStatusDto(
                status="READY" if bars else "EMPTY",
                observedTradeDate=result.observed_trade_date,
                note=None if bars else "该时间窗口暂无股票趋势通道数据。",
            ),
        )


def _to_bar(row: dict[str, object]) -> StockTrendChannelBarDto:
    return StockTrendChannelBarDto(
        tradeDate=row["trade_date"],
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        shortChannel=StockTrendChannelBandDto(
            upper=float(row["short_upper"]),
            lower=float(row["short_lower"]),
            position=row["short_position"],
            state=row["short_state"],
        ),
        longChannel=StockTrendChannelBandDto(
            upper=float(row["long_upper"]),
            lower=float(row["long_lower"]),
            position=row["long_position"],
            state=row["long_state"],
        ),
        combinedState=row["combined_state"],
    )
