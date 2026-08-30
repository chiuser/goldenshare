"""Latest-only, fail-closed ETF Basic snapshot selectors."""

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.assets.etf_basic import (
    audit_etf_basic_raw_snapshot,
    audit_etf_basic_silver_snapshot,
    raw_tushare_etf_basic,
    silver_etf_basic,
)
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    silver_etf_basic_snapshot_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import (
    RAW_ETF_BASIC_CHECKS,
    SILVER_ETF_BASIC_CHECKS,
    EtfBasicRawSnapshotReference,
    EtfBasicSilverSnapshotReference,
    build_etf_basic_raw_snapshot_reference,
    build_etf_basic_silver_snapshot_reference,
    classify_etf_basic_requestability,
    compute_etf_requestable_target_hash,
)

SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
_TERMINAL_CHECK_STATUSES = {
    AssetCheckExecutionRecordStatus.SUCCEEDED,
    AssetCheckExecutionRecordStatus.FAILED,
}


class EtfBasicReadinessError(RuntimeError):
    """The latest Basic materializations are not safe to freeze."""


def _normalize_date(value: date, *, field_name: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be a date.")
    return value


def _metadata_scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _latest_materialization(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
):
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset_key),
        limit=1,
    ).records
    if not records:
        raise EtfBasicReadinessError(
            f"etf_basic_latest_materialization_missing: {asset_key.to_user_string()}."
        )
    return records[0]


def _materialization_metadata(record) -> dict[str, Any]:
    materialization = record.asset_materialization
    if materialization is None:
        raise EtfBasicReadinessError("etf_basic_materialization_payload_missing.")
    return {
        key: _metadata_scalar(value) for key, value in materialization.metadata.items()
    }


def _require_latest_blocking_checks(
    *,
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    materialization_storage_id: int,
    check_names: tuple[str, ...],
) -> None:
    for check_name in check_names:
        records = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(asset_key, check_name),
            limit=1,
            status=_TERMINAL_CHECK_STATUSES,
        )
        if not records:
            raise EtfBasicReadinessError(
                f"etf_basic_latest_check_missing: asset={asset_key.to_user_string()}, "
                f"check={check_name}."
            )
        record = records[0]
        event = record.event
        dagster_event = event.dagster_event if event is not None else None
        evaluation = (
            dagster_event.event_specific_data if dagster_event is not None else None
        )
        target = getattr(evaluation, "target_materialization_data", None)
        if target is None or target.storage_id != materialization_storage_id:
            raise EtfBasicReadinessError(
                f"etf_basic_latest_check_not_bound: asset={asset_key.to_user_string()}, "
                f"check={check_name}."
            )
        passed = (
            record.status is AssetCheckExecutionRecordStatus.SUCCEEDED
            and bool(getattr(evaluation, "blocking", False))
            and bool(getattr(evaluation, "passed", False))
        )
        if not passed:
            raise EtfBasicReadinessError(
                f"etf_basic_latest_check_failed: asset={asset_key.to_user_string()}, "
                f"check={check_name}."
            )


def _require_observed_on_date(
    value: object,
    *,
    required_date: date,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value:
        raise EtfBasicReadinessError(f"etf_basic_{field_name}_missing.")
    try:
        observed_at = datetime.fromisoformat(value)
    except ValueError as error:
        raise EtfBasicReadinessError(
            f"etf_basic_{field_name}_invalid: expected timezone ISO-8601."
        ) from error
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise EtfBasicReadinessError(
            f"etf_basic_{field_name}_invalid: timezone is required."
        )
    observed_date = observed_at.astimezone(SHANGHAI_TIMEZONE).date()
    if observed_date != required_date:
        raise EtfBasicReadinessError(
            f"etf_basic_{field_name}_stale: observed_date={observed_date}, "
            f"required_date={required_date}."
        )
    return observed_at.isoformat()


def _require_string_metadata(
    metadata: dict[str, Any],
    key: str,
) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        raise EtfBasicReadinessError(f"etf_basic_metadata_missing: {key}.")
    return value


def _select_latest_raw_reference(
    *,
    instance: dg.DagsterInstance,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    required_freshness_date: date,
) -> tuple[EtfBasicRawSnapshotReference, object]:
    raw_record = _latest_materialization(instance, raw_tushare_etf_basic.key)
    _require_latest_blocking_checks(
        instance=instance,
        asset_key=raw_tushare_etf_basic.key,
        materialization_storage_id=raw_record.storage_id,
        check_names=RAW_ETF_BASIC_CHECKS,
    )
    metadata = _materialization_metadata(raw_record)
    raw_snapshot_hash = _require_string_metadata(
        metadata,
        "goldenshare/raw_snapshot_hash",
    )
    raw_uri = _require_string_metadata(metadata, "dagster/uri")
    raw_observed_at = _require_observed_on_date(
        metadata.get("goldenshare/observed_at"),
        required_date=required_freshness_date,
        field_name="raw_observed_at",
    )
    try:
        expected_path = raw_etf_basic_snapshot_path(
            lake_root_path,
            raw_snapshot_hash,
        )
    except ValueError as error:
        raise EtfBasicReadinessError("etf_basic_raw_snapshot_hash_invalid.") from error
    if Path(raw_uri) != expected_path:
        raise EtfBasicReadinessError(
            "etf_basic_raw_uri_hash_path_mismatch: "
            f"expected={expected_path}, observed={raw_uri}."
        )
    audit = audit_etf_basic_raw_snapshot(
        path=expected_path,
        duckdb_resource=duckdb_resource,
        expected_snapshot_hash=raw_snapshot_hash,
    )
    if not audit.passed:
        raise EtfBasicReadinessError(
            "etf_basic_latest_raw_file_invalid: "
            f"failures={(*audit.source_contract_failures, *audit.key_domain_failures, *audit.content_hash_failures)}."
        )
    return (
        build_etf_basic_raw_snapshot_reference(
            raw_snapshot_hash=raw_snapshot_hash,
            raw_uri=raw_uri,
            raw_observed_at=raw_observed_at,
        ),
        raw_record,
    )


def select_latest_etf_basic_raw_snapshot_reference(
    *,
    instance: dg.DagsterInstance,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    required_freshness_date: date,
) -> EtfBasicRawSnapshotReference:
    """Freeze only the latest checked Raw materialization; never fall back."""

    required_date = _normalize_date(
        required_freshness_date,
        field_name="required_freshness_date",
    )
    reference, _ = _select_latest_raw_reference(
        instance=instance,
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb_resource,
        required_freshness_date=required_date,
    )
    return reference


def select_latest_etf_basic_snapshot_reference(
    *,
    instance: dg.DagsterInstance,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    eligibility_as_of: date,
    required_freshness_date: date,
) -> EtfBasicSilverSnapshotReference:
    """Freeze the latest checked same-day Raw/Silver pair; never fall back."""

    eligibility_date = _normalize_date(
        eligibility_as_of,
        field_name="eligibility_as_of",
    )
    freshness_date = _normalize_date(
        required_freshness_date,
        field_name="required_freshness_date",
    )
    if freshness_date != eligibility_date:
        raise EtfBasicReadinessError(
            "etf_basic_freshness_date_mismatch: required_freshness_date must equal "
            "eligibility_as_of."
        )

    raw_reference, _ = _select_latest_raw_reference(
        instance=instance,
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb_resource,
        required_freshness_date=freshness_date,
    )
    silver_record = _latest_materialization(instance, silver_etf_basic.key)
    _require_latest_blocking_checks(
        instance=instance,
        asset_key=silver_etf_basic.key,
        materialization_storage_id=silver_record.storage_id,
        check_names=SILVER_ETF_BASIC_CHECKS,
    )
    metadata = _materialization_metadata(silver_record)
    raw_snapshot_hash = _require_string_metadata(
        metadata,
        "goldenshare/raw_snapshot_hash",
    )
    if raw_snapshot_hash != raw_reference.raw_snapshot_hash:
        raise EtfBasicReadinessError(
            "etf_basic_latest_layers_not_aligned: latest Silver does not consume "
            "the latest Raw content hash."
        )
    silver_content_hash = _require_string_metadata(
        metadata,
        "goldenshare/silver_content_hash",
    )
    silver_uri = _require_string_metadata(metadata, "dagster/uri")
    silver_observed_at = _require_observed_on_date(
        metadata.get("goldenshare/observed_at"),
        required_date=freshness_date,
        field_name="silver_observed_at",
    )
    metadata_raw_observed_at = _require_observed_on_date(
        metadata.get("goldenshare/raw_observed_at"),
        required_date=freshness_date,
        field_name="silver_raw_observed_at",
    )
    if metadata_raw_observed_at != raw_reference.raw_observed_at:
        raise EtfBasicReadinessError("etf_basic_silver_raw_observed_at_mismatch.")
    try:
        expected_silver_path = silver_etf_basic_snapshot_path(
            lake_root_path,
            raw_snapshot_hash,
        )
    except ValueError as error:
        raise EtfBasicReadinessError(
            "etf_basic_silver_snapshot_hash_invalid."
        ) from error
    if Path(silver_uri) != expected_silver_path:
        raise EtfBasicReadinessError(
            "etf_basic_silver_uri_hash_path_mismatch: "
            f"expected={expected_silver_path}, observed={silver_uri}."
        )
    silver_audit = audit_etf_basic_silver_snapshot(
        path=expected_silver_path,
        duckdb_resource=duckdb_resource,
        raw_path=Path(raw_reference.raw_uri),
        expected_raw_snapshot_hash=raw_snapshot_hash,
        expected_silver_content_hash=silver_content_hash,
    )
    if not silver_audit.passed:
        raise EtfBasicReadinessError(
            "etf_basic_latest_silver_file_invalid: "
            f"failures={(*silver_audit.source_filter_failures, *silver_audit.key_domain_failures, *silver_audit.content_hash_failures)}."
        )

    requestable_rows = tuple(
        row
        for row in silver_audit.rows
        if classify_etf_basic_requestability(
            row,
            eligibility_as_of=eligibility_date,
        )
        is None
    )
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash=raw_snapshot_hash,
        silver_content_hash=silver_content_hash,
        raw_uri=raw_reference.raw_uri,
        silver_uri=silver_uri,
        raw_observed_at=raw_reference.raw_observed_at,
        silver_observed_at=silver_observed_at,
        eligibility_as_of=eligibility_date,
        requestable_code_count=len(requestable_rows),
        requestable_code_hash=compute_etf_requestable_target_hash(requestable_rows),
    )


__all__ = [
    "EtfBasicReadinessError",
    "select_latest_etf_basic_raw_snapshot_reference",
    "select_latest_etf_basic_snapshot_reference",
]
