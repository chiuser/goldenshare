"""Bounded continuity selector primitives for non-stock-minute sensors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path


DEFAULT_CONTINUITY_WINDOW_LIMIT = 10
DEFAULT_CONTINUITY_SAMPLE_LIMIT = 20
_MISSING_READINESS_REASON = "readiness_status_missing"
_UNKNOWN_TRADE_DATE_REASON = "unknown_trade_date"


def _normalize_trade_date(value: str, *, field_name: str = "trade_date") -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be an ISO trade date: {value!r}."
        ) from error


def _normalize_optional_trade_date(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _normalize_trade_date(value, field_name=field_name)


def _normalize_trade_dates(
    values: Iterable[str],
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


def _sample(values: Sequence[object], sample_limit: int) -> tuple[object, ...]:
    if sample_limit <= 0:
        return ()
    return tuple(values[:sample_limit])


def _date_bounds(values: Sequence[str]) -> tuple[str | None, str | None]:
    if not values:
        return None, None
    return values[0], values[-1]


@dataclass(frozen=True)
class ContinuityExpectedDateWindow:
    expected_trade_dates: tuple[str, ...]
    min_trade_date: str | None
    max_trade_date: str | None
    evaluated_at: datetime
    window_limit: int

    def __post_init__(self) -> None:
        if self.window_limit <= 0:
            raise ValueError("window_limit must be greater than zero.")
        expected_trade_dates = _normalize_trade_dates(
            self.expected_trade_dates,
            field_name="expected_trade_date",
        )
        if len(expected_trade_dates) > self.window_limit:
            raise ValueError(
                "expected_trade_dates must already be clipped to window_limit."
            )
        min_trade_date = _normalize_optional_trade_date(
            self.min_trade_date,
            field_name="min_trade_date",
        )
        max_trade_date = expected_trade_dates[-1] if expected_trade_dates else None
        if self.max_trade_date is not None:
            normalized_max = _normalize_trade_date(
                self.max_trade_date,
                field_name="max_trade_date",
            )
            if normalized_max != max_trade_date:
                raise ValueError("max_trade_date must match the last expected date.")
        object.__setattr__(self, "expected_trade_dates", expected_trade_dates)
        object.__setattr__(self, "min_trade_date", min_trade_date)
        object.__setattr__(self, "max_trade_date", max_trade_date)


@dataclass(frozen=True)
class ContinuityRegisteredGapStatus:
    expected_trade_dates: tuple[str, ...]
    registered_trade_dates: tuple[str, ...]
    first_missing_registered_date: str | None
    missing_registered_dates: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.first_missing_registered_date is None

    def to_cursor_details(self) -> dict[str, object]:
        expected_start_date, expected_end_date = _date_bounds(
            self.expected_trade_dates
        )
        return {
            "expected_start_date": expected_start_date,
            "expected_end_date": expected_end_date,
            "expected_count": len(self.expected_trade_dates),
            "registered_count": len(self.registered_trade_dates),
            "first_missing_registered_date": self.first_missing_registered_date,
            "missing_registered_dates": list(self.missing_registered_dates),
        }


@dataclass(frozen=True)
class ContinuityDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...] = ()
    missing_check_names: tuple[str, ...] = ()
    missing_file_paths: tuple[str, ...] = ()
    summary: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        trade_date = _normalize_trade_date(self.trade_date)
        reason = str(self.reason).strip()
        if not reason:
            raise ValueError("reason is required.")
        if self.ready != (self.materialized and self.checks_passed):
            raise ValueError("ready must equal materialized and checks_passed.")
        object.__setattr__(self, "trade_date", trade_date)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "failed_check_names",
            tuple(str(value) for value in self.failed_check_names),
        )
        object.__setattr__(
            self,
            "missing_check_names",
            tuple(str(value) for value in self.missing_check_names),
        )
        object.__setattr__(
            self,
            "missing_file_paths",
            tuple(str(value) for value in self.missing_file_paths),
        )
        object.__setattr__(self, "summary", dict(self.summary))

    def to_cursor_details(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "materialized": self.materialized,
            "checks_passed": self.checks_passed,
            "reason": self.reason,
            "failed_check_names": list(self.failed_check_names),
            "missing_check_names": list(self.missing_check_names),
            "missing_file_paths": list(self.missing_file_paths),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class ContinuityBatchReadiness:
    expected_trade_dates: tuple[str, ...]
    statuses_by_trade_date: Mapping[str, ContinuityDateReadiness]
    elapsed_ms: int
    scanned_file_count: int = 0

    def __post_init__(self) -> None:
        expected_trade_dates = _normalize_trade_dates(
            self.expected_trade_dates,
            field_name="expected_trade_date",
        )
        statuses_by_trade_date: dict[str, ContinuityDateReadiness] = {}
        for key, status in self.statuses_by_trade_date.items():
            trade_date = _normalize_trade_date(
                key,
                field_name="status_trade_date",
            )
            if status.trade_date != trade_date:
                raise ValueError(
                    "status trade_date must match statuses_by_trade_date key."
                )
            statuses_by_trade_date[trade_date] = status
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must not be negative.")
        if self.scanned_file_count < 0:
            raise ValueError("scanned_file_count must not be negative.")
        object.__setattr__(self, "expected_trade_dates", expected_trade_dates)
        object.__setattr__(self, "statuses_by_trade_date", statuses_by_trade_date)

    def status_for_trade_date(self, trade_date: str) -> ContinuityDateReadiness:
        normalized_trade_date = _normalize_trade_date(trade_date)
        if normalized_trade_date not in set(self.expected_trade_dates):
            return ContinuityDateReadiness(
                trade_date=normalized_trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=_UNKNOWN_TRADE_DATE_REASON,
                failed_check_names=("continuity_unknown_trade_date",),
            )
        status = self.statuses_by_trade_date.get(normalized_trade_date)
        if status is not None:
            return status
        return ContinuityDateReadiness(
            trade_date=normalized_trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=_MISSING_READINESS_REASON,
            failed_check_names=("continuity_readiness_status_missing",),
        )

    def to_cursor_details(
        self,
        *,
        sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
    ) -> dict[str, object]:
        status_samples = [
            self.status_for_trade_date(trade_date).to_cursor_details()
            for trade_date in self.expected_trade_dates[:sample_limit]
        ]
        expected_start_date, expected_end_date = _date_bounds(
            self.expected_trade_dates
        )
        return {
            "expected_start_date": expected_start_date,
            "expected_end_date": expected_end_date,
            "expected_count": len(self.expected_trade_dates),
            "elapsed_ms": self.elapsed_ms,
            "scanned_file_count": self.scanned_file_count,
            "status_samples": status_samples,
        }


@dataclass(frozen=True)
class ContinuitySelection:
    selected_trade_date: str | None
    selected_status: ContinuityDateReadiness | None
    ready_through_trade_date: str | None
    first_not_ready_trade_date: str | None
    blocked_reason: str | None


def load_expected_trade_date_window(
    connection,
    calendar_path: Path,
    *,
    evaluated_at: datetime,
    min_trade_date: str | None = None,
    same_day_register_start: time | None = None,
    window_limit: int = DEFAULT_CONTINUITY_WINDOW_LIMIT,
) -> ContinuityExpectedDateWindow:
    if window_limit <= 0:
        raise ValueError("window_limit must be greater than zero.")
    normalized_min_trade_date = _normalize_optional_trade_date(
        min_trade_date,
        field_name="min_trade_date",
    )
    today = evaluated_at.date().isoformat()
    rows = connection.execute(
        """
        SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR) AS trade_date
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND (? IS NULL OR CAST(trade_date AS DATE) >= CAST(? AS DATE))
          AND CAST(trade_date AS DATE) <= CAST(? AS DATE)
        ORDER BY CAST(trade_date AS DATE)
        """,
        [
            str(calendar_path),
            normalized_min_trade_date,
            normalized_min_trade_date,
            today,
        ],
    ).fetchall()
    trade_dates = tuple(str(row[0]) for row in rows)
    if (
        same_day_register_start is not None
        and evaluated_at.time() < same_day_register_start
    ):
        trade_dates = tuple(trade_date for trade_date in trade_dates if trade_date != today)
    trade_dates = trade_dates[-window_limit:]
    return ContinuityExpectedDateWindow(
        expected_trade_dates=trade_dates,
        min_trade_date=normalized_min_trade_date,
        max_trade_date=trade_dates[-1] if trade_dates else None,
        evaluated_at=evaluated_at,
        window_limit=window_limit,
    )


def build_registered_gap_status(
    *,
    expected_trade_dates: Sequence[str],
    registered_trade_dates: Iterable[str],
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityRegisteredGapStatus:
    expected_trade_dates = _normalize_trade_dates(
        expected_trade_dates,
        field_name="expected_trade_date",
    )
    registered_trade_date_set = set(
        _normalize_trade_dates(
            registered_trade_dates,
            field_name="registered_trade_date",
        )
    )
    registered_in_window = tuple(
        trade_date
        for trade_date in expected_trade_dates
        if trade_date in registered_trade_date_set
    )
    missing_registered_dates = tuple(
        trade_date
        for trade_date in expected_trade_dates
        if trade_date not in registered_trade_date_set
    )
    sampled_missing_registered_dates = tuple(
        str(value) for value in _sample(missing_registered_dates, sample_limit)
    )
    first_missing_registered_date = (
        missing_registered_dates[0] if missing_registered_dates else None
    )
    return ContinuityRegisteredGapStatus(
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_in_window,
        first_missing_registered_date=first_missing_registered_date,
        missing_registered_dates=sampled_missing_registered_dates,
    )


def select_first_not_ready_trade_date(
    *,
    expected_trade_dates: Sequence[str],
    readiness: ContinuityBatchReadiness,
) -> ContinuitySelection:
    expected_trade_dates = _normalize_trade_dates(
        expected_trade_dates,
        field_name="expected_trade_date",
    )
    ready_through_trade_date: str | None = None

    for trade_date in expected_trade_dates:
        status = readiness.status_for_trade_date(trade_date)
        if status.ready:
            ready_through_trade_date = trade_date
            continue
        if status.reason == _MISSING_READINESS_REASON:
            return ContinuitySelection(
                selected_trade_date=None,
                selected_status=status,
                ready_through_trade_date=ready_through_trade_date,
                first_not_ready_trade_date=trade_date,
                blocked_reason=_MISSING_READINESS_REASON,
            )
        if status.materialized and not status.checks_passed:
            return ContinuitySelection(
                selected_trade_date=None,
                selected_status=status,
                ready_through_trade_date=ready_through_trade_date,
                first_not_ready_trade_date=trade_date,
                blocked_reason="materialized_check_failed",
            )
        return ContinuitySelection(
            selected_trade_date=trade_date,
            selected_status=status,
            ready_through_trade_date=ready_through_trade_date,
            first_not_ready_trade_date=trade_date,
            blocked_reason=None,
        )

    return ContinuitySelection(
        selected_trade_date=None,
        selected_status=None,
        ready_through_trade_date=ready_through_trade_date,
        first_not_ready_trade_date=None,
        blocked_reason=None,
    )


def build_continuity_cursor_details(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    batch_readiness: ContinuityBatchReadiness | None,
    selection: ContinuitySelection | None,
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> dict[str, object]:
    expected_start_date, expected_end_date = _date_bounds(
        expected_window.expected_trade_dates
    )
    details: dict[str, object] = {
        "schema_version": 1,
        "evaluated_at": expected_window.evaluated_at.isoformat(),
        "expected_start_date": expected_start_date,
        "expected_end_date": expected_end_date,
        "expected_count": len(expected_window.expected_trade_dates),
        "registered_count": len(gap_status.registered_trade_dates),
        "first_missing_registered_date": gap_status.first_missing_registered_date,
        "missing_registered_dates": list(gap_status.missing_registered_dates),
        "first_not_ready_trade_date": None,
        "ready_through_trade_date": None,
        "selected_trade_date": None,
        "blocked_reason": None,
        "batch_elapsed_ms": None,
        "scanned_file_count": None,
        "status_samples": [],
    }
    if batch_readiness is not None:
        batch_details = batch_readiness.to_cursor_details(sample_limit=sample_limit)
        details["batch_elapsed_ms"] = batch_details["elapsed_ms"]
        details["scanned_file_count"] = batch_details["scanned_file_count"]
        details["status_samples"] = batch_details["status_samples"]
    if selection is not None:
        details["first_not_ready_trade_date"] = selection.first_not_ready_trade_date
        details["ready_through_trade_date"] = selection.ready_through_trade_date
        details["selected_trade_date"] = selection.selected_trade_date
        details["blocked_reason"] = selection.blocked_reason
    return details
