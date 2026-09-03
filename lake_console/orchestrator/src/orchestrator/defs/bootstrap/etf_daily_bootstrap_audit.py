"""Physical Raw/Silver audits for ETF daily Direct Lake Bootstrap."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.bootstrap.etf_daily_bootstrap_apply import (
    EtfDailyBootstrapCheckpointEntry,
    load_checkpoint,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    EtfDailyBootstrapPlanError,
    EtfDailyRawBootstrapPlan,
    EtfDailyRawManifestEntry,
    EtfDailySilverBootstrapPlan,
    hash_payload,
    write_immutable_json,
)
from orchestrator.defs.bootstrap.etf_daily_raw_batch_audit import (
    audit_etf_daily_raw_batch,
    etf_daily_raw_batches,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    audit_etf_daily_basic_coverage,
    audit_etf_daily_domain,
    audit_etf_daily_silver_relation,
    audit_etf_daily_source_filter,
    audit_etf_daily_source_parity,
    validate_etf_daily_basic_reference,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import EtfBasicSilverSnapshotReference


class EtfDailyBootstrapAuditError(ValueError):
    """Raised when the physical Bootstrap evidence cannot be closed."""


def run_raw_audit(
    *,
    raw_plan: EtfDailyRawBootstrapPlan,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    checkpoint_path: Path,
    latest_basic_reference: EtfBasicSilverSnapshotReference,
    output_path: Path,
) -> dict[str, object]:
    """Audit all Raw files and profile latest-Basic coverage without binding Raw."""

    started = perf_counter()
    checkpoint_entries = _validate_checkpoint_scope(
        checkpoint_path=checkpoint_path,
        phase="raw",
        plan_hash=raw_plan.raw_plan_hash,
        expected_count=2 * len(raw_plan.trade_dates),
    )
    reference = validate_etf_daily_basic_reference(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        basic_reference=latest_basic_reference,
    )
    files: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    domain_profiles: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    with duckdb_resource.connect() as connection:
        basic_sql = read_parquet(Path(reference.silver_uri), hive_partitioning=False)
        for spec, dates in etf_daily_raw_batches(raw_plan.trade_dates):
            batch = audit_etf_daily_raw_batch(
                connection,
                lake_root=lake_root,
                trade_dates=dates,
                spec=spec,
                basic_relation_sql=basic_sql,
            )
            files.extend(batch["files"])
            coverage.extend(batch["coverage_profiles"])
            domain_profiles.extend(batch["domain_profiles"])
            batches.append(batch["performance"])
    for summaries in (files, coverage, domain_profiles):
        summaries.sort(
            key=lambda item: (
                item["trade_date"],
                item["asset_key"] != FUND_DAILY_RAW_SPEC.asset_key,
            )
        )
    manifest = tuple(
        EtfDailyRawManifestEntry(
            **{key: value for key, value in item.items() if key != "error_codes"}
        )
        for item in files
    )
    manifest_by_key = {(item.asset_key, item.trade_date): item for item in manifest}
    checkpoint_failures = [
        item.to_dict()
        for item in checkpoint_entries
        if (manifest_entry := manifest_by_key.get((item.asset_key, item.trade_date)))
        is None
        or item.target_path != manifest_entry.target_path
        or item.row_count != manifest_entry.row_count
        or item.content_hash != manifest_entry.content_hash
    ]
    structural_failures = [item for item in files if item["error_codes"]]
    payload: dict[str, object] = {
        "schema_version": "etf_daily_raw_audit_v1",
        "raw_plan_hash": raw_plan.raw_plan_hash,
        "raw_manifest": [entry.to_dict() for entry in manifest],
        "raw_manifest_hash": hash_payload([entry.to_dict() for entry in manifest]),
        "basic_reference_fingerprint": reference.reference_fingerprint,
        "basic_role": "latest_ready_coverage_observation_only",
        "files": files,
        "structural_failure_count": len(structural_failures),
        "structural_failures": structural_failures,
        "checkpoint_failure_count": len(checkpoint_failures),
        "checkpoint_failures": checkpoint_failures,
        "source_write_conservation": not checkpoint_failures,
        "domain_profiles": domain_profiles,
        "coverage_profiles": coverage,
        "raw_asset_code_sets_required_equal": False,
        "passed": not structural_failures and not checkpoint_failures,
        "dagster_events_written": 0,
        "performance": {
            "batch_count": len(batches),
            "raw_batch_sql_query_count": sum(
                item["sql_query_count"] for item in batches
            ),
            "raw_data_load_count": sum(item["raw_data_load_count"] for item in batches),
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
            "batches": batches,
        },
    }
    payload["report_hash"] = hash_payload(payload)
    write_immutable_json(output_path, payload)
    return payload


def run_physical_post_audit(
    *,
    raw_plan: EtfDailyRawBootstrapPlan,
    silver_plan: EtfDailySilverBootstrapPlan,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    checkpoint_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Close the four-asset physical contract before any Dagster event write."""

    if silver_plan.parent_raw_plan_hash != raw_plan.raw_plan_hash:
        raise EtfDailyBootstrapAuditError("Silver Plan is not a child of the Raw Plan")
    raw_checkpoint = _validate_checkpoint_scope(
        checkpoint_path=checkpoint_path,
        phase="raw",
        plan_hash=raw_plan.raw_plan_hash,
        expected_count=2 * len(raw_plan.trade_dates),
    )
    silver_checkpoint = _validate_checkpoint_scope(
        checkpoint_path=checkpoint_path,
        phase="silver",
        plan_hash=silver_plan.silver_plan_hash,
        expected_count=2 * len(raw_plan.trade_dates),
    )
    reference = validate_etf_daily_basic_reference(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        basic_reference=silver_plan.basic_reference,
    )
    actual_files = _actual_dataset_files(lake_root)
    expected_paths = _expected_paths(lake_root, raw_plan.trade_dates)
    missing_paths = sorted(str(path) for path in expected_paths - actual_files)
    extra_paths = sorted(str(path) for path in actual_files - expected_paths)
    file_evidence: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    if not missing_paths and not extra_paths:
        with duckdb_resource.connect() as connection:
            basic_sql = read_parquet(
                Path(reference.silver_uri), hive_partitioning=False
            )
            for trade_date in raw_plan.trade_dates:
                for raw_spec, silver_spec in (
                    (FUND_DAILY_RAW_SPEC, FUND_DAILY_SILVER_SPEC),
                    (FUND_ADJ_RAW_SPEC, FUND_ADJ_SILVER_SPEC),
                ):
                    evidence = _audit_pair(
                        connection,
                        lake_root=lake_root,
                        trade_date=trade_date,
                        raw_spec=raw_spec,
                        silver_spec=silver_spec,
                        basic_sql=basic_sql,
                        basic_reference=reference,
                    )
                    file_evidence.extend(evidence)
                    failures.extend(
                        item for item in evidence if item["passed"] is not True
                    )
    staging_residuals = sorted(
        str(path)
        for operation in (
            f"{raw_plan.operation_id}-raw-apply",
            f"{silver_plan.operation_id}-silver-apply",
        )
        for path in (staging_root / "etf_daily" / f"operation_id={operation}").rglob(
            "*.parquet"
        )
    )
    checkpoint_by_key = {
        (item.phase, item.asset_key, item.trade_date): item
        for item in (*raw_checkpoint, *silver_checkpoint)
    }
    checkpoint_failures = [
        {
            "phase": phase,
            "asset_key": item["asset_key"],
            "trade_date": item["trade_date"],
        }
        for item in file_evidence
        for phase in ("raw" if str(item["asset_key"]).startswith("raw_") else "silver",)
        if (
            checkpoint := checkpoint_by_key.get(
                (phase, str(item["asset_key"]), str(item["trade_date"]))
            )
        )
        is None
        or checkpoint.target_path != item["target_path"]
        or checkpoint.row_count != item["row_count"]
        or checkpoint.content_hash != item["content_hash"]
    ]
    payload: dict[str, object] = {
        "schema_version": "etf_daily_physical_post_audit_v1",
        "raw_plan_hash": raw_plan.raw_plan_hash,
        "silver_plan_hash": silver_plan.silver_plan_hash,
        "trade_date_count": len(raw_plan.trade_dates),
        "expected_file_count": 4 * len(raw_plan.trade_dates),
        "actual_file_count": len(actual_files),
        "missing_paths": missing_paths,
        "extra_paths": extra_paths,
        "staging_residuals": staging_residuals,
        "checkpoint_failures": checkpoint_failures,
        "file_evidence": file_evidence,
        "basic_reference": reference.model_dump(mode="json"),
        "passed": not missing_paths
        and not extra_paths
        and not staging_residuals
        and not checkpoint_failures
        and not failures,
        "dagster_events_written": 0,
    }
    payload["report_hash"] = hash_payload(payload)
    write_immutable_json(output_path, payload)
    if payload["passed"] is not True:
        raise EtfDailyBootstrapAuditError("ETF daily physical post-audit did not pass")
    return payload


def _audit_pair(
    connection: Any,
    *,
    lake_root: Path,
    trade_date: str,
    raw_spec: Any,
    silver_spec: Any,
    basic_sql: str,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> list[dict[str, object]]:
    raw_path = raw_spec.target_path_builder(lake_root, trade_date)
    silver_path = silver_spec.target_path_builder(lake_root, trade_date)
    raw_sql = read_parquet(raw_path, hive_partitioning=False)
    silver_sql = read_parquet(silver_path, hive_partitioning=False)
    raw = audit_etf_daily_raw_relation(
        connection,
        relation_sql=raw_sql,
        spec=raw_spec,
        partition_key=trade_date,
    )
    silver = audit_etf_daily_silver_relation(
        connection,
        relation_sql=silver_sql,
        spec=silver_spec,
        partition_key=trade_date,
    )
    source_filter = audit_etf_daily_source_filter(
        connection,
        silver_relation_sql=silver_sql,
        basic_relation_sql=basic_sql,
    )
    parity = audit_etf_daily_source_parity(
        connection,
        raw_relation_sql=raw_sql,
        silver_relation_sql=silver_sql,
        basic_relation_sql=basic_sql,
        spec=silver_spec,
    )
    domain = audit_etf_daily_domain(
        connection,
        silver_relation_sql=silver_sql,
        spec=silver_spec,
    )
    coverage = audit_etf_daily_basic_coverage(
        connection,
        raw_relation_sql=raw_sql,
        silver_relation_sql=silver_sql,
        basic_relation_sql=basic_sql,
        partition_key=trade_date,
    )
    raw_evidence = {
        "asset_key": raw_spec.asset_key,
        "trade_date": trade_date,
        "target_path": str(raw_path),
        "row_count": raw.row_count,
        "content_hash": raw.content_hash,
        "source_row_count": raw.row_count,
        "normalized_row_count": raw.row_count,
        "written_row_count": raw.row_count,
        "source_fields": list(raw_spec.source_columns),
        "errors": list(raw.error_codes),
        "passed": not raw.error_codes,
    }
    silver_errors = (
        list(silver.error_codes)
        + list(source_filter.error_codes)
        + list(parity.error_codes)
        + list(domain.error_codes)
    )
    silver_evidence = {
        "asset_key": silver_spec.asset_key,
        "trade_date": trade_date,
        "target_path": str(silver_path),
        "row_count": silver.row_count,
        "content_hash": silver.content_hash,
        "raw_row_count": parity.raw_row_count,
        "selected_row_count": parity.selected_row_count,
        "rejected_row_count": parity.rejected_row_count,
        "written_row_count": silver.row_count,
        "reject_reason_counts": dict(parity.reason_counts),
        "basic_reference": basic_reference.model_dump(mode="json"),
        "basic_reference_fingerprint": basic_reference.reference_fingerprint,
        "basic_raw_snapshot_hash": basic_reference.raw_snapshot_hash,
        "basic_silver_content_hash": basic_reference.silver_content_hash,
        "basic_raw_uri": basic_reference.raw_uri,
        "basic_silver_uri": basic_reference.silver_uri,
        "source_fields": list(silver_spec.source_columns),
        "coverage_warning": coverage.has_warning,
        "errors": silver_errors,
        "passed": not silver_errors,
    }
    return [raw_evidence, silver_evidence]


def _expected_paths(lake_root: Path, dates: Sequence[str]) -> set[Path]:
    return {
        spec.target_path_builder(lake_root, trade_date)
        for trade_date in dates
        for spec in (
            FUND_DAILY_RAW_SPEC,
            FUND_ADJ_RAW_SPEC,
            FUND_DAILY_SILVER_SPEC,
            FUND_ADJ_SILVER_SPEC,
        )
    }


def _actual_dataset_files(lake_root: Path) -> set[Path]:
    roots = {
        spec.target_path_builder(lake_root, "2025-01-01").parents[1]
        for spec in (
            FUND_DAILY_RAW_SPEC,
            FUND_ADJ_RAW_SPEC,
            FUND_DAILY_SILVER_SPEC,
            FUND_ADJ_SILVER_SPEC,
        )
    }
    return {
        path for root in roots for path in root.glob("trade_date=*/part-000.parquet")
    }


def _validate_checkpoint_scope(
    *,
    checkpoint_path: Path,
    phase: str,
    plan_hash: str,
    expected_count: int,
) -> tuple[EtfDailyBootstrapCheckpointEntry, ...]:
    entries = [item for item in load_checkpoint(checkpoint_path) if item.phase == phase]
    if len(entries) != expected_count or any(
        item.phase_plan_hash != plan_hash for item in entries
    ):
        raise EtfDailyBootstrapAuditError(
            f"{phase} checkpoint does not close the frozen file set"
        )
    return tuple(entries)


def validate_report_hash(report: Mapping[str, Any]) -> None:
    if report.get("report_hash") != hash_payload(
        {key: value for key, value in report.items() if key != "report_hash"}
    ):
        raise EtfDailyBootstrapPlanError("Bootstrap report hash has drifted")


__all__ = [
    "EtfDailyBootstrapAuditError",
    "run_physical_post_audit",
    "run_raw_audit",
    "validate_report_hash",
]
