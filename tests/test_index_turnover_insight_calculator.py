from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calculator import (
    IndexTurnoverInsightCalculator,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_universe import (
    INDEX_TURNOVER_INSIGHT_UNIVERSE,
)
from src.foundation.clients.local_lake.major_index_turnover_reader import (
    MajorIndexTurnoverMinuteRow,
)


def _times(trade_date: date) -> tuple[datetime, ...]:
    morning = datetime.combine(trade_date, time(9, 30))
    afternoon = datetime.combine(trade_date, time(13, 1))
    return tuple(morning + timedelta(minutes=index) for index in range(121)) + tuple(
        afternoon + timedelta(minutes=index) for index in range(120)
    )


def _rows(days: int) -> tuple[MajorIndexTurnoverMinuteRow, ...]:
    end = date(2026, 9, 1)
    return tuple(
        MajorIndexTurnoverMinuteRow(
            ts_code="000001.SH",
            trade_date=trade_date,
            trade_time=trade_time,
            amount_yuan=Decimal("100000000"),
        )
        for offset in range(days)
        for trade_date in (end - timedelta(days=offset),)
        for trade_time in _times(trade_date)
    )


def test_index_calculator_uses_gold_amount_as_yuan_and_requires_exact_windows() -> None:
    calculator = IndexTurnoverInsightCalculator()
    complete = calculator.calculate(
        ts_code="000001.SH",
        rows=_rows(20),
        observed_trade_date=date(2026, 9, 1),
        previous_observed_trade_date=date(2026, 8, 31),
    )
    incomplete = calculator.calculate(
        ts_code="000001.SH",
        rows=_rows(4),
        observed_trade_date=date(2026, 9, 1),
        previous_observed_trade_date=date(2026, 8, 31),
    )

    assert complete.panel is not None
    assert complete.panel.summary.current.amount_yi == 241
    assert complete.panel.summary.avg5d.amount_yi == 241
    assert complete.panel.summary.avg20d.amount_yi == 241
    assert complete.averages_complete is True
    assert incomplete.panel is not None
    assert incomplete.panel.summary.avg5d.amount_yi is None
    assert incomplete.panel.summary.avg20d.amount_yi is None
    assert incomplete.averages_complete is False


def test_index_calculator_builds_fixed_identity_panel_without_inheriting_total_dto() -> None:
    calculator = IndexTurnoverInsightCalculator()
    calculation = calculator.calculate(
        ts_code="000001.SH",
        rows=_rows(20),
        observed_trade_date=date(2026, 9, 1),
        previous_observed_trade_date=date(2026, 8, 31),
    )
    panel = calculator.build_panel_dto(
        identity=INDEX_TURNOVER_INSIGHT_UNIVERSE[0],
        calculation=calculation,
        status="READY",
        message=None,
        exception_code=None,
    )

    assert panel.tsCode == "000001.SH"
    assert panel.indexName == "上证指数"
    assert len(panel.series) == 241
    assert panel.model_dump(by_alias=True)["summary"]["current"]["amountYi"] == 241
