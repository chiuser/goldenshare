"""Stable ETF minute Raw writer shared by daily assets and bootstrap work."""

import hashlib
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter

import dagster as dg
import duckdb as duckdb_module

from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    EtfMinsBarDomainCheckEvidence,
    EtfMinsRawCandidateValidation,
    EtfMinsRawMaterializationEvidence,
    evaluate_etf_mins_raw_candidate,
    load_etf_mins_bar_domain_check_evidence,
    load_etf_mins_raw_materialization_evidence,
)
from orchestrator.defs.asset_guards.etf_mins_prod_readiness import (
    validate_etf_mins_prod_coverage_reference,
)
from orchestrator.defs.assets.etf_basic import (
    audit_etf_basic_silver_snapshot,
    silver_etf_basic,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    etf_mins_staging_path,
    lake_path_template,
    raw_etf_basic_snapshot_path,
    raw_etf_mins_path,
    silver_etf_basic_snapshot_path,
    silver_etf_mins_path,
)
from orchestrator.defs.prod_db.etf_mins import (
    build_prod_etf_mins_duckdb_attach_sql,
    build_prod_etf_mins_duckdb_source_sql,
    validate_prod_etf_mins_duckdb_contract,
    validate_prod_etf_mins_select_contract,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_ETF_MINS_SCHEMA,
    SILVER_ETF_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
    classify_etf_basic_requestability,
    compute_etf_requestable_target_hash,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_ASSET_FREQS,
    ETF_MINS_SOURCE_COLUMNS,
    EtfMinsProdCoverageReference,
    EtfMinsRawConfig,
    EtfMinsRequestableTarget,
    normalize_etf_mins_source_freq,
    normalize_etf_mins_trade_date,
    source_freq_for_etf_mins_asset_freq,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)

_SOURCE_RELATION = "etf_mins_source"
_CANDIDATE_RELATION = "etf_mins_candidate"
_BASIC_ALL_RELATION = "etf_basic_all"
_REQUESTABLE_RELATION = "etf_mins_requestable_targets"
_EXISTING_TARGET_RELATION = "etf_mins_existing_target"


class EtfMinsRawWriteError(RuntimeError):
    """Raised when an ETF minute candidate cannot be promoted safely."""


@dataclass(frozen=True, slots=True)
class EtfMinsRawWriteResult:
    target_path: Path
    partition_key: str
    source_freq: str
    source_row_count: int
    code_count: int
    query_count: int
    elapsed_ms: int
    basic_reference: EtfBasicSilverSnapshotReference
    prod_coverage_reference: EtfMinsProdCoverageReference | None
    validation: EtfMinsRawCandidateValidation
    file_sha256: str
    write_disposition: str


def write_raw_etf_mins_partition_from_prod_db(
    *,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    source_freq: str,
    partition_key: str,
    basic_reference: EtfBasicSilverSnapshotReference,
    prod_coverage_reference: EtfMinsProdCoverageReference | None,
) -> EtfMinsRawWriteResult:
    """Write one immutable ETF minute Raw partition from one Prod detail query.

    Daily callers pass the Sensor's five-frequency coverage reference.  The
    historical bootstrap caller deliberately passes ``None`` so missing codes
    and explicit zero-row files remain observable Raw facts for N3.
    """

    started_at = perf_counter()
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    normalized_partition = normalize_etf_mins_trade_date(partition_key)
    _assert_lake_and_staging_roots(lake_root=lake_root, staging_root=staging_root)
    normalized_basic_reference, requestable_targets = (
        revalidate_etf_mins_basic_reference(
            duckdb=duckdb,
            lake_root=lake_root,
            basic_reference=basic_reference,
        )
    )
    if prod_coverage_reference is not None:
        normalized_coverage_reference = validate_etf_mins_prod_coverage_reference(
            partition_key=normalized_partition,
            basic_reference=normalized_basic_reference,
            requestable_targets=requestable_targets,
            coverage_reference=prod_coverage_reference,
        )
    else:
        normalized_coverage_reference = None

    validate_prod_etf_mins_select_contract()
    validate_prod_etf_mins_duckdb_contract()
    partition_date = date.fromisoformat(normalized_partition)
    source_sql = build_prod_etf_mins_duckdb_source_sql(
        source_freq=normalized_freq,
        start_datetime=f"{normalized_partition} 00:00:00",
        end_datetime=f"{(partition_date + timedelta(days=1)).isoformat()} 00:00:00",
    )
    target_path = raw_etf_mins_path(
        lake_root,
        normalized_freq,
        normalized_partition,
    )
    candidate_path = etf_mins_staging_path(
        staging_root,
        operation_id,
        "raw",
        normalized_freq,
        normalized_partition,
    )
    if candidate_path.exists():
        raise EtfMinsRawWriteError(
            "etf_mins_staging_conflict: the run-scoped candidate already exists: "
            f"{candidate_path}."
        )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect() as connection:
        _load_duckdb_postgres_extension(connection)
        _attach_prod_etf_mins_readonly(
            connection,
            postgres_connection_string=prod_postgres.duckdb_connection_string(),
        )
        try:
            connection.execute(f"CREATE TEMP TABLE {_SOURCE_RELATION} AS {source_sql}")
        except duckdb_module.Error:
            raise EtfMinsRawWriteError(
                "etf_mins_source_detail_query_failed: the single bounded Prod "
                "detail query failed; connection details and SQL are omitted."
            ) from None
        try:
            connection.execute(
                copy_query_to_parquet(
                    _ordered_etf_mins_source_sql(),
                    candidate_path,
                )
            )
        except duckdb_module.Error:
            raise EtfMinsRawWriteError(
                "etf_mins_staging_write_failed: the detail relation could not be "
                f"written to the run-scoped candidate: {candidate_path}."
            ) from None
        try:
            connection.execute(
                f"CREATE TEMP VIEW {_CANDIDATE_RELATION} AS "
                f"SELECT * FROM {read_parquet(candidate_path, hive_partitioning=False)}"
            )
        except duckdb_module.Error:
            raise EtfMinsRawWriteError(
                "etf_mins_staging_readback_failed: the run-scoped candidate is not "
                f"a readable Parquet file: {candidate_path}."
            ) from None
        create_etf_mins_frozen_basic_relations(
            connection,
            basic_reference=normalized_basic_reference,
        )
        existing_relation = _create_existing_target_relation(
            connection,
            target_path=target_path,
        )
        validation = evaluate_etf_mins_raw_candidate(
            connection=connection,
            source_relation=_SOURCE_RELATION,
            candidate_relation=_CANDIDATE_RELATION,
            basic_all_relation=_BASIC_ALL_RELATION,
            requestable_targets_relation=_REQUESTABLE_RELATION,
            trade_date=normalized_partition,
            source_freq=normalized_freq,
            existing_target_relation=existing_relation,
        )
        if not validation.promotion_allowed:
            raise EtfMinsRawWriteError(
                "etf_mins_raw_candidate_rejected: "
                f"reason_codes={validation.stable_blocking_reason_codes}, "
                f"unexplained_new_samples={validation.unexplained_new_samples}, "
                f"candidate={candidate_path}."
            )
        if normalized_coverage_reference is not None and (
            validation.source_row_count == 0 or validation.missing_count != 0
        ):
            raise EtfMinsRawWriteError(
                "etf_mins_daily_coverage_candidate_mismatch: the single detail query "
                "does not match the carried all-green coverage reference; "
                f"source_row_count={validation.source_row_count}, "
                f"missing_count={validation.missing_count}, candidate={candidate_path}."
            )

        if target_path.exists() and existing_relation is None:
            existing_relation = _create_existing_target_relation(
                connection,
                target_path=target_path,
            )
        if existing_relation is not None:
            if not etf_mins_relations_are_semantically_equal(
                connection,
                left_relation=_CANDIDATE_RELATION,
                right_relation=existing_relation,
            ):
                raise EtfMinsRawWriteError(
                    "etf_mins_target_conflict: the formal target differs from the "
                    f"validated candidate and will not be overwritten: {target_path}."
                )
            candidate_path.unlink()
            write_disposition = "reused"
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                raise EtfMinsRawWriteError(
                    "etf_mins_target_conflict: the formal target appeared during "
                    f"promotion and will not be overwritten: {target_path}."
                )
            try:
                os.replace(candidate_path, target_path)
            except OSError:
                raise EtfMinsRawWriteError(
                    "etf_mins_atomic_promote_failed: the validated candidate was not "
                    f"promoted to the formal target: {target_path}."
                ) from None
            write_disposition = "added"

    _remove_empty_staging_directories(
        candidate_path=candidate_path,
        staging_root=staging_root,
    )
    if not target_path.is_file():
        raise EtfMinsRawWriteError(
            f"etf_mins_formal_file_missing_after_promote: {target_path}."
        )
    return EtfMinsRawWriteResult(
        target_path=target_path,
        partition_key=normalized_partition,
        source_freq=normalized_freq,
        source_row_count=validation.source_row_count,
        code_count=validation.distinct_code_count,
        query_count=1,
        elapsed_ms=max(0, int((perf_counter() - started_at) * 1000)),
        basic_reference=normalized_basic_reference,
        prod_coverage_reference=normalized_coverage_reference,
        validation=validation,
        file_sha256=_sha256_file(target_path),
        write_disposition=write_disposition,
    )


def build_etf_mins_raw_materialization_metadata(
    result: EtfMinsRawWriteResult,
) -> dict[str, object]:
    """Build the stable P5 metadata contract for a later Raw asset."""

    validation = result.validation
    reference = result.basic_reference
    extra_metadata: dict[str, object] = {
        "partition_key": result.partition_key,
        "source_freq": result.source_freq,
        "source_method": "prod_db_readonly",
        "source_row_count": result.source_row_count,
        "code_count": result.code_count,
        "query_count": result.query_count,
        "elapsed_ms": result.elapsed_ms,
        "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
        "basic_silver_content_hash": reference.silver_content_hash,
        "basic_raw_observed_at": reference.raw_observed_at,
        "basic_silver_observed_at": reference.silver_observed_at,
        "basic_reference_fingerprint": reference.reference_fingerprint,
        "eligibility_as_of": reference.eligibility_as_of,
        "requestable_code_count": reference.requestable_code_count,
        "requestable_code_hash": reference.requestable_code_hash,
        "expected_count": validation.expected_count,
        "present_count": validation.present_count,
        "missing_count": validation.missing_count,
        "known_non_required_present_count": (
            validation.known_non_required_present_count
        ),
        "retained_legacy_count": validation.retained_legacy_count,
        "unexplained_new_count": validation.unexplained_new_count,
        "file_sha256": result.file_sha256,
        "write_disposition": result.write_disposition,
        "policy_state": validation.policy_state,
        "silver_eligible": validation.silver_eligible,
    }
    if result.prod_coverage_reference is not None:
        extra_metadata["prod_coverage_reference_fingerprint"] = (
            result.prod_coverage_reference.coverage_fingerprint
        )
    return build_materialization_metadata(
        uri=result.target_path,
        row_count=validation.candidate_row_count,
        observed_columns=ETF_MINS_SOURCE_COLUMNS,
        extra_metadata=extra_metadata,
    )


def revalidate_etf_mins_basic_reference(
    *,
    duckdb: DuckDBResource,
    lake_root: Path,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> tuple[
    EtfBasicSilverSnapshotReference,
    tuple[EtfMinsRequestableTarget, ...],
]:
    reference = basic_reference.validate_contract()
    raw_path = Path(reference.raw_uri)
    silver_path = Path(reference.silver_uri)
    if raw_path != raw_etf_basic_snapshot_path(
        lake_root,
        reference.raw_snapshot_hash,
    ) or silver_path != silver_etf_basic_snapshot_path(
        lake_root,
        reference.raw_snapshot_hash,
    ):
        raise EtfMinsRawWriteError(
            "etf_mins_basic_reference_path_mismatch: frozen Basic files are not "
            "bound to the expected content-addressed Lake paths."
        )
    audit = audit_etf_basic_silver_snapshot(
        path=silver_path,
        duckdb_resource=duckdb,
        raw_path=raw_path,
        expected_raw_snapshot_hash=reference.raw_snapshot_hash,
        expected_silver_content_hash=reference.silver_content_hash,
    )
    if not audit.passed:
        raise EtfMinsRawWriteError(
            "etf_mins_basic_reference_invalid: "
            f"source_filter_failures={audit.source_filter_failures}, "
            f"key_domain_failures={audit.key_domain_failures}, "
            f"content_hash_failures={audit.content_hash_failures}."
        )
    eligibility_as_of = date.fromisoformat(reference.eligibility_as_of)
    requestable_rows = tuple(
        row
        for row in audit.rows
        if classify_etf_basic_requestability(
            row,
            eligibility_as_of=eligibility_as_of,
        )
        is None
    )
    requestable_hash = compute_etf_requestable_target_hash(requestable_rows)
    if (
        len(requestable_rows) != reference.requestable_code_count
        or requestable_hash != reference.requestable_code_hash
    ):
        raise EtfMinsRawWriteError(
            "etf_mins_basic_reference_changed: requestable count/hash no longer "
            "matches the frozen Basic reference."
        )
    return reference, tuple(
        EtfMinsRequestableTarget(
            ts_code=str(row["ts_code"]),
            list_date=row["list_date"],  # type: ignore[arg-type]
            exchange=str(row["exchange"]),
        )
        for row in requestable_rows
    )


def _assert_lake_and_staging_roots(*, lake_root: Path, staging_root: Path) -> None:
    for name, root in (("lake_root", lake_root), ("staging_root", staging_root)):
        if not root.is_dir():
            raise EtfMinsRawWriteError(
                f"etf_mins_{name}_unavailable: expected an existing directory: {root}."
            )
        if not os.access(root, os.R_OK | os.W_OK):
            raise EtfMinsRawWriteError(
                f"etf_mins_{name}_unavailable: directory is not readable/writable: {root}."
            )
    if os.stat(lake_root).st_dev != os.stat(staging_root).st_dev:
        raise EtfMinsRawWriteError(
            "etf_mins_cross_filesystem_promote_forbidden: lake and staging roots "
            "must use the same filesystem."
        )


def create_etf_mins_frozen_basic_relations(
    connection,
    *,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> None:
    basic_source = read_parquet(
        Path(basic_reference.silver_uri),
        hive_partitioning=False,
    )
    connection.execute(
        f"CREATE TEMP VIEW {_BASIC_ALL_RELATION} AS SELECT * FROM {basic_source}"
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW {_REQUESTABLE_RELATION} AS
        SELECT ts_code, list_date, exchange
        FROM {_BASIC_ALL_RELATION}
        WHERE list_status = 'L'
          AND list_date IS NOT NULL
          AND list_date <= CAST({duckdb_string(basic_reference.eligibility_as_of)} AS DATE)
          AND (
               (ends_with(ts_code, '.SH') AND exchange = 'SH')
            OR (ends_with(ts_code, '.SZ') AND exchange = 'SZ')
          )
        """
    )


def _create_existing_target_relation(connection, *, target_path: Path) -> str | None:
    if not target_path.is_file():
        return None
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW {_EXISTING_TARGET_RELATION} AS "
        f"SELECT * FROM {read_parquet(target_path, hive_partitioning=False)}"
    )
    return _EXISTING_TARGET_RELATION


def _ordered_etf_mins_source_sql() -> str:
    columns = ", ".join(ETF_MINS_SOURCE_COLUMNS)
    return f"SELECT {columns} FROM {_SOURCE_RELATION} ORDER BY ts_code, trade_time"


def etf_mins_relations_are_semantically_equal(
    connection,
    *,
    left_relation: str,
    right_relation: str,
) -> bool:
    columns = ", ".join(column.name for column in RAW_ETF_MINS_SCHEMA)
    try:
        difference_counts = connection.execute(
            f"""
            SELECT
              (SELECT count(*) FROM (
                SELECT {columns} FROM {left_relation}
                EXCEPT ALL
                SELECT {columns} FROM {right_relation}
              )) AS left_minus_right,
              (SELECT count(*) FROM (
                SELECT {columns} FROM {right_relation}
                EXCEPT ALL
                SELECT {columns} FROM {left_relation}
              )) AS right_minus_left
            """
        ).fetchone()
    except Exception as error:
        raise EtfMinsRawWriteError(
            "etf_mins_target_conflict: the existing target cannot be compared "
            "against the validated candidate."
        ) from error
    return difference_counts == (0, 0)


def _load_duckdb_postgres_extension(connection) -> None:
    try:
        connection.execute("LOAD postgres")
        return
    except Exception:  # noqa: BLE001 - retry for local DuckDB installations.
        try:
            connection.execute("INSTALL postgres")
            connection.execute("LOAD postgres")
        except Exception as error:
            raise EtfMinsRawWriteError(
                "DuckDB postgres extension is required for ETF minute Raw extraction."
            ) from error


def _attach_prod_etf_mins_readonly(
    connection,
    *,
    postgres_connection_string: str,
) -> None:
    attach_sql = build_prod_etf_mins_duckdb_attach_sql(
        conninfo=postgres_connection_string,
    )
    try:
        connection.execute(attach_sql)
    except Exception:  # noqa: BLE001 - never expose connection details.
        raise EtfMinsRawWriteError(
            "DuckDB failed to attach the read-only Prod Postgres source for ETF minutes."
        ) from None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_empty_staging_directories(
    *,
    candidate_path: Path,
    staging_root: Path,
) -> None:
    stop_at = staging_root / "etf_mins"
    current = candidate_path.parent
    while current != stop_at and current.is_relative_to(stop_at):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


class EtfMinsSilverWriteError(RuntimeError):
    """Raised when an ETF minute Silver partition cannot be published safely."""


@dataclass(frozen=True, slots=True)
class EtfMinsSilverWriteResult:
    target_path: Path
    partition_key: str
    source_freq: str
    row_count: int
    code_count: int
    raw_evidence: EtfMinsRawMaterializationEvidence
    bar_domain_evidence: EtfMinsBarDomainCheckEvidence
    raw_sha256: str
    silver_sha256: str
    write_disposition: str


def write_silver_etf_mins_partition(
    *,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    duckdb: DuckDBResource,
    raw_evidence: EtfMinsRawMaterializationEvidence,
    bar_domain_evidence: EtfMinsBarDomainCheckEvidence,
) -> EtfMinsSilverWriteResult:
    """Publish an exact typed copy of one already-admitted Raw partition."""

    _assert_lake_and_staging_roots(lake_root=lake_root, staging_root=staging_root)
    if bar_domain_evidence.raw_storage_id != raw_evidence.storage_id:
        raise EtfMinsSilverWriteError("etf_mins_silver_bar_check_binding_mismatch.")
    if bar_domain_evidence.raw_sha256 != raw_evidence.raw_sha256:
        raise EtfMinsSilverWriteError("etf_mins_silver_raw_hash_binding_mismatch.")
    if bar_domain_evidence.decision not in {"green", "warn"}:
        raise EtfMinsSilverWriteError("etf_mins_silver_raw_decision_not_admissible.")
    target_path = silver_etf_mins_path(
        lake_root,
        raw_evidence.source_freq,
        raw_evidence.partition_key,
    )
    candidate_path = etf_mins_staging_path(
        staging_root,
        operation_id,
        "silver",
        raw_evidence.source_freq,
        raw_evidence.partition_key,
    )
    if candidate_path.exists():
        raise EtfMinsSilverWriteError(f"etf_mins_staging_conflict: {candidate_path}.")
    candidate_path.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect() as connection:
        raw_relation = read_parquet(raw_evidence.raw_path, hive_partitioning=False)
        try:
            connection.execute(
                copy_query_to_parquet(
                    build_etf_mins_silver_copy_sql(raw_relation),
                    candidate_path,
                )
            )
            candidate_relation = read_parquet(candidate_path, hive_partitioning=False)
            observed_schema = tuple(
                (str(row[0]), str(row[1]).upper())
                for row in connection.execute(
                    f"DESCRIBE SELECT * FROM {candidate_relation}"
                ).fetchall()
            )
        except duckdb_module.Error:
            raise EtfMinsSilverWriteError(
                "etf_mins_silver_candidate_write_or_readback_failed."
            ) from None
        expected_schema = tuple(
            (column.name, column.type) for column in SILVER_ETF_MINS_SCHEMA
        )
        if observed_schema != expected_schema:
            raise EtfMinsSilverWriteError("etf_mins_silver_candidate_schema_mismatch.")
        try:
            raw_equal = etf_mins_relations_are_semantically_equal(
                connection,
                left_relation=raw_relation,
                right_relation=candidate_relation,
            )
        except EtfMinsRawWriteError as error:
            raise EtfMinsSilverWriteError(
                "etf_mins_silver_raw_equivalence_check_failed."
            ) from error
        if not raw_equal:
            raise EtfMinsSilverWriteError("etf_mins_silver_candidate_differs_from_raw.")
        counts = connection.execute(
            f"SELECT count(*), count(DISTINCT ts_code) FROM {candidate_relation}"
        ).fetchone()
        if counts is None or int(counts[0]) != raw_evidence.row_count:
            raise EtfMinsSilverWriteError(
                "etf_mins_silver_candidate_row_count_mismatch."
            )

        if target_path.exists():
            target_relation = read_parquet(target_path, hive_partitioning=False)
            try:
                target_equal = etf_mins_relations_are_semantically_equal(
                    connection,
                    left_relation=candidate_relation,
                    right_relation=target_relation,
                )
            except EtfMinsRawWriteError as error:
                raise EtfMinsSilverWriteError(
                    "etf_mins_target_conflict: existing Silver is unreadable."
                ) from error
            if not target_equal:
                raise EtfMinsSilverWriteError(
                    "etf_mins_target_conflict: existing Silver differs from Raw."
                )
            candidate_path.unlink()
            write_disposition = "reused"
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                raise EtfMinsSilverWriteError(
                    "etf_mins_target_conflict: Silver target appeared during promote."
                )
            try:
                os.replace(candidate_path, target_path)
            except OSError:
                raise EtfMinsSilverWriteError(
                    "etf_mins_silver_atomic_promote_failed."
                ) from None
            write_disposition = "added"

    _remove_empty_staging_directories(
        candidate_path=candidate_path,
        staging_root=staging_root,
    )
    return EtfMinsSilverWriteResult(
        target_path=target_path,
        partition_key=raw_evidence.partition_key,
        source_freq=raw_evidence.source_freq,
        row_count=int(counts[0]),
        code_count=int(counts[1]),
        raw_evidence=raw_evidence,
        bar_domain_evidence=bar_domain_evidence,
        raw_sha256=raw_evidence.raw_sha256,
        silver_sha256=_sha256_file(target_path),
        write_disposition=write_disposition,
    )


def build_etf_mins_silver_materialization_metadata(
    result: EtfMinsSilverWriteResult,
) -> dict[str, object]:
    reference = result.raw_evidence.basic_reference
    return build_materialization_metadata(
        uri=result.target_path,
        row_count=result.row_count,
        observed_columns=ETF_MINS_SOURCE_COLUMNS,
        extra_metadata={
            "partition_key": result.partition_key,
            "source_freq": result.source_freq,
            "code_count": result.code_count,
            "raw_uri": str(result.raw_evidence.raw_path),
            "raw_sha256": result.raw_sha256,
            "silver_sha256": result.silver_sha256,
            "write_disposition": result.write_disposition,
            "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
            "basic_silver_content_hash": reference.silver_content_hash,
            "basic_raw_observed_at": reference.raw_observed_at,
            "basic_silver_observed_at": reference.silver_observed_at,
            "basic_reference_fingerprint": reference.reference_fingerprint,
            "eligibility_as_of": reference.eligibility_as_of,
            "requestable_code_hash": reference.requestable_code_hash,
            "gap_policy_version": result.bar_domain_evidence.gap_policy_version,
            "bar_domain_decision": result.bar_domain_evidence.decision,
            "bar_domain_reason_codes": list(result.bar_domain_evidence.reason_codes),
        },
    )


def build_etf_mins_silver_copy_sql(raw_relation: str) -> str:
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS VARCHAR) AS freq,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(open AS DOUBLE) AS open,
      CAST(close AS DOUBLE) AS close,
      CAST(high AS DOUBLE) AS high,
      CAST(low AS DOUBLE) AS low,
      CAST(vol AS BIGINT) AS vol,
      CAST(amount AS DOUBLE) AS amount,
      CAST(vwap AS DOUBLE) AS vwap,
      CAST(exchange AS VARCHAR) AS exchange
    FROM {raw_relation}
    ORDER BY ts_code, trade_time
    """


def build_raw_etf_mins_asset(*, minutes: int) -> dg.AssetsDefinition:
    source_freq = source_freq_for_etf_mins_asset_freq(minutes)
    asset_name = f"raw_etf_mins_{minutes}m"

    def raw_asset(
        context: dg.AssetExecutionContext,
        config: EtfMinsRawConfig,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
        prod_postgres: ProdPostgresResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        result = write_raw_etf_mins_partition_from_prod_db(
            lake_root=lake_root.root(),
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            operation_id=context.run_id,
            duckdb=duckdb,
            prod_postgres=prod_postgres,
            source_freq=source_freq,
            partition_key=context.partition_key,
            basic_reference=config.basic_snapshot_reference,
            prod_coverage_reference=config.prod_coverage_reference.to_reference(),
        )
        return dg.MaterializeResult(
            metadata=build_etf_mins_raw_materialization_metadata(result)
        )

    return dg.asset(
        name=asset_name,
        deps=[silver_etf_basic],
        partitions_def=cn_a_etf_mins_trade_days,
        group_name="quote",
        tags=build_asset_tags(
            layer=AssetLayer.RAW,
            data_domain=DataDomain.QUOTE_DATA,
        ),
        metadata=build_asset_definition_metadata(
            dataset_id="etf_mins",
            source_system=SourceSystem.TUSHARE,
            source_api="etf_mins",
            source_doc="docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md",
            data_contract="source_mirror",
            column_schema=RAW_ETF_MINS_SCHEMA,
            path_template=lake_path_template(
                raw_etf_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    source_freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            extra_metadata={
                "frequency": source_freq,
                "source_method": "prod_db_readonly",
            },
        ),
        description=(
            f"按交易日保存 Prod Raw 中 {source_freq} ETF 分钟物理事实；"
            "三项 blocking checks 通过后才 ready，失败不删除已经安全保存的 Raw 文件。"
        ),
    )(raw_asset)


RAW_ETF_MINS_ASSETS = tuple(
    build_raw_etf_mins_asset(minutes=minutes) for minutes in ETF_MINS_ASSET_FREQS
)


def build_silver_etf_mins_asset(
    *,
    minutes: int,
    raw_asset: dg.AssetsDefinition,
) -> dg.AssetsDefinition:
    source_freq = source_freq_for_etf_mins_asset_freq(minutes)
    asset_name = f"silver_etf_mins_{minutes}m"

    @dg.asset(
        name=asset_name,
        deps=[raw_asset],
        partitions_def=cn_a_etf_mins_trade_days,
        group_name="quote",
        tags=build_asset_tags(
            layer=AssetLayer.SILVER,
            data_domain=DataDomain.QUOTE_DATA,
        ),
        metadata=build_asset_definition_metadata(
            dataset_id="etf_mins",
            source_system=SourceSystem.DERIVED,
            data_contract="audited_exact_copy",
            column_schema=SILVER_ETF_MINS_SCHEMA,
            path_template=lake_path_template(
                silver_etf_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    source_freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            extra_metadata={"frequency": source_freq},
        ),
        description=(
            f"按交易日保存通过当前 N3 policy 的 {source_freq} ETF 分钟完整分区，"
            "与对应 Raw 11 字段逐行等价；供下游分析消费。"
        ),
    )
    def silver_asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        raw_evidence = load_etf_mins_raw_materialization_evidence(
            instance=context.instance,
            lake_root=lake_root.root(),
            asset_key=raw_asset.key,
            partition_key=context.partition_key,
            source_freq=source_freq,
        )
        bar_domain_evidence = load_etf_mins_bar_domain_check_evidence(
            instance=context.instance,
            raw_evidence=raw_evidence,
        )
        result = write_silver_etf_mins_partition(
            lake_root=lake_root.root(),
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            operation_id=context.run_id,
            duckdb=duckdb,
            raw_evidence=raw_evidence,
            bar_domain_evidence=bar_domain_evidence,
        )
        return dg.MaterializeResult(
            metadata=build_etf_mins_silver_materialization_metadata(result)
        )

    return silver_asset


SILVER_ETF_MINS_ASSETS = tuple(
    build_silver_etf_mins_asset(minutes=minutes, raw_asset=raw_asset)
    for minutes, raw_asset in zip(
        ETF_MINS_ASSET_FREQS,
        RAW_ETF_MINS_ASSETS,
        strict=True,
    )
)

(
    raw_etf_mins_1m,
    raw_etf_mins_5m,
    raw_etf_mins_15m,
    raw_etf_mins_30m,
    raw_etf_mins_60m,
) = RAW_ETF_MINS_ASSETS

(
    silver_etf_mins_1m,
    silver_etf_mins_5m,
    silver_etf_mins_15m,
    silver_etf_mins_30m,
    silver_etf_mins_60m,
) = SILVER_ETF_MINS_ASSETS


__all__ = [
    "RAW_ETF_MINS_ASSETS",
    "SILVER_ETF_MINS_ASSETS",
    "EtfMinsRawWriteError",
    "EtfMinsRawWriteResult",
    "EtfMinsSilverWriteError",
    "EtfMinsSilverWriteResult",
    "build_etf_mins_raw_materialization_metadata",
    "build_etf_mins_silver_copy_sql",
    "build_etf_mins_silver_materialization_metadata",
    "build_raw_etf_mins_asset",
    "build_silver_etf_mins_asset",
    "create_etf_mins_frozen_basic_relations",
    "etf_mins_relations_are_semantically_equal",
    "raw_etf_mins_1m",
    "raw_etf_mins_5m",
    "raw_etf_mins_15m",
    "raw_etf_mins_30m",
    "raw_etf_mins_60m",
    "revalidate_etf_mins_basic_reference",
    "silver_etf_mins_1m",
    "silver_etf_mins_5m",
    "silver_etf_mins_15m",
    "silver_etf_mins_30m",
    "silver_etf_mins_60m",
    "write_raw_etf_mins_partition_from_prod_db",
    "write_silver_etf_mins_partition",
]
