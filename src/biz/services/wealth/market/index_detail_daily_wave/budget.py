"""One monotonic deadline for reading, calculating and releasing resources."""
from collections.abc import Callable
import math
import time

from .spec import DEFAULT_SPEC, DailyWaveReviewSpec


class DailyWaveInputError(ValueError):
    """Invalid completed daily input."""


class DailyWaveSourceInputError(DailyWaveInputError):
    """Invalid source indicator relation, distinguished from output contract bugs."""


class DailyWaveBudgetExceeded(RuntimeError):
    """No partial result is returned when a limit is exceeded."""


class DailyWaveCancelled(RuntimeError):
    """The caller has observed cancellation."""


class DailyWaveBudget:
    def __init__(self, spec: DailyWaveReviewSpec = DEFAULT_SPEC,
                 deadline: float | None = None,
                 check_cancelled: Callable[[], bool] | None = None):
        if deadline is not None and (isinstance(deadline, bool)
                                     or not isinstance(deadline, (int, float))
                                     or not math.isfinite(deadline)):
            raise DailyWaveInputError("deadline必须为有限单调时刻")
        self.spec = spec
        self.deadline = min(time.monotonic() + spec.calculation_seconds,
                            deadline if deadline is not None else math.inf)
        self.check_cancelled = check_cancelled

    @property
    def read_deadline(self) -> float:
        return self.deadline - self.spec.cleanup_seconds

    def check(self) -> None:
        if self.check_cancelled is not None and self.check_cancelled():
            raise DailyWaveCancelled("本次日线计算已取消")
        if time.monotonic() >= self.deadline:
            raise DailyWaveBudgetExceeded("本次日线处理超过时间上限")

    def remaining_ms(self) -> int:
        self.check()
        return math.floor((self.read_deadline - time.monotonic()) * 1000)
