from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class IndexDailyReconciliationWindow:
    """A local-time window in which one reconciliation target may be audited."""

    start_time: time
    end_time: time
    interval: timedelta


INDEX_DAILY_RECONCILIATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
INDEX_DAILY_CURRENT_DAY_RECONCILIATION_WINDOW = IndexDailyReconciliationWindow(
    start_time=time(17, 45),
    end_time=time(22, 30),
    interval=timedelta(minutes=30),
)
INDEX_DAILY_PREVIOUS_OPEN_DAY_RECONCILIATION_WINDOW = IndexDailyReconciliationWindow(
    start_time=time(9, 0),
    end_time=time(16, 30),
    interval=timedelta(minutes=30),
)
INDEX_DAILY_SOURCE_DELAY_OPEN_DAY_LIMIT = 3
INDEX_DAILY_MAX_TERMINAL_REPAIR_ATTEMPTS = 3
INDEX_DAILY_REPAIR_BATCH_SIZE = 100
INDEX_DAILY_REPAIR_MAX_TASK_RUNS_PER_ROUND = 20
INDEX_DAILY_ACTIVATION_REQUIRED_OPEN_DAYS = 3
INDEX_DAILY_GAP_REPAIR_RUN_SCOPE = "index_daily_gap_repair"


def is_allowed_index_daily_repair_target(
    *,
    target_trade_date: date,
    current_trade_date: date,
    previous_open_trade_date: date | None,
) -> bool:
    return target_trade_date == current_trade_date or target_trade_date == previous_open_trade_date
