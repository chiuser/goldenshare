from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.queries.quote_trend_channel_query import (
    QuoteTrendChannelQuery,
    QuoteTrendChannelQueryError,
    TrendChannelInstrumentRow,
    TrendChannelSourceRow,
    TrendChannelWatermark,
)
from src.biz.services.quote_trend_channel_calculator import (
    TrendChannelCalculator,
    TrendChannelInvariantError,
)
from src.biz.services.quote_trend_channel_query_service import (
    QuoteTrendChannelQueryService,
    TrendChannelCacheKey,
    TrendChannelComputeError,
    TrendChannelInstrumentMissingError,
    TrendChannelSeries,
    TrendChannelSeriesCache,
    TrendChannelSourceChangingError,
    TrendChannelSourceInvalidError,
    TrendChannelSourceUnavailableError,
)
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


BASE_UPDATED_AT = datetime(2026, 8, 7, 17, 30, tzinfo=timezone.utc)


class _Dialect:
    name = "postgresql"


class _Bind:
    def __init__(self) -> None:
        self.dialect = _Dialect()
        self.engine = self


class _FakeSession:
    def __init__(self, bind: _Bind | None = None) -> None:
        self._bind = bind or _Bind()

    def get_bind(self) -> _Bind:
        return self._bind


class _FakeQuery:
    def __init__(
        self,
        *,
        rows: tuple[TrendChannelSourceRow, ...] = (),
        watermark: TrendChannelWatermark | None = None,
        watermark_sequence: list[TrendChannelWatermark] | None = None,
        instrument: TrendChannelInstrumentRow | None = None,
        first_watermark_barrier: threading.Barrier | None = None,
        error: QuoteTrendChannelQueryError | None = None,
    ) -> None:
        self.rows = rows
        self.watermark = watermark or _watermark_for(rows)
        self.watermark_sequence = list(watermark_sequence or [])
        self.instrument = instrument or TrendChannelInstrumentRow(
            ts_code="000001.SH",
            name="上证指数",
        )
        self.first_watermark_barrier = first_watermark_barrier
        self.error = error
        self.watermark_calls = 0
        self.load_all_rows_calls = 0
        self.load_instrument_calls = 0
        self._lock = threading.Lock()

    def load_instrument(self, session: Any) -> TrendChannelInstrumentRow | None:
        del session
        self.load_instrument_calls += 1
        if self.error is not None:
            raise self.error
        return self.instrument

    def load_watermark(self, session: Any) -> TrendChannelWatermark:
        del session
        if self.error is not None:
            raise self.error
        with self._lock:
            call_number = self.watermark_calls
            self.watermark_calls += 1
            value = (
                self.watermark_sequence.pop(0)
                if self.watermark_sequence
                else self.watermark
            )
        if self.first_watermark_barrier is not None and call_number < 2:
            self.first_watermark_barrier.wait(timeout=2)
        return value

    def load_all_rows(self, session: Any) -> tuple[TrendChannelSourceRow, ...]:
        del session
        with self._lock:
            self.load_all_rows_calls += 1
        if self.error is not None:
            raise self.error
        return self.rows


class _CountingCalculator:
    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.calls = 0
        self.delay_seconds = delay_seconds
        self.error = error
        self._delegate = TrendChannelCalculator()
        self._lock = threading.Lock()

    def calculate(
        self,
        rows: tuple[TrendChannelSourceRow, ...],
    ):
        with self._lock:
            self.calls += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return self._delegate.calculate(rows)


def _row(
    trade_date: date,
    *,
    updated_at: datetime = BASE_UPDATED_AT,
    open_value: str = "10",
    high: str = "11",
    low: str = "9",
    close: str = "10",
) -> TrendChannelSourceRow:
    return TrendChannelSourceRow(
        trade_date=trade_date,
        open=Decimal(open_value),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        updated_at=updated_at,
    )


def _watermark_for(
    rows: tuple[TrendChannelSourceRow, ...],
) -> TrendChannelWatermark:
    if not rows:
        return TrendChannelWatermark(
            row_count=0,
            max_trade_date=None,
            max_updated_at=None,
        )
    return TrendChannelWatermark(
        row_count=len(rows),
        max_trade_date=max(row.trade_date for row in rows),
        max_updated_at=max(row.updated_at for row in rows),
    )


def _service(
    query: _FakeQuery,
    *,
    calculator: _CountingCalculator | None = None,
    cache: TrendChannelSeriesCache | None = None,
) -> tuple[QuoteTrendChannelQueryService, _CountingCalculator, TrendChannelSeriesCache]:
    selected_calculator = calculator or _CountingCalculator()
    selected_cache = cache or TrendChannelSeriesCache(max_entries=2)
    return (
        QuoteTrendChannelQueryService(
            query=query,  # type: ignore[arg-type]
            calculator=selected_calculator,  # type: ignore[arg-type]
            cache=selected_cache,
        ),
        selected_calculator,
        selected_cache,
    )


def _cache_key(index: int) -> TrendChannelCacheKey:
    return TrendChannelCacheKey(
        source_identity="postgresql:test",
        ts_code="000001.SH",
        formula_version="sse-daily-trend-channel-v1",
        row_count=index,
        max_trade_date=date(2026, 1, index),
        max_updated_at=BASE_UPDATED_AT + timedelta(seconds=index),
    )


def test_real_query_reads_instrument_watermark_and_all_rows_in_ascending_order() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        IndexBasic.__table__.create(connection)
        IndexDailyServing.__table__.create(connection)

    with Session(engine) as session:
        session.add(
            IndexBasic(
                ts_code="000001.SH",
                name="上证指数",
                created_at=BASE_UPDATED_AT,
                updated_at=BASE_UPDATED_AT,
            )
        )
        for offset in (2, 0, 1):
            trade_date = date(2026, 8, 5) + timedelta(days=offset)
            session.add(
                IndexDailyServing(
                    ts_code="000001.SH",
                    trade_date=trade_date,
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10"),
                    source="api",
                    created_at=BASE_UPDATED_AT,
                    updated_at=BASE_UPDATED_AT + timedelta(seconds=offset),
                )
            )
        session.commit()

        query = QuoteTrendChannelQuery()
        instrument = query.load_instrument(session)
        watermark = query.load_watermark(session)
        rows = query.load_all_rows(session)

    assert instrument == TrendChannelInstrumentRow(
        ts_code="000001.SH",
        name="上证指数",
    )
    assert watermark.row_count == 3
    assert watermark.max_trade_date == date(2026, 8, 7)
    assert watermark.max_updated_at is not None
    assert [row.trade_date for row in rows] == [
        date(2026, 8, 5),
        date(2026, 8, 6),
        date(2026, 8, 7),
    ]


def test_real_query_normalizes_empty_watermark() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        IndexDailyServing.__table__.create(connection)

    with Session(engine) as session:
        watermark = QuoteTrendChannelQuery().load_watermark(session)

    assert watermark == TrendChannelWatermark(
        row_count=0,
        max_trade_date=None,
        max_updated_at=None,
    )


@pytest.mark.parametrize(
    "method_name",
    ["load_instrument", "load_watermark", "load_all_rows"],
)
def test_query_maps_sqlalchemy_errors(method_name: str) -> None:
    class FailingSession:
        def execute(self, statement: Any) -> None:
            del statement
            raise SQLAlchemyError("boom")

    method = getattr(QuoteTrendChannelQuery(), method_name)
    with pytest.raises(QuoteTrendChannelQueryError):
        method(FailingSession())


def test_service_loads_instrument_and_fails_closed_when_missing() -> None:
    query = _FakeQuery()
    service, _, _ = _service(query)
    session = _FakeSession()

    assert service.load_instrument(session) == query.instrument  # type: ignore[arg-type]
    query.instrument = None
    with pytest.raises(TrendChannelInstrumentMissingError):
        service.load_instrument(session)  # type: ignore[arg-type]


def test_build_response_slices_ascending_history_with_real_previous_trade_date() -> None:
    rows = (
        _row(date(2026, 8, 1)),
        _row(date(2026, 8, 5)),
        _row(date(2026, 8, 7)),
    )
    query = _FakeQuery(rows=rows)
    now = datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc)
    service = QuoteTrendChannelQueryService(
        query=query,  # type: ignore[arg-type]
        calculator=TrendChannelCalculator(),
        cache=TrendChannelSeriesCache(max_entries=2),
        now_provider=lambda: now,
    )

    response = service.build_response(  # type: ignore[arg-type]
        _FakeSession(),
        end_date=date(2026, 8, 7),
        limit=2,
    )

    assert [bar.trade_date for bar in response.bars] == [
        date(2026, 8, 5),
        date(2026, 8, 7),
    ]
    assert response.data_status.status == "READY"
    assert response.data_status.observed_trade_date == date(2026, 8, 7)
    assert response.data_status.as_of_time == now
    assert response.meta.start_date == date(2026, 8, 5)
    assert response.meta.end_date == date(2026, 8, 7)
    assert response.meta.has_more_history is True
    assert response.meta.next_end_date == date(2026, 8, 1)


def test_build_response_returns_empty_for_source_and_pre_history_window() -> None:
    empty_query = _FakeQuery(rows=())
    empty_service, _, _ = _service(empty_query)

    empty_response = empty_service.build_response(  # type: ignore[arg-type]
        _FakeSession(),
        end_date=None,
        limit=500,
    )

    assert empty_response.data_status.status == "EMPTY"
    assert empty_response.data_status.observed_trade_date is None
    assert empty_response.data_status.note == "source_has_no_daily_rows"
    assert empty_response.bars == []
    assert empty_response.meta.next_end_date is None

    rows = (_row(date(2026, 8, 5)), _row(date(2026, 8, 7)))
    history_query = _FakeQuery(rows=rows)
    history_service, _, _ = _service(history_query)
    before_history = history_service.build_response(  # type: ignore[arg-type]
        _FakeSession(),
        end_date=date(2026, 8, 1),
        limit=500,
    )

    assert before_history.data_status.status == "EMPTY"
    assert before_history.data_status.observed_trade_date == date(2026, 8, 7)
    assert before_history.data_status.note == "no_rows_on_or_before_end_date"
    assert before_history.bars == []
    assert before_history.meta.start_date is None
    assert before_history.meta.end_date is None


def test_two_entry_cache_is_lru_and_clearable() -> None:
    cache = TrendChannelSeriesCache(max_entries=2)
    keys = [_cache_key(index) for index in range(1, 5)]
    values = [
        TrendChannelSeries(
            watermark=TrendChannelWatermark(
                row_count=index,
                max_trade_date=key.max_trade_date,
                max_updated_at=key.max_updated_at,
            ),
            rows=(),
        )
        for index, key in enumerate(keys, start=1)
    ]

    cache.put(keys[0], values[0])
    cache.put(keys[1], values[1])
    assert cache.get(keys[0]) is values[0]
    cache.put(keys[2], values[2])
    assert cache.get(keys[1]) is None
    assert cache.get(keys[0]) is values[0]
    assert cache.get(keys[2]) is values[2]

    cache.put(keys[3], values[3])
    assert cache.get(keys[0]) is None
    cache.clear()
    assert cache.get(keys[2]) is None
    assert cache.get(keys[3]) is None


def test_same_watermark_uses_cached_complete_series() -> None:
    rows = (_row(date(2026, 8, 6)), _row(date(2026, 8, 7)))
    query = _FakeQuery(rows=rows)
    service, calculator, _ = _service(query)
    session = _FakeSession()

    first = service.load_series(session)  # type: ignore[arg-type]
    second = service.load_series(session)  # type: ignore[arg-type]

    assert second is first
    assert query.load_all_rows_calls == 1
    assert calculator.calls == 1


@pytest.mark.parametrize("change_kind", ["new_day", "row_count", "updated_at"])
def test_each_watermark_component_change_triggers_rebuild(change_kind: str) -> None:
    rows = (_row(date(2026, 8, 6)), _row(date(2026, 8, 7)))
    query = _FakeQuery(rows=rows)
    service, calculator, _ = _service(query)
    session = _FakeSession()
    first = service.load_series(session)  # type: ignore[arg-type]

    if change_kind == "new_day":
        query.rows = (*rows, _row(date(2026, 8, 8), updated_at=BASE_UPDATED_AT + timedelta(days=1)))
    elif change_kind == "row_count":
        query.rows = (rows[1],)
    else:
        query.rows = (
            rows[0],
            _row(date(2026, 8, 7), updated_at=BASE_UPDATED_AT + timedelta(minutes=1)),
        )
    query.watermark = _watermark_for(query.rows)

    second = service.load_series(session)  # type: ignore[arg-type]

    assert second is not first
    assert second.watermark == query.watermark
    assert query.load_all_rows_calls == 2
    assert calculator.calls == 2


def test_cache_key_includes_engine_identity() -> None:
    rows = (_row(date(2026, 8, 7)),)
    query = _FakeQuery(rows=rows)
    service, calculator, _ = _service(query)

    service.load_series(_FakeSession())  # type: ignore[arg-type]
    service.load_series(_FakeSession())  # type: ignore[arg-type]

    assert query.load_all_rows_calls == 2
    assert calculator.calls == 2


def test_concurrent_cold_requests_compute_once() -> None:
    rows = (_row(date(2026, 8, 6)), _row(date(2026, 8, 7)))
    query = _FakeQuery(
        rows=rows,
        first_watermark_barrier=threading.Barrier(2),
    )
    calculator = _CountingCalculator(delay_seconds=0.02)
    service, _, _ = _service(query, calculator=calculator)
    session = _FakeSession()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(service.load_series, session) for _ in range(2)]  # type: ignore[arg-type]
        results = [future.result(timeout=2) for future in futures]

    assert results[0] is results[1]
    assert query.load_all_rows_calls == 1
    assert calculator.calls == 1


def test_one_changed_snapshot_retries_and_publishes_only_stable_result() -> None:
    rows = (
        _row(date(2026, 8, 6)),
        _row(date(2026, 8, 7), updated_at=BASE_UPDATED_AT + timedelta(minutes=1)),
    )
    old_watermark = TrendChannelWatermark(
        row_count=1,
        max_trade_date=date(2026, 8, 6),
        max_updated_at=BASE_UPDATED_AT,
    )
    new_watermark = _watermark_for(rows)
    query = _FakeQuery(
        rows=rows,
        watermark=new_watermark,
        watermark_sequence=[
            old_watermark,
            old_watermark,
            new_watermark,
            new_watermark,
            new_watermark,
            new_watermark,
        ],
    )
    service, calculator, _ = _service(query)

    series = service.load_series(_FakeSession())  # type: ignore[arg-type]

    assert series.watermark == new_watermark
    assert query.load_all_rows_calls == 2
    assert calculator.calls == 1


def test_two_continuously_changing_snapshots_fail_without_calculation() -> None:
    rows = (_row(date(2026, 8, 7)),)
    watermark_1 = _watermark_for(rows)
    watermark_2 = TrendChannelWatermark(
        row_count=2,
        max_trade_date=date(2026, 8, 8),
        max_updated_at=BASE_UPDATED_AT + timedelta(minutes=1),
    )
    watermark_3 = TrendChannelWatermark(
        row_count=3,
        max_trade_date=date(2026, 8, 9),
        max_updated_at=BASE_UPDATED_AT + timedelta(minutes=2),
    )
    query = _FakeQuery(
        rows=rows,
        watermark=watermark_3,
        watermark_sequence=[
            watermark_1,
            watermark_1,
            watermark_2,
            watermark_2,
            watermark_2,
            watermark_3,
        ],
    )
    service, calculator, _ = _service(query)

    with pytest.raises(TrendChannelSourceChangingError):
        service.load_series(_FakeSession())  # type: ignore[arg-type]

    assert query.load_all_rows_calls == 2
    assert calculator.calls == 0


@pytest.mark.parametrize(
    ("rows", "watermark"),
    [
        (
            (_row(date(2026, 8, 7)),),
            TrendChannelWatermark(
                row_count=2,
                max_trade_date=date(2026, 8, 7),
                max_updated_at=BASE_UPDATED_AT,
            ),
        ),
        (
            (_row(date(2026, 8, 6)), _row(date(2026, 8, 7))),
            TrendChannelWatermark(
                row_count=2,
                max_trade_date=date(2026, 8, 8),
                max_updated_at=BASE_UPDATED_AT,
            ),
        ),
        (
            (_row(date(2026, 8, 6)), _row(date(2026, 8, 7))),
            TrendChannelWatermark(
                row_count=2,
                max_trade_date=date(2026, 8, 7),
                max_updated_at=BASE_UPDATED_AT + timedelta(minutes=1),
            ),
        ),
    ],
)
def test_row_count_last_date_and_updated_at_must_match_watermark(
    rows: tuple[TrendChannelSourceRow, ...],
    watermark: TrendChannelWatermark,
) -> None:
    query = _FakeQuery(rows=rows, watermark=watermark)
    service, calculator, _ = _service(query)

    with pytest.raises(TrendChannelSourceChangingError):
        service.load_series(_FakeSession())  # type: ignore[arg-type]

    assert query.load_all_rows_calls == 2
    assert calculator.calls == 0


def test_empty_source_is_cached_as_empty_series() -> None:
    query = _FakeQuery(rows=())
    service, calculator, _ = _service(query)
    session = _FakeSession()

    first = service.load_series(session)  # type: ignore[arg-type]
    second = service.load_series(session)  # type: ignore[arg-type]

    assert first is second
    assert first.rows == ()
    assert first.watermark == _watermark_for(())
    assert query.load_all_rows_calls == 1
    assert calculator.calls == 1


def test_source_row_limit_is_rejected_before_full_history_query() -> None:
    watermark = TrendChannelWatermark(
        row_count=10_001,
        max_trade_date=date(2026, 8, 7),
        max_updated_at=BASE_UPDATED_AT,
    )
    query = _FakeQuery(watermark=watermark)
    service, calculator, _ = _service(query)

    with pytest.raises(TrendChannelSourceInvalidError) as exc_info:
        service.load_series(_FakeSession())  # type: ignore[arg-type]

    assert exc_info.value.reason_code == "source_row_limit_exceeded"
    assert query.load_all_rows_calls == 0
    assert calculator.calls == 0


def test_query_and_calculator_errors_are_mapped_without_hiding_programming_errors() -> None:
    query_error = _FakeQuery(error=QuoteTrendChannelQueryError("boom"))
    service, _, _ = _service(query_error)
    with pytest.raises(TrendChannelSourceUnavailableError):
        service.load_series(_FakeSession())  # type: ignore[arg-type]

    invalid_rows = (_row(date(2026, 8, 7), open_value="8", low="9"),)
    invalid_query = _FakeQuery(rows=invalid_rows)
    invalid_service, _, _ = _service(invalid_query)
    with pytest.raises(TrendChannelSourceInvalidError) as invalid_exc:
        invalid_service.load_series(_FakeSession())  # type: ignore[arg-type]
    assert invalid_exc.value.reason_code == "invalid_ohlc_range"

    invariant_error = TrendChannelInvariantError(
        reason_code="short_channel_inverted",
        trade_date=date(2026, 8, 7),
    )
    invariant_service, _, _ = _service(
        _FakeQuery(rows=(_row(date(2026, 8, 7)),)),
        calculator=_CountingCalculator(error=invariant_error),
    )
    with pytest.raises(TrendChannelComputeError) as compute_exc:
        invariant_service.load_series(_FakeSession())  # type: ignore[arg-type]
    assert compute_exc.value.reason_code == "short_channel_inverted"

    programming_service, _, _ = _service(
        _FakeQuery(rows=(_row(date(2026, 8, 7)),)),
        calculator=_CountingCalculator(error=TypeError("programming bug")),
    )
    with pytest.raises(TypeError, match="programming bug"):
        programming_service.load_series(_FakeSession())  # type: ignore[arg-type]
