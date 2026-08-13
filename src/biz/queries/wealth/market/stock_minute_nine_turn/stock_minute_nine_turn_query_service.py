from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.stock_nine_turn.stock_nine_turn_query_service import (
    StockNineTurnNotFoundError,
    StockNineTurnSourceContractError,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import (
    NineTurnContractError,
    build_stock_nine_turn_response,
)
from src.foundation.clients.local_lake.stock_nine_turn_reader import (
    StockNineTurnLakeReader,
    StockNineTurnReadRequest,
)
from src.foundation.models.core_serving.security_serving import Security


class StockMinuteNineTurnQueryService:
    def __init__(
        self,
        lake_root: Path,
        *,
        reader: StockNineTurnLakeReader | None = None,
    ) -> None:
        self._reader = reader or StockNineTurnLakeReader(lake_root)

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
        normalized_code = ts_code.strip().upper()
        security = session.get(Security, normalized_code)
        if security is None or security.security_type != "EQUITY":
            raise StockNineTurnNotFoundError(f"未找到股票标的：{normalized_code}")
        page = self._reader.read(
            StockNineTurnReadRequest(
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
            return build_stock_nine_turn_response(
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
                            "gold/quote/stk_mins_qfq",
                            "gold/indicator/stk_mins_qfq_nineturn",
                        ],
                        "scannedFileCount": page.scanned_file_count,
                        "elapsedMs": round(page.elapsed_ms, 3),
                    }
                    if debug
                    else None
                ),
            )
        except NineTurnContractError as exc:
            raise StockNineTurnSourceContractError(str(exc)) from exc
