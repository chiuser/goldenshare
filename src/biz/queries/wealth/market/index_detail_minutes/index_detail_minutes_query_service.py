from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteReadPage,
    IndexMinuteReadRequest,
    MajorIndexMinsLakeReader,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
KNOWN_UNSUPPORTED_SILVER_CODES = frozenset({"899050.BJ"})


class IndexDetailMinutesQueryService:
    def __init__(
        self,
        lake_root: Path,
        *,
        reader: MajorIndexMinsLakeReader | None = None,
        universe_service: IndexDetailUniverseService | None = None,
    ) -> None:
        self._reader = reader or MajorIndexMinsLakeReader(lake_root)
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
        if normalized_code in KNOWN_UNSUPPORTED_SILVER_CODES:
            page = _empty_page()
            response = IndexMinutesResponseDto(
                tsCode=normalized_code,
                freq=freq,
                bars=[],
                meta=build_index_minute_meta(
                    page,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                ),
                dataStatus=build_index_minute_status(
                    page,
                    expected_end_date=end_date,
                    known_unsupported=True,
                ),
            )
            enforce_index_minute_response_size(response)
            return response

        page = self._reader.read_bars(
            IndexMinuteReadRequest(
                ts_code=normalized_code,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                cursor=cursor,
            )
        )
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
            dataStatus=build_index_minute_status(page, expected_end_date=end_date),
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
        if normalized_code in KNOWN_UNSUPPORTED_SILVER_CODES:
            page = _empty_page()
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
                known_unsupported=normalized_code in KNOWN_UNSUPPORTED_SILVER_CODES,
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
            observationCount=row["observation_count"],
            paramsKey=row["params_key"],
            indicatorVersion=row["indicator_version"],
        )


def _as_shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(SHANGHAI)
    return value.replace(tzinfo=SHANGHAI)


def _empty_page() -> IndexMinuteReadPage:
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
