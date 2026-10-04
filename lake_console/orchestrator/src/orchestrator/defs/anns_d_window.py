"""Window intent and ordered admission; no permanent announcement state."""

import hashlib
import json
import math
import time
from dataclasses import asdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementWindowBudget,
    announcement_atomic_json,
    announcement_file_lock,
)
from orchestrator.defs.anns_d_contract import (
    AnnouncementCancelled,
    AnnouncementError,
    announcement_dates,
)
from orchestrator.defs.anns_d_execution import update_announcement_day

ANNOUNCEMENT_WINDOW_TAG = "anns_d/window_id"
ANNOUNCEMENT_START_TAG = "anns_d/start_date"
ANNOUNCEMENT_END_TAG = "anns_d/end_date"
ANNOUNCEMENT_STARTED_TAG = "anns_d/started_at"
from orchestrator.defs.run_contracts.anns_d import (
    ANNOUNCEMENT_REFRESH_DAYS,
    ANNOUNCEMENT_TIMEZONE,
)


def announcement_refresh_dates(scheduled):
    if scheduled.tzinfo is None:
        raise AnnouncementError("announcement_schedule_timezone")
    today = scheduled.astimezone(ZoneInfo(ANNOUNCEMENT_TIMEZONE)).date()
    return tuple(
        (today - timedelta(days=offset)).isoformat()
        for offset in range(ANNOUNCEMENT_REFRESH_DAYS, 0, -1)
    )


def announcement_bridge_dates(enabled):
    end = enabled.astimezone(ZoneInfo(ANNOUNCEMENT_TIMEZONE)).date() - timedelta(days=1)
    if end.isoformat() < "2026-10-01":
        return ()
    return announcement_dates(
        "2026-10-01",
        end.isoformat(),
        today=enabled.astimezone(ZoneInfo(ANNOUNCEMENT_TIMEZONE)).date(),
    )


def announcement_window_tags(window_id, start, end, started_at=None):
    if not window_id or not window_id.replace("-", "").replace("_", "").isalnum():
        raise AnnouncementError("announcement_window_identity")
    announcement_dates(start, end)
    timestamp = time.time() if started_at is None else float(started_at)
    if not math.isfinite(timestamp) or timestamp <= 0 or timestamp > time.time() + 1:
        raise AnnouncementError("announcement_window_start_time")
    return {
        ANNOUNCEMENT_WINDOW_TAG: window_id,
        ANNOUNCEMENT_START_TAG: start,
        ANNOUNCEMENT_END_TAG: end,
        ANNOUNCEMENT_STARTED_TAG: str(timestamp),
    }


def announcement_day_run_id(window_id, day):
    return hashlib.sha256(f"{window_id}:{day}".encode()).hexdigest()[:32]


def announcement_day_checkpoint(store, window_id, day):
    return AnnouncementCheckpoint(
        store.directory / "delivery.json",
        {"window_id": window_id, "day": day, "policy": asdict(store.policy)},
    )


def execute_announcement_window_day(day, call, store, control, tags):
    window_id = tags[ANNOUNCEMENT_WINDOW_TAG]
    announcement_window_tags(
        window_id,
        tags[ANNOUNCEMENT_START_TAG],
        tags[ANNOUNCEMENT_END_TAG],
        tags[ANNOUNCEMENT_STARTED_TAG],
    )
    days = announcement_dates(tags[ANNOUNCEMENT_START_TAG], tags[ANNOUNCEMENT_END_TAG])
    if day not in days:
        raise AnnouncementError("announcement_day_outside_window")
    directory = store.staging / "anns_d" / "windows" / window_id
    state_path = directory / "admission.json"
    policy = store.policy
    identity = {"window_id": window_id, "days": days, "policy": asdict(policy)}
    identity = json.loads(json.dumps(identity))
    checkpoint = announcement_day_checkpoint(store, window_id, day)
    # No waiting worker can monopolize the only Dagster worker ahead of its predecessor.
    with announcement_file_lock(directory / "execution.lock"):
        state = (
            json.loads(state_path.read_text())
            if state_path.exists()
            else {
                "identity": identity,
                "completed": [],
                "started_at": float(tags[ANNOUNCEMENT_STARTED_TAG]),
            }
        )
        if state["identity"] != identity:
            raise AnnouncementError("announcement_window_contract_changed")
        position = days.index(day)
        if any(earlier not in state["completed"] for earlier in days[:position]):
            raise AnnouncementError("announcement_predecessor_incomplete")
        if (
            day not in state["completed"]
            and time.time() >= state["started_at"] + policy.max_window_seconds
        ):
            raise AnnouncementError("announcement_window_expired")
        budget = AnnouncementWindowBudget(directory / "budget.json", window_id, policy)
        with announcement_file_lock(budget.path.with_suffix(".lock")):
            document = budget._read()
            document["deadline"] = state["started_at"] + policy.max_window_seconds
            announcement_atomic_json(budget.path, document)
        announcement_atomic_json(state_path, state)
        control.progress(
            window_id=window_id,
            day=day,
            days_completed=len(state["completed"]),
            days_total=len(days),
            requests_budget=policy.max_window_requests,
        )
        try:
            delivery = update_announcement_day(
                day, call, store, checkpoint, control, budget, policy
            )
        except BaseException as error:
            state.update(
                failed_day=day,
                phase="cancelled"
                if isinstance(error, (AnnouncementCancelled, KeyboardInterrupt))
                else "failed",
            )
            announcement_atomic_json(state_path, state)
            raise
        if day not in state["completed"]:
            state["completed"].append(day)
        state.update(
            phase="completed" if len(state["completed"]) == len(days) else "running",
            failed_day=None,
        )
        announcement_atomic_json(state_path, state)
        control.progress(
            days_completed=len(state["completed"]),
            days_total=len(days),
            percent=100 * len(state["completed"]) / len(days),
        )
        return checkpoint, delivery


def announcement_single_day_tags(run_id, day):
    return announcement_window_tags(run_id, day, day)
