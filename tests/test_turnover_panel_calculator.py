from __future__ import annotations

from decimal import Decimal

from src.biz.queries.wealth.market.turnover_common.turnover_panel_calculator import (
    TURNOVER_PANEL_MINUTE_GRID,
    TurnoverPanelAverageInput,
    TurnoverPanelCalculator,
    TurnoverPanelMinuteInput,
)


def _points(amount_yuan: str) -> tuple[TurnoverPanelMinuteInput, ...]:
    return tuple(
        TurnoverPanelMinuteInput(time=label, amount_yuan=Decimal(amount_yuan))
        for label in TURNOVER_PANEL_MINUTE_GRID
    )


def test_common_calculator_uses_yuan_and_exact_delta_before_rounding() -> None:
    result = TurnoverPanelCalculator().calculate(
        current=_points("100000000.01"),
        previous=_points("100000000.00"),
        averages=TurnoverPanelAverageInput(
            avg5d_yuan=Decimal("2377100000000"),
            avg20d_yuan=Decimal("2806400000000"),
            available5d_count=5,
            available20d_count=20,
        ),
    )

    assert len(result.series) == 241
    assert result.series[0].delta_amount_yi == 0
    assert result.series[0].delta_direction == "up"
    assert result.summary.current.amount_yi == 241
    assert result.summary.avg5d.amount_yi == 23771
    assert [tick.value_yi for tick in result.upper_axis.ticks] == [
        0,
        8000,
        16000,
        24000,
        32000,
    ]


def test_common_calculator_supports_current_only_and_signed_delta_axis() -> None:
    calculator = TurnoverPanelCalculator()
    current_only = calculator.calculate(
        current=_points("100000000"), previous=None, averages=None
    )
    signed = calculator.calculate(
        current=_points("50000000"),
        previous=_points("100000000"),
        averages=None,
    )

    assert current_only.delta_axis is None
    assert all(point.previous_amount_yi is None for point in current_only.series)
    assert signed.delta_axis is not None
    assert signed.delta_axis.min_yi < 0
    assert signed.delta_axis.zero_yi == 0
    assert signed.upper_axis.min_yi == 0
