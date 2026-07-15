from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.stk_mins_migration import _check_success_count
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    StkMinsQfqBootstrapCheckAudit,
    StkMinsQfqBootstrapPartitionAudit,
    _batch_gold_counts,
    _latest_materialization,
    _read_parquet_paths,
    _sample_partition_keys,
    _values_sql,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_history import (
    GOLD_STK_MINS_QFQ_DERIVED_EVENT_COUNT_PER_ASSET_PARTITION,
    STK_MINS_QFQ_HISTORY_START_DATE,
    StkMinsQfqDerivedHistoryBatch,
    plan_stk_mins_qfq_derived_history,
)
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, gold_stk_mins_qfq_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.stk_mins import qfq_source_freq_for_derived_freq
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)
from orchestrator.defs.stk_mins_qfq import (
    _derived_window_completion_predicate,
    _derived_window_rows_sql,
    build_gold_stk_mins_qfq_derived_coverage_sql,
)


GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS = {
    90: dg.AssetKey("gold_stk_mins_qfq_90m"),
    120: dg.AssetKey("gold_stk_mins_qfq_120m"),
}
GOLD_STK_MINS_QFQ_DERIVED_CHECKS = (
    stk_mins_checks.GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES
)


@dataclass(frozen=True)
class StkMinsQfqDerivedBootstrapEventPlan:
    selected_partition_keys: tuple[str, ...]
    selected_target_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    batches: tuple[StkMinsQfqDerivedHistoryBatch, ...]
    planned_source_file_count: int
    planned_source_row_count: int
    planned_source_stock_day_count: int
    planned_target_file_count: int
    planned_target_row_count: int
    existing_target_file_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    materialized_partition_counts: Mapping[int, int]
    check_success_counts: Mapping[str, int]

    @property
    def asset_partition_count(self) -> int:
        return len(self.selected_partition_keys) * len(self.selected_target_freqs)

    @property
    def planned_event_count(self) -> int:
        return (
            self.asset_partition_count
            * GOLD_STK_MINS_QFQ_DERIVED_EVENT_COUNT_PER_ASSET_PARTITION
        )


@dataclass(frozen=True)
class StkMinsQfqDerivedBootstrapEventReport:
    plan: StkMinsQfqDerivedBootstrapEventPlan
    dry_run: bool
    partition_audits: tuple[StkMinsQfqBootstrapPartitionAudit, ...]
    reported_asset_partitions: tuple[tuple[int, str], ...]
    skipped_ready_asset_partitions: tuple[tuple[int, str], ...]
    reported_event_count: int

    @property
    def failed_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)


@dataclass(frozen=True)
class StkMinsQfqDerivedFinalAuditReport:
    selected_partition_count: int
    selected_target_freqs: tuple[int, ...]
    planned_source_file_count: int
    planned_source_row_count: int
    planned_target_file_count: int
    existing_target_file_count: int
    missing_input_count: int
    materialized_partition_counts: Mapping[int, int]
    check_success_counts: Mapping[str, int]
    check_success_counts_skipped: bool
    sample_readiness: Mapping[str, bool]


def plan_stk_mins_qfq_derived_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
    include_check_success_counts: bool = True,
) -> StkMinsQfqDerivedBootstrapEventPlan:
    """Plan derived gold qfq runless events without per-partition deep scans."""

    history_plan = plan_stk_mins_qfq_derived_history(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
    )
    selected_keys = set(history_plan.selected_partition_keys)
    materialized_counts = {
        freq: len(
            selected_keys.intersection(
                instance.get_materialized_partitions(asset_key)
            )
        )
        for freq, asset_key in GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS.items()
        if freq in history_plan.selected_target_freqs
    }
    check_counts: dict[str, int] = {}
    if include_check_success_counts:
        for freq in history_plan.selected_target_freqs:
            asset_key = GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[freq]
            for check_name in GOLD_STK_MINS_QFQ_DERIVED_CHECKS:
                key = f"{asset_key.to_user_string()}:{check_name}"
                check_counts[key] = _check_success_count(
                    instance,
                    dg.AssetCheckKey(asset_key, check_name),
                )
    return StkMinsQfqDerivedBootstrapEventPlan(
        selected_partition_keys=history_plan.selected_partition_keys,
        selected_target_freqs=history_plan.selected_target_freqs,
        selected_years=history_plan.selected_years,
        batches=history_plan.batches,
        planned_source_file_count=history_plan.planned_source_file_count,
        planned_source_row_count=history_plan.planned_source_row_count,
        planned_source_stock_day_count=history_plan.planned_source_stock_day_count,
        planned_target_file_count=history_plan.planned_target_file_count,
        planned_target_row_count=history_plan.planned_target_row_count,
        existing_target_file_count=history_plan.existing_target_file_count,
        missing_input_count=history_plan.missing_input_count,
        missing_input_samples=history_plan.missing_input_samples,
        materialized_partition_counts=materialized_counts,
        check_success_counts=check_counts,
    )


def report_stk_mins_qfq_derived_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    dry_run: bool = False,
    skip_existing_ready: bool = False,
) -> StkMinsQfqDerivedBootstrapEventReport:
    plan = plan_stk_mins_qfq_derived_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb,
        include_check_success_counts=False,
    )
    if plan.missing_input_count:
        raise FileNotFoundError(
            "Gold qfq derived event inputs are missing: "
            f"{tuple(plan.missing_input_samples)}"
        )
    if plan.existing_target_file_count != plan.planned_target_file_count:
        raise FileNotFoundError(
            "Gold qfq derived target files are incomplete: "
            f"existing={plan.existing_target_file_count}, "
            f"planned={plan.planned_target_file_count}."
        )

    audits: list[StkMinsQfqBootstrapPartitionAudit] = []
    skipped: list[tuple[int, str]] = []
    reported: list[tuple[int, str]] = []
    event_count = 0
    for batch in plan.batches:
        pending_keys: list[str] = []
        for partition_key in batch.partition_keys:
            if skip_existing_ready and _gold_qfq_derived_partition_ready(
                instance,
                freq=batch.target_freq,
                partition_key=partition_key,
            ):
                skipped.append((batch.target_freq, partition_key))
            else:
                pending_keys.append(partition_key)
        if not pending_keys:
            continue

        batch_audits = audit_stk_mins_qfq_derived_bootstrap_batch(
            lake_root=lake_root,
            duckdb=duckdb,
            batch=StkMinsQfqDerivedHistoryBatch(
                target_freq=batch.target_freq,
                source_freq=batch.source_freq,
                year=batch.year,
                partition_keys=tuple(pending_keys),
            ),
        )
        failed_audits = tuple(audit for audit in batch_audits if not audit.passed)
        if failed_audits:
            samples = {
                f"{audit.freq}:{audit.partition_key}": audit.failed_check_names
                for audit in failed_audits[:10]
            }
            raise ValueError(f"stk_mins qfq derived bootstrap audit failed: {samples}")

        audits.extend(batch_audits)
        if not dry_run:
            for audit in batch_audits:
                event_count += _report_stk_mins_qfq_derived_partition_events(
                    instance,
                    audit,
                )
                reported.append((audit.freq, audit.partition_key))

    return StkMinsQfqDerivedBootstrapEventReport(
        plan=plan,
        dry_run=dry_run,
        partition_audits=tuple(audits),
        reported_asset_partitions=tuple(reported),
        skipped_ready_asset_partitions=tuple(skipped),
        reported_event_count=0 if dry_run else event_count,
    )


def audit_stk_mins_qfq_derived_bootstrap_batch(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    batch: StkMinsQfqDerivedHistoryBatch,
) -> tuple[StkMinsQfqBootstrapPartitionAudit, ...]:
    """Audit one target freq/year batch once, then fan out per-date checks."""

    del duckdb
    asset_key = GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[int(batch.target_freq)]
    output_root_path = gold_stk_mins_qfq_path(
        lake_root,
        int(batch.target_freq),
        "{ts_code}",
        batch.year,
    ).parents[2]
    source_paths = _source_qfq_paths_for_batch(lake_root, batch)
    if not source_paths:
        return _derived_input_failure_audits(
            batch=batch,
            asset_key=asset_key,
            output_root_path=output_root_path,
            missing_path=gold_stk_mins_qfq_path(
                lake_root,
                int(batch.source_freq),
                "{ts_code}",
                batch.year,
            ).parents[2],
        )

    expected_identity_sql = build_gold_stk_mins_qfq_derived_coverage_sql(
        source_qfq_paths=source_paths,
        target_freq=batch.target_freq,
        partition_keys=batch.partition_keys,
    )
    with connect_configured_duckdb() as connection:
        diagnostics_by_date = _batch_derived_diagnostics_counts(
            connection,
            batch=batch,
            source_paths=source_paths,
        )
        expected_paths_by_date = _expected_derived_gold_paths_by_date(
            connection,
            lake_root=lake_root,
            target_freq=batch.target_freq,
            expected_identity_sql=expected_identity_sql,
        )
        all_expected_paths = tuple(
            dict.fromkeys(
                path for paths in expected_paths_by_date.values() for path in paths
            )
        )
        existing_paths = tuple(path for path in all_expected_paths if path.exists())
        missing_paths_by_date = {
            partition_key: tuple(
                path
                for path in expected_paths_by_date.get(partition_key, ())
                if not path.exists()
            )
            for partition_key in batch.partition_keys
        }
        schema_mismatch_count, observed_schema, schema_error = (
            stk_mins_checks._gold_qfq_schema_mismatch_count(
                connection,
                existing_paths,
            )
        )
        gold_counts = _batch_gold_counts(
            connection,
            partition_keys=batch.partition_keys,
            gold_paths=existing_paths,
            freq=batch.target_freq,
        )
        identity_counts = _batch_derived_identity_coverage_counts(
            connection,
            partition_keys=batch.partition_keys,
            gold_paths=existing_paths,
            expected_identity_sql=expected_identity_sql,
        )

    audits: list[StkMinsQfqBootstrapPartitionAudit] = []
    for partition_key in batch.partition_keys:
        expected_paths = expected_paths_by_date.get(partition_key, ())
        missing_paths = missing_paths_by_date.get(partition_key, ())
        existing_file_count = len(expected_paths) - len(missing_paths)
        diagnostics = diagnostics_by_date.get(partition_key, {})
        gold = gold_counts.get(partition_key, {})
        identity = identity_counts.get(partition_key, {})
        counts = stk_mins_checks.GoldStkMinsQfqDerivedCheckCounts(
            source_freq=batch.source_freq,
            source_file_count=len(source_paths),
            source_row_count=int(diagnostics.get("source_row_count", 0)),
            source_stock_day_count=int(
                diagnostics.get("source_stock_day_count", 0)
            ),
            expected_window_count=int(diagnostics.get("expected_window_count", 0)),
            generated_window_count=int(diagnostics.get("generated_window_count", 0)),
            incomplete_window_count=int(
                diagnostics.get("incomplete_window_count", 0)
            ),
            exchange_mismatch_window_count=int(
                diagnostics.get("exchange_mismatch_window_count", 0)
            ),
            expected_file_count=len(expected_paths),
            existing_file_count=existing_file_count,
            missing_file_count=len(missing_paths),
            gold_target_row_count=int(gold.get("gold_target_row_count", 0)),
            schema_mismatch_file_count=int(schema_mismatch_count),
            path_mismatch_row_count=int(gold.get("path_mismatch_row_count", 0)),
            duplicate_key_count=int(gold.get("duplicate_key_count", 0)),
            invalid_price_row_count=int(gold.get("invalid_price_row_count", 0)),
            missing_gold_identity_row_count=int(
                identity.get("missing_gold_identity_row_count", 0)
            ),
            unexpected_gold_identity_row_count=int(
                identity.get("unexpected_gold_identity_row_count", 0)
            ),
            exchange_mismatch_row_count=int(
                identity.get("exchange_mismatch_row_count", 0)
            ),
        )
        results = stk_mins_checks._gold_qfq_derived_check_results(
            asset_key=asset_key,
            partition_key=partition_key,
            freq=batch.target_freq,
            counts=counts,
            output_root_path=output_root_path,
            input_file_paths=source_paths,
            missing_gold_paths=missing_paths,
            observed_schema=observed_schema,
            schema_error=schema_error,
            samples={},
        )
        checks = tuple(
            StkMinsQfqBootstrapCheckAudit(
                check_name=str(result.check_name),
                passed=bool(result.passed),
                metadata=result.metadata or {},
            )
            for result in results
        )
        audits.append(
            StkMinsQfqBootstrapPartitionAudit(
                freq=batch.target_freq,
                partition_key=partition_key,
                asset_key=asset_key,
                output_root_path=output_root_path,
                passed=all(check.passed for check in checks),
                row_count=counts.gold_target_row_count,
                observed_columns=tuple(observed_schema),
                expected_file_count=counts.expected_file_count,
                existing_file_count=counts.existing_file_count,
                checks=checks,
            )
        )
    return tuple(audits)


def audit_stk_mins_qfq_derived_final_state(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
    include_check_success_counts: bool = True,
) -> StkMinsQfqDerivedFinalAuditReport:
    plan = plan_stk_mins_qfq_derived_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
        include_check_success_counts=include_check_success_counts,
    )
    sample_readiness: dict[str, bool] = {}
    for partition_key in _sample_partition_keys(plan.selected_partition_keys):
        for freq in plan.selected_target_freqs:
            status = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[freq],
                    GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
                ),
                partition_key=partition_key,
            )
            sample_readiness[f"{freq}:{partition_key}"] = status.ready
    return StkMinsQfqDerivedFinalAuditReport(
        selected_partition_count=len(plan.selected_partition_keys),
        selected_target_freqs=plan.selected_target_freqs,
        planned_source_file_count=plan.planned_source_file_count,
        planned_source_row_count=plan.planned_source_row_count,
        planned_target_file_count=plan.planned_target_file_count,
        existing_target_file_count=plan.existing_target_file_count,
        missing_input_count=plan.missing_input_count,
        materialized_partition_counts=plan.materialized_partition_counts,
        check_success_counts=plan.check_success_counts,
        check_success_counts_skipped=not include_check_success_counts,
        sample_readiness=sample_readiness,
    )


def _batch_derived_diagnostics_counts(
    connection,
    *,
    batch: StkMinsQfqDerivedHistoryBatch,
    source_paths: Sequence[Path],
) -> dict[str, dict[str, int]]:
    source = _read_parquet_paths(source_paths)
    selected_values_sql = _values_sql(batch.partition_keys)
    window_rows_sql = _derived_window_rows_sql(batch.target_freq)
    completion_predicate = _derived_window_completion_predicate(
        batch.target_freq,
        source_row_count_column="coalesce(actual_windows.source_row_count, 0)",
        window_id_column="expected_windows.window_id",
    )
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS ({selected_values_sql}),
        source_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(exchange AS VARCHAR) AS exchange
          FROM {source}
          WHERE CAST(freq AS INTEGER) = {batch.source_freq}
        ),
        selected_source_rows AS (
          SELECT source_rows.*
          FROM source_rows
          INNER JOIN selected
            ON source_rows.partition_key = selected.partition_key
        ),
        source_stock_days AS (
          SELECT DISTINCT partition_key, ts_code, trade_date
          FROM selected_source_rows
        ),
        window_map AS (
          {window_rows_sql}
        ),
        expected_windows AS (
          SELECT
            source_stock_days.partition_key,
            source_stock_days.ts_code,
            source_stock_days.trade_date,
            window_map.window_id,
            max(window_map.target_time) AS target_time,
            count(*) AS expected_source_row_count
          FROM source_stock_days
          CROSS JOIN window_map
          GROUP BY
            source_stock_days.partition_key,
            source_stock_days.ts_code,
            source_stock_days.trade_date,
            window_map.window_id
        ),
        windowed_rows AS (
          SELECT
            selected_source_rows.partition_key,
            selected_source_rows.ts_code,
            selected_source_rows.trade_date,
            selected_source_rows.trade_time,
            selected_source_rows.exchange,
            window_map.window_id,
            window_map.target_time
          FROM selected_source_rows
          INNER JOIN window_map
            ON strftime(selected_source_rows.trade_time, '%H:%M:%S')
             = window_map.source_time
        ),
        actual_windows AS (
          SELECT
            partition_key,
            ts_code,
            trade_date,
            window_id,
            max(trade_time) AS trade_time,
            max(target_time) AS target_time,
            count(*) AS source_row_count,
            count(DISTINCT exchange) AS exchange_count
          FROM windowed_rows
          GROUP BY partition_key, ts_code, trade_date, window_id
        ),
        window_status AS (
          SELECT
            expected_windows.partition_key,
            expected_windows.window_id,
            coalesce(actual_windows.source_row_count, 0) AS source_row_count,
            coalesce(actual_windows.exchange_count, 0) AS exchange_count,
            actual_windows.trade_time,
            expected_windows.target_time,
            actual_windows.source_row_count IS NOT NULL
              AND strftime(actual_windows.trade_time, '%H:%M:%S')
                = expected_windows.target_time
              AND ({completion_predicate}) AS generated
          FROM expected_windows
          LEFT JOIN actual_windows
            ON expected_windows.partition_key = actual_windows.partition_key
           AND expected_windows.ts_code = actual_windows.ts_code
           AND expected_windows.trade_date = actual_windows.trade_date
           AND expected_windows.window_id = actual_windows.window_id
        ),
        source_aggregates AS (
          SELECT
            partition_key,
            count(*) AS source_row_count,
            count(DISTINCT ts_code || '|' || CAST(trade_date AS VARCHAR))
              AS source_stock_day_count
          FROM selected_source_rows
          GROUP BY partition_key
        ),
        window_aggregates AS (
          SELECT
            partition_key,
            count(*) AS expected_window_count,
            count(*) FILTER (WHERE generated AND exchange_count = 1)
              AS generated_window_count,
            count(*) FILTER (WHERE source_row_count > 0 AND NOT generated)
              AS incomplete_window_count,
            count(*) FILTER (WHERE exchange_count > 1)
              AS exchange_mismatch_window_count
          FROM window_status
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(source_aggregates.source_row_count, 0)
            AS source_row_count,
          coalesce(source_aggregates.source_stock_day_count, 0)
            AS source_stock_day_count,
          coalesce(window_aggregates.expected_window_count, 0)
            AS expected_window_count,
          coalesce(window_aggregates.generated_window_count, 0)
            AS generated_window_count,
          coalesce(window_aggregates.incomplete_window_count, 0)
            AS incomplete_window_count,
          coalesce(window_aggregates.exchange_mismatch_window_count, 0)
            AS exchange_mismatch_window_count
        FROM selected
        LEFT JOIN source_aggregates
          ON selected.partition_key = source_aggregates.partition_key
        LEFT JOIN window_aggregates
          ON selected.partition_key = window_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "source_row_count": int(source_row_count),
            "source_stock_day_count": int(source_stock_day_count),
            "expected_window_count": int(expected_window_count),
            "generated_window_count": int(generated_window_count),
            "incomplete_window_count": int(incomplete_window_count),
            "exchange_mismatch_window_count": int(exchange_mismatch_window_count),
        }
        for (
            partition_key,
            source_row_count,
            source_stock_day_count,
            expected_window_count,
            generated_window_count,
            incomplete_window_count,
            exchange_mismatch_window_count,
        ) in rows
    }


def _expected_derived_gold_paths_by_date(
    connection,
    *,
    lake_root: Path,
    target_freq: int,
    expected_identity_sql: str,
) -> dict[str, tuple[Path, ...]]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT
          strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
          CAST(ts_code AS VARCHAR) AS ts_code,
          strftime(CAST(trade_date AS DATE), '%Y') AS year
        FROM ({expected_identity_sql})
        ORDER BY partition_key, ts_code
        """
    ).fetchall()
    paths_by_date: dict[str, list[Path]] = {}
    for partition_key, ts_code, year in rows:
        paths_by_date.setdefault(str(partition_key), []).append(
            gold_stk_mins_qfq_path(lake_root, target_freq, str(ts_code), str(year))
        )
    return {key: tuple(paths) for key, paths in paths_by_date.items()}


def _batch_derived_identity_coverage_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    gold_paths: Sequence[Path],
    expected_identity_sql: str,
) -> dict[str, dict[str, int]]:
    if not gold_paths:
        return {
            partition_key: {
                "missing_gold_identity_row_count": 0,
                "unexpected_gold_identity_row_count": 0,
                "exchange_mismatch_row_count": 0,
            }
            for partition_key in partition_keys
        }
    gold_source = _read_parquet_paths(gold_paths)
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS ({_values_sql(partition_keys)}),
        gold_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(exchange AS VARCHAR) AS exchange
          FROM {gold_source}
        ),
        target_gold_rows AS (
          SELECT gold_rows.*
          FROM gold_rows
          INNER JOIN selected
            ON gold_rows.partition_key = selected.partition_key
        ),
        expected_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(exchange AS VARCHAR) AS exchange
          FROM ({expected_identity_sql})
        ),
        compared_rows AS (
          SELECT
            coalesce(target_gold_rows.partition_key, expected_rows.partition_key)
              AS partition_key,
            target_gold_rows.exchange AS gold_exchange,
            expected_rows.exchange AS expected_exchange,
            target_gold_rows.ts_code IS NULL AS missing_gold_row,
            expected_rows.ts_code IS NULL AS unexpected_gold_row
          FROM target_gold_rows
          FULL OUTER JOIN expected_rows
            ON target_gold_rows.partition_key = expected_rows.partition_key
           AND target_gold_rows.ts_code = expected_rows.ts_code
           AND target_gold_rows.trade_time = expected_rows.trade_time
        ),
        identity_aggregates AS (
          SELECT
            partition_key,
            count(*) FILTER (WHERE missing_gold_row)
              AS missing_gold_identity_row_count,
            count(*) FILTER (WHERE unexpected_gold_row)
              AS unexpected_gold_identity_row_count,
            count(*) FILTER (
              WHERE NOT missing_gold_row
                AND NOT unexpected_gold_row
                AND gold_exchange IS DISTINCT FROM expected_exchange
            ) AS exchange_mismatch_row_count
          FROM compared_rows
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(identity_aggregates.missing_gold_identity_row_count, 0)
            AS missing_gold_identity_row_count,
          coalesce(identity_aggregates.unexpected_gold_identity_row_count, 0)
            AS unexpected_gold_identity_row_count,
          coalesce(identity_aggregates.exchange_mismatch_row_count, 0)
            AS exchange_mismatch_row_count
        FROM selected
        LEFT JOIN identity_aggregates
          ON selected.partition_key = identity_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "missing_gold_identity_row_count": int(missing_gold_identity_row_count),
            "unexpected_gold_identity_row_count": int(
                unexpected_gold_identity_row_count
            ),
            "exchange_mismatch_row_count": int(exchange_mismatch_row_count),
        }
        for (
            partition_key,
            missing_gold_identity_row_count,
            unexpected_gold_identity_row_count,
            exchange_mismatch_row_count,
        ) in rows
    }


def _derived_input_failure_audits(
    *,
    batch: StkMinsQfqDerivedHistoryBatch,
    asset_key: dg.AssetKey,
    output_root_path: Path,
    missing_path: Path,
) -> tuple[StkMinsQfqBootstrapPartitionAudit, ...]:
    audits: list[StkMinsQfqBootstrapPartitionAudit] = []
    for partition_key in batch.partition_keys:
        results = stk_mins_checks._gold_qfq_input_failure_results(
            asset_key=asset_key,
            missing_path=missing_path,
            partition_key=partition_key,
            freq=batch.target_freq,
            check_names=GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
        )
        checks = tuple(
            StkMinsQfqBootstrapCheckAudit(
                check_name=str(result.check_name),
                passed=bool(result.passed),
                metadata=result.metadata or {},
            )
            for result in results
        )
        audits.append(
            StkMinsQfqBootstrapPartitionAudit(
                freq=batch.target_freq,
                partition_key=partition_key,
                asset_key=asset_key,
                output_root_path=output_root_path,
                passed=False,
                row_count=0,
                observed_columns=(),
                expected_file_count=0,
                existing_file_count=0,
                checks=checks,
            )
        )
    return tuple(audits)


def _gold_qfq_derived_partition_ready(
    instance: dg.DagsterInstance,
    *,
    freq: int,
    partition_key: str,
) -> bool:
    status = asset_readiness_status(
        instance,
        AssetReadinessSpec(
            GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[freq],
            GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
        ),
        partition_key=partition_key,
    )
    return status.ready


def report_stk_mins_qfq_derived_partition_events(
    *,
    instance: dg.DagsterInstance,
    audit: StkMinsQfqBootstrapPartitionAudit,
    source_method: str = "stk_mins_qfq_derived_history_generation",
    extra_metadata: Mapping[str, object] | None = None,
) -> int:
    return _report_stk_mins_qfq_derived_partition_events(
        instance,
        audit,
        source_method=source_method,
        extra_metadata=extra_metadata,
    )


def _report_stk_mins_qfq_derived_partition_events(
    instance: dg.DagsterInstance,
    audit: StkMinsQfqBootstrapPartitionAudit,
    *,
    source_method: str = "stk_mins_qfq_derived_history_generation",
    extra_metadata: Mapping[str, object] | None = None,
) -> int:
    source_freq = qfq_source_freq_for_derived_freq(audit.freq)
    materialization_extra_metadata = {
        "source_method": source_method,
        "bootstrap_event_backfill": True,
        "freq": audit.freq,
        "source_freq": source_freq,
        "partition_key": audit.partition_key,
        "expected_file_count": audit.expected_file_count,
        "existing_file_count": audit.existing_file_count,
    }
    if extra_metadata:
        materialization_extra_metadata.update(extra_metadata)
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=audit.asset_key,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.output_root_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata=materialization_extra_metadata,
            ),
        )
    )
    materialization = _latest_materialization(
        instance,
        audit.asset_key,
        audit.partition_key,
    )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 1
    for check in audit.checks:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=audit.asset_key,
                check_name=check.check_name,
                passed=check.passed,
                metadata=check.metadata,
                blocking=True,
                partition=audit.partition_key,
                target_materialization_data=target,
            )
        )
        event_count += 1
    return event_count


def _source_qfq_paths_for_batch(
    lake_root: Path,
    batch: StkMinsQfqDerivedHistoryBatch,
) -> tuple[Path, ...]:
    source_root = gold_stk_mins_qfq_path(
        lake_root,
        batch.source_freq,
        "{ts_code}",
        batch.year,
    ).parents[2]
    return tuple(sorted(source_root.glob(f"ts_code=*/year={batch.year}/part-000.parquet")))
