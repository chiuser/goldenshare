from dataclasses import dataclass
import math
from typing import Callable

from .forecast_spec import FORECAST_SPEC
from .types import XxmBar


class ProjectionPrecisionError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ProjectionState:
    e12: float
    e26: float
    dea: float

    def advance(self, close: float) -> tuple["ProjectionState", tuple[float, float, float]]:
        e12 = self.e12 * 11 / 13 + close * 2 / 13
        e26 = self.e26 * 25 / 27 + close * 2 / 27
        dif = e12 - e26
        dea = .8 * self.dea + .2 * dif
        return ProjectionState(e12, e26, dea), (dif, dea, 2 * (dif - dea))

    def project(self, close: float, stamp: str, period: str, *, guard: bool = True):
        state, values = self.advance(close)
        if period == "day":
            # DEA rounding cannot change detector decisions or internal EMA state.
            if guard and any(near_rounding_tie(values[i]) for i in (0, 2)):
                raise ProjectionPrecisionError("ROUNDING_BOUNDARY")
            values = tuple(round(v, 3) for v in values)
        return XxmBar(stamp, close, *values), state


def near_rounding_tie(value: float) -> bool:
    half = (math.floor(value * 1000) + .5) / 1000
    return abs(value - half) <= FORECAST_SPEC.daily_rounding_guard


def recover_projection(bars: tuple[XxmBar, ...], period: str, check: Callable[[], object]) -> ProjectionState:
    tail = FORECAST_SPEC.calibration_tail_bars
    if len(bars) < tail:
        raise ProjectionPrecisionError("CALIBRATION_FAILED")
    state = ProjectionState(bars[0].close, bars[0].close, 0.)
    tolerance = FORECAST_SPEC.daily_calibration_abs_tol if period == "day" else FORECAST_SPEC.minute_calibration_abs_tol
    for i, bar in enumerate(bars):
        if i % 1000 == 0:
            check()
        state, values = state.advance(bar.close)
        if i >= len(bars) - tail:
            if any(abs(actual - source) > tolerance for actual, source in zip(values, (bar.dif, bar.dea, bar.hist))):
                raise ProjectionPrecisionError("CALIBRATION_FAILED")
            if period == "day" and any(abs(v * 1000 - round(v * 1000)) > 1e-8 for v in (bar.dif, bar.dea, bar.hist)):
                raise ProjectionPrecisionError("CALIBRATION_FAILED")
    check()
    return state
