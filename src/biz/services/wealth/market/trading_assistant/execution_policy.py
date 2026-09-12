"""Versioned engineering budgets from design §§4.8.4, 4.29, 4.36.

Not user settings or environment overrides. App supplies one immutable instance.
"""

from dataclasses import dataclass
from time import monotonic
from typing import Callable


@dataclass(frozen=True, slots=True)
class TradingAssistantExecutionPolicyV1:
    local_concurrency: int = 1
    idle_poll_seconds: int = 1
    page_rows: int = 500
    page_bytes: int = 1048576
    batch_budget_ms: int = 2000
    sql_timeout_ms: int = 1000
    lock_timeout_ms: int = 100
    lease_seconds: int = 15
    shutdown_grace_seconds: int = 5
    transient_retry_delays_seconds: tuple[int, ...] = (2, 4, 8, 16, 30)
    data_probe_seconds: int = 60
    read_request_budget_ms: int = 5000
    write_request_budget_ms: int = 10000
    max_validation_rebases: int = 1

    def __post_init__(self):
        positive = (self.idle_poll_seconds, self.page_rows, self.page_bytes,
                    self.batch_budget_ms, self.sql_timeout_ms, self.lock_timeout_ms,
                    self.lease_seconds, self.shutdown_grace_seconds, self.data_probe_seconds,
                    self.read_request_budget_ms, self.write_request_budget_ms)
        if any(type(v) is not int or v <= 0 for v in positive):
            raise ValueError("Execution budgets must be positive integers")
        if type(self.local_concurrency) is not int or self.local_concurrency != 1:
            raise ValueError("Exactly one local execution slot is supported")
        if type(self.max_validation_rebases) is not int or self.max_validation_rebases != 1:
            raise ValueError("Only one validation rebase is supported")
        if not (self.lock_timeout_ms < self.sql_timeout_ms <= self.batch_budget_ms
                < self.read_request_budget_ms < self.write_request_budget_ms
                < self.lease_seconds * 1000):
            raise ValueError("Inconsistent deadline hierarchy")
        if not self.batch_budget_ms < self.shutdown_grace_seconds * 1000 < self.lease_seconds * 1000:
            raise ValueError("Inconsistent shutdown grace")
        if (not isinstance(self.transient_retry_delays_seconds, tuple)
                or len(self.transient_retry_delays_seconds) != 5
                or any(type(v) is not int or v <= 0 for v in self.transient_retry_delays_seconds)
                or tuple(sorted(set(self.transient_retry_delays_seconds)))
                != self.transient_retry_delays_seconds):
            raise ValueError("Expected five increasing retry delays")


@dataclass(frozen=True, slots=True)
class TradingAssistantPayloadBudgetV1:
    """Measurement targets, deliberately not request rejection thresholds."""
    small_payload_target_bytes: int = 65536
    aggregate_payload_target_bytes: int = 5242880

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in (
            self.small_payload_target_bytes, self.aggregate_payload_target_bytes
        )) or self.small_payload_target_bytes > self.aggregate_payload_target_bytes:
            raise ValueError("Invalid payload measurement targets")


class DeadlineExceeded(TimeoutError):
    """An execution deadline, not proof that a save was rolled back."""


@dataclass(frozen=True, slots=True)
class Deadline:
    expires_at: float
    clock: Callable[[], float]

    @classmethod
    def after_ms(cls, budget_ms: int, clock: Callable[[], float] = monotonic):
        if type(budget_ms) is not int or budget_ms <= 0:
            raise ValueError("Invalid deadline budget")
        return cls(clock() + budget_ms / 1000, clock)

    def remaining_ms(self) -> int:
        remaining = int((self.expires_at - self.clock()) * 1000)
        if remaining <= 0:
            raise DeadlineExceeded("Execution deadline exceeded")
        return remaining

    def bounded_ms(self, maximum: int) -> int:
        if type(maximum) is not int or maximum <= 0:
            raise ValueError("Invalid child budget")
        return min(maximum, self.remaining_ms())
