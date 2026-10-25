"""Code-owned trial limits, as agreed in the next-stage LLD 14.3.1."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DailyWaveReviewSpec:
    ts_code: str = "000001.SH"
    period: str = "day"
    rule_id: str = "xxm-daily-wave-review-v0.1"
    schema_version: int = 1
    requested_start: str = "2023-10-24"
    requested_end: str = "2026-10-21"
    absolute_start: str = "2021-10-01"
    context_batch_points: int = 250
    max_context_points: int = 500
    max_main_points: int = 800
    max_total_points: int = 1300
    max_input_bytes: int = 1024 * 1024
    max_calendar_days: int = 2000
    source_equation_tolerance: Decimal = Decimal("0.0021")
    calculation_seconds: float = 8.0
    max_memory_bytes: int = 256 * 1024 * 1024
    max_response_bytes: int = 2 * 1024 * 1024
    connection_seconds: float = 2.0
    query_seconds: float = 3.0
    lock_seconds: float = 1.0
    frontend_seconds: float = 10.0


DEFAULT_SPEC = DailyWaveReviewSpec()
