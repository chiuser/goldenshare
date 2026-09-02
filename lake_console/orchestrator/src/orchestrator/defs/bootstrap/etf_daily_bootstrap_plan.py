"""Frozen Raw and Silver plans for ETF daily Direct Lake Bootstrap."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawSpec,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    EtfDailySilverSpec,
    audit_etf_daily_silver_relation,
    validate_etf_daily_basic_reference,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import EtfBasicSilverSnapshotReference
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION,
    ETF_DAILY_BOOTSTRAP_START_DATE,
    ETF_DAILY_COVERAGE_POLICY_REVISION,
    ETF_DAILY_DISK_SAFETY_FACTOR,
    FUND_ADJ_API_NAME,
    FUND_ADJ_PAGE_LIMIT,
    FUND_ADJ_REQUEST_POLICY,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_API_NAME,
    FUND_DAILY_PAGE_LIMIT,
    FUND_DAILY_REQUEST_POLICY,
    FUND_DAILY_SOURCE_COLUMNS,
    normalize_etf_daily_trade_date,
)

FORMAL_LAKE_ROOT = Path("/Volumes/datasource/data_lake")
BOOTSTRAP_STAGING_ROOT = Path("/Volumes/datasource/data_lake_staging")
BOOTSTRAP_REPORT_ROOT = Path("/private/tmp/goldenshare-bootstrap/etf_daily")
ETF_DAILY_BOOTSTRAP_SCHEMA_VERSION = "etf_daily_bootstrap_v1"
_FUND_DAILY_ESTIMATED_FILE_BYTES = 95_801
_FUND_ADJ_ESTIMATED_FILE_BYTES = 28_088
_TARGET_STATES = {"missing", "existing_structurally_ready", "existing_invalid"}


class EtfDailyBootstrapPlanError(ValueError):
    """Raised when an ETF daily frozen plan cannot be trusted."""


def hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists():
        if load_json(path, label="immutable ETF daily report") != dict(payload):
            raise EtfDailyBootstrapPlanError(
                f"immutable report conflicts with existing content: {path}"
            )
        return
    atomic_write_json(path, payload)


def load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EtfDailyBootstrapPlanError(f"{label} does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise EtfDailyBootstrapPlanError(f"{label} is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise EtfDailyBootstrapPlanError(f"{label} must contain one JSON object")
    return payload


@dataclass(frozen=True, slots=True)
class EtfDailyBootstrapSourceContract:
    api_name: Literal["fund_daily", "fund_adj"]
    fields: tuple[str, ...]
    page_limit: int
    request_policy_hash: str

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "fields": list(self.fields)}


@dataclass(frozen=True, slots=True)
class EtfDailyBootstrapTarget:
    asset_key: str
    trade_date: str
    target_path: str
    observed_state: Literal[
        "missing", "existing_structurally_ready", "existing_invalid"
    ]
    observed_row_count: int | None
    observed_content_hash: str | None
    observed_size_bytes: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EtfDailyRawManifestEntry:
    asset_key: Literal["raw_tushare_fund_daily", "raw_tushare_fund_adj"]
    trade_date: str
    target_path: str
    row_count: int
    content_hash: str
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EtfDailyRawBootstrapPlan:
    schema_version: str
    operation_id: str
    created_at: str
    code_revision: str
    contract_revision: str
    watermark: str
    trade_dates: tuple[str, ...]
    trade_dates_hash: str
    source_contracts: tuple[EtfDailyBootstrapSourceContract, ...]
    raw_targets: tuple[EtfDailyBootstrapTarget, ...]
    estimated_new_bytes: int
    required_free_bytes: int
    observed_free_bytes: int
    raw_plan_hash: str

    @property
    def should_stop(self) -> bool:
        return any(target.observed_state == "existing_invalid" for target in self.raw_targets)

    def hash_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "created_at": self.created_at,
            "code_revision": self.code_revision,
            "contract_revision": self.contract_revision,
            "watermark": self.watermark,
            "trade_dates": list(self.trade_dates),
            "trade_dates_hash": self.trade_dates_hash,
            "source_contracts": [item.to_dict() for item in self.source_contracts],
            "raw_targets": [item.to_dict() for item in self.raw_targets],
            "estimated_new_bytes": self.estimated_new_bytes,
            "required_free_bytes": self.required_free_bytes,
            "observed_free_bytes": self.observed_free_bytes,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.hash_payload(),
            "raw_plan_hash": self.raw_plan_hash,
            "should_stop": self.should_stop,
            "writes": {"tushare_requests": 0, "formal_lake_files": 0, "dagster_events": 0},
        }


@dataclass(frozen=True, slots=True)
class EtfDailySilverBootstrapPlan:
    schema_version: str
    operation_id: str
    created_at: str
    code_revision: str
    contract_revision: str
    parent_raw_plan_hash: str
    raw_manifest: tuple[EtfDailyRawManifestEntry, ...]
    raw_manifest_hash: str
    coverage_policy_revision: str
    basic_reference: EtfBasicSilverSnapshotReference
    silver_targets: tuple[EtfDailyBootstrapTarget, ...]
    estimated_new_bytes: int
    required_free_bytes: int
    observed_free_bytes: int
    silver_plan_hash: str

    @property
    def trade_dates(self) -> tuple[str, ...]:
        return tuple(sorted({entry.trade_date for entry in self.raw_manifest}))

    @property
    def should_stop(self) -> bool:
        return any(target.observed_state == "existing_invalid" for target in self.silver_targets)

    def hash_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "created_at": self.created_at,
            "code_revision": self.code_revision,
            "contract_revision": self.contract_revision,
            "parent_raw_plan_hash": self.parent_raw_plan_hash,
            "raw_manifest": [item.to_dict() for item in self.raw_manifest],
            "raw_manifest_hash": self.raw_manifest_hash,
            "coverage_policy_revision": self.coverage_policy_revision,
            "basic_reference": self.basic_reference.model_dump(mode="json"),
            "silver_targets": [item.to_dict() for item in self.silver_targets],
            "estimated_new_bytes": self.estimated_new_bytes,
            "required_free_bytes": self.required_free_bytes,
            "observed_free_bytes": self.observed_free_bytes,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.hash_payload(),
            "silver_plan_hash": self.silver_plan_hash,
            "should_stop": self.should_stop,
            "writes": {"tushare_requests": 0, "formal_lake_files": 0, "dagster_events": 0},
        }


def source_contracts() -> tuple[EtfDailyBootstrapSourceContract, ...]:
    return (
        EtfDailyBootstrapSourceContract(
            api_name=FUND_DAILY_API_NAME,
            fields=FUND_DAILY_SOURCE_COLUMNS,
            page_limit=FUND_DAILY_PAGE_LIMIT,
            request_policy_hash=hash_payload(FUND_DAILY_REQUEST_POLICY.to_details()),
        ),
        EtfDailyBootstrapSourceContract(
            api_name=FUND_ADJ_API_NAME,
            fields=FUND_ADJ_SOURCE_COLUMNS,
            page_limit=FUND_ADJ_PAGE_LIMIT,
            request_policy_hash=hash_payload(FUND_ADJ_REQUEST_POLICY.to_details()),
        ),
    )


def load_registered_bootstrap_dates(instance: Any) -> tuple[str, ...]:
    raw_values = tuple(instance.get_dynamic_partitions(cn_a_etf_mins_trade_days.name))
    normalized = tuple(normalize_etf_daily_trade_date(value) for value in raw_values)
    if not normalized or len(normalized) != len(set(normalized)):
        raise EtfDailyBootstrapPlanError("registered ETF dates are empty or duplicated")
    watermark = max(normalized)
    selected = tuple(
        sorted(
            value
            for value in normalized
            if ETF_DAILY_BOOTSTRAP_START_DATE.isoformat() <= value <= watermark
        )
    )
    if not selected:
        raise EtfDailyBootstrapPlanError(
            "registered ETF date set has no date on or after 2025-01-01"
        )
    return selected


def validate_roots(lake_root: Path, staging_root: Path) -> None:
    for label, root in (("Lake", lake_root), ("staging", staging_root)):
        if not root.is_dir():
            raise EtfDailyBootstrapPlanError(
                f"{label} root must already exist as a directory: {root}"
            )
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise EtfDailyBootstrapPlanError(
            "ETF daily Bootstrap staging and Lake must share one filesystem"
        )


def required_free_bytes(estimated_new_bytes: int) -> int:
    return int(
        (Decimal(estimated_new_bytes) * ETF_DAILY_DISK_SAFETY_FACTOR).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def _audit_target(
    connection: Any,
    *,
    lake_root: Path,
    partition_key: str,
    spec: EtfDailyRawSpec | EtfDailySilverSpec,
) -> EtfDailyBootstrapTarget:
    path = spec.target_path_builder(lake_root, partition_key)
    if not path.exists():
        return EtfDailyBootstrapTarget(
            spec.asset_key, partition_key, str(path), "missing", None, None, None
        )
    row_count: int | None = None
    content_hash: str | None = None
    try:
        relation_sql = read_parquet(path, hive_partitioning=False)
        audit = (
            audit_etf_daily_raw_relation(
                connection,
                relation_sql=relation_sql,
                spec=spec,
                partition_key=partition_key,
            )
            if isinstance(spec, EtfDailyRawSpec)
            else audit_etf_daily_silver_relation(
                connection,
                relation_sql=relation_sql,
                spec=spec,
                partition_key=partition_key,
            )
        )
        row_count = audit.row_count
        content_hash = audit.content_hash
        state = (
            "existing_structurally_ready"
            if not audit.error_codes and content_hash is not None
            else "existing_invalid"
        )
    except Exception:  # noqa: BLE001 - an unreadable target is recorded as invalid.
        state = "existing_invalid"
    return EtfDailyBootstrapTarget(
        spec.asset_key,
        partition_key,
        str(path),
        state,
        row_count,
        content_hash,
        path.stat().st_size if path.is_file() else None,
    )


def inspect_targets(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
    trade_dates: Sequence[str],
    specs: Sequence[EtfDailyRawSpec | EtfDailySilverSpec],
) -> tuple[EtfDailyBootstrapTarget, ...]:
    with duckdb_resource.connect() as connection:
        return tuple(
            _audit_target(
                connection,
                lake_root=lake_root,
                partition_key=trade_date,
                spec=spec,
            )
            for trade_date in trade_dates
            for spec in specs
        )


def build_etf_daily_raw_bootstrap_plan(
    *,
    instance: Any,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    code_revision: str,
    operation_id: str | None = None,
    created_at: datetime | None = None,
    observed_free_bytes: int | None = None,
) -> EtfDailyRawBootstrapPlan:
    """Freeze a request-free Raw plan from the registered ETF partition set."""

    validate_roots(lake_root, staging_root)
    dates = load_registered_bootstrap_dates(instance)
    targets = inspect_targets(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        trade_dates=dates,
        specs=(FUND_DAILY_RAW_SPEC, FUND_ADJ_RAW_SPEC),
    )
    estimated = sum(
        _FUND_DAILY_ESTIMATED_FILE_BYTES
        if target.asset_key == FUND_DAILY_RAW_SPEC.asset_key
        else _FUND_ADJ_ESTIMATED_FILE_BYTES
        for target in targets
        if target.observed_state == "missing"
    )
    required = required_free_bytes(estimated)
    free = int(
        observed_free_bytes
        if observed_free_bytes is not None
        else shutil.disk_usage(staging_root).free
    )
    if free < required:
        raise EtfDailyBootstrapPlanError(
            f"ETF daily Raw Bootstrap space gate failed: required={required}, free={free}"
        )
    operation = operation_id or f"etf-daily-{uuid4().hex}"
    _validate_operation_id(operation)
    draft = EtfDailyRawBootstrapPlan(
        schema_version=ETF_DAILY_BOOTSTRAP_SCHEMA_VERSION,
        operation_id=operation,
        created_at=_normalize_timestamp(created_at or datetime.now().astimezone()),
        code_revision=str(code_revision).strip(),
        contract_revision=ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION,
        watermark=dates[-1],
        trade_dates=dates,
        trade_dates_hash=hash_payload(list(dates)),
        source_contracts=source_contracts(),
        raw_targets=targets,
        estimated_new_bytes=estimated,
        required_free_bytes=required,
        observed_free_bytes=free,
        raw_plan_hash="",
    )
    if not draft.code_revision:
        raise EtfDailyBootstrapPlanError("code_revision must be non-empty")
    return replace(draft, raw_plan_hash=hash_payload(draft.hash_payload()))


def build_raw_manifest(
    *,
    raw_plan: EtfDailyRawBootstrapPlan,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[EtfDailyRawManifestEntry, ...]:
    entries: list[EtfDailyRawManifestEntry] = []
    with duckdb_resource.connect() as connection:
        for trade_date in raw_plan.trade_dates:
            for spec in (FUND_DAILY_RAW_SPEC, FUND_ADJ_RAW_SPEC):
                path = spec.target_path_builder(lake_root, trade_date)
                if not path.is_file():
                    raise EtfDailyBootstrapPlanError(f"Raw manifest file is missing: {path}")
                audit = audit_etf_daily_raw_relation(
                    connection,
                    relation_sql=read_parquet(path, hive_partitioning=False),
                    spec=spec,
                    partition_key=trade_date,
                )
                if audit.error_codes or audit.content_hash is None:
                    raise EtfDailyBootstrapPlanError(
                        f"Raw manifest file is invalid: {path}, errors={audit.error_codes!r}"
                    )
                entries.append(
                    EtfDailyRawManifestEntry(
                        asset_key=spec.asset_key,  # type: ignore[arg-type]
                        trade_date=trade_date,
                        target_path=str(path),
                        row_count=audit.row_count,
                        content_hash=audit.content_hash,
                        size_bytes=path.stat().st_size,
                    )
                )
    return tuple(entries)


def build_etf_daily_silver_bootstrap_plan(
    *,
    raw_plan: EtfDailyRawBootstrapPlan,
    raw_audit_report: Mapping[str, Any],
    basic_reference: EtfBasicSilverSnapshotReference,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    code_revision: str,
    coverage_policy_revision: str,
    coverage_review_confirmed: bool,
    created_at: datetime | None = None,
    observed_free_bytes: int | None = None,
) -> EtfDailySilverBootstrapPlan:
    """Freeze Silver only after a green Raw audit and explicit coverage review."""

    validate_roots(lake_root, staging_root)
    if not coverage_review_confirmed:
        raise EtfDailyBootstrapPlanError("fund_adj coverage review is not confirmed")
    if coverage_policy_revision != ETF_DAILY_COVERAGE_POLICY_REVISION:
        raise EtfDailyBootstrapPlanError("coverage policy revision does not match code")
    _validate_raw_audit_report(raw_plan=raw_plan, report=raw_audit_report)
    manifest = build_raw_manifest(
        raw_plan=raw_plan,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
    )
    manifest_hash = hash_payload([entry.to_dict() for entry in manifest])
    if (
        raw_audit_report.get("raw_manifest_hash") != manifest_hash
        or raw_audit_report.get("raw_manifest")
        != [entry.to_dict() for entry in manifest]
    ):
        raise EtfDailyBootstrapPlanError("Raw manifest differs from the green audit")
    reference = validate_etf_daily_basic_reference(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        basic_reference=basic_reference,
    )
    targets = inspect_targets(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        trade_dates=raw_plan.trade_dates,
        specs=(FUND_DAILY_SILVER_SPEC, FUND_ADJ_SILVER_SPEC),
    )
    raw_size_by_date_and_asset = {
        (entry.trade_date, entry.asset_key): entry.size_bytes for entry in manifest
    }
    source_asset = {
        FUND_DAILY_SILVER_SPEC.asset_key: FUND_DAILY_RAW_SPEC.asset_key,
        FUND_ADJ_SILVER_SPEC.asset_key: FUND_ADJ_RAW_SPEC.asset_key,
    }
    estimated = sum(
        raw_size_by_date_and_asset[(target.trade_date, source_asset[target.asset_key])]
        for target in targets
        if target.observed_state == "missing"
    )
    required = required_free_bytes(estimated)
    free = int(
        observed_free_bytes
        if observed_free_bytes is not None
        else shutil.disk_usage(staging_root).free
    )
    if free < required:
        raise EtfDailyBootstrapPlanError(
            f"ETF daily Silver Bootstrap space gate failed: required={required}, free={free}"
        )
    draft = EtfDailySilverBootstrapPlan(
        schema_version=ETF_DAILY_BOOTSTRAP_SCHEMA_VERSION,
        operation_id=raw_plan.operation_id,
        created_at=_normalize_timestamp(created_at or datetime.now().astimezone()),
        code_revision=str(code_revision).strip(),
        contract_revision=ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION,
        parent_raw_plan_hash=raw_plan.raw_plan_hash,
        raw_manifest=manifest,
        raw_manifest_hash=manifest_hash,
        coverage_policy_revision=coverage_policy_revision,
        basic_reference=reference,
        silver_targets=targets,
        estimated_new_bytes=estimated,
        required_free_bytes=required,
        observed_free_bytes=free,
        silver_plan_hash="",
    )
    if not draft.code_revision:
        raise EtfDailyBootstrapPlanError("code_revision must be non-empty")
    return replace(draft, silver_plan_hash=hash_payload(draft.hash_payload()))


def write_raw_bootstrap_plan(plan: EtfDailyRawBootstrapPlan, path: Path) -> None:
    write_immutable_json(path, plan.to_dict())


def write_silver_bootstrap_plan(plan: EtfDailySilverBootstrapPlan, path: Path) -> None:
    write_immutable_json(path, plan.to_dict())


def load_etf_daily_raw_bootstrap_plan(
    path: Path, *, expected_plan_hash: str
) -> EtfDailyRawBootstrapPlan:
    payload = load_json(path, label="ETF daily Raw plan")
    if payload.get("raw_plan_hash") != expected_plan_hash:
        raise EtfDailyBootstrapPlanError("expected Raw Plan hash does not match report")
    try:
        plan = EtfDailyRawBootstrapPlan(
            schema_version=str(payload["schema_version"]),
            operation_id=str(payload["operation_id"]),
            created_at=str(payload["created_at"]),
            code_revision=str(payload["code_revision"]),
            contract_revision=str(payload["contract_revision"]),
            watermark=str(payload["watermark"]),
            trade_dates=tuple(str(value) for value in payload["trade_dates"]),
            trade_dates_hash=str(payload["trade_dates_hash"]),
            source_contracts=tuple(
                _source_contract_from_payload(value) for value in payload["source_contracts"]
            ),
            raw_targets=tuple(_target_from_payload(value) for value in payload["raw_targets"]),
            estimated_new_bytes=int(payload["estimated_new_bytes"]),
            required_free_bytes=int(payload["required_free_bytes"]),
            observed_free_bytes=int(payload["observed_free_bytes"]),
            raw_plan_hash=str(payload["raw_plan_hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EtfDailyBootstrapPlanError("Raw Plan is structurally invalid") from error
    _validate_raw_plan(plan, expected_plan_hash=expected_plan_hash)
    return plan


def load_etf_daily_silver_bootstrap_plan(
    path: Path, *, expected_plan_hash: str
) -> EtfDailySilverBootstrapPlan:
    payload = load_json(path, label="ETF daily Silver plan")
    if payload.get("silver_plan_hash") != expected_plan_hash:
        raise EtfDailyBootstrapPlanError("expected Silver Plan hash does not match report")
    try:
        plan = EtfDailySilverBootstrapPlan(
            schema_version=str(payload["schema_version"]),
            operation_id=str(payload["operation_id"]),
            created_at=str(payload["created_at"]),
            code_revision=str(payload["code_revision"]),
            contract_revision=str(payload["contract_revision"]),
            parent_raw_plan_hash=str(payload["parent_raw_plan_hash"]),
            raw_manifest=tuple(_manifest_from_payload(value) for value in payload["raw_manifest"]),
            raw_manifest_hash=str(payload["raw_manifest_hash"]),
            coverage_policy_revision=str(payload["coverage_policy_revision"]),
            basic_reference=EtfBasicSilverSnapshotReference.model_validate(
                payload["basic_reference"]
            ).validate_contract(),
            silver_targets=tuple(
                _target_from_payload(value) for value in payload["silver_targets"]
            ),
            estimated_new_bytes=int(payload["estimated_new_bytes"]),
            required_free_bytes=int(payload["required_free_bytes"]),
            observed_free_bytes=int(payload["observed_free_bytes"]),
            silver_plan_hash=str(payload["silver_plan_hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EtfDailyBootstrapPlanError("Silver Plan is structurally invalid") from error
    _validate_silver_plan(plan, expected_plan_hash=expected_plan_hash)
    return plan


def _validate_operation_id(value: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise EtfDailyBootstrapPlanError("operation_id must be one safe path component")


def _normalize_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EtfDailyBootstrapPlanError("created_at must include a timezone")
    return value.isoformat()


def _source_contract_from_payload(value: Mapping[str, Any]) -> EtfDailyBootstrapSourceContract:
    return EtfDailyBootstrapSourceContract(
        api_name=str(value["api_name"]),  # type: ignore[arg-type]
        fields=tuple(str(item) for item in value["fields"]),
        page_limit=int(value["page_limit"]),
        request_policy_hash=str(value["request_policy_hash"]),
    )


def _target_from_payload(value: Mapping[str, Any]) -> EtfDailyBootstrapTarget:
    return EtfDailyBootstrapTarget(
        asset_key=str(value["asset_key"]),
        trade_date=normalize_etf_daily_trade_date(str(value["trade_date"])),
        target_path=str(value["target_path"]),
        observed_state=str(value["observed_state"]),  # type: ignore[arg-type]
        observed_row_count=(
            int(value["observed_row_count"])
            if value.get("observed_row_count") is not None
            else None
        ),
        observed_content_hash=(
            str(value["observed_content_hash"])
            if value.get("observed_content_hash") is not None
            else None
        ),
        observed_size_bytes=(
            int(value["observed_size_bytes"])
            if value.get("observed_size_bytes") is not None
            else None
        ),
    )


def _manifest_from_payload(value: Mapping[str, Any]) -> EtfDailyRawManifestEntry:
    return EtfDailyRawManifestEntry(
        asset_key=str(value["asset_key"]),  # type: ignore[arg-type]
        trade_date=normalize_etf_daily_trade_date(str(value["trade_date"])),
        target_path=str(value["target_path"]),
        row_count=int(value["row_count"]),
        content_hash=str(value["content_hash"]),
        size_bytes=int(value["size_bytes"]),
    )


def _validate_raw_plan(plan: EtfDailyRawBootstrapPlan, *, expected_plan_hash: str) -> None:
    _validate_operation_id(plan.operation_id)
    dates = tuple(normalize_etf_daily_trade_date(value) for value in plan.trade_dates)
    expected = {
        (asset_key, trade_date)
        for trade_date in dates
        for asset_key in (FUND_DAILY_RAW_SPEC.asset_key, FUND_ADJ_RAW_SPEC.asset_key)
    }
    observed = {(target.asset_key, target.trade_date) for target in plan.raw_targets}
    if (
        plan.schema_version != ETF_DAILY_BOOTSTRAP_SCHEMA_VERSION
        or plan.contract_revision != ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION
        or not dates
        or dates != tuple(sorted(set(dates)))
        or dates[0] < ETF_DAILY_BOOTSTRAP_START_DATE.isoformat()
        or plan.watermark != dates[-1]
        or plan.trade_dates_hash != hash_payload(list(dates))
        or plan.source_contracts != source_contracts()
        or observed != expected
        or len(plan.raw_targets) != len(expected)
        or any(target.observed_state not in _TARGET_STATES for target in plan.raw_targets)
        or hash_payload(plan.hash_payload()) != expected_plan_hash
    ):
        raise EtfDailyBootstrapPlanError("Raw Plan payload or contract has drifted")


def _validate_silver_plan(
    plan: EtfDailySilverBootstrapPlan, *, expected_plan_hash: str
) -> None:
    _validate_operation_id(plan.operation_id)
    dates = plan.trade_dates
    raw_expected = {
        (asset_key, trade_date)
        for trade_date in dates
        for asset_key in (FUND_DAILY_RAW_SPEC.asset_key, FUND_ADJ_RAW_SPEC.asset_key)
    }
    silver_expected = {
        (asset_key, trade_date)
        for trade_date in dates
        for asset_key in (FUND_DAILY_SILVER_SPEC.asset_key, FUND_ADJ_SILVER_SPEC.asset_key)
    }
    if (
        plan.schema_version != ETF_DAILY_BOOTSTRAP_SCHEMA_VERSION
        or plan.contract_revision != ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION
        or plan.coverage_policy_revision != ETF_DAILY_COVERAGE_POLICY_REVISION
        or not dates
        or {(item.asset_key, item.trade_date) for item in plan.raw_manifest} != raw_expected
        or len(plan.raw_manifest) != len(raw_expected)
        or {(item.asset_key, item.trade_date) for item in plan.silver_targets}
        != silver_expected
        or len(plan.silver_targets) != len(silver_expected)
        or any(target.observed_state not in _TARGET_STATES for target in plan.silver_targets)
        or plan.raw_manifest_hash
        != hash_payload([entry.to_dict() for entry in plan.raw_manifest])
        or hash_payload(plan.hash_payload()) != expected_plan_hash
    ):
        raise EtfDailyBootstrapPlanError("Silver Plan payload or contract has drifted")


def _validate_raw_audit_report(
    *, raw_plan: EtfDailyRawBootstrapPlan, report: Mapping[str, Any]
) -> None:
    if (
        report.get("raw_plan_hash") != raw_plan.raw_plan_hash
        or report.get("passed") is not True
        or int(report.get("dagster_events_written", -1)) != 0
    ):
        raise EtfDailyBootstrapPlanError("Raw audit report is not green for the plan")
    expected = hash_payload({key: value for key, value in report.items() if key != "report_hash"})
    if report.get("report_hash") != expected:
        raise EtfDailyBootstrapPlanError("Raw audit report hash has drifted")


__all__ = [
    "BOOTSTRAP_REPORT_ROOT",
    "BOOTSTRAP_STAGING_ROOT",
    "ETF_DAILY_BOOTSTRAP_SCHEMA_VERSION",
    "FORMAL_LAKE_ROOT",
    "EtfDailyBootstrapPlanError",
    "EtfDailyBootstrapSourceContract",
    "EtfDailyBootstrapTarget",
    "EtfDailyRawBootstrapPlan",
    "EtfDailyRawManifestEntry",
    "EtfDailySilverBootstrapPlan",
    "atomic_write_json",
    "build_etf_daily_raw_bootstrap_plan",
    "build_etf_daily_silver_bootstrap_plan",
    "build_raw_manifest",
    "file_sha256",
    "hash_payload",
    "inspect_targets",
    "load_etf_daily_raw_bootstrap_plan",
    "load_etf_daily_silver_bootstrap_plan",
    "load_json",
    "load_registered_bootstrap_dates",
    "required_free_bytes",
    "source_contracts",
    "validate_roots",
    "write_immutable_json",
    "write_raw_bootstrap_plan",
    "write_silver_bootstrap_plan",
]
