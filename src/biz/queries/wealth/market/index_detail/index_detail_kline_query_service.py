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
    IndexDetailIdentityDto,
    IndexDetailIndexRefDto,
    IndexDetailKlineMetaDto,
    IndexDetailKlineResponseDto,
    IndexDetailSseKlineMetaDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_field_mapper import (
    build_identity,
    build_kline_bar,
    build_page_context,
)
from src.biz.services.wealth.market.index_detail.index_detail_status_resolver import IndexDetailStatusResolver
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
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
_BOLL_FIELDS = _TECHNICAL_REQUIRED_FIELDS[:3]
SSE_DAILY_CALCULATIONS = (
    *({"calculation_id": "ma", "parameters": {"period": period}} for _, period in _MA_FIELDS),
    {"calculation_id": "boll", "parameters": {"period": 20, "multiplier": 2}},
    {"calculation_id": "macd", "parameters": {"fast": 12, "slow": 26, "signal": 9}},
    {"calculation_id": "kdj", "parameters": {"window": 9, "k_period": 3, "d_period": 3}},
)
_SSE_FACTOR_FIELDS = (
    *((("value", field),) for field, _ in _MA_FIELDS),
    tuple(zip(("upper", "middle", "lower"), _BOLL_FIELDS)),
    tuple(zip(("dif", "dea", "hist"), _TECHNICAL_REQUIRED_FIELDS[3:6])),
    tuple(zip(("k", "d", "j"), _TECHNICAL_REQUIRED_FIELDS[6:])),
)
SSE_DAILY_AUX_FIELDS = ("vol", "amount", "pre_close", "change_amount", "pct_chg")
PriceRows = list[dict[str, Any]]
CalculateDailyFactors = Callable[[tuple[date, ...]], tuple[CalculationResult, int, tuple]]
CalculateRecentDaily = Callable[[date, date, int], CalculationWithSource]


def apply_calculated_kline_factors(ts_code, rows, calculations):
    instances = {(item.calculation_id, tuple(sorted(dict(item.parameters).items()))): dict(item.fields)
                 for item in calculations}
    if len(calculations) != len(_SSE_FACTOR_FIELDS) or len(instances) != len(_SSE_FACTOR_FIELDS):
        raise IndexDetailQueryError(f"{ts_code} 本页指标实例不完整")
    for request, fields in zip(SSE_DAILY_CALCULATIONS, _SSE_FACTOR_FIELDS, strict=True):
        key = request["calculation_id"], tuple(sorted(request["parameters"].items()))
        values_by_field = instances.get(key, {})
        for result_field, row_field in fields:
            values = values_by_field.get(result_field)
            if values is None or len(values) != len(rows):
                raise IndexDetailQueryError(f"{ts_code} 指标结果字段不完整：{key[0]}.{result_field}")
            for row, value in zip(rows, values, strict=True):
                row[row_field] = value


def count_calculated_kline_missing(rows, preceding_rows):
    required = _BASE_REQUIRED_FIELDS + _TECHNICAL_REQUIRED_FIELDS[3:]
    windowed = _MA_FIELDS + tuple((name, 20) for name in _BOLL_FIELDS)
    return sum(
        sum(row[name] is None for name in required)
        + sum(row[name] is None and effective_count >= period for name, period in windowed)
        for effective_count, row in enumerate(rows, start=preceding_rows + 1)
    )


class IndexDetailKlineQueryService:
    """Assemble factor-only index daily K-line responses."""

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
            identity = self._build_identity_or_raise(self._query.load_identity(session, ts_code=ts_code), ts_code=ts_code)
            context = self._context_query.resolve_context(session, market="CN_A", requested_trade_date=end_date)
            query_end_date = end_date or context.trade_date
            rows = self._query.load_kline_rows(
                session, ts_code=ts_code, end_date=query_end_date, start_date=start_date, limit=limit,
            )
        else:
            identity = self._build_identity_or_raise(daily_lake.index_identity(ts_code), ts_code=ts_code)
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
        identity = self._build_identity_or_raise(self._daily_lake.index_identity(ts_code), ts_code=ts_code)
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
        rows, missing_count, next_end = [], None, None
        if query_end < lower:
            if context is None:
                calendar = self._daily_lake.calendar_rows(start=query_end, end=query_end)
        else:
            calculated = calculate(query_end, lower, limit)
            facts = calculated.source_facts
            if context is None:
                calendar = tuple((day.trade_date, day.is_open, day.pretrade_date) for day in facts.calendar_days)
            result = calculated.result
            if result is not None:
                dates = tuple(bar.trade_date for bar in facts.target_bars)
                if dates != result.times or len(dates) != result.range.count:
                    raise IndexDetailQueryError(f"{ts_code} 指标结果日期或根数与本页行情不一致")
                *indicators, price = result.calculations
                values = dict(price.fields)
                for index, bar in enumerate(facts.target_bars):
                    vol, amount = values["volume"][index], values["amount"][index]
                    rows.append({
                        "trade_date": bar.trade_date,
                        **{name: values[name][index] for name in ("open", "high", "low", "close")},
                        "pre_close": bar.pre_close, "change": bar.change_amount, "pct_change": bar.pct_chg,
                        "vol": None if vol is None else vol / 100,
                        "amount": None if amount is None else amount / 1000,
                    })
                apply_calculated_kline_factors(ts_code, rows, indicators)
                missing_count = count_calculated_kline_missing(rows, calculated.selection.preceding_rows)
                next_end = facts.previous_target_date
        if context is None:
            context = self._context_query.resolve_local_context(
                self._daily_lake, market="CN_A", requested_trade_date=end_date, now=now, calendar_rows=calendar,
            )
        check_active()
        return self._calculated_daily_response(context, identity, rows, missing_count, start_date, limit, next_end)

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
        identity = self._build_identity_or_raise(identity_row, ts_code=ts_code)
        dates = tuple(row[0] for row in window)
        rows, missing_count = [], None
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
            if result.range.count != len(rows):
                raise IndexDetailQueryError(f"{ts_code} 指标结果日期或根数与本页行情不一致")
            apply_calculated_kline_factors(ts_code, rows, result.calculations)
            missing_count = count_calculated_kline_missing(rows, preceding_rows)
        next_end = window[0][2] if len(window) == limit else None
        if next_end is not None and start_date is not None and next_end < start_date:
            next_end = None
        return self._calculated_daily_response(context, identity, rows, missing_count, start_date, limit, next_end)

    def _calculated_daily_response(self, context, identity, rows, missing_count, start_date, limit, next_end):
        query_end = context.trade_date
        expected_end = query_end if context.is_trading_day else context.prev_trade_date
        data_status = self._status_resolver.resolve(
            expected_trade_date=expected_end or query_end,
            observed_trade_date=rows[-1]["trade_date"] if rows else None,
            empty=not rows, partial=bool(missing_count),
        )
        return IndexDetailKlineResponseDto(
            pageContext=build_page_context(context),
            indexRef=IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
            period="day", bars=[build_kline_bar(row) for row in rows],
            meta=IndexDetailSseKlineMetaDto(
                count=len(rows), limit=limit, startDate=start_date, endDate=query_end, nextEndDate=next_end,
            ),
            dataStatus=data_status,
        ), missing_count

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

    @staticmethod
    def _build_identity_or_raise(
        identity_row: Mapping[str, Any] | None, *, ts_code: str,
    ) -> IndexDetailIdentityDto:
        if identity_row is None:
            raise IndexDetailNotFoundError(f"未找到指数身份：{ts_code}")
        try:
            return build_identity(identity_row)
        except ValueError as exc:
            raise IndexDetailNotFoundError(f"指数身份缺少名称：{ts_code}") from exc
