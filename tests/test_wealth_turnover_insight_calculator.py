from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.biz.queries.wealth.market.turnover_insight.turnover_insight_calculator import (
    TURNOVER_INSIGHT_AXIS_LABELS,
    TURNOVER_INSIGHT_MINUTE_GRID,
    TurnoverInsightCalculator,
    TurnoverInsightPointQualityError,
    TurnoverInsightTimeGridError,
)
from src.biz.queries.wealth.market.turnover_insight.turnover_insight_query import (
    TurnoverInsightSnapshotRow,
)


def _snapshot(
    *,
    trade_date: date,
    per_minute_amount: Decimal,
    points: list[dict[str, object]] | None = None,
) -> TurnoverInsightSnapshotRow:
    source_points = points or [
        {"tradeTime": label, "amount": str(per_minute_amount)}
        for label in TURNOVER_INSIGHT_MINUTE_GRID
    ]
    total = sum((Decimal(str(point["amount"])) for point in source_points), Decimal("0"))
    return TurnoverInsightSnapshotRow(
        trade_date=trade_date,
        pretrade_date=None,
        latest_trade_time=datetime.combine(trade_date, datetime.strptime("15:00", "%H:%M").time()),
        total_amount_thousand_yuan=total,
        source_row_count=len(source_points),
        security_count=5000,
        points=tuple(source_points),
        built_at=datetime(2026, 8, 22, 20, 0),
    )


def test_turnover_insight_calculator_builds_exact_241_point_contract() -> None:
    calculator = TurnoverInsightCalculator()
    current = _snapshot(trade_date=date(2026, 8, 21), per_minute_amount=Decimal("200000"))
    previous = _snapshot(trade_date=date(2026, 8, 20), per_minute_amount=Decimal("250000"))

    result = calculator.calculate_pair(current_snapshot=current, previous_snapshot=previous)

    assert len(result.series) == 241
    assert result.series[0].time == "09:30"
    assert result.series[120].time == "11:30"
    assert result.series[121].time == "13:01"
    assert result.series[-1].time == "15:00"
    assert sum(point.showAxisLabel for point in result.series) == 17
    assert "13:00" not in TURNOVER_INSIGHT_AXIS_LABELS
    assert result.summary.current.amountYi == 482
    assert result.summary.previous.amountYi == 603
    assert result.summary.delta.amountYi == -121
    assert result.summary.delta.direction == "down"


def test_turnover_insight_axis_matches_reviewed_figma_examples() -> None:
    calculator = TurnoverInsightCalculator()

    upper = calculator.build_cumulative_axis([18921, 20939])
    delta = calculator.build_delta_axis([-2018, -1000, -1])

    assert [tick.valueYi for tick in upper.ticks] == [0, 6000, 12000, 18000, 24000]
    assert [tick.displayText for tick in upper.ticks] == ["0", "6,000亿", "12,000亿", "18,000亿", "24,000亿"]
    assert [tick.valueYi for tick in delta.ticks] == [-2400, -1200, 0]
    assert [tick.valueYi for tick in calculator.build_cumulative_axis([0]).ticks] == [0, 1, 2, 3, 4]
    assert [tick.valueYi for tick in calculator.build_delta_axis([0]).ticks] == [-1, 0, 1]
    assert [tick.valueYi for tick in calculator.build_delta_axis([-2018, 845]).ticks] == [
        -2400,
        -1200,
        0,
        470,
        940,
    ]


def test_turnover_insight_uses_decimal_and_direction_before_rounding() -> None:
    calculator = TurnoverInsightCalculator()
    current = _snapshot(trade_date=date(2026, 8, 21), per_minute_amount=Decimal("100000.01"))
    previous = _snapshot(trade_date=date(2026, 8, 20), per_minute_amount=Decimal("100000.00"))

    result = calculator.calculate_pair(current_snapshot=current, previous_snapshot=previous)

    assert result.series[0].deltaAmountYi == 0
    assert result.series[0].deltaDirection == "up"
    assert result.summary.delta.direction == "up"


@pytest.mark.parametrize(
    "mutator,error_type",
    [
        (lambda points: points.pop(), TurnoverInsightTimeGridError),
        (lambda points: points.__setitem__(1, dict(points[0])), TurnoverInsightTimeGridError),
        (lambda points: points[0].update(amount="-1"), TurnoverInsightPointQualityError),
    ],
)
def test_turnover_insight_rejects_invalid_point_contract(mutator, error_type) -> None:
    points = [
        {"tradeTime": label, "amount": "100000"}
        for label in TURNOVER_INSIGHT_MINUTE_GRID
    ]
    mutator(points)
    snapshot = _snapshot(
        trade_date=date(2026, 8, 21),
        per_minute_amount=Decimal("100000"),
        points=points,
    )

    with pytest.raises(error_type):
        TurnoverInsightCalculator().parse_snapshot(snapshot)


def test_turnover_insight_rejects_point_sum_mismatch() -> None:
    snapshot = _snapshot(trade_date=date(2026, 8, 21), per_minute_amount=Decimal("100000"))
    mismatched = TurnoverInsightSnapshotRow(
        trade_date=snapshot.trade_date,
        pretrade_date=snapshot.pretrade_date,
        latest_trade_time=snapshot.latest_trade_time,
        total_amount_thousand_yuan=snapshot.total_amount_thousand_yuan + Decimal("0.11"),
        source_row_count=snapshot.source_row_count,
        security_count=snapshot.security_count,
        points=snapshot.points,
        built_at=snapshot.built_at,
    )

    with pytest.raises(TurnoverInsightPointQualityError):
        TurnoverInsightCalculator().parse_snapshot(mismatched)
