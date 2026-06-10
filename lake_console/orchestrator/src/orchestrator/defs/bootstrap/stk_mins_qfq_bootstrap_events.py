from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.bootstrap.stk_mins_migration import _check_success_count
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
    StkMinsQfqHistoryBatch,
    _silver_paths_for_batch,
    _trade_adj_factor_paths_for_keys,
    plan_stk_mins_qfq_history,
)
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)
from orchestrator.defs.stk_mins_qfq import build_daily_qfq_select_sql


GOLD_STK_MINS_QFQ_ASSET_KEYS = {
    freq: dg.AssetKey(f"gold_stk_mins_qfq_{freq}m") for freq in STK_MINS_FREQS
}
GOLD_STK_MINS_QFQ_CHECKS = stk_mins_checks.GOLD_STK_MINS_QFQ_CHECK_NAMES
GOLD_STK_MINS_QFQ_EVENT_COUNT_PER_ASSET_PARTITION = 1 + len(
    GOLD_STK_MINS_QFQ_CHECKS
)


@dataclass(frozen=True)
class StkMinsQfqBootstrapCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class StkMinsQfqBootstrapPartitionAudit:
    freq: int
    partition_key: str
    asset_key: dg.AssetKey
    output_root_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    expected_file_count: int | None
    existing_file_count: int | None
    checks: tuple[StkMinsQfqBootstrapCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class StkMinsQfqBootstrapEventPlan:
    selected_partition_keys: tuple[str, ...]
    selected_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    batches: tuple[StkMinsQfqHistoryBatch, ...]
    planned_target_file_count: int
    existing_target_file_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    materialized_partition_counts: Mapping[int, int]
    check_success_counts: Mapping[str, int]

    @property
    def asset_partition_count(self) -> int:
        return len(self.selected_partition_keys) * len(self.selected_freqs)

    @property
    def planned_event_count(self) -> int:
        return (
            self.asset_partition_count
            * GOLD_STK_MINS_QFQ_EVENT_COUNT_PER_ASSET_PARTITION
        )


@dataclass(frozen=True)
class StkMinsQfqBootstrapEventReport:
    plan: StkMinsQfqBootstrapEventPlan
    dry_run: bool
    partition_audits: tuple[StkMinsQfqBootstrapPartitionAudit, ...]
    reported_asset_partitions: tuple[tuple[int, str], ...]
    skipped_ready_asset_partitions: tuple[tuple[int, str], ...]
    reported_event_count: int

    @property
    def failed_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)


@dataclass(frozen=True)
class StkMinsQfqFinalAuditReport:
    selected_partition_count: int
    selected_freqs: tuple[int, ...]
    planned_target_file_count: int
    existing_target_file_count: int
    missing_input_count: int
    materialized_partition_counts: Mapping[int, int]
    check_success_counts: Mapping[str, int]
    sample_readiness: Mapping[str, bool]


def plan_stk_mins_qfq_bootstrap_events(
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
) -> StkMinsQfqBootstrapEventPlan:
    """Plan gold qfq runless events without per-partition check evaluation."""

    history_plan = plan_stk_mins_qfq_history(
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
        for freq, asset_key in GOLD_STK_MINS_QFQ_ASSET_KEYS.items()
        if freq in history_plan.selected_freqs
    }
    check_counts: dict[str, int] = {}
    for freq in history_plan.selected_freqs:
        asset_key = GOLD_STK_MINS_QFQ_ASSET_KEYS[freq]
        for check_name in GOLD_STK_MINS_QFQ_CHECKS:
            key = f"{asset_key.to_user_string()}:{check_name}"
            check_counts[key] = _check_success_count(
                instance,
                dg.AssetCheckKey(asset_key, check_name),
            )
    return StkMinsQfqBootstrapEventPlan(
        selected_partition_keys=history_plan.selected_partition_keys,
        selected_freqs=history_plan.selected_freqs,
        selected_years=history_plan.selected_years,
        batches=history_plan.batches,
        planned_target_file_count=history_plan.planned_target_file_count,
        existing_target_file_count=history_plan.existing_target_file_count,
        missing_input_count=history_plan.missing_input_count,
        missing_input_samples=history_plan.missing_input_samples,
        materialized_partition_counts=materialized_counts,
        check_success_counts=check_counts,
    )


def report_stk_mins_qfq_bootstrap_events(
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
) -> StkMinsQfqBootstrapEventReport:
    plan = plan_stk_mins_qfq_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb,
    )
    if plan.missing_input_count:
        raise FileNotFoundError(
            "Gold qfq event inputs are missing: "
            f"{tuple(plan.missing_input_samples)}"
        )
    if plan.existing_target_file_count != plan.planned_target_file_count:
        raise FileNotFoundError(
            "Gold qfq target files are incomplete: "
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
            if skip_existing_ready and _gold_qfq_partition_ready(
                instance,
                freq=batch.freq,
                partition_key=partition_key,
            ):
                skipped.append((batch.freq, partition_key))
            else:
                pending_keys.append(partition_key)
        if not pending_keys:
            continue
        batch_audits = audit_stk_mins_qfq_bootstrap_batch(
            lake_root=lake_root,
            duckdb=duckdb,
            batch=StkMinsQfqHistoryBatch(
                freq=batch.freq,
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
            raise ValueError(f"stk_mins qfq bootstrap audit failed: {samples}")
        audits.extend(batch_audits)
        if not dry_run:
            for audit in batch_audits:
                event_count += _report_stk_mins_qfq_partition_events(instance, audit)
                reported.append((audit.freq, audit.partition_key))

    if dry_run:
        return StkMinsQfqBootstrapEventReport(
            plan=plan,
            dry_run=True,
            partition_audits=tuple(audits),
            reported_asset_partitions=(),
            skipped_ready_asset_partitions=tuple(skipped),
            reported_event_count=0,
        )

    return StkMinsQfqBootstrapEventReport(
        plan=plan,
        dry_run=False,
        partition_audits=tuple(audits),
        reported_asset_partitions=tuple(reported),
        skipped_ready_asset_partitions=tuple(skipped),
        reported_event_count=event_count,
    )


def audit_stk_mins_qfq_bootstrap_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    freq: int,
    partition_key: str,
) -> StkMinsQfqBootstrapPartitionAudit:
    asset_key = GOLD_STK_MINS_QFQ_ASSET_KEYS[int(freq)]
    output_root_path = gold_stk_mins_qfq_path(
        lake_root,
        int(freq),
        "{ts_code}",
        partition_key[:4],
    ).parents[2]
    results = stk_mins_checks._gold_stk_mins_qfq_check_results(
        context=_PartitionContext(partition_key),
        lake_root=_LakeRootShim(lake_root),
        duckdb=duckdb,
        freq=int(freq),
        asset_key=asset_key,
    )
    checks = tuple(
        StkMinsQfqBootstrapCheckAudit(
            check_name=str(result.check_name),
            passed=bool(result.passed),
            metadata=result.metadata or {},
        )
        for result in results
    )
    metadata = checks[0].metadata if checks else {}
    schema_metadata = next(
        (
            check.metadata
            for check in checks
            if check.check_name
            == stk_mins_checks.GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK
        ),
        {},
    )
    observed_schema = _metadata_mapping(schema_metadata, "goldenshare/observed_schema")
    return StkMinsQfqBootstrapPartitionAudit(
        freq=int(freq),
        partition_key=partition_key,
        asset_key=asset_key,
        output_root_path=output_root_path,
        passed=all(check.passed for check in checks),
        row_count=_metadata_int(metadata, "goldenshare/gold_target_row_count"),
        observed_columns=tuple(observed_schema),
        expected_file_count=_metadata_int(metadata, "goldenshare/expected_file_count"),
        existing_file_count=_metadata_int(metadata, "goldenshare/existing_file_count"),
        checks=checks,
    )


def audit_stk_mins_qfq_bootstrap_batch(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    batch: StkMinsQfqHistoryBatch,
) -> tuple[StkMinsQfqBootstrapPartitionAudit, ...]:
    """Audit one freq/year batch once, then fan out per-date check results."""

    asset_key = GOLD_STK_MINS_QFQ_ASSET_KEYS[int(batch.freq)]
    output_root_path = gold_stk_mins_qfq_path(
        lake_root,
        int(batch.freq),
        "{ts_code}",
        batch.year,
    ).parents[2]
    silver_paths = _silver_paths_for_batch(lake_root, batch)
    trade_adj_paths = _trade_adj_factor_paths_for_keys(lake_root, batch.partition_keys)
    as_of_trade_date = batch.partition_keys[-1]
    as_of_adj_path = silver_adj_factor_path(lake_root, as_of_trade_date)

    with connect_configured_duckdb() as connection:
        expected_paths_by_date = _expected_gold_paths_by_date(
            connection,
            lake_root=lake_root,
            batch=batch,
            silver_paths=silver_paths,
        )
        all_expected_paths = tuple(
            dict.fromkeys(
                path for paths in expected_paths_by_date.values() for path in paths
            )
        )
        existing_paths = tuple(path for path in all_expected_paths if path.exists())
        missing_paths_by_date = {
            partition_key: tuple(
                path for path in expected_paths_by_date.get(partition_key, ()) if not path.exists()
            )
            for partition_key in batch.partition_keys
        }
        schema_mismatch_count, observed_schema, schema_error = (
            stk_mins_checks._gold_qfq_schema_mismatch_count(connection, existing_paths)
        )
        silver_counts = _batch_silver_counts(
            connection,
            partition_keys=batch.partition_keys,
            silver_paths=silver_paths,
        )
        gold_counts = _batch_gold_counts(
            connection,
            partition_keys=batch.partition_keys,
            gold_paths=existing_paths,
            freq=batch.freq,
        )
        factor_counts = _batch_factor_coverage_counts(
            connection,
            partition_keys=batch.partition_keys,
            silver_paths=silver_paths,
            trade_adj_paths=trade_adj_paths,
            as_of_adj_path=as_of_adj_path,
        )
        formula_counts = _batch_formula_counts(
            connection,
            partition_keys=batch.partition_keys,
            gold_paths=existing_paths,
            silver_paths=silver_paths,
            trade_adj_paths=trade_adj_paths,
            as_of_adj_path=as_of_adj_path,
        )

    audits: list[StkMinsQfqBootstrapPartitionAudit] = []
    for partition_key in batch.partition_keys:
        expected_paths = expected_paths_by_date.get(partition_key, ())
        missing_paths = missing_paths_by_date.get(partition_key, ())
        existing_file_count = len(expected_paths) - len(missing_paths)
        silver = silver_counts.get(partition_key, {})
        gold = gold_counts.get(partition_key, {})
        factor = factor_counts.get(partition_key, {})
        formula = formula_counts.get(partition_key, {})
        counts = stk_mins_checks.GoldStkMinsQfqCheckCounts(
            silver_row_count=int(silver.get("silver_row_count", 0)),
            expected_file_count=len(expected_paths),
            existing_file_count=existing_file_count,
            missing_file_count=len(missing_paths),
            gold_target_row_count=int(gold.get("gold_target_row_count", 0)),
            missing_trade_adj_factor_row_count=int(
                factor.get("missing_trade_adj_factor_row_count", 0)
            ),
            missing_as_of_adj_factor_row_count=int(
                factor.get("missing_as_of_adj_factor_row_count", 0)
            ),
            qfq_output_row_count=int(factor.get("qfq_output_row_count", 0)),
            schema_mismatch_file_count=int(schema_mismatch_count),
            path_mismatch_row_count=int(gold.get("path_mismatch_row_count", 0)),
            duplicate_key_count=int(gold.get("duplicate_key_count", 0)),
            invalid_price_row_count=int(gold.get("invalid_price_row_count", 0)),
            formula_missing_gold_row_count=int(
                formula.get("formula_missing_gold_row_count", 0)
            ),
            formula_unexpected_gold_row_count=int(
                formula.get("formula_unexpected_gold_row_count", 0)
            ),
            formula_mismatch_row_count=int(
                formula.get("formula_mismatch_row_count", 0)
            ),
        )
        input_paths = [
            silver_stk_mins_path(lake_root, batch.freq, partition_key),
            silver_adj_factor_path(lake_root, partition_key),
        ]
        if as_of_adj_path != input_paths[-1]:
            input_paths.append(as_of_adj_path)
        results = stk_mins_checks._gold_qfq_check_results(
            asset_key=asset_key,
            partition_key=partition_key,
            freq=batch.freq,
            counts=counts,
            output_root_path=output_root_path,
            input_file_paths=input_paths,
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
                freq=batch.freq,
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


def _expected_gold_paths_by_date(
    connection,
    *,
    lake_root: Path,
    batch: StkMinsQfqHistoryBatch,
    silver_paths: Sequence[Path],
) -> dict[str, tuple[Path, ...]]:
    source = _read_parquet_paths(silver_paths)
    rows = connection.execute(
        f"""
        SELECT
          strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
          CAST(ts_code AS VARCHAR) AS ts_code,
          strftime(CAST(trade_date AS DATE), '%Y') AS year
        FROM {source}
        GROUP BY partition_key, ts_code, year
        ORDER BY partition_key, ts_code
        """
    ).fetchall()
    paths_by_date: dict[str, list[Path]] = {
        partition_key: [] for partition_key in batch.partition_keys
    }
    for partition_key, ts_code, year in rows:
        paths_by_date.setdefault(str(partition_key), []).append(
            gold_stk_mins_qfq_path(lake_root, batch.freq, str(ts_code), str(year))
        )
    return {key: tuple(paths) for key, paths in paths_by_date.items()}


def _batch_silver_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    silver_paths: Sequence[Path],
) -> dict[str, dict[str, int]]:
    source = _read_parquet_paths(silver_paths)
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS ({_values_sql(partition_keys)}),
        silver_rows AS (
          SELECT
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(ts_code AS VARCHAR) AS ts_code
          FROM {source}
        )
        SELECT
          selected.partition_key,
          count(silver_rows.ts_code) AS silver_row_count,
          count(DISTINCT silver_rows.ts_code) AS expected_file_count
        FROM selected
        LEFT JOIN silver_rows
          ON selected.partition_key = silver_rows.partition_key
        GROUP BY selected.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "silver_row_count": int(silver_row_count),
            "expected_file_count": int(expected_file_count),
        }
        for partition_key, silver_row_count, expected_file_count in rows
    }


def _batch_gold_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    gold_paths: Sequence[Path],
    freq: int,
) -> dict[str, dict[str, int]]:
    if not gold_paths:
        return {
            partition_key: {
                "gold_target_row_count": 0,
                "path_mismatch_row_count": 0,
                "duplicate_key_count": 0,
                "invalid_price_row_count": 0,
            }
            for partition_key in partition_keys
        }
    source = _read_parquet_paths(gold_paths, filename=True)
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS ({_values_sql(partition_keys)}),
        gold_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(freq AS INTEGER) AS freq,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(filename AS VARCHAR) AS filename,
            regexp_extract(CAST(filename AS VARCHAR), 'ts_code=([^/]+)/year=', 1)
              AS path_ts_code,
            regexp_extract(CAST(filename AS VARCHAR), 'year=([0-9]{{4}})/', 1)
              AS path_year
          FROM {source}
        ),
        target_rows AS (
          SELECT gold_rows.*
          FROM gold_rows
          INNER JOIN selected
            ON gold_rows.partition_key = selected.partition_key
        ),
        duplicate_groups AS (
          SELECT partition_key, ts_code, trade_time, count(*) AS duplicate_count
          FROM target_rows
          GROUP BY partition_key, ts_code, trade_time
          HAVING count(*) > 1
        ),
        gold_aggregates AS (
          SELECT
            partition_key,
            count(*) AS gold_target_row_count,
            sum(
              CASE
                WHEN freq != {freq}
                  OR ts_code != path_ts_code
                  OR strftime(trade_date, '%Y') != path_year
                  OR CAST(trade_time AS DATE) != trade_date
                THEN 1 ELSE 0
              END
            ) AS path_mismatch_row_count,
            sum(
              CASE
                WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                  OR high < low
                  OR open < low OR open > high
                  OR close < low OR close > high
                THEN 1 ELSE 0
              END
            ) AS invalid_price_row_count
          FROM target_rows
          GROUP BY partition_key
        ),
        duplicate_aggregates AS (
          SELECT partition_key, count(*) AS duplicate_key_count
          FROM duplicate_groups
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(gold_aggregates.gold_target_row_count, 0)
            AS gold_target_row_count,
          coalesce(gold_aggregates.path_mismatch_row_count, 0)
            AS path_mismatch_row_count,
          coalesce(duplicate_aggregates.duplicate_key_count, 0)
            AS duplicate_key_count,
          coalesce(gold_aggregates.invalid_price_row_count, 0)
            AS invalid_price_row_count
        FROM selected
        LEFT JOIN gold_aggregates
          ON selected.partition_key = gold_aggregates.partition_key
        LEFT JOIN duplicate_aggregates
          ON selected.partition_key = duplicate_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "gold_target_row_count": int(gold_target_row_count),
            "path_mismatch_row_count": int(path_mismatch_row_count),
            "duplicate_key_count": int(duplicate_key_count),
            "invalid_price_row_count": int(invalid_price_row_count),
        }
        for (
            partition_key,
            gold_target_row_count,
            path_mismatch_row_count,
            duplicate_key_count,
            invalid_price_row_count,
        ) in rows
    }


def _batch_factor_coverage_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    silver_paths: Sequence[Path],
    trade_adj_paths: Sequence[Path],
    as_of_adj_path: Path,
) -> dict[str, dict[str, int]]:
    silver_source = _read_parquet_paths(silver_paths)
    trade_adj_source = _read_parquet_paths(trade_adj_paths)
    as_of_adj_source = _read_parquet_paths((as_of_adj_path,))
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS ({_values_sql(partition_keys)}),
        silver_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key
          FROM {silver_source}
        ),
        trade_adj_factor AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(adj_factor AS DOUBLE) AS trade_adj_factor
          FROM {trade_adj_source}
        ),
        as_of_adj_factor AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(adj_factor AS DOUBLE) AS as_of_adj_factor
          FROM {as_of_adj_source}
        ),
        joined_rows AS (
          SELECT
            silver_rows.partition_key,
            silver_rows.ts_code,
            trade_adj_factor.trade_adj_factor,
            as_of_adj_factor.as_of_adj_factor
          FROM silver_rows
          LEFT JOIN trade_adj_factor
            ON silver_rows.ts_code = trade_adj_factor.ts_code
           AND silver_rows.trade_date = trade_adj_factor.trade_date
          LEFT JOIN as_of_adj_factor
            ON silver_rows.ts_code = as_of_adj_factor.ts_code
        )
        SELECT
          selected.partition_key,
          count(joined_rows.ts_code) FILTER (
            WHERE joined_rows.trade_adj_factor IS NOT NULL
              AND joined_rows.as_of_adj_factor IS NOT NULL
          ) AS qfq_output_row_count,
          count(joined_rows.ts_code) FILTER (
            WHERE joined_rows.trade_adj_factor IS NULL
          ) AS missing_trade_adj_factor_row_count,
          count(joined_rows.ts_code) FILTER (
            WHERE joined_rows.as_of_adj_factor IS NULL
          ) AS missing_as_of_adj_factor_row_count
        FROM selected
        LEFT JOIN joined_rows
          ON selected.partition_key = joined_rows.partition_key
        GROUP BY selected.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "qfq_output_row_count": int(qfq_output_row_count),
            "missing_trade_adj_factor_row_count": int(
                missing_trade_adj_factor_row_count
            ),
            "missing_as_of_adj_factor_row_count": int(
                missing_as_of_adj_factor_row_count
            ),
        }
        for (
            partition_key,
            qfq_output_row_count,
            missing_trade_adj_factor_row_count,
            missing_as_of_adj_factor_row_count,
        ) in rows
    }


def _batch_formula_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    gold_paths: Sequence[Path],
    silver_paths: Sequence[Path],
    trade_adj_paths: Sequence[Path],
    as_of_adj_path: Path,
) -> dict[str, dict[str, int]]:
    if not gold_paths:
        return {
            partition_key: {
                "formula_missing_gold_row_count": 0,
                "formula_unexpected_gold_row_count": 0,
                "formula_mismatch_row_count": 0,
            }
            for partition_key in partition_keys
        }
    gold_source = _read_parquet_paths(gold_paths)
    qfq_select_sql = build_daily_qfq_select_sql(
        silver_paths=silver_paths,
        trade_adj_factor_paths=trade_adj_paths,
        as_of_adj_factor_paths=[as_of_adj_path],
    )
    tolerance = stk_mins_checks.GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS ({_values_sql(partition_keys)}),
        gold_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close
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
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close
          FROM ({qfq_select_sql})
        ),
        compared_rows AS (
          SELECT
            coalesce(target_gold_rows.partition_key, expected_rows.partition_key)
              AS partition_key,
            target_gold_rows.open AS gold_open,
            expected_rows.open AS expected_open,
            target_gold_rows.high AS gold_high,
            expected_rows.high AS expected_high,
            target_gold_rows.low AS gold_low,
            expected_rows.low AS expected_low,
            target_gold_rows.close AS gold_close,
            expected_rows.close AS expected_close,
            target_gold_rows.ts_code IS NULL AS missing_gold_row,
            expected_rows.ts_code IS NULL AS unexpected_gold_row
          FROM target_gold_rows
          FULL OUTER JOIN expected_rows
            ON target_gold_rows.partition_key = expected_rows.partition_key
           AND target_gold_rows.ts_code = expected_rows.ts_code
           AND target_gold_rows.trade_time = expected_rows.trade_time
        ),
        formula_aggregates AS (
          SELECT
            partition_key,
            count(*) FILTER (WHERE missing_gold_row)
              AS formula_missing_gold_row_count,
            count(*) FILTER (WHERE unexpected_gold_row)
              AS formula_unexpected_gold_row_count,
            count(*) FILTER (
              WHERE NOT missing_gold_row
                AND NOT unexpected_gold_row
                AND (
                  abs(gold_open - expected_open) > {tolerance}
                  OR abs(gold_high - expected_high) > {tolerance}
                  OR abs(gold_low - expected_low) > {tolerance}
                  OR abs(gold_close - expected_close) > {tolerance}
                )
            ) AS formula_mismatch_row_count
          FROM compared_rows
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(formula_aggregates.formula_missing_gold_row_count, 0)
            AS formula_missing_gold_row_count,
          coalesce(formula_aggregates.formula_unexpected_gold_row_count, 0)
            AS formula_unexpected_gold_row_count,
          coalesce(formula_aggregates.formula_mismatch_row_count, 0)
            AS formula_mismatch_row_count
        FROM selected
        LEFT JOIN formula_aggregates
          ON selected.partition_key = formula_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "formula_missing_gold_row_count": int(formula_missing_gold_row_count),
            "formula_unexpected_gold_row_count": int(
                formula_unexpected_gold_row_count
            ),
            "formula_mismatch_row_count": int(formula_mismatch_row_count),
        }
        for (
            partition_key,
            formula_missing_gold_row_count,
            formula_unexpected_gold_row_count,
            formula_mismatch_row_count,
        ) in rows
    }


def _read_parquet_paths(
    paths: Sequence[Path],
    *,
    filename: bool = False,
    union_by_name: bool = True,
) -> str:
    if not paths:
        raise ValueError("read_parquet paths must not be empty.")
    path_list = ", ".join(duckdb_string(path) for path in paths)
    filename_clause = ", filename=true" if filename else ""
    union_clause = ", union_by_name=true" if union_by_name else ""
    return (
        f"read_parquet([{path_list}], hive_partitioning=false"
        f"{union_clause}{filename_clause})"
    )


def _values_sql(values: Sequence[str]) -> str:
    if not values:
        raise ValueError("At least one value is required.")
    return "VALUES " + ", ".join(f"({duckdb_string(value)})" for value in values)


def audit_stk_mins_qfq_final_state(
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
) -> StkMinsQfqFinalAuditReport:
    plan = plan_stk_mins_qfq_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
    )
    sample_readiness: dict[str, bool] = {}
    for partition_key in _sample_partition_keys(plan.selected_partition_keys):
        for freq in plan.selected_freqs:
            status = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    GOLD_STK_MINS_QFQ_ASSET_KEYS[freq],
                    GOLD_STK_MINS_QFQ_CHECKS,
                ),
                partition_key=partition_key,
            )
            sample_readiness[f"{freq}:{partition_key}"] = status.ready
    return StkMinsQfqFinalAuditReport(
        selected_partition_count=len(plan.selected_partition_keys),
        selected_freqs=plan.selected_freqs,
        planned_target_file_count=plan.planned_target_file_count,
        existing_target_file_count=plan.existing_target_file_count,
        missing_input_count=plan.missing_input_count,
        materialized_partition_counts=plan.materialized_partition_counts,
        check_success_counts=plan.check_success_counts,
        sample_readiness=sample_readiness,
    )


class _LakeRootShim:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self) -> Path:
        return self._root


class _PartitionContext:
    def __init__(self, partition_key: str) -> None:
        self.partition_key = partition_key


def _gold_qfq_partition_ready(
    instance: dg.DagsterInstance,
    *,
    freq: int,
    partition_key: str,
) -> bool:
    status = asset_readiness_status(
        instance,
        AssetReadinessSpec(GOLD_STK_MINS_QFQ_ASSET_KEYS[freq], GOLD_STK_MINS_QFQ_CHECKS),
        partition_key=partition_key,
    )
    return status.ready


def _report_stk_mins_qfq_partition_events(
    instance: dg.DagsterInstance,
    audit: StkMinsQfqBootstrapPartitionAudit,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=audit.asset_key,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.output_root_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "source_method": "stk_mins_qfq_history_generation",
                    "bootstrap_event_backfill": True,
                    "freq": audit.freq,
                    "partition_key": audit.partition_key,
                    "expected_file_count": audit.expected_file_count,
                    "existing_file_count": audit.existing_file_count,
                },
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


def _latest_materialization(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_key: str,
):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=[partition_key],
        ),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(f"Expected materialization after runless report: {asset_key}")
    return result.records[0]


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int | None:
    value = _metadata_value(metadata, key)
    if value is None:
        return None
    return int(value)


def _metadata_mapping(metadata: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = _metadata_value(metadata, key)
    return value if isinstance(value, Mapping) else {}


def _metadata_value(metadata: Mapping[str, Any], key: str) -> Any:
    value = metadata.get(key)
    if hasattr(value, "value"):
        return value.value
    return value


def _sample_partition_keys(partition_keys: Sequence[str]) -> tuple[str, ...]:
    if not partition_keys:
        return ()
    ordered = tuple(partition_keys)
    return tuple(dict.fromkeys((ordered[0], ordered[len(ordered) // 2], ordered[-1])))
