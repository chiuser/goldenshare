"""Design §7.11: internal immutable IO policy, separate from computation."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TradingAssistantNotificationPolicyV1:
    max_inflight_per_process: int = 1
    total_timeout_ms: int = 10000
    connect_timeout_ms: int = 3000
    read_timeout_ms: int = 5000
    pool_timeout_ms: int = 1000
    min_robot_interval_ms: int = 1000
    automatic_retry_count: int = 0

    def __post_init__(self):
        if (type(self.max_inflight_per_process) is not int or type(self.automatic_retry_count) is not int
                or self.max_inflight_per_process != 1 or self.automatic_retry_count != 0
                or any(type(v) is not int or v <= 0 for v in (self.total_timeout_ms,
                    self.connect_timeout_ms, self.read_timeout_ms, self.pool_timeout_ms, self.min_robot_interval_ms))
                or max(self.connect_timeout_ms, self.read_timeout_ms, self.pool_timeout_ms) > self.total_timeout_ms):
            raise ValueError("Invalid notification execution policy")
