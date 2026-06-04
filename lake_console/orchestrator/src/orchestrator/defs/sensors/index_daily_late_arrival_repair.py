"""Late-arrival repair planning for index_daily raw sensor runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


REPAIR_CURSOR_KEY = "repair_state"
MAX_REPAIR_RUN_REQUESTS_PER_TICK = 50
MAX_REPAIR_ATTEMPTS_PER_CODE_PER_DAY = 8
MAX_REPAIR_CURSOR_CODE_COUNT = 500
REPAIR_BACKOFF_MINUTES_BY_NEXT_ATTEMPT = (15, 30, 30)
REPAIR_BACKOFF_MINUTES_AFTER_THIRD_ATTEMPT = 60


@dataclass(frozen=True)
class IndexDailyPendingCodeRun:
    index_code: str
    run_key: str
    is_repair: bool
    repair_attempt: int


@dataclass(frozen=True)
class IndexDailyPendingCodeSelection:
    runs: tuple[IndexDailyPendingCodeRun, ...]
    next_pending_offset: int
    repair_state: dict[str, Any]
    new_code_count: int
    repair_due_count: int
    repair_selected_count: int
    repair_waiting_count: int
    repair_exhausted_count: int
    repair_budget_limited_count: int
    repair_state_code_count: int
    repair_cursor_code_limit_exceeded: bool


def select_index_daily_pending_code_runs(
    *,
    cursor_payload: Mapping[str, Any],
    evaluated_at: datetime,
    target_trade_date: str,
    pending_codes: Sequence[str],
    max_initial_run_requests: int,
    max_repair_run_requests: int = MAX_REPAIR_RUN_REQUESTS_PER_TICK,
    max_repair_attempts_per_code_per_day: int = MAX_REPAIR_ATTEMPTS_PER_CODE_PER_DAY,
    max_repair_cursor_code_count: int = MAX_REPAIR_CURSOR_CODE_COUNT,
) -> IndexDailyPendingCodeSelection:
    """Select raw index_daily code runs with bounded late-arrival repair attempts."""

    if max_initial_run_requests < 0:
        raise ValueError("max_initial_run_requests must not be negative.")
    if max_repair_run_requests < 0:
        raise ValueError("max_repair_run_requests must not be negative.")
    if max_repair_attempts_per_code_per_day <= 0:
        raise ValueError("max_repair_attempts_per_code_per_day must be positive.")
    if max_repair_cursor_code_count <= 0:
        raise ValueError("max_repair_cursor_code_count must be positive.")

    normalized_pending_codes = tuple(dict.fromkeys(pending_codes))
    if not normalized_pending_codes:
        return IndexDailyPendingCodeSelection(
            runs=(),
            next_pending_offset=0,
            repair_state={},
            new_code_count=0,
            repair_due_count=0,
            repair_selected_count=0,
            repair_waiting_count=0,
            repair_exhausted_count=0,
            repair_budget_limited_count=0,
            repair_state_code_count=0,
            repair_cursor_code_limit_exceeded=False,
        )

    evaluation_date = _repair_evaluation_date(evaluated_at)
    state_by_code = _load_repair_state_by_code(
        cursor_payload=cursor_payload,
        target_trade_date=target_trade_date,
        pending_codes=normalized_pending_codes,
        evaluation_date=evaluation_date,
        evaluated_at=evaluated_at,
    )
    state_by_code.update(
        _states_from_previous_selected_codes(
            cursor_payload=cursor_payload,
            target_trade_date=target_trade_date,
            pending_codes=normalized_pending_codes,
            known_codes=tuple(state_by_code),
            evaluated_at=evaluated_at,
        )
    )

    initial_codes = tuple(
        code for code in normalized_pending_codes if code not in state_by_code
    )
    selected_initial_codes, next_pending_offset = _select_initial_codes(
        cursor_payload=cursor_payload,
        target_trade_date=target_trade_date,
        pending_codes=initial_codes,
        max_initial_run_requests=max_initial_run_requests,
    )

    runs: list[IndexDailyPendingCodeRun] = []
    for index_code in selected_initial_codes:
        run_key = base_index_daily_run_key(
            trade_date=target_trade_date,
            index_code=index_code,
        )
        state_by_code[index_code] = _state_entry(
            attempt=0,
            last_run_key=run_key,
            last_launched_at=evaluated_at,
            next_retry_at=evaluated_at + _repair_backoff_for_next_attempt(1),
        )
        runs.append(
            IndexDailyPendingCodeRun(
                index_code=index_code,
                run_key=run_key,
                is_repair=False,
                repair_attempt=0,
            )
        )

    repair_cursor_code_limit_exceeded = (
        len(state_by_code) > max_repair_cursor_code_count
    )
    due_repair_codes: list[str] = []
    repair_waiting_count = 0
    repair_exhausted_count = 0
    repair_selected_count = 0
    repair_budget_limited_count = 0

    if not selected_initial_codes and not repair_cursor_code_limit_exceeded:
        for index_code in normalized_pending_codes:
            state = state_by_code.get(index_code)
            if state is None:
                continue
            attempt = _state_attempt(state)
            if attempt >= max_repair_attempts_per_code_per_day:
                repair_exhausted_count += 1
                continue
            next_retry_at = _parse_datetime(state.get("next_retry_at"), evaluated_at)
            if next_retry_at is not None and next_retry_at > evaluated_at:
                repair_waiting_count += 1
                continue
            due_repair_codes.append(index_code)

        selected_repair_codes = tuple(due_repair_codes[:max_repair_run_requests])
        repair_budget_limited_count = max(
            0, len(due_repair_codes) - len(selected_repair_codes)
        )
        for index_code in selected_repair_codes:
            state = state_by_code[index_code]
            next_attempt = _state_attempt(state) + 1
            run_key = repair_index_daily_run_key(
                trade_date=target_trade_date,
                index_code=index_code,
                evaluation_date=evaluation_date,
                repair_attempt=next_attempt,
            )
            next_retry_at = (
                None
                if next_attempt >= max_repair_attempts_per_code_per_day
                else evaluated_at
                + _repair_backoff_for_next_attempt(next_attempt + 1)
            )
            state_by_code[index_code] = _state_entry(
                attempt=next_attempt,
                last_run_key=run_key,
                last_launched_at=evaluated_at,
                next_retry_at=next_retry_at,
            )
            runs.append(
                IndexDailyPendingCodeRun(
                    index_code=index_code,
                    run_key=run_key,
                    is_repair=True,
                    repair_attempt=next_attempt,
                )
            )
        repair_selected_count = len(selected_repair_codes)

    repair_state = _repair_state_payload(
        target_trade_date=target_trade_date,
        evaluation_date=evaluation_date,
        state_by_code=state_by_code,
    )
    return IndexDailyPendingCodeSelection(
        runs=tuple(runs),
        next_pending_offset=next_pending_offset,
        repair_state=repair_state,
        new_code_count=len(initial_codes),
        repair_due_count=len(due_repair_codes),
        repair_selected_count=repair_selected_count,
        repair_waiting_count=repair_waiting_count,
        repair_exhausted_count=repair_exhausted_count,
        repair_budget_limited_count=repair_budget_limited_count,
        repair_state_code_count=len(state_by_code),
        repair_cursor_code_limit_exceeded=repair_cursor_code_limit_exceeded,
    )


def base_index_daily_run_key(*, trade_date: str, index_code: str) -> str:
    return f"index_daily:{trade_date}:{index_code}"


def repair_index_daily_run_key(
    *,
    trade_date: str,
    index_code: str,
    evaluation_date: str,
    repair_attempt: int,
) -> str:
    return f"index_daily:{trade_date}:{index_code}:repair:{evaluation_date}:{repair_attempt}"


def _cursor_details(cursor_payload: Mapping[str, Any]) -> dict[str, Any]:
    details = cursor_payload.get("details")
    return dict(details) if isinstance(details, Mapping) else {}


def _repair_evaluation_date(evaluated_at: datetime) -> str:
    return evaluated_at.strftime("%Y%m%d")


def _select_initial_codes(
    *,
    cursor_payload: Mapping[str, Any],
    target_trade_date: str,
    pending_codes: tuple[str, ...],
    max_initial_run_requests: int,
) -> tuple[tuple[str, ...], int]:
    if not pending_codes or max_initial_run_requests == 0:
        return (), 0

    details = _cursor_details(cursor_payload)
    cursor_trade_date = cursor_payload.get("target_date")
    raw_offset = details.get("next_pending_offset", 0)
    start_offset = raw_offset if cursor_trade_date == target_trade_date else 0
    if not isinstance(start_offset, int) or start_offset < 0:
        start_offset = 0
    start_offset = start_offset % len(pending_codes)

    rotated_pending_codes = pending_codes[start_offset:] + pending_codes[:start_offset]
    selected_codes = rotated_pending_codes[:max_initial_run_requests]
    next_offset = (start_offset + len(selected_codes)) % len(pending_codes)
    return selected_codes, next_offset


def _load_repair_state_by_code(
    *,
    cursor_payload: Mapping[str, Any],
    target_trade_date: str,
    pending_codes: tuple[str, ...],
    evaluation_date: str,
    evaluated_at: datetime,
) -> dict[str, dict[str, Any]]:
    details = _cursor_details(cursor_payload)
    raw_repair_state = details.get(REPAIR_CURSOR_KEY)
    if not isinstance(raw_repair_state, Mapping):
        return {}
    if raw_repair_state.get("target_trade_date") != target_trade_date:
        return {}
    raw_codes = raw_repair_state.get("codes")
    if not isinstance(raw_codes, Mapping):
        return {}

    previous_evaluation_date = raw_repair_state.get("evaluation_date")
    pending_code_set = set(pending_codes)
    state_by_code: dict[str, dict[str, Any]] = {}
    for index_code, raw_state in raw_codes.items():
        if index_code not in pending_code_set or not isinstance(raw_state, Mapping):
            continue
        last_run_key = _string_or_empty(raw_state.get("last_run_key"))
        last_launched_at = _parse_datetime(raw_state.get("last_launched_at"), evaluated_at)
        if previous_evaluation_date != evaluation_date:
            state_by_code[index_code] = _state_entry(
                attempt=0,
                last_run_key=last_run_key,
                last_launched_at=last_launched_at,
                next_retry_at=None,
            )
            continue
        state_by_code[index_code] = _state_entry(
            attempt=_coerce_non_negative_int(raw_state.get("attempt"), default=0),
            last_run_key=last_run_key,
            last_launched_at=last_launched_at,
            next_retry_at=_parse_datetime(raw_state.get("next_retry_at"), evaluated_at),
        )
    return state_by_code


def _states_from_previous_selected_codes(
    *,
    cursor_payload: Mapping[str, Any],
    target_trade_date: str,
    pending_codes: tuple[str, ...],
    known_codes: tuple[str, ...],
    evaluated_at: datetime,
) -> dict[str, dict[str, Any]]:
    if cursor_payload.get("target_date") != target_trade_date:
        return {}
    details = _cursor_details(cursor_payload)
    raw_selected_codes = details.get("selected_codes")
    if not isinstance(raw_selected_codes, Sequence) or isinstance(
        raw_selected_codes, str
    ):
        return {}

    known_code_set = set(known_codes)
    pending_code_set = set(pending_codes)
    launched_at = _parse_datetime(cursor_payload.get("evaluated_at"), evaluated_at)
    if launched_at is None:
        launched_at = evaluated_at
    state_by_code: dict[str, dict[str, Any]] = {}
    for raw_index_code in raw_selected_codes:
        if not isinstance(raw_index_code, str):
            continue
        index_code = raw_index_code
        if index_code not in pending_code_set or index_code in known_code_set:
            continue
        run_key = base_index_daily_run_key(
            trade_date=target_trade_date,
            index_code=index_code,
        )
        state_by_code[index_code] = _state_entry(
            attempt=0,
            last_run_key=run_key,
            last_launched_at=launched_at,
            next_retry_at=launched_at + _repair_backoff_for_next_attempt(1),
        )
    return state_by_code


def _state_entry(
    *,
    attempt: int,
    last_run_key: str,
    last_launched_at: datetime | None,
    next_retry_at: datetime | None,
) -> dict[str, Any]:
    return {
        "attempt": max(0, attempt),
        "last_run_key": last_run_key,
        "last_launched_at": last_launched_at,
        "next_retry_at": next_retry_at,
    }


def _repair_state_payload(
    *,
    target_trade_date: str,
    evaluation_date: str,
    state_by_code: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not state_by_code:
        return {}
    return {
        "target_trade_date": target_trade_date,
        "evaluation_date": evaluation_date,
        "codes": {
            index_code: {
                "attempt": _state_attempt(state),
                "last_run_key": _string_or_empty(state.get("last_run_key")),
                "last_launched_at": _datetime_to_iso(state.get("last_launched_at")),
                "next_retry_at": _datetime_to_iso(state.get("next_retry_at")),
            }
            for index_code, state in sorted(state_by_code.items())
        },
    }


def _repair_backoff_for_next_attempt(next_attempt: int) -> timedelta:
    if next_attempt <= 0:
        raise ValueError("next_attempt must be positive.")
    if next_attempt <= len(REPAIR_BACKOFF_MINUTES_BY_NEXT_ATTEMPT):
        minutes = REPAIR_BACKOFF_MINUTES_BY_NEXT_ATTEMPT[next_attempt - 1]
    else:
        minutes = REPAIR_BACKOFF_MINUTES_AFTER_THIRD_ATTEMPT
    return timedelta(minutes=minutes)


def _state_attempt(state: Mapping[str, Any]) -> int:
    return _coerce_non_negative_int(state.get("attempt"), default=0)


def _coerce_non_negative_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    return default


def _string_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _parse_datetime(value: Any, evaluated_at: datetime) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None and evaluated_at.tzinfo is not None:
        return parsed.replace(tzinfo=evaluated_at.tzinfo)
    return parsed


def _datetime_to_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None
