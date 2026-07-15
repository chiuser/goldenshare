"""Shared Gold quality predicates for ``dc_daily_technical``.

The normal sensor and the blocking asset check deliberately use the same
set-based predicates.  Formula correctness is covered by the fixed fixtures;
runtime checks validate the published file and its relationship to Silver.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    gold_dc_daily_technical_path,
    silver_dc_daily_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
    SILVER_DC_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_BOLL,
    DC_DAILY_TECHNICAL_INDICATOR_VERSION,
    DC_DAILY_TECHNICAL_PARAMS_KEY,
    DC_DAILY_TECHNICAL_MA_PERIODS,
)


GOLD_DC_DAILY_TECHNICAL_CHECK_NAME = "gold_dc_daily_technical_core_check"


@dataclass(frozen=True, slots=True)
class GoldDcDailyTechnicalAudit:
    trade_date: str
    passed: bool
    materialized: bool
    checked_row_count: int
    failed_row_count: int
    failed_rules: tuple[str, ...] = ()
    reason_code: str = "ready"
    sample_rows: tuple[dict[str, Any], ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


def _expected_schema(schema: Sequence[object]) -> tuple[tuple[str, str], ...]:
    return tuple((str(column.name), str(column.type).upper()) for column in schema)


def _schema_mismatch(connection, path: Path, schema: Sequence[object]) -> tuple[bool, dict[str, object]]:
    observed = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
    )
    expected = _expected_schema(schema)
    return observed != expected, {
        "expected_columns": [name for name, _ in expected],
        "observed_columns": [name for name, _ in observed],
        "expected_types": {name: type_name for name, type_name in expected},
        "observed_types": {name: type_name for name, type_name in observed},
    }


def _sample_rows(connection, relation: str, condition: str) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        f"SELECT ts_code, trade_date, category FROM {relation} WHERE {condition} LIMIT 5"
    ).fetchmany(5)
    return tuple(
        {
            "ts_code": row[0],
            "trade_date": row[1].isoformat() if hasattr(row[1], "isoformat") else row[1],
            "category": row[2],
        }
        for row in rows
    )


def _union_files(paths_by_date: Mapping[str, Path], columns: Sequence[str]) -> str:
    if not paths_by_date:
        raise ValueError("at least one file is required")
    selects = []
    projection = ", ".join(columns)
    for trade_date, path in paths_by_date.items():
        selects.append(
            f"SELECT {projection}, DATE {duckdb_string(trade_date)} AS source_partition_date "
            f"FROM {read_parquet(path, hive_partitioning=False)}"
        )
    return "\nUNION ALL\n".join(selects)


def _schema_failures(
    connection,
    paths_by_date: Mapping[str, Path],
    schema: Sequence[object],
) -> dict[str, dict[str, object]]:
    failures: dict[str, dict[str, object]] = {}
    for trade_date, path in paths_by_date.items():
        try:
            mismatch, summary = _schema_mismatch(connection, path, schema)
        except Exception as exc:
            failures[trade_date] = {"scan_error": str(exc)[:300], "file_path": str(path)}
            continue
        if mismatch:
            failures[trade_date] = {**summary, "file_path": str(path)}
    return failures


def _quality_stats(connection, *, gold_sql: str, silver_sql: str) -> dict[str, tuple[int, ...]]:
    ma_warmup = ",\n".join(
        f"sum(CASE WHEN observation_count < {period} AND ma_{period} IS NOT NULL THEN 1 ELSE 0 END)"
        for period in DC_DAILY_TECHNICAL_MA_PERIODS
    )
    boll_period, _ = DC_DAILY_TECHNICAL_BOLL
    gold_stats = connection.execute(
        f"""
        WITH gold AS ({gold_sql}),
        grouped AS (
          SELECT
            source_partition_date,
            count(*) AS row_count,
            sum(CASE WHEN trade_date IS NULL OR trade_date <> source_partition_date THEN 1 ELSE 0 END) AS date_mismatch_count,
            sum(CASE WHEN ts_code IS NULL OR trim(ts_code) = '' OR category IS NULL OR trim(category) = '' THEN 1 ELSE 0 END) AS null_key_count,
            sum(CASE WHEN params_key <> {duckdb_string(DC_DAILY_TECHNICAL_PARAMS_KEY)} OR indicator_version <> {duckdb_string(DC_DAILY_TECHNICAL_INDICATOR_VERSION)} THEN 1 ELSE 0 END) AS metadata_mismatch_count,
            sum(CASE WHEN observation_count IS NULL OR observation_count < 1 THEN 1 ELSE 0 END) AS observation_count_invalid,
            sum(CASE WHEN close IS NULL OR NOT isfinite(close)
              OR (ma_5 IS NOT NULL AND NOT isfinite(ma_5))
              OR (ma_10 IS NOT NULL AND NOT isfinite(ma_10))
              OR (ma_15 IS NOT NULL AND NOT isfinite(ma_15))
              OR (ma_20 IS NOT NULL AND NOT isfinite(ma_20))
              OR (ma_30 IS NOT NULL AND NOT isfinite(ma_30))
              OR (ma_60 IS NOT NULL AND NOT isfinite(ma_60))
              OR (ma_120 IS NOT NULL AND NOT isfinite(ma_120))
              OR (ma_250 IS NOT NULL AND NOT isfinite(ma_250))
              OR (kdj_k IS NOT NULL AND NOT isfinite(kdj_k))
              OR (kdj_d IS NOT NULL AND NOT isfinite(kdj_d))
              OR (kdj_j IS NOT NULL AND NOT isfinite(kdj_j))
              OR (macd_dif IS NOT NULL AND NOT isfinite(macd_dif))
              OR (macd_dea IS NOT NULL AND NOT isfinite(macd_dea))
              OR (macd IS NOT NULL AND NOT isfinite(macd))
              OR (boll_mid IS NOT NULL AND NOT isfinite(boll_mid))
              OR (boll_upper IS NOT NULL AND NOT isfinite(boll_upper))
              OR (boll_lower IS NOT NULL AND NOT isfinite(boll_lower)) THEN 1 ELSE 0 END) AS numeric_invalid_count,
            {ma_warmup},
            sum(CASE WHEN observation_count < {boll_period} AND (boll_mid IS NOT NULL OR boll_upper IS NOT NULL OR boll_lower IS NOT NULL) THEN 1 ELSE 0 END) AS boll_warmup_invalid,
            sum(CASE WHEN observation_count >= {boll_period} AND (boll_mid IS NULL OR boll_upper IS NULL OR boll_lower IS NULL) THEN 1 ELSE 0 END) AS boll_post_warmup_missing
          FROM gold
          GROUP BY source_partition_date
        ),
        duplicates AS (
          SELECT source_partition_date, coalesce(sum(row_count - 1), 0) AS duplicate_key_count
          FROM (
            SELECT source_partition_date, ts_code, trade_date, category, count(*) AS row_count
            FROM gold
            GROUP BY source_partition_date, ts_code, trade_date, category
            HAVING count(*) > 1
          ) grouped_keys
          GROUP BY source_partition_date
        ),
        monotonic AS (
          SELECT source_partition_date,
                 sum(CASE WHEN previous_observation_count IS NOT NULL
                               AND observation_count <= previous_observation_count
                          THEN 1 ELSE 0 END) AS monotonic_failure_count
          FROM (
            SELECT source_partition_date, observation_count,
                   lag(observation_count) OVER (
                     PARTITION BY ts_code, category ORDER BY trade_date
                   ) AS previous_observation_count
            FROM gold
          ) ordered
          GROUP BY source_partition_date
        )
        SELECT grouped.*, coalesce(duplicates.duplicate_key_count, 0),
               coalesce(monotonic.monotonic_failure_count, 0)
        FROM grouped
        LEFT JOIN duplicates USING (source_partition_date)
        LEFT JOIN monotonic USING (source_partition_date)
        """
    ).fetchall()
    return {
        str(row[0]): tuple(int(value or 0) for value in row[1:])
        for row in gold_stats
    }


def _key_and_close_differences(connection, *, gold_sql: str, silver_sql: str) -> dict[str, tuple[int, int]]:
    rows = connection.execute(
        f"""
        WITH gold AS ({gold_sql}), silver AS ({silver_sql}),
        missing AS (
          SELECT source_partition_date, ts_code, trade_date, category
          FROM silver
          EXCEPT
          SELECT source_partition_date, ts_code, trade_date, category FROM gold
        ),
        extra AS (
          SELECT source_partition_date, ts_code, trade_date, category FROM gold
          EXCEPT
          SELECT source_partition_date, ts_code, trade_date, category FROM silver
        ),
        missing_counts AS (
          SELECT source_partition_date, count(*) AS count
          FROM missing
          GROUP BY source_partition_date
        ),
        extra_counts AS (
          SELECT source_partition_date, count(*) AS count
          FROM extra
          GROUP BY source_partition_date
        ),
        close_diff AS (
          SELECT s.source_partition_date, count(*) AS count
          FROM silver s
          INNER JOIN gold g USING (source_partition_date, ts_code, trade_date, category)
          WHERE s.close IS DISTINCT FROM g.close
          GROUP BY s.source_partition_date
        )
        SELECT dates.source_partition_date,
               coalesce(missing_counts.count, 0) + coalesce(extra_counts.count, 0) AS key_difference_count,
               coalesce(close_diff.count, 0) AS close_difference_count
        FROM (
          SELECT source_partition_date FROM missing
          UNION
          SELECT source_partition_date FROM extra
          UNION
          SELECT source_partition_date FROM close_diff
        ) dates
        LEFT JOIN missing_counts USING (source_partition_date)
        LEFT JOIN extra_counts USING (source_partition_date)
        LEFT JOIN close_diff USING (source_partition_date)
        """
    ).fetchall()
    return {str(row[0]): (int(row[1] or 0), int(row[2] or 0)) for row in rows}


def _build_status(
    *,
    trade_date: str,
    target_path: Path,
    source_path: Path,
    schema_summary: Mapping[str, object] | None,
    stats: tuple[int, ...] | None,
    source_schema_summary: Mapping[str, object] | None = None,
    differences: tuple[int, int] = (0, 0),
    source_exists: bool,
) -> GoldDcDailyTechnicalAudit:
    if not target_path.exists():
        return GoldDcDailyTechnicalAudit(
            trade_date=trade_date,
            passed=False,
            materialized=False,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("file_exists_and_row_count_positive",),
            reason_code="file_missing",
            metadata={"target_path": str(target_path), "source_path": str(source_path)},
        )
    if not source_exists:
        return GoldDcDailyTechnicalAudit(
            trade_date=trade_date,
            passed=False,
            materialized=True,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("silver_source_exists",),
            reason_code="silver_source_missing",
            metadata={"target_path": str(target_path), "source_path": str(source_path)},
        )
    if source_schema_summary is not None:
        scan_error = source_schema_summary.get("scan_error")
        return GoldDcDailyTechnicalAudit(
            trade_date=trade_date,
            passed=False,
            materialized=True,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("silver_source_schema_matches_contract",)
            if scan_error is None
            else ("quality_scan_completed",),
            reason_code=(
                "gold_dc_daily_technical_core_check_failed"
                if scan_error is None
                else "scan_error"
            ),
            metadata={
                "target_path": str(target_path),
                "source_path": str(source_path),
                "source_schema": dict(source_schema_summary),
            },
        )
    if schema_summary is not None:
        scan_error = schema_summary.get("scan_error")
        return GoldDcDailyTechnicalAudit(
            trade_date=trade_date,
            passed=False,
            materialized=True,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("schema_matches_contract",)
            if scan_error is None
            else ("quality_scan_completed",),
            reason_code=(
                "gold_dc_daily_technical_core_check_failed"
                if scan_error is None
                else "scan_error"
            ),
            metadata={
                "target_path": str(target_path),
                "source_path": str(source_path),
                "schema": dict(schema_summary),
            },
        )
    if stats is None:
        return GoldDcDailyTechnicalAudit(
            trade_date=trade_date,
            passed=False,
            materialized=True,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("partition_scan_observed",),
            reason_code="scan_error",
            metadata={"target_path": str(target_path), "source_path": str(source_path)},
        )

    (
        row_count,
        date_mismatch,
        null_key,
        metadata_mismatch,
        observation_invalid,
        numeric_invalid,
        *warmup_values,
        boll_warmup_invalid,
        boll_post_warmup_missing,
        duplicate_key_count,
        monotonic_failure_count,
    ) = stats
    ma_warmup_failures = warmup_values[: len(DC_DAILY_TECHNICAL_MA_PERIODS)]
    key_difference, close_difference = differences
    failed_rules: list[str] = []
    if row_count <= 0:
        failed_rules.append("row_count_positive")
    if schema_summary is not None:
        failed_rules.append("schema_matches_contract")
    if date_mismatch:
        failed_rules.append("partition_date_matches_trade_date")
    if null_key:
        failed_rules.append("business_key_non_null")
    if duplicate_key_count:
        failed_rules.append("business_key_unique")
    if key_difference:
        failed_rules.append("gold_keys_equal_silver_keys")
    if close_difference:
        failed_rules.append("close_matches_silver_close")
    if observation_invalid:
        failed_rules.append("observation_count_starts_at_one")
    if monotonic_failure_count:
        failed_rules.append("observation_count_monotonic")
    if metadata_mismatch:
        failed_rules.append("params_and_version_match")
    if numeric_invalid:
        failed_rules.append("post_warmup_values_are_finite")
    if any(ma_warmup_failures) or boll_warmup_invalid or boll_post_warmup_missing:
        failed_rules.append("warmup_null_rules_hold")
    failed_row_count = sum(
        (
            date_mismatch,
            null_key,
            duplicate_key_count,
            key_difference,
            close_difference,
            observation_invalid,
            monotonic_failure_count,
            metadata_mismatch,
            numeric_invalid,
            *ma_warmup_failures,
            boll_warmup_invalid,
            boll_post_warmup_missing,
        )
    )
    return GoldDcDailyTechnicalAudit(
        trade_date=trade_date,
        passed=not failed_rules,
        materialized=True,
        checked_row_count=row_count,
        failed_row_count=failed_row_count,
        failed_rules=tuple(failed_rules),
        reason_code="ready" if not failed_rules else "gold_dc_daily_technical_core_check_failed",
        metadata={
            "target_path": str(target_path),
            "source_path": str(source_path),
            "schema": dict(schema_summary) if schema_summary is not None else None,
            "key_difference_count": key_difference,
            "close_difference_count": close_difference,
            "warmup_failure_counts": {
                f"ma_{period}": value
                for period, value in zip(DC_DAILY_TECHNICAL_MA_PERIODS, ma_warmup_failures, strict=True)
            },
        },
    )


def batch_gold_dc_daily_technical_audit(
    *,
    connection,
    lake_root: Path,
    trade_dates: Sequence[str],
) -> dict[str, GoldDcDailyTechnicalAudit]:
    """Audit a bounded set of Gold files with set-based DuckDB aggregation."""

    dates = tuple(dict.fromkeys(str(value) for value in trade_dates))
    target_paths = {trade_date: gold_dc_daily_technical_path(lake_root, trade_date) for trade_date in dates}
    source_paths = {trade_date: silver_dc_daily_path(lake_root, trade_date) for trade_date in dates}
    target_existing = {date: path for date, path in target_paths.items() if path.exists()}
    source_existing = {date: path for date, path in source_paths.items() if path.exists()}
    schema_failures = _schema_failures(connection, target_existing, GOLD_DC_DAILY_TECHNICAL_SCHEMA)
    source_schema_failures = _schema_failures(
        connection,
        source_existing,
        SILVER_DC_DAILY_SCHEMA,
    )
    statuses: dict[str, GoldDcDailyTechnicalAudit] = {}
    if not target_existing or not source_existing:
        for trade_date in dates:
            statuses[trade_date] = _build_status(
                trade_date=trade_date,
                target_path=target_paths[trade_date],
                source_path=source_paths[trade_date],
                schema_summary=schema_failures.get(trade_date),
                source_schema_summary=source_schema_failures.get(trade_date),
                stats=None,
                source_exists=source_paths[trade_date].exists(),
            )
        if not target_existing:
            return statuses

    target_scan = {
        trade_date: path
        for trade_date, path in target_existing.items()
        if trade_date not in schema_failures
    }
    source_scan = {
        trade_date: path
        for trade_date, path in source_existing.items()
        if trade_date not in source_schema_failures
    }
    if not target_scan or not source_scan:
        for trade_date in dates:
            statuses[trade_date] = _build_status(
                trade_date=trade_date,
                target_path=target_paths[trade_date],
                source_path=source_paths[trade_date],
                schema_summary=schema_failures.get(trade_date),
                source_schema_summary=source_schema_failures.get(trade_date),
                stats=None,
                source_exists=source_paths[trade_date].exists(),
            )
        return statuses

    try:
        gold_sql = _union_files(target_scan, (
            "ts_code", "trade_date", "category", "close", "ma_5", "ma_10", "ma_15", "ma_20",
            "ma_30", "ma_60", "ma_120", "ma_250", "kdj_k", "kdj_d", "kdj_j", "macd_dif",
            "macd_dea", "macd", "boll_mid", "boll_upper", "boll_lower", "observation_count",
            "params_key", "indicator_version",
        ))
        source_sql = _union_files(source_scan, ("ts_code", "trade_date", "category", "close"))
        stats_by_date = _quality_stats(connection, gold_sql=gold_sql, silver_sql=source_sql)
        differences = _key_and_close_differences(connection, gold_sql=gold_sql, silver_sql=source_sql)
    except Exception as exc:
        for trade_date in target_scan:
            statuses[trade_date] = GoldDcDailyTechnicalAudit(
                trade_date=trade_date,
                passed=False,
                materialized=True,
                checked_row_count=0,
                failed_row_count=0,
                failed_rules=("quality_scan_completed",),
                reason_code="scan_error",
                metadata={"scan_error": str(exc)[:500], "target_path": str(target_paths[trade_date])},
            )
        for trade_date in dates:
            statuses.setdefault(
                trade_date,
                _build_status(
                    trade_date=trade_date,
                    target_path=target_paths[trade_date],
                    source_path=source_paths[trade_date],
                    schema_summary=schema_failures.get(trade_date),
                    source_schema_summary=source_schema_failures.get(trade_date),
                    stats=None,
                    source_exists=source_paths[trade_date].exists(),
                ),
            )
        return statuses

    for trade_date in dates:
        statuses[trade_date] = _build_status(
            trade_date=trade_date,
            target_path=target_paths[trade_date],
            source_path=source_paths[trade_date],
            schema_summary=schema_failures.get(trade_date),
            source_schema_summary=source_schema_failures.get(trade_date),
            stats=stats_by_date.get(trade_date),
            differences=differences.get(trade_date, (0, 0)),
            source_exists=source_paths[trade_date].exists(),
        )
    return statuses


def audit_gold_dc_daily_technical_partition(
    *, connection, lake_root: Path, trade_date: str
) -> GoldDcDailyTechnicalAudit:
    return batch_gold_dc_daily_technical_audit(
        connection=connection,
        lake_root=lake_root,
        trade_dates=(trade_date,),
    )[str(trade_date)]


__all__ = [
    "GOLD_DC_DAILY_TECHNICAL_CHECK_NAME",
    "GoldDcDailyTechnicalAudit",
    "audit_gold_dc_daily_technical_partition",
    "batch_gold_dc_daily_technical_audit",
]
