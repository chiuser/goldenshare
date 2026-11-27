from __future__ import annotations

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.stock_detail_minutes.stock_detail_minutes_query import StockMinuteQueryWindow
from src.biz.queries.wealth.market.stock_detail_minutes.stock_minute_calculation_reader import (
    NINE_TURN_DATASET,
    STOCK_MINUTE_SOURCES,
    StockMinuteCalculationReader,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import build_nine_turn_response
from src.foundation.clients.local_lake.nine_turn_minute_contract import encode_nine_turn_minute_cursor
from src.foundation.clients.local_lake.stock_mins_reader import MinuteReadPage, MinuteReadRequest
from src.foundation.clients.reference_data import local_reference_data
from src.foundation.models.core_serving.security_serving import Security


class StockMinuteNineTurnNotFoundError(ValueError):
    pass


class StockMinuteNineTurnQueryService:
    def __init__(self, reader: StockMinuteCalculationReader) -> None:
        self._reader = reader

    def read(self, session: Session, request: MinuteReadRequest, *, debug: bool) -> NineTurnSeriesDto:
        code = request.ts_code.strip().upper()
        reference = local_reference_data(session)
        security = reference.security.get(ts_code=code) if reference is not None else session.get(Security, code)
        if security is None or security.security_type != "EQUITY":
            raise StockMinuteNineTurnNotFoundError(f"未找到股票标的：{code}")
        page, window = self._reader.read(request, output="nine_turn")
        return self.to_response(page, window, request, debug=debug)

    @staticmethod
    def to_response(
        page: MinuteReadPage, window: StockMinuteQueryWindow, request: MinuteReadRequest, *, debug: bool,
    ) -> NineTurnSeriesDto:
        code = request.ts_code.strip().upper()
        cursor = None
        if page.has_more:
            first = page.rows[0]
            cursor = encode_nine_turn_minute_cursor(
                dataset=NINE_TURN_DATASET, subject_type="stock", ts_code=code, freq=request.freq,
                start_date=request.start_date, end_date=request.end_date,
                before_trade_date=first["trade_date"], before_trade_time=first["trade_time"],
            )
        return build_nine_turn_response(
            subject_type="stock", ts_code=code, period=str(request.freq),  # type: ignore[arg-type]
            rows=list(page.rows), source_row_count=page.count, matched_row_count=page.count, missing_row_count=0,
            has_more=page.has_more, next_cursor=cursor,
            start_date=window.start_date, end_date=window.query_end_date, expected_end_date=window.expected_end_date,
            observed_start_date=page.observed_start_date, observed_end_date=page.observed_end_date, limit=request.limit,
            debug_info={
                "sourceDatasets": list(STOCK_MINUTE_SOURCES), "scannedFileCount": page.scanned_file_count,
                "elapsedMs": round(page.elapsed_ms, 3),
            } if debug else None,
        )
