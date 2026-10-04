"""Announcement execution budgets; shared by daily and history helpers."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AnnouncementPolicy:
    page_size: int = 2000
    prod_fetch_rows: int = 10000
    interval_seconds: float = 5
    max_attempts: int = 3
    call_timeout: float = 30
    cancel_grace: float = 5
    max_day_requests: int = 100
    max_window_requests: int = 350
    max_window_seconds: float = 3600
    max_month_rows: int = 2000000
    month_deadline: float = 1800
    sql_timeout_ms: int = 60000
    duckdb_memory: str = "2GB"
    duckdb_threads: int = 2
    spill_limit: str = "20GB"
    min_free_reserve: int = 5 * 1024**3

    def __post_init__(self):
        if self.page_size != 2000:
            raise ValueError("announcement_page_size_contract")
        for name in (
            "prod_fetch_rows",
            "max_attempts",
            "max_day_requests",
            "max_window_requests",
            "max_month_rows",
            "sql_timeout_ms",
            "duckdb_threads",
            "min_free_reserve",
        ):
            if (
                isinstance(getattr(self, name), bool)
                or not isinstance(getattr(self, name), int)
                or getattr(self, name) <= 0
            ):
                raise ValueError(f"announcement_invalid_{name}")
        for name in (
            "interval_seconds",
            "call_timeout",
            "cancel_grace",
            "max_window_seconds",
            "month_deadline",
        ):
            value = getattr(self, name)
            if (
                not math.isfinite(value)
                or value < 0
                or (name != "interval_seconds" and value == 0)
            ):
                raise ValueError(f"announcement_invalid_{name}")
