from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.queries.wealth.market.index_detail.index_detail_query import IndexDetailQuery
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailCapabilitiesDto,
    IndexDetailChartDefaultsDto,
    IndexDetailConstituentBreadthDto,
    IndexDetailIdentityDto,
    IndexDetailNineTurnPeriod,
    IndexDetailPageInitResponseDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_field_mapper import (
    build_daily_basic,
    build_identity,
    build_page_context,
    build_quote,
)
from src.biz.services.wealth.market.index_detail.index_detail_status_resolver import IndexDetailStatusResolver
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailUniverseService,
)
from src.foundation.config.local_minute_capability import (
    SUPPORTED_MINUTE_FREQS,
    resolve_index_minute_capability,
    resolve_index_nine_turn_minute_capability,
)
from src.foundation.config.settings import get_settings


_DAILY_BASIC_FIELDS = ("pe", "pe_ttm", "pb", "turnover_rate", "float_mv", "total_mv")


class IndexDetailPageQueryService:
    """Assemble the index-detail page initialization contract."""

    def __init__(self) -> None:
        self._universe_service = IndexDetailUniverseService()
        self._context_query = MarketPageContextQuery()
        self._query = IndexDetailQuery()
        self._status_resolver = IndexDetailStatusResolver()

    def build_page_init(self, session: Session, *, ts_code: str,
                        trade_date: date | None) -> IndexDetailPageInitResponseDto:
        return self.query_page_init(session, ts_code=ts_code, trade_date=trade_date)[0]

    def query_page_init(
        self,
        session: Session,
        *,
        ts_code: str,
        trade_date: date | None,
    ) -> tuple[IndexDetailPageInitResponseDto, int, int]:
        self._universe_service.require_supported(ts_code)
        identity = self._load_identity_or_raise(session, ts_code=ts_code)
        context = self._context_query.resolve_context(
            session,
            market="CN_A",
            requested_trade_date=trade_date,
        )
        quote_row = self._query.load_latest_quote(
            session,
            ts_code=ts_code,
            expected_trade_date=context.trade_date,
        )
        if quote_row is None:
            data_status = self._status_resolver.resolve(
                expected_trade_date=context.trade_date,
                observed_trade_date=None,
                empty=True,
                partial=False,
            )
            return IndexDetailPageInitResponseDto(
                pageContext=build_page_context(context),
                asOfTradeDate=None,
                index=identity,
                quote=None,
                dailyBasic=None,
                constituentBreadth=None,
                chartDefaults=self._build_chart_defaults(ts_code=ts_code),
                capabilities=self._build_capabilities(ts_code=ts_code),
                dataStatus=data_status,
            ), 0, 0

        as_of_trade_date = quote_row["trade_date"]
        factor_missing_count = sum(
            1
            for field_name in ("factor_vol", "factor_amount")
            if quote_row.get(field_name) is None
        )
        if quote_row.get("factor_trade_date") is None:
            factor_missing_count = 2

        daily_basic_row = self._query.load_daily_basic(
            session,
            ts_code=ts_code,
            trade_date=as_of_trade_date,
        )
        daily_basic_missing_count = (
            len(_DAILY_BASIC_FIELDS)
            if daily_basic_row is None
            else sum(1 for field_name in _DAILY_BASIC_FIELDS if daily_basic_row.get(field_name) is None)
        )

        weight_trade_date = self._query.load_weight_trade_date(
            session,
            ts_code=ts_code,
            contribution_trade_date=as_of_trade_date,
        )
        breadth = None
        breadth_missing_count: int | None = None
        if weight_trade_date is not None:
            breadth_counts = self._query.load_breadth(
                session,
                ts_code=ts_code,
                contribution_trade_date=as_of_trade_date,
                weight_trade_date=weight_trade_date,
            )
            breadth_missing_count = breadth_counts["total_count"] - breadth_counts["matched_count"]
            if (
                breadth_counts["up_count"] + breadth_counts["flat_count"] + breadth_counts["down_count"]
                != breadth_counts["matched_count"]
                or breadth_counts["matched_count"] + breadth_missing_count != breadth_counts["total_count"]
            ):
                raise ValueError("constituent breadth count invariant failed")
            breadth_status = self._status_resolver.resolve(
                expected_trade_date=as_of_trade_date,
                observed_trade_date=as_of_trade_date,
                empty=False,
                partial=False,
            )
            breadth = IndexDetailConstituentBreadthDto(
                tradeDate=as_of_trade_date,
                weightTradeDate=weight_trade_date,
                upCount=breadth_counts["up_count"],
                flatCount=breadth_counts["flat_count"],
                downCount=breadth_counts["down_count"],
                totalConstituentCount=breadth_counts["total_count"],
                matchedCount=breadth_counts["matched_count"],
                missingCount=breadth_missing_count,
                dataStatus=breadth_status,
            )

        partial = (
            factor_missing_count > 0
            or daily_basic_missing_count > 0
            or weight_trade_date is None
        )
        data_status = self._status_resolver.resolve(
            expected_trade_date=context.trade_date,
            observed_trade_date=as_of_trade_date,
            empty=False,
            partial=partial,
        )
        return IndexDetailPageInitResponseDto(
            pageContext=build_page_context(context),
            asOfTradeDate=as_of_trade_date,
            index=identity,
            quote=build_quote(quote_row),
            dailyBasic=build_daily_basic(daily_basic_row) if daily_basic_row is not None else None,
            constituentBreadth=breadth,
            chartDefaults=self._build_chart_defaults(ts_code=ts_code),
            capabilities=self._build_capabilities(ts_code=ts_code),
            dataStatus=data_status,
        ), factor_missing_count, daily_basic_missing_count

    @staticmethod
    def _build_chart_defaults(*, ts_code: str) -> IndexDetailChartDefaultsDto:
        capability = resolve_index_minute_capability(get_settings())
        available_periods = ["day"]
        if capability.enabled:
            available_periods.extend(["m1", "m5", "m15", "m30", "m60", "m90", "m120"])
        overlays = ["MA", "BOLL"]
        if ts_code == "000001.SH":
            overlays.append("TREND_CHANNEL")
        return IndexDetailChartDefaultsDto(
            defaultPeriod="day",
            availablePeriods=available_periods,  # type: ignore[arg-type]
            availableMainOverlays=overlays,  # type: ignore[arg-type]
            availableIndicatorTabs=["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"],
        )

    @staticmethod
    def _build_capabilities(*, ts_code: str) -> IndexDetailCapabilitiesDto:
        capability = resolve_index_minute_capability(get_settings())
        nine_turn_capability = resolve_index_nine_turn_minute_capability(get_settings())
        nine_turn_periods: list[IndexDetailNineTurnPeriod] = ["day"]
        if nine_turn_capability.enabled:
            nine_turn_periods.extend(["5", "15", "30", "60", "90", "120"])
        return IndexDetailCapabilitiesDto(
            supportsTimeShare=False,
            supportsWeeklyMonthly=False,
            supportsMinute=capability.enabled,
            minuteFrequencies=list(SUPPORTED_MINUTE_FREQS) if capability.enabled else [],
            supportsTrendChannel=ts_code == "000001.SH",
            supportsNineTurn=True,
            nineTurnPeriods=nine_turn_periods,
            supportsTechnicalConclusion=False,
            supportsTradePlanEntry=True,
        )

    def _load_identity_or_raise(self, session: Session, *, ts_code: str) -> IndexDetailIdentityDto:
        identity_row = self._query.load_identity(session, ts_code=ts_code)
        if identity_row is None:
            raise IndexDetailNotFoundError(f"未找到指数身份：{ts_code}")
        try:
            return build_identity(identity_row)
        except ValueError as exc:
            raise IndexDetailNotFoundError(f"指数身份缺少名称：{ts_code}") from exc
