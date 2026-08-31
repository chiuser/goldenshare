"""Shared stable Raw validation semantics for ETF minute lake files."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.assets.etf_basic import audit_etf_basic_silver_snapshot
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    raw_etf_mins_path,
    silver_etf_basic_snapshot_path,
    silver_etf_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_ETF_MINS_SCHEMA,
    SILVER_ETF_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    ETF_MINS_SENSOR_WINDOW_LIMIT,
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX,
    ETF_MINS_SOURCE_FREQS,
    EtfMinsRawDecisionPolicy,
    asset_freq_for_etf_mins_source_freq,
    get_etf_mins_raw_decision_policy,
    normalize_etf_mins_source_freq,
    normalize_etf_mins_trade_date,
    raw_etf_mins_check_names,
    silver_etf_mins_check_names,
)

ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED = "unclassified"

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RAW_SCHEMA = tuple((column.name, column.type) for column in RAW_ETF_MINS_SCHEMA)
_RAW_MATERIALIZATION_QUERY_LIMIT = ETF_MINS_SENSOR_WINDOW_LIMIT * 10


@dataclass(frozen=True, slots=True)
class EtfMinsRawCandidateValidation:
    promotion_allowed: bool
    silver_eligible: bool
    policy_state: str
    stable_blocking_reason_codes: tuple[str, ...]
    source_row_count: int
    candidate_row_count: int
    source_minus_candidate_count: int
    candidate_minus_source_count: int
    distinct_code_count: int
    null_key_count: int
    duplicate_key_count: int
    date_mismatch_count: int
    freq_mismatch_count: int
    exchange_mismatch_count: int
    invalid_ohlc_count: int
    invalid_volume_amount_count: int
    invalid_vwap_count: int
    off_session_time_count: int
    grid_gap_candidate_count: int
    expected_count: int
    present_count: int
    missing_count: int
    known_non_required_present_count: int
    retained_legacy_count: int
    unexplained_new_count: int
    missing_samples: tuple[str, ...]
    known_non_required_samples: tuple[str, ...]
    retained_legacy_samples: tuple[str, ...]
    unexplained_new_samples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfMinsRawMaterializationEvidence:
    asset_key: dg.AssetKey
    storage_id: int
    partition_key: str
    source_freq: str
    raw_path: Path
    raw_sha256: str
    row_count: int
    code_count: int
    expected_count: int
    present_count: int
    missing_count: int
    known_non_required_present_count: int
    retained_legacy_count: int
    unexplained_new_count: int
    basic_reference: EtfBasicSilverSnapshotReference


@dataclass(frozen=True, slots=True)
class EtfMinsRawMaterializationBatchEvidence:
    """The latest Raw lineage recovered with one bounded query per asset."""

    expected_partition_keys: tuple[str, ...]
    evidences_by_partition_and_freq: Mapping[
        tuple[str, str], EtfMinsRawMaterializationEvidence
    ]
    missing_partition_and_freqs: tuple[tuple[str, str], ...]
    materialization_query_count: int

    def evidence_for(
        self,
        partition_key: str,
        source_freq: str,
    ) -> EtfMinsRawMaterializationEvidence | None:
        return self.evidences_by_partition_and_freq.get(
            (
                normalize_etf_mins_trade_date(partition_key),
                normalize_etf_mins_source_freq(source_freq),
            )
        )


@dataclass(frozen=True, slots=True)
class EtfMinsRawBarDomainResult:
    asset_key: dg.AssetKey
    partition_key: str
    source_freq: str
    raw_sha256: str
    gap_policy_version: str
    gap_policy_hash: str
    decision: str
    silver_eligible: bool
    reason_codes: tuple[str, ...]
    issue_counts: tuple[tuple[str, int], ...]
    samples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfMinsBarDomainCheckEvidence:
    raw_storage_id: int
    gap_policy_version: str
    gap_policy_hash: str
    decision: str
    reason_codes: tuple[str, ...]
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class EtfMinsSilverMaterializationEvidence:
    asset_key: dg.AssetKey
    storage_id: int
    partition_key: str
    source_freq: str
    silver_path: Path
    silver_sha256: str
    raw_path: Path
    raw_sha256: str
    row_count: int
    code_count: int
    basic_reference_fingerprint: str
    gap_policy_version: str
    bar_domain_decision: str
    bar_domain_reason_codes: tuple[str, ...]


def evaluate_etf_mins_raw_candidate(
    *,
    connection: Any,
    source_relation: str,
    candidate_relation: str,
    basic_all_relation: str,
    requestable_targets_relation: str,
    trade_date: str,
    source_freq: str,
    existing_target_relation: str | None = None,
) -> EtfMinsRawCandidateValidation:
    """Evaluate transport, stable Raw gates, set classes, and N3 diagnostics."""

    normalized_trade_date = normalize_etf_mins_trade_date(trade_date)
    normalized_source_freq = normalize_etf_mins_source_freq(source_freq)
    source_name = _normalize_relation_name(source_relation)
    candidate_name = _normalize_relation_name(candidate_relation)
    basic_name = _normalize_relation_name(basic_all_relation)
    requestable_name = _normalize_relation_name(requestable_targets_relation)
    existing_name = (
        None
        if existing_target_relation is None
        else _normalize_relation_name(existing_target_relation)
    )

    _assert_exact_raw_schema(connection, source_name)
    _assert_exact_raw_schema(connection, candidate_name)
    _assert_relation_columns(connection, basic_name, required=("ts_code",))
    _assert_relation_columns(
        connection,
        requestable_name,
        required=("ts_code", "list_date"),
    )
    if existing_name is not None:
        _assert_relation_columns(connection, existing_name, required=("ts_code",))

    existing_codes_sql = (
        "SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code "
        f"FROM {existing_name} WHERE ts_code IS NOT NULL"
        if existing_name is not None
        else "SELECT CAST(NULL AS VARCHAR) AS ts_code WHERE FALSE"
    )
    summary_sql = _build_etf_mins_raw_candidate_summary_sql(
        source_relation=source_name,
        candidate_relation=candidate_name,
        basic_all_relation=basic_name,
        requestable_targets_relation=requestable_name,
        existing_codes_sql=existing_codes_sql,
        trade_date=normalized_trade_date,
        source_freq=normalized_source_freq,
    )
    row = connection.execute(summary_sql).fetchone()
    if row is None:
        raise RuntimeError("ETF minute Raw validation did not return a summary row.")

    numeric_values = tuple(int(value) for value in row[:21])
    (
        source_row_count,
        candidate_row_count,
        source_minus_candidate_count,
        candidate_minus_source_count,
        distinct_code_count,
        null_key_count,
        duplicate_key_count,
        date_mismatch_count,
        freq_mismatch_count,
        exchange_mismatch_count,
        invalid_ohlc_count,
        invalid_volume_amount_count,
        invalid_vwap_count,
        off_session_time_count,
        grid_gap_candidate_count,
        expected_count,
        present_count,
        missing_count,
        known_non_required_present_count,
        retained_legacy_count,
        unexplained_new_count,
    ) = numeric_values
    samples = tuple(tuple(str(code) for code in (value or ())) for value in row[21:25])

    blocking_reasons: list[str] = []
    if (
        source_row_count != candidate_row_count
        or source_minus_candidate_count != 0
        or candidate_minus_source_count != 0
    ):
        blocking_reasons.append("etf_mins_raw_transport_mismatch")
    if null_key_count != 0 or duplicate_key_count != 0:
        blocking_reasons.append("etf_mins_raw_key_contract_failed")
    if date_mismatch_count != 0 or freq_mismatch_count != 0:
        blocking_reasons.append("etf_mins_raw_partition_contract_failed")
    if exchange_mismatch_count != 0:
        blocking_reasons.append("etf_mins_raw_exchange_identity_failed")
    if unexplained_new_count != 0:
        blocking_reasons.append("etf_mins_unexplained_new_code")

    return EtfMinsRawCandidateValidation(
        promotion_allowed=not blocking_reasons,
        silver_eligible=False,
        policy_state=ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED,
        stable_blocking_reason_codes=tuple(blocking_reasons),
        source_row_count=source_row_count,
        candidate_row_count=candidate_row_count,
        source_minus_candidate_count=source_minus_candidate_count,
        candidate_minus_source_count=candidate_minus_source_count,
        distinct_code_count=distinct_code_count,
        null_key_count=null_key_count,
        duplicate_key_count=duplicate_key_count,
        date_mismatch_count=date_mismatch_count,
        freq_mismatch_count=freq_mismatch_count,
        exchange_mismatch_count=exchange_mismatch_count,
        invalid_ohlc_count=invalid_ohlc_count,
        invalid_volume_amount_count=invalid_volume_amount_count,
        invalid_vwap_count=invalid_vwap_count,
        off_session_time_count=off_session_time_count,
        grid_gap_candidate_count=grid_gap_candidate_count,
        expected_count=expected_count,
        present_count=present_count,
        missing_count=missing_count,
        known_non_required_present_count=known_non_required_present_count,
        retained_legacy_count=retained_legacy_count,
        unexplained_new_count=unexplained_new_count,
        missing_samples=samples[0],
        known_non_required_samples=samples[1],
        retained_legacy_samples=samples[2],
        unexplained_new_samples=samples[3],
    )


def load_etf_mins_raw_materialization_evidence(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    asset_key: dg.AssetKey,
    partition_key: str,
    source_freq: str,
) -> EtfMinsRawMaterializationEvidence:
    """Load and physically rebind the latest Raw materialization for one partition."""

    normalized_partition = normalize_etf_mins_trade_date(partition_key)
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=[normalized_partition],
        ),
        limit=1,
    ).records
    if not records:
        raise RuntimeError(
            "etf_mins_raw_materialization_missing: "
            f"asset={asset_key.to_user_string()}, partition={normalized_partition}."
        )
    return _build_etf_mins_raw_materialization_evidence(
        record=records[0],
        lake_root=lake_root,
        asset_key=asset_key,
        partition_key=normalized_partition,
        source_freq=normalized_freq,
    )


def load_etf_mins_raw_materialization_evidence_batch(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    asset_keys_by_source_freq: Mapping[str, dg.AssetKey],
    partition_keys: Sequence[str],
) -> EtfMinsRawMaterializationBatchEvidence:
    """Recover at most ten dates of Raw lineage in exactly five bounded queries."""

    normalized_partitions = tuple(
        sorted({normalize_etf_mins_trade_date(value) for value in partition_keys})
    )
    if len(normalized_partitions) > ETF_MINS_SENSOR_WINDOW_LIMIT:
        raise ValueError(
            "etf_mins_raw_lineage_window_exceeds_ten_trade_dates."
        )
    normalized_assets = {
        normalize_etf_mins_source_freq(source_freq): asset_key
        for source_freq, asset_key in asset_keys_by_source_freq.items()
    }
    if set(normalized_assets) != set(ETF_MINS_SOURCE_FREQS):
        raise ValueError("etf_mins_raw_lineage_requires_five_canonical_assets.")
    if len({asset_key for asset_key in normalized_assets.values()}) != len(
        ETF_MINS_SOURCE_FREQS
    ):
        raise ValueError("etf_mins_raw_lineage_asset_keys_must_be_unique.")
    if not normalized_partitions:
        return EtfMinsRawMaterializationBatchEvidence(
            expected_partition_keys=(),
            evidences_by_partition_and_freq={},
            missing_partition_and_freqs=(),
            materialization_query_count=0,
        )

    evidences: dict[tuple[str, str], EtfMinsRawMaterializationEvidence] = {}
    query_count = 0
    for source_freq in ETF_MINS_SOURCE_FREQS:
        asset_key = normalized_assets[source_freq]
        records = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=asset_key,
                asset_partitions=list(normalized_partitions),
            ),
            limit=_RAW_MATERIALIZATION_QUERY_LIMIT,
        ).records
        query_count += 1
        seen_partitions: set[str] = set()
        for record in records:
            materialization = record.asset_materialization
            record_partition = str(
                getattr(record, "partition_key", None)
                or (
                    getattr(materialization, "partition", None)
                    if materialization is not None
                    else None
                )
                or ""
            ).strip()
            if record_partition not in normalized_partitions:
                continue
            if record_partition in seen_partitions:
                continue
            # Records are newest first.  Parse the first record before marking it
            # seen so an invalid latest record fails closed instead of falling back.
            evidence = _build_etf_mins_raw_materialization_evidence(
                record=record,
                lake_root=lake_root,
                asset_key=asset_key,
                partition_key=record_partition,
                source_freq=source_freq,
            )
            evidences[(record_partition, source_freq)] = evidence
            seen_partitions.add(record_partition)
        missing_for_asset = tuple(
            partition_key
            for partition_key in normalized_partitions
            if partition_key not in seen_partitions
        )
        if missing_for_asset and len(records) >= _RAW_MATERIALIZATION_QUERY_LIMIT:
            raise RuntimeError(
                "etf_mins_raw_materialization_batch_truncated: "
                f"asset={asset_key.to_user_string()}, "
                f"missing={missing_for_asset}."
            )

    missing = tuple(
        (partition_key, source_freq)
        for partition_key in normalized_partitions
        for source_freq in ETF_MINS_SOURCE_FREQS
        if (partition_key, source_freq) not in evidences
    )
    return EtfMinsRawMaterializationBatchEvidence(
        expected_partition_keys=normalized_partitions,
        evidences_by_partition_and_freq=evidences,
        missing_partition_and_freqs=missing,
        materialization_query_count=query_count,
    )


def _build_etf_mins_raw_materialization_evidence(
    *,
    record: Any,
    lake_root: Path,
    asset_key: dg.AssetKey,
    partition_key: str,
    source_freq: str,
) -> EtfMinsRawMaterializationEvidence:
    normalized_partition = normalize_etf_mins_trade_date(partition_key)
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    materialization = record.asset_materialization
    if materialization is None:
        raise RuntimeError("etf_mins_raw_materialization_payload_missing.")
    metadata = {
        key: _metadata_scalar(value) for key, value in materialization.metadata.items()
    }
    raw_path = Path(_require_string_metadata(metadata, "dagster/uri"))
    expected_path = raw_etf_mins_path(lake_root, normalized_freq, normalized_partition)
    if raw_path != expected_path or not raw_path.is_file():
        raise RuntimeError(
            "etf_mins_raw_materialization_path_invalid: "
            f"expected={expected_path}, observed={raw_path}."
        )
    if _require_string_metadata(metadata, "goldenshare/partition_key") != (
        normalized_partition
    ):
        raise RuntimeError("etf_mins_raw_materialization_partition_mismatch.")
    if _require_string_metadata(metadata, "goldenshare/source_freq") != normalized_freq:
        raise RuntimeError("etf_mins_raw_materialization_frequency_mismatch.")
    if tuple(metadata.get("goldenshare/observed_columns") or ()) != (
        ETF_MINS_SOURCE_COLUMNS
    ):
        raise RuntimeError("etf_mins_raw_materialization_columns_mismatch.")
    if (
        _require_string_metadata(
            metadata,
            "goldenshare/source_method",
        )
        != "prod_db_readonly"
    ):
        raise RuntimeError("etf_mins_raw_materialization_source_method_invalid.")
    if _require_non_negative_int_metadata(metadata, "goldenshare/query_count") != 1:
        raise RuntimeError("etf_mins_raw_materialization_query_count_invalid.")
    if (
        _require_string_metadata(
            metadata,
            "goldenshare/policy_state",
        )
        != ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED
    ):
        raise RuntimeError("etf_mins_raw_materialization_policy_state_invalid.")
    if metadata.get("goldenshare/silver_eligible") is not False:
        raise RuntimeError("etf_mins_raw_materialization_silver_state_invalid.")
    raw_sha256 = _require_sha256_metadata(metadata, "goldenshare/file_sha256")
    if _sha256_file(raw_path) != raw_sha256:
        raise RuntimeError("etf_mins_raw_materialization_file_hash_changed.")

    raw_snapshot_hash = _require_sha256_metadata(
        metadata,
        "goldenshare/basic_raw_snapshot_hash",
    )
    basic_reference = build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash=raw_snapshot_hash,
        silver_content_hash=_require_sha256_metadata(
            metadata,
            "goldenshare/basic_silver_content_hash",
        ),
        raw_uri=str(raw_etf_basic_snapshot_path(lake_root, raw_snapshot_hash)),
        silver_uri=str(silver_etf_basic_snapshot_path(lake_root, raw_snapshot_hash)),
        raw_observed_at=_require_string_metadata(
            metadata,
            "goldenshare/basic_raw_observed_at",
        ),
        silver_observed_at=_require_string_metadata(
            metadata,
            "goldenshare/basic_silver_observed_at",
        ),
        eligibility_as_of=_require_string_metadata(
            metadata,
            "goldenshare/eligibility_as_of",
        ),
        requestable_code_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/requestable_code_count",
        ),
        requestable_code_hash=_require_sha256_metadata(
            metadata,
            "goldenshare/requestable_code_hash",
        ),
    )
    if basic_reference.reference_fingerprint != _require_sha256_metadata(
        metadata,
        "goldenshare/basic_reference_fingerprint",
    ):
        raise RuntimeError("etf_mins_raw_materialization_basic_reference_invalid.")
    return EtfMinsRawMaterializationEvidence(
        asset_key=asset_key,
        storage_id=int(record.storage_id),
        partition_key=normalized_partition,
        source_freq=normalized_freq,
        raw_path=raw_path,
        raw_sha256=raw_sha256,
        row_count=_require_non_negative_int_metadata(metadata, "dagster/row_count"),
        code_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/code_count",
        ),
        expected_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/expected_count",
        ),
        present_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/present_count",
        ),
        missing_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/missing_count",
        ),
        known_non_required_present_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/known_non_required_present_count",
        ),
        retained_legacy_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/retained_legacy_count",
        ),
        unexplained_new_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/unexplained_new_count",
        ),
        basic_reference=basic_reference,
    )


def audit_etf_mins_raw_file_contract(
    *,
    connection: Any,
    evidence: EtfMinsRawMaterializationEvidence,
) -> tuple[tuple[str, int], ...]:
    """Return stable file-contract failure counts for one finalized Raw file."""

    relation_name = "etf_mins_raw_file_contract"
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW {relation_name} AS SELECT * FROM "
        f"{read_parquet(evidence.raw_path, hive_partitioning=False)}"
    )
    try:
        _assert_exact_raw_schema(connection, relation_name)
    except ValueError:
        return (("schema_mismatch", 1),)
    row = connection.execute(
        _raw_file_contract_sql(
            relation_name=relation_name,
            trade_date=evidence.partition_key,
            source_freq=evidence.source_freq,
        )
    ).fetchone()
    if row is None:
        return (("summary_missing", 1),)
    names = (
        "row_count_mismatch",
        "null_key_count",
        "duplicate_key_count",
        "date_mismatch_count",
        "freq_mismatch_count",
    )
    expected_row_count = evidence.row_count
    values = (
        int(row[0]) != expected_row_count,
        int(row[1]),
        int(row[2]),
        int(row[3]),
        int(row[4]),
    )
    return tuple(
        (name, int(value)) for name, value in zip(names, values, strict=True) if value
    )


def audit_etf_mins_raw_request_scope(
    *,
    connection: Any,
    evidence: EtfMinsRawMaterializationEvidence,
) -> tuple[EtfMinsRawCandidateValidation, tuple[str, ...]]:
    """Recompute the frozen Basic scope without reading Prod or today's Basic."""

    reference = evidence.basic_reference.validate_contract()
    audit = audit_etf_basic_silver_snapshot(
        path=Path(reference.silver_uri),
        duckdb_resource=_BorrowedDuckDBResource(connection),
        raw_path=Path(reference.raw_uri),
        expected_raw_snapshot_hash=reference.raw_snapshot_hash,
        expected_silver_content_hash=reference.silver_content_hash,
    )
    if not audit.passed:
        raise RuntimeError("etf_mins_frozen_basic_snapshot_invalid.")
    connection.execute(
        "CREATE OR REPLACE TEMP VIEW etf_mins_request_scope_raw AS SELECT * FROM "
        f"{read_parquet(evidence.raw_path, hive_partitioning=False)}"
    )
    connection.execute(
        "CREATE OR REPLACE TEMP VIEW etf_mins_request_scope_basic AS "
        "SELECT * FROM "
        f"{read_parquet(Path(reference.silver_uri), hive_partitioning=False)}"
    )
    connection.execute(
        "CREATE OR REPLACE TEMP VIEW etf_mins_request_scope_targets AS "
        "SELECT ts_code, list_date FROM etf_mins_request_scope_basic "
        "WHERE list_status = 'L' AND list_date <= "
        f"DATE {duckdb_string(reference.eligibility_as_of)}"
    )
    validation = evaluate_etf_mins_raw_candidate(
        connection=connection,
        source_relation="etf_mins_request_scope_raw",
        candidate_relation="etf_mins_request_scope_raw",
        basic_all_relation="etf_mins_request_scope_basic",
        requestable_targets_relation="etf_mins_request_scope_targets",
        trade_date=evidence.partition_key,
        source_freq=evidence.source_freq,
        existing_target_relation="etf_mins_request_scope_raw",
    )
    frozen_nonbasic_count = (
        evidence.retained_legacy_count + evidence.unexplained_new_count
    )
    failures: list[str] = []
    comparisons = (
        ("expected_count_changed", validation.expected_count, evidence.expected_count),
        ("present_count_changed", validation.present_count, evidence.present_count),
        ("missing_count_changed", validation.missing_count, evidence.missing_count),
        (
            "known_non_required_count_changed",
            validation.known_non_required_present_count,
            evidence.known_non_required_present_count,
        ),
        (
            "nonbasic_count_changed",
            validation.retained_legacy_count,
            frozen_nonbasic_count,
        ),
    )
    failures.extend(
        name for name, actual, expected in comparisons if actual != expected
    )
    if validation.exchange_mismatch_count:
        failures.append("exchange_identity_mismatch")
    if evidence.unexplained_new_count:
        failures.append("unexplained_new_code")
    return validation, tuple(failures)


def batch_etf_mins_raw_lake_readiness(
    *,
    connection: Any,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    lineage: EtfMinsRawMaterializationBatchEvidence,
    approved_policy_version: str = ETF_MINS_RAW_APPROVED_POLICY_VERSION,
) -> ContinuityBatchReadiness:
    """Recompute the three Raw checks for at most ten dates in one connection."""

    started_at = perf_counter()
    expected_dates = _normalize_etf_mins_readiness_dates(expected_trade_dates)
    if expected_dates != lineage.expected_partition_keys:
        raise ValueError("etf_mins_raw_lineage_window_mismatch.")
    registered = {
        normalize_etf_mins_trade_date(value) for value in registered_trade_days
    }
    policy = get_etf_mins_raw_decision_policy(approved_policy_version)
    evidences = lineage.evidences_by_partition_and_freq
    file_failures: dict[tuple[str, str], list[str]] = {}
    valid_evidences: list[EtfMinsRawMaterializationEvidence] = []
    for key, evidence in evidences.items():
        failures = file_failures.setdefault(key, [])
        if evidence.raw_path != raw_etf_mins_path(
            lake_root,
            evidence.source_freq,
            evidence.partition_key,
        ):
            failures.append("path_mismatch")
        elif not evidence.raw_path.is_file():
            failures.append("file_missing")
        elif _sha256_file(evidence.raw_path) != evidence.raw_sha256:
            failures.append("file_hash_changed")
        else:
            observed_schema = tuple(
                (str(row[0]), str(row[1]).upper())
                for row in connection.execute(
                    f"DESCRIBE SELECT * FROM "
                    f"{read_parquet(evidence.raw_path, hive_partitioning=False)}"
                ).fetchall()
            )
            if observed_schema != _RAW_SCHEMA:
                failures.append("schema_mismatch")
        if not failures:
            valid_evidences.append(evidence)

    _create_etf_mins_batch_raw_rows(connection, valid_evidences)
    file_metrics = _load_etf_mins_batch_layer_metrics(
        connection,
        relation_name="etf_mins_batch_raw_rows",
    )
    for evidence in valid_evidences:
        key = (evidence.partition_key, evidence.source_freq)
        metrics = file_metrics.get(key, {})
        if int(metrics.get("row_count", -1)) != evidence.row_count:
            file_failures[key].append("row_count_mismatch")
        for reason_code in (
            "null_key_count",
            "duplicate_key_count",
            "date_mismatch_count",
            "freq_mismatch_count",
        ):
            if int(metrics.get(reason_code, 0)):
                file_failures[key].append(reason_code)

    request_failures, request_metrics = _load_etf_mins_batch_request_scope(
        connection=connection,
        evidences=valid_evidences,
    )
    bar_results = _evaluate_etf_mins_batch_bar_domain(
        connection=connection,
        evidences=tuple(valid_evidences),
        policy=policy,
    )
    bar_by_key = {
        (result.partition_key, result.source_freq): result for result in bar_results
    }

    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date in expected_dates:
        expected_keys = tuple(
            (trade_date, source_freq) for source_freq in ETF_MINS_SOURCE_FREQS
        )
        missing_keys = tuple(key for key in expected_keys if key not in evidences)
        missing_paths = tuple(
            str(raw_etf_mins_path(lake_root, source_freq, trade_date))
            for _, source_freq in missing_keys
        )
        if trade_date not in registered:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="etf_mins_partition_not_registered",
                missing_check_names=tuple(
                    check_name
                    for source_freq in ETF_MINS_SOURCE_FREQS
                    for check_name in raw_etf_mins_check_names(
                        asset_freq_for_etf_mins_source_freq(source_freq)
                    )
                ),
                missing_file_paths=missing_paths,
            )
            continue
        if missing_keys:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="etf_mins_raw_materialization_missing",
                missing_check_names=tuple(
                    check_name
                    for _, source_freq in missing_keys
                    for check_name in raw_etf_mins_check_names(
                        asset_freq_for_etf_mins_source_freq(source_freq)
                    )
                ),
                missing_file_paths=missing_paths,
            )
            continue
        references = {
            evidences[key].basic_reference.reference_fingerprint
            for key in expected_keys
        }
        failed_check_names: list[str] = []
        failure_codes: list[str] = []
        if len(references) != 1:
            failure_codes.append("basic_reference_mismatch")
            failed_check_names.extend(
                raw_etf_mins_check_names(
                    asset_freq_for_etf_mins_source_freq(source_freq)
                )[1]
                for source_freq in ETF_MINS_SOURCE_FREQS
            )
        for key in expected_keys:
            minutes = asset_freq_for_etf_mins_source_freq(key[1])
            check_names = raw_etf_mins_check_names(minutes)
            if file_failures.get(key):
                failed_check_names.append(check_names[0])
                failure_codes.extend(file_failures[key])
            if request_failures.get(key):
                failed_check_names.append(check_names[1])
                failure_codes.extend(request_failures[key])
            bar_result = bar_by_key.get(key)
            if bar_result is None or not bar_result.silver_eligible:
                failed_check_names.append(check_names[2])
                failure_codes.extend(
                    ("bar_domain_missing",)
                    if bar_result is None
                    else bar_result.reason_codes
                )
        failed_check_names = list(dict.fromkeys(failed_check_names))
        failure_codes = list(dict.fromkeys(failure_codes))
        checks_passed = not failed_check_names
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=checks_passed,
            materialized=True,
            checks_passed=checks_passed,
            reason=(
                "ready"
                if checks_passed
                else "etf_mins_existing_file_check_failed"
            ),
            failed_check_names=tuple(failed_check_names),
            summary={
                "failure_codes": failure_codes[:ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT],
                "raw_file_count": len(expected_keys),
                "raw_row_count": sum(evidences[key].row_count for key in expected_keys),
                "request_scope": {
                    source_freq: request_metrics.get((trade_date, source_freq), {})
                    for source_freq in ETF_MINS_SOURCE_FREQS
                },
                "bar_domain_decisions": {
                    source_freq: (
                        bar_by_key[(trade_date, source_freq)].decision
                        if (trade_date, source_freq) in bar_by_key
                        else "missing"
                    )
                    for source_freq in ETF_MINS_SOURCE_FREQS
                },
            },
        )
    return ContinuityBatchReadiness(
        expected_trade_dates=expected_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=int((perf_counter() - started_at) * 1000),
        scanned_file_count=len(valid_evidences),
    )


def batch_etf_mins_silver_lake_readiness(
    *,
    connection: Any,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    raw_lineage: EtfMinsRawMaterializationBatchEvidence,
) -> ContinuityBatchReadiness:
    """Recompute Silver file/equivalence checks without Dagster event history."""

    started_at = perf_counter()
    expected_dates = _normalize_etf_mins_readiness_dates(expected_trade_dates)
    if expected_dates != raw_lineage.expected_partition_keys:
        raise ValueError("etf_mins_silver_raw_lineage_window_mismatch.")
    registered = {
        normalize_etf_mins_trade_date(value) for value in registered_trade_days
    }
    raw_evidences = raw_lineage.evidences_by_partition_and_freq
    silver_paths = {
        (trade_date, source_freq): silver_etf_mins_path(
            lake_root,
            source_freq,
            trade_date,
        )
        for trade_date in expected_dates
        for source_freq in ETF_MINS_SOURCE_FREQS
    }
    valid_silver_keys: list[tuple[str, str]] = []
    failures: dict[tuple[str, str], list[str]] = {
        key: [] for key in silver_paths
    }
    expected_silver_schema = tuple(
        (column.name, column.type) for column in SILVER_ETF_MINS_SCHEMA
    )
    for key, path in silver_paths.items():
        if not path.is_file():
            failures[key].append("file_missing")
            continue
        observed_schema = tuple(
            (str(row[0]), str(row[1]).upper())
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM "
                f"{read_parquet(path, hive_partitioning=False)}"
            ).fetchall()
        )
        if observed_schema != expected_silver_schema:
            failures[key].append("schema_mismatch")
            continue
        valid_silver_keys.append(key)

    _create_etf_mins_batch_silver_rows(
        connection=connection,
        silver_paths=silver_paths,
        valid_keys=valid_silver_keys,
    )
    silver_metrics = _load_etf_mins_batch_layer_metrics(
        connection,
        relation_name="etf_mins_batch_silver_rows",
    )
    for key in valid_silver_keys:
        metrics = silver_metrics.get(key, {})
        for reason_code in (
            "null_key_count",
            "duplicate_key_count",
            "date_mismatch_count",
            "freq_mismatch_count",
        ):
            if int(metrics.get(reason_code, 0)):
                failures[key].append(reason_code)

    valid_raw_evidences = tuple(
        raw_evidences[key]
        for key in sorted(raw_evidences)
        if key in set(valid_silver_keys)
    )
    _create_etf_mins_batch_raw_rows(connection, valid_raw_evidences)
    differences = _load_etf_mins_batch_raw_silver_differences(connection)
    for key in valid_silver_keys:
        raw_evidence = raw_evidences.get(key)
        if raw_evidence is None:
            failures[key].append("raw_materialization_missing")
            continue
        metrics = silver_metrics.get(key, {})
        if int(metrics.get("row_count", 0)) != raw_evidence.row_count:
            failures[key].append("row_count_mismatch")
        raw_minus, silver_minus = differences.get(key, (0, 0))
        if raw_minus:
            failures[key].append("raw_minus_silver_count")
        if silver_minus:
            failures[key].append("silver_minus_raw_count")

    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date in expected_dates:
        keys = tuple(
            (trade_date, source_freq) for source_freq in ETF_MINS_SOURCE_FREQS
        )
        missing_paths = tuple(
            str(silver_paths[key])
            for key in keys
            if "file_missing" in failures[key]
        )
        if trade_date not in registered:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="etf_mins_partition_not_registered",
                missing_check_names=tuple(
                    check_name
                    for source_freq in ETF_MINS_SOURCE_FREQS
                    for check_name in silver_etf_mins_check_names(
                        asset_freq_for_etf_mins_source_freq(source_freq)
                    )
                ),
                missing_file_paths=missing_paths,
            )
            continue
        if missing_paths:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="etf_mins_silver_materialization_missing",
                missing_check_names=tuple(
                    check_name
                    for key in keys
                    if "file_missing" in failures[key]
                    for check_name in silver_etf_mins_check_names(
                        asset_freq_for_etf_mins_source_freq(key[1])
                    )
                ),
                missing_file_paths=missing_paths,
            )
            continue
        failed_check_names: list[str] = []
        failure_codes: list[str] = []
        for key in keys:
            check_names = silver_etf_mins_check_names(
                asset_freq_for_etf_mins_source_freq(key[1])
            )
            key_failures = failures[key]
            if any(
                reason
                in {
                    "schema_mismatch",
                    "null_key_count",
                    "duplicate_key_count",
                    "date_mismatch_count",
                    "freq_mismatch_count",
                }
                for reason in key_failures
            ):
                failed_check_names.append(check_names[0])
            if any(
                reason
                in {
                    "raw_materialization_missing",
                    "row_count_mismatch",
                    "raw_minus_silver_count",
                    "silver_minus_raw_count",
                }
                for reason in key_failures
            ):
                failed_check_names.append(check_names[1])
            failure_codes.extend(key_failures)
        failed_check_names = list(dict.fromkeys(failed_check_names))
        failure_codes = list(dict.fromkeys(failure_codes))
        checks_passed = not failed_check_names
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=checks_passed,
            materialized=True,
            checks_passed=checks_passed,
            reason=(
                "ready"
                if checks_passed
                else "etf_mins_existing_file_check_failed"
            ),
            failed_check_names=tuple(failed_check_names),
            summary={
                "failure_codes": failure_codes[:ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT],
                "silver_file_count": len(keys),
                "silver_row_count": sum(
                    int(silver_metrics.get(key, {}).get("row_count", 0))
                    for key in keys
                ),
            },
        )
    return ContinuityBatchReadiness(
        expected_trade_dates=expected_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=int((perf_counter() - started_at) * 1000),
        scanned_file_count=len(valid_silver_keys) + len(valid_raw_evidences),
    )


def _normalize_etf_mins_readiness_dates(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(
        sorted({normalize_etf_mins_trade_date(value) for value in values})
    )
    if len(normalized) > ETF_MINS_SENSOR_WINDOW_LIMIT:
        raise ValueError("etf_mins_readiness_window_exceeds_ten_trade_dates.")
    return normalized


def _create_etf_mins_batch_silver_rows(
    *,
    connection: Any,
    silver_paths: Mapping[tuple[str, str], Path],
    valid_keys: Sequence[tuple[str, str]],
) -> None:
    columns = ", ".join(ETF_MINS_SOURCE_COLUMNS)
    selects = [
        "SELECT "
        f"{columns}, {duckdb_string(trade_date)} AS expected_trade_date, "
        f"{duckdb_string(source_freq)} AS expected_source_freq FROM "
        f"{read_parquet(silver_paths[(trade_date, source_freq)], hive_partitioning=False)}"
        for trade_date, source_freq in valid_keys
    ]
    if selects:
        sql = " UNION ALL ".join(selects)
    else:
        typed_columns = ", ".join(
            f"CAST(NULL AS {column.type}) AS {column.name}"
            for column in SILVER_ETF_MINS_SCHEMA
        )
        sql = (
            f"SELECT {typed_columns}, CAST(NULL AS VARCHAR) AS expected_trade_date, "
            "CAST(NULL AS VARCHAR) AS expected_source_freq WHERE FALSE"
        )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE etf_mins_batch_silver_rows AS " + sql
    )


def _load_etf_mins_batch_layer_metrics(
    connection: Any,
    *,
    relation_name: str,
) -> dict[tuple[str, str], dict[str, int]]:
    normalized_relation = _normalize_relation_name(relation_name)
    rows = connection.execute(
        f"""
        WITH duplicate_keys AS (
          SELECT expected_trade_date, expected_source_freq,
            count(*) - 1 AS duplicate_count
          FROM {normalized_relation}
          GROUP BY expected_trade_date, expected_source_freq, ts_code, freq, trade_time
          HAVING count(*) > 1
        ), duplicates AS (
          SELECT expected_trade_date, expected_source_freq,
            coalesce(sum(duplicate_count), 0)::BIGINT AS duplicate_key_count
          FROM duplicate_keys
          GROUP BY expected_trade_date, expected_source_freq
        )
        SELECT rows.expected_trade_date, rows.expected_source_freq,
          count(*)::BIGINT AS row_count,
          count(*) FILTER (
            WHERE ts_code IS NULL OR freq IS NULL OR trade_time IS NULL
          )::BIGINT AS null_key_count,
          coalesce(max(duplicates.duplicate_key_count), 0)::BIGINT,
          count(*) FILTER (
            WHERE trade_time IS NOT NULL
              AND CAST(trade_time AS DATE) <> CAST(rows.expected_trade_date AS DATE)
          )::BIGINT AS date_mismatch_count,
          count(*) FILTER (
            WHERE freq IS NOT NULL AND freq <> rows.expected_source_freq
          )::BIGINT AS freq_mismatch_count
        FROM {normalized_relation} AS rows
        LEFT JOIN duplicates USING (expected_trade_date, expected_source_freq)
        GROUP BY rows.expected_trade_date, rows.expected_source_freq
        """
    ).fetchall()
    names = (
        "row_count",
        "null_key_count",
        "duplicate_key_count",
        "date_mismatch_count",
        "freq_mismatch_count",
    )
    return {
        (str(row[0]), str(row[1])): {
            name: int(value)
            for name, value in zip(names, row[2:], strict=True)
        }
        for row in rows
    }


def _load_etf_mins_batch_raw_silver_differences(
    connection: Any,
) -> dict[tuple[str, str], tuple[int, int]]:
    columns = ", ".join(ETF_MINS_SOURCE_COLUMNS)
    rows = connection.execute(
        f"""
        WITH raw_minus AS (
          SELECT expected_trade_date, expected_source_freq, {columns}
          FROM etf_mins_batch_raw_rows
          EXCEPT ALL
          SELECT expected_trade_date, expected_source_freq, {columns}
          FROM etf_mins_batch_silver_rows
        ), silver_minus AS (
          SELECT expected_trade_date, expected_source_freq, {columns}
          FROM etf_mins_batch_silver_rows
          EXCEPT ALL
          SELECT expected_trade_date, expected_source_freq, {columns}
          FROM etf_mins_batch_raw_rows
        ), keys AS (
          SELECT DISTINCT expected_trade_date, expected_source_freq
          FROM etf_mins_batch_raw_rows
          UNION
          SELECT DISTINCT expected_trade_date, expected_source_freq
          FROM etf_mins_batch_silver_rows
        )
        SELECT keys.expected_trade_date, keys.expected_source_freq,
          (SELECT count(*) FROM raw_minus
            WHERE raw_minus.expected_trade_date = keys.expected_trade_date
              AND raw_minus.expected_source_freq = keys.expected_source_freq)::BIGINT,
          (SELECT count(*) FROM silver_minus
            WHERE silver_minus.expected_trade_date = keys.expected_trade_date
              AND silver_minus.expected_source_freq = keys.expected_source_freq)::BIGINT
        FROM keys
        """
    ).fetchall()
    return {
        (str(row[0]), str(row[1])): (int(row[2]), int(row[3])) for row in rows
    }


def _create_etf_mins_batch_raw_rows(
    connection: Any,
    evidences: Sequence[EtfMinsRawMaterializationEvidence],
) -> None:
    columns = ", ".join(ETF_MINS_SOURCE_COLUMNS)
    selects = [
        "SELECT "
        f"{columns}, "
        f"{duckdb_string(evidence.partition_key)} AS expected_trade_date, "
        f"{duckdb_string(evidence.source_freq)} AS expected_source_freq, "
        f"{duckdb_string(evidence.basic_reference.reference_fingerprint)} "
        "AS basic_reference_fingerprint FROM "
        f"{read_parquet(evidence.raw_path, hive_partitioning=False)}"
        for evidence in evidences
    ]
    if selects:
        sql = " UNION ALL ".join(selects)
    else:
        typed_columns = ", ".join(
            f"CAST(NULL AS {column.type}) AS {column.name}"
            for column in RAW_ETF_MINS_SCHEMA
        )
        sql = (
            f"SELECT {typed_columns}, CAST(NULL AS VARCHAR) AS expected_trade_date, "
            "CAST(NULL AS VARCHAR) AS expected_source_freq, "
            "CAST(NULL AS VARCHAR) AS basic_reference_fingerprint WHERE FALSE"
        )
    connection.execute("CREATE OR REPLACE TEMP TABLE etf_mins_batch_raw_rows AS " + sql)


def _load_etf_mins_batch_request_scope(
    *,
    connection: Any,
    evidences: Sequence[EtfMinsRawMaterializationEvidence],
) -> tuple[
    dict[tuple[str, str], list[str]],
    dict[tuple[str, str], dict[str, int]],
]:
    failures: dict[tuple[str, str], list[str]] = {
        (evidence.partition_key, evidence.source_freq): [] for evidence in evidences
    }
    references: dict[str, EtfBasicSilverSnapshotReference] = {}
    for evidence in evidences:
        reference = evidence.basic_reference.validate_contract()
        references.setdefault(reference.reference_fingerprint, reference)

    basic_selects: list[str] = []
    for fingerprint, reference in references.items():
        audit = audit_etf_basic_silver_snapshot(
            path=Path(reference.silver_uri),
            duckdb_resource=_BorrowedDuckDBResource(connection),
            raw_path=Path(reference.raw_uri),
            expected_raw_snapshot_hash=reference.raw_snapshot_hash,
            expected_silver_content_hash=reference.silver_content_hash,
        )
        if not audit.passed:
            for evidence in evidences:
                if evidence.basic_reference.reference_fingerprint == fingerprint:
                    failures[(evidence.partition_key, evidence.source_freq)].append(
                        "frozen_basic_snapshot_invalid"
                    )
            continue
        basic_selects.append(
            "SELECT ts_code, list_status, list_date, "
            f"{duckdb_string(fingerprint)} AS basic_reference_fingerprint FROM "
            f"{read_parquet(Path(reference.silver_uri), hive_partitioning=False)}"
        )
    if basic_selects:
        basic_sql = " UNION ALL ".join(basic_selects)
    else:
        basic_sql = (
            "SELECT CAST(NULL AS VARCHAR) AS ts_code, "
            "CAST(NULL AS VARCHAR) AS list_status, "
            "CAST(NULL AS DATE) AS list_date, "
            "CAST(NULL AS VARCHAR) AS basic_reference_fingerprint WHERE FALSE"
        )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE etf_mins_batch_basic_rows AS " + basic_sql
    )
    manifest_values = ", ".join(
        "("
        f"{duckdb_string(evidence.partition_key)}, "
        f"{duckdb_string(evidence.source_freq)}, "
        f"{duckdb_string(evidence.basic_reference.reference_fingerprint)}, "
        f"DATE {duckdb_string(evidence.basic_reference.eligibility_as_of)}"
        ")"
        for evidence in evidences
    )
    if not manifest_values:
        return failures, {}
    exchange_predicate = " OR ".join(
        "(right(upper(trim(ts_code)), 3) = "
        f"{duckdb_string(f'.{suffix}')} AND exchange = {duckdb_string(exchange)})"
        for suffix, exchange in ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX.items()
    )
    rows = connection.execute(
        f"""
        WITH manifest(trade_date, source_freq, basic_reference_fingerprint,
          eligibility_as_of) AS (VALUES {manifest_values}),
        candidate_codes AS (
          SELECT DISTINCT expected_trade_date AS trade_date,
            expected_source_freq AS source_freq,
            basic_reference_fingerprint, trim(ts_code) AS ts_code
          FROM etf_mins_batch_raw_rows
          WHERE ts_code IS NOT NULL
        ),
        basic_codes AS (
          SELECT DISTINCT basic_reference_fingerprint, trim(ts_code) AS ts_code
          FROM etf_mins_batch_basic_rows
          WHERE ts_code IS NOT NULL
        ),
        expected_codes AS (
          SELECT DISTINCT manifest.trade_date, manifest.source_freq,
            manifest.basic_reference_fingerprint, trim(basic.ts_code) AS ts_code
          FROM manifest
          JOIN etf_mins_batch_basic_rows AS basic USING (basic_reference_fingerprint)
          WHERE basic.list_status = 'L'
            AND CAST(basic.list_date AS DATE) <= manifest.eligibility_as_of
            AND CAST(basic.list_date AS DATE) <= CAST(manifest.trade_date AS DATE)
        ),
        metrics AS (
          SELECT manifest.trade_date, manifest.source_freq,
            (SELECT count(*) FROM expected_codes AS expected
              WHERE expected.trade_date = manifest.trade_date
                AND expected.source_freq = manifest.source_freq)::BIGINT
              AS expected_count,
            (SELECT count(*) FROM candidate_codes AS candidate
              WHERE candidate.trade_date = manifest.trade_date
                AND candidate.source_freq = manifest.source_freq)::BIGINT
              AS present_count,
            (SELECT count(*) FROM expected_codes AS expected
              LEFT JOIN candidate_codes AS candidate
                ON candidate.trade_date = expected.trade_date
               AND candidate.source_freq = expected.source_freq
               AND candidate.basic_reference_fingerprint =
                 expected.basic_reference_fingerprint
               AND candidate.ts_code = expected.ts_code
              WHERE expected.trade_date = manifest.trade_date
                AND expected.source_freq = manifest.source_freq
                AND candidate.ts_code IS NULL)::BIGINT AS missing_count,
            (SELECT count(*) FROM candidate_codes AS candidate
              JOIN basic_codes AS basic
                ON basic.basic_reference_fingerprint =
                  candidate.basic_reference_fingerprint
               AND basic.ts_code = candidate.ts_code
              LEFT JOIN expected_codes AS expected
                ON expected.trade_date = candidate.trade_date
               AND expected.source_freq = candidate.source_freq
               AND expected.basic_reference_fingerprint =
                 candidate.basic_reference_fingerprint
               AND expected.ts_code = candidate.ts_code
              WHERE candidate.trade_date = manifest.trade_date
                AND candidate.source_freq = manifest.source_freq
                AND expected.ts_code IS NULL)::BIGINT
              AS known_non_required_present_count,
            (SELECT count(*) FROM candidate_codes AS candidate
              LEFT JOIN basic_codes AS basic
                ON basic.basic_reference_fingerprint =
                  candidate.basic_reference_fingerprint
               AND basic.ts_code = candidate.ts_code
              WHERE candidate.trade_date = manifest.trade_date
                AND candidate.source_freq = manifest.source_freq
                AND basic.ts_code IS NULL)::BIGINT AS nonbasic_count
          FROM manifest
        ), exchange_metrics AS (
          SELECT expected_trade_date AS trade_date,
            expected_source_freq AS source_freq,
            count(*) FILTER (
              WHERE ts_code IS NOT NULL AND NOT ({exchange_predicate})
            )::BIGINT AS exchange_mismatch_count
          FROM etf_mins_batch_raw_rows
          GROUP BY expected_trade_date, expected_source_freq
        )
        SELECT metrics.trade_date, metrics.source_freq,
          expected_count, present_count, missing_count,
          known_non_required_present_count, nonbasic_count,
          coalesce(exchange_mismatch_count, 0)::BIGINT
        FROM metrics
        LEFT JOIN exchange_metrics USING (trade_date, source_freq)
        ORDER BY trade_date, source_freq
        """
    ).fetchall()
    metric_names = (
        "expected_count",
        "present_count",
        "missing_count",
        "known_non_required_present_count",
        "nonbasic_count",
        "exchange_mismatch_count",
    )
    metrics = {
        (str(row[0]), str(row[1])): {
            name: int(value)
            for name, value in zip(metric_names, row[2:], strict=True)
        }
        for row in rows
    }
    evidence_by_key = {
        (evidence.partition_key, evidence.source_freq): evidence
        for evidence in evidences
    }
    comparisons = (
        ("expected_count_changed", "expected_count", "expected_count"),
        ("present_count_changed", "present_count", "present_count"),
        ("missing_count_changed", "missing_count", "missing_count"),
        (
            "known_non_required_count_changed",
            "known_non_required_present_count",
            "known_non_required_present_count",
        ),
    )
    for key, evidence in evidence_by_key.items():
        observed = metrics.get(key)
        if observed is None:
            failures[key].append("request_scope_summary_missing")
            continue
        for reason_code, metric_name, evidence_name in comparisons:
            if observed[metric_name] != int(getattr(evidence, evidence_name)):
                failures[key].append(reason_code)
        frozen_nonbasic_count = (
            evidence.retained_legacy_count + evidence.unexplained_new_count
        )
        if observed["nonbasic_count"] != frozen_nonbasic_count:
            failures[key].append("nonbasic_count_changed")
        if observed["exchange_mismatch_count"]:
            failures[key].append("exchange_identity_mismatch")
        if evidence.unexplained_new_count:
            failures[key].append("unexplained_new_code")
    return failures, metrics


def _evaluate_etf_mins_batch_bar_domain(
    *,
    connection: Any,
    evidences: tuple[EtfMinsRawMaterializationEvidence, ...],
    policy: EtfMinsRawDecisionPolicy,
) -> tuple[EtfMinsRawBarDomainResult, ...]:
    """Read the physical files once, then evaluate each date from the temp batch."""

    by_date: dict[str, dict[str, EtfMinsRawMaterializationEvidence]] = {}
    for evidence in evidences:
        by_date.setdefault(evidence.partition_key, {})[evidence.source_freq] = evidence
    results: list[EtfMinsRawBarDomainResult] = []
    projected_columns = ", ".join(ETF_MINS_SOURCE_COLUMNS)
    for trade_date in sorted(by_date):
        evidence_by_freq = by_date[trade_date]
        if set(evidence_by_freq) != set(ETF_MINS_SOURCE_FREQS):
            continue
        if len(
            {
                evidence.basic_reference.reference_fingerprint
                for evidence in evidence_by_freq.values()
            }
        ) != 1:
            continue
        connection.execute(
            "CREATE OR REPLACE TEMP VIEW etf_mins_bar_domain_rows AS "
            f"SELECT {projected_columns}, expected_source_freq "
            "FROM etf_mins_batch_raw_rows "
            f"WHERE expected_trade_date = {duckdb_string(trade_date)}"
        )
        connection.execute("DROP TABLE IF EXISTS etf_mins_bar_domain_code_facts")
        connection.execute(
            "DROP TABLE IF EXISTS etf_mins_bar_domain_grid_differences"
        )
        connection.execute(_bar_domain_code_facts_sql())
        connection.execute(_bar_domain_grid_differences_sql(policy))
        full_zero_codes = tuple(
            str(row[0])
            for row in connection.execute(
                _bar_domain_full_zero_codes_sql()
            ).fetchall()
        )
        total_row_count = int(
            connection.execute(
                "SELECT count(*) FROM etf_mins_bar_domain_rows"
            ).fetchone()[0]
        )
        results.extend(
            _load_bar_domain_result(
                connection=connection,
                evidence=evidence_by_freq[source_freq],
                policy=policy,
                total_row_count=total_row_count,
                full_zero_codes=full_zero_codes,
            )
            for source_freq in ETF_MINS_SOURCE_FREQS
        )
    return tuple(results)


def evaluate_etf_mins_raw_bar_domain(
    *,
    duckdb: DuckDBResource,
    evidences: tuple[EtfMinsRawMaterializationEvidence, ...],
    approved_policy_version: str = ETF_MINS_RAW_APPROVED_POLICY_VERSION,
) -> tuple[EtfMinsRawBarDomainResult, ...]:
    """Evaluate one trade day's five Raw files in one DuckDB connection/read pass."""

    policy = get_etf_mins_raw_decision_policy(approved_policy_version)
    evidence_by_freq = {evidence.source_freq: evidence for evidence in evidences}
    if (
        len(evidences) != len(ETF_MINS_SOURCE_FREQS)
        or len(evidence_by_freq) != len(ETF_MINS_SOURCE_FREQS)
        or set(evidence_by_freq) != set(ETF_MINS_SOURCE_FREQS)
    ):
        raise RuntimeError("etf_mins_bar_domain_requires_five_canonical_frequencies.")
    partition_keys = {evidence.partition_key for evidence in evidences}
    if len(partition_keys) != 1:
        raise RuntimeError("etf_mins_bar_domain_requires_one_trade_date.")
    if (
        len({evidence.basic_reference.reference_fingerprint for evidence in evidences})
        != 1
    ):
        raise RuntimeError("etf_mins_bar_domain_basic_reference_mismatch.")

    with duckdb.connect() as connection:
        union_sql = " UNION ALL ".join(
            "SELECT "
            + ", ".join(ETF_MINS_SOURCE_COLUMNS)
            + f", {duckdb_string(source_freq)} AS expected_source_freq"
            + " FROM "
            + read_parquet(
                evidence_by_freq[source_freq].raw_path,
                hive_partitioning=False,
            )
            for source_freq in ETF_MINS_SOURCE_FREQS
        )
        connection.execute("CREATE TEMP TABLE etf_mins_bar_domain_rows AS " + union_sql)
        connection.execute(_bar_domain_code_facts_sql())
        connection.execute(_bar_domain_grid_differences_sql(policy))
        full_zero_codes = tuple(
            str(row[0])
            for row in connection.execute(_bar_domain_full_zero_codes_sql()).fetchall()
        )
        total_row_count = int(
            connection.execute(
                "SELECT count(*) FROM etf_mins_bar_domain_rows"
            ).fetchone()[0]
        )
        results = tuple(
            _load_bar_domain_result(
                connection=connection,
                evidence=evidence_by_freq[source_freq],
                policy=policy,
                total_row_count=total_row_count,
                full_zero_codes=full_zero_codes,
            )
            for source_freq in ETF_MINS_SOURCE_FREQS
        )
    return results


def load_etf_mins_bar_domain_check_evidence(
    *,
    instance: dg.DagsterInstance,
    raw_evidence: EtfMinsRawMaterializationEvidence,
) -> EtfMinsBarDomainCheckEvidence:
    """Load the passed bar-domain check bound to the exact Raw materialization."""

    check_name = raw_etf_mins_check_names(
        asset_freq_for_etf_mins_source_freq(raw_evidence.source_freq)
    )[2]
    records = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(raw_evidence.asset_key, check_name),
        limit=1,
        status={
            AssetCheckExecutionRecordStatus.SUCCEEDED,
            AssetCheckExecutionRecordStatus.FAILED,
        },
    )
    if not records:
        raise RuntimeError("etf_mins_bar_domain_check_missing.")
    record = records[0]
    event = record.event
    dagster_event = event.dagster_event if event is not None else None
    evaluation = (
        dagster_event.event_specific_data if dagster_event is not None else None
    )
    target = getattr(evaluation, "target_materialization_data", None)
    if target is None or int(target.storage_id) != raw_evidence.storage_id:
        raise RuntimeError("etf_mins_bar_domain_check_not_bound_to_raw.")
    if (
        record.status is not AssetCheckExecutionRecordStatus.SUCCEEDED
        or not bool(getattr(evaluation, "blocking", False))
        or not bool(getattr(evaluation, "passed", False))
    ):
        raise RuntimeError("etf_mins_bar_domain_check_not_passed.")
    metadata = {
        key: _metadata_scalar(value)
        for key, value in getattr(evaluation, "metadata", {}).items()
    }
    policy_version = _require_string_metadata(
        metadata,
        "goldenshare/gap_policy_version",
    )
    policy = get_etf_mins_raw_decision_policy(policy_version)
    policy_hash = _require_sha256_metadata(
        metadata,
        "goldenshare/gap_policy_hash",
    )
    if policy_hash != policy.policy_hash:
        raise RuntimeError("etf_mins_bar_domain_check_policy_hash_mismatch.")
    decision = _require_string_metadata(
        metadata,
        "goldenshare/bar_domain_decision",
    )
    reason_codes = _metadata_string_tuple(
        metadata,
        "goldenshare/bar_domain_reason_codes",
    )
    raw_sha256 = _require_sha256_metadata(metadata, "goldenshare/raw_sha256")
    if raw_sha256 != raw_evidence.raw_sha256:
        raise RuntimeError("etf_mins_bar_domain_check_raw_hash_mismatch.")
    if decision not in {"green", "warn"}:
        raise RuntimeError("etf_mins_bar_domain_check_decision_not_admissible.")
    return EtfMinsBarDomainCheckEvidence(
        raw_storage_id=raw_evidence.storage_id,
        gap_policy_version=policy_version,
        gap_policy_hash=policy_hash,
        decision=decision,
        reason_codes=reason_codes,
        raw_sha256=raw_sha256,
    )


def load_etf_mins_silver_materialization_evidence(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    asset_key: dg.AssetKey,
    partition_key: str,
    source_freq: str,
) -> EtfMinsSilverMaterializationEvidence:
    """Load and physically rebind the latest Silver materialization."""

    normalized_partition = normalize_etf_mins_trade_date(partition_key)
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=[normalized_partition],
        ),
        limit=1,
    ).records
    if not records:
        raise RuntimeError("etf_mins_silver_materialization_missing.")
    record = records[0]
    materialization = record.asset_materialization
    if materialization is None:
        raise RuntimeError("etf_mins_silver_materialization_payload_missing.")
    metadata = {
        key: _metadata_scalar(value) for key, value in materialization.metadata.items()
    }
    silver_path = Path(_require_string_metadata(metadata, "dagster/uri"))
    expected_path = silver_etf_mins_path(
        lake_root,
        normalized_freq,
        normalized_partition,
    )
    if silver_path != expected_path or not silver_path.is_file():
        raise RuntimeError("etf_mins_silver_materialization_path_invalid.")
    if _require_string_metadata(metadata, "goldenshare/partition_key") != (
        normalized_partition
    ):
        raise RuntimeError("etf_mins_silver_materialization_partition_mismatch.")
    if _require_string_metadata(metadata, "goldenshare/source_freq") != normalized_freq:
        raise RuntimeError("etf_mins_silver_materialization_frequency_mismatch.")
    if tuple(metadata.get("goldenshare/observed_columns") or ()) != (
        ETF_MINS_SOURCE_COLUMNS
    ):
        raise RuntimeError("etf_mins_silver_materialization_columns_mismatch.")
    silver_sha256 = _require_sha256_metadata(
        metadata,
        "goldenshare/silver_sha256",
    )
    if _sha256_file(silver_path) != silver_sha256:
        raise RuntimeError("etf_mins_silver_materialization_file_hash_changed.")
    policy_version = _require_string_metadata(
        metadata,
        "goldenshare/gap_policy_version",
    )
    get_etf_mins_raw_decision_policy(policy_version)
    decision = _require_string_metadata(
        metadata,
        "goldenshare/bar_domain_decision",
    )
    if decision not in {"green", "warn"}:
        raise RuntimeError("etf_mins_silver_materialization_decision_invalid.")
    return EtfMinsSilverMaterializationEvidence(
        asset_key=asset_key,
        storage_id=int(record.storage_id),
        partition_key=normalized_partition,
        source_freq=normalized_freq,
        silver_path=silver_path,
        silver_sha256=silver_sha256,
        raw_path=Path(_require_string_metadata(metadata, "goldenshare/raw_uri")),
        raw_sha256=_require_sha256_metadata(metadata, "goldenshare/raw_sha256"),
        row_count=_require_non_negative_int_metadata(metadata, "dagster/row_count"),
        code_count=_require_non_negative_int_metadata(
            metadata,
            "goldenshare/code_count",
        ),
        basic_reference_fingerprint=_require_sha256_metadata(
            metadata,
            "goldenshare/basic_reference_fingerprint",
        ),
        gap_policy_version=policy_version,
        bar_domain_decision=decision,
        bar_domain_reason_codes=_metadata_string_tuple(
            metadata,
            "goldenshare/bar_domain_reason_codes",
        ),
    )


def audit_etf_mins_silver_file_contract(
    *,
    connection: Any,
    evidence: EtfMinsSilverMaterializationEvidence,
) -> tuple[tuple[str, int], ...]:
    """Return exact Silver file/schema/key/partition contract failures."""

    relation_name = "etf_mins_silver_file_contract"
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW {relation_name} AS SELECT * FROM "
        f"{read_parquet(evidence.silver_path, hive_partitioning=False)}"
    )
    if _relation_schema(connection, relation_name) != tuple(
        (column.name, column.type) for column in SILVER_ETF_MINS_SCHEMA
    ):
        return (("schema_mismatch", 1),)
    row = connection.execute(
        _raw_file_contract_sql(
            relation_name=relation_name,
            trade_date=evidence.partition_key,
            source_freq=evidence.source_freq,
        )
    ).fetchone()
    if row is None:
        return (("summary_missing", 1),)
    values = (
        ("row_count_mismatch", int(int(row[0]) != evidence.row_count)),
        ("null_key_count", int(row[1])),
        ("duplicate_key_count", int(row[2])),
        ("date_mismatch_count", int(row[3])),
        ("freq_mismatch_count", int(row[4])),
    )
    return tuple((name, value) for name, value in values if value)


def audit_etf_mins_silver_raw_equivalence(
    *,
    connection: Any,
    silver_evidence: EtfMinsSilverMaterializationEvidence,
    raw_evidence: EtfMinsRawMaterializationEvidence,
) -> tuple[tuple[str, int], ...]:
    """Compare current formal Raw/Silver files in both directions."""

    failures: list[tuple[str, int]] = []
    if silver_evidence.raw_path != raw_evidence.raw_path:
        failures.append(("raw_uri_mismatch", 1))
    if silver_evidence.raw_sha256 != raw_evidence.raw_sha256:
        failures.append(("raw_sha256_mismatch", 1))
    if (
        silver_evidence.basic_reference_fingerprint
        != raw_evidence.basic_reference.reference_fingerprint
    ):
        failures.append(("basic_reference_mismatch", 1))
    if failures:
        return tuple(failures)

    raw_relation = read_parquet(raw_evidence.raw_path, hive_partitioning=False)
    silver_relation = read_parquet(
        silver_evidence.silver_path,
        hive_partitioning=False,
    )
    columns = ", ".join(ETF_MINS_SOURCE_COLUMNS)
    row = connection.execute(
        f"""
        SELECT
          (SELECT count(*) FROM {raw_relation})::BIGINT,
          (SELECT count(*) FROM {silver_relation})::BIGINT,
          (SELECT count(*) FROM (
            SELECT {columns} FROM {raw_relation}
            EXCEPT ALL
            SELECT {columns} FROM {silver_relation}
          ))::BIGINT,
          (SELECT count(*) FROM (
            SELECT {columns} FROM {silver_relation}
            EXCEPT ALL
            SELECT {columns} FROM {raw_relation}
          ))::BIGINT,
          (SELECT count(*) FROM (
            SELECT ts_code, freq, trade_time FROM {raw_relation}
            EXCEPT ALL
            SELECT ts_code, freq, trade_time FROM {silver_relation}
          ))::BIGINT,
          (SELECT count(*) FROM (
            SELECT ts_code, freq, trade_time FROM {silver_relation}
            EXCEPT ALL
            SELECT ts_code, freq, trade_time FROM {raw_relation}
          ))::BIGINT
        """
    ).fetchone()
    if row is None:
        return (("summary_missing", 1),)
    raw_rows, silver_rows, raw_minus, silver_minus, raw_keys, silver_keys = (
        int(value) for value in row
    )
    values = (
        ("row_count_mismatch", abs(raw_rows - silver_rows)),
        ("raw_minus_silver_count", raw_minus),
        ("silver_minus_raw_count", silver_minus),
        ("raw_key_minus_silver_count", raw_keys),
        ("silver_key_minus_raw_count", silver_keys),
    )
    return tuple((name, value) for name, value in values if value)


def _build_etf_mins_raw_candidate_summary_sql(
    *,
    source_relation: str,
    candidate_relation: str,
    basic_all_relation: str,
    requestable_targets_relation: str,
    existing_codes_sql: str,
    trade_date: str,
    source_freq: str,
) -> str:
    columns = ", ".join(column.name for column in RAW_ETF_MINS_SCHEMA)
    asset_freq = asset_freq_for_etf_mins_source_freq(source_freq)
    sample_limit = ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT
    exchange_identity_predicate = " OR\n      ".join(
        "(right(upper(trim(ts_code)), 3) = "
        f"{duckdb_string(f'.{suffix}')} AND exchange = {duckdb_string(exchange)})"
        for suffix, exchange in ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX.items()
    )
    return f"""
WITH source_rows AS (
  SELECT {columns} FROM {source_relation}
),
candidate_rows AS (
  SELECT {columns} FROM {candidate_relation}
),
candidate_codes AS (
  SELECT DISTINCT trim(ts_code) AS ts_code
  FROM candidate_rows
  WHERE ts_code IS NOT NULL
),
basic_codes AS (
  SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code
  FROM {basic_all_relation}
  WHERE ts_code IS NOT NULL
),
requestable_targets AS (
  SELECT DISTINCT
    trim(CAST(ts_code AS VARCHAR)) AS ts_code,
    CAST(list_date AS DATE) AS list_date
  FROM {requestable_targets_relation}
  WHERE ts_code IS NOT NULL AND list_date IS NOT NULL
),
expected_codes AS (
  SELECT ts_code
  FROM requestable_targets
  WHERE list_date <= DATE '{trade_date}'
),
existing_codes AS (
  {existing_codes_sql}
),
missing_codes AS (
  SELECT expected.ts_code
  FROM expected_codes AS expected
  LEFT JOIN candidate_codes AS candidate USING (ts_code)
  WHERE candidate.ts_code IS NULL
),
known_non_required_codes AS (
  SELECT candidate.ts_code
  FROM candidate_codes AS candidate
  JOIN basic_codes AS basic USING (ts_code)
  LEFT JOIN expected_codes AS expected USING (ts_code)
  WHERE expected.ts_code IS NULL
),
retained_legacy_codes AS (
  SELECT candidate.ts_code
  FROM candidate_codes AS candidate
  LEFT JOIN basic_codes AS basic USING (ts_code)
  JOIN existing_codes AS existing USING (ts_code)
  WHERE basic.ts_code IS NULL
),
unexplained_new_codes AS (
  SELECT candidate.ts_code
  FROM candidate_codes AS candidate
  LEFT JOIN basic_codes AS basic USING (ts_code)
  LEFT JOIN existing_codes AS existing USING (ts_code)
  WHERE basic.ts_code IS NULL AND existing.ts_code IS NULL
),
duplicate_keys AS (
  SELECT count(*) - 1 AS duplicate_count
  FROM candidate_rows
  GROUP BY ts_code, freq, trade_time
  HAVING count(*) > 1
),
ordered_rows AS (
  SELECT
    ts_code,
    trade_time,
    lag(trade_time) OVER (PARTITION BY ts_code ORDER BY trade_time) AS previous_time
  FROM candidate_rows
  WHERE ts_code IS NOT NULL AND trade_time IS NOT NULL
),
source_minus_candidate AS (
  SELECT {columns} FROM source_rows
  EXCEPT ALL
  SELECT {columns} FROM candidate_rows
),
candidate_minus_source AS (
  SELECT {columns} FROM candidate_rows
  EXCEPT ALL
  SELECT {columns} FROM source_rows
)
SELECT
  (SELECT count(*) FROM source_rows) AS source_row_count,
  (SELECT count(*) FROM candidate_rows) AS candidate_row_count,
  (SELECT count(*) FROM source_minus_candidate) AS source_minus_candidate_count,
  (SELECT count(*) FROM candidate_minus_source) AS candidate_minus_source_count,
  (SELECT count(*) FROM candidate_codes) AS distinct_code_count,
  (SELECT count(*) FROM candidate_rows
    WHERE ts_code IS NULL OR freq IS NULL OR trade_time IS NULL) AS null_key_count,
  COALESCE((SELECT sum(duplicate_count) FROM duplicate_keys), 0) AS duplicate_key_count,
  (SELECT count(*) FROM candidate_rows
    WHERE trade_time IS NOT NULL AND CAST(trade_time AS DATE) <> DATE '{trade_date}')
    AS date_mismatch_count,
  (SELECT count(*) FROM candidate_rows
    WHERE freq IS NOT NULL AND freq <> '{source_freq}') AS freq_mismatch_count,
  (SELECT count(*) FROM candidate_rows
    WHERE ts_code IS NOT NULL AND NOT (
      {exchange_identity_predicate}
    )) AS exchange_mismatch_count,
  (SELECT count(*) FROM candidate_rows
    WHERE open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
      OR NOT isfinite(open) OR NOT isfinite(close)
      OR NOT isfinite(high) OR NOT isfinite(low)
      OR high < greatest(open, close, low)
      OR low > least(open, close, high)) AS invalid_ohlc_count,
  (SELECT count(*) FROM candidate_rows
    WHERE vol IS NULL OR amount IS NULL OR vol < 0
      OR NOT isfinite(amount) OR amount < 0) AS invalid_volume_amount_count,
  (SELECT count(*) FROM candidate_rows
    WHERE vwap IS NULL OR NOT isfinite(vwap) OR vwap < 0) AS invalid_vwap_count,
  (SELECT count(*) FROM candidate_rows
    WHERE trade_time IS NOT NULL AND (
      CAST(trade_time AS TIME) < TIME '09:00:00'
      OR CAST(trade_time AS TIME) > TIME '16:00:00'
    )) AS off_session_time_count,
  (SELECT count(*) FROM ordered_rows
    WHERE previous_time IS NOT NULL
      AND date_diff('minute', previous_time, trade_time) > {asset_freq})
    AS grid_gap_candidate_count,
  (SELECT count(*) FROM expected_codes) AS expected_count,
  (SELECT count(*) FROM candidate_codes) AS present_count,
  (SELECT count(*) FROM missing_codes) AS missing_count,
  (SELECT count(*) FROM known_non_required_codes)
    AS known_non_required_present_count,
  (SELECT count(*) FROM retained_legacy_codes) AS retained_legacy_count,
  (SELECT count(*) FROM unexplained_new_codes) AS unexplained_new_count,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM missing_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS missing_samples,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM known_non_required_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS known_non_required_samples,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM retained_legacy_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS retained_legacy_samples,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM unexplained_new_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS unexplained_new_samples
"""


def _assert_exact_raw_schema(connection: Any, relation_name: str) -> None:
    observed = _relation_schema(connection, relation_name)
    if observed != _RAW_SCHEMA:
        raise ValueError(
            "ETF minute Raw relation schema does not match the exact 11-column contract: "
            f"relation={relation_name}, observed={observed}."
        )


def _assert_relation_columns(
    connection: Any,
    relation_name: str,
    *,
    required: tuple[str, ...],
) -> None:
    observed_names = {name for name, _ in _relation_schema(connection, relation_name)}
    missing = tuple(column for column in required if column not in observed_names)
    if missing:
        raise ValueError(
            f"ETF minute validation relation {relation_name} is missing {missing}."
        )


def _relation_schema(
    connection: Any, relation_name: str
) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {relation_name}").fetchall()
    return tuple((str(row[0]), str(row[1]).upper()) for row in rows)


def _normalize_relation_name(value: object) -> str:
    normalized = str(value).strip()
    if not _SQL_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError("ETF minute validation relation must be a simple identifier.")
    return normalized


def _raw_file_contract_sql(
    *,
    relation_name: str,
    trade_date: str,
    source_freq: str,
) -> str:
    return f"""
    SELECT
      count(*),
      count(*) FILTER (
        WHERE ts_code IS NULL OR freq IS NULL OR trade_time IS NULL
      ),
      count(*) FILTER (
        WHERE ts_code IS NOT NULL AND freq IS NOT NULL AND trade_time IS NOT NULL
      ) - count(DISTINCT (ts_code, freq, trade_time)) FILTER (
        WHERE ts_code IS NOT NULL AND freq IS NOT NULL AND trade_time IS NOT NULL
      ),
      count(*) FILTER (
        WHERE trade_time IS NOT NULL
          AND CAST(trade_time AS DATE) <> DATE {duckdb_string(trade_date)}
      ),
      count(*) FILTER (
        WHERE freq IS NOT NULL AND freq <> {duckdb_string(source_freq)}
      )
    FROM {relation_name}
    """


def _bar_domain_code_facts_sql() -> str:
    return """
    CREATE TEMP TABLE etf_mins_bar_domain_code_facts AS
    SELECT
      expected_source_freq AS source_freq,
      ts_code,
      count(*)::BIGINT AS row_count,
      count(DISTINCT CAST(trade_time AS TIME))::BIGINT AS distinct_time_count,
      min(CAST(trade_time AS TIME)) AS min_clock_time,
      max(CAST(trade_time AS TIME)) AS max_clock_time,
      count(*) FILTER (
        WHERE open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
          OR NOT isfinite(open) OR NOT isfinite(close)
          OR NOT isfinite(high) OR NOT isfinite(low)
          OR open <= 0 OR close <= 0 OR high <= 0 OR low <= 0
          OR high < greatest(open, close, low)
          OR low > least(open, close, high)
      )::BIGINT AS price_domain_anomaly_count,
      count(*) FILTER (
        WHERE vol IS NULL OR amount IS NULL OR vol < 0
          OR (amount IS NOT NULL AND NOT isfinite(amount)) OR amount < 0
      )::BIGINT AS volume_amount_domain_anomaly_count,
      count(*) FILTER (
        WHERE vwap IS NULL OR NOT isfinite(vwap) OR vwap < 0
      )::BIGINT AS vwap_domain_anomaly_count,
      count(*) FILTER (
        WHERE trade_time IS NOT NULL AND (
          CAST(trade_time AS TIME) < TIME '09:00:00'
          OR CAST(trade_time AS TIME) > TIME '16:00:00'
        )
      )::BIGINT AS off_session_time_observed_count,
      count(*) FILTER (WHERE vol = 0)::BIGINT AS zero_volume_bar_count
    FROM etf_mins_bar_domain_rows
    WHERE ts_code IS NOT NULL
    GROUP BY expected_source_freq, ts_code
    """


def _bar_domain_grid_differences_sql(policy: EtfMinsRawDecisionPolicy) -> str:
    expected_values = ", ".join(
        f"({duckdb_string(source_freq)}, {duckdb_string(clock_time)})"
        for source_freq, clock_times in policy.expected_clock_times_by_source_freq
        for clock_time in clock_times
    )
    return f"""
    CREATE TEMP TABLE etf_mins_bar_domain_grid_differences AS
    WITH expected_grid(source_freq, clock_time) AS (
      VALUES {expected_values}
    ),
    codes AS (
      SELECT DISTINCT expected_source_freq AS source_freq, ts_code
      FROM etf_mins_bar_domain_rows
      WHERE ts_code IS NOT NULL
    ),
    expected_points AS (
      SELECT codes.source_freq, codes.ts_code, expected.clock_time
      FROM codes
      JOIN expected_grid AS expected USING (source_freq)
    ),
    actual_points AS (
      SELECT DISTINCT expected_source_freq AS source_freq, ts_code,
        CAST(CAST(trade_time AS TIME) AS VARCHAR) AS clock_time
      FROM etf_mins_bar_domain_rows
      WHERE ts_code IS NOT NULL AND trade_time IS NOT NULL
    ),
    differences AS (
      (SELECT * FROM expected_points EXCEPT ALL SELECT * FROM actual_points)
      UNION ALL
      (SELECT * FROM actual_points EXCEPT ALL SELECT * FROM expected_points)
    )
    SELECT source_freq, ts_code, count(*)::BIGINT AS difference_count
    FROM differences
    GROUP BY source_freq, ts_code
    """


def _bar_domain_full_zero_codes_sql() -> str:
    return f"""
    SELECT ts_code
    FROM etf_mins_bar_domain_code_facts
    GROUP BY ts_code
    HAVING count(*) = {len(ETF_MINS_SOURCE_FREQS)}
      AND count(DISTINCT source_freq) = {len(ETF_MINS_SOURCE_FREQS)}
      AND count(*) FILTER (
        WHERE row_count > 0 AND zero_volume_bar_count = row_count
      ) = {len(ETF_MINS_SOURCE_FREQS)}
    ORDER BY ts_code
    """


def _load_bar_domain_result(
    *,
    connection: Any,
    evidence: EtfMinsRawMaterializationEvidence,
    policy: EtfMinsRawDecisionPolicy,
    total_row_count: int,
    full_zero_codes: tuple[str, ...],
) -> EtfMinsRawBarDomainResult:
    exchange_predicate = " OR ".join(
        "(right(upper(trim(ts_code)), 3) = "
        f"{duckdb_string(f'.{suffix}')} AND exchange = {duckdb_string(exchange)})"
        for suffix, exchange in ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX.items()
    )
    expected_times = policy.expected_clock_times(evidence.source_freq)
    row = connection.execute(
        f"""
        WITH partition_rows AS (
          SELECT * FROM etf_mins_bar_domain_rows
          WHERE expected_source_freq = {duckdb_string(evidence.source_freq)}
        ),
        duplicate_keys AS (
          SELECT count(*) - 1 AS duplicate_count
          FROM partition_rows
          GROUP BY ts_code, freq, trade_time
          HAVING count(*) > 1
        ),
        code_summary AS (
          SELECT
            coalesce(sum(price_domain_anomaly_count), 0)::BIGINT
              AS price_domain_anomaly_count,
            coalesce(sum(volume_amount_domain_anomaly_count), 0)::BIGINT
              AS volume_amount_domain_anomaly_count,
            coalesce(sum(vwap_domain_anomaly_count), 0)::BIGINT
              AS vwap_domain_anomaly_count,
            coalesce(sum(off_session_time_observed_count), 0)::BIGINT
              AS off_session_time_observed_count,
            count(*) FILTER (
              WHERE min_clock_time IS DISTINCT FROM TIME {duckdb_string(expected_times[0])}
                 OR max_clock_time IS DISTINCT FROM TIME {duckdb_string(expected_times[-1])}
            )::BIGINT AS boundary_time_variant_candidate_count
          FROM etf_mins_bar_domain_code_facts
          WHERE source_freq = {duckdb_string(evidence.source_freq)}
        )
        SELECT
          count(*)::BIGINT,
          count(*) FILTER (
            WHERE ts_code IS NULL OR freq IS NULL OR trade_time IS NULL
          )::BIGINT,
          coalesce((SELECT sum(duplicate_count) FROM duplicate_keys), 0)::BIGINT,
          count(*) FILTER (
            WHERE trade_time IS NOT NULL
              AND CAST(trade_time AS DATE) <> DATE {duckdb_string(evidence.partition_key)}
          )::BIGINT,
          count(*) FILTER (
            WHERE freq IS NOT NULL AND freq <> {duckdb_string(evidence.source_freq)}
          )::BIGINT,
          count(*) FILTER (
            WHERE ts_code IS NOT NULL AND NOT ({exchange_predicate})
          )::BIGINT,
          (SELECT count(*) FROM etf_mins_bar_domain_grid_differences
            WHERE source_freq = {duckdb_string(evidence.source_freq)})::BIGINT,
          (SELECT price_domain_anomaly_count FROM code_summary),
          (SELECT volume_amount_domain_anomaly_count FROM code_summary),
          (SELECT vwap_domain_anomaly_count FROM code_summary),
          (SELECT off_session_time_observed_count FROM code_summary),
          (SELECT boundary_time_variant_candidate_count FROM code_summary)
        FROM partition_rows
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("etf_mins_bar_domain_summary_missing.")
    (
        row_count,
        null_key_count,
        duplicate_key_count,
        date_mismatch_count,
        freq_mismatch_count,
        exchange_mismatch_count,
        minute_grid_contract_anomaly_count,
        price_domain_anomaly_count,
        volume_amount_domain_anomaly_count,
        vwap_domain_anomaly_count,
        off_session_time_observed_count,
        boundary_time_variant_candidate_count,
    ) = (int(value) for value in row)
    issue_counts = {
        "all_frequencies_empty": int(total_row_count == 0),
        "partial_frequency_empty": int(row_count == 0 and total_row_count > 0),
        "expected_code_missing": evidence.missing_count,
        "minute_grid_contract_anomaly": minute_grid_contract_anomaly_count,
        "boundary_time_variant_candidate": boundary_time_variant_candidate_count,
        "price_domain_anomaly": price_domain_anomaly_count,
        "volume_amount_domain_anomaly": volume_amount_domain_anomaly_count,
        "vwap_domain_anomaly": vwap_domain_anomaly_count,
        "off_session_time_observed": off_session_time_observed_count,
        "unexplained_new_code_observed": evidence.unexplained_new_count,
        "key_contract_anomaly": null_key_count + duplicate_key_count,
        "partition_contract_anomaly": date_mismatch_count + freq_mismatch_count,
        "exchange_identity_anomaly": exchange_mismatch_count,
        "full_zero_volume_etf_day_observed": len(full_zero_codes),
        "known_non_required_code_present": evidence.known_non_required_present_count,
        "retained_legacy_code_present": evidence.retained_legacy_count,
    }
    blocking_reasons = tuple(
        reason for reason in policy.blocking_reason_codes if issue_counts[reason] > 0
    )
    warning_reasons = tuple(
        reason for reason in policy.warning_reason_codes if issue_counts[reason] > 0
    )
    reasons = blocking_reasons + warning_reasons
    decision = "blocked" if blocking_reasons else "warn" if warning_reasons else "green"
    anomalous_codes = tuple(
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT ts_code
            FROM etf_mins_bar_domain_code_facts
            WHERE source_freq = {duckdb_string(evidence.source_freq)}
              AND (
                price_domain_anomaly_count > 0
                OR volume_amount_domain_anomaly_count > 0
                OR vwap_domain_anomaly_count > 0
                OR off_session_time_observed_count > 0
                OR min_clock_time IS DISTINCT FROM TIME {duckdb_string(expected_times[0])}
                OR max_clock_time IS DISTINCT FROM TIME {duckdb_string(expected_times[-1])}
                OR EXISTS (
                  SELECT 1 FROM etf_mins_bar_domain_grid_differences AS grid
                  WHERE grid.source_freq = etf_mins_bar_domain_code_facts.source_freq
                    AND grid.ts_code = etf_mins_bar_domain_code_facts.ts_code
                )
              )
            ORDER BY ts_code
            LIMIT {ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT}
            """
        ).fetchall()
    )
    samples = tuple(dict.fromkeys((*anomalous_codes, *full_zero_codes)))[
        :ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT
    ]
    return EtfMinsRawBarDomainResult(
        asset_key=evidence.asset_key,
        partition_key=evidence.partition_key,
        source_freq=evidence.source_freq,
        raw_sha256=evidence.raw_sha256,
        gap_policy_version=policy.version,
        gap_policy_hash=policy.policy_hash,
        decision=decision,
        silver_eligible=not blocking_reasons,
        reason_codes=reasons,
        issue_counts=tuple(
            (reason, issue_counts[reason])
            for reason in (*policy.blocking_reason_codes, *policy.warning_reason_codes)
        ),
        samples=samples,
    )


class _BorrowedDuckDBResource:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @contextmanager
    def connect(self):  # type: ignore[no-untyped-def]
        yield self._connection


def _metadata_scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _require_string_metadata(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"etf_mins_metadata_missing: {key}.")
    return value


def _require_sha256_metadata(metadata: dict[str, Any], key: str) -> str:
    value = _require_string_metadata(metadata, key)
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RuntimeError(f"etf_mins_metadata_sha256_invalid: {key}.")
    return value


def _require_non_negative_int_metadata(metadata: dict[str, Any], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        raise TypeError(f"etf_mins_metadata_integer_invalid: {key}.")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"etf_mins_metadata_integer_invalid: {key}.") from error
    if normalized < 0:
        raise RuntimeError(f"etf_mins_metadata_integer_invalid: {key}.")
    return normalized


def _metadata_string_tuple(metadata: dict[str, Any], key: str) -> tuple[str, ...]:
    value = metadata.get(key)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"etf_mins_metadata_string_list_invalid: {key}.")
    return tuple(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED",
    "EtfMinsBarDomainCheckEvidence",
    "EtfMinsRawBarDomainResult",
    "EtfMinsRawCandidateValidation",
    "EtfMinsRawMaterializationBatchEvidence",
    "EtfMinsRawMaterializationEvidence",
    "EtfMinsSilverMaterializationEvidence",
    "audit_etf_mins_raw_file_contract",
    "audit_etf_mins_raw_request_scope",
    "audit_etf_mins_silver_file_contract",
    "audit_etf_mins_silver_raw_equivalence",
    "batch_etf_mins_raw_lake_readiness",
    "batch_etf_mins_silver_lake_readiness",
    "evaluate_etf_mins_raw_bar_domain",
    "evaluate_etf_mins_raw_candidate",
    "load_etf_mins_bar_domain_check_evidence",
    "load_etf_mins_raw_materialization_evidence",
    "load_etf_mins_raw_materialization_evidence_batch",
    "load_etf_mins_silver_materialization_evidence",
]
