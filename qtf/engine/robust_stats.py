from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


MAD_NORMALIZATION = 1.4826


class RobustZIssueCode(StrEnum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    ZERO_MAD = "ZERO_MAD"


@dataclass(frozen=True, slots=True)
class RobustZResult:
    value: float | None
    median: float | None
    mad: float | None
    issue_code: RobustZIssueCode | None

    @property
    def valid(self) -> bool:
        return self.issue_code is None


def median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median requires at least one value")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("median requires finite values")
    return float(statistics.median(values))


def robust_z(
    value: float,
    history: Sequence[float],
    *,
    required_count: int,
    clip: float,
) -> RobustZResult:
    if required_count <= 0:
        raise ValueError("required_count must be positive")
    if not math.isfinite(clip) or clip <= 0:
        raise ValueError("clip must be finite and positive")
    if len(history) != required_count:
        return RobustZResult(None, None, None, RobustZIssueCode.INSUFFICIENT_HISTORY)
    if not math.isfinite(value) or any(not math.isfinite(item) for item in history):
        return RobustZResult(None, None, None, RobustZIssueCode.NON_FINITE_VALUE)
    center = median(history)
    mad = median([abs(item - center) for item in history])
    if mad == 0:
        return RobustZResult(None, center, mad, RobustZIssueCode.ZERO_MAD)
    score = (value - center) / (MAD_NORMALIZATION * mad)
    return RobustZResult(max(-clip, min(clip, score)), center, mad, None)


def bounded_weighted_state(
    price_z: float,
    amount_z: float,
    *,
    price_weight: float,
    amount_weight: float,
    z_clip: float,
) -> float:
    if not all(math.isfinite(value) for value in (price_z, amount_z, price_weight, amount_weight, z_clip)):
        raise ValueError("state inputs must be finite")
    if z_clip <= 0:
        raise ValueError("z_clip must be positive")
    composite = price_weight * price_z + amount_weight * amount_z
    return max(0.0, min(100.0, 50.0 + composite / z_clip * 50.0))


def ewma(current: float, previous: float | None, *, weight: float) -> float:
    if not math.isfinite(current) or (previous is not None and not math.isfinite(previous)):
        raise ValueError("EWMA inputs must be finite")
    if not math.isfinite(weight) or weight <= 0 or weight > 1:
        raise ValueError("EWMA weight must be in (0, 1]")
    if previous is None:
        return current
    return weight * current + (1.0 - weight) * previous


def linear_slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        raise ValueError("linear slope requires at least two values")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("linear slope requires finite values")
    x_mean = (len(values) - 1) / 2.0
    y_mean = sum(values) / len(values)
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    if denominator == 0:
        raise ValueError("linear slope denominator is zero")
    return numerator / denominator


def upward_change_share(values: Sequence[float]) -> float:
    if len(values) < 2:
        raise ValueError("upward change share requires at least two values")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("upward change share requires finite values")
    changes = zip(values, values[1:])
    return sum(1 for left, right in changes if right > left) / (len(values) - 1)
