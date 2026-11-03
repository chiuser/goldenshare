from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.stock_detail.stock_detail_query import (
    StockDetailQuery,
)
from src.biz.schemas.wealth.market.stock_detail import (
    StockChartDefaultsDto,
    StockDetailCapabilitiesDto,
    StockDetailDebugInfoDto,
    StockDetailPageInitResponseDto,
    StockDetailStockIdentityDto,
    StockDetailUserActionsDto,
)
from src.biz.services.wealth.market.stock_detail.stock_detail_field_mapper import (
    build_data_status,
    build_page_context,
    build_quote,
)
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_contracts import (
    StockDailyKlineInput, StockDailyKlineRequest, StockDailyKlineRow,
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
            pageContext=build_page_context(context),
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
                userActions=StockDetailUserActionsDto(alert=True, tradePlan=True),
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

    def prepare_kline_input(
        self, session: Session, request: StockDailyKlineRequest,
    ) -> StockDailyKlineInput:
        context = self._context_query.resolve_context(
            session, market="CN_A", requested_trade_date=request.end_date or request.trade_date,
        )
        security = self._load_security_or_raise(session, ts_code=request.ts_code)
        query_end_date = request.end_date or context.trade_date
        rows = self._query.load_kline_rows(
            session, ts_code=request.ts_code, end_date=query_end_date,
            start_date=request.start_date, limit=request.limit,
        )
        # Strict indexing distinguishes a missing column from a legitimate SQL NULL.
        bars = tuple(StockDailyKlineRow(
            trade_date=row["trade_date"],
            **{name: None if row[name] is None else float(row[name]) for name in (
                "open_qfq", "high_qfq", "low_qfq", "close_qfq", "pre_close", "change",
                "pct_chg", "vol", "amount", "turnover_rate", "volume_ratio",
            )},
        ) for row in rows)
        return StockDailyKlineInput(
            request, context, security.ts_code, security.name, query_end_date, bars,
        )

    def _load_security_or_raise(self, session: Session, *, ts_code: str) -> Security:
        security = self._query.load_security(session, ts_code=ts_code)
        if security is None:
            raise StockDetailNotFoundError(f"未找到股票标的：{ts_code}")
        return security

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
