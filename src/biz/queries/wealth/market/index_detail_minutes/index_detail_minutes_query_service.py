from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from src.biz.queries.wealth.market.index_minute_nine_turn.index_minute_nine_turn_query_service import (
    IndexMinuteNineTurnQueryService,
)
from src.biz.schemas.wealth.market.index_detail_minutes import (
    IndexMinuteBarDto,
    IndexMinuteIndicatorDto,
    IndexMinuteIndicatorsResponseDto,
    IndexMinutesResponseDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailUniverseService,
)
from src.biz.services.wealth.market.index_detail_minutes.index_minute_response_policy import (
    build_index_minute_meta,
    build_index_minute_status,
    enforce_index_minute_response_size,
)
from src.foundation.clients.local_lake.index_nine_turn_contract import SUPPORTED_INDEX_NINE_TURN_FREQS
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteReadPage,
    IndexMinuteReadRequest,
    IndexMinuteRequestError,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
KNOWN_UNSUPPORTED_MINUTE_CODES = frozenset({"899050.BJ"})


class IndexMinutePageReader(Protocol):
    def read_bars(self, request: IndexMinuteReadRequest) -> IndexMinuteReadPage: ...
    def read_indicators(self, request: IndexMinuteReadRequest) -> IndexMinuteReadPage: ...


class IndexDetailMinutesQueryService:
    def __init__(
        self,
        reader: IndexMinutePageReader,
        *,
        universe_service: IndexDetailUniverseService | None = None,
    ) -> None:
        self._reader = reader
        self._universe = universe_service or IndexDetailUniverseService()

    def read_bars(
        self,
        *,
        ts_code: str,
        freq: int,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        cursor: str | None,
    ) -> IndexMinutesResponseDto:
        normalized_code = ts_code.strip().upper()
        self._universe.require_supported(normalized_code)
        request = IndexMinuteReadRequest(
            ts_code=normalized_code, freq=freq, start_date=start_date, end_date=end_date, limit=limit, cursor=cursor,
        )
        known_unsupported = normalized_code in KNOWN_UNSUPPORTED_MINUTE_CODES
        page = empty_index_minute_page() if known_unsupported else self._reader.read_bars(request)
        try:
            nine_turn = (
                IndexMinuteNineTurnQueryService.to_response(page, request, debug=False)
                if freq in SUPPORTED_INDEX_NINE_TURN_FREQS else None
            )
        except ValueError as exc:
            raise IndexMinuteRequestError(str(exc)) from exc
        response = IndexMinutesResponseDto(
            tsCode=normalized_code,
            freq=freq,
            bars=[self._to_bar(row) for row in page.rows],
            meta=build_index_minute_meta(
                page,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            ),
            dataStatus=build_index_minute_status(page, expected_end_date=end_date, known_unsupported=known_unsupported),
            nineTurn=nine_turn,
        )
        enforce_index_minute_response_size(response)
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
    ) -> IndexMinuteIndicatorsResponseDto:
        normalized_code = ts_code.strip().upper()
        self._universe.require_supported(normalized_code)
        if normalized_code in KNOWN_UNSUPPORTED_MINUTE_CODES:
            page = empty_index_minute_page()
        else:
            page = self._reader.read_indicators(
                IndexMinuteReadRequest(
                    ts_code=normalized_code,
                    freq=freq,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                    cursor=cursor,
                )
            )
        response = IndexMinuteIndicatorsResponseDto(
            tsCode=normalized_code,
            freq=freq,
            items=[self._to_indicator(row) for row in page.rows],
            meta=build_index_minute_meta(
                page,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            ),
            dataStatus=build_index_minute_status(
                page,
                expected_end_date=end_date,
                known_unsupported=normalized_code in KNOWN_UNSUPPORTED_MINUTE_CODES,
            ),
        )
        enforce_index_minute_response_size(response)
        return response

    @staticmethod
    def _to_bar(row: dict[str, Any]) -> IndexMinuteBarDto:
        return IndexMinuteBarDto(
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
    def _to_indicator(row: dict[str, Any]) -> IndexMinuteIndicatorDto:
        return IndexMinuteIndicatorDto(
            tsCode=row["ts_code"],
            freq=row["freq"],
            tradeDate=row["trade_date"],
            tradeTime=_as_shanghai_datetime(row["trade_time"]),
            ma5=row["ma_5"],
            ma10=row["ma_10"],
            ma20=row["ma_20"],
            ma30=row["ma_30"],
            ma60=row["ma_60"],
            ma90=row["ma_90"],
            ma250=row["ma_250"],
            bollMiddle=row["boll_mid"],
            bollUpper=row["boll_upper"],
            bollLower=row["boll_lower"],
            macdDif=row["macd_dif"],
            macdDea=row["macd_dea"],
            macd=row["macd"],
            kdjK=row["kdj_k"],
            kdjD=row["kdj_d"],
            kdjJ=row["kdj_j"],
            paramsKey=row["params_key"],
            indicatorVersion=row["indicator_version"],
        )


def _as_shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(SHANGHAI)
    return value.replace(tzinfo=SHANGHAI)


def empty_index_minute_page() -> IndexMinuteReadPage:
    return IndexMinuteReadPage(
        rows=(),
        count=0,
        has_more=False,
        next_cursor=None,
        observed_start_date=None,
        observed_end_date=None,
        scanned_file_count=0,
        elapsed_ms=0.0,
    )
