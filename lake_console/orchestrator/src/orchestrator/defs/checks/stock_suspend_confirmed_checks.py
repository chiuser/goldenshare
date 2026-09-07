"""Native blocking checks with explicit unpartitioned publication identity.

Dagster 1.13.18 otherwise looks up the daily job partition for AssetCheckResult.
The explicit evaluation remains a current-run event; no runless writes here.
"""

from collections.abc import Iterator
from pathlib import Path

import dagster as dg
import duckdb as duckdb_api
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.paths import silver_stock_suspend_confirmed_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import (
    CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY,
    CONFIRMED_FACT_VERSION_METADATA_KEY,
    DAGSTER_URI_METADATA_KEY,
    CheckScope,
    build_check_metadata,
)


def _publication_failure_reason(record, *, path: Path) -> str | None:
    """Publication prerequisite, independent of file validation."""
    if record is None:
        return "publication_missing"
    if record.asset_materialization.partition is not None:
        return "publication_partition_mismatch"
    if record.asset_materialization.asset_key != dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY):
        return "publication_asset_mismatch"
    metadata = record.asset_materialization.metadata
    for key, expected, reason in (
        (DAGSTER_URI_METADATA_KEY, str(path), "publication_uri_mismatch"),
        (CONFIRMED_FACT_VERSION_METADATA_KEY, contract.STOCK_SUSPEND_CONFIRMED_VERSION, "publication_version_mismatch"),
        (CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY, contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256, "publication_hash_mismatch"),
    ):
        if getattr(metadata.get(key), "value", None) != expected:
            return reason
    return None


def _confirmed_input_path_readonly(lake_root) -> Path:
    root = lake_root.root()
    path = silver_stock_suspend_confirmed_path(root)
    contract.assert_suspend_path(path, root=root)
    contract.suspend_file_identity(path)
    return path


def _input_failure(stage: str, reason: str, error: Exception | None = None) -> dg.Failure:
    # No checked_rows: an IO/precondition failure is not a completed validation.
    return dg.Failure(
        description=f"固定停牌事实检查未完成：{stage}/{reason}。" + (f" {error}" if error else ""),
        metadata={"goldenshare/failure_stage": stage, "goldenshare/reason_code": reason,
                  "goldenshare/error_type": type(error).__name__ if error else None},
    )


def _validate_inspected_file(connection, inspection, *, schema_only: bool):
    validation = inspection.schema_validation
    if not validation.passed:
        return validation
    if not schema_only and inspection.row_count != contract.STOCK_SUSPEND_CONFIRMED_COUNTS[0]:
        return contract.ValidationResult(False, "row_count_mismatch", inspection.row_count, inspection.row_count)
    if inspection.row_count > contract.STOCK_SUSPEND_CONFIRMED_COUNTS[0]:
        return validation  # Schema is valid; no row decode or digest over the bound.
    loaded = contract.load_confirmed_relation(connection, inspection, relation_name="confirmed_check")
    if not schema_only:
        return contract.validate_confirmed_content(connection, loaded.relation_name)
    try:
        digest = contract.confirmed_logical_sha256(connection, loaded.relation_name)
    except contract.ConfirmedFactsError as error:
        if error.reason_code != "encoding_invalid":
            raise
        digest = None  # Invalid content does not invalidate a valid physical schema.
    return contract.ValidationResult(True, "ok", inspection.row_count, 0, logical_sha256=digest)


def _evaluate_confirmed_check(context, lake_root, duckdb, *, check_name: str, schema_only: bool):
    try:
        path = _confirmed_input_path_readonly(lake_root)
    except contract.ConfirmedFactsError as error:
        raise _input_failure("input_path", error.reason_code, error) from error
    except FileNotFoundError as error:
        raise _input_failure("input_path", "input_missing", error) from error
    except OSError as error:
        raise _input_failure("input_path", "input_path_error", error) from error
    records = context.instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY)), limit=1,
    ).records
    record = records[0] if records else None
    reason = _publication_failure_reason(record, path=path)
    if reason:
        raise _input_failure("publication", reason)
    stage = "input_resource"
    try:
        with duckdb.connect() as connection:
            stage = "validation"
            inspection = contract.inspect_confirmed_file(connection, path)
            validation = _validate_inspected_file(connection, inspection, schema_only=schema_only)
    except contract.ConfirmedFactsError as error:
        raise _input_failure("input_resource" if error.reason_code == "size_exceeded" else stage,
                             error.reason_code, error) from error
    except duckdb_api.OutOfMemoryException as error:
        raise _input_failure("input_resource", "resource_exhausted", error) from error
    except FileNotFoundError as error:
        raise _input_failure(stage, "input_disappeared", error) from error
    except (duckdb_api.IOException, duckdb_api.InvalidInputException, OSError) as error:
        raise _input_failure(stage, "parquet_read_error" if stage == "validation" else "connection_error", error) from error
    metadata = build_check_metadata(
        check_scope=CheckScope.SCHEMA if schema_only else CheckScope.RECONCILIATION,
        file_path=path, checked_row_count=validation.checked_rows,
        failed_row_count=validation.failed_rows,
        extra_metadata={
            CONFIRMED_FACT_VERSION_METADATA_KEY: contract.STOCK_SUSPEND_CONFIRMED_VERSION,
            CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY: validation.logical_sha256,
            "failure_stage": None if validation.passed else "validation",
            "reason_code": validation.reason_code,
            "failure_samples": list(validation.samples),
            "summary": "固定停牌事实检查通过。" if validation.passed else "固定停牌事实检查失败，禁止生成新 Silver。",
            "next_action": "等待下游生成。" if validation.passed else "人工核对固定文件及批准发布记录，不自动修复或补绿。",
            "diagnostic_ref": "查看当前检查的实际指纹、失败原因与原生发布关联。",
        },
    )
    yield AssetCheckEvaluation(
        asset_key=dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY),
        check_name=check_name, passed=validation.passed, metadata=metadata,
        severity=dg.AssetCheckSeverity.ERROR, blocking=True, partition=None,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=record.storage_id, run_id=record.event_log_entry.run_id,
            timestamp=record.timestamp,
        ),
    )
    yield dg.Output(None)


@dg.asset_check(
    asset=dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY),
    name=contract.STOCK_SUSPEND_CONFIRMED_CHECKS[0], blocking=True,
)
def silver_stock_suspend_confirmed_schema_check(
    context: dg.AssetCheckExecutionContext, lake_root: LakeRootResource, duckdb: DuckDBResource,
) -> Iterator[AssetCheckEvaluation | dg.Output]:
    yield from _evaluate_confirmed_check(
        context, lake_root, duckdb, check_name=contract.STOCK_SUSPEND_CONFIRMED_CHECKS[0], schema_only=True,
    )


@dg.asset_check(
    asset=dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY),
    name=contract.STOCK_SUSPEND_CONFIRMED_CHECKS[1], blocking=True,
)
def silver_stock_suspend_confirmed_approved_content_check(
    context: dg.AssetCheckExecutionContext, lake_root: LakeRootResource, duckdb: DuckDBResource,
) -> Iterator[AssetCheckEvaluation | dg.Output]:
    yield from _evaluate_confirmed_check(
        context, lake_root, duckdb, check_name=contract.STOCK_SUSPEND_CONFIRMED_CHECKS[1], schema_only=False,
    )
