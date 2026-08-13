"""Bounded lake readiness for canonical CN A-share Gold minute bars."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.cn_a_gold_minute_bars import (
    audit_canonical_gold_minute_relation,
)
from orchestrator.defs.io.cn_a_gold_minute_writer import load_minute_source_codes
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
)

PathBuilder = Callable[[Path, int, str], Path]
ExpectedCodeProvider = Callable[[str], Sequence[object]]


def batch_canonical_gold_minute_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    target_path_builder: PathBuilder,
    source_path_builder: PathBuilder,
    check_names: Sequence[str],
    expected_code_provider: ExpectedCodeProvider | None = None,
    asset_family: str,
) -> ContinuityBatchReadiness:
    started_at = perf_counter()
    expected = tuple(str(value) for value in expected_trade_dates)
    if len(expected) > 10:
        raise ValueError("canonical Gold minute readiness window exceeds 10 dates")
    if len(check_names) != len(CN_A_GOLD_MINUTE_FREQS):
        raise ValueError("canonical Gold minute check-name count must equal 7")
    registered = {str(value) for value in registered_trade_days}
    statuses: dict[str, ContinuityDateReadiness] = {}
    scanned_file_count = 0

    for trade_date in expected:
        target_paths = tuple(
            target_path_builder(lake_root, freq, trade_date)
            for freq in CN_A_GOLD_MINUTE_FREQS
        )
        existing_paths = tuple(path for path in target_paths if path.is_file())
        missing_paths = tuple(path for path in target_paths if not path.is_file())
        if trade_date not in registered:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=f"{asset_family} partition is not registered for {trade_date}",
                missing_check_names=tuple(check_names),
                summary={"reason_code": "missing_registered_partition"},
            )
            continue
        if not existing_paths:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=f"{asset_family} Gold files are missing for {trade_date}",
                missing_check_names=tuple(check_names),
                missing_file_paths=tuple(str(path) for path in missing_paths),
                summary={"reason_code": "file_missing", "missing_file_count": 7},
            )
            continue
        if missing_paths:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=f"{asset_family} Gold partition is partially materialized for {trade_date}",
                failed_check_names=tuple(check_names),
                missing_file_paths=tuple(str(path) for path in missing_paths),
                summary={
                    "reason_code": "partial_materialization",
                    "existing_file_count": len(existing_paths),
                    "missing_file_count": len(missing_paths),
                },
            )
            continue

        failed_checks: list[str] = []
        failed_rules: list[str] = []
        checked_row_count = 0
        try:
            for freq, check_name, target_path in zip(
                CN_A_GOLD_MINUTE_FREQS, check_names, target_paths, strict=True
            ):
                source_path = source_path_builder(lake_root, freq, trade_date)
                codes = (
                    tuple(expected_code_provider(trade_date))
                    if expected_code_provider is not None
                    else load_minute_source_codes(connection, source_path)
                )
                audit = audit_canonical_gold_minute_relation(
                    connection,
                    relation_sql=(
                        "SELECT * FROM "
                        f"{read_parquet(target_path, hive_partitioning=False)}"
                    ),
                    target_freq=freq,
                    partition_key=trade_date,
                    expected_codes=codes,
                )
                scanned_file_count += 1
                checked_row_count += audit.row_count
                if not audit.ready:
                    failed_checks.append(check_name)
                    failed_rules.extend(
                        f"{freq}m:{rule}" for rule in audit.failed_rules
                    )
        except Exception as error:  # noqa: BLE001 - readiness must fail closed.
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=f"{asset_family} Gold readiness scan failed for {trade_date}",
                failed_check_names=tuple(check_names),
                summary={
                    "reason_code": "scan_error",
                    "scan_error_type": type(error).__name__,
                    "scanned_file_count": scanned_file_count,
                },
            )
            continue
        if failed_checks:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=f"{asset_family} Gold core checks failed for {trade_date}",
                failed_check_names=tuple(failed_checks),
                summary={
                    "reason_code": "core_check_failed",
                    "failed_rules": failed_rules[:20],
                    "checked_row_count": checked_row_count,
                },
            )
            continue
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=True,
            materialized=True,
            checks_passed=True,
            reason=f"{asset_family} Gold ready for {trade_date}",
            summary={
                "reason_code": "ready",
                "checked_row_count": checked_row_count,
                "scanned_file_count": 7,
            },
        )

    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        scanned_file_count=scanned_file_count,
    )


__all__ = ["batch_canonical_gold_minute_lake_readiness"]
