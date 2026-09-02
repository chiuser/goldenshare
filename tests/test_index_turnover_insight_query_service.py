from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
)
from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calculator import (
    IndexTurnoverInsightCalculator,
)
from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calendar_query import (
    IndexTurnoverInsightCalendarDay,
)
from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_query_service import (
    IndexTurnoverInsightQueryService,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_exception_builder import (
    IndexTurnoverInsightExceptionBuilder,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_status_resolver import (
    IndexTurnoverInsightStatusResolver,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_universe import (
    INDEX_TURNOVER_INSIGHT_UNIVERSE,
)
from src.foundation.clients.local_lake.major_index_turnover_reader import (
    MajorIndexTurnoverMinuteRow,
    MajorIndexTurnoverReadIssue,
    MajorIndexTurnoverReadResult,
)


EXPECTED = date(2026, 9, 1)
PREVIOUS = date(2026, 8, 31)


def _dates(count: int = 21) -> tuple[date, ...]:
    return tuple(EXPECTED - timedelta(days=index) for index in range(count))


def _times(trade_date: date) -> tuple[datetime, ...]:
    morning = datetime.combine(trade_date, time(9, 30))
    afternoon = datetime.combine(trade_date, time(13, 1))
    return tuple(morning + timedelta(minutes=index) for index in range(121)) + tuple(
        afternoon + timedelta(minutes=index) for index in range(120)
    )


def _rows(trade_dates: tuple[date, ...]) -> tuple[MajorIndexTurnoverMinuteRow, ...]:
    return tuple(
        MajorIndexTurnoverMinuteRow(
            ts_code=identity.ts_code,
            trade_date=trade_date,
            trade_time=trade_time,
            amount_yuan=Decimal("100000000"),
        )
        for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
        for trade_date in trade_dates
        for trade_time in _times(trade_date)
    )


def _candidates(trade_dates: tuple[date, ...]) -> tuple[IndexTurnoverInsightCalendarDay, ...]:
    return tuple(
        IndexTurnoverInsightCalendarDay(
            trade_date=trade_date,
            previous_trade_date=(
                trade_dates[index + 1] if index + 1 < len(trade_dates) else None
            ),
        )
        for index, trade_date in enumerate(trade_dates)
    )


def _context() -> MarketPageContext:
    return MarketPageContext(
        market="CN_A",
        trade_date=EXPECTED,
        prev_trade_date=PREVIOUS,
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 9, 2, 8, 0),
        source="explicit",
    )


def _service(result: MajorIndexTurnoverReadResult, trade_dates: tuple[date, ...]):
    context_query = Mock()
    context_query.resolve_context.return_value = _context()
    calendar_query = Mock()
    calendar_query.load_candidates.return_value = _candidates(trade_dates)
    reader = Mock()
    reader.read.return_value = result
    service = IndexTurnoverInsightQueryService(
        context_query=context_query,
        calendar_query=calendar_query,
        reader=reader,
        calculator=IndexTurnoverInsightCalculator(),
        status_resolver=IndexTurnoverInsightStatusResolver(),
        exception_builder=IndexTurnoverInsightExceptionBuilder(),
    )
    return service, reader


def _result(
    *,
    trade_dates: tuple[date, ...],
    rows: tuple[MajorIndexTurnoverMinuteRow, ...] | None = None,
    issues: tuple[MajorIndexTurnoverReadIssue, ...] = (),
    missing: tuple[date, ...] = (),
) -> MajorIndexTurnoverReadResult:
    available = tuple(day for day in trade_dates if day not in set(missing))
    actual_rows = rows if rows is not None else _rows(available)
    return MajorIndexTurnoverReadResult(
        rows=actual_rows,
        available_trade_dates=available,
        missing_trade_dates=missing,
        issues=issues,
        scanned_file_count=len(available),
        scanned_row_count=len(actual_rows),
        elapsed_ms=12,
    )


def test_service_reads_once_and_returns_fixed_ready_ten_panel_order() -> None:
    trade_dates = _dates()
    service, reader = _service(_result(trade_dates=trade_dates), trade_dates)

    response = service.build_index_turnover_insight(
        Mock(), market="CN_A", trade_date=EXPECTED, debug=True
    )

    assert response.status == "READY"
    assert response.asOf == "盘后数据 · 2026-09-01"
    assert [(item.tsCode, item.indexName) for item in response.indices] == [
        (identity.ts_code, identity.index_name)
        for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
    ]
    assert all(item.status == "READY" and len(item.series) == 241 for item in response.indices)
    assert response.indices[0].summary.current.amountYi == 241
    assert response.debugInfo is not None
    assert response.debugInfo.scannedFileCount == 21
    reader.read.assert_called_once()
    assert len(reader.read.call_args.args[0].trade_dates) == 21


def test_service_keeps_expected_pair_and_marks_only_missing_current_card() -> None:
    trade_dates = _dates()
    rows = tuple(
        row
        for row in _rows(trade_dates)
        if not (row.ts_code == "000001.SH" and row.trade_date == EXPECTED)
    )
    issue = MajorIndexTurnoverReadIssue(
        code="ITI_SOURCE_NOT_READY",
        ts_code="000001.SH",
        trade_date=EXPECTED,
        detail="missing",
    )
    service, _reader = _service(
        _result(trade_dates=trade_dates, rows=rows, issues=(issue,)), trade_dates
    )

    response = service.build_index_turnover_insight(
        Mock(), market="CN_A", trade_date=EXPECTED, debug=False
    )

    assert response.status == "PARTIAL"
    assert response.tradingDay.observedTradeDate == EXPECTED
    assert response.indices[0].status == "EMPTY"
    assert response.indices[0].series == []
    assert all(item.status == "READY" for item in response.indices[1:])
    assert response.debugInfo is None


def test_service_falls_back_as_one_group_only_when_expected_partition_is_missing() -> None:
    trade_dates = _dates()
    result = _result(
        trade_dates=trade_dates,
        rows=_rows(trade_dates[1:]),
        missing=(EXPECTED,),
    )
    service, _reader = _service(result, trade_dates)

    response = service.build_index_turnover_insight(
        Mock(), market="CN_A", trade_date=EXPECTED, debug=True
    )

    assert response.status == "DELAYED"
    assert response.tradingDay.observedTradeDate == PREVIOUS
    assert response.tradingDay.previousObservedTradeDate == trade_dates[2]
    assert all(item.status == "READY" for item in response.indices)
    assert response.exceptionCode == "ITI_SOURCE_DELAYED"
    assert response.debugInfo is not None
    assert any(
        exception.code == "ITI_SOURCE_DELAYED"
        for exception in response.debugInfo.exceptions
    )


def test_service_maps_unclassified_response_build_failure_to_query_failed() -> None:
    trade_dates = _dates()
    service, _reader = _service(_result(trade_dates=trade_dates), trade_dates)
    service._calculator = Mock()  # noqa: SLF001
    service._calculator.calculate.side_effect = RuntimeError("unexpected")
    service._calculator.build_panel_dto = IndexTurnoverInsightCalculator().build_panel_dto

    response = service.build_index_turnover_insight(
        Mock(), market="CN_A", trade_date=EXPECTED, debug=True
    )

    assert response.status == "ERROR"
    assert response.exceptionCode == "ITI_QUERY_FAILED"
    assert len(response.indices) == 10
    assert all(item.status == "ERROR" for item in response.indices)
    assert response.debugInfo is not None
    assert response.debugInfo.exceptions[0].code == "ITI_QUERY_FAILED"
