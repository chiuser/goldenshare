"""Bounded Gold readiness for the daily board technical indicators."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
    batch_gold_dc_daily_technical_audit,
)
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT,
)


def _status_from_audit(audit) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=audit.trade_date,
        ready=audit.passed,
        materialized=audit.materialized,
        checks_passed=audit.passed,
        reason=audit.reason_code,
        failed_check_names=(
            (GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,) if audit.materialized and not audit.passed else ()
        ),
        missing_check_names=(
            (GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,) if not audit.materialized else ()
        ),
        summary={
            "dataset": "gold_dc_daily_technical",
            "checked_row_count": audit.checked_row_count,
            "failed_row_count": audit.failed_row_count,
            "failed_rules": list(audit.failed_rules),
            **dict(audit.metadata),
        },
    )


def batch_gold_dc_daily_technical_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    source_readiness: Mapping[str, object] | None = None,
) -> ContinuityBatchReadiness:
    """Scan at most the configured recent window with one DuckDB connection.

    ``source_readiness`` is supplied by the normal sensor after its bounded
    Silver scan.  It is diagnostic input only; the Gold audit still validates
    the Gold/Silver key and close relationship in the same set-based query.
    """

    started_at = perf_counter()
    expected = tuple(str(value) for value in expected_trade_dates)
    if len(expected) > DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT:
        raise ValueError(
            "gold daily technical readiness window exceeds "
            f"{DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT} trade dates."
        )
    registered = {str(value) for value in registered_trade_days}
    audits = batch_gold_dc_daily_technical_audit(
        connection=connection,
        lake_root=lake_root,
        trade_dates=expected,
    )
    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date in expected:
        audit = audits[trade_date]
        status = _status_from_audit(audit)
        if trade_date not in registered and status.materialized:
            status = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="partition_not_registered",
                failed_check_names=(GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,),
                summary={**dict(status.summary), "registered": False},
            )
        elif trade_date not in registered:
            status = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="partition_not_registered",
                missing_check_names=(GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,),
                summary={**dict(status.summary), "registered": False},
            )
        if source_readiness and trade_date in source_readiness:
            source_status = source_readiness[trade_date]
            status = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=status.ready,
                materialized=status.materialized,
                checks_passed=status.checks_passed,
                reason=status.reason,
                failed_check_names=status.failed_check_names,
                missing_check_names=status.missing_check_names,
                missing_file_paths=status.missing_file_paths,
                summary={
                    **dict(status.summary),
                    "source_ready": bool(getattr(source_status, "ready", False)),
                    "source_reason": str(getattr(source_status, "reason", "")),
                },
            )
        statuses[trade_date] = status

    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        scanned_file_count=sum(
            int(status.materialized) for status in statuses.values()
        ),
    )


__all__ = ["batch_gold_dc_daily_technical_lake_readiness"]
