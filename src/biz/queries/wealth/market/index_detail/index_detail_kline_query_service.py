from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.queries.wealth.market.index_detail.index_detail_query import (
    _KLINE_FIELD_NAMES, IndexDetailQuery,
)
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailIndexRefDto,
    IndexDetailKlineMetaDto,
    IndexDetailKlineResponseDto,
)
from src.biz.services.wealth.market.index_detail.index_daily_kline_service import IndexDailyKlineService
from src.biz.services.wealth.market.index_detail.index_detail_field_mapper import (
    build_kline_bar, build_page_context, require_index_kline_identity,
)
from src.biz.services.wealth.market.index_detail.index_detail_status_resolver import IndexDetailStatusResolver
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailQueryError,
    IndexDetailRequestError,
    IndexDetailUniverseService,
)
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader, IndexDailyLakeSourceError
from src.foundation.clients.technical_indicator_stock_daily import dg_index_daily_origin
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from goldenshare_technical_indicators.contracts import CalculationResult
from goldenshare_technical_indicators.sources.contracts import CalculationWithSource


_BASE_REQUIRED_FIELDS = ("open", "high", "low", "close", "pre_close", "change", "pct_change", "vol", "amount")
_TECHNICAL_REQUIRED_FIELDS = (
    "boll_upper_bfq",
    "boll_mid_bfq",
    "boll_lower_bfq",
    "macd_dif_bfq",
    "macd_dea_bfq",
    "macd_bfq",
    "kdj_k_bfq",
    "kdj_d_bfq",
    "kdj_bfq",
)
_MA_FIELDS: tuple[tuple[str, int], ...] = (
    ("ma_bfq_5", 5),
    ("ma_bfq_10", 10),
    ("ma_bfq_20", 20),
    ("ma_bfq_30", 30),
    ("ma_bfq_60", 60),
    ("ma_bfq_90", 90),
    ("ma_bfq_250", 250),
)
SSE_DAILY_AUX_FIELDS = ("vol", "amount", "pre_close", "change_amount", "pct_chg")
CalculateDailyFactors = Callable[[tuple[date, ...]], tuple[CalculationResult, int, tuple]]
CalculateRecentDaily = Callable[[date, date, int], CalculationWithSource]


class IndexDetailKlineQueryService:
    """Assemble index daily K-line responses from the selected source."""

    def __init__(self, *, daily_lake: IndexDailyLakeReader | None = None) -> None:
        self._universe_service = IndexDetailUniverseService()
        self._context_query = MarketPageContextQuery()
        self._query = IndexDetailQuery()
        self._daily_lake = daily_lake
        self._status_resolver = IndexDetailStatusResolver()

    def build_kline(self, session: Session | None, **params) -> IndexDetailKlineResponseDto:
        return self.query_kline(session, **params)[0]

    def query_kline(
        self,
        session: Session | None,
        *,
        ts_code: str,
        period: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        calculate: CalculateDailyFactors | None = None,
        calculate_recent: CalculateRecentDaily | None = None,
        source_origin: date | None = None,
        check_active: Callable[[], None] | None = None,
    ) -> tuple[IndexDetailKlineResponseDto, int | None]:
        if period != "day":
            raise IndexDetailRequestError("指数详情只支持 period=day")
        if limit < 1 or limit > 2000:
            raise IndexDetailRequestError("limit 必须在 1 到 2000 之间")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise IndexDetailRequestError("startDate 不能晚于 endDate")

        self._universe_service.require_supported(ts_code)
        if calculate_recent is not None:
            return self._build_recent_daily_kline(
                ts_code=ts_code, start_date=start_date, end_date=end_date, limit=limit,
                calculate=calculate_recent, check_active=check_active,
            )
        if calculate is not None:
            assert source_origin is not None and check_active is not None
            return self._build_calculated_daily_kline(
                session, ts_code=ts_code, start_date=start_date, end_date=end_date,
                limit=limit, source_origin=source_origin,
                calculate=calculate, check_active=check_active,
            )
        daily_lake = None if ts_code == "899050.BJ" else self._daily_lake
        history_before = None
        if daily_lake is None:
            identity = require_index_kline_identity(self._query.load_identity(session, ts_code=ts_code), ts_code=ts_code)
            context = self._context_query.resolve_context(session, market="CN_A", requested_trade_date=end_date)
            query_end_date = end_date or context.trade_date
            rows = self._query.load_kline_rows(
                session, ts_code=ts_code, end_date=query_end_date, start_date=start_date, limit=limit,
            )
        else:
            identity = require_index_kline_identity(daily_lake.index_identity(ts_code), ts_code=ts_code)
            context = self._context_query.resolve_local_context(
                daily_lake, market="CN_A", requested_trade_date=end_date,
            )
            query_end_date = end_date or context.trade_date
            rows, history_before = self._load_lake_rows(
                daily_lake, ts_code=ts_code, start_date=start_date, end_date=query_end_date, limit=limit,
            )
        observed_trade_date = rows[-1]["trade_date"] if rows else None
        if not rows:
            data_status = self._status_resolver.resolve(
                expected_trade_date=query_end_date,
                observed_trade_date=None,
                empty=True,
                partial=False,
            )
            return IndexDetailKlineResponseDto(
                pageContext=build_page_context(context),
                indexRef=IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
                period="day",
                bars=[],
                meta=IndexDetailKlineMetaDto(
                    count=0,
                    limit=limit,
                    startDate=start_date,
                    endDate=query_end_date,
                ),
                dataStatus=data_status,
            ), None

        missing_count = self._count_non_ma_missing(rows)
        ma_missing_after_warmup = self._has_ma_missing_after_effective_history(
            session,
            ts_code=ts_code,
            rows=rows,
            daily_lake=daily_lake,
            history_before=history_before,
        )
        if ma_missing_after_warmup:
            missing_count += 1
        if daily_lake is None:
            latest_daily_date = self._query.load_latest_daily_date(
                session, ts_code=ts_code, end_date=query_end_date,
            )
            factor_lags_completed_daily = latest_daily_date is not None and observed_trade_date < latest_daily_date
        else:
            factor_lags_completed_daily = observed_trade_date < query_end_date and daily_lake.has_daily_after(
                ts_code=ts_code, after=observed_trade_date, end=query_end_date,
            )
        if factor_lags_completed_daily:
            missing_count += 1
        partial = missing_count > 0
        data_status = self._status_resolver.resolve(
            expected_trade_date=query_end_date,
            observed_trade_date=observed_trade_date,
            empty=False,
            partial=partial,
        )
        return IndexDetailKlineResponseDto(
            pageContext=build_page_context(context),
            indexRef=IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
            period="day",
            bars=[build_kline_bar(row) for row in rows],
            meta=IndexDetailKlineMetaDto(
                count=len(rows),
                limit=limit,
                startDate=start_date,
                endDate=query_end_date,
            ),
            dataStatus=data_status,
        ), missing_count

    def _build_recent_daily_kline(
        self, *, ts_code: str, start_date: date | None, end_date: date | None, limit: int,
        calculate: CalculateRecentDaily, check_active: Callable[[], None],
    ) -> tuple[IndexDetailKlineResponseDto, int | None]:
        lower = dg_index_daily_origin(ts_code)
        if start_date is not None:
            lower = max(lower, start_date)
        check_active()
        identity = require_index_kline_identity(self._daily_lake.index_identity(ts_code), ts_code=ts_code)
        check_active()
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        context = None
        if end_date is None:
            context = self._context_query.resolve_local_context(
                self._daily_lake, market="CN_A", requested_trade_date=None, now=now,
            )
            query_end = context.trade_date
        else:
            query_end = end_date
        page, next_end = None, None
        if query_end < lower:
            if context is None:
                calendar = self._daily_lake.calendar_rows(start=query_end, end=query_end)
        else:
            calculated = calculate(query_end, lower, limit)
            facts = calculated.source_facts
            if context is None:
                calendar = tuple((day.trade_date, day.is_open, day.pretrade_date) for day in facts.calendar_days)
            if calculated.result is not None:
                page = IndexDailyKlineService.prepare_local_result(ts_code, calculated)
                next_end = facts.previous_target_date
        if context is None:
            context = self._context_query.resolve_local_context(
                self._daily_lake, market="CN_A", requested_trade_date=end_date, now=now, calendar_rows=calendar,
            )
        check_active()
        return IndexDailyKlineService.assemble(
            context=context, identity=identity, page=page, start_date=start_date, limit=limit,
            next_end=next_end, include_nine_turn=True,
        )

    def _build_calculated_daily_kline(
        self, session: Session | None, *, ts_code: str, start_date: date | None, end_date: date | None,
        limit: int, source_origin: date, calculate: CalculateDailyFactors,
        check_active: Callable[[], None],
    ) -> tuple[IndexDetailKlineResponseDto, int | None]:
        lower = max(source_origin, start_date or source_origin)
        check_active()
        identity_row = self._query.load_identity(session, ts_code=ts_code)
        context, window = self._context_query.resolve_sse_kline_context(
            session, requested_trade_date=end_date, start=lower, limit=limit,
        )
        identity = require_index_kline_identity(identity_row, ts_code=ts_code)
        dates = tuple(row[0] for row in window)
        rows, page = [], None
        if dates:
            result, preceding_rows, target_ohlc = calculate(dates)
            if result.times != dates or target_ohlc is None or len(target_ohlc) != len(dates):
                raise IndexDetailQueryError(f"{ts_code} 指标结果日期或根数与本页行情不一致")
            aux = self._read_sse_auxiliary(session, ts_code, dates)
            if tuple(aux) != dates:
                raise IndexDetailQueryError(f"{ts_code} 读取数据失败：数据缺失")
            for day, (open_price, high, low, close) in zip(dates, target_ohlc, strict=True):
                row = aux[day]
                rows.append({
                    "trade_date": day, "open": open_price, "high": high, "low": low, "close": close,
                    "pre_close": row["pre_close"], "change": row["change_amount"], "pct_change": row["pct_chg"],
                    "vol": row["vol"], "amount": row["amount"],
                })
            page = IndexDailyKlineService.prepare_prod_result(ts_code, rows, result, preceding_rows)
        next_end = window[0][2] if len(window) == limit else None
        if next_end is not None and start_date is not None and next_end < start_date:
            next_end = None
        return IndexDailyKlineService.assemble(
            context=context, identity=identity, page=page, start_date=start_date, limit=limit,
            next_end=next_end, include_nine_turn=False,
        )

    @staticmethod
    def _read_sse_auxiliary(session, ts_code, dates):
        statement = select(IndexDailyServing.trade_date, *(getattr(IndexDailyServing, name)
                                                           for name in SSE_DAILY_AUX_FIELDS)).where(
            IndexDailyServing.ts_code == ts_code, IndexDailyServing.trade_date.in_(dates),
        ).order_by(IndexDailyServing.trade_date)
        return {row["trade_date"]: dict(row) for row in session.execute(statement).mappings()}

    @staticmethod
    def _count_non_ma_missing(rows: list[Mapping[str, Any]]) -> int:
        field_names = _BASE_REQUIRED_FIELDS + _TECHNICAL_REQUIRED_FIELDS
        return sum(1 for row in rows for field_name in field_names if row.get(field_name) is None)

    @staticmethod
    def _load_lake_rows(
        reader: IndexDailyLakeReader,
        *,
        ts_code: str,
        start_date: date | None,
        end_date: date,
        limit: int,
    ) -> tuple[list[dict[str, Any]], date | None]:
        dates = reader.factor_dates(start=start_date, end=end_date)
        rows = []
        stop = len(dates)
        while stop and len(rows) < limit:
            remaining = limit - len(rows)
            start = max(0, stop - remaining)
            rows.extend(reader.factor_rows(
                ts_code=ts_code, dates=dates[start:stop], columns=_KLINE_FIELD_NAMES,
                limit=remaining, descending=True,
            ))
            stop = start
        rows.reverse()
        return rows, dates[stop] if dates else None

    @staticmethod
    def _count_lake_history(
        reader: IndexDailyLakeReader,
        *,
        ts_code: str,
        before: date,
    ) -> int:
        dates = reader.factor_dates(start=None, end=before - timedelta(days=1))
        max_period = max(period for _, period in _MA_FIELDS)
        count = 0
        stop = len(dates)
        while stop and count < max_period:
            remaining = max_period - count
            start = max(0, stop - remaining)
            rows = reader.factor_rows(
                ts_code=ts_code, dates=dates[start:stop], columns=("trade_date", "close"),
                limit=remaining, descending=True,
            )
            count += sum(row["close"] is not None for row in rows)
            stop = start
        return count

    def _has_ma_missing_after_effective_history(
        self,
        session: Session,
        *,
        ts_code: str,
        rows: list[Mapping[str, Any]],
        daily_lake: IndexDailyLakeReader | None,
        history_before: date | None,
    ) -> bool:
        if not any(row.get(field_name) is None for row in rows for field_name, _period in _MA_FIELDS):
            return False
        if daily_lake is None:
            effective_count = self._query.count_effective_history_before(
                session, ts_code=ts_code, first_trade_date=rows[0]["trade_date"],
            )
        else:
            # A newer partition already examined by the chart cannot contain
            # an earlier target row. Only look beyond that window for warmup.
            effective_count = self._count_lake_history(
                daily_lake, ts_code=ts_code, before=history_before or rows[0]["trade_date"],
            )
        for row in rows:
            if row.get("close") is not None:
                effective_count += 1
            for field_name, period in _MA_FIELDS:
                if row.get(field_name) is None and effective_count >= period:
                    return True
        return False
