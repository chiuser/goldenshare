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
from orchestrator.defs.bootstrap.etf_daily_physical_batch_audit import (
    audit_etf_daily_physical_batch,
)
from orchestrator.defs.bootstrap.etf_daily_raw_batch_audit import (
    audit_etf_daily_raw_batch,
    etf_daily_raw_batches,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
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

    started = perf_counter()
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
    batches: list[dict[str, Any]] = []
    if not missing_paths and not extra_paths:
        with duckdb_resource.connect() as connection:
            basic_sql = read_parquet(
                Path(reference.silver_uri), hive_partitioning=False
            )
            for raw_spec, dates in etf_daily_raw_batches(raw_plan.trade_dates):
                batch = audit_etf_daily_physical_batch(
                    connection,
                    lake_root=lake_root,
                    trade_dates=dates,
                    spec=FUND_DAILY_SILVER_SPEC
                    if raw_spec is FUND_DAILY_RAW_SPEC
                    else FUND_ADJ_SILVER_SPEC,
                    basic_sql=basic_sql,
                    basic_reference=reference,
                )
                file_evidence.extend(batch["files"])
                batches.append(batch["performance"])
                failures.extend(
                    item for item in batch["files"] if item["passed"] is not True
                )
    asset_order = {
        spec.asset_key: index
        for index, spec in enumerate(
            (
                FUND_DAILY_RAW_SPEC,
                FUND_DAILY_SILVER_SPEC,
                FUND_ADJ_RAW_SPEC,
                FUND_ADJ_SILVER_SPEC,
            )
        )
    }
    file_evidence.sort(
        key=lambda item: (item["trade_date"], asset_order[item["asset_key"]])
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
        "performance": {
            "batch_count": len(batches),
            "physical_batch_sql_query_count": sum(
                item["sql_query_count"] for item in batches
            ),
            "raw_data_load_count": sum(item["raw_data_load_count"] for item in batches),
            "silver_data_load_count": sum(
                item["silver_data_load_count"] for item in batches
            ),
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
            "batches": batches,
        },
    }
    payload["report_hash"] = hash_payload(payload)
    write_immutable_json(output_path, payload)
    if payload["passed"] is not True:
        raise EtfDailyBootstrapAuditError("ETF daily physical post-audit did not pass")
    return payload


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
