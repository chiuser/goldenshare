"""Frozen announcement intent and sequential, resumable multi-day execution."""

import hashlib
import json
import math
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from orchestrator.defs.anns_d_checkpoint import (
    ANNOUNCEMENT_CANCELLATION_ERRORS,
    AnnouncementCheckpoint,
    AnnouncementWindowBudget,
    announcement_atomic_json,
    announcement_file_fingerprint,
    announcement_file_lock,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_VERSION,
    AnnouncementError,
    announcement_date_range,
    announcement_dates,
)
from orchestrator.defs.anns_d_execution import (
    announcement_capture_pages,
    update_announcement_day,
)
from orchestrator.defs.run_contracts.anns_d import (
    ANNOUNCEMENT_EXECUTION_VERSION,
    ANNOUNCEMENT_REFRESH_DAYS,
    ANNOUNCEMENT_TIMEZONE,
)

ANNOUNCEMENT_WINDOW_TAG = "anns_d/window_id"
ANNOUNCEMENT_START_TAG = "anns_d/start_date"
ANNOUNCEMENT_END_TAG = "anns_d/end_date"
ANNOUNCEMENT_STARTED_TAG = "anns_d/started_at"
ANNOUNCEMENT_AUTOMATIC_TAG = "anns_d/automatic"
ANNOUNCEMENT_EXECUTION_VERSION_TAG = "anns_d/execution_version"

_DAY_FAILURE_REASONS = frozenset(
    {
        "announcement_source_timeout",
        "announcement_source_call_failed",
        "announcement_source_process_exit",
        "announcement_response_schema",
        "announcement_source_keys",
        "announcement_source_type",
        "announcement_source_date",
        "announcement_partition_mismatch",
        "announcement_oversized_page",
        "announcement_repeated_page",
        "announcement_day_budget",
        "announcement_file_contract",
        "announcement_file_schema",
    }
)


@dataclass(frozen=True)
class AnnouncementDayDelivery:
    day: str
    checkpoint_path: Path
    identity: Mapping[str, Any]
    delivery: Mapping[str, Any]


def announcement_refresh_dates(scheduled):
    if scheduled.tzinfo is None:
        raise AnnouncementError("announcement_schedule_timezone")
    today = scheduled.astimezone(ZoneInfo(ANNOUNCEMENT_TIMEZONE)).date()
    return announcement_date_range(
        (today - timedelta(days=ANNOUNCEMENT_REFRESH_DAYS)).isoformat(),
        (today + timedelta(days=1)).isoformat(),
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


def _window_id(window_id):
    if (
        not isinstance(window_id, str)
        or not window_id
        or not window_id.replace("-", "").replace("_", "").isalnum()
    ):
        raise AnnouncementError("announcement_window_identity")
    return window_id


def _planned_timestamp(value):
    if isinstance(value, bool):
        raise AnnouncementError("announcement_window_start_time")
    try:
        timestamp = float(value)
    except (TypeError, ValueError, OverflowError):
        raise AnnouncementError("announcement_window_start_time") from None
    if not math.isfinite(timestamp) or timestamp <= 0 or timestamp > time.time() + 1:
        raise AnnouncementError("announcement_window_start_time")
    return timestamp


def announcement_window_dates(start, end, started_at, *, automatic=False):
    scheduled = datetime.fromtimestamp(
        _planned_timestamp(started_at), ZoneInfo(ANNOUNCEMENT_TIMEZONE)
    )
    if automatic:
        expected = announcement_refresh_dates(scheduled)
        if (start, end) != (expected[0], expected[-1]):
            raise AnnouncementError("announcement_automatic_window_range")
        return expected
    return announcement_dates(start, end, today=scheduled.date())


def announcement_window_tags(
    window_id, start, end, started_at=None, *, automatic=False
):
    window_id = _window_id(window_id)
    timestamp = _planned_timestamp(time.time() if started_at is None else started_at)
    announcement_window_dates(start, end, timestamp, automatic=automatic)
    return {
        ANNOUNCEMENT_WINDOW_TAG: window_id,
        ANNOUNCEMENT_START_TAG: start,
        ANNOUNCEMENT_END_TAG: end,
        ANNOUNCEMENT_STARTED_TAG: str(timestamp),
        ANNOUNCEMENT_EXECUTION_VERSION_TAG: str(ANNOUNCEMENT_EXECUTION_VERSION),
        **({ANNOUNCEMENT_AUTOMATIC_TAG: "true"} if automatic else {}),
    }


def announcement_schedule_tags(scheduled):
    days = announcement_refresh_dates(scheduled)
    tick = scheduled.astimezone(ZoneInfo(ANNOUNCEMENT_TIMEZONE)).date().isoformat()
    window_id = hashlib.sha256(
        f"anns_d:update:{ANNOUNCEMENT_EXECUTION_VERSION}:{tick}:{days[0]}:{days[-1]}".encode()
    ).hexdigest()[:32]
    return announcement_window_tags(
        window_id, days[0], days[-1], scheduled.timestamp(), automatic=True
    )


def announcement_manual_window_id(root_run_id, first, last):
    if not isinstance(root_run_id, str) or not root_run_id:
        raise AnnouncementError("announcement_window_identity")
    announcement_date_range(first, last)
    return hashlib.sha256(
        f"anns_d:manual:{ANNOUNCEMENT_EXECUTION_VERSION}:{root_run_id}:{first}:{last}".encode()
    ).hexdigest()[:32]


def announcement_window_identity(days, tags, policy):
    days = tuple(days)
    if not days:
        raise AnnouncementError("announcement_window_dates")
    try:
        window_id = _window_id(tags[ANNOUNCEMENT_WINDOW_TAG])
        started_at = _planned_timestamp(tags[ANNOUNCEMENT_STARTED_TAG])
        start, end = tags[ANNOUNCEMENT_START_TAG], tags[ANNOUNCEMENT_END_TAG]
    except KeyError:
        raise AnnouncementError("announcement_window_intent") from None
    if tags.get(ANNOUNCEMENT_EXECUTION_VERSION_TAG) != str(
        ANNOUNCEMENT_EXECUTION_VERSION
    ):
        raise AnnouncementError("announcement_execution_version")
    automatic_tag = tags.get(ANNOUNCEMENT_AUTOMATIC_TAG)
    if automatic_tag not in (None, "true"):
        raise AnnouncementError("announcement_window_intent")
    automatic = automatic_tag == "true"
    expected = announcement_window_dates(start, end, started_at, automatic=automatic)
    if days != expected:
        raise AnnouncementError("announcement_window_dates")
    if automatic:
        scheduled = datetime.fromtimestamp(started_at, ZoneInfo(ANNOUNCEMENT_TIMEZONE))
        if window_id != announcement_schedule_tags(scheduled)[ANNOUNCEMENT_WINDOW_TAG]:
            raise AnnouncementError("announcement_window_identity")
    return {
        "execution_version": ANNOUNCEMENT_EXECUTION_VERSION,
        "window_id": window_id,
        "days": list(days),
        "started_at": started_at,
        "automatic": automatic,
        "policy": asdict(policy),
        "contract_version": ANNOUNCEMENT_VERSION,
    }


def _window_directory(staging, window_id):
    return assert_safe_announcement_path(
        Path(staging) / "anns_d" / "windows" / _window_id(window_id)
    )


def _read_document(path):
    path = assert_safe_announcement_path(path)
    try:
        document = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AnnouncementError("announcement_window_checkpoint") from None
    if not isinstance(document, dict):
        raise AnnouncementError("announcement_window_checkpoint")
    return document


def _identity_tags(identity, window_id, first, last, policy):
    if not isinstance(identity, dict):
        raise AnnouncementError("announcement_window_checkpoint")
    try:
        tags = announcement_window_tags(
            window_id,
            first,
            last,
            identity["started_at"],
            automatic=identity["automatic"],
        )
        expected = announcement_window_identity(identity["days"], tags, policy)
    except KeyError:
        raise AnnouncementError("announcement_window_checkpoint") from None
    if identity != expected:
        raise AnnouncementError("announcement_window_contract_changed")
    return tags


def announcement_restore_window_tags(window_id, first, last, staging, policy):
    directory = _window_directory(staging, window_id)
    execution_path, budget_path = (
        directory / "execution.json",
        directory / "budget.json",
    )
    if (directory / "admission.json").exists():
        raise AnnouncementError("announcement_legacy_execution")
    if execution_path.exists():
        document = _read_document(execution_path)
        tags = _identity_tags(document.get("identity"), window_id, first, last, policy)
        identity = announcement_window_identity(
            document["identity"]["days"], tags, policy
        )
        budget = AnnouncementWindowBudget(
            budget_path, window_id, policy, identity=identity, require_existing=True
        )
        _validate_execution_counts(document, budget._read())
        return tags
    if budget_path.exists():
        document = _read_document(budget_path)
        tags = _identity_tags(document.get("identity"), window_id, first, last, policy)
        identity = announcement_window_identity(
            document["identity"]["days"], tags, policy
        )
        budget = AnnouncementWindowBudget(
            budget_path, window_id, policy, identity=identity, require_existing=True
        )
        document = budget._read()
        if document["requests"] or document["day_requests"] or document["in_flight"]:
            raise AnnouncementError("announcement_window_checkpoint")
        return tags
    days = announcement_dates(first, last)
    for day in days:
        path = (
            Path(staging)
            / "anns_d"
            / f"run_id={announcement_day_run_id(window_id, day)}"
            / "delivery.json"
        )
        if assert_safe_announcement_path(path).exists():
            raise AnnouncementError("announcement_legacy_execution")
    return announcement_window_tags(window_id, first, last)


def announcement_manual_window_tags(root_run_id, first, last, staging, policy):
    window_id = announcement_manual_window_id(root_run_id, first, last)
    return announcement_restore_window_tags(window_id, first, last, staging, policy)


def announcement_day_run_id(window_id, day):
    return hashlib.sha256(f"{_window_id(window_id)}:{day}".encode()).hexdigest()[:32]


def announcement_day_checkpoint(store, window_id, day):
    return AnnouncementCheckpoint(
        store.directory / "delivery.json",
        {"window_id": window_id, "day": day, "policy": asdict(store.policy)},
    )


def _new_execution(identity, control):
    return {
        "identity": identity,
        "phase": "planned",
        "active_run_id": control.view.get("active_run_id"),
        "actual_started_at": time.time(),
        "updated_at": time.time(),
        "current_day": None,
        "days": {day: {"phase": "planned"} for day in identity["days"]},
        "requests": 0,
        "day_requests": {},
        "attempted_days": [],
        "files_completed": [],
        "failed_days": [],
        "unattempted_days": list(identity["days"]),
    }


def _load_execution(path, identity):
    state = _read_document(path)
    if state.get("identity") != identity:
        raise AnnouncementError("announcement_window_contract_changed")
    records = state.get("days")
    if (
        not isinstance(records, dict)
        or set(records) != set(identity["days"])
        or any(
            not isinstance(record, dict)
            or record.get("phase")
            not in ("planned", "running", "failed", "cancelled", "promoted")
            or record.get("failure_phase") not in (None, "failed", "cancelled")
            for record in records.values()
        )
    ):
        raise AnnouncementError("announcement_window_checkpoint")
    return state


def _summarize_execution(state):
    days, records = state["identity"]["days"], state["days"]
    state["attempted_days"] = [
        day for day in days if records[day]["phase"] != "planned"
    ]
    state["files_completed"] = [
        day for day in days if records[day]["phase"] == "promoted"
    ]
    state["failed_days"] = [
        day
        for day in days
        if records[day]["phase"] == "failed"
        or records[day].get("failure_phase") == "failed"
    ]
    state["unattempted_days"] = [
        day for day in days if records[day]["phase"] == "planned"
    ]
    state["updated_at"] = time.time()


def _validate_execution_counts(state, budget_document):
    missing = {"requests", "day_requests"} - state.keys()
    if missing:
        records = state.get("days")
        if (
            missing == {"requests", "day_requests"}
            and state.get("phase") == "planned"
            and isinstance(records, dict)
            and set(records) == set(state["identity"]["days"])
            and all(
                isinstance(record, dict) and record.get("phase") == "planned"
                for record in records.values()
            )
            and budget_document["requests"] == 0
            and not budget_document["day_requests"]
            and not budget_document["in_flight"]
        ):
            return 0, {}
        raise AnnouncementError("announcement_window_checkpoint")
    requests, day_requests = state["requests"], state["day_requests"]
    identity = state["identity"]
    if (
        type(requests) is not int
        or not 0 <= requests <= identity["policy"]["max_window_requests"]
        or not isinstance(day_requests, dict)
        or any(
            day not in identity["days"]
            or type(count) is not int
            or not 0 <= count <= identity["policy"]["max_day_requests"]
            for day, count in day_requests.items()
        )
        or sum(day_requests.values()) != requests
    ):
        raise AnnouncementError("announcement_window_checkpoint")
    if budget_document["requests"] < requests or any(
        budget_document["day_requests"].get(day, 0) < count
        for day, count in day_requests.items()
    ):
        raise AnnouncementError("announcement_window_budget_regressed")
    return requests, day_requests


def _initialize_execution(directory, identity, budget, control, staging):
    state_path = directory / "execution.json"
    if (directory / "admission.json").exists():
        raise AnnouncementError("announcement_legacy_execution")
    if state_path.exists():
        state = _load_execution(state_path, identity)
        requests, day_requests = _validate_execution_counts(state, budget._read())
        state.update(requests=requests, day_requests=day_requests)
        return state
    for day in identity["days"]:
        path = (
            Path(staging)
            / "anns_d"
            / f"run_id={announcement_day_run_id(identity['window_id'], day)}"
            / "delivery.json"
        )
        if assert_safe_announcement_path(path).exists():
            raise AnnouncementError("announcement_legacy_execution")
    if budget.path.exists():
        document = budget._read()
        if document["requests"] or document["day_requests"] or document["in_flight"]:
            raise AnnouncementError("announcement_window_checkpoint")
    else:
        announcement_atomic_json(budget.path, budget.initial_document())
    state = _new_execution(identity, control)
    announcement_atomic_json(state_path, state)
    return state


def _save_execution(path, state, budget):
    document = budget._read()
    _validate_execution_counts(state, document)
    _summarize_execution(state)
    state["requests"] = document["requests"]
    state["day_requests"] = document["day_requests"]
    announcement_atomic_json(path, state)


def _lazy_source(day, store, call_factory):
    call = None

    def invoke(params, control):
        nonlocal call
        if call is None:
            call = call_factory(day, store)
        return call(params, control)

    return invoke


def _failure_summary(state, state_path):
    return {
        "window_id": state["identity"]["window_id"],
        "fixed_days": state["identity"]["days"],
        "attempted_days": state["attempted_days"],
        "failed_days": state["failed_days"],
        "failure_reasons": {
            day: record["reason"]
            for day, record in state["days"].items()
            if record.get("reason")
        },
        "files_completed_dates": state["files_completed"],
        "unattempted_days": state["unattempted_days"],
        "requests": state["requests"],
        "checkpoint": str(state_path),
    }


def _persisted_promoted_record(checkpoint, store, day, policy):
    if not checkpoint.path.exists():
        return None
    persisted = AnnouncementCheckpoint(checkpoint.path, checkpoint.identity)
    if persisted.document.get("phase") != "promoted":
        return None
    announcement_capture_pages(persisted, page_size=policy.page_size)
    delivery = persisted.document["delivery"]
    if announcement_file_fingerprint(store.target(day)) != delivery["fingerprint"]:
        raise AnnouncementError("announcement_delivery_file_changed")
    return {
        "phase": "promoted",
        "checkpoint": str(checkpoint.path),
        "fingerprint": delivery["fingerprint"],
    }


def _record_window_failure(
    state,
    state_path,
    budget,
    control,
    day,
    checkpoint,
    committed,
    error,
    *,
    day_started,
    force_stop=False,
):
    cancelled = isinstance(error, ANNOUNCEMENT_CANCELLATION_ERRORS)
    failure_phase = "cancelled" if cancelled else "failed"
    reason = (
        str(error) if isinstance(error, AnnouncementError) else type(error).__name__
    )
    if not day_started:
        # A cancelled date was never claimed; keep its original facts.
        state["current_day"] = None
    elif committed is not None:
        # A later observation failure must not erase a committed file's proof.
        state["days"][day] = {
            **committed,
            "failure_phase": failure_phase,
            "reason": reason,
        }
    else:
        state["days"][day] = {
            "phase": failure_phase,
            "reason": reason,
            **({"checkpoint": str(checkpoint.path)} if checkpoint else {}),
        }
    state["phase"] = failure_phase
    if cancelled:
        # The enclosing locked activity persists cancellation exactly once.
        return True
    _save_execution(state_path, state, budget)
    stop = (
        force_stop
        or committed is not None
        or cancelled
        or not (
            isinstance(error, AnnouncementError) and str(error) in _DAY_FAILURE_REASONS
        )
    )
    if stop:
        control.progress(
            **_failure_summary(state, state_path),
            phase=state["phase"],
            files_completed=len(state["files_completed"]),
            days_total=len(state["identity"]["days"]),
        )
    return stop


def execute_announcement_window(
    days, *, tags, policy, control, store_factory, call_factory
):
    days = tuple(days)
    identity = announcement_window_identity(days, tags, policy)
    # Invalid intent is rejected before a store may create any staging directory.
    first_store = store_factory(days[0])
    staging = first_store.staging
    if asdict(first_store.policy) != asdict(policy):
        raise AnnouncementError("announcement_window_contract_changed")
    directory = _window_directory(staging, identity["window_id"])
    state_path = directory / "execution.json"
    budget = AnnouncementWindowBudget(
        directory / "budget.json",
        identity["window_id"],
        policy,
        identity=identity,
        require_existing=True,
    )
    with announcement_file_lock(directory / "execution.lock"):
        state = _initialize_execution(directory, identity, budget, control, staging)
        try:
            return _execute_announcement_window_locked(
                state,
                state_path,
                budget,
                control=control,
                first_store=first_store,
                policy=policy,
                store_factory=store_factory,
                call_factory=call_factory,
            )
        except ANNOUNCEMENT_CANCELLATION_ERRORS:
            state["phase"] = "cancelled"
            _save_execution(state_path, state, budget)
            control.progress(
                **_failure_summary(state, state_path),
                phase="cancelled",
                files_completed=len(state["files_completed"]),
                days_total=len(days),
            )
            raise


def _execute_announcement_window_locked(
    state,
    state_path,
    budget,
    *,
    control,
    first_store,
    policy,
    store_factory,
    call_factory,
):
    """Run the validated activity while its caller owns the execution lock."""
    identity = state["identity"]
    days = tuple(identity["days"])
    staging, root = first_store.staging, first_store.root
    deliveries = {}
    state["active_run_id"] = control.view.get("active_run_id")
    state["phase"] = "running"
    _save_execution(state_path, state, budget)
    control.progress(
        window_id=identity["window_id"],
        phase="files_running",
        files_completed=len(state["files_completed"]),
        days_total=len(days),
        requests=state["requests"],
    )
    for index, day in enumerate(days):
        checkpoint = None
        previous = deepcopy(state["days"][day])
        committed = previous if previous["phase"] == "promoted" else None
        day_started = day_helper_entered = False
        try:
            control.check()
            day_started = True
            state["current_day"] = day
            if previous["phase"] == "planned":
                state["days"][day] = {"phase": "running"}
            _save_execution(state_path, state, budget)
            store = first_store if index == 0 else store_factory(day)
            if (
                store.staging != staging
                or store.root != root
                or asdict(store.policy) != asdict(policy)
                or store.directory
                != staging
                / "anns_d"
                / (f"run_id={announcement_day_run_id(identity['window_id'], day)}")
            ):
                raise AnnouncementError("announcement_window_contract_changed")
            checkpoint = announcement_day_checkpoint(store, identity["window_id"], day)
            if previous.get("checkpoint") and (
                previous["checkpoint"] != str(checkpoint.path)
                or not checkpoint.path.exists()
            ):
                raise AnnouncementError("announcement_delivery_missing")
            if previous["phase"] == "promoted" and (
                not checkpoint.document.get("delivery")
                or checkpoint.document["delivery"].get("fingerprint")
                != previous.get("fingerprint")
            ):
                raise AnnouncementError("announcement_delivery_missing")
            day_helper_entered = True
            delivery = update_announcement_day(
                day,
                _lazy_source(day, store, call_factory),
                store,
                checkpoint,
                control,
                budget,
                policy,
                window_dates=days,
            )
            deliveries[day] = AnnouncementDayDelivery(
                day,
                checkpoint.path,
                MappingProxyType(deepcopy(checkpoint.identity)),
                MappingProxyType(deepcopy(delivery)),
            )
            state["days"][day] = {
                "phase": "promoted",
                "checkpoint": str(checkpoint.path),
                "fingerprint": delivery["fingerprint"],
            }
            _save_execution(state_path, state, budget)
            committed = deepcopy(state["days"][day])
            control.progress(
                window_id=identity["window_id"],
                phase="file_promoted",
                day=day,
                files_completed=len(state["files_completed"]),
                days_total=len(days),
                requests=state["requests"],
                requests_budget=policy.max_window_requests,
            )
            control.check()
        except BaseException as error:
            if committed is None and day_helper_entered and checkpoint is not None:
                try:
                    committed = _persisted_promoted_record(
                        checkpoint, store, day, policy
                    )
                except (Exception, *ANNOUNCEMENT_CANCELLATION_ERRORS) as proof_error:
                    _record_window_failure(
                        state,
                        state_path,
                        budget,
                        control,
                        day,
                        checkpoint,
                        None,
                        proof_error,
                        day_started=day_started,
                        force_stop=True,
                    )
                    raise
            if _record_window_failure(
                state,
                state_path,
                budget,
                control,
                day,
                checkpoint,
                committed,
                error,
                day_started=day_started,
            ):
                raise
    state["current_day"] = None
    state["phase"] = "failed" if state["failed_days"] else "files_completed"
    _save_execution(state_path, state, budget)
    if state["failed_days"]:
        summary = _failure_summary(state, state_path)
        control.progress(
            **summary,
            phase="failed",
            files_completed=len(state["files_completed"]),
            days_total=len(days),
        )
        raise AnnouncementError("announcement_window_failed", source_sample=summary)
    control.progress(
        window_id=identity["window_id"],
        phase="files_completed",
        files_completed=len(days),
        days_total=len(days),
        requests=state["requests"],
    )
    control.check()
    return deliveries
