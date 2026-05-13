from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.sector_overview import (
    ModuleStatusItemDto,
    PageStatusDto,
    SectorHeatMapItemDto,
    SectorLeadingStockDto,
    SectorMetricDto,
    SectorOverviewDebugInfoDto,
    SectorOverviewPayloadDto,
    SectorOverviewResponseDto,
    SectorRankColumnDto,
    SectorRankRowDto,
    SectorSubjectDto,
    TradingDayDto,
)
from src.biz.services.wealth.market.sector_overview.sector_overview_exception_builder import (
    SectorOverviewExceptionBuilder,
)
from src.biz.services.wealth.market.sector_overview.sector_overview_status_resolver import (
    SectorOverviewStatusResolver,
)
from .sector_overview_query import SectorDailyRow, SectorIndexRow, SectorMoneyflowRow, SectorOverviewQuery
from .sector_overview_state_query import SectorOverviewSourceState, SectorOverviewStateQuery, SectorOverviewTradingDayContext


_CATEGORY_TO_SECTOR_TYPE = {
    "行业板块": "INDUSTRY",
    "概念板块": "CONCEPT",
    "地域板块": "REGION",
}
_CONTENT_TYPE_TO_SECTOR_TYPE = {
    "行业": "INDUSTRY",
    "概念": "CONCEPT",
    "地域": "REGION",
}


@dataclass(frozen=True, slots=True)
class SectorColumnDefinition:
    column_key: str
    title: str
    tone: str
    metric_label: str
    source_kind: str
    category: str | None
    descending: bool


_COLUMN_DEFINITIONS: tuple[SectorColumnDefinition, ...] = (
    SectorColumnDefinition("industryTopGainers", "行业涨幅前五", "UP", "涨幅", "daily", "行业板块", True),
    SectorColumnDefinition("conceptTopGainers", "概念涨幅前五", "UP", "涨幅", "daily", "概念板块", True),
    SectorColumnDefinition("regionTopGainers", "地域涨幅前五", "UP", "涨幅", "daily", "地域板块", True),
    SectorColumnDefinition("fundIn", "资金流入前五", "UP", "净流入", "moneyflow", None, True),
    SectorColumnDefinition("industryTopLosers", "行业跌幅前五", "DOWN", "跌幅", "daily", "行业板块", False),
    SectorColumnDefinition("conceptTopLosers", "概念跌幅前五", "DOWN", "跌幅", "daily", "概念板块", False),
    SectorColumnDefinition("regionTopLosers", "地域跌幅前五", "DOWN", "跌幅", "daily", "地域板块", False),
    SectorColumnDefinition("fundOut", "资金流出前五", "DOWN", "净流出", "moneyflow", None, False),
)


class MarketSectorOverviewQueryService:
    """Orchestrate sector-overview module response assembly."""

    def __init__(self) -> None:
        self._state_query = SectorOverviewStateQuery()
        self._query = SectorOverviewQuery()
        self._status_resolver = SectorOverviewStatusResolver()
        self._exception_builder = SectorOverviewExceptionBuilder()

    def build_sector_overview(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> SectorOverviewResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        source_state = self._state_query.load_source_state(
            session,
            expected_trade_date=trading_day_context.expected_trade_date,
        )
        observed_trade_date = source_state.observed_trade_date
        query_trade_date = trade_date or observed_trade_date or trading_day_context.expected_trade_date

        try:
            daily_rows = self._query.load_daily_rows(session, trade_date=query_trade_date)
            index_rows = self._query.load_index_rows(session, trade_date=query_trade_date)
            moneyflow_rows = self._query.load_moneyflow_rows(session, trade_date=query_trade_date)
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"sector-overview query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                query_trade_date=query_trade_date,
                debug=debug,
                exceptions=exceptions,
            )

        columns = [
            self._build_column(
                definition=definition,
                daily_rows=daily_rows,
                index_rows=index_rows,
                moneyflow_rows=moneyflow_rows,
            )
            for definition in _COLUMN_DEFINITIONS
        ]
        heatmap_items = self._build_heatmap_items(daily_rows=daily_rows, index_rows=index_rows)
        has_display_rows = any(column.rows for column in columns) or bool(heatmap_items)
        min_column_row_count = min((len(column.rows) for column in columns), default=0)
        all_sources_available = bool(daily_rows) and bool(index_rows) and bool(moneyflow_rows)
        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=(query_trade_date if has_display_rows else observed_trade_date),
            has_display_rows=has_display_rows,
            all_sources_available=all_sources_available,
            column_count=len(columns),
            min_column_row_count=min_column_row_count,
            heatmap_count=len(heatmap_items),
            as_of_time=trading_day_context.as_of_time,
        )

        if status_result.module_status.status == "DELAYED":
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="dc source bundle delayed",
                    expected_trade_date=trading_day_context.expected_trade_date.isoformat(),
                    observed_trade_date=(
                        status_result.module_status.observedTradeDate.isoformat()
                        if status_result.module_status.observedTradeDate is not None
                        else None
                    ),
                )
            )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(self._exception_builder.source_empty(message="dc source bundle has no usable rows"))

        return SectorOverviewResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=status_result.page_status,
            sectorOverview=SectorOverviewPayloadDto(
                tradeDate=query_trade_date,
                status=status_result.module_status.status,  # type: ignore[arg-type]
                columns=columns,
                heatMapItems=heatmap_items,
            ),
            debugInfo=(
                SectorOverviewDebugInfoDto(
                    modules=[status_result.module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    def _build_column(
        self,
        *,
        definition: SectorColumnDefinition,
        daily_rows: list[SectorDailyRow],
        index_rows: dict[str, SectorIndexRow],
        moneyflow_rows: list[SectorMoneyflowRow],
    ) -> SectorRankColumnDto:
        if definition.source_kind == "daily":
            rows = [row for row in daily_rows if row.category == definition.category and row.pct_change is not None]
            ranked_rows = self._sort_daily_rows(rows, descending=definition.descending)[:5]
            dto_rows = [
                self._build_daily_rank_row(rank=index + 1, row=row, index_row=index_rows.get(row.ts_code))
                for index, row in enumerate(ranked_rows)
            ]
        elif definition.source_kind == "moneyflow":
            ranked_rows = self._sort_moneyflow_rows(
                [row for row in moneyflow_rows if row.net_amount is not None],
                descending=definition.descending,
            )[:5]
            dto_rows = [
                self._build_moneyflow_rank_row(rank=index + 1, row=row, index_row=index_rows.get(row.ts_code))
                for index, row in enumerate(ranked_rows)
            ]
        else:
            raise ValueError(f"unsupported sector column source: {definition.source_kind}")

        return SectorRankColumnDto(
            columnKey=definition.column_key,
            title=definition.title,
            tone=definition.tone,  # type: ignore[arg-type]
            metricLabel=definition.metric_label,
            rows=dto_rows,
        )

    def _build_daily_rank_row(
        self,
        *,
        rank: int,
        row: SectorDailyRow,
        index_row: SectorIndexRow | None,
    ) -> SectorRankRowDto:
        return SectorRankRowDto(
            rank=rank,
            subject=self._build_subject(
                subject_code=row.ts_code,
                subject_name=index_row.name if index_row is not None else None,
                sector_type=self._sector_type_from_category(row.category),
            ),
            metric=SectorMetricDto(
                value=self._to_float(row.pct_change),
                displayText=self._format_percent(row.pct_change),
                unit="%",
                direction=self._direction(row.pct_change),
            ),
            leadingStock=self._build_leading_stock(index_row),
        )

    def _build_moneyflow_rank_row(
        self,
        *,
        rank: int,
        row: SectorMoneyflowRow,
        index_row: SectorIndexRow | None,
    ) -> SectorRankRowDto:
        return SectorRankRowDto(
            rank=rank,
            subject=self._build_subject(
                subject_code=row.ts_code,
                subject_name=row.name or (index_row.name if index_row is not None else None),
                sector_type=self._sector_type_from_content_type(row.content_type),
            ),
            metric=SectorMetricDto(
                value=self._to_float(row.net_amount),
                displayText=self._format_amount_yi(row.net_amount),
                unit=None,
                direction=self._direction(row.net_amount),
            ),
            leadingStock=self._build_leading_stock(index_row),
        )

    def _build_heatmap_items(
        self,
        *,
        daily_rows: list[SectorDailyRow],
        index_rows: dict[str, SectorIndexRow],
    ) -> list[SectorHeatMapItemDto]:
        sorted_rows = sorted(
            [row for row in daily_rows if row.pct_change is not None],
            key=lambda row: (
                -abs(float(row.pct_change or 0)),
                -float(row.pct_change or 0),
                row.ts_code,
            ),
        )[:20]
        return [
            SectorHeatMapItemDto(
                subject=self._build_subject(
                    subject_code=row.ts_code,
                    subject_name=index_rows.get(row.ts_code).name if row.ts_code in index_rows else None,
                    sector_type=self._sector_type_from_category(row.category),
                ),
                changePct=self._to_float(row.pct_change),
                direction=self._direction(row.pct_change),  # type: ignore[arg-type]
                riseStockCount=index_rows.get(row.ts_code).up_num if row.ts_code in index_rows else None,
                fallStockCount=index_rows.get(row.ts_code).down_num if row.ts_code in index_rows else None,
                leadingStock=self._build_leading_stock(index_rows.get(row.ts_code)),
            )
            for row in sorted_rows
        ]

    @staticmethod
    def _sort_daily_rows(rows: list[SectorDailyRow], *, descending: bool) -> list[SectorDailyRow]:
        if descending:
            return sorted(
                rows,
                key=lambda row: (
                    row.pct_change is None,
                    -float(row.pct_change or 0),
                    row.ts_code,
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                row.pct_change is None,
                float(row.pct_change or 0),
                row.ts_code,
            ),
        )

    @staticmethod
    def _sort_moneyflow_rows(rows: list[SectorMoneyflowRow], *, descending: bool) -> list[SectorMoneyflowRow]:
        if descending:
            return sorted(
                rows,
                key=lambda row: (
                    row.net_amount is None,
                    -float(row.net_amount or 0),
                    row.ts_code,
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                row.net_amount is None,
                float(row.net_amount or 0),
                row.ts_code,
            ),
        )

    @staticmethod
    def _build_subject(
        *,
        subject_code: str,
        subject_name: str | None,
        sector_type: str,
    ) -> SectorSubjectDto:
        return SectorSubjectDto(
            subjectType="sector",
            subjectCode=subject_code,
            subjectName=subject_name,
            sectorType=sector_type,  # type: ignore[arg-type]
        )

    @staticmethod
    def _build_leading_stock(index_row: SectorIndexRow | None) -> SectorLeadingStockDto | None:
        if index_row is None:
            return None
        if index_row.leading_code is None and index_row.leading is None and index_row.leading_pct is None:
            return None
        return SectorLeadingStockDto(
            stockCode=index_row.leading_code,
            stockName=index_row.leading,
            changePct=MarketSectorOverviewQueryService._to_float(index_row.leading_pct),
        )

    @staticmethod
    def _build_trading_day(*, trading_day_context: SectorOverviewTradingDayContext) -> TradingDayDto:
        return TradingDayDto(
            tradeDate=trading_day_context.expected_trade_date,
            prevTradeDate=trading_day_context.prev_trade_date,
            market="CN_A",
            isTradingDay=trading_day_context.is_trading_day,
            sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
            timezone="Asia/Shanghai",
        )

    def _build_error_response(
        self,
        *,
        trading_day_context: SectorOverviewTradingDayContext,
        source_state: SectorOverviewSourceState,
        query_trade_date: date,
        debug: bool,
        exceptions: list,
    ) -> SectorOverviewResponseDto:
        module_status = ModuleStatusItemDto(
            moduleKey="sectorOverview",
            expectedTradeDate=trading_day_context.expected_trade_date,
            observedTradeDate=source_state.observed_trade_date,
            lagDays=SectorOverviewStatusResolver._lag_days(
                trading_day_context.expected_trade_date,
                source_state.observed_trade_date,
            ),
            status="ERROR",
            note="module failed to load",
        )
        return SectorOverviewResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=PageStatusDto(status="ERROR", displayText="模块加载失败", asOfTime=trading_day_context.as_of_time),
            sectorOverview=SectorOverviewPayloadDto(
                tradeDate=query_trade_date,
                status="ERROR",
                columns=[],
                heatMapItems=[],
            ),
            debugInfo=(
                SectorOverviewDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _sector_type_from_category(value: str) -> str:
        if value not in _CATEGORY_TO_SECTOR_TYPE:
            raise ValueError(f"unsupported dc_daily category: {value}")
        return _CATEGORY_TO_SECTOR_TYPE[value]

    @staticmethod
    def _sector_type_from_content_type(value: str) -> str:
        if value not in _CONTENT_TYPE_TO_SECTOR_TYPE:
            raise ValueError(f"unsupported board_moneyflow_dc content_type: {value}")
        return _CONTENT_TYPE_TO_SECTOR_TYPE[value]

    @staticmethod
    def _direction(value: Decimal | int | float | None) -> str:
        if value is None:
            return "UNKNOWN"
        if value > 0:
            return "UP"
        if value < 0:
            return "DOWN"
        return "FLAT"

    @staticmethod
    def _format_percent(value: Decimal | None) -> str:
        if value is None:
            return "--"
        number = float(value)
        sign = "+" if number > 0 else ""
        return f"{sign}{number:.2f}%"

    @staticmethod
    def _format_amount_yi(value: Decimal | None) -> str:
        if value is None:
            return "--"
        number = float(value) / 100000000
        sign = "+" if number > 0 else ""
        return f"{sign}{number:.1f}亿"

    @staticmethod
    def _to_float(value: Decimal | int | float | None) -> float | None:
        if value is None:
            return None
        return float(value)
