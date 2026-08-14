from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailUniverseService,
)
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import (
    NineTurnContractError,
    build_nine_turn_response,
)
from src.foundation.clients.local_lake.index_nine_turn_reader import (
    IndexNineTurnLakeReader,
    IndexNineTurnReadRequest,
    IndexNineTurnSourceContractError,
)


class IndexMinuteNineTurnQueryService:
    def __init__(
        self,
        lake_root: Path,
        *,
        reader: IndexNineTurnLakeReader | None = None,
        universe_service: IndexDetailUniverseService | None = None,
    ) -> None:
        self._reader = reader or IndexNineTurnLakeReader(lake_root)
        self._universe = universe_service or IndexDetailUniverseService()

    def read(
        self,
        session: Session,
        *,
        ts_code: str,
        freq: int,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        cursor: str | None,
        debug: bool,
    ) -> NineTurnSeriesDto:
        del session  # Universe is the product identity boundary for index endpoints.
        normalized_code = self._universe.normalize_ts_code(ts_code)
        self._universe.require_supported(normalized_code)
        page = self._reader.read(
            IndexNineTurnReadRequest(
                ts_code=normalized_code,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                cursor=cursor,
            )
        )
        effective_end = end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        try:
            return build_nine_turn_response(
                subject_type="index",
                ts_code=normalized_code,
                period=str(freq),  # type: ignore[arg-type]
                rows=list(page.rows),
                source_row_count=page.source_row_count,
                matched_row_count=page.matched_row_count,
                missing_row_count=page.missing_row_count,
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                start_date=start_date,
                end_date=effective_end,
                expected_end_date=end_date,
                observed_start_date=page.observed_start_date,
                observed_end_date=page.observed_end_date,
                limit=limit,
                debug_info=(
                    {
                        "sourceDatasets": [
                            "gold/quote/major_index_mins",
                            "gold/indicator/major_index_mins_nineturn",
                        ],
                        "scannedFileCount": page.scanned_file_count,
                        "elapsedMs": round(page.elapsed_ms, 3),
                    }
                    if debug
                    else None
                ),
            )
        except NineTurnContractError as exc:
            raise IndexNineTurnSourceContractError(str(exc)) from exc


__all__ = ["IndexMinuteNineTurnQueryService"]
