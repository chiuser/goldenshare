"""Continuity gates for stock minute date-driven chains."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Protocol

import dagster as dg

from orchestrator.defs.paths import gold_stk_mins_qfq_macd_kdj_state_path
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_CONTINUITY_SAMPLE_LIMIT,
    STK_MINS_CONTINUITY_WINDOW_LIMIT,
)


class ReadinessStatusLike(Protocol):
    ready: bool
    reason: str


@dataclass(frozen=True)
class StockMinsContinuityStatus:
    partition_set_name: str
    expected_start_date: str | None
    expected_end_date: str | None
    expected_count: int
    registered_count: int
    ready_count: int
    first_missing_registered_date: str | None
    missing_registered_date_samples: tuple[str, ...]
    first_not_ready_trade_date: str | None
    first_not_ready_reason: str | None
    previous_expected_trade_date: str | None
    ready_through_trade_date: str | None
    next_actionable_trade_date: str | None
    blocked_reason: str | None

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None

    def to_cursor_details(self) -> dict[str, object]:
        return {
            "partition_set_name": self.partition_set_name,
            "expected_start_date": self.expected_start_date,
            "expected_end_date": self.expected_end_date,
            "expected_count": self.expected_count,
            "registered_count": self.registered_count,
            "ready_count": self.ready_count,
            "first_missing_registered_date": self.first_missing_registered_date,
            "missing_registered_date_samples": list(
                self.missing_registered_date_samples
            ),
            "first_not_ready_trade_date": self.first_not_ready_trade_date,
            "first_not_ready_reason": self.first_not_ready_reason,
            "previous_expected_trade_date": self.previous_expected_trade_date,
            "ready_through_trade_date": self.ready_through_trade_date,
            "next_actionable_trade_date": self.next_actionable_trade_date,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class StockMinsContinuitySelection:
    status: StockMinsContinuityStatus
    selected_trade_date: str | None
    selected_status: ReadinessStatusLike | None


def _normalize_partition_set_name(partition_set_name: str) -> str:
    normalized = partition_set_name.strip()
    if not normalized:
        raise ValueError("partition_set_name is required.")
    return normalized


def _normalize_trade_date(value: str, *, field_name: str = "trade_date") -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be an ISO trade date: {value!r}."
        ) from error


def _normalize_trade_dates(
    values: Sequence[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _normalize_trade_date(value, field_name=field_name)
                for value in values
            }
        )
    )


def _date_samples(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(values[:STK_MINS_CONTINUITY_SAMPLE_LIMIT])


def _expected_bounds(
    expected_trade_dates: Sequence[str],
) -> tuple[str | None, str | None]:
    if not expected_trade_dates:
        return None, None
    return expected_trade_dates[0], expected_trade_dates[-1]


def load_stock_mins_expected_trade_dates(
    connection,
    calendar_path: Path,
    *,
    min_trade_date: str,
    evaluated_at: datetime,
    same_day_register_start: time | None = None,
) -> tuple[str, ...]:
    min_trade_date = _normalize_trade_date(
        min_trade_date,
        field_name="min_trade_date",
    )
    today = evaluated_at.date().isoformat()
    rows = connection.execute(
        """
        SELECT CAST(trade_date AS VARCHAR) AS trade_date
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND trade_date >= CAST(? AS DATE)
          AND trade_date <= CAST(? AS DATE)
        ORDER BY trade_date
        """,
        [str(calendar_path), min_trade_date, today],
    ).fetchall()
    trade_dates = tuple(row[0] for row in rows)
    if (
        same_day_register_start is not None
        and evaluated_at.time() < same_day_register_start
    ):
        trade_dates = tuple(
            trade_date for trade_date in trade_dates if trade_date != today
        )
    return trade_dates


def previous_expected_trade_date(
    expected_trade_dates: Sequence[str],
    target_trade_date: str,
) -> str | None:
    expected_trade_dates = _normalize_trade_dates(
        expected_trade_dates,
        field_name="expected_trade_date",
    )
    target_trade_date = _normalize_trade_date(
        target_trade_date,
        field_name="target_trade_date",
    )
    for trade_date in reversed(expected_trade_dates):
        if trade_date < target_trade_date:
            return trade_date
    return None


def is_first_expected_trade_date(
    expected_trade_dates: Sequence[str],
    target_trade_date: str,
) -> bool:
    expected_trade_dates = _normalize_trade_dates(
        expected_trade_dates,
        field_name="expected_trade_date",
    )
    target_trade_date = _normalize_trade_date(
        target_trade_date,
        field_name="target_trade_date",
    )
    return bool(expected_trade_dates) and expected_trade_dates[0] == target_trade_date


def expected_trade_dates_between(
    expected_trade_dates: Sequence[str],
    *,
    start_trade_date: str,
    end_trade_date: str,
) -> tuple[str, ...]:
    expected_trade_dates = _normalize_trade_dates(
        expected_trade_dates,
        field_name="expected_trade_date",
    )
    start_trade_date = _normalize_trade_date(
        start_trade_date,
        field_name="start_trade_date",
    )
    end_trade_date = _normalize_trade_date(
        end_trade_date,
        field_name="end_trade_date",
    )
    if start_trade_date > end_trade_date:
        raise ValueError("start_trade_date must not be after end_trade_date.")
    return tuple(
        trade_date
        for trade_date in expected_trade_dates
        if start_trade_date <= trade_date <= end_trade_date
    )


def build_registered_gap_status(
    *,
    partition_set_name: str,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    target_trade_date: str | None = None,
) -> StockMinsContinuityStatus:
    partition_set_name = _normalize_partition_set_name(partition_set_name)
    expected_trade_dates = _normalize_trade_dates(
        expected_trade_dates,
        field_name="expected_trade_date",
    )
    registered_trade_days = _normalize_trade_dates(
        registered_trade_days,
        field_name="registered_trade_day",
    )
    registered_trade_day_set = set(registered_trade_days)
    missing_registered_dates = tuple(
        trade_date
        for trade_date in expected_trade_dates
        if trade_date not in registered_trade_day_set
    )
    first_missing_registered_date = (
        missing_registered_dates[0] if missing_registered_dates else None
    )
    ready_through_trade_date = None
    ready_count = 0
    for trade_date in expected_trade_dates:
        if trade_date not in registered_trade_day_set:
            break
        ready_through_trade_date = trade_date
        ready_count += 1

    expected_start_date, expected_end_date = _expected_bounds(expected_trade_dates)
    return StockMinsContinuityStatus(
        partition_set_name=partition_set_name,
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
        expected_count=len(expected_trade_dates),
        registered_count=sum(
            1
            for trade_date in expected_trade_dates
            if trade_date in registered_trade_day_set
        ),
        ready_count=ready_count,
        first_missing_registered_date=first_missing_registered_date,
        missing_registered_date_samples=_date_samples(missing_registered_dates),
        first_not_ready_trade_date=None,
        first_not_ready_reason=None,
        previous_expected_trade_date=(
            previous_expected_trade_date(expected_trade_dates, target_trade_date)
            if target_trade_date is not None
            else None
        ),
        ready_through_trade_date=ready_through_trade_date,
        next_actionable_trade_date=first_missing_registered_date,
        blocked_reason=(
            "missing_registered_partition"
            if first_missing_registered_date is not None
            else None
        ),
    )


def select_first_not_ready_trade_date(
    *,
    partition_set_name: str,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    readiness_for_trade_date: Callable[[str], ReadinessStatusLike],
    has_materialized_check_problem: Callable[[ReadinessStatusLike], bool],
    window_limit: int = STK_MINS_CONTINUITY_WINDOW_LIMIT,
) -> StockMinsContinuitySelection:
    if window_limit <= 0:
        raise ValueError("window_limit must be greater than zero.")

    partition_set_name = _normalize_partition_set_name(partition_set_name)
    expected_trade_dates = _normalize_trade_dates(
        expected_trade_dates,
        field_name="expected_trade_date",
    )[-window_limit:]
    registered_trade_days = _normalize_trade_dates(
        registered_trade_days,
        field_name="registered_trade_day",
    )
    registered_trade_day_set = set(registered_trade_days)
    expected_start_date, expected_end_date = _expected_bounds(expected_trade_dates)
    registered_count = sum(
        1
        for expected_trade_date in expected_trade_dates
        if expected_trade_date in registered_trade_day_set
    )
    missing_registered_dates = tuple(
        expected_trade_date
        for expected_trade_date in expected_trade_dates
        if expected_trade_date not in registered_trade_day_set
    )
    if missing_registered_dates:
        first_missing_registered_date = missing_registered_dates[0]
        status = StockMinsContinuityStatus(
            partition_set_name=partition_set_name,
            expected_start_date=expected_start_date,
            expected_end_date=expected_end_date,
            expected_count=len(expected_trade_dates),
            registered_count=registered_count,
            ready_count=0,
            first_missing_registered_date=first_missing_registered_date,
            missing_registered_date_samples=_date_samples(missing_registered_dates),
            first_not_ready_trade_date=None,
            first_not_ready_reason=None,
            previous_expected_trade_date=previous_expected_trade_date(
                expected_trade_dates,
                first_missing_registered_date,
            ),
            ready_through_trade_date=None,
            next_actionable_trade_date=None,
            blocked_reason="missing_registered_partition",
        )
        return StockMinsContinuitySelection(
            status=status,
            selected_trade_date=None,
            selected_status=None,
        )

    ready_count = 0
    ready_through_trade_date = None

    for trade_date in expected_trade_dates:
        readiness_status = readiness_for_trade_date(trade_date)
        if readiness_status.ready:
            ready_count += 1
            ready_through_trade_date = trade_date
            continue

        blocked_reason = (
            "materialized_check_problem"
            if has_materialized_check_problem(readiness_status)
            else None
        )
        selected_trade_date = None if blocked_reason else trade_date
        status = StockMinsContinuityStatus(
            partition_set_name=partition_set_name,
            expected_start_date=expected_start_date,
            expected_end_date=expected_end_date,
            expected_count=len(expected_trade_dates),
            registered_count=registered_count,
            ready_count=ready_count,
            first_missing_registered_date=None,
            missing_registered_date_samples=(),
            first_not_ready_trade_date=trade_date,
            first_not_ready_reason=readiness_status.reason,
            previous_expected_trade_date=previous_expected_trade_date(
                expected_trade_dates,
                trade_date,
            ),
            ready_through_trade_date=ready_through_trade_date,
            next_actionable_trade_date=selected_trade_date,
            blocked_reason=blocked_reason,
        )
        return StockMinsContinuitySelection(
            status=status,
            selected_trade_date=selected_trade_date,
            selected_status=readiness_status,
        )

    status = StockMinsContinuityStatus(
        partition_set_name=partition_set_name,
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
        expected_count=len(expected_trade_dates),
        registered_count=registered_count,
        ready_count=ready_count,
        first_missing_registered_date=None,
        missing_registered_date_samples=(),
        first_not_ready_trade_date=None,
        first_not_ready_reason=None,
        previous_expected_trade_date=None,
        ready_through_trade_date=ready_through_trade_date,
        next_actionable_trade_date=None,
        blocked_reason=None,
    )
    return StockMinsContinuitySelection(
        status=status,
        selected_trade_date=None,
        selected_status=None,
    )


def assert_expected_dates_registered(
    *,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    partition_set_name: str,
    start_trade_date: str,
    end_trade_date: str,
) -> tuple[str, ...]:
    partition_set_name = _normalize_partition_set_name(partition_set_name)
    expected_range = expected_trade_dates_between(
        expected_trade_dates,
        start_trade_date=start_trade_date,
        end_trade_date=end_trade_date,
    )
    if not expected_range:
        raise dg.Failure(
            description=(
                "Stock mins expected trade date range is empty: "
                f"start_trade_date={start_trade_date}, end_trade_date={end_trade_date}."
            ),
            metadata={
                "partition_set_name": partition_set_name,
                "start_trade_date": start_trade_date,
                "end_trade_date": end_trade_date,
            },
        )

    registered_trade_day_set = set(
        _normalize_trade_dates(
            registered_trade_days,
            field_name="registered_trade_day",
        )
    )
    missing_registered_dates = tuple(
        trade_date
        for trade_date in expected_range
        if trade_date not in registered_trade_day_set
    )
    if missing_registered_dates:
        raise dg.Failure(
            description=(
                "Stock mins expected trade dates are not fully registered: "
                f"partition_set={partition_set_name}, "
                f"first_missing_registered_date={missing_registered_dates[0]}."
            ),
            metadata={
                "partition_set_name": partition_set_name,
                "first_missing_registered_date": missing_registered_dates[0],
                "missing_registered_date_samples": list(
                    _date_samples(missing_registered_dates)
                ),
                "missing_registered_date_count": len(missing_registered_dates),
                "start_trade_date": expected_range[0],
                "end_trade_date": expected_range[-1],
            },
        )
    return expected_range


def assert_exact_previous_state_path(
    *,
    lake_root: Path,
    freq: int,
    target_trade_date: str,
    previous_expected_trade_date: str | None,
    allow_without_previous_state: bool,
) -> Path | None:
    target_trade_date = _normalize_trade_date(
        target_trade_date,
        field_name="target_trade_date",
    )
    if previous_expected_trade_date is None:
        if allow_without_previous_state:
            return None
        raise dg.Failure(
            description=(
                "Stock mins MACD/KDJ requires a previous expected state before "
                f"target_trade_date={target_trade_date}."
            ),
            metadata={
                "target_trade_date": target_trade_date,
                "allow_without_previous_state": allow_without_previous_state,
            },
        )

    previous_expected_trade_date = _normalize_trade_date(
        previous_expected_trade_date,
        field_name="previous_expected_trade_date",
    )
    previous_state_path = gold_stk_mins_qfq_macd_kdj_state_path(
        lake_root,
        freq,
        previous_expected_trade_date,
    )
    if previous_state_path.exists():
        return previous_state_path
    raise dg.Failure(
        description=(
            "Stock mins MACD/KDJ previous expected state is missing: "
            f"target_trade_date={target_trade_date}, "
            f"previous_expected_trade_date={previous_expected_trade_date}."
        ),
        metadata={
            "target_trade_date": target_trade_date,
            "previous_expected_trade_date": previous_expected_trade_date,
            "previous_state_path": str(previous_state_path),
        },
    )
