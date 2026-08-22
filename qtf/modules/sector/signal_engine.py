from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from qtf.engine.robust_stats import linear_slope, upward_change_share


@dataclass(frozen=True, slots=True)
class TurnHotEvaluation:
    signal: bool
    slope: float
    upward_share: float
    armed_after: bool


def evaluate_turn_hot(
    states: Sequence[float],
    *,
    armed: bool,
    signal_threshold: float,
    reset_threshold: float,
    up_move_share_min: float,
) -> TurnHotEvaluation:
    if len(states) < 2:
        raise ValueError("turn-hot evaluation requires at least two states")
    slope = linear_slope(states)
    upward_share = upward_change_share(states)
    current = states[-1]
    previous = states[-2]
    signal = (
        armed
        and previous < signal_threshold <= current
        and slope > 0
        and upward_share >= up_move_share_min
    )
    armed_after = False if signal else armed
    if current < reset_threshold:
        armed_after = True
    return TurnHotEvaluation(
        signal=signal,
        slope=slope,
        upward_share=upward_share,
        armed_after=armed_after,
    )
