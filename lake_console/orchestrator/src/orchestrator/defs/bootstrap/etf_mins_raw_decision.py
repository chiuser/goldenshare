"""Registered N3B admission decisions for ETF minute Raw observations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
    EtfMinsBootstrapError,
    compute_etf_mins_bootstrap_payload_hash,
)
from orchestrator.defs.bootstrap.etf_mins_raw_observation import (
    ETF_MINS_RAW_OBSERVATION_ARTIFACT_FILENAMES,
    ETF_MINS_RAW_OBSERVATION_KIND,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_RAW_OBSERVATION_REASON_CODES,
    ETF_MINS_SOURCE_FREQS,
    EtfMinsRawDecisionPolicy,
    get_etf_mins_raw_decision_policy,
)

ETF_MINS_RAW_DECISION_KIND = "etf_mins_raw_decision"
ETF_MINS_RAW_DECISION_MANIFEST_FILENAME = "raw_partition_decision_manifest.parquet"
ETF_MINS_RAW_DECISION_SUMMARY_FILENAME = "raw_decision_summary.json"

_BASE_TABLE = "etf_mins_raw_decision_base"


@dataclass(frozen=True, slots=True)
class EtfMinsRawDecisionResult:
    operation_id: str
    output_dir: Path
    raw_partition_decision_manifest_path: Path
    raw_decision_summary_path: Path
    observation_summary_hash: str
    approved_policy_version: str
    approved_policy_hash: str
    raw_partition_decision_manifest_hash: str
    raw_decision_summary_hash: str
    partition_count: int
    green_partition_count: int
    warn_partition_count: int
    blocked_partition_count: int
    silver_eligible_partition_count: int
    analysis_sql_statement_count: int
    elapsed_seconds: float


def decide_etf_mins_raw(
    *,
    observation_summary_path: Path,
    approved_policy_version: str,
    output_dir: Path,
) -> EtfMinsRawDecisionResult:
    """Classify immutable N3A artifacts without reading Prod or Raw files."""

    started_at = perf_counter()
    operation_root = _validate_decision_paths(
        observation_summary_path=observation_summary_path,
        output_dir=output_dir,
    )
    summary = _load_observation_summary(observation_summary_path)
    observation_summary_hash = str(summary["observation_summary_hash"])
    operation_id = str(summary["operation_id"])
    if operation_root.name != f"operation_id={operation_id}":
        raise EtfMinsBootstrapError("etf_mins_raw_decision_operation_id_mismatch.")
    policy = _load_registered_policy(approved_policy_version)
    artifact_paths = _validate_observation_artifact_files(
        observation_dir=observation_summary_path.parent,
        summary=summary,
    )

    manifest_path = output_dir / ETF_MINS_RAW_DECISION_MANIFEST_FILENAME
    decision_summary_path = output_dir / ETF_MINS_RAW_DECISION_SUMMARY_FILENAME
    if manifest_path.exists() or decision_summary_path.exists():
        if not manifest_path.is_file() or not decision_summary_path.is_file():
            raise EtfMinsBootstrapError(
                "etf_mins_raw_decision_output_conflict: decision output is partial."
            )
        return _load_existing_decision(
            output_dir=output_dir,
            operation_id=operation_id,
            observation_summary_hash=observation_summary_hash,
            policy=policy,
        )

    candidate_dir = operation_root / f".raw-decide.candidate-{uuid.uuid4().hex}"
    candidate_dir.mkdir(parents=False, exist_ok=False)
    candidate_manifest_path = candidate_dir / ETF_MINS_RAW_DECISION_MANIFEST_FILENAME
    candidate_summary_path = candidate_dir / ETF_MINS_RAW_DECISION_SUMMARY_FILENAME
    sql_statement_count = 0
    try:
        with connect_configured_duckdb() as connection:
            sql_statement_count += _validate_observation_artifact_relations(
                connection,
                summary=summary,
                artifact_paths=artifact_paths,
            )
            connection.execute(
                _create_decision_base_sql(
                    summary=summary,
                    artifact_paths=artifact_paths,
                    policy=policy,
                )
            )
            sql_statement_count += 1
            _validate_grid_anomaly_localization(connection)
            sql_statement_count += 1
            connection.execute(
                copy_query_to_parquet(
                    _decision_manifest_sql(policy),
                    candidate_manifest_path,
                )
            )
            sql_statement_count += 1
            decision_counts = connection.execute(
                _decision_counts_sql(candidate_manifest_path)
            ).fetchone()
            sql_statement_count += 1
            if decision_counts is None:
                raise EtfMinsBootstrapError("etf_mins_raw_decision_counts_missing.")
            reason_summary = _load_decision_reason_summary(
                connection,
                manifest_path=candidate_manifest_path,
                policy=policy,
            )
            sql_statement_count += 1
            decision_samples = _load_decision_samples(
                connection,
                manifest_path=candidate_manifest_path,
            )
            sql_statement_count += 1

        partition_count = int(decision_counts[0])
        green_count = int(decision_counts[1])
        warn_count = int(decision_counts[2])
        blocked_count = int(decision_counts[3])
        eligible_count = int(decision_counts[4])
        expected_partition_count = int(
            summary["observed_distributions"]["partition_count"]  # type: ignore[index]
        )
        if (
            partition_count != expected_partition_count
            or green_count + warn_count + blocked_count != partition_count
            or eligible_count != green_count + warn_count
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_raw_decision_partition_coverage_invalid."
            )

        manifest_hash = _sha256_file(candidate_manifest_path)
        elapsed_seconds = round(perf_counter() - started_at, 6)
        decision_payload: dict[str, object] = {
            "decision_kind": ETF_MINS_RAW_DECISION_KIND,
            "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
            "operation_id": operation_id,
            "plan_fingerprint": str(summary["plan_fingerprint"]),
            "input_manifest_hash": str(summary["input_manifest_hash"]),
            "observation_summary_hash": observation_summary_hash,
            "approved_policy_version": policy.version,
            "approved_policy_hash": policy.policy_hash,
            "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "partition_count": partition_count,
            "decision_counts": {
                "green": green_count,
                "warn": warn_count,
                "blocked": blocked_count,
            },
            "silver_eligible_partition_count": eligible_count,
            "raw_partition_decision_manifest": {
                "filename": ETF_MINS_RAW_DECISION_MANIFEST_FILENAME,
                "row_count": partition_count,
                "size_bytes": candidate_manifest_path.stat().st_size,
                "sha256": manifest_hash,
            },
            "decision_reason_summary": reason_summary,
            "decision_samples": decision_samples,
            "sample_limit": ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
            "input_artifact_file_count": len(artifact_paths),
            "raw_scan_query_count": 0,
            "prod_query_count": 0,
            "analysis_sql_statement_count": sql_statement_count,
            "elapsed_seconds": elapsed_seconds,
        }
        decision_payload["raw_decision_summary_hash"] = (
            compute_etf_mins_bootstrap_payload_hash(decision_payload)
        )
        _write_json(candidate_summary_path, decision_payload)

        if manifest_path.exists() or decision_summary_path.exists():
            raise EtfMinsBootstrapError(
                "etf_mins_raw_decision_output_conflict: output appeared while "
                "the candidate was being built."
            )
        os.replace(candidate_manifest_path, manifest_path)
        os.replace(candidate_summary_path, decision_summary_path)
        candidate_dir.rmdir()
    except Exception:
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)
        raise

    return _load_existing_decision(
        output_dir=output_dir,
        operation_id=operation_id,
        observation_summary_hash=observation_summary_hash,
        policy=policy,
    )


def _validate_decision_paths(
    *,
    observation_summary_path: Path,
    output_dir: Path,
) -> Path:
    if not observation_summary_path.is_absolute() or not output_dir.is_absolute():
        raise EtfMinsBootstrapError("etf_mins_raw_decision_path_not_absolute.")
    if (
        observation_summary_path.name != "raw_observation_summary.json"
        or observation_summary_path.parent.name != "raw-observe"
    ):
        raise EtfMinsBootstrapError("etf_mins_raw_decision_observation_path_invalid.")
    operation_root = observation_summary_path.parent.parent.resolve(strict=False)
    if output_dir.resolve(strict=False) != operation_root:
        raise EtfMinsBootstrapError(
            "etf_mins_raw_decision_output_path_invalid: output_dir must be the "
            "input operation directory."
        )
    return operation_root


def _load_registered_policy(version: str) -> EtfMinsRawDecisionPolicy:
    try:
        return get_etf_mins_raw_decision_policy(version)
    except ValueError as error:
        raise EtfMinsBootstrapError(
            "etf_mins_raw_decision_policy_not_registered."
        ) from error


def _load_observation_summary(path: Path) -> dict[str, object]:
    summary = _load_json(path, error_prefix="etf_mins_raw_decision_observation")
    expected_hash = compute_etf_mins_bootstrap_payload_hash(
        summary,
        self_hash_field="observation_summary_hash",
    )
    distributions = summary.get("observed_distributions")
    if (
        summary.get("observation_kind") != ETF_MINS_RAW_OBSERVATION_KIND
        or int(summary.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION
        or summary.get("partition_state") != "unclassified"
        or summary.get("observation_summary_hash") != expected_hash
        or not isinstance(distributions, Mapping)
        or int(distributions.get("partition_count", 0)) <= 0
        or "decision" in summary
        or "silver_eligible" in summary
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_raw_decision_observation_summary_invalid."
        )
    for field_name in (
        "operation_id",
        "plan_fingerprint",
        "input_manifest_hash",
        "basic_raw_snapshot_hash",
        "basic_silver_content_hash",
    ):
        if not str(summary.get(field_name) or ""):
            raise EtfMinsBootstrapError(
                f"etf_mins_raw_decision_observation_field_missing: {field_name}."
            )
    return summary


def _validate_observation_artifact_files(
    *,
    observation_dir: Path,
    summary: Mapping[str, object],
) -> dict[str, Path]:
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(
        ETF_MINS_RAW_OBSERVATION_ARTIFACT_FILENAMES
    ):
        raise EtfMinsBootstrapError("etf_mins_raw_decision_artifact_manifest_invalid.")
    paths: dict[str, Path] = {}
    for filename in ETF_MINS_RAW_OBSERVATION_ARTIFACT_FILENAMES:
        metadata = artifacts.get(filename)
        path = observation_dir / filename
        if (
            not isinstance(metadata, Mapping)
            or not path.is_file()
            or int(metadata.get("row_count", -1)) < 0
            or int(metadata.get("size_bytes", -1)) != path.stat().st_size
            or metadata.get("sha256") != _sha256_file(path)
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_raw_decision_observation_artifact_changed."
            )
        paths[filename] = path
    return paths


def _validate_observation_artifact_relations(
    connection: Any,
    *,
    summary: Mapping[str, object],
    artifact_paths: Mapping[str, Path],
) -> int:
    artifacts = summary["artifacts"]
    input_manifest_hash = str(summary["input_manifest_hash"])
    statement_count = 0
    for filename in ETF_MINS_RAW_OBSERVATION_ARTIFACT_FILENAMES:
        row = connection.execute(
            "SELECT count(*), count(*) FILTER ("
            f"WHERE schema_version <> {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION} "
            "OR input_manifest_hash <> "
            f"{duckdb_string(input_manifest_hash)}) FROM "
            f"{read_parquet(artifact_paths[filename], hive_partitioning=False)}"
        ).fetchone()
        statement_count += 1
        metadata = artifacts[filename]  # type: ignore[index]
        if (
            row is None
            or int(row[0]) != int(metadata["row_count"])  # type: ignore[index]
            or int(row[1]) != 0
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_raw_decision_observation_artifact_contract_invalid."
            )

    observation_path = artifact_paths["raw_partition_observation_manifest.parquet"]
    partition_row = connection.execute(
        "SELECT count(*), count(DISTINCT (trade_date, source_freq)), "
        "count(*) FILTER (WHERE policy_state <> 'unclassified'), "
        "count(DISTINCT source_freq), count(DISTINCT trade_date) "
        f"FROM {read_parquet(observation_path, hive_partitioning=False)}"
    ).fetchone()
    statement_count += 1
    expected_partition_count = int(
        summary["observed_distributions"]["partition_count"]  # type: ignore[index]
    )
    if (
        partition_row is None
        or int(partition_row[0]) != expected_partition_count
        or int(partition_row[1]) != expected_partition_count
        or int(partition_row[2]) != 0
        or int(partition_row[3]) != len(ETF_MINS_SOURCE_FREQS)
        or int(partition_row[4]) * len(ETF_MINS_SOURCE_FREQS)
        != expected_partition_count
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_raw_decision_partition_observation_incomplete."
        )

    for filename, key_sql in (
        (
            "raw_code_day_freq_profile.parquet",
            "(ts_code, trade_date, source_freq)",
        ),
        ("raw_grid_profile.parquet", "(source_freq, clock_time)"),
        (
            "raw_issue_details.parquet",
            "(trade_date, source_freq, reason_code)",
        ),
    ):
        duplicate_row = connection.execute(
            "SELECT count(*) - count(DISTINCT "
            f"{key_sql}) FROM "
            f"{read_parquet(artifact_paths[filename], hive_partitioning=False)}"
        ).fetchone()
        statement_count += 1
        if duplicate_row is None or int(duplicate_row[0]) != 0:
            raise EtfMinsBootstrapError(
                "etf_mins_raw_decision_observation_key_invalid."
            )
    return statement_count


def _create_decision_base_sql(
    *,
    summary: Mapping[str, object],
    artifact_paths: Mapping[str, Path],
    policy: EtfMinsRawDecisionPolicy,
) -> str:
    observation_path = artifact_paths["raw_partition_observation_manifest.parquet"]
    code_path = artifact_paths["raw_code_day_freq_profile.parquet"]
    grid_path = artifact_paths["raw_grid_profile.parquet"]
    issue_path = artifact_paths["raw_issue_details.parquet"]
    expected_grid_values = ", ".join(
        f"({duckdb_string(source_freq)}, {duckdb_string(clock_time)})"
        for source_freq, clock_times in policy.expected_clock_times_by_source_freq
        for clock_time in clock_times
    )
    expected_freq_values = ", ".join(
        "("
        f"{duckdb_string(source_freq)}, {len(clock_times)}, "
        f"{duckdb_string(clock_times[0])}, {duckdb_string(clock_times[-1])}"
        ")"
        for source_freq, clock_times in policy.expected_clock_times_by_source_freq
    )
    return f"""
    CREATE TEMP TABLE {_BASE_TABLE} AS
    WITH expected_grid(source_freq, clock_time) AS (
      VALUES {expected_grid_values}
    ),
    expected_freq(source_freq, expected_clock_count, min_clock_time,
                  max_clock_time) AS (
      VALUES {expected_freq_values}
    ),
    observed_grid AS (
      SELECT source_freq, clock_time, code_day_count, total_code_day_count,
        coverage_ratio
      FROM {read_parquet(grid_path, hive_partitioning=False)}
    ),
    missing_grid AS (
      SELECT expected.source_freq, count(*) AS missing_clock_count
      FROM expected_grid AS expected
      LEFT JOIN observed_grid AS observed USING (source_freq, clock_time)
      WHERE observed.clock_time IS NULL
      GROUP BY expected.source_freq
    ),
    unexpected_grid AS (
      SELECT observed.source_freq, count(*) AS unexpected_clock_count
      FROM observed_grid AS observed
      LEFT JOIN expected_grid AS expected USING (source_freq, clock_time)
      WHERE expected.clock_time IS NULL
      GROUP BY observed.source_freq
    ),
    incomplete_grid AS (
      SELECT source_freq, count(*) AS incomplete_clock_count
      FROM observed_grid
      WHERE coverage_ratio <> 1.0 OR code_day_count <> total_code_day_count
      GROUP BY source_freq
    ),
    grid_contract AS (
      SELECT
        expected.source_freq,
        coalesce(missing.missing_clock_count, 0)::BIGINT AS missing_clock_count,
        coalesce(unexpected.unexpected_clock_count, 0)::BIGINT
          AS unexpected_clock_count,
        coalesce(incomplete.incomplete_clock_count, 0)::BIGINT
          AS incomplete_clock_count
      FROM expected_freq AS expected
      LEFT JOIN missing_grid AS missing USING (source_freq)
      LEFT JOIN unexpected_grid AS unexpected USING (source_freq)
      LEFT JOIN incomplete_grid AS incomplete USING (source_freq)
    ),
    code_profile AS (
      SELECT * FROM {read_parquet(code_path, hive_partitioning=False)}
    ),
    code_day_facts AS (
      SELECT
        code.trade_date,
        code.source_freq,
        count(*) FILTER (
          WHERE code.row_count <> expected.expected_clock_count
             OR code.distinct_time_count <> expected.expected_clock_count
             OR CAST(code.min_clock_time AS TIME)
                <> CAST(expected.min_clock_time AS TIME)
             OR CAST(code.max_clock_time AS TIME)
                <> CAST(expected.max_clock_time AS TIME)
             OR code.grid_gap_candidate_count <> 1
        )::BIGINT AS code_day_grid_anomaly_count
      FROM code_profile AS code
      JOIN expected_freq AS expected USING (source_freq)
      GROUP BY code.trade_date, code.source_freq
    ),
    full_zero_volume_etf_days AS (
      SELECT ts_code, trade_date
      FROM code_profile
      GROUP BY ts_code, trade_date
      HAVING count(DISTINCT source_freq) = {len(ETF_MINS_SOURCE_FREQS)}
        AND count(*) = {len(ETF_MINS_SOURCE_FREQS)}
        AND count(*) FILTER (
          WHERE row_count > 0 AND zero_volume_bar_count = row_count
        ) = {len(ETF_MINS_SOURCE_FREQS)}
    ),
    full_zero_volume_partition_facts AS (
      SELECT zero_day.trade_date, expected.source_freq,
        count(*)::BIGINT AS full_zero_volume_etf_day_observed_count
      FROM full_zero_volume_etf_days AS zero_day
      CROSS JOIN expected_freq AS expected
      GROUP BY zero_day.trade_date, expected.source_freq
    ),
    observed_reasons AS (
      SELECT trade_date, source_freq,
        CAST(to_json(list(reason_code ORDER BY reason_code)) AS VARCHAR)
          AS observed_reason_codes_json
      FROM {read_parquet(issue_path, hive_partitioning=False)}
      GROUP BY trade_date, source_freq
    )
    SELECT
      {ETF_MINS_BOOTSTRAP_SCHEMA_VERSION}::INTEGER AS schema_version,
      observation.operation_id,
      observation.plan_fingerprint,
      observation.input_manifest_hash,
      {duckdb_string(str(summary["observation_summary_hash"]))}
        AS observation_summary_hash,
      {duckdb_string(policy.version)} AS approved_policy_version,
      {duckdb_string(policy.policy_hash)} AS approved_policy_hash,
      observation.trade_date,
      observation.source_freq,
      observation.raw_relative_path,
      observation.raw_sha256,
      observation.raw_size_bytes,
      observation.raw_row_count,
      observation.basic_raw_snapshot_hash,
      observation.basic_silver_content_hash,
      CAST(observation.all_frequencies_empty AS BIGINT)
        AS all_frequencies_empty_count,
      CAST(observation.partial_frequency_empty AS BIGINT)
        AS partial_frequency_empty_count,
      observation.missing_count AS expected_code_missing_count,
      observation.grid_gap_candidate_count
        AS internal_grid_gap_candidate_count,
      observation.boundary_variant_code_day_count
        AS boundary_time_variant_candidate_count,
      observation.zero_volume_bar_count AS zero_volume_bar_observed_count,
      observation.price_domain_anomaly_count AS price_domain_anomaly_count,
      observation.volume_amount_anomaly_count
        AS volume_amount_domain_anomaly_count,
      observation.invalid_vwap_count AS vwap_domain_anomaly_count,
      observation.off_session_time_count AS off_session_time_observed_count,
      observation.known_non_required_present_count
        AS known_non_required_code_present_count,
      observation.retained_legacy_count AS retained_legacy_code_present_count,
      observation.unexplained_new_count
        AS unexplained_new_code_observed_count,
      observation.null_key_count + observation.duplicate_key_count
        AS key_contract_anomaly_count,
      observation.date_mismatch_count + observation.freq_mismatch_count
        AS partition_contract_anomaly_count,
      observation.exchange_mismatch_count AS exchange_identity_anomaly_count,
      coalesce(zero_day.full_zero_volume_etf_day_observed_count, 0)::BIGINT
        AS full_zero_volume_etf_day_observed_count,
      coalesce(code.code_day_grid_anomaly_count, 0)::BIGINT
        AS minute_grid_contract_anomaly_count,
      (
        grid.missing_clock_count
        + grid.unexpected_clock_count
        + grid.incomplete_clock_count
      )::BIGINT AS global_grid_contract_anomaly_count,
      coalesce(reasons.observed_reason_codes_json, '[]')
        AS observed_reason_codes_json
    FROM {read_parquet(observation_path, hive_partitioning=False)} AS observation
    JOIN grid_contract AS grid USING (source_freq)
    LEFT JOIN code_day_facts AS code USING (trade_date, source_freq)
    LEFT JOIN full_zero_volume_partition_facts AS zero_day
      USING (trade_date, source_freq)
    LEFT JOIN observed_reasons AS reasons USING (trade_date, source_freq)
    """


def _validate_grid_anomaly_localization(connection: Any) -> None:
    rows = connection.execute(
        "SELECT source_freq FROM "
        f"{_BASE_TABLE} GROUP BY source_freq "
        "HAVING max(global_grid_contract_anomaly_count) > 0 "
        "AND sum(minute_grid_contract_anomaly_count) = 0 "
        "ORDER BY source_freq"
    ).fetchall()
    if rows:
        raise EtfMinsBootstrapError("etf_mins_raw_decision_grid_anomaly_not_locatable.")


def _decision_manifest_sql(policy: EtfMinsRawDecisionPolicy) -> str:
    reason_selects = []
    for priority, reason_code in enumerate(policy.blocking_reason_codes):
        reason_selects.append(
            "SELECT trade_date, source_freq, "
            f"{duckdb_string(reason_code)} AS reason_code, "
            f"{priority}::INTEGER AS reason_order, 'blocked' AS severity "
            f"FROM {_BASE_TABLE} WHERE {reason_code}_count > 0"
        )
    warning_offset = len(policy.blocking_reason_codes)
    for offset, reason_code in enumerate(policy.warning_reason_codes):
        reason_selects.append(
            "SELECT trade_date, source_freq, "
            f"{duckdb_string(reason_code)} AS reason_code, "
            f"{warning_offset + offset}::INTEGER AS reason_order, "
            "'warn' AS severity "
            f"FROM {_BASE_TABLE} WHERE {reason_code}_count > 0"
        )
    reason_sql = " UNION ALL ".join(reason_selects)
    observation_count_columns = ",\n      ".join(
        f"base.{reason_code}_count"
        for reason_code in ETF_MINS_RAW_OBSERVATION_REASON_CODES
    )
    return f"""
    WITH reason_rows AS (
      {reason_sql}
    ),
    reason_groups AS (
      SELECT
        trade_date,
        source_freq,
        CAST(to_json(list(reason_code ORDER BY reason_order)) AS VARCHAR)
          AS decision_reason_codes_json,
        count(*) FILTER (WHERE severity = 'blocked') AS blocked_reason_count,
        count(*) FILTER (WHERE severity = 'warn') AS warning_reason_count
      FROM reason_rows
      GROUP BY trade_date, source_freq
    )
    SELECT
      base.schema_version,
      base.operation_id,
      base.plan_fingerprint,
      base.input_manifest_hash,
      base.observation_summary_hash,
      base.approved_policy_version,
      base.approved_policy_hash,
      base.trade_date,
      base.source_freq,
      base.raw_relative_path,
      base.raw_sha256,
      base.raw_size_bytes,
      base.raw_row_count,
      base.basic_raw_snapshot_hash,
      base.basic_silver_content_hash,
      {observation_count_columns},
      base.full_zero_volume_etf_day_observed_count,
      base.minute_grid_contract_anomaly_count,
      base.global_grid_contract_anomaly_count,
      base.observed_reason_codes_json,
      coalesce(reasons.decision_reason_codes_json, '[]')
        AS decision_reason_codes_json,
      CASE
        WHEN coalesce(reasons.blocked_reason_count, 0) > 0 THEN 'blocked'
        WHEN coalesce(reasons.warning_reason_count, 0) > 0 THEN 'warn'
        ELSE 'green'
      END AS decision,
      coalesce(reasons.blocked_reason_count, 0) = 0 AS silver_eligible
    FROM {_BASE_TABLE} AS base
    LEFT JOIN reason_groups AS reasons USING (trade_date, source_freq)
    ORDER BY base.trade_date, base.source_freq
    """


def _decision_counts_sql(manifest_path: Path) -> str:
    return f"""
    SELECT
      count(*),
      count(*) FILTER (WHERE decision = 'green'),
      count(*) FILTER (WHERE decision = 'warn'),
      count(*) FILTER (WHERE decision = 'blocked'),
      count(*) FILTER (WHERE silver_eligible)
    FROM {read_parquet(manifest_path, hive_partitioning=False)}
    """


def _load_decision_reason_summary(
    connection: Any,
    *,
    manifest_path: Path,
    policy: EtfMinsRawDecisionPolicy,
) -> list[dict[str, object]]:
    reason_codes = policy.blocking_reason_codes + policy.warning_reason_codes
    selects = []
    for priority, reason_code in enumerate(reason_codes):
        severity = "blocked" if reason_code in policy.blocking_reason_codes else "warn"
        selects.append(
            "SELECT "
            f"{priority}::INTEGER AS reason_order, "
            f"{duckdb_string(reason_code)} AS reason_code, "
            f"{duckdb_string(severity)} AS severity, "
            "count(*) AS partition_count, "
            f"sum({reason_code}_count) AS issue_count, "
            "CAST(to_json(list(trade_date || '|' || source_freq "
            f"ORDER BY trade_date, source_freq)[:{ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT}]) "
            "AS VARCHAR) AS sample_json FROM "
            f"{read_parquet(manifest_path, hive_partitioning=False)} "
            f"WHERE {reason_code}_count > 0"
        )
    rows = connection.execute(
        "SELECT reason_code, severity, partition_count, issue_count, sample_json "
        f"FROM ({' UNION ALL '.join(selects)}) AS reasons "
        "WHERE partition_count > 0 ORDER BY reason_order"
    ).fetchall()
    return [
        {
            "reason_code": str(row[0]),
            "severity": str(row[1]),
            "partition_count": int(row[2]),
            "issue_count": int(row[3]),
            "samples": json.loads(str(row[4])),
        }
        for row in rows
    ]


def _load_decision_samples(
    connection: Any,
    *,
    manifest_path: Path,
) -> dict[str, list[str]]:
    rows = connection.execute(
        "SELECT decision, CAST(to_json(list(trade_date || '|' || source_freq "
        f"ORDER BY trade_date, source_freq)[:{ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT}]) "
        "AS VARCHAR) FROM "
        f"{read_parquet(manifest_path, hive_partitioning=False)} "
        "GROUP BY decision ORDER BY decision"
    ).fetchall()
    return {str(row[0]): json.loads(str(row[1])) for row in rows}


def _load_existing_decision(
    *,
    output_dir: Path,
    operation_id: str,
    observation_summary_hash: str,
    policy: EtfMinsRawDecisionPolicy,
) -> EtfMinsRawDecisionResult:
    manifest_path = output_dir / ETF_MINS_RAW_DECISION_MANIFEST_FILENAME
    summary_path = output_dir / ETF_MINS_RAW_DECISION_SUMMARY_FILENAME
    summary = _load_json(summary_path, error_prefix="etf_mins_raw_decision")
    expected_summary_hash = compute_etf_mins_bootstrap_payload_hash(
        summary,
        self_hash_field="raw_decision_summary_hash",
    )
    manifest = summary.get("raw_partition_decision_manifest")
    decision_counts = summary.get("decision_counts")
    if (
        summary.get("decision_kind") != ETF_MINS_RAW_DECISION_KIND
        or int(summary.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION
        or summary.get("operation_id") != operation_id
        or summary.get("observation_summary_hash") != observation_summary_hash
        or summary.get("approved_policy_version") != policy.version
        or summary.get("approved_policy_hash") != policy.policy_hash
        or summary.get("raw_decision_summary_hash") != expected_summary_hash
        or not isinstance(manifest, Mapping)
        or not isinstance(decision_counts, Mapping)
        or manifest.get("filename") != ETF_MINS_RAW_DECISION_MANIFEST_FILENAME
        or not manifest_path.is_file()
        or int(manifest.get("size_bytes", -1)) != manifest_path.stat().st_size
        or manifest.get("sha256") != _sha256_file(manifest_path)
    ):
        raise EtfMinsBootstrapError("etf_mins_raw_decision_output_conflict.")
    partition_count = int(summary["partition_count"])
    green_count = int(decision_counts.get("green", -1))
    warn_count = int(decision_counts.get("warn", -1))
    blocked_count = int(decision_counts.get("blocked", -1))
    eligible_count = int(summary["silver_eligible_partition_count"])
    if (
        int(manifest.get("row_count", -1)) != partition_count
        or green_count + warn_count + blocked_count != partition_count
        or eligible_count != green_count + warn_count
    ):
        raise EtfMinsBootstrapError("etf_mins_raw_decision_output_counts_invalid.")
    return EtfMinsRawDecisionResult(
        operation_id=operation_id,
        output_dir=output_dir,
        raw_partition_decision_manifest_path=manifest_path,
        raw_decision_summary_path=summary_path,
        observation_summary_hash=observation_summary_hash,
        approved_policy_version=policy.version,
        approved_policy_hash=policy.policy_hash,
        raw_partition_decision_manifest_hash=str(manifest["sha256"]),
        raw_decision_summary_hash=expected_summary_hash,
        partition_count=partition_count,
        green_partition_count=green_count,
        warn_partition_count=warn_count,
        blocked_partition_count=blocked_count,
        silver_eligible_partition_count=eligible_count,
        analysis_sql_statement_count=int(summary["analysis_sql_statement_count"]),
        elapsed_seconds=float(summary["elapsed_seconds"]),
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path, *, error_prefix: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EtfMinsBootstrapError(f"{error_prefix}_json_unreadable.") from error
    if not isinstance(payload, dict):
        raise EtfMinsBootstrapError(f"{error_prefix}_json_invalid.")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ETF_MINS_RAW_DECISION_KIND",
    "ETF_MINS_RAW_DECISION_MANIFEST_FILENAME",
    "ETF_MINS_RAW_DECISION_SUMMARY_FILENAME",
    "EtfMinsRawDecisionResult",
    "decide_etf_mins_raw",
]
