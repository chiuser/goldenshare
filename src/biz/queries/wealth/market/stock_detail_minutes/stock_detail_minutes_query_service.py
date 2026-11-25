from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from src.biz.queries.wealth.market.stock_detail_minutes.stock_minute_calculation_reader import (
    SHANGHAI,
    STOCK_MINUTE_SOURCES,
    StockMinuteCalculationReader,
)
from src.biz.queries.wealth.market.stock_minute_nine_turn.stock_minute_nine_turn_query_service import (
    StockMinuteNineTurnQueryService,
)
from src.biz.schemas.wealth.market.stock_detail_minutes import (
    MinuteDataStatus,
    MinutePageMeta,
    StockMinuteBarDto,
    StockMinuteIndicatorDto,
    StockMinuteIndicatorsResponseDto,
    StockMinuteChartResponseDto,
)
from src.foundation.clients.local_lake.stock_mins_reader import (
    MinuteReadPage,
    MinuteReadRequest,
)
from src.foundation.clients.local_lake.stock_nine_turn_contract import SUPPORTED_STOCK_NINE_TURN_FREQS


class StockMinuteQueryService:
    def __init__(self, reader: StockMinuteCalculationReader) -> None:
        self._reader = reader

    def read_chart(self, request: MinuteReadRequest, *, debug: bool) -> StockMinuteChartResponseDto:
        page, window = self._reader.read(request, output="chart")
        nine_turn = (
            StockMinuteNineTurnQueryService.to_response(page, window, request, debug=debug)
            if request.freq in SUPPORTED_STOCK_NINE_TURN_FREQS else None
        )
        return StockMinuteChartResponseDto(
            tsCode=request.ts_code.strip().upper(),
            freq=request.freq,
            bars=[self._to_bar(row) for row in page.rows],
            indicators=[self._to_indicator(row) for row in page.rows],
            nineTurn=nine_turn,
            meta=self._to_meta(page, start_date=window.start_date, end_date=window.query_end_date, limit=request.limit),
            dataStatus=self._to_status(page, expected_end_date=window.expected_end_date),
            debugInfo=self._debug_info(page, debug=debug, dataset="bars", expected_end_date=window.expected_end_date),
        )

    def read_indicators(self, request: MinuteReadRequest, *, debug: bool) -> StockMinuteIndicatorsResponseDto:
        page, window = self._reader.read(request, output="indicators")
        return StockMinuteIndicatorsResponseDto(
            tsCode=request.ts_code.strip().upper(),
            freq=request.freq,
            items=[self._to_indicator(row) for row in page.rows],
            meta=self._to_meta(page, start_date=window.start_date, end_date=window.query_end_date, limit=request.limit),
            dataStatus=self._to_status(page, expected_end_date=window.expected_end_date),
            debugInfo=self._debug_info(page, debug=debug, dataset="indicators", expected_end_date=window.expected_end_date),
        )

    @staticmethod
    def _to_meta(
        page: MinuteReadPage,
        *,
        start_date: date | None,
        end_date: date,
        limit: int,
    ) -> MinutePageMeta:
        return MinutePageMeta(
            count=page.count,
            limit=limit,
            hasMore=page.has_more,
            nextCursor=page.next_cursor,
            startDate=start_date,
            endDate=end_date,
            observedStartDate=page.observed_start_date,
            observedEndDate=page.observed_end_date,
        )

    @staticmethod
    def _to_status(page: MinuteReadPage, *, expected_end_date: date | None) -> MinuteDataStatus:
        if not page.rows:
            if expected_end_date is not None:
                return MinuteDataStatus(
                    status="DELAYED",
                    expectedEndDate=expected_end_date,
                    observedEndDate=None,
                    message="分钟数据尚未覆盖期望交易日。",
                )
            return MinuteDataStatus(status="EMPTY", expectedEndDate=None, observedEndDate=None)
        if expected_end_date is not None and page.observed_end_date is not None and page.observed_end_date < expected_end_date:
            return MinuteDataStatus(
                status="DELAYED",
                expectedEndDate=expected_end_date,
                observedEndDate=page.observed_end_date,
                message="分钟数据尚未覆盖期望交易日。",
            )
        return MinuteDataStatus(
            status="READY",
            expectedEndDate=expected_end_date,
            observedEndDate=page.observed_end_date,
        )

    @staticmethod
    def _to_bar(row: dict[str, Any]) -> StockMinuteBarDto:
        return StockMinuteBarDto(
            tsCode=row["ts_code"],
            freq=row["freq"],
            tradeDate=row["trade_date"],
            tradeTime=_as_shanghai_datetime(row["trade_time"]),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            vol=row["vol"],
            amount=row["amount"],
            exchange=row["exchange"],
        )

    @staticmethod
    def _to_indicator(row: dict[str, Any]) -> StockMinuteIndicatorDto:
        return StockMinuteIndicatorDto(
            tsCode=row["ts_code"],
            freq=row["freq"],
            tradeDate=row["trade_date"],
            tradeTime=_as_shanghai_datetime(row["trade_time"]),
            macdDif=row["macd_dif_qfq"],
            macdDea=row["macd_dea_qfq"],
            macd=row["macd_qfq"],
            kdjK=row["kdj_k_qfq"],
            kdjD=row["kdj_d_qfq"],
            kdjJ=row["kdj_qfq"],
            paramsKey=row["params_key"],
            indicatorVersion=row["indicator_version"],
        )

    @staticmethod
    def _debug_info(
        page: MinuteReadPage,
        *,
        debug: bool,
        dataset: Literal["bars", "indicators"],
        expected_end_date: date | None,
    ) -> dict[str, Any] | None:
        if not debug:
            return None
        return {
            "dataset": dataset,
            "sourceDatasets": list(STOCK_MINUTE_SOURCES),
            "expectedEndDate": expected_end_date,
            "scannedFileCount": page.scanned_file_count,
            "elapsedMs": round(page.elapsed_ms, 3),
        }


def _as_shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(SHANGHAI)
    return value.replace(tzinfo=SHANGHAI)
