"""Confirmed swing and provisional forming-leg construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .bars import CanonicalBar
from .identities import stable_hash
from .pivot import DetectorState, PivotConfirmation, PivotDetectionResult, PivotType


class Direction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


@dataclass(frozen=True, slots=True)
class ConfirmedSwing:
    swing_key: str
    from_pivot_key: str
    to_pivot_key: str
    direction: Direction
    start_at: datetime
    end_at: datetime
    available_at: datetime
    start_price: Decimal
    end_price: Decimal
    absolute_change: Decimal
    return_ratio: Decimal
    duration_bars: int
    confirmation_delay_bars: int


@dataclass(frozen=True, slots=True)
class FormingLeg:
    from_pivot_key: str
    direction: Direction
    forming_extreme_at: datetime
    forming_extreme_price: Decimal
    visible_at: datetime
    threshold_remaining: Decimal
    uses_provisional: bool = True


def build_confirmed_swings(
    confirmations: tuple[PivotConfirmation, ...],
    bars: tuple[CanonicalBar, ...],
) -> tuple[ConfirmedSwing, ...]:
    bar_index = {bar.bar_key: index for index, bar in enumerate(bars)}
    swings: list[ConfirmedSwing] = []
    for start, end in zip(confirmations, confirmations[1:]):
        try:
            start_index = bar_index[start.extreme_bar_key]
            end_index = bar_index[end.extreme_bar_key]
            confirmation_index = bar_index[end.confirmation_bar_key]
        except KeyError as exc:
            raise ValueError(
                "pivot references a bar outside the canonical prefix"
            ) from exc
        if start.pivot_type is PivotType.LOW and end.pivot_type is PivotType.HIGH:
            direction = Direction.UP
            if end.extreme_price <= start.extreme_price:
                raise ValueError(
                    "UP swing must end above its start: "
                    f"{start.extreme_at.isoformat()}={start.extreme_price} -> "
                    f"{end.extreme_at.isoformat()}={end.extreme_price}"
                )
        elif start.pivot_type is PivotType.HIGH and end.pivot_type is PivotType.LOW:
            direction = Direction.DOWN
            if end.extreme_price >= start.extreme_price:
                raise ValueError(
                    "DOWN swing must end below its start: "
                    f"{start.extreme_at.isoformat()}={start.extreme_price} -> "
                    f"{end.extreme_at.isoformat()}={end.extreme_price}"
                )
        else:
            raise ValueError("adjacent confirmed pivots must alternate")
        if end_index <= start_index or confirmation_index < end_index:
            raise ValueError("pivot bar indices violate swing chronology")
        swings.append(
            ConfirmedSwing(
                swing_key=stable_hash("swing/v1", start.pivot_key, end.pivot_key),
                from_pivot_key=start.pivot_key,
                to_pivot_key=end.pivot_key,
                direction=direction,
                start_at=start.extreme_at,
                end_at=end.extreme_at,
                available_at=end.confirmed_at,
                start_price=start.extreme_price,
                end_price=end.extreme_price,
                absolute_change=end.extreme_price - start.extreme_price,
                return_ratio=end.extreme_price / start.extreme_price - Decimal(1),
                duration_bars=end_index - start_index,
                confirmation_delay_bars=confirmation_index - end_index,
            )
        )
    return tuple(swings)


def build_forming_leg(
    detection: PivotDetectionResult,
    bars: tuple[CanonicalBar, ...],
) -> FormingLeg | None:
    if not detection.confirmations or not bars:
        return None
    candidate = detection.forming_candidate
    if candidate is None:
        return None
    last_pivot = detection.confirmations[-1]
    current_close = bars[-1].close
    if detection.state is DetectorState.UP:
        if last_pivot.pivot_type is not PivotType.LOW:
            raise AssertionError("UP state must follow a confirmed LOW")
        direction = Direction.UP
        reversal_so_far = candidate.extreme_price - current_close
    elif detection.state is DetectorState.DOWN:
        if last_pivot.pivot_type is not PivotType.HIGH:
            raise AssertionError("DOWN state must follow a confirmed HIGH")
        direction = Direction.DOWN
        reversal_so_far = current_close - candidate.extreme_price
    else:
        return None
    remaining = max(Decimal(0), candidate.threshold_at_extreme - reversal_so_far)
    return FormingLeg(
        from_pivot_key=last_pivot.pivot_key,
        direction=direction,
        forming_extreme_at=candidate.extreme_at,
        forming_extreme_price=candidate.extreme_price,
        visible_at=bars[-1].bar_end_at,
        threshold_remaining=remaining,
    )
