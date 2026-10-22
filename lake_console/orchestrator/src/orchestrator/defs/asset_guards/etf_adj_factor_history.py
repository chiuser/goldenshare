"""Read original acceptance and unchanged files; never generate factor rows."""

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import dagster as dg
import sqlalchemy as sa
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable as Checks
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster._core.storage.event_log.sql_event_log import SqlEventLogStorage
from dagster._serdes import deserialize_value

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import audit_etf_daily_raw_relation
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    EtfDailySilverAudit,
    audit_etf_daily_domain,
    audit_etf_daily_silver_relation,
    audit_etf_daily_source_filter,
    validate_etf_daily_basic_reference,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import EtfBasicSilverSnapshotReference
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_SENSOR_WINDOW_LIMIT,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
)

# Business boundary approved in plan 8.5; no writable configuration or factor value.
_STOP_DATE = "2026-10-19"
_SPEC = FUND_ADJ_SILVER_SPEC


def scalar_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: getattr(value, "value", value) for key, value in metadata.items()}


@dataclass(frozen=True, slots=True)
class FactorMaterializationEvidence:
    storage_id: int | None
    run_id: str | None
    metadata: Mapping[str, Any]

    @classmethod
    def from_record(cls, record: Any) -> "FactorMaterializationEvidence":
        entry = getattr(record, "event_log_entry", None)
        mat = record.asset_materialization
        return cls(
            getattr(record, "storage_id", None),
            getattr(entry, "run_id", None),
            scalar_metadata(mat.metadata) if mat is not None else {},
        )


def needs_factor_history(asset_key: str, metadata: Mapping[str, Any]) -> bool:
    return (
        asset_key == _SPEC.asset_key
        and metadata.get("goldenshare/approved_exception_row_count", 0) != 0
    )


@dataclass(frozen=True, slots=True)
class FactorHistoryEvidence:
    materialization: FactorMaterializationEvidence
    raw_metadata: Mapping[str, Any]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactorHistoryAudit:
    relation: EtfDailySilverAudit | None
    basic_reference: EtfBasicSilverSnapshotReference | None
    errors: tuple[str, ...]
    added_row_count: int = 0


class _BorrowedConnection:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


def _original_identity_errors(
    day: str, target: FactorMaterializationEvidence
) -> list[str]:
    md = target.metadata
    if (
        day >= _STOP_DATE
        or not isinstance(target.storage_id, int)
        or not target.run_id
        or type(md.get("goldenshare/approved_exception_row_count")) is not int
        or md.get("goldenshare/approved_exception_row_count") != 1
        or md.get("goldenshare/exception_sample_codes") != ["512390.SH"]
        or not md.get("goldenshare/exception_registry_hash")
    ):
        return ["factor_history_approval_identity_invalid"]
    return []


def load_factor_history_evidence(
    instance: dg.DagsterInstance,
    targets: Mapping[str, FactorMaterializationEvidence],
    *,
    current_run_id: str | None = None,
) -> dict[str, FactorHistoryEvidence]:
    """Two bounded SQL reads for <=10 dates, original and latest checks included."""
    if not targets:
        return {}
    if len(targets) > ETF_DAILY_SENSOR_WINDOW_LIMIT:
        raise ValueError("factor_history_window_exceeds_ten_trade_dates")
    errors = {
        day: _original_identity_errors(day, item) for day, item in targets.items()
    }
    valid = {day: item for day, item in targets.items() if not errors[day]}
    raw_by_day: dict[str, Mapping[str, Any]] = {}
    try:
        storage = instance.event_log_storage
        if not isinstance(storage, SqlEventLogStorage):
            raise TypeError("factor_history_storage_unsupported")
        if valid:
            key = dg.AssetKey(_SPEC.asset_key).to_string()
            checks_filter = sa.and_(
                Checks.c.asset_key == key,
                Checks.c.partition.in_(tuple(valid)),
                Checks.c.check_name.in_(SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS),
            )
            original_filter = sa.or_(
                *(
                    sa.and_(
                        Checks.c.partition == day,
                        Checks.c.run_id == target.run_id,
                        Checks.c.materialization_event_storage_id == target.storage_id,
                    )
                    for day, target in valid.items()
                )
            )
            original_ids = (
                sa.select(sa.func.max(Checks.c.id))
                .where(checks_filter, original_filter)
                .group_by(Checks.c.partition, Checks.c.check_name)
            )
            latest_ids = sa.select(sa.func.max(Checks.c.id)).where(checks_filter)
            if current_run_id:
                latest_ids = latest_ids.where(
                    sa.or_(Checks.c.run_id.is_(None), Checks.c.run_id != current_run_id)
                )
            latest_ids = latest_ids.group_by(Checks.c.partition, Checks.c.check_name)
            raw_ids = (
                sa.select(sa.func.max(Events.c.id))
                .where(
                    Events.c.asset_key
                    == dg.AssetKey(_SPEC.raw_spec.asset_key).to_string(),
                    Events.c.dagster_event_type == "ASSET_MATERIALIZATION",
                    sa.or_(
                        *(
                            sa.and_(
                                Events.c.partition == day,
                                Events.c.id < target.storage_id,
                            )
                            for day, target in valid.items()
                        )
                    ),
                )
                .group_by(Events.c.partition)
            )
            with storage.index_connection() as connection:
                check_rows = (
                    connection.execute(
                        sa.select(Checks)
                        .where(
                            sa.or_(
                                Checks.c.id.in_(original_ids),
                                Checks.c.id.in_(latest_ids),
                            )
                        )
                        .limit(12 * len(valid) + 1)
                    )
                    .mappings()
                    .all()
                )
                raw_rows = (
                    connection.execute(
                        sa.select(Events.c.partition, Events.c.event)
                        .where(Events.c.id.in_(raw_ids))
                        .limit(len(valid) + 1)
                    )
                    .mappings()
                    .all()
                )
            if len(check_rows) > 12 * len(valid) or len(raw_rows) > len(valid):
                raise ValueError("factor_history_evidence_truncated")
            for row in raw_rows:
                entry = deserialize_value(row["event"], EventLogEntry)
                mat = entry.dagster_event.event_specific_data.materialization
                if (
                    mat.asset_key != dg.AssetKey(_SPEC.raw_spec.asset_key)
                    or mat.partition != row["partition"]
                ):
                    raise ValueError("factor_history_raw_identity_invalid")
                raw_by_day[row["partition"]] = scalar_metadata(mat.metadata)
            for day, target in valid.items():
                for name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS:
                    rows = [
                        r
                        for r in check_rows
                        if r["partition"] == day and r["check_name"] == name
                    ]
                    originals = [
                        r
                        for r in rows
                        if r["run_id"] == target.run_id
                        and r["materialization_event_storage_id"] == target.storage_id
                    ]
                    latest = [
                        r
                        for r in rows
                        if not current_run_id or r["run_id"] != current_run_id
                    ]
                    if not originals or not latest:
                        errors[day].append("factor_history_original_checks_missing")
                        continue
                    original = max(originals, key=lambda r: r["id"])
                    for row in (original, max(latest, key=lambda r: r["id"])):
                        if (
                            row["execution_status"] != "SUCCEEDED"
                            or not row["evaluation_event"]
                        ):
                            errors[day].append("factor_history_check_not_passed")
                            continue
                        entry = deserialize_value(
                            row["evaluation_event"], EventLogEntry
                        )
                        ev = entry.dagster_event.event_specific_data
                        if (
                            entry.run_id != row["run_id"]
                            or not ev.passed
                            or not ev.blocking
                            or ev.asset_key != dg.AssetKey(_SPEC.asset_key)
                            or ev.partition != day
                            or ev.check_name != name
                            or ev.target_materialization_data is None
                            or ev.target_materialization_data.storage_id
                            != target.storage_id
                            or row["materialization_event_storage_id"]
                            != target.storage_id
                        ):
                            errors[day].append("factor_history_check_binding_invalid")
                    # Only the original run proves approval. New rechecks cannot create it.
                    ev = (
                        deserialize_value(
                            original["evaluation_event"], EventLogEntry
                        ).dagster_event.event_specific_data
                        if original["evaluation_event"]
                        else None
                    )
                    if name.endswith(("source_parity_check", "basic_coverage_check")):
                        md = scalar_metadata(ev.metadata) if ev is not None else {}
                        for field in (
                            "approved_exception_row_count",
                            "exception_sample_codes",
                            "exception_registry_hash",
                        ):
                            if md.get("goldenshare/" + field) != target.metadata.get(
                                "goldenshare/" + field
                            ):
                                errors[day].append(
                                    "factor_history_approval_check_mismatch"
                                )
    except Exception as error:  # noqa: BLE001 - report unavailable original evidence.
        for day in valid:
            errors[day].append(f"factor_history_evidence_{type(error).__name__}")
    return {
        day: FactorHistoryEvidence(
            target, raw_by_day.get(day, {}), tuple(dict.fromkeys(errors[day]))
        )
        for day, target in targets.items()
    }


def audit_factor_history(
    *,
    connection: Any,
    lake_root: Path,
    trade_date: str,
    evidence: FactorHistoryEvidence,
    validated_basic_references: dict[str, EtfBasicSilverSnapshotReference],
) -> FactorHistoryAudit:
    """Original acceptance plus fresh physical hashes, schema, key, date and domain."""
    errors = list(evidence.errors)
    relation = None
    reference = None
    try:
        md = evidence.materialization.metadata
        reference = EtfBasicSilverSnapshotReference.model_validate(
            md["goldenshare/basic_reference"]
        ).validate_contract()
        fingerprint = reference.reference_fingerprint
        if fingerprint not in validated_basic_references:
            validated_basic_references[fingerprint] = (
                validate_etf_daily_basic_reference(
                    lake_root_path=lake_root,
                    duckdb_resource=cast(
                        DuckDBResource, _BorrowedConnection(connection)
                    ),
                    basic_reference=reference,
                )
            )
        reference = validated_basic_references[fingerprint]
        for field, expected in {
            "basic_reference_fingerprint": fingerprint,
            "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
            "basic_silver_content_hash": reference.silver_content_hash,
            "basic_raw_uri": reference.raw_uri,
            "basic_silver_uri": reference.silver_uri,
        }.items():
            if md.get("goldenshare/" + field) != expected:
                errors.append("factor_history_basic_binding_invalid")
        raw_path = _SPEC.raw_spec.target_path_builder(lake_root, trade_date)
        silver_path = _SPEC.target_path_builder(lake_root, trade_date)
        raw_sql = read_parquet(raw_path, hive_partitioning=False)
        silver_sql = read_parquet(silver_path, hive_partitioning=False)
        raw = audit_etf_daily_raw_relation(
            connection,
            relation_sql=raw_sql,
            spec=_SPEC.raw_spec,
            partition_key=trade_date,
        )
        relation = audit_etf_daily_silver_relation(
            connection, relation_sql=silver_sql, spec=_SPEC, partition_key=trade_date
        )
        errors.extend(raw.error_codes)
        errors.extend(relation.error_codes)
        for metadata, path, rows, content_hash in (
            (evidence.raw_metadata, raw_path, raw.row_count, raw.content_hash),
            (md, silver_path, relation.row_count, relation.content_hash),
        ):
            if (
                metadata.get("dagster/uri") != str(path)
                or metadata.get("dagster/row_count") != rows
                or not content_hash
                or metadata.get("goldenshare/content_hash") != content_hash
            ):
                errors.append("factor_history_file_content_changed")
        if (
            md.get("goldenshare/raw_row_count") != raw.row_count
            or md.get("goldenshare/written_row_count") != relation.row_count
            or md.get("goldenshare/selected_row_count", -1)
            + md.get("goldenshare/rejected_row_count", -1)
            != raw.row_count
            or md.get("goldenshare/selected_row_count", -1) + 1 != relation.row_count
        ):
            errors.append("factor_history_row_count_mismatch")
        if not relation.schema_errors:
            errors.extend(
                audit_etf_daily_domain(
                    connection, silver_relation_sql=silver_sql, spec=_SPEC
                ).error_codes
            )
            errors.extend(
                audit_etf_daily_source_filter(
                    connection,
                    silver_relation_sql=silver_sql,
                    basic_relation_sql=read_parquet(
                        Path(reference.silver_uri), hive_partitioning=False
                    ),
                ).error_codes
            )
    except Exception as error:  # noqa: BLE001 - report corrupt files without writing.
        errors.append(f"factor_history_file_{type(error).__name__}")
    return FactorHistoryAudit(relation, reference, tuple(dict.fromkeys(errors)))
