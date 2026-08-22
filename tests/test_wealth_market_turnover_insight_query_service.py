from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext
from src.biz.queries.wealth.market.turnover_common.turnover_daily_average_query import (
    TurnoverDailyAverageSnapshot,
)
from src.biz.queries.wealth.market.turnover_insight.turnover_insight_calculator import (
    TURNOVER_INSIGHT_MINUTE_GRID,
)
from src.biz.queries.wealth.market.turnover_insight.turnover_insight_query import (
    TurnoverInsightCandidateSet,
    TurnoverInsightSnapshotRow,
)
from src.biz.queries.wealth.market.turnover_insight.turnover_insight_query_service import (
    TurnoverInsightQueryService,
)


def _context(*, trade_date: date, previous_date: date) -> MarketPageContext:
    return MarketPageContext(
        market="CN_A",
        trade_date=trade_date,
        prev_trade_date=previous_date,
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 8, 22, 20, 0),
        source="explicit",
    )


def _snapshot(*, trade_date: date, previous_date: date | None, amount: Decimal) -> TurnoverInsightSnapshotRow:
    points = tuple({"tradeTime": label, "amount": str(amount)} for label in TURNOVER_INSIGHT_MINUTE_GRID)
    return TurnoverInsightSnapshotRow(
        trade_date=trade_date,
        pretrade_date=previous_date,
        latest_trade_time=datetime(2026, 8, 22, 15, 0),
        total_amount_thousand_yuan=amount * Decimal(len(points)),
        source_row_count=len(points),
        security_count=5000,
        points=points,
        built_at=datetime(2026, 8, 22, 20, 0),
    )


def _averages(end_trade_date: date) -> TurnoverDailyAverageSnapshot:
    return TurnoverDailyAverageSnapshot(
        end_trade_date=end_trade_date,
        avg5d_amount=Decimal("2377100000"),
        avg20d_amount=Decimal("2806400000"),
        available5d_count=5,
        available20d_count=20,
    )


def test_delayed_response_loads_averages_for_observed_date() -> None:
    expected = date(2026, 8, 21)
    observed = date(2026, 8, 20)
    previous = date(2026, 8, 19)
    service = TurnoverInsightQueryService()
    service._context_query = Mock()
    service._context_query.resolve_context.return_value = _context(
        trade_date=expected,
        previous_date=observed,
    )
    service._query = Mock()
    service._query.load_candidates.return_value = TurnoverInsightCandidateSet(
        expected_trade_date=expected,
        expected_prev_trade_date=observed,
        rows=(
            _snapshot(trade_date=observed, previous_date=previous, amount=Decimal("200000")),
            _snapshot(trade_date=previous, previous_date=date(2026, 8, 18), amount=Decimal("250000")),
        ),
    )
    service._daily_average_query = Mock()
    service._daily_average_query.load.return_value = _averages(observed)

    response = service.build_turnover_insight(
        Mock(),
        market="CN_A",
        trade_date=expected,
        debug=True,
    )

    assert response.status == "DELAYED"
    assert response.tradingDay.observedTradeDate == observed
    assert response.summary.avg5d.amountYi == 23771
    service._daily_average_query.load.assert_called_once()
    assert service._daily_average_query.load.call_args.kwargs["end_trade_date"] == observed


def test_average_query_failure_preserves_ready_minute_series() -> None:
    current = date(2026, 8, 21)
    previous = date(2026, 8, 20)
    service = TurnoverInsightQueryService()
    service._context_query = Mock()
    service._context_query.resolve_context.return_value = _context(
        trade_date=current,
        previous_date=previous,
    )
    service._query = Mock()
    service._query.load_candidates.return_value = TurnoverInsightCandidateSet(
        expected_trade_date=current,
        expected_prev_trade_date=previous,
        rows=(
            _snapshot(trade_date=current, previous_date=previous, amount=Decimal("200000")),
            _snapshot(trade_date=previous, previous_date=date(2026, 8, 19), amount=Decimal("250000")),
        ),
    )
    service._daily_average_query = Mock()
    service._daily_average_query.load.side_effect = RuntimeError("bounded average query failed")

    response = service.build_turnover_insight(
        Mock(),
        market="CN_A",
        trade_date=current,
        debug=True,
    )

    assert response.status == "READY"
    assert len(response.series) == 241
    assert response.summary.avg5d.amountYi is None
    assert response.summary.avg20d.amountYi is None
    assert response.debugInfo is not None
    assert [exception.code for exception in response.debugInfo.exceptions] == [
        "TI_DAILY_AVERAGE_UNAVAILABLE"
    ]
