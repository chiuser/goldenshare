from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class IndexDailyRepairSlotWindow:
    """A named automatic repair stage and its Shanghai-local availability window."""

    repair_slot: str
    start_time: time
    end_time: time


INDEX_DAILY_RECONCILIATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL = "same_day_initial"
INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING = "previous_open_day_morning"
INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON = "previous_open_day_afternoon"
INDEX_DAILY_AUTOMATIC_REPAIR_SLOTS = frozenset(
    {
        INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
        INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
        INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
    }
)
INDEX_DAILY_PREVIOUS_OPEN_DAY_REPAIR_SLOT_WINDOWS = (
    IndexDailyRepairSlotWindow(
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
        start_time=time(9, 0),
        end_time=time(12, 0),
    ),
    IndexDailyRepairSlotWindow(
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
        start_time=time(13, 30),
        end_time=time(16, 30),
    ),
)
INDEX_DAILY_SOURCE_DELAY_OPEN_DAY_LIMIT = 3
INDEX_DAILY_REPAIR_BATCH_SIZE = 100
INDEX_DAILY_REPAIR_MAX_TASK_RUNS_PER_ROUND = 20
INDEX_DAILY_ACTIVATION_REQUIRED_OPEN_DAYS = 3
INDEX_DAILY_GAP_REPAIR_RUN_SCOPE = "index_daily_gap_repair"


def previous_open_day_repair_slot_for_time(local_time: time) -> str | None:
    for window in INDEX_DAILY_PREVIOUS_OPEN_DAY_REPAIR_SLOT_WINDOWS:
        if window.start_time <= local_time <= window.end_time:
            return window.repair_slot
    return None


def is_allowed_index_daily_repair_target(
    *,
    target_trade_date: date,
    current_trade_date: date,
    previous_open_trade_date: date | None,
) -> bool:
    return target_trade_date == current_trade_date or target_trade_date == previous_open_trade_date
