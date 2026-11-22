from __future__ import annotations

from datetime import date

from goldenshare_technical_indicators.errors import SourceReadError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.index_nine_turn.index_nine_turn_query import (
    IndexNineTurnQuery,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailRequestError,
    IndexDetailUniverseService,
)
from src.biz.services.wealth.market.nine_turn.daily_nine_turn_cursor import (
    decode_daily_nine_turn_cursor,
    encode_daily_nine_turn_cursor,
)
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import (
    NineTurnContractError,
    build_nine_turn_response,
)
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader, IndexDailyLakeSourceError
from src.foundation.clients.technical_indicator_stock_daily import dg_index_daily_origin


class IndexNineTurnSourceContractError(RuntimeError):
    pass


class IndexNineTurnQueryError(RuntimeError):
    pass


class IndexNineTurnQueryService:
    def __init__(self, *, daily_lake: IndexDailyLakeReader | None = None) -> None:
        self._universe = IndexDetailUniverseService()
        self._context_query = MarketPageContextQuery()
        self._query = IndexNineTurnQuery()
        self._daily_lake = daily_lake

    def read_daily(
        self,
        session: Session,
        *,
        ts_code: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        cursor: str | None,
        debug: bool,
    ) -> NineTurnSeriesDto:
        normalized_code = self._universe.normalize_ts_code(ts_code)
        self._universe.require_supported(normalized_code)
        if not 1 <= limit <= 2_000:
            raise IndexDetailRequestError("limit 必须在 1 到 2000 之间。")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise IndexDetailRequestError("startDate 不能晚于 endDate。")
        if self._daily_lake is None:
            context = self._context_query.resolve_context(
                session, market="CN_A", requested_trade_date=end_date,
            )
        else:
            try:
                context = self._context_query.resolve_local_context(
                    self._daily_lake, market="CN_A", requested_trade_date=end_date,
                )
            except IndexDailyLakeSourceError as exc:
                raise IndexNineTurnQueryError("指数日线九转读取 DG 交易日历失败。") from exc
        query_end_date = end_date or context.trade_date
        try:
            before_trade_date = decode_daily_nine_turn_cursor(
                cursor,
                dataset="index_daily_nine_turn",
                subject_type="index",
                ts_code=normalized_code,
                start_date=start_date,
                end_date=query_end_date,
            )
        except ValueError as exc:
            raise IndexDetailRequestError(str(exc)) from exc
        try:
            if self._daily_lake is None:
                page = self._query.load_daily_page(
                    session, ts_code=normalized_code, start_date=start_date, end_date=query_end_date,
                    before_trade_date=before_trade_date, limit=limit,
                )
                daily_source = "core_serving.index_factor_pro"
            else:
                origin = dg_index_daily_origin(normalized_code)
                dates = self._daily_lake.ordinary_daily_page_dates(
                    normalized_code, start=max(start_date or origin, origin), end=query_end_date,
                    before=before_trade_date, limit=limit + 1,
                )
                page = self._query.load_daily_page_for_dates(session, ts_code=normalized_code, dates=dates, limit=limit)
                daily_source = "silver/index_daily"
            for row in page.rows:
                if row["nine_turn_matched"] and row["formula_version"] != 1:
                    raise IndexNineTurnSourceContractError(
                        "指数日线九转 serving formula_version 不是 1。"
                    )
            source_row_count = len(page.rows)
            matched_row_count = sum(1 for row in page.rows if row["nine_turn_matched"])
            next_cursor = None
            if page.has_more and page.rows:
                next_cursor = encode_daily_nine_turn_cursor(
                    dataset="index_daily_nine_turn",
                    subject_type="index",
                    ts_code=normalized_code,
                    start_date=start_date,
                    end_date=query_end_date,
                    before_trade_date=page.rows[0]["trade_date"],
                )
            return build_nine_turn_response(
                subject_type="index",
                ts_code=normalized_code,
                period="day",
                rows=list(page.rows),
                source_row_count=source_row_count,
                matched_row_count=matched_row_count,
                missing_row_count=source_row_count - matched_row_count,
                has_more=page.has_more,
                next_cursor=next_cursor,
                start_date=start_date,
                end_date=query_end_date,
                expected_end_date=query_end_date,
                observed_start_date=page.observed_start_date,
                observed_end_date=page.observed_end_date,
                limit=limit,
                debug_info=(
                    {
                        "sourceTables": [
                            daily_source,
                            "core_serving.index_nineturn_daily",
                        ],
                        "beforeTradeDate": (
                            before_trade_date.isoformat()
                            if before_trade_date is not None
                            else None
                        ),
                    }
                    if debug
                    else None
                ),
            )
        except IndexNineTurnSourceContractError:
            raise
        except NineTurnContractError as exc:
            raise IndexNineTurnSourceContractError(str(exc)) from exc
        except (SQLAlchemyError, IndexDailyLakeSourceError, SourceReadError) as exc:
            raise IndexNineTurnQueryError("指数日线九转查询失败。") from exc


__all__ = [
    "IndexNineTurnQueryError",
    "IndexNineTurnQueryService",
    "IndexNineTurnSourceContractError",
]
