from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any
from time import monotonic

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.stock_detail.stock_detail_query import (
    STOCK_DAILY_BASIC_FIELDS, StockDetailQuery,
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
from src.foundation.clients.local_lake.reference_data_reader import STOCK_BASIC_LOCATION
from src.foundation.clients.reference_data import SecurityReferenceRow, local_reference_data
from src.foundation.models.core_serving.security_serving import Security
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.sources.read_context import SourceReadContext


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
        daily_lake=None,
        kernel_config=None,
    ) -> StockDetailPageInitResponseDto:
        context = self._context_query.resolve_context(session, market="CN_A", requested_trade_date=trade_date)
        security = self._load_security_or_raise(session, ts_code=ts_code)
        factor_row = self._query.load_latest_factor_row(
            session,
            ts_code=ts_code,
            expected_trade_date=context.trade_date,
        )
        observed_trade_date = factor_row["trade_date"] if factor_row is not None else None
        basic_source = "core_serving.equity_daily_basic"
        if factor_row is not None:
            if daily_lake is None:
                basic = self._query.load_daily_basic(session, ts_code=ts_code, trade_date=observed_trade_date)
            else:
                basic_source = "raw/tushare/daily_basic"
                control = ExecutionControl(arrived_at=monotonic(), config=kernel_config)
                basic = daily_lake.daily_rows(
                    "stock_daily_basic", ts_code, (observed_trade_date,), STOCK_DAILY_BASIC_FIELDS,
                    control=control, read_context=SourceReadContext(kernel_config),
                ).get(observed_trade_date)
            factor_row.update({field: basic[field] if basic is not None else None
                               for field in STOCK_DAILY_BASIC_FIELDS})
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
                    basic_source=basic_source if factor_row is not None else None,
                    security_source=(
                        STOCK_BASIC_LOCATION if local_reference_data(session) is not None
                        else "core_serving.security_serving"
                    ),
                )
                if debug
                else None
            ),
        )

    def prepare_kline_input(
        self, session: Session, request: StockDailyKlineRequest,
        *, load_rows: Callable[[str, date, date | None, int], Sequence[Mapping[str, Any]]],
        remaining_seconds: Callable[[], float] | None = None,
    ) -> StockDailyKlineInput:
        context = self._context_query.resolve_context(
            session, market="CN_A", requested_trade_date=request.end_date or request.trade_date,
            timeout_seconds=remaining_seconds() if remaining_seconds is not None else None,
        )
        security = self._load_security_or_raise(
            session, ts_code=request.ts_code,
            timeout_seconds=remaining_seconds() if remaining_seconds is not None else None,
        )
        query_end_date = request.end_date or context.trade_date
        rows = load_rows(request.ts_code, query_end_date, request.start_date, request.limit)
        # Strict indexing distinguishes a missing column from a legitimate SQL NULL.
        bars = tuple(StockDailyKlineRow(
            trade_date=row["trade_date"],
            open_qfq=None, high_qfq=None, low_qfq=None, close_qfq=None, vol=None, amount=None,
            **{name: None if row[name] is None else float(row[name]) for name in (
                "pre_close", "change", "pct_chg", "turnover_rate", "volume_ratio",
            )},
        ) for row in rows)
        return StockDailyKlineInput(
            request, context, security.ts_code, security.name, query_end_date, bars,
        )

    def _load_security_or_raise(
        self, session: Session, *, ts_code: str, timeout_seconds: float | None = None,
    ) -> Security | SecurityReferenceRow:
        security = self._query.load_security(session, ts_code=ts_code, timeout_seconds=timeout_seconds)
        if security is None:
            raise StockDetailNotFoundError(f"未找到股票标的：{ts_code}")
        return security

    @staticmethod
    def _to_stock_identity(security: Security | SecurityReferenceRow) -> StockDetailStockIdentityDto:
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
        basic_source: str | None,
        security_source: str,
    ) -> StockDetailDebugInfoDto:
        return StockDetailDebugInfoDto(
            sourceTables=[security_source, "core_serving.equity_factor_pro",
                          *([basic_source] if basic_source else [])],
            query={
                "tsCode": ts_code,
                "expectedTradeDate": expected_trade_date.isoformat(),
                "observedTradeDate": observed_trade_date.isoformat() if observed_trade_date is not None else None,
                "limit": limit,
            },
        )
