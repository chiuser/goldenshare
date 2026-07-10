"""DuckDB lake readiness for daily stock nine-turn sensors."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import AbstractSet

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.catalog.lake_assets import (
    RAW_STK_NINETURN_CHECKS,
    SILVER_STOCK_NINETURN_DAILY_CHECKS,
)
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_identity_map_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_EXPECTED_SCHEMA,
    SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA,
    StkNineturnPathPlan,
    StkNineturnPartitionMetrics,
    build_stk_nineturn_path_plan,
    describe_stk_nineturn_parquet_schema,
    load_raw_stk_nineturn_metrics,
    load_silver_stock_nineturn_daily_metrics,
    raw_stk_nineturn_failed_rule_names,
    silver_stock_nineturn_daily_failed_rule_names,
)


_RAW_CONTRACT_RULES = frozenset(
    {
        "partition_date_matches",
        "freq_is_daily",
    }
)
_SILVER_CONTRACT_RULES = frozenset(
    {
        "key_columns_non_null",
        "unique_ts_code_trade_date",
        "canonical_key_unique",
        "partition_date_matches",
        "freq_is_daily",
    }
)
_SILVER_MAPPING_RULES = frozenset(
    {
        "identity_mapping_complete",
        "identity_mapping_exactly_once",
        "market_values_conflict_free",
        "signal_conflicts_have_canonical_source",
    }
)


def _schema_statuses(
    connection,
    *,
    paths_by_trade_date: dict[str, Path],
    expected_schema: tuple[tuple[str, str], ...],
) -> dict[str, bool]:
    return {
        trade_date: (
            describe_stk_nineturn_parquet_schema(connection, path)
            == expected_schema
        )
        for trade_date, path in paths_by_trade_date.items()
        if path.exists()
    }


def _raw_failed_checks(
    metrics: StkNineturnPartitionMetrics,
) -> tuple[str, ...]:
    failed_rules = set(raw_stk_nineturn_failed_rule_names(metrics))
    failed_checks = []
    if metrics.row_count <= 0 or failed_rules & _RAW_CONTRACT_RULES:
        failed_checks.append(RAW_STK_NINETURN_CHECKS[0])
    if failed_rules - _RAW_CONTRACT_RULES:
        failed_checks.append(RAW_STK_NINETURN_CHECKS[1])
    return tuple(failed_checks)


def _silver_failed_checks(
    metrics: StkNineturnPartitionMetrics,
) -> tuple[str, ...]:
    failed_rules = set(silver_stock_nineturn_daily_failed_rule_names(metrics))
    failed_checks = []
    if metrics.row_count <= 0 or failed_rules & _SILVER_CONTRACT_RULES:
        failed_checks.append(SILVER_STOCK_NINETURN_DAILY_CHECKS[0])
    if failed_rules - _SILVER_CONTRACT_RULES:
        failed_checks.append(SILVER_STOCK_NINETURN_DAILY_CHECKS[1])
    return tuple(failed_checks)


def batch_raw_stk_nineturn_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: AbstractSet[str],
    full_semantics: bool = True,
) -> ContinuityBatchReadiness:
    started = perf_counter()
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    registered_trade_days = {str(value) for value in registered_trade_days}
    paths_by_date = {
        trade_date: raw_stk_nineturn_path(lake_root, trade_date)
        for trade_date in expected_trade_dates
    }
    schema_matches = _schema_statuses(
        connection,
        paths_by_trade_date=paths_by_date,
        expected_schema=RAW_STK_NINETURN_EXPECTED_SCHEMA,
    )
    valid_plans = [
        build_stk_nineturn_path_plan(trade_date=trade_date, path=path)
        for trade_date, path in paths_by_date.items()
        if path.exists() and schema_matches.get(trade_date, False)
    ]
    metrics_by_date = (
        load_raw_stk_nineturn_metrics(connection, path_plans=valid_plans)
        if valid_plans
        else {}
    )

    statuses = {}
    for trade_date in expected_trade_dates:
        path = paths_by_date[trade_date]
        if trade_date not in registered_trade_days:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=path.exists(),
                checks_passed=False,
                reason="missing_registered_partition",
                failed_check_names=(RAW_STK_NINETURN_CHECKS[0],),
            )
            continue
        if not path.exists():
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="raw_stk_nineturn_file_missing",
                missing_check_names=RAW_STK_NINETURN_CHECKS,
                missing_file_paths=(str(path),),
            )
            continue
        if not schema_matches.get(trade_date, False):
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="raw_stk_nineturn_schema_failed",
                failed_check_names=(RAW_STK_NINETURN_CHECKS[0],),
            )
            continue
        metrics = metrics_by_date.get(trade_date)
        if metrics is None:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="raw_stk_nineturn_checks_failed",
                failed_check_names=(RAW_STK_NINETURN_CHECKS[0],),
                summary={"row_count": 0},
            )
            continue
        failed_checks = _raw_failed_checks(metrics) if full_semantics else ()
        ready = metrics.row_count > 0 and not failed_checks
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=ready,
            materialized=True,
            checks_passed=ready,
            reason="ready" if ready else "raw_stk_nineturn_checks_failed",
            failed_check_names=failed_checks,
            summary={
                "row_count": metrics.row_count,
                "failed_rule_count": len(
                    raw_stk_nineturn_failed_rule_names(metrics)
                ),
            },
        )

    elapsed_ms = int((perf_counter() - started) * 1000)
    return ContinuityBatchReadiness(
        expected_trade_dates=expected_trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=elapsed_ms,
        scanned_file_count=sum(path.exists() for path in paths_by_date.values()),
    )


def batch_silver_stock_nineturn_daily_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: AbstractSet[str],
    full_semantics: bool = True,
) -> ContinuityBatchReadiness:
    started = perf_counter()
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    registered_trade_days = {str(value) for value in registered_trade_days}
    raw_paths = {
        trade_date: raw_stk_nineturn_path(lake_root, trade_date)
        for trade_date in expected_trade_dates
    }
    silver_paths = {
        trade_date: silver_stock_nineturn_daily_path(lake_root, trade_date)
        for trade_date in expected_trade_dates
    }
    identity_map_path = silver_stock_identity_map_path(lake_root)
    raw_schema_matches = _schema_statuses(
        connection,
        paths_by_trade_date=raw_paths,
        expected_schema=RAW_STK_NINETURN_EXPECTED_SCHEMA,
    )
    silver_schema_matches = _schema_statuses(
        connection,
        paths_by_trade_date=silver_paths,
        expected_schema=SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA,
    )

    if not identity_map_path.exists():
        statuses = {
            trade_date: ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=silver_paths[trade_date].exists(),
                checks_passed=False,
                reason="identity_mapping_missing",
                failed_check_names=(SILVER_STOCK_NINETURN_DAILY_CHECKS[1],),
                missing_file_paths=(str(identity_map_path),),
            )
            for trade_date in expected_trade_dates
        }
        return ContinuityBatchReadiness(
            expected_trade_dates=expected_trade_dates,
            statuses_by_trade_date=statuses,
            elapsed_ms=int((perf_counter() - started) * 1000),
            scanned_file_count=sum(
                path.exists() for path in (*raw_paths.values(), *silver_paths.values())
            ),
        )

    raw_plans = [
        build_stk_nineturn_path_plan(
            trade_date=trade_date,
            path=path,
        )
        for trade_date, path in raw_paths.items()
        if path.exists() and raw_schema_matches.get(trade_date, False)
    ]
    silver_plans = [
        build_stk_nineturn_path_plan(
            trade_date=trade_date,
            path=path,
        )
        if path.exists() and silver_schema_matches.get(trade_date, False)
        else StkNineturnPathPlan(
            trade_date=trade_date,
            path=path,
            file_exists=False,
        )
        for trade_date, path in silver_paths.items()
    ]
    metrics_by_date = (
        load_silver_stock_nineturn_daily_metrics(
            connection,
            raw_path_plans=raw_plans,
            silver_path_plans=silver_plans,
            identity_map_path=identity_map_path,
        )
        if raw_plans
        else {}
    )

    statuses = {}
    for trade_date in expected_trade_dates:
        raw_path = raw_paths[trade_date]
        silver_path = silver_paths[trade_date]
        if trade_date not in registered_trade_days:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=silver_path.exists(),
                checks_passed=False,
                reason="missing_registered_partition",
                failed_check_names=(SILVER_STOCK_NINETURN_DAILY_CHECKS[0],),
            )
            continue
        if not raw_path.exists() or not raw_schema_matches.get(trade_date, False):
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=silver_path.exists(),
                checks_passed=False,
                reason="raw_stk_nineturn_not_ready",
                failed_check_names=(SILVER_STOCK_NINETURN_DAILY_CHECKS[1],),
                missing_file_paths=(str(raw_path),) if not raw_path.exists() else (),
            )
            continue
        metrics = metrics_by_date.get(trade_date)
        if metrics is None:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=silver_path.exists(),
                checks_passed=False,
                reason="identity_mapping_not_ready",
                failed_check_names=(SILVER_STOCK_NINETURN_DAILY_CHECKS[1],),
            )
            continue
        failed_rules = set(silver_stock_nineturn_daily_failed_rule_names(metrics))
        mapping_failed = bool(failed_rules & _SILVER_MAPPING_RULES)
        if mapping_failed:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=silver_path.exists(),
                checks_passed=False,
                reason="identity_mapping_not_ready",
                failed_check_names=(SILVER_STOCK_NINETURN_DAILY_CHECKS[1],),
                summary={
                    "unmapped_source_code_count": metrics.unmapped_source_code_count,
                    "market_value_conflict_key_count": (
                        metrics.market_value_conflict_key_count
                    ),
                    "unresolved_signal_conflict_count": (
                        metrics.unresolved_count_signal_conflict_key_count
                    ),
                },
            )
            continue
        if not silver_path.exists():
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="silver_stock_nineturn_daily_file_missing",
                missing_check_names=SILVER_STOCK_NINETURN_DAILY_CHECKS,
                missing_file_paths=(str(silver_path),),
            )
            continue
        if not silver_schema_matches.get(trade_date, False):
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="silver_stock_nineturn_daily_schema_failed",
                failed_check_names=(SILVER_STOCK_NINETURN_DAILY_CHECKS[0],),
            )
            continue
        failed_checks = _silver_failed_checks(metrics) if full_semantics else ()
        ready = metrics.row_count > 0 and not failed_checks
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=ready,
            materialized=True,
            checks_passed=ready,
            reason=(
                "ready"
                if ready
                else "silver_stock_nineturn_daily_checks_failed"
            ),
            failed_check_names=failed_checks,
            summary={
                "source_row_count": metrics.source_row_count,
                "output_row_count": metrics.row_count,
                "expected_output_row_count": metrics.expected_output_row_count,
                "failed_rule_count": len(failed_rules),
            },
        )

    elapsed_ms = int((perf_counter() - started) * 1000)
    return ContinuityBatchReadiness(
        expected_trade_dates=expected_trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=elapsed_ms,
        scanned_file_count=(
            sum(path.exists() for path in raw_paths.values())
            + sum(path.exists() for path in silver_paths.values())
            + 1
        ),
    )
