from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calendar_query import (
    IndexTurnoverInsightCalendarContractError,
    IndexTurnoverInsightCalendarDay,
    IndexTurnoverInsightCalendarQuery,
)


def test_calendar_query_uses_one_bounded_read_and_preserves_pretrade_date() -> None:
    session = Mock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(trade_date=date(2026, 9, 1), pretrade_date=date(2026, 8, 31)),
        SimpleNamespace(trade_date=date(2026, 8, 31), pretrade_date=date(2026, 8, 29)),
        SimpleNamespace(trade_date=date(2026, 8, 29), pretrade_date=date(2026, 8, 28)),
    ]

    result = IndexTurnoverInsightCalendarQuery().load_candidates(
        session,
        expected_trade_date=date(2026, 9, 1),
        limit=24,
    )

    assert result[0] == IndexTurnoverInsightCalendarDay(
        trade_date=date(2026, 9, 1), previous_trade_date=date(2026, 8, 31)
    )
    assert len(result) == 3
    session.execute.assert_called_once()


def test_calendar_query_rejects_non_adjacent_contract() -> None:
    candidates = (
        IndexTurnoverInsightCalendarDay(date(2026, 9, 1), date(2026, 8, 29)),
        IndexTurnoverInsightCalendarDay(date(2026, 8, 31), date(2026, 8, 29)),
    )

    with pytest.raises(IndexTurnoverInsightCalendarContractError):
        IndexTurnoverInsightCalendarQuery._validate(candidates)


@pytest.mark.parametrize("limit", [0, 25])
def test_calendar_query_rejects_out_of_contract_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        IndexTurnoverInsightCalendarQuery().load_candidates(
            Mock(), expected_trade_date=date(2026, 9, 1), limit=limit
        )
