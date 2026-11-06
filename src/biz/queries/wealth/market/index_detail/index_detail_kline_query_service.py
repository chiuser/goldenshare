from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.queries.wealth.market.index_detail.index_detail_query import (
    _KLINE_FIELD_NAMES, _KLINE_PRICE_FIELDS, IndexDetailQuery,
)
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailDataStatusDto,
    IndexDetailDebugInfoDto,
    IndexDetailIdentityDto,
    IndexDetailIndexRefDto,
    IndexDetailKlineMetaDto,
    IndexDetailKlineResponseDto,
    IndexDetailModuleDebugDto,
    IndexDetailSseKlineMetaDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_exception_builder import IndexDetailExceptionBuilder
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
from src.foundation.technical_indicators.contracts import CalculationInstance, CalculationResult


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
    *(CalculationInstance(f"ma{period}", "ma", {"period": period}) for _, period in _MA_FIELDS),
    CalculationInstance("boll", "boll", {"period": 20, "multiplier": 2}),
    CalculationInstance("macd", "macd", {"fast": 12, "slow": 26, "signal": 9}),
    CalculationInstance("kdj", "kdj", {"window": 9, "k_period": 3, "d_period": 3}),
)
_SSE_FACTOR_FIELDS = {
    **{f"ma{period}": (("value", field),) for field, period in _MA_FIELDS},
    "boll": tuple(zip(("upper", "middle", "lower"), _BOLL_FIELDS)),
    "macd": tuple(zip(("dif", "dea", "hist"), _TECHNICAL_REQUIRED_FIELDS[3:6])),
    "kdj": tuple(zip(("k", "d", "j"), _TECHNICAL_REQUIRED_FIELDS[6:])),
}
_PRICE_LABELS = {"open": "开盘价", "high": "最高价", "low": "最低价", "close": "收盘价"}
PriceRows = list[dict[str, Any]]
ReadPrevious = Callable[[date, int], PriceRows]
CalculateDailyFactors = Callable[[PriceRows, ReadPrevious], tuple[CalculationResult, int]]


class IndexDetailKlineQueryService:
    """Assemble factor-only index daily K-line responses."""

    def __init__(self, *, daily_lake: IndexDailyLakeReader | None = None) -> None:
        self._universe_service = IndexDetailUniverseService()
        self._context_query = MarketPageContextQuery()
        self._query = IndexDetailQuery()
        self._daily_lake = daily_lake
        self._status_resolver = IndexDetailStatusResolver()
        self._exception_builder = IndexDetailExceptionBuilder()

    def build_kline(
        self,
        session: Session | None,
        *,
        ts_code: str,
        period: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        debug: bool,
        calculate: CalculateDailyFactors | None = None,
        source_origin: date | None = None,
        check_active: Callable[[], None] | None = None,
    ) -> IndexDetailKlineResponseDto:
        if period != "day":
            raise IndexDetailRequestError("指数详情只支持 period=day")
        if limit < 1 or limit > 2000:
            raise IndexDetailRequestError("limit 必须在 1 到 2000 之间")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise IndexDetailRequestError("startDate 不能晚于 endDate")

        self._universe_service.require_supported(ts_code)
        if calculate is not None:
            assert source_origin is not None and check_active is not None
            return self._build_sse_kline(
                session, ts_code=ts_code, start_date=start_date, end_date=end_date,
                limit=limit, debug=debug, source_origin=source_origin,
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
            exceptions = [
                self._exception_builder.source_empty(
                    module="indexDetailKline",
                    message="指数因子日线无可用数据",
                )
            ]
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
                debugInfo=(
                    IndexDetailDebugInfoDto(
                        modules=[self._module_debug(data_status, row_count=0, missing_count=None)],
                        exceptions=exceptions,
                    )
                    if debug
                    else None
                ),
            )

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
        exceptions = []
        if partial:
            exceptions.append(
                self._exception_builder.factor_partial(
                    module="indexDetailKline",
                    message="指数日线因子存在缺失或落后",
                )
            )
        if observed_trade_date is not None and observed_trade_date < query_end_date:
            exceptions.append(
                self._exception_builder.source_delayed(
                    module="indexDetailKline",
                    message="指数因子观测日期落后于查询上界",
                )
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
            debugInfo=(
                IndexDetailDebugInfoDto(
                    modules=[self._module_debug(data_status, row_count=len(rows), missing_count=missing_count)],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    def _build_sse_kline(
        self, session: Session | None, *, ts_code: str, start_date: date | None, end_date: date | None,
        limit: int, debug: bool, source_origin: date, calculate: CalculateDailyFactors,
        check_active: Callable[[], None],
    ) -> IndexDetailKlineResponseDto:
        lower = max(source_origin, start_date or source_origin)
        check_active()
        if self._daily_lake is not None:
            identity_row = self._daily_lake.index_identity(ts_code)
            check_active()
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            calendar = self._daily_lake.calendar_rows(
                end=end_date or now.date(),
                start=min(lower, end_date) if end_date is not None else None,
                recent_open_days=(None if end_date < lower else limit) if end_date is not None else limit + 1,
            )
            check_active()
            context = self._context_query.resolve_local_context(
                self._daily_lake, market="CN_A", requested_trade_date=end_date, now=now, calendar_rows=calendar,
            )
            expected_end = context.trade_date if context.is_trading_day else context.prev_trade_date
            window = tuple(row for row in calendar if row[1] and expected_end is not None
                           and lower <= row[0] <= expected_end)[-limit:]
        else:
            identity_row = self._query.load_identity(session, ts_code=ts_code)
            context, window = self._context_query.resolve_sse_kline_context(
                session, requested_trade_date=end_date, start=lower, limit=limit,
            )
            expected_end = context.trade_date if context.is_trading_day else context.prev_trade_date
        identity = self._build_identity_or_raise(identity_row, ts_code=ts_code)
        query_end = context.trade_date
        dates = tuple(row[0] for row in window)
        rows = self._read_sse_rows(session, ts_code, dates, _KLINE_PRICE_FIELDS, check_active)

        def read_previous(before: date, warmup: int) -> PriceRows:
            if before <= source_origin:
                return []
            check_active()
            if self._daily_lake is not None:
                previous = tuple(day for day, opened, _ in self._daily_lake.calendar_rows(
                    end=before - timedelta(days=1), start=source_origin, recent_open_days=warmup,
                ) if opened)
            else:
                previous = self._context_query.load_sse_preceding_dates(
                    session, before=before, start=source_origin, limit=warmup,
                )
            return self._read_sse_rows(session, ts_code, previous, ("trade_date", "high", "low", "close"), check_active)

        exceptions = []
        missing_count = None
        if rows:
            result, preceding_rows = calculate(rows, read_previous)
            self._apply_sse_factors(ts_code, rows, dates, result)
            missing_count = self._count_sse_missing(rows, preceding_rows)
            if missing_count:
                exceptions.append(self._exception_builder.factor_partial(
                    module="indexDetailKline", message="指数日线因子存在缺失或落后",
                ))
        else:
            exceptions.append(self._exception_builder.source_empty(
                module="indexDetailKline", message="指数因子日线无可用数据",
            ))
        next_end = window[0][2] if len(window) == limit else None
        if next_end is not None and start_date is not None and next_end < start_date:
            next_end = None
        data_status = self._status_resolver.resolve(
            expected_trade_date=expected_end or query_end, observed_trade_date=dates[-1] if dates else None,
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
            debugInfo=IndexDetailDebugInfoDto(
                modules=[self._module_debug(data_status, row_count=len(rows), missing_count=missing_count)],
                exceptions=exceptions,
            ) if debug else None,
        )

    def _read_sse_rows(
        self, session: Session | None, ts_code: str, dates: tuple[date, ...],
        fields: tuple[str, ...], check_active: Callable[[], None],
    ) -> PriceRows:
        if not dates:
            return []
        check_active()
        if self._daily_lake is not None:
            try:
                rows = self._daily_lake.factor_rows(ts_code=ts_code, dates=dates, columns=fields, limit=len(dates))
            except IndexDailyLakeSourceError as exc:
                detail = str(exc.__cause__)
                failed_day = next((day for day in dates if f"trade_date={day}/" in detail), None)
                if failed_day is not None:
                    raise IndexDetailQueryError(f"{ts_code} {failed_day} 日线行情文件读取失败") from exc
                raise IndexDetailQueryError(f"{ts_code} 日线行情读取失败") from exc
        else:
            rows = self._query.load_kline_rows(
                session, ts_code=ts_code, start_date=dates[0], end_date=dates[-1], limit=len(dates), fields=fields,
            )
        check_active()
        actual_dates = tuple(row["trade_date"] for row in rows)
        if actual_dates != dates:
            missing = next((day for day in dates if day not in actual_dates), None)
            if missing is not None:
                raise IndexDetailQueryError(f"{ts_code} {missing} 缺少交易日日线行情")
            expected, actual = next((want, got) for want, got in zip(dates, actual_dates) if want != got)
            raise IndexDetailQueryError(f"{ts_code} {actual} 日线行情日期重复、乱序或超出范围，应为 {expected}")
        for row in rows:
            for field, label in _PRICE_LABELS.items():
                if field not in fields:
                    continue
                value = row[field]
                if value is None:
                    raise IndexDetailQueryError(f"{ts_code} {row['trade_date']} {label}缺失")
                if not isfinite(value):
                    raise IndexDetailQueryError(f"{ts_code} {row['trade_date']} {label}无效")
        return rows

    @staticmethod
    def _apply_sse_factors(ts_code: str, rows: PriceRows, dates: tuple[date, ...], result: CalculationResult) -> None:
        if result.times != dates or result.range.count != len(rows):
            raise IndexDetailQueryError(f"{ts_code} 指标结果日期或根数与本页行情不一致")
        instances = {item.instance_id: dict(item.fields) for item in result.calculations}
        if len(result.calculations) != len(_SSE_FACTOR_FIELDS) or instances.keys() != _SSE_FACTOR_FIELDS.keys():
            raise IndexDetailQueryError(f"{ts_code} 本页指标实例不完整")
        for instance, fields in _SSE_FACTOR_FIELDS.items():
            values_by_field = instances[instance]
            for result_field, row_field in fields:
                values = values_by_field.get(result_field)
                if values is None or len(values) != len(rows):
                    raise IndexDetailQueryError(f"{ts_code} 指标结果字段不完整：{instance}.{result_field}")
                for row, value in zip(rows, values):
                    row[row_field] = value

    @staticmethod
    def _count_sse_missing(rows: PriceRows, preceding_rows: int) -> int:
        required = _BASE_REQUIRED_FIELDS + _TECHNICAL_REQUIRED_FIELDS[3:]
        windowed = _MA_FIELDS + tuple((name, 20) for name in _BOLL_FIELDS)
        return sum(
            sum(row[name] is None for name in required)
            + sum(row[name] is None and effective_count >= period for name, period in windowed)
            for effective_count, row in enumerate(rows, start=preceding_rows + 1)
        )

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
    def _module_debug(
        data_status: IndexDetailDataStatusDto,
        *,
        row_count: int,
        missing_count: int | None,
    ) -> IndexDetailModuleDebugDto:
        return IndexDetailModuleDebugDto(
            module="kline",
            status=data_status.status,
            expectedTradeDate=data_status.expectedTradeDate,
            observedTradeDate=data_status.observedTradeDate,
            rowCount=row_count,
            missingCount=missing_count,
        )

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
