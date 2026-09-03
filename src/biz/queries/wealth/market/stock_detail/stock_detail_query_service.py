from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.stock_detail.stock_detail_query import (
    StockDetailQuery,
)
from src.biz.schemas.wealth.market.context import MarketPageContextDto
from src.biz.schemas.wealth.market.stock_detail import (
    StockChartDefaultsDto,
    StockDetailCapabilitiesDto,
    StockDetailDebugInfoDto,
    StockDetailKlineResponseDto,
    StockDetailPageInitResponseDto,
    StockDetailStockIdentityDto,
    StockDetailStockRefDto,
    StockDetailUserActionsDto,
    StockKlineMetaDto,
)
from src.biz.services.wealth.market.stock_detail.stock_detail_field_mapper import (
    build_data_status,
    build_kline_bar,
    build_quote,
)
from src.foundation.config.local_minute_capability import (
    SUPPORTED_MINUTE_FREQS,
    resolve_local_minute_capability,
    resolve_stock_nine_turn_minute_capability,
)
from src.foundation.config.settings import get_settings
from src.foundation.config.stock_daily_trend_channel_capability import (
    resolve_stock_daily_trend_channel_capability,
)
from src.foundation.models.core_serving.security_serving import Security


class StockDetailNotFoundError(ValueError):
    """Raised when the requested stock does not exist in the serving master."""


class StockDetailQueryService:
    """Assemble wealth stock detail responses from serving facts."""

    def __init__(self) -> None:
        self._context_query = MarketPageContextQuery()
        self._query = StockDetailQuery()

    def build_page_init(
        self,
        session: Session,
        *,
        ts_code: str,
        trade_date: date | None,
        debug: bool,
    ) -> StockDetailPageInitResponseDto:
        context = self._context_query.resolve_context(session, market="CN_A", requested_trade_date=trade_date)
        security = self._load_security_or_raise(session, ts_code=ts_code)
        factor_row = self._query.load_latest_factor_row(
            session,
            ts_code=ts_code,
            expected_trade_date=context.trade_date,
        )
        observed_trade_date = factor_row["trade_date"] if factor_row is not None else None
        minute_capability = resolve_local_minute_capability(get_settings())
        nine_turn_minute_capability = resolve_stock_nine_turn_minute_capability(
            get_settings()
        )
        trend_channel_capability = resolve_stock_daily_trend_channel_capability(
            get_settings()
        )

        return StockDetailPageInitResponseDto(
            pageContext=self._to_context_dto(context),
            stock=self._to_stock_identity(security),
            quote=build_quote(factor_row) if factor_row is not None else None,
            chartDefaults=StockChartDefaultsDto(
                availableMainOverlays=(
                    ["MA", "BOLL", "TREND_CHANNEL"]
                    if trend_channel_capability.enabled
                    else ["MA", "BOLL"]
                )
            ),
            capabilities=StockDetailCapabilitiesDto(
                userActions=StockDetailUserActionsDto(),
                supportsMinute=minute_capability.enabled,
                minuteFrequencies=list(SUPPORTED_MINUTE_FREQS) if minute_capability.enabled else [],
                supportsNineTurn=True,
                supportsTrendChannel=trend_channel_capability.enabled,
                nineTurnPeriods=(
                    ["day", "30", "60", "90", "120"]
                    if nine_turn_minute_capability.enabled
                    else ["day"]
                ),
            ),
            dataStatus=build_data_status(
                expected_trade_date=context.trade_date,
                observed_trade_date=observed_trade_date,
            ),
            debugInfo=(
                self._build_debug_info(
                    ts_code=ts_code,
                    expected_trade_date=context.trade_date,
                    observed_trade_date=observed_trade_date,
                    limit=None,
                )
                if debug
                else None
            ),
        )

    def build_kline(
        self,
        session: Session,
        *,
        ts_code: str,
        period: str,
        adjustment: str,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        debug: bool,
    ) -> StockDetailKlineResponseDto:
        if period != "day":
            raise ValueError("股票详情首期只支持 period=day")
        if adjustment != "forward":
            raise ValueError("股票详情首期只支持 adjustment=forward")
        if limit < 1 or limit > 2000:
            raise ValueError("limit 必须在 1 到 2000 之间")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("startDate 不能晚于 endDate")

        context = self._context_query.resolve_context(
            session,
            market="CN_A",
            requested_trade_date=end_date or trade_date,
        )
        security = self._load_security_or_raise(session, ts_code=ts_code)
        query_end_date = end_date or context.trade_date
        rows = self._query.load_kline_rows(
            session,
            ts_code=ts_code,
            end_date=query_end_date,
            start_date=start_date,
            limit=limit,
        )
        observed_trade_date = rows[-1]["trade_date"] if rows else None

        return StockDetailKlineResponseDto(
            pageContext=self._to_context_dto(context),
            stockRef=StockDetailStockRefDto(tsCode=security.ts_code, name=security.name),
            period="day",
            adjustment="forward",
            sourceAdjustment="qfq",
            bars=[build_kline_bar(row) for row in rows],
            meta=StockKlineMetaDto(
                count=len(rows),
                limit=limit,
                startDate=start_date,
                endDate=query_end_date,
            ),
            dataStatus=build_data_status(
                expected_trade_date=query_end_date,
                observed_trade_date=observed_trade_date,
            ),
            debugInfo=(
                self._build_debug_info(
                    ts_code=ts_code,
                    expected_trade_date=query_end_date,
                    observed_trade_date=observed_trade_date,
                    limit=limit,
                )
                if debug
                else None
            ),
        )

    def _load_security_or_raise(self, session: Session, *, ts_code: str) -> Security:
        security = self._query.load_security(session, ts_code=ts_code)
        if security is None:
            raise StockDetailNotFoundError(f"未找到股票标的：{ts_code}")
        return security

    @staticmethod
    def _to_context_dto(context: MarketPageContext) -> MarketPageContextDto:
        return MarketPageContextDto(
            market="CN_A",
            tradeDate=context.trade_date,
            prevTradeDate=context.prev_trade_date,
            isTradingDay=context.is_trading_day,
            sessionStatus=context.session_status,  # type: ignore[arg-type]
            timezone="Asia/Shanghai",
            generatedAt=context.generated_at,
            source=context.source,  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_stock_identity(security: Security) -> StockDetailStockIdentityDto:
        tags = [value for value in [security.industry, security.area] if value]
        return StockDetailStockIdentityDto(
            tsCode=security.ts_code,
            symbol=security.symbol,
            name=security.name,
            market=security.market,
            exchange=security.exchange,
            industry=security.industry,
            area=security.area,
            listStatus=security.list_status,
            tags=tags,
        )

    @staticmethod
    def _build_debug_info(
        *,
        ts_code: str,
        expected_trade_date: date,
        observed_trade_date: date | None,
        limit: int | None,
    ) -> StockDetailDebugInfoDto:
        return StockDetailDebugInfoDto(
            sourceTables=["core_serving.security_serving", "core_serving.equity_factor_pro"],
            query={
                "tsCode": ts_code,
                "expectedTradeDate": expected_trade_date.isoformat(),
                "observedTradeDate": observed_trade_date.isoformat() if observed_trade_date is not None else None,
                "limit": limit,
            },
        )
