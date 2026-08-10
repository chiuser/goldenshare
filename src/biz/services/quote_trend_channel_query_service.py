from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from threading import RLock
from typing import ContextManager
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.queries.quote_trend_channel_query import (
    TREND_CHANNEL_TS_CODE,
    QuoteTrendChannelQuery,
    QuoteTrendChannelQueryError,
    TrendChannelInstrumentRow,
    TrendChannelSourceRow,
    TrendChannelWatermark,
)
from src.biz.schemas.quote_trend_channel import (
    TrendChannelBandDto,
    TrendChannelBarDto,
    TrendChannelDataStatusDto,
    TrendChannelFormulaDto,
    TrendChannelInstrumentDto,
    TrendChannelMetaDto,
    TrendChannelResponse,
)
from src.biz.services.quote_trend_channel_calculator import (
    FORMULA_KEY,
    FORMULA_VERSION,
    LONG_PERIOD,
    MAX_SOURCE_ROWS,
    SHORT_PERIOD,
    ComputedTrendChannelRow,
    TrendChannelCalculator,
    TrendChannelInputError,
    TrendChannelInvariantError,
)


SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class TrendChannelCacheKey:
    source_identity: str
    ts_code: str
    formula_version: str
    row_count: int
    max_trade_date: date | None
    max_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class TrendChannelSeries:
    watermark: TrendChannelWatermark
    rows: tuple[ComputedTrendChannelRow, ...]


class TrendChannelSeriesCache:
    def __init__(self, *, max_entries: int = 2) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[TrendChannelCacheKey, TrendChannelSeries] = OrderedDict()
        self._entries_lock = RLock()
        self._compute_lock = RLock()

    def get(self, key: TrendChannelCacheKey) -> TrendChannelSeries | None:
        with self._entries_lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: TrendChannelCacheKey, value: TrendChannelSeries) -> None:
        with self._entries_lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._entries_lock:
            self._entries.clear()

    def compute_lock(self) -> ContextManager[None]:
        return self._compute_lock


@lru_cache(maxsize=1)
def get_quote_trend_channel_cache() -> TrendChannelSeriesCache:
    return TrendChannelSeriesCache(max_entries=2)


class TrendChannelInstrumentMissingError(RuntimeError):
    pass


class TrendChannelSourceUnavailableError(RuntimeError):
    pass


class TrendChannelSourceInvalidError(RuntimeError):
    def __init__(
        self,
        *,
        reason_code: str,
        trade_date: date | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.trade_date = trade_date
        super().__init__(reason_code)


class TrendChannelSourceChangingError(RuntimeError):
    pass


class TrendChannelComputeError(RuntimeError):
    def __init__(
        self,
        *,
        reason_code: str,
        trade_date: date | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.trade_date = trade_date
        super().__init__(reason_code)


class QuoteTrendChannelQueryService:
    def __init__(
        self,
        *,
        query: QuoteTrendChannelQuery | None = None,
        calculator: TrendChannelCalculator | None = None,
        cache: TrendChannelSeriesCache | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._query = query or QuoteTrendChannelQuery()
        self._calculator = calculator or TrendChannelCalculator()
        self._cache = cache if cache is not None else get_quote_trend_channel_cache()
        self._now_provider = now_provider or (
            lambda: datetime.now(tz=SHANGHAI_TIMEZONE)
        )

    def load_instrument(self, session: Session) -> TrendChannelInstrumentRow:
        try:
            instrument = self._query.load_instrument(session)
        except QuoteTrendChannelQueryError as exc:
            raise TrendChannelSourceUnavailableError(
                "trend channel instrument source unavailable"
            ) from exc
        if instrument is None:
            raise TrendChannelInstrumentMissingError("trend channel instrument missing")
        return instrument

    def load_series(self, session: Session) -> TrendChannelSeries:
        try:
            return self._load_consistent_series(session)
        except QuoteTrendChannelQueryError as exc:
            raise TrendChannelSourceUnavailableError(
                "trend channel source unavailable"
            ) from exc
        except TrendChannelInputError as exc:
            raise TrendChannelSourceInvalidError(
                reason_code=exc.reason_code,
                trade_date=exc.trade_date,
            ) from exc
        except TrendChannelInvariantError as exc:
            raise TrendChannelComputeError(
                reason_code=exc.reason_code,
                trade_date=exc.trade_date,
            ) from exc

    def build_response(
        self,
        session: Session,
        *,
        end_date: date | None,
        limit: int,
    ) -> TrendChannelResponse:
        instrument = self.load_instrument(session)
        series = self.load_series(session)
        rows = series.rows

        if rows:
            effective_end_date = end_date or rows[-1].trade_date
            trade_dates = tuple(row.trade_date for row in rows)
            end_index = bisect_right(trade_dates, effective_end_date)
            start_index = max(0, end_index - limit)
            selected = rows[start_index:end_index]
            has_more_history = start_index > 0
            next_end_date = (
                rows[start_index - 1].trade_date if has_more_history else None
            )
        else:
            selected = ()
            has_more_history = False
            next_end_date = None

        if selected:
            status = "READY"
            note = None
        elif rows:
            status = "EMPTY"
            note = "no_rows_on_or_before_end_date"
        else:
            status = "EMPTY"
            note = "source_has_no_daily_rows"

        bars = [_build_bar_dto(row) for row in selected]
        return TrendChannelResponse(
            instrument=TrendChannelInstrumentDto(
                ts_code=TREND_CHANNEL_TS_CODE,
                name=instrument.name or "上证指数",
            ),
            formula=TrendChannelFormulaDto(
                key=FORMULA_KEY,
                version=FORMULA_VERSION,
                short_period=SHORT_PERIOD,
                long_period=LONG_PERIOD,
                seed="first_observation",
                state_rule="strict_close_breakout_inside_retention",
            ),
            data_status=TrendChannelDataStatusDto(
                status=status,
                observed_trade_date=series.watermark.max_trade_date,
                as_of_time=self._now_provider(),
                note=note,
            ),
            bars=bars,
            meta=TrendChannelMetaDto(
                bar_count=len(bars),
                limit=limit,
                start_date=selected[0].trade_date if selected else None,
                end_date=selected[-1].trade_date if selected else None,
                has_more_history=has_more_history,
                next_end_date=next_end_date,
            ),
        )

    def _load_consistent_series(self, session: Session) -> TrendChannelSeries:
        source_identity = _source_identity(session)

        for _attempt in range(2):
            watermark_before = self._query.load_watermark(session)
            key_before = _cache_key(source_identity, watermark_before)
            cached = self._cache.get(key_before)
            if cached is not None:
                return cached

            with self._cache.compute_lock():
                watermark_locked = self._query.load_watermark(session)
                key_locked = _cache_key(source_identity, watermark_locked)
                cached = self._cache.get(key_locked)
                if cached is not None:
                    return cached

                if watermark_locked.row_count > MAX_SOURCE_ROWS:
                    raise TrendChannelSourceInvalidError(
                        reason_code="source_row_limit_exceeded"
                    )

                source_rows = self._query.load_all_rows(session)
                watermark_after = self._query.load_watermark(session)
                if not _snapshot_matches_watermark(
                    rows=source_rows,
                    expected=watermark_locked,
                    observed_after=watermark_after,
                ):
                    continue

                computed_rows = self._calculator.calculate(source_rows)
                series = TrendChannelSeries(
                    watermark=watermark_locked,
                    rows=computed_rows,
                )
                self._cache.put(key_locked, series)
                return series

        raise TrendChannelSourceChangingError("trend channel source kept changing")


def _source_identity(session: Session) -> str:
    bind = session.get_bind()
    root_bind = getattr(bind, "engine", bind)
    return f"{bind.dialect.name}:{id(root_bind)}"


def _cache_key(
    source_identity: str,
    watermark: TrendChannelWatermark,
) -> TrendChannelCacheKey:
    return TrendChannelCacheKey(
        source_identity=source_identity,
        ts_code=TREND_CHANNEL_TS_CODE,
        formula_version=FORMULA_VERSION,
        row_count=watermark.row_count,
        max_trade_date=watermark.max_trade_date,
        max_updated_at=watermark.max_updated_at,
    )


def _snapshot_matches_watermark(
    *,
    rows: tuple[TrendChannelSourceRow, ...],
    expected: TrendChannelWatermark,
    observed_after: TrendChannelWatermark,
) -> bool:
    if expected != observed_after or len(rows) != expected.row_count:
        return False
    if expected.row_count == 0:
        return (
            not rows
            and expected.max_trade_date is None
            and expected.max_updated_at is None
        )
    if not rows or expected.max_trade_date is None or expected.max_updated_at is None:
        return False
    return (
        rows[-1].trade_date == expected.max_trade_date
        and max(row.updated_at for row in rows) == expected.max_updated_at
    )


def _build_bar_dto(row: ComputedTrendChannelRow) -> TrendChannelBarDto:
    return TrendChannelBarDto(
        trade_date=row.trade_date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        short_channel=TrendChannelBandDto(
            upper=row.short_channel.upper,
            lower=row.short_channel.lower,
            position=row.short_channel.position,
            state=row.short_channel.state,
        ),
        long_channel=TrendChannelBandDto(
            upper=row.long_channel.upper,
            lower=row.long_channel.lower,
            position=row.long_channel.position,
            state=row.long_channel.state,
        ),
        combined_state=row.combined_state,
    )
