from __future__ import annotations

from datetime import date, timedelta

import pytest

from qtf.engine.ranking import percentile_flags, percentile_ranks
from qtf.engine.robust_stats import (
    MAD_NORMALIZATION,
    RobustZIssueCode,
    bounded_weighted_state,
    ewma,
    linear_slope,
    robust_z,
    upward_change_share,
)
from qtf.engine.time_frontier import as_of_prefix, trailing_window_before, validate_trade_dates
from qtf.modules.sector.signal_engine import evaluate_turn_hot


def test_robust_z_uses_mad_normalization_clips_and_reports_invalid_history() -> None:
    result = robust_z(6.0, [1.0, 2.0, 3.0, 4.0, 5.0], required_count=5, clip=10.0)
    clipped = robust_z(100.0, [1.0, 2.0, 3.0, 4.0, 5.0], required_count=5, clip=3.0)
    short = robust_z(6.0, [1.0, 2.0], required_count=5, clip=3.0)
    zero_mad = robust_z(2.0, [1.0] * 5, required_count=5, clip=3.0)

    assert result.value == pytest.approx(3.0 / MAD_NORMALIZATION)
    assert clipped.value == 3.0
    assert short.issue_code is RobustZIssueCode.INSUFFICIENT_HISTORY
    assert zero_mad.issue_code is RobustZIssueCode.ZERO_MAD
    assert zero_mad.value is None


def test_state_ewma_and_trend_formulas_match_the_frozen_contract() -> None:
    state = bounded_weighted_state(
        1.0,
        -0.5,
        price_weight=0.5,
        amount_weight=0.5,
        z_clip=3.0,
    )
    smoothed = ewma(80.0, 50.0, weight=0.30)

    assert state == pytest.approx(54.1666666667)
    assert ewma(80.0, None, weight=0.30) == 80.0
    assert smoothed == 59.0
    assert linear_slope([10.0, 20.0, 30.0]) == 10.0
    assert upward_change_share([10.0, 20.0, 15.0, 30.0]) == pytest.approx(2 / 3)


def test_percentile_ranking_uses_average_ties_and_explicit_threshold() -> None:
    ranks = percentile_ranks({"d": 4.0, "c": 2.0, "a": 1.0, "b": 2.0})

    assert ranks == {"a": 0.0, "b": 50.0, "c": 50.0, "d": 100.0}
    assert percentile_flags(ranks, threshold=80.0) == {
        "a": False,
        "b": False,
        "c": False,
        "d": True,
    }

    code_ordered = percentile_ranks({"z": 1.0, "a": 2.0})
    assert tuple(code_ordered) == ("a", "z")
    assert code_ordered == {"a": 100.0, "z": 0.0}


def test_time_frontier_windows_exclude_current_and_future_dates() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(6))

    assert validate_trade_dates(dates) == dates
    assert trailing_window_before(dates, 4, 3) == dates[1:4]
    assert dates[4] not in trailing_window_before(dates, 4, 3)
    assert as_of_prefix(dates, dates[3]) == dates[:4]
    with pytest.raises(ValueError, match="strictly increasing"):
        validate_trade_dates((dates[0], dates[0]))


def test_turn_hot_requires_crossing_trend_up_share_and_armed_then_resets() -> None:
    crossing = evaluate_turn_hot(
        [50.0, 55.0, 60.0, 68.0, 71.0],
        armed=True,
        signal_threshold=70.0,
        reset_threshold=60.0,
        up_move_share_min=0.60,
    )
    unarmed = evaluate_turn_hot(
        [50.0, 55.0, 60.0, 68.0, 71.0],
        armed=False,
        signal_threshold=70.0,
        reset_threshold=60.0,
        up_move_share_min=0.60,
    )
    reset = evaluate_turn_hot(
        [70.0, 68.0, 64.0, 61.0, 59.0],
        armed=False,
        signal_threshold=70.0,
        reset_threshold=60.0,
        up_move_share_min=0.60,
    )

    assert crossing.signal is True
    assert crossing.armed_after is False
    assert unarmed.signal is False
    assert reset.signal is False
    assert reset.armed_after is True
