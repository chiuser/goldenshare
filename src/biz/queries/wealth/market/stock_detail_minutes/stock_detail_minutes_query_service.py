from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from src.biz.queries.wealth.market.stock_detail_minutes.stock_detail_minutes_query import (
    resolve_stock_minute_query_window,
)
from src.biz.schemas.wealth.market.stock_detail_minutes import (
    MinuteDataStatus,
    MinutePageMeta,
    StockMinuteBarDto,
    StockMinuteIndicatorDto,
    StockMinuteIndicatorsResponseDto,
    StockMinutesResponseDto,
)
from src.foundation.clients.local_lake.stock_mins_reader import (
    MinuteReadPage,
    MinuteReadRequest,
    MinuteRequestError,
    StockMinsLakeReader,
)

MAX_RESPONSE_BYTES = 5_000_000
SHANGHAI = ZoneInfo("Asia/Shanghai")


class StockMinuteQueryService:
    def __init__(self, lake_root: Path, *, reader: StockMinsLakeReader | None = None) -> None:
        self._reader = reader or StockMinsLakeReader(lake_root)

    def read_bars(
        self,
        *,
        ts_code: str,
        freq: int,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        cursor: str | None,
        debug: bool,
    ) -> StockMinutesResponseDto:
        window = self._resolve_window(start_date=start_date, end_date=end_date)
        page = self._reader.read_bars(
            MinuteReadRequest(
                ts_code=ts_code,
                freq=freq,
                start_date=window.start_date,
                end_date=window.query_end_date,
                limit=limit,
                cursor=cursor,
            )
        )
        response = StockMinutesResponseDto(
            tsCode=ts_code.strip().upper(),
            freq=freq,
            bars=[self._to_bar(row) for row in page.rows],
            meta=self._to_meta(
                page,
                start_date=window.start_date,
                end_date=window.query_end_date,
                limit=limit,
            ),
            dataStatus=self._to_status(page, expected_end_date=window.expected_end_date),
            debugInfo=self._debug_info(page, debug=debug, dataset="bars", expected_end_date=window.expected_end_date),
        )
        self._enforce_response_size(response)
        return response

    def read_indicators(
        self,
        *,
        ts_code: str,
        freq: int,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        cursor: str | None,
        debug: bool,
    ) -> StockMinuteIndicatorsResponseDto:
        window = self._resolve_window(start_date=start_date, end_date=end_date)
        page = self._reader.read_indicators(
            MinuteReadRequest(
                ts_code=ts_code,
                freq=freq,
                start_date=window.start_date,
                end_date=window.query_end_date,
                limit=limit,
                cursor=cursor,
            )
        )
        response = StockMinuteIndicatorsResponseDto(
            tsCode=ts_code.strip().upper(),
            freq=freq,
            items=[self._to_indicator(row) for row in page.rows],
            meta=self._to_meta(
                page,
                start_date=window.start_date,
                end_date=window.query_end_date,
                limit=limit,
            ),
            dataStatus=self._to_status(page, expected_end_date=window.expected_end_date),
            debugInfo=self._debug_info(
                page,
                debug=debug,
                dataset="indicators",
                expected_end_date=window.expected_end_date,
            ),
        )
        self._enforce_response_size(response)
        return response

    @staticmethod
    def _resolve_window(*, start_date: date | None, end_date: date | None):
        return resolve_stock_minute_query_window(
            start_date=start_date,
            end_date=end_date,
            today=datetime.now(SHANGHAI).date(),
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
            "expectedEndDate": expected_end_date,
            "scannedFileCount": page.scanned_file_count,
            "elapsedMs": round(page.elapsed_ms, 3),
        }

    @staticmethod
    def _enforce_response_size(response: Any) -> None:
        payload_size = len(response.model_dump_json(by_alias=True).encode("utf-8"))
        if payload_size > MAX_RESPONSE_BYTES:
            raise MinuteRequestError("响应超过 5MB，请降低 limit 或使用 cursor 分页。")


def _as_shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(SHANGHAI)
    return value.replace(tzinfo=SHANGHAI)
