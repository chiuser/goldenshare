"""Audit an approved addition while preserving every originally accepted row."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable as Checks
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster._serdes import deserialize_value

from orchestrator.defs.asset_guards.etf_adj_factor_history import (
    FactorHistoryAudit,
    FactorMaterializationEvidence,
    scalar_metadata,
)
from orchestrator.defs.assets.etf_basic import (
    ETF_BASIC_SILVER_COLUMN_TYPES,
    audit_etf_basic_silver_snapshot,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import audit_etf_daily_raw_relation
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC as SPEC,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    audit_etf_daily_domain,
    audit_etf_daily_silver_relation,
    etf_daily_classified_select,
)
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    silver_etf_basic_snapshot_path,
)
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_SOURCE_COLUMNS,
    EtfBasicSilverSnapshotReference,
    classify_etf_basic_requestability,
    compute_etf_basic_silver_content_hash,
    compute_etf_requestable_target_hash,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_FACTOR_COMPLETION_METADATA_KEY,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    EtfFactorCompletionPlan,
)


class CompletionBasicCache:
    """Cache physical snapshot audits, but validate each dated reference separately."""

    def __init__(
        self, connection: Any, lake_root: Path, *, allow_full_read: bool = True
    ) -> None:
        self.connection = connection
        self.lake_root = lake_root
        self.allow_full_read = allow_full_read
        self.snapshots: dict[
            tuple[str, str, str, str], tuple[tuple[dict, ...], str]
        ] = {}
        self.references: dict[str, EtfBasicSilverSnapshotReference] = {}
        self._seeded_references: set[str] = set()

    def seed(
        self, reference: EtfBasicSilverSnapshotReference, rows: Sequence[Mapping]
    ) -> None:
        """Reuse an actual caller-owned full audit; never exposed as an operator option."""
        reference.validate_contract()
        if compute_etf_basic_silver_content_hash(rows) != reference.silver_content_hash:
            raise ValueError("completion_cached_basic_content_mismatch")
        key = self._key(reference)
        if key not in self.snapshots:
            if len(rows) > 5000:
                raise ValueError("completion_basic_rows_exceed_budget")
            table = f"completion_basic_{reference.raw_snapshot_hash[:16]}"
            fields = ",".join(
                f"CAST(json_extract_string(value, '$.{c}') AS {ETF_BASIC_SILVER_COLUMN_TYPES[c]}) AS {c}"
                for c in ETF_BASIC_SOURCE_COLUMNS
            )
            self.connection.execute(
                f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT {fields} FROM json_each(?)",
                [json.dumps([dict(row) for row in rows], default=str)],
            )
            self.snapshots[key] = (
                tuple(dict(r) for r in rows),
                f"SELECT * FROM {table}",
            )
        self._seeded_references.add(reference.reference_fingerprint)

    def _key(
        self, reference: EtfBasicSilverSnapshotReference
    ) -> tuple[str, str, str, str]:
        if Path(reference.raw_uri) != raw_etf_basic_snapshot_path(
            self.lake_root, reference.raw_snapshot_hash
        ) or Path(reference.silver_uri) != silver_etf_basic_snapshot_path(
            self.lake_root, reference.raw_snapshot_hash
        ):
            raise ValueError("completion_basic_path_not_formal")
        return (
            reference.raw_uri,
            reference.silver_uri,
            reference.raw_snapshot_hash,
            reference.silver_content_hash,
        )

    def get(self, reference: EtfBasicSilverSnapshotReference) -> str:
        reference.validate_contract()
        if (
            not self.allow_full_read
            and reference.reference_fingerprint not in self._seeded_references
        ):
            raise ValueError("completion_prepared_basic_reference_not_seeded")
        key = self._key(reference)
        if key not in self.snapshots:
            if not self.allow_full_read:
                raise ValueError("completion_prepared_basic_missing")
            # Existing producer validates the full pair. Different dated references
            # to the same pair reuse its rows, not another physical audit.
            from orchestrator.defs.asset_guards.etf_adj_factor_history import (
                _BorrowedConnection,
            )

            audit = audit_etf_basic_silver_snapshot(
                path=Path(reference.silver_uri),
                raw_path=Path(reference.raw_uri),
                duckdb_resource=_BorrowedConnection(self.connection),
                expected_raw_snapshot_hash=reference.raw_snapshot_hash,
                expected_silver_content_hash=reference.silver_content_hash,
            )
            if not audit.passed:
                raise ValueError("completion_basic_pair_audit_failed")
            self.seed(reference, audit.rows)
        rows, sql = self.snapshots[key]
        if reference.reference_fingerprint not in self.references:
            eligible = tuple(
                r
                for r in rows
                if classify_etf_basic_requestability(
                    r, eligibility_as_of=date.fromisoformat(reference.eligibility_as_of)
                )
                is None
            )
            if (
                len(eligible) != reference.requestable_code_count
                or compute_etf_requestable_target_hash(eligible)
                != reference.requestable_code_hash
            ):
                raise ValueError("completion_basic_reference_targets_changed")
            self.references[reference.reference_fingerprint] = reference
        return sql


@dataclass(frozen=True, slots=True)
class PreparedCompletionBasic:
    """Caller-owned audited contents; no file, process or persistent cache access."""

    snapshots: Mapping[tuple[str, str, str, str], tuple[Mapping, ...]]
    references: Mapping[str, EtfBasicSilverSnapshotReference]

    @classmethod
    def from_cache(cls, cache: CompletionBasicCache) -> "PreparedCompletionBasic":
        if not cache.snapshots or len(cache.snapshots) > 2 or not cache.references:
            raise ValueError("completion_prepared_basic_not_audited")
        return cls(
            MappingProxyType(
                {
                    key: tuple(MappingProxyType(dict(row)) for row in rows)
                    for key, (rows, _sql) in cache.snapshots.items()
                }
            ),
            MappingProxyType(dict(cache.references)),
        )

    def seed_cache(
        self,
        connection: Any,
        lake_root: Path,
        references: Sequence[EtfBasicSilverSnapshotReference],
    ) -> CompletionBasicCache:
        if not references:
            raise ValueError("completion_prepared_basic_references_missing")
        cache = CompletionBasicCache(connection, lake_root, allow_full_read=False)
        for reference in references:
            reference.validate_contract()
            if self.references.get(reference.reference_fingerprint) != reference:
                raise ValueError("completion_prepared_basic_reference_not_audited")
            key = cache._key(reference)
            rows = self.snapshots.get(key)
            if rows is None:
                raise ValueError("completion_prepared_basic_snapshot_missing")
            cache.seed(reference, rows)
            cache.get(reference)
        return cache


def require_prepared_basic(value: object) -> PreparedCompletionBasic:
    """Maintenance callers must reject missing input before daily defaults apply."""
    if not isinstance(value, PreparedCompletionBasic):
        raise TypeError("completion_prepared_basic_required")
    return value


@dataclass(frozen=True, slots=True)
class CompletionEvidence:
    errors: Mapping[str, tuple[str, ...]]


def load_completion_evidence(
    *,
    storage: Any,
    plan: EtfFactorCompletionPlan,
    days: Sequence[str],
    current_targets: Mapping[str, FactorMaterializationEvidence] | None = None,
    require_current_checks: bool = True,
) -> CompletionEvidence:
    """One bounded UNION read; mixed old/new windows stay within four queries."""
    if len(days) > 10 or len(set(days)) != len(days):
        raise ValueError("completion_evidence_window_exceeds_ten_dates")
    errors: dict[str, list[str]] = {d: [] for d in days}
    files = [plan.file(d) for d in days]
    ids = {i for f in files for i in (f.original_storage_id, f.raw_storage_id)}
    ids.add(plan.basic_evidence["storage_id"])
    original_check_ids = {i for f in files for i in f.original_check_ids.values()}
    original_check_ids.update(plan.basic_evidence["check_ids"].values())
    asset_key = '["silver_etf_adj_factor"]'
    latest_ids = (
        sa.select(sa.func.max(Checks.c.id))
        .where(
            Checks.c.asset_key == asset_key,
            Checks.c.partition.in_(days),
            Checks.c.check_name.in_(SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS),
        )
        .group_by(Checks.c.partition, Checks.c.check_name)
    )
    check_condition = Checks.c.id.in_(original_check_ids)
    if require_current_checks:
        check_condition = sa.or_(check_condition, Checks.c.id.in_(latest_ids))
    event_query = sa.select(
        sa.literal("materialization").label("kind"),
        Events.c.id,
        Events.c.event.label("event"),
        Events.c.run_id,
        Events.c.partition,
        Events.c.asset_key,
        sa.literal(None).label("check_name"),
        sa.literal(None).label("materialization_event_storage_id"),
        sa.literal(None).label("execution_status"),
    ).where(Events.c.id.in_(ids))
    check_query = sa.select(
        sa.literal("check"),
        Checks.c.id,
        Checks.c.evaluation_event,
        Checks.c.run_id,
        Checks.c.partition,
        Checks.c.asset_key,
        Checks.c.check_name,
        Checks.c.materialization_event_storage_id,
        Checks.c.execution_status,
    ).where(check_condition)
    with storage.index_connection() as connection:
        rows = (
            connection.execute(
                sa.union_all(event_query, check_query).limit(14 * len(days) + 5)
            )
            .mappings()
            .all()
        )
    records = [r for r in rows if r["kind"] == "materialization"]
    checks = [
        {**r, "evaluation_event": r["event"]} for r in rows if r["kind"] == "check"
    ]
    if len(records) > 2 * len(days) + 1 or len(checks) > 12 * len(days) + 3:
        raise ValueError("completion_evidence_truncated")
    by_id = {r["id"]: deserialize_value(r["event"], EventLogEntry) for r in records}
    checks_by_id = {r["id"]: r for r in checks}
    basic_entry = by_id.get(plan.basic_evidence["storage_id"])
    basic_mat = (
        basic_entry.dagster_event.event_specific_data.materialization
        if basic_entry
        else None
    )
    basic_valid = bool(
        basic_mat is not None
        and basic_mat.asset_key.to_user_string() == "silver_etf_basic"
        and scalar_metadata(basic_mat.metadata) == plan.basic_evidence["metadata"]
    )
    for name, cid in plan.basic_evidence["check_ids"].items():
        row = checks_by_id.get(cid)
        ev = (
            deserialize_value(
                row["evaluation_event"], EventLogEntry
            ).dagster_event.event_specific_data
            if row and row["evaluation_event"]
            else None
        )
        basic_valid = basic_valid and bool(
            row
            and row["execution_status"] == "SUCCEEDED"
            and ev is not None
            and ev.passed
            and ev.blocking
            and ev.asset_key.to_user_string() == "silver_etf_basic"
            and ev.check_name == name
            and ev.target_materialization_data is not None
            and ev.target_materialization_data.storage_id
            == plan.basic_evidence["storage_id"]
            and row["materialization_event_storage_id"]
            == plan.basic_evidence["storage_id"]
        )
    if not basic_valid:
        for day in days:
            errors[day].append("completion_frozen_basic_acceptance_invalid")
    for f in files:
        for eid, expected_asset, expected_md, expected_run in (
            (
                f.original_storage_id,
                SPEC.asset_key,
                f.original_metadata,
                f.original_run_id,
            ),
            (f.raw_storage_id, SPEC.raw_spec.asset_key, f.raw_metadata, None),
        ):
            entry = by_id.get(eid)
            mat = (
                entry.dagster_event.event_specific_data.materialization
                if entry
                else None
            )
            if (
                mat is None
                or mat.asset_key.to_user_string() != expected_asset
                or mat.partition != f.trade_date
                or scalar_metadata(mat.metadata) != expected_md
                or (expected_asset == SPEC.asset_key and entry.run_id != expected_run)
            ):
                errors[f.trade_date].append("completion_original_evidence_changed")
        for name, cid in f.original_check_ids.items():
            row = checks_by_id.get(cid)
            if row is None or not _check_matches(
                row, name, f.trade_date, f.original_storage_id, f.original_run_id
            ):
                errors[f.trade_date].append(
                    "completion_original_check_missing_or_invalid"
                )
                continue
            if f.original_metadata.get(
                "goldenshare/approved_exception_row_count"
            ) and name.endswith(("source_parity_check", "basic_coverage_check")):
                evaluation = deserialize_value(
                    row["evaluation_event"], EventLogEntry
                ).dagster_event.event_specific_data
                md = scalar_metadata(evaluation.metadata)
                if any(
                    md.get("goldenshare/" + k)
                    != f.original_metadata.get("goldenshare/" + k)
                    for k in (
                        "approved_exception_row_count",
                        "exception_sample_codes",
                        "exception_registry_hash",
                    )
                ):
                    errors[f.trade_date].append("completion_original_approval_mismatch")
            if require_current_checks:
                candidates = [
                    r
                    for r in checks
                    if r["partition"] == f.trade_date and r["check_name"] == name
                ]
                latest = max(candidates, key=lambda r: r["id"]) if candidates else None
                target = (
                    current_targets[f.trade_date].storage_id
                    if current_targets
                    else f.original_storage_id
                )
                if latest is None or not _check_matches(
                    latest, name, f.trade_date, target
                ):
                    errors[f.trade_date].append(
                        "completion_latest_check_not_passed_or_bound"
                    )
    return CompletionEvidence({d: tuple(dict.fromkeys(e)) for d, e in errors.items()})


def _check_matches(
    row: Mapping, name: str, day: str, target: int, run_id: object = ...
) -> bool:
    if row["execution_status"] != "SUCCEEDED" or not row["evaluation_event"]:
        return False
    entry = deserialize_value(row["evaluation_event"], EventLogEntry)
    ev = entry.dagster_event.event_specific_data
    return bool(
        ev.passed
        and ev.blocking
        and ev.asset_key.to_user_string() == SPEC.asset_key
        and ev.partition == day
        and ev.check_name == name
        and ev.target_materialization_data is not None
        and ev.target_materialization_data.storage_id == target
        and row["materialization_event_storage_id"] == target
        and entry.run_id == row["run_id"]
        and (run_id is ... or row["run_id"] == run_id)
    )


def completion_relations(
    *,
    plan: EtfFactorCompletionPlan,
    day: str,
    lake_root: Path,
    basic_sql: str,
    raw_relation_sql: str | None = None,
) -> tuple[str, str, str]:
    codes = plan.scope["additions"][day]
    code_list = ",".join(duckdb_string(c) for c in codes)
    raw_sql = raw_relation_sql or read_parquet(
        SPEC.raw_spec.target_path_builder(lake_root, day), hive_partitioning=False
    )
    original_sql = read_parquet(
        SPEC.target_path_builder(lake_root, day), hive_partitioning=False
    )
    classified = etf_daily_classified_select(
        raw_relation_sql=f"SELECT * FROM {raw_sql} WHERE ts_code IN ({code_list})",
        basic_relation_sql=basic_sql,
    )
    added = f"SELECT ts_code,strptime(trade_date,'%Y%m%d')::DATE AS trade_date,adj_factor,discount_rate FROM ({classified}) classified WHERE rejection_reason IS NULL"
    original = f"SELECT * FROM {original_sql} WHERE ts_code NOT IN ({code_list})"
    return (
        original,
        added,
        f"SELECT * FROM {original_sql} UNION ALL SELECT * FROM ({added}) added",
    )


def audit_completion_file(
    *,
    connection: Any,
    lake_root: Path,
    plan: EtfFactorCompletionPlan,
    trade_date: str,
    basic_cache: CompletionBasicCache,
    evidence_errors: Sequence[str] = (),
    relation_sql: str | None = None,
    expected_complete: bool = True,
) -> FactorHistoryAudit:
    """The same fact audit is used by candidate review, checks and readiness."""
    errors = list(evidence_errors)
    reference = None
    relation = None
    temporary_tables: list[str] = []
    try:
        plan.validate()
        item = plan.file(trade_date)
        reference = EtfBasicSilverSnapshotReference.model_validate(plan.basic_reference)
        basic_sql = basic_cache.get(reference)
        old_reference = EtfBasicSilverSnapshotReference.model_validate(
            item.original_metadata["goldenshare/basic_reference"]
        )
        basic_cache.get(old_reference)
        reference = old_reference
        actual_sql = (
            relation_sql
            or f"SELECT * FROM {read_parquet(SPEC.target_path_builder(lake_root, trade_date), hive_partitioning=False)}"
        )
        # Each physical input is loaded once. All later audits and set comparisons
        # use these per-call tables, including repeated DESCRIBE/hash/domain SQL.
        suffix = uuid4().hex
        actual_table = f"completion_actual_{suffix}"
        raw_table = f"completion_raw_{suffix}"
        raw_path = SPEC.raw_spec.target_path_builder(lake_root, trade_date)
        for table, sql in (
            (actual_table, actual_sql),
            (
                raw_table,
                f"SELECT * FROM {read_parquet(raw_path, hive_partitioning=False)}",
            ),
        ):
            connection.execute(f"CREATE TEMP TABLE {table} AS ({sql}) LIMIT 5001")
            temporary_tables.append(table)
            if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 5000:
                raise ValueError("completion_file_rows_exceed_budget")
        actual_sql = f"SELECT * FROM {actual_table}"
        _original, added, _candidate = completion_relations(
            plan=plan,
            day=trade_date,
            lake_root=lake_root,
            basic_sql=basic_sql,
            raw_relation_sql=raw_table,
        )
        codes = plan.scope["additions"][trade_date]
        code_list = ",".join(duckdb_string(c) for c in codes)
        actual_old = (
            f"SELECT * FROM ({actual_sql}) actual WHERE ts_code NOT IN ({code_list})"
        )
        old = audit_etf_daily_silver_relation(
            connection, relation_sql=actual_old, spec=SPEC, partition_key=trade_date
        )
        relation = audit_etf_daily_silver_relation(
            connection, relation_sql=actual_sql, spec=SPEC, partition_key=trade_date
        )
        raw = audit_etf_daily_raw_relation(
            connection,
            relation_sql=raw_table,
            spec=SPEC.raw_spec,
            partition_key=trade_date,
        )
        errors.extend(raw.error_codes)
        errors.extend(old.error_codes)
        errors.extend(relation.error_codes)
        errors.extend(
            audit_etf_daily_domain(
                connection, silver_relation_sql=actual_sql, spec=SPEC
            ).error_codes
        )
        if (
            old.row_count != item.original_metadata["dagster/row_count"]
            or old.content_hash != item.original_metadata["goldenshare/content_hash"]
            or raw.row_count != item.raw_metadata["dagster/row_count"]
            or raw.content_hash != item.raw_metadata["goldenshare/content_hash"]
            or str(raw_path) != item.raw_metadata["dagster/uri"]
            or str(SPEC.target_path_builder(lake_root, trade_date))
            != item.original_metadata["dagster/uri"]
        ):
            errors.append("completion_original_or_raw_content_changed")
        added_audit = audit_etf_daily_silver_relation(
            connection, relation_sql=added, spec=SPEC, partition_key=trade_date
        )
        errors.extend(added_audit.error_codes)
        errors.extend(
            audit_etf_daily_domain(
                connection, silver_relation_sql=added, spec=SPEC
            ).error_codes
        )
        actual_codes = {
            r[0]
            for r in connection.execute(
                f"SELECT ts_code FROM ({added}) added"
            ).fetchall()
        }
        if added_audit.row_count != len(codes) or actual_codes != set(codes):
            errors.append("completion_added_source_or_basic_incomplete")
        if expected_complete:
            actual_added = (
                f"SELECT * FROM ({actual_sql}) actual WHERE ts_code IN ({code_list})"
            )
            for left, right in ((actual_added, added), (added, actual_added)):
                if connection.execute(
                    f"SELECT count(*) FROM (({left}) EXCEPT ALL ({right})) delta"
                ).fetchone()[0]:
                    errors.append("completion_added_rows_differ_from_raw")
            if (
                relation.row_count != item.expected_row_count
                or relation.content_hash != item.expected_content_hash
            ):
                errors.append("completion_full_content_changed")
        elif relation.row_count != old.row_count:
            errors.append("completion_target_keys_already_present")
        if item.original_metadata.get("goldenshare/approved_exception_row_count"):
            from orchestrator.defs.asset_guards.etf_adj_factor_history import (
                _original_identity_errors,
            )

            errors.extend(
                _original_identity_errors(
                    trade_date,
                    FactorMaterializationEvidence(
                        item.original_storage_id,
                        item.original_run_id,
                        item.original_metadata,
                    ),
                )
            )
    except Exception as error:  # noqa: BLE001 - evidence failure must block, never overwrite.
        errors.append(f"completion_file_{type(error).__name__}")
    finally:
        for table in reversed(temporary_tables):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
    return FactorHistoryAudit(
        relation,
        reference,
        tuple(dict.fromkeys(errors)),
        added_row_count=len(plan.scope["additions"][trade_date]),
    )


def audit_completed_target(
    *,
    connection: Any,
    lake_root: Path,
    storage: Any,
    trade_date: str,
    target: FactorMaterializationEvidence,
    basic_cache: CompletionBasicCache,
    evidence_errors: Sequence[str] | None = None,
    require_current_checks: bool = True,
) -> FactorHistoryAudit:
    try:
        plan = EtfFactorCompletionPlan.from_dict(
            target.metadata[ETF_FACTOR_COMPLETION_METADATA_KEY]
        )
        item = plan.file(trade_date)
        if (
            target.metadata.get("dagster/uri")
            != str(SPEC.target_path_builder(lake_root, trade_date))
            or target.metadata.get("dagster/row_count") != item.expected_row_count
            or target.metadata.get("goldenshare/written_row_count")
            != item.expected_row_count
            or target.metadata.get("goldenshare/content_hash")
            != item.expected_content_hash
            or target.metadata.get("goldenshare/basic_reference")
            != item.original_metadata["goldenshare/basic_reference"]
        ):
            raise ValueError("completion_materialization_binding_invalid")
        if evidence_errors is None:
            evidence_errors = load_completion_evidence(
                storage=storage,
                plan=plan,
                days=[trade_date],
                current_targets={trade_date: target},
                require_current_checks=require_current_checks,
            ).errors[trade_date]
        return audit_completion_file(
            connection=connection,
            lake_root=lake_root,
            plan=plan,
            trade_date=trade_date,
            basic_cache=basic_cache,
            evidence_errors=evidence_errors,
        )
    except Exception as error:  # noqa: BLE001 - never fall back on malformed new evidence.
        return FactorHistoryAudit(
            None, None, (f"completion_target_{type(error).__name__}",)
        )
