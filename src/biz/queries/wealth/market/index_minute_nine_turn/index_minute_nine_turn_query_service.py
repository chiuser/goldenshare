from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailUniverseService,
)
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import (
    NineTurnContractError,
    build_nine_turn_response,
)
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteReadPage, IndexMinuteReadRequest, IndexMinuteSourceContractError,
)
from src.foundation.clients.local_lake.nine_turn_minute_contract import encode_nine_turn_minute_cursor

if TYPE_CHECKING:
    from src.biz.queries.wealth.market.index_detail_minutes.index_minute_calculation_reader import (
        IndexMinuteCalculationReader,
    )


class IndexMinuteNineTurnQueryService:
    def __init__(
        self,
        reader: IndexMinuteCalculationReader,
        *,
        universe_service: IndexDetailUniverseService | None = None,
    ) -> None:
        self._reader = reader
        self._universe = universe_service or IndexDetailUniverseService()

    def read(
        self,
        *,
        ts_code: str,
        freq: int,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        cursor: str | None,
        debug: bool,
    ) -> NineTurnSeriesDto:
        normalized_code = self._universe.normalize_ts_code(ts_code)
        self._universe.require_supported(normalized_code)
        request = IndexMinuteReadRequest(
            ts_code=normalized_code, freq=freq, start_date=start_date, end_date=end_date, limit=limit, cursor=cursor,
        )
        return self.to_response(self._reader.read_nine_turn(request), request, debug=debug)

    @staticmethod
    def to_response(page: IndexMinuteReadPage, request: IndexMinuteReadRequest, *, debug: bool) -> NineTurnSeriesDto:
        rows = []
        for row in page.rows:
            up, down = row.get("up_count"), row.get("down_count")
            if up not in range(14) or down not in range(14):
                raise IndexMinuteSourceContractError("指数分钟九转计数无效。")
            rows.append({**row, "up_count": int(up), "down_count": int(down), "nine_turn_matched": True})
        next_cursor = None
        if page.has_more:
            first = page.rows[0]
            next_cursor = encode_nine_turn_minute_cursor(
                dataset="index_minute_nine_turn", subject_type="index", ts_code=request.ts_code, freq=request.freq,
                start_date=request.start_date, end_date=request.end_date,
                before_trade_date=first["trade_date"], before_trade_time=first["trade_time"],
            )
        effective_end = request.end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        source_dataset = (
            "silver/quote/major_index_mins" if request.freq in (90, 120) else "gold/quote/major_index_mins"
        )
        try:
            return build_nine_turn_response(
                subject_type="index",
                ts_code=request.ts_code,
                period=str(request.freq),  # type: ignore[arg-type]
                rows=rows,
                source_row_count=page.count,
                matched_row_count=page.count,
                missing_row_count=0,
                has_more=page.has_more,
                next_cursor=next_cursor,
                start_date=request.start_date,
                end_date=effective_end,
                expected_end_date=request.end_date,
                observed_start_date=page.observed_start_date,
                observed_end_date=page.observed_end_date,
                limit=request.limit,
                debug_info=(
                    {
                        "sourceDatasets": [source_dataset] if page.scanned_file_count else [],
                        "scannedFileCount": page.scanned_file_count,
                        "elapsedMs": round(page.elapsed_ms, 3),
                    }
                    if debug
                    else None
                ),
            )
        except NineTurnContractError as exc:
            raise IndexMinuteSourceContractError(str(exc)) from exc


__all__ = ["IndexMinuteNineTurnQueryService"]
