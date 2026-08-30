"""Local-only N3A observation for finalized ETF minute Raw files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from orchestrator.defs.assets.etf_mins import (
    create_etf_mins_frozen_basic_relations,
)
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
    EtfMinsBootstrapError,
    compute_etf_mins_bootstrap_payload_hash,
    load_etf_mins_bootstrap_raw_evidence,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ,
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX,
)

ETF_MINS_RAW_OBSERVATION_KIND = "etf_mins_raw_observation"
ETF_MINS_RAW_PROPOSED_POLICY_KIND = "etf_mins_raw_proposed_policy"
ETF_MINS_RAW_OBSERVATION_MAX_ISSUE_ROWS = 200_000
ETF_MINS_RAW_OBSERVATION_MAX_ISSUE_BYTES = 256 * 1024 * 1024

ETF_MINS_RAW_OBSERVATION_REASON_CODES = (
    "all_frequencies_empty",
    "partial_frequency_empty",
    "expected_code_missing",
    "internal_grid_gap_candidate",
    "boundary_time_variant_candidate",
    "zero_volume_bar_observed",
    "price_domain_anomaly",
    "volume_amount_domain_anomaly",
    "vwap_domain_anomaly",
    "off_session_time_observed",
    "known_non_required_code_present",
    "retained_legacy_code_present",
    "unexplained_new_code_observed",
    "key_contract_anomaly",
    "partition_contract_anomaly",
    "exchange_identity_anomaly",
)

_PARQUET_FILENAMES = (
    "raw_file_manifest.parquet",
    "raw_code_day_freq_profile.parquet",
    "raw_grid_profile.parquet",
    "raw_domain_profile.parquet",
    "raw_issue_details.parquet",
    "raw_partition_observation_manifest.parquet",
)
_INPUT_TABLE = "etf_mins_raw_observation_inputs"
_AGGREGATE_TABLE = "etf_mins_raw_observation_aggregate"
_BOUNDARY_TABLE = "etf_mins_raw_observation_boundaries"
_BASIC_SET_TABLE = "etf_mins_raw_observation_basic_sets"
_BASIC_ALL_RELATION = "etf_basic_all"
_REQUESTABLE_RELATION = "etf_mins_requestable_targets"


@dataclass(frozen=True, slots=True)
class EtfMinsRawObservationResult:
    operation_id: str
    output_dir: Path
    raw_observation_summary_path: Path
    proposed_policy_path: Path
    input_manifest_hash: str
    observation_summary_hash: str
    proposed_policy_hash: str
    scanned_file_count: int
    scanned_row_count: int
    scanned_byte_count: int
    issue_row_count: int
    raw_scan_query_count: int
    analysis_sql_statement_count: int
    peak_temp_dir_size_bytes: int
    elapsed_seconds: float


def observe_etf_mins_raw(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    raw_bootstrap_report_path: Path,
    output_dir: Path,
) -> EtfMinsRawObservationResult:
    """Profile finalized Raw facts without accessing Prod or making a decision."""

    started_at = perf_counter()
    evidence = load_etf_mins_bootstrap_raw_evidence(
        lake_root=lake_root,
        duckdb=duckdb,
        raw_final_report_path=raw_bootstrap_report_path,
    )
    operation_root = raw_bootstrap_report_path.parent.resolve(strict=False)
    expected_output_dir = operation_root / "raw-observe"
    if not output_dir.is_absolute() or output_dir.resolve(strict=False) != (
        expected_output_dir
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_raw_observation_output_path_invalid: output_dir must be the "
            "raw-observe directory inside the input operation."
        )
    if output_dir.exists():
        return _load_existing_observation(
            output_dir=output_dir,
            operation_id=evidence.plan.operation_id,
            input_manifest_hash=evidence.raw_apply_report.finalized_raw_manifest_hash,
            raw_final_report_hash=evidence.raw_apply_report.report_hash,
        )

    candidate_dir = output_dir.with_name(
        f".{output_dir.name}.candidate-{uuid.uuid4().hex}"
    )
    candidate_dir.mkdir(parents=False, exist_ok=False)
    profile_dir = candidate_dir / ".query-profiles"
    profile_dir.mkdir()
    sql_metrics = {
        "analysis_sql_statement_count": 0,
        "raw_scan_query_count": 0,
        "peak_temp_dir_size_bytes": 0,
    }
    try:
        inputs = _build_observation_inputs(
            lake_root=lake_root,
            manifest_rows=evidence.finalized_raw_manifest,
            input_manifest_hash=evidence.raw_apply_report.finalized_raw_manifest_hash,
            basic_raw_snapshot_hash=evidence.plan.basic_raw_snapshot_hash,
            basic_silver_content_hash=evidence.plan.basic_silver_content_hash,
        )
        raw_files_sql = _raw_files_sql(inputs)
        with duckdb.connect() as connection:
            _create_input_table(connection, inputs=inputs, sql_metrics=sql_metrics)
            create_etf_mins_frozen_basic_relations(
                connection,
                basic_reference=evidence.basic_reference,
            )
            _copy_profile(
                connection,
                _raw_file_manifest_sql(),
                candidate_dir / "raw_file_manifest.parquet",
                sql_metrics=sql_metrics,
            )
            _execute_profiled(
                connection,
                _raw_aggregate_sql(raw_files_sql),
                profile_dir / "raw_aggregate.json",
                sql_metrics=sql_metrics,
            )
            _create_basic_set_table(connection, sql_metrics=sql_metrics)
            _assert_observed_scope_matches_manifest(
                connection,
                sql_metrics=sql_metrics,
            )
            _copy_profile(
                connection,
                _code_day_profile_sql(),
                candidate_dir / "raw_code_day_freq_profile.parquet",
                sql_metrics=sql_metrics,
            )
            _create_boundary_table(connection, sql_metrics=sql_metrics)
            _execute_profiled(
                connection,
                copy_query_to_parquet(
                    _grid_profile_sql(raw_files_sql),
                    candidate_dir / "raw_grid_profile.parquet",
                ),
                profile_dir / "raw_grid.json",
                sql_metrics=sql_metrics,
            )
            _copy_profile(
                connection,
                _domain_profile_sql(),
                candidate_dir / "raw_domain_profile.parquet",
                sql_metrics=sql_metrics,
            )
            _copy_profile(
                connection,
                _partition_observation_sql(candidate_dir),
                candidate_dir / "raw_partition_observation_manifest.parquet",
                sql_metrics=sql_metrics,
            )
            _copy_profile(
                connection,
                _issue_details_sql(candidate_dir),
                candidate_dir / "raw_issue_details.parquet",
                sql_metrics=sql_metrics,
            )
            row_counts = _load_artifact_row_counts(
                connection,
                candidate_dir=candidate_dir,
                sql_metrics=sql_metrics,
            )
            distributions = _load_distribution_summary(
                connection,
                candidate_dir=candidate_dir,
                sql_metrics=sql_metrics,
            )
            prod_callback_candidates = _load_prod_callback_candidates(
                connection,
                candidate_dir=candidate_dir,
                sql_metrics=sql_metrics,
            )

        issue_path = candidate_dir / "raw_issue_details.parquet"
        issue_row_count = row_counts["raw_issue_details.parquet"]
        issue_row_limit = min(
            ETF_MINS_RAW_OBSERVATION_MAX_ISSUE_ROWS,
            evidence.plan.target_file_count
            * len(ETF_MINS_RAW_OBSERVATION_REASON_CODES),
        )
        if issue_row_count > issue_row_limit:
            raise EtfMinsBootstrapError(
                "etf_mins_raw_observation_issue_row_budget_exceeded: narrow the "
                "frozen plan; issue rows are never truncated."
            )
        if issue_path.stat().st_size > ETF_MINS_RAW_OBSERVATION_MAX_ISSUE_BYTES:
            raise EtfMinsBootstrapError(
                "etf_mins_raw_observation_issue_size_budget_exceeded: narrow the "
                "frozen plan; issue details are never truncated."
            )

        artifacts = _artifact_metadata(candidate_dir, row_counts=row_counts)
        summary_payload: dict[str, object] = {
            "observation_kind": ETF_MINS_RAW_OBSERVATION_KIND,
            "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
            "operation_id": evidence.plan.operation_id,
            "plan_fingerprint": evidence.plan.plan_fingerprint,
            "raw_final_report_hash": evidence.raw_apply_report.report_hash,
            "input_manifest_hash": (
                evidence.raw_apply_report.finalized_raw_manifest_hash
            ),
            "basic_raw_snapshot_hash": evidence.plan.basic_raw_snapshot_hash,
            "basic_silver_content_hash": evidence.plan.basic_silver_content_hash,
            "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "partition_state": "unclassified",
            "scanned_file_count": len(inputs),
            "scanned_row_count": sum(int(row["raw_row_count"]) for row in inputs),
            "scanned_byte_count": sum(int(row["raw_size_bytes"]) for row in inputs),
            "analysis_sql_statement_count": sql_metrics["analysis_sql_statement_count"],
            "raw_scan_query_count": sql_metrics["raw_scan_query_count"],
            "peak_temp_dir_size_bytes": sql_metrics["peak_temp_dir_size_bytes"],
            "elapsed_seconds": round(perf_counter() - started_at, 6),
            "artifacts": artifacts,
            "observed_distributions": distributions,
            "prod_callback_candidates": prod_callback_candidates,
            "prod_callback_candidate_limit": ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
        }
        summary_payload["observation_summary_hash"] = (
            compute_etf_mins_bootstrap_payload_hash(summary_payload)
        )
        _write_json(
            candidate_dir / "raw_observation_summary.json",
            summary_payload,
        )

        proposed_payload = _build_proposed_policy(
            operation_id=evidence.plan.operation_id,
            input_manifest_hash=evidence.raw_apply_report.finalized_raw_manifest_hash,
            observation_summary_hash=str(summary_payload["observation_summary_hash"]),
            issue_counts=distributions["issue_counts"],
        )
        _write_json(candidate_dir / "proposed_policy.json", proposed_payload)
        shutil.rmtree(profile_dir)
        os.replace(candidate_dir, output_dir)
    except Exception:
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)
        raise

    return _load_existing_observation(
        output_dir=output_dir,
        operation_id=evidence.plan.operation_id,
        input_manifest_hash=evidence.raw_apply_report.finalized_raw_manifest_hash,
        raw_final_report_hash=evidence.raw_apply_report.report_hash,
    )


def _build_observation_inputs(
    *,
    lake_root: Path,
    manifest_rows: Sequence[Mapping[str, object]],
    input_manifest_hash: str,
    basic_raw_snapshot_hash: str,
    basic_silver_content_hash: str,
) -> tuple[dict[str, object], ...]:
    inputs: list[dict[str, object]] = []
    for row in manifest_rows:
        raw_path = (lake_root / str(row["formal_raw_relative_path"])).resolve(
            strict=False
        )
        if not raw_path.is_file() or not raw_path.is_relative_to(
            lake_root.resolve(strict=False)
        ):
            raise EtfMinsBootstrapError("etf_mins_raw_observation_input_path_invalid.")
        actual_size = raw_path.stat().st_size
        if actual_size != int(row["formal_raw_size_bytes"]):
            raise EtfMinsBootstrapError("etf_mins_raw_observation_input_size_changed.")
        inputs.append(
            {
                "operation_id": str(row["operation_id"]),
                "plan_fingerprint": str(row["plan_fingerprint"]),
                "input_manifest_hash": input_manifest_hash,
                "trade_date": str(row["trade_date"]),
                "source_freq": str(row["source_freq"]),
                "raw_relative_path": str(row["formal_raw_relative_path"]),
                "raw_absolute_path": str(raw_path),
                "raw_sha256": str(row["formal_raw_sha256"]),
                "raw_size_bytes": actual_size,
                "raw_row_count": int(row["formal_raw_row_count"]),
                "disposition": str(row["disposition"]),
                "zero_row": bool(row["zero_row"]),
                "basic_raw_snapshot_hash": basic_raw_snapshot_hash,
                "basic_silver_content_hash": basic_silver_content_hash,
                "expected_count": int(row["expected_count"]),
                "present_count": int(row["present_count"]),
                "missing_count": int(row["missing_count"]),
                "known_non_required_present_count": int(
                    row["known_non_required_present_count"]
                ),
                "retained_legacy_count": int(row["retained_legacy_count"]),
                "unexplained_new_count": int(row["unexplained_new_count"]),
            }
        )
    return tuple(
        sorted(
            inputs, key=lambda row: (str(row["trade_date"]), str(row["source_freq"]))
        )
    )


def _create_input_table(
    connection: Any,
    *,
    inputs: Sequence[Mapping[str, object]],
    sql_metrics: dict[str, int],
) -> None:
    columns = tuple(inputs[0]) if inputs else ()
    if not columns:
        raise EtfMinsBootstrapError("etf_mins_raw_observation_input_empty.")
    type_by_column = {
        "raw_size_bytes": "BIGINT",
        "raw_row_count": "BIGINT",
        "zero_row": "BOOLEAN",
        "expected_count": "BIGINT",
        "present_count": "BIGINT",
        "missing_count": "BIGINT",
        "known_non_required_present_count": "BIGINT",
        "retained_legacy_count": "BIGINT",
        "unexplained_new_count": "BIGINT",
    }
    schema = ", ".join(
        f"{column} {type_by_column.get(column, 'VARCHAR')}" for column in columns
    )
    _execute(
        connection,
        f"CREATE TEMP TABLE {_INPUT_TABLE} ({schema})",
        sql_metrics=sql_metrics,
    )
    placeholders = ", ".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO {_INPUT_TABLE} VALUES ({placeholders})",
        [tuple(row[column] for column in columns) for row in inputs],
    )
    sql_metrics["analysis_sql_statement_count"] += 1


def _raw_files_sql(inputs: Sequence[Mapping[str, object]]) -> str:
    paths = ", ".join(duckdb_string(str(row["raw_absolute_path"])) for row in inputs)
    return (
        f"read_parquet([{paths}], hive_partitioning=false, "
        "union_by_name=false, filename=true)"
    )


def _raw_file_manifest_sql() -> str:
    return f"""
    SELECT
      {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION}::INTEGER AS schema_version,
      operation_id,
      plan_fingerprint,
      input_manifest_hash,
      trade_date,
      source_freq,
      raw_relative_path,
      raw_sha256,
      raw_size_bytes,
      raw_row_count,
      disposition,
      zero_row,
      basic_raw_snapshot_hash,
      basic_silver_content_hash,
      expected_count,
      present_count,
      missing_count,
      known_non_required_present_count,
      retained_legacy_count,
      unexplained_new_count
    FROM {_INPUT_TABLE}
    ORDER BY trade_date, source_freq
    """


def _raw_aggregate_sql(raw_files_sql: str) -> str:
    exchange_predicate = " OR ".join(
        "(right(upper(trim(ts_code)), 3) = "
        f"{duckdb_string(f'.{suffix}')} AND actual_exchange = "
        f"{duckdb_string(exchange)})"
        for suffix, exchange in ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX.items()
    )
    gap_minutes = (
        "CASE source_freq "
        + " ".join(
            f"WHEN {duckdb_string(source_freq)} THEN {asset_freq}"
            for source_freq, asset_freq in ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ.items()
        )
        + " END"
    )
    return f"""
    CREATE TEMP TABLE {_AGGREGATE_TABLE} AS
    WITH joined AS (
      SELECT
        i.trade_date,
        i.source_freq,
        r.filename IS NOT NULL AS matched,
        r.ts_code,
        r.freq AS actual_freq,
        r.trade_time,
        r.open,
        r.close,
        r.high,
        r.low,
        r.vol,
        r.amount,
        r.vwap,
        r.exchange AS actual_exchange
      FROM {_INPUT_TABLE} AS i
      LEFT JOIN {raw_files_sql} AS r
        ON r.filename = i.raw_absolute_path
    ),
    ordered AS (
      SELECT
        *,
        lag(trade_time) OVER (
          PARTITION BY trade_date, source_freq, ts_code
          ORDER BY trade_time
        ) AS previous_trade_time
      FROM joined
    )
    SELECT
      CASE WHEN GROUPING(ts_code) = 1 THEN 'partition' ELSE 'code_day' END
        AS aggregation_level,
      trade_date,
      source_freq,
      ts_code,
      min(actual_exchange) FILTER (WHERE matched) AS exchange,
      count(DISTINCT actual_exchange) FILTER (WHERE matched)
        AS distinct_exchange_count,
      count(*) FILTER (WHERE matched) AS row_count,
      count(DISTINCT trade_time) FILTER (WHERE matched)
        AS distinct_time_count,
      count(DISTINCT ts_code) FILTER (WHERE matched AND ts_code IS NOT NULL)
        AS distinct_code_count,
      min(trade_time) FILTER (WHERE matched) AS min_trade_time,
      max(trade_time) FILTER (WHERE matched) AS max_trade_time,
      count(*) FILTER (
        WHERE matched AND (ts_code IS NULL OR actual_freq IS NULL OR trade_time IS NULL)
      ) AS null_key_count,
      count(*) FILTER (
        WHERE matched AND ts_code IS NOT NULL AND actual_freq IS NOT NULL
          AND trade_time IS NOT NULL
      ) - count(DISTINCT (ts_code, actual_freq, trade_time)) FILTER (
        WHERE matched AND ts_code IS NOT NULL AND actual_freq IS NOT NULL
          AND trade_time IS NOT NULL
      ) AS duplicate_key_count,
      count(*) FILTER (
        WHERE matched AND trade_time IS NOT NULL
          AND CAST(trade_time AS DATE) <> CAST(trade_date AS DATE)
      ) AS date_mismatch_count,
      count(*) FILTER (
        WHERE matched AND actual_freq IS NOT NULL AND actual_freq <> source_freq
      ) AS freq_mismatch_count,
      count(*) FILTER (
        WHERE matched AND ts_code IS NOT NULL
          AND (actual_exchange IS NULL OR NOT ({exchange_predicate}))
      ) AS exchange_mismatch_count,
      count(*) FILTER (
        WHERE matched AND (open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL)
      ) AS null_price_count,
      count(*) FILTER (
        WHERE matched AND (
          (open IS NOT NULL AND NOT isfinite(open))
          OR (close IS NOT NULL AND NOT isfinite(close))
          OR (high IS NOT NULL AND NOT isfinite(high))
          OR (low IS NOT NULL AND NOT isfinite(low))
        )
      ) AS nonfinite_price_count,
      count(*) FILTER (
        WHERE matched AND (open <= 0 OR close <= 0 OR high <= 0 OR low <= 0)
      ) AS nonpositive_price_count,
      count(*) FILTER (
        WHERE matched AND (
          open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
          OR NOT isfinite(open) OR NOT isfinite(close)
          OR NOT isfinite(high) OR NOT isfinite(low)
          OR high < greatest(open, close, low)
          OR low > least(open, close, high)
        )
      ) AS invalid_ohlc_count,
      count(*) FILTER (
        WHERE matched AND (
          open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
          OR NOT isfinite(open) OR NOT isfinite(close)
          OR NOT isfinite(high) OR NOT isfinite(low)
          OR open <= 0 OR close <= 0 OR high <= 0 OR low <= 0
          OR high < greatest(open, close, low)
          OR low > least(open, close, high)
        )
      ) AS price_domain_anomaly_count,
      count(*) FILTER (
        WHERE matched AND (vol IS NULL OR amount IS NULL)
      ) AS null_volume_amount_count,
      count(*) FILTER (
        WHERE matched AND (
          vol IS NULL OR amount IS NULL OR vol < 0
          OR (amount IS NOT NULL AND NOT isfinite(amount)) OR amount < 0
        )
      ) AS volume_amount_anomaly_count,
      count(*) FILTER (WHERE matched AND vol = 0) AS zero_volume_bar_count,
      count(*) FILTER (
        WHERE matched AND (
          vwap IS NULL OR NOT isfinite(vwap) OR vwap < 0
        )
      ) AS invalid_vwap_count,
      count(*) FILTER (
        WHERE matched AND trade_time IS NOT NULL AND (
          CAST(trade_time AS TIME) < TIME '09:00:00'
          OR CAST(trade_time AS TIME) > TIME '16:00:00'
        )
      ) AS off_session_time_count,
      count(*) FILTER (
        WHERE matched AND previous_trade_time IS NOT NULL
          AND date_diff('minute', previous_trade_time, trade_time) > {gap_minutes}
      ) AS grid_gap_candidate_count
    FROM ordered
    GROUP BY GROUPING SETS (
      (trade_date, source_freq),
      (trade_date, source_freq, ts_code)
    )
    """


def _code_day_profile_sql() -> str:
    return f"""
    SELECT
      {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION}::INTEGER AS schema_version,
      i.input_manifest_hash,
      a.ts_code,
      a.trade_date,
      a.source_freq,
      a.exchange,
      a.distinct_exchange_count,
      a.row_count,
      a.distinct_time_count,
      a.min_trade_time,
      a.max_trade_time,
      CAST(a.min_trade_time AS TIME) AS min_clock_time,
      CAST(a.max_trade_time AS TIME) AS max_clock_time,
      a.null_key_count,
      a.duplicate_key_count,
      a.date_mismatch_count,
      a.freq_mismatch_count,
      a.exchange_mismatch_count,
      a.null_price_count,
      a.nonfinite_price_count,
      a.nonpositive_price_count,
      a.invalid_ohlc_count,
      a.price_domain_anomaly_count,
      a.null_volume_amount_count,
      a.volume_amount_anomaly_count,
      a.zero_volume_bar_count,
      a.invalid_vwap_count,
      a.off_session_time_count,
      a.grid_gap_candidate_count
    FROM {_AGGREGATE_TABLE} AS a
    JOIN {_INPUT_TABLE} AS i USING (trade_date, source_freq)
    WHERE a.aggregation_level = 'code_day' AND a.ts_code IS NOT NULL
    ORDER BY a.ts_code, a.trade_date, a.source_freq
    """


def _create_basic_set_table(connection: Any, *, sql_metrics: dict[str, int]) -> None:
    _execute(
        connection,
        f"""
        CREATE TEMP TABLE {_BASIC_SET_TABLE} AS
        WITH partitions AS (
          SELECT trade_date, source_freq FROM {_INPUT_TABLE}
        ),
        present_codes AS (
          SELECT DISTINCT trade_date, source_freq, ts_code
          FROM {_AGGREGATE_TABLE}
          WHERE aggregation_level = 'code_day' AND ts_code IS NOT NULL
        ),
        expected_codes AS (
          SELECT
            partition.trade_date,
            partition.source_freq,
            trim(CAST(target.ts_code AS VARCHAR)) AS ts_code
          FROM partitions AS partition
          JOIN {_REQUESTABLE_RELATION} AS target
            ON CAST(target.list_date AS DATE) <= CAST(partition.trade_date AS DATE)
        ),
        expected_counts AS (
          SELECT trade_date, source_freq, count(*) AS expected_count
          FROM expected_codes GROUP BY trade_date, source_freq
        ),
        present_counts AS (
          SELECT trade_date, source_freq, count(*) AS present_count
          FROM present_codes GROUP BY trade_date, source_freq
        ),
        missing_counts AS (
          SELECT expected.trade_date, expected.source_freq, count(*) AS missing_count
          FROM expected_codes AS expected
          LEFT JOIN present_codes AS present
            USING (trade_date, source_freq, ts_code)
          WHERE present.ts_code IS NULL
          GROUP BY expected.trade_date, expected.source_freq
        ),
        known_non_required_counts AS (
          SELECT present.trade_date, present.source_freq,
            count(*) AS known_non_required_present_count
          FROM present_codes AS present
          JOIN {_BASIC_ALL_RELATION} AS basic USING (ts_code)
          LEFT JOIN expected_codes AS expected
            USING (trade_date, source_freq, ts_code)
          WHERE expected.ts_code IS NULL
          GROUP BY present.trade_date, present.source_freq
        ),
        nonbasic_counts AS (
          SELECT present.trade_date, present.source_freq, count(*) AS nonbasic_count
          FROM present_codes AS present
          LEFT JOIN {_BASIC_ALL_RELATION} AS basic USING (ts_code)
          WHERE basic.ts_code IS NULL
          GROUP BY present.trade_date, present.source_freq
        )
        SELECT
          partition.trade_date,
          partition.source_freq,
          coalesce(expected.expected_count, 0)::BIGINT AS expected_count,
          coalesce(present.present_count, 0)::BIGINT AS present_count,
          coalesce(missing.missing_count, 0)::BIGINT AS missing_count,
          coalesce(known.known_non_required_present_count, 0)::BIGINT
            AS known_non_required_present_count,
          coalesce(nonbasic.nonbasic_count, 0)::BIGINT AS nonbasic_count
        FROM partitions AS partition
        LEFT JOIN expected_counts AS expected USING (trade_date, source_freq)
        LEFT JOIN present_counts AS present USING (trade_date, source_freq)
        LEFT JOIN missing_counts AS missing USING (trade_date, source_freq)
        LEFT JOIN known_non_required_counts AS known USING (trade_date, source_freq)
        LEFT JOIN nonbasic_counts AS nonbasic USING (trade_date, source_freq)
        """,
        sql_metrics=sql_metrics,
    )


def _assert_observed_scope_matches_manifest(
    connection: Any,
    *,
    sql_metrics: dict[str, int],
) -> None:
    row = _execute(
        connection,
        f"""
        SELECT count(*)
        FROM {_INPUT_TABLE} AS input
        JOIN {_AGGREGATE_TABLE} AS aggregate USING (trade_date, source_freq)
        JOIN {_BASIC_SET_TABLE} AS basic USING (trade_date, source_freq)
        WHERE aggregate.aggregation_level = 'partition'
          AND (
            aggregate.row_count <> input.raw_row_count
            OR aggregate.distinct_code_count <> input.present_count
            OR basic.expected_count <> input.expected_count
            OR basic.present_count <> input.present_count
            OR basic.missing_count <> input.missing_count
            OR basic.known_non_required_present_count
              <> input.known_non_required_present_count
            OR basic.nonbasic_count
              <> input.retained_legacy_count + input.unexplained_new_count
          )
        """,
        sql_metrics=sql_metrics,
    ).fetchone()
    if row is None or int(row[0]) != 0:
        raise EtfMinsBootstrapError("etf_mins_raw_observation_manifest_scope_mismatch.")


def _create_boundary_table(connection: Any, *, sql_metrics: dict[str, int]) -> None:
    _execute(
        connection,
        f"""
        CREATE TEMP TABLE {_BOUNDARY_TABLE} AS
        WITH boundary_counts AS (
          SELECT
            source_freq,
            CAST(min_trade_time AS TIME) AS min_clock_time,
            CAST(max_trade_time AS TIME) AS max_clock_time,
            count(*) AS code_day_count
          FROM {_AGGREGATE_TABLE}
          WHERE aggregation_level = 'code_day' AND ts_code IS NOT NULL
          GROUP BY source_freq, min_clock_time, max_clock_time
        )
        SELECT source_freq, min_clock_time, max_clock_time, code_day_count
        FROM boundary_counts
        QUALIFY row_number() OVER (
          PARTITION BY source_freq
          ORDER BY code_day_count DESC, min_clock_time, max_clock_time
        ) = 1
        """,
        sql_metrics=sql_metrics,
    )


def _grid_profile_sql(raw_files_sql: str) -> str:
    return f"""
    WITH raw_rows AS (
      SELECT
        i.trade_date,
        i.source_freq,
        r.ts_code,
        CAST(r.trade_time AS TIME) AS clock_time
      FROM {_INPUT_TABLE} AS i
      JOIN {raw_files_sql} AS r
        ON r.filename = i.raw_absolute_path
      WHERE r.ts_code IS NOT NULL AND r.trade_time IS NOT NULL
    ),
    totals AS (
      SELECT source_freq, count(DISTINCT (trade_date, ts_code)) AS code_day_count
      FROM raw_rows
      GROUP BY source_freq
    ),
    coverage AS (
      SELECT
        source_freq,
        clock_time,
        count(DISTINCT (trade_date, ts_code)) AS code_day_count,
        min(trade_date) AS first_trade_date,
        max(trade_date) AS last_trade_date
      FROM raw_rows
      GROUP BY source_freq, clock_time
    )
    SELECT
      {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION}::INTEGER AS schema_version,
      (SELECT min(input_manifest_hash) FROM {_INPUT_TABLE}) AS input_manifest_hash,
      coverage.source_freq,
      CAST(coverage.clock_time AS VARCHAR) AS clock_time,
      coverage.code_day_count,
      totals.code_day_count AS total_code_day_count,
      coverage.code_day_count::DOUBLE / nullif(totals.code_day_count, 0)
        AS coverage_ratio,
      coverage.first_trade_date,
      coverage.last_trade_date
    FROM coverage
    JOIN totals USING (source_freq)
    ORDER BY coverage.source_freq, coverage.clock_time
    """


def _domain_profile_sql() -> str:
    return f"""
    WITH boundary_variants AS (
      SELECT
        a.trade_date,
        a.source_freq,
        count(*) FILTER (
          WHERE CAST(a.min_trade_time AS TIME) IS DISTINCT FROM b.min_clock_time
             OR CAST(a.max_trade_time AS TIME) IS DISTINCT FROM b.max_clock_time
        ) AS boundary_variant_code_day_count
      FROM {_AGGREGATE_TABLE} AS a
      LEFT JOIN {_BOUNDARY_TABLE} AS b USING (source_freq)
      WHERE a.aggregation_level = 'code_day' AND a.ts_code IS NOT NULL
      GROUP BY a.trade_date, a.source_freq
    ),
    date_totals AS (
      SELECT trade_date, sum(raw_row_count) AS date_row_count
      FROM {_INPUT_TABLE}
      GROUP BY trade_date
    )
    SELECT
      {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION}::INTEGER AS schema_version,
      i.input_manifest_hash,
      i.trade_date,
      i.source_freq,
      a.row_count AS raw_row_count,
      a.distinct_code_count,
      a.min_trade_time,
      a.max_trade_time,
      a.null_key_count,
      a.duplicate_key_count,
      a.date_mismatch_count,
      a.freq_mismatch_count,
      a.exchange_mismatch_count,
      a.null_price_count,
      a.nonfinite_price_count,
      a.nonpositive_price_count,
      a.invalid_ohlc_count,
      a.price_domain_anomaly_count,
      a.null_volume_amount_count,
      a.volume_amount_anomaly_count,
      a.zero_volume_bar_count,
      a.invalid_vwap_count,
      a.off_session_time_count,
      a.grid_gap_candidate_count,
      coalesce(v.boundary_variant_code_day_count, 0)
        AS boundary_variant_code_day_count,
      basic.expected_count,
      basic.present_count,
      basic.missing_count,
      basic.known_non_required_present_count,
      i.retained_legacy_count,
      i.unexplained_new_count,
      totals.date_row_count = 0 AS all_frequencies_empty,
      i.raw_row_count = 0 AND totals.date_row_count > 0 AS partial_frequency_empty
    FROM {_INPUT_TABLE} AS i
    JOIN {_AGGREGATE_TABLE} AS a USING (trade_date, source_freq)
    JOIN {_BASIC_SET_TABLE} AS basic USING (trade_date, source_freq)
    JOIN date_totals AS totals USING (trade_date)
    LEFT JOIN boundary_variants AS v USING (trade_date, source_freq)
    WHERE a.aggregation_level = 'partition'
    ORDER BY i.trade_date, i.source_freq
    """


def _partition_observation_sql(candidate_dir: Path) -> str:
    domain_path = candidate_dir / "raw_domain_profile.parquet"
    return f"""
    SELECT
      {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION}::INTEGER AS schema_version,
      i.operation_id,
      i.plan_fingerprint,
      i.input_manifest_hash,
      i.trade_date,
      i.source_freq,
      i.raw_relative_path,
      i.raw_sha256,
      i.raw_size_bytes,
      i.raw_row_count,
      i.basic_raw_snapshot_hash,
      i.basic_silver_content_hash,
      d.distinct_code_count,
      d.min_trade_time,
      d.max_trade_time,
      d.null_key_count,
      d.duplicate_key_count,
      d.date_mismatch_count,
      d.freq_mismatch_count,
      d.exchange_mismatch_count,
      d.price_domain_anomaly_count,
      d.volume_amount_anomaly_count,
      d.zero_volume_bar_count,
      d.invalid_vwap_count,
      d.off_session_time_count,
      d.grid_gap_candidate_count,
      d.boundary_variant_code_day_count,
      d.expected_count,
      d.present_count,
      d.missing_count,
      d.known_non_required_present_count,
      i.retained_legacy_count,
      i.unexplained_new_count,
      d.all_frequencies_empty,
      d.partial_frequency_empty,
      'unclassified'::VARCHAR AS policy_state
    FROM {_INPUT_TABLE} AS i
    JOIN {read_parquet(domain_path, hive_partitioning=False)} AS d
      USING (trade_date, source_freq)
    ORDER BY i.trade_date, i.source_freq
    """


def _issue_details_sql(candidate_dir: Path) -> str:
    code_path = candidate_dir / "raw_code_day_freq_profile.parquet"
    domain_path = candidate_dir / "raw_domain_profile.parquet"
    sample_limit = ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT
    return f"""
    WITH code_profile AS (
      SELECT * FROM {read_parquet(code_path, hive_partitioning=False)}
    ),
    domain_profile AS (
      SELECT * FROM {read_parquet(domain_path, hive_partitioning=False)}
    ),
    boundary_profile AS (
      SELECT
        c.*,
        c.min_clock_time IS DISTINCT FROM b.min_clock_time
          OR c.max_clock_time IS DISTINCT FROM b.max_clock_time AS is_variant
      FROM code_profile AS c
      LEFT JOIN {_BOUNDARY_TABLE} AS b USING (source_freq)
    ),
    code_issues AS (
      SELECT trade_date, source_freq, 'internal_grid_gap_candidate' AS reason_code,
        grid_gap_candidate_count AS issue_count, ts_code
      FROM boundary_profile WHERE grid_gap_candidate_count > 0
      UNION ALL
      SELECT trade_date, source_freq, 'boundary_time_variant_candidate', 1, ts_code
      FROM boundary_profile WHERE is_variant
      UNION ALL
      SELECT trade_date, source_freq, 'zero_volume_bar_observed',
        zero_volume_bar_count, ts_code
      FROM boundary_profile WHERE zero_volume_bar_count > 0
      UNION ALL
      SELECT trade_date, source_freq, 'price_domain_anomaly',
        price_domain_anomaly_count, ts_code
      FROM boundary_profile WHERE price_domain_anomaly_count > 0
      UNION ALL
      SELECT trade_date, source_freq, 'volume_amount_domain_anomaly',
        volume_amount_anomaly_count, ts_code
      FROM boundary_profile WHERE volume_amount_anomaly_count > 0
      UNION ALL
      SELECT trade_date, source_freq, 'vwap_domain_anomaly',
        invalid_vwap_count, ts_code
      FROM boundary_profile WHERE invalid_vwap_count > 0
      UNION ALL
      SELECT trade_date, source_freq, 'off_session_time_observed',
        off_session_time_count, ts_code
      FROM boundary_profile WHERE off_session_time_count > 0
      UNION ALL
      SELECT trade_date, source_freq, 'exchange_identity_anomaly',
        exchange_mismatch_count, ts_code
      FROM boundary_profile WHERE exchange_mismatch_count > 0
    ),
    grouped_code_issues AS (
      SELECT
        trade_date,
        source_freq,
        reason_code,
        sum(issue_count)::BIGINT AS issue_count,
        CAST(to_json(list(ts_code ORDER BY ts_code)[:{sample_limit}]) AS VARCHAR)
          AS sample_json
      FROM code_issues
      GROUP BY trade_date, source_freq, reason_code
    ),
    present_codes AS (
      SELECT DISTINCT trade_date, source_freq, ts_code FROM code_profile
    ),
    expected_codes AS (
      SELECT
        i.trade_date,
        i.source_freq,
        trim(CAST(target.ts_code AS VARCHAR)) AS ts_code
      FROM {_INPUT_TABLE} AS i
      JOIN {_REQUESTABLE_RELATION} AS target
        ON CAST(target.list_date AS DATE) <= CAST(i.trade_date AS DATE)
    ),
    missing_codes AS (
      SELECT expected.trade_date, expected.source_freq, expected.ts_code
      FROM expected_codes AS expected
      LEFT JOIN present_codes AS present
        USING (trade_date, source_freq, ts_code)
      WHERE present.ts_code IS NULL
    ),
    missing_issues AS (
      SELECT
        trade_date,
        source_freq,
        'expected_code_missing' AS reason_code,
        count(*)::BIGINT AS issue_count,
        CAST(to_json(list(ts_code ORDER BY ts_code)[:{sample_limit}]) AS VARCHAR)
          AS sample_json
      FROM missing_codes
      GROUP BY trade_date, source_freq
    ),
    known_non_required_codes AS (
      SELECT present.trade_date, present.source_freq, present.ts_code
      FROM present_codes AS present
      JOIN {_BASIC_ALL_RELATION} AS basic USING (ts_code)
      LEFT JOIN expected_codes AS expected
        USING (trade_date, source_freq, ts_code)
      WHERE expected.ts_code IS NULL
    ),
    known_non_required_issues AS (
      SELECT
        trade_date,
        source_freq,
        'known_non_required_code_present' AS reason_code,
        count(*)::BIGINT AS issue_count,
        CAST(to_json(list(ts_code ORDER BY ts_code)[:{sample_limit}]) AS VARCHAR)
          AS sample_json
      FROM known_non_required_codes
      GROUP BY trade_date, source_freq
    ),
    nonbasic_codes AS (
      SELECT present.trade_date, present.source_freq, present.ts_code
      FROM present_codes AS present
      LEFT JOIN {_BASIC_ALL_RELATION} AS basic USING (ts_code)
      WHERE basic.ts_code IS NULL
    ),
    nonbasic_samples AS (
      SELECT
        trade_date,
        source_freq,
        CAST(to_json(list(ts_code ORDER BY ts_code)[:{sample_limit}]) AS VARCHAR)
          AS sample_json
      FROM nonbasic_codes
      GROUP BY trade_date, source_freq
    ),
    partition_issues AS (
      SELECT trade_date, source_freq, 'all_frequencies_empty' AS reason_code,
        1::BIGINT AS issue_count,
        CAST(to_json([trade_date]) AS VARCHAR) AS sample_json
      FROM domain_profile WHERE all_frequencies_empty
      UNION ALL
      SELECT trade_date, source_freq, 'partial_frequency_empty', 1,
        CAST(to_json([trade_date || '|' || source_freq]) AS VARCHAR)
      FROM domain_profile WHERE partial_frequency_empty
      UNION ALL
      SELECT trade_date, source_freq, 'key_contract_anomaly',
        (null_key_count + duplicate_key_count)::BIGINT,
        '[]'::VARCHAR
      FROM domain_profile WHERE null_key_count + duplicate_key_count > 0
      UNION ALL
      SELECT trade_date, source_freq, 'partition_contract_anomaly',
        (date_mismatch_count + freq_mismatch_count)::BIGINT,
        '[]'::VARCHAR
      FROM domain_profile WHERE date_mismatch_count + freq_mismatch_count > 0
      UNION ALL
      SELECT d.trade_date, d.source_freq, 'retained_legacy_code_present',
        d.retained_legacy_count::BIGINT, coalesce(s.sample_json, '[]')
      FROM domain_profile AS d
      LEFT JOIN nonbasic_samples AS s USING (trade_date, source_freq)
      WHERE d.retained_legacy_count > 0
      UNION ALL
      SELECT d.trade_date, d.source_freq, 'unexplained_new_code_observed',
        d.unexplained_new_count::BIGINT, coalesce(s.sample_json, '[]')
      FROM domain_profile AS d
      LEFT JOIN nonbasic_samples AS s USING (trade_date, source_freq)
      WHERE d.unexplained_new_count > 0
    ),
    all_issues AS (
      SELECT * FROM grouped_code_issues
      UNION ALL SELECT * FROM missing_issues
      UNION ALL SELECT * FROM known_non_required_issues
      UNION ALL SELECT * FROM partition_issues
    )
    SELECT
      {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION}::INTEGER AS schema_version,
      (SELECT min(input_manifest_hash) FROM {_INPUT_TABLE}) AS input_manifest_hash,
      trade_date,
      source_freq,
      reason_code,
      issue_count,
      sample_json
    FROM all_issues
    WHERE issue_count > 0
    ORDER BY trade_date, source_freq, reason_code
    """


def _copy_profile(
    connection: Any,
    select_sql: str,
    target_path: Path,
    *,
    sql_metrics: dict[str, int],
) -> None:
    _execute(
        connection,
        copy_query_to_parquet(select_sql, target_path),
        sql_metrics=sql_metrics,
    )


def _load_artifact_row_counts(
    connection: Any,
    *,
    candidate_dir: Path,
    sql_metrics: dict[str, int],
) -> dict[str, int]:
    expressions = ", ".join(
        "(SELECT count(*) FROM "
        f"{read_parquet(candidate_dir / filename, hive_partitioning=False)})"
        f" AS count_{index}"
        for index, filename in enumerate(_PARQUET_FILENAMES)
    )
    row = _execute(
        connection,
        f"SELECT {expressions}",
        sql_metrics=sql_metrics,
    ).fetchone()
    if row is None:
        raise EtfMinsBootstrapError("etf_mins_raw_observation_artifact_counts_missing.")
    return {
        filename: int(row[index]) for index, filename in enumerate(_PARQUET_FILENAMES)
    }


def _load_distribution_summary(
    connection: Any,
    *,
    candidate_dir: Path,
    sql_metrics: dict[str, int],
) -> dict[str, object]:
    code_path = candidate_dir / "raw_code_day_freq_profile.parquet"
    domain_path = candidate_dir / "raw_domain_profile.parquet"
    issue_path = candidate_dir / "raw_issue_details.parquet"
    distribution_rows = _execute(
        connection,
        f"""
        SELECT
          substr(trade_date, 1, 4) AS trade_year,
          source_freq,
          exchange,
          count(*) AS code_day_count,
          sum(row_count) AS row_count
        FROM {read_parquet(code_path, hive_partitioning=False)}
        GROUP BY trade_year, source_freq, exchange
        ORDER BY trade_year, source_freq, exchange
        """,
        sql_metrics=sql_metrics,
    ).fetchall()
    partition_row = _execute(
        connection,
        f"""
        SELECT
          count(*) AS partition_count,
          count(*) FILTER (WHERE raw_row_count = 0) AS zero_row_partition_count,
          count(DISTINCT trade_date) FILTER (WHERE all_frequencies_empty)
            AS all_frequencies_empty_date_count,
          count(DISTINCT trade_date) FILTER (WHERE partial_frequency_empty)
            AS partial_frequency_empty_date_count,
          sum(raw_row_count) AS raw_row_count,
          sum(distinct_code_count) AS code_day_count
        FROM {read_parquet(domain_path, hive_partitioning=False)}
        """,
        sql_metrics=sql_metrics,
    ).fetchone()
    issue_rows = _execute(
        connection,
        f"""
        SELECT reason_code, sum(issue_count) AS issue_count, count(*) AS partition_count
        FROM {read_parquet(issue_path, hive_partitioning=False)}
        GROUP BY reason_code
        ORDER BY reason_code
        """,
        sql_metrics=sql_metrics,
    ).fetchall()
    if partition_row is None:
        raise EtfMinsBootstrapError(
            "etf_mins_raw_observation_partition_summary_missing."
        )
    return {
        "partition_count": int(partition_row[0]),
        "zero_row_partition_count": int(partition_row[1]),
        "all_frequencies_empty_date_count": int(partition_row[2]),
        "partial_frequency_empty_date_count": int(partition_row[3]),
        "raw_row_count": int(partition_row[4] or 0),
        "code_day_count": int(partition_row[5] or 0),
        "year_exchange_frequency": [
            {
                "trade_year": str(row[0]),
                "source_freq": str(row[1]),
                "exchange": None if row[2] is None else str(row[2]),
                "code_day_count": int(row[3]),
                "row_count": int(row[4]),
            }
            for row in distribution_rows
        ],
        "issue_counts": [
            {
                "reason_code": str(row[0]),
                "issue_count": int(row[1]),
                "partition_count": int(row[2]),
            }
            for row in issue_rows
        ],
    }


def _load_prod_callback_candidates(
    connection: Any,
    *,
    candidate_dir: Path,
    sql_metrics: dict[str, int],
) -> list[dict[str, str]]:
    code_path = candidate_dir / "raw_code_day_freq_profile.parquet"
    rows = _execute(
        connection,
        f"""
        SELECT trade_date, source_freq, ts_code,
          CASE
            WHEN price_domain_anomaly_count > 0 THEN 'price_domain_anomaly'
            WHEN volume_amount_anomaly_count > 0
              THEN 'volume_amount_domain_anomaly'
            WHEN invalid_vwap_count > 0 THEN 'vwap_domain_anomaly'
            WHEN off_session_time_count > 0 THEN 'off_session_time_observed'
            WHEN exchange_mismatch_count > 0 THEN 'exchange_identity_anomaly'
            ELSE 'internal_grid_gap_candidate'
          END AS reason_code
        FROM {read_parquet(code_path, hive_partitioning=False)}
        WHERE price_domain_anomaly_count > 0
           OR volume_amount_anomaly_count > 0
           OR invalid_vwap_count > 0
           OR off_session_time_count > 0
           OR exchange_mismatch_count > 0
           OR grid_gap_candidate_count > 0
        ORDER BY trade_date, source_freq, ts_code, reason_code
        LIMIT {ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT}
        """,
        sql_metrics=sql_metrics,
    ).fetchall()
    return [
        {
            "trade_date": str(row[0]),
            "source_freq": str(row[1]),
            "ts_code": str(row[2]),
            "reason_code": str(row[3]),
        }
        for row in rows
    ]


def _build_proposed_policy(
    *,
    operation_id: str,
    input_manifest_hash: str,
    observation_summary_hash: str,
    issue_counts: object,
) -> dict[str, object]:
    observed_codes = {
        str(row["reason_code"]) for row in issue_counts if isinstance(row, Mapping)
    }
    recommendations = []
    for reason_code in ETF_MINS_RAW_OBSERVATION_REASON_CODES:
        if reason_code in {
            "all_frequencies_empty",
            "expected_code_missing",
            "price_domain_anomaly",
            "volume_amount_domain_anomaly",
            "vwap_domain_anomaly",
            "key_contract_anomaly",
            "partition_contract_anomaly",
            "exchange_identity_anomaly",
            "unexplained_new_code_observed",
        }:
            suggested_class = "candidate_blocking"
        elif reason_code in {
            "partial_frequency_empty",
            "internal_grid_gap_candidate",
            "boundary_time_variant_candidate",
            "off_session_time_observed",
        }:
            suggested_class = "requires_distribution_review"
        else:
            suggested_class = "candidate_warning"
        recommendations.append(
            {
                "reason_code": reason_code,
                "observed": reason_code in observed_codes,
                "suggested_policy_class": suggested_class,
            }
        )
    payload: dict[str, object] = {
        "proposal_kind": ETF_MINS_RAW_PROPOSED_POLICY_KIND,
        "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
        "operation_id": operation_id,
        "input_manifest_hash": input_manifest_hash,
        "observation_summary_hash": observation_summary_hash,
        "effective": False,
        "requires_admin_approval": True,
        "recommendations": recommendations,
    }
    payload["proposed_policy_hash"] = compute_etf_mins_bootstrap_payload_hash(payload)
    return payload


def _artifact_metadata(
    candidate_dir: Path,
    *,
    row_counts: Mapping[str, int],
) -> dict[str, object]:
    return {
        filename: {
            "row_count": int(row_counts[filename]),
            "size_bytes": (candidate_dir / filename).stat().st_size,
            "sha256": _sha256_file(candidate_dir / filename),
        }
        for filename in _PARQUET_FILENAMES
    }


def _load_existing_observation(
    *,
    output_dir: Path,
    operation_id: str,
    input_manifest_hash: str,
    raw_final_report_hash: str,
) -> EtfMinsRawObservationResult:
    if not output_dir.is_dir():
        raise EtfMinsBootstrapError(
            "etf_mins_raw_observation_output_conflict: existing output is not a "
            "complete observation directory."
        )
    summary_path = output_dir / "raw_observation_summary.json"
    proposed_path = output_dir / "proposed_policy.json"
    summary = _load_json(summary_path)
    proposed = _load_json(proposed_path)
    expected_summary_hash = compute_etf_mins_bootstrap_payload_hash(
        summary,
        self_hash_field="observation_summary_hash",
    )
    if (
        summary.get("observation_kind") != ETF_MINS_RAW_OBSERVATION_KIND
        or int(summary.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION
        or summary.get("operation_id") != operation_id
        or summary.get("input_manifest_hash") != input_manifest_hash
        or summary.get("raw_final_report_hash") != raw_final_report_hash
        or summary.get("partition_state") != "unclassified"
        or summary.get("observation_summary_hash") != expected_summary_hash
    ):
        raise EtfMinsBootstrapError("etf_mins_raw_observation_summary_conflict.")
    expected_proposed_hash = compute_etf_mins_bootstrap_payload_hash(
        proposed,
        self_hash_field="proposed_policy_hash",
    )
    if (
        proposed.get("proposal_kind") != ETF_MINS_RAW_PROPOSED_POLICY_KIND
        or int(proposed.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION
        or proposed.get("operation_id") != operation_id
        or proposed.get("input_manifest_hash") != input_manifest_hash
        or proposed.get("observation_summary_hash") != expected_summary_hash
        or proposed.get("effective") is not False
        or proposed.get("proposed_policy_hash") != expected_proposed_hash
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_raw_observation_proposed_policy_conflict."
        )
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(_PARQUET_FILENAMES):
        raise EtfMinsBootstrapError(
            "etf_mins_raw_observation_artifact_manifest_invalid."
        )
    for filename in _PARQUET_FILENAMES:
        metadata = artifacts.get(filename)
        path = output_dir / filename
        if (
            not isinstance(metadata, Mapping)
            or not path.is_file()
            or int(metadata.get("size_bytes", -1)) != path.stat().st_size
            or metadata.get("sha256") != _sha256_file(path)
        ):
            raise EtfMinsBootstrapError("etf_mins_raw_observation_artifact_changed.")
    if "decision" in summary or "silver_eligible" in summary:
        raise EtfMinsBootstrapError(
            "etf_mins_raw_observation_premature_decision_detected."
        )
    return EtfMinsRawObservationResult(
        operation_id=operation_id,
        output_dir=output_dir,
        raw_observation_summary_path=summary_path,
        proposed_policy_path=proposed_path,
        input_manifest_hash=input_manifest_hash,
        observation_summary_hash=expected_summary_hash,
        proposed_policy_hash=expected_proposed_hash,
        scanned_file_count=int(summary["scanned_file_count"]),
        scanned_row_count=int(summary["scanned_row_count"]),
        scanned_byte_count=int(summary["scanned_byte_count"]),
        issue_row_count=int(artifacts["raw_issue_details.parquet"]["row_count"]),
        raw_scan_query_count=int(summary["raw_scan_query_count"]),
        analysis_sql_statement_count=int(summary["analysis_sql_statement_count"]),
        peak_temp_dir_size_bytes=int(summary["peak_temp_dir_size_bytes"]),
        elapsed_seconds=float(summary["elapsed_seconds"]),
    )


def _execute(
    connection: Any,
    sql: str,
    *,
    sql_metrics: dict[str, int],
) -> Any:
    sql_metrics["analysis_sql_statement_count"] += 1
    return connection.execute(sql)


def _execute_profiled(
    connection: Any,
    sql: str,
    profile_path: Path,
    *,
    sql_metrics: dict[str, int],
) -> None:
    connection.execute("PRAGMA enable_profiling='json'")
    connection.execute(f"PRAGMA profiling_output={duckdb_string(profile_path)}")
    try:
        _execute(connection, sql, sql_metrics=sql_metrics)
    finally:
        connection.execute("PRAGMA disable_profiling")
    if not profile_path.is_file():
        raise EtfMinsBootstrapError("etf_mins_raw_observation_query_profile_missing.")
    profile = _load_json(profile_path)
    sql_metrics["raw_scan_query_count"] += 1
    sql_metrics["peak_temp_dir_size_bytes"] = max(
        sql_metrics["peak_temp_dir_size_bytes"],
        int(profile.get("system_peak_temp_dir_size", 0)),
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EtfMinsBootstrapError(
            f"etf_mins_raw_observation_json_unreadable: {path.name}."
        ) from error
    if not isinstance(payload, dict):
        raise EtfMinsBootstrapError(
            f"etf_mins_raw_observation_json_invalid: {path.name}."
        )
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ETF_MINS_RAW_OBSERVATION_KIND",
    "ETF_MINS_RAW_OBSERVATION_REASON_CODES",
    "ETF_MINS_RAW_PROPOSED_POLICY_KIND",
    "EtfMinsRawObservationResult",
    "observe_etf_mins_raw",
]
