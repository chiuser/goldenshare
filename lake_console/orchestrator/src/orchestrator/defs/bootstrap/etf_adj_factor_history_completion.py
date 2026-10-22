"""Frozen, factor-only historical additions. Ordinary writers are not changed."""

import json
import os
import shutil
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import dagster as dg
import sqlalchemy as sa
import yaml
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable as Checks
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster._serdes import deserialize_value

from orchestrator.defs.asset_guards.etf_adj_factor_history import (
    FactorMaterializationEvidence,
    scalar_metadata,
)
from orchestrator.defs.asset_guards.etf_adj_factor_history_completion import (
    CompletionBasicCache,
    audit_completion_file,
    completion_relations,
    load_completion_evidence,
    require_prepared_basic,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    FORMAL_LAKE_ROOT,
    atomic_write_json,
    write_immutable_json,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import audit_etf_daily_raw_relation
from orchestrator.defs.io.etf_daily_silver_writer import FUND_ADJ_SILVER_SPEC as SPEC
from orchestrator.defs.io.etf_daily_silver_writer import audit_etf_daily_silver_relation
from orchestrator.defs.run_contracts.etf_basic import (
    SILVER_ETF_BASIC_CHECKS,
    EtfBasicSilverSnapshotReference,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_FACTOR_COMPLETION_METADATA_KEY,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    EtfFactorCompletionFile,
    EtfFactorCompletionPlan,
    validate_etf_factor_completion_scope,
)

_COMPLETE_DAYS = ("2026-10-19", "2026-10-20", "2026-10-21")
_MAX_BYTES = 16 * 1024 * 1024


def _budget(started: float, check_cancel: Callable[[], bool]) -> None:
    if check_cancel() or perf_counter() - started > 30:
        raise InterruptedError("completion_cancelled_or_thirty_second_budget")


def _fixed_totals(plan):
    EtfFactorCompletionPlan.from_dict(plan.to_dict())
    if (
        sum(item.original_metadata["dagster/row_count"] for item in plan.files) != 42900
        or sum(item.expected_row_count for item in plan.files) != 43601
    ):
        raise ValueError("completion_original_42900_or_complete_43601_changed")


def _progress(path: Path, plan: EtfFactorCompletionPlan) -> dict:
    _reject_links(path)
    value = (
        json.loads(path.read_text())
        if path.is_file()
        else {"plan_hash": plan.plan_hash, "files": {}}
    )
    if value.get("plan_hash") != plan.plan_hash or not isinstance(
        value.get("files"), dict
    ):
        raise ValueError("completion_progress_identity_mismatch")
    if not set(value["files"]).issubset(plan.scope["additions"]):
        raise ValueError("completion_progress_date_out_of_scope")
    return value


def _save_progress(path: Path, value: dict) -> None:
    _reject_links(path)
    value["updated_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    atomic_write_json(path, value)


def _prepared_cache(prepared_basic, connection, lake_root, plan):
    prepared = require_prepared_basic(prepared_basic)
    references = [EtfBasicSilverSnapshotReference.model_validate(plan.basic_reference)]
    references.extend(
        EtfBasicSilverSnapshotReference.model_validate(
            item.original_metadata["goldenshare/basic_reference"]
        )
        for item in plan.files
    )
    return prepared.seed_cache(connection, lake_root, references)


def _reject_links(path: Path) -> Path:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(parent.is_symlink() for parent in (path, *path.parents))
    ):
        raise ValueError("completion_path_symlink_or_invalid")
    return path


def _file_bytes(paths) -> int:
    total = 0
    for path in set(paths):
        if (
            not path.is_absolute()
            or any(parent.is_symlink() for parent in (path, *path.parents))
            or not path.is_file()
        ):
            raise ValueError("completion_file_missing_or_symlink")
        total += path.stat().st_size
    if total > _MAX_BYTES:
        raise ValueError("completion_files_exceed_16_mib")
    return total


def _latest_target(instance, day):
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(SPEC.asset_key), asset_partitions=[day]
        ),
        limit=1,
    ).records
    if len(records) != 1:
        raise ValueError("completion_latest_materialization_missing")
    record = records[0]
    if record.asset_materialization.partition != day:
        raise ValueError("completion_latest_materialization_wrong_date")
    return FactorMaterializationEvidence.from_record(record)


def _original_target_matches(target, item) -> bool:
    return (
        target.storage_id == item.original_storage_id
        and target.run_id == item.original_run_id
        and dict(target.metadata) == dict(item.original_metadata)
    )


def completion_materialization_metadata(plan, item, lake_root) -> dict:
    """New counts describe the new file; old counters remain inside the Plan."""
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata

    return build_materialization_metadata(
        uri=SPEC.target_path_builder(lake_root, item.trade_date),
        row_count=item.expected_row_count,
        observed_columns=("ts_code", "trade_date", "adj_factor", "discount_rate"),
        extra_metadata={
            "written_row_count": item.expected_row_count,
            "content_hash": item.expected_content_hash,
            "basic_reference": item.original_metadata["goldenshare/basic_reference"],
            "basic_raw_snapshot_hash": item.original_metadata[
                "goldenshare/basic_raw_snapshot_hash"
            ],
            "basic_silver_content_hash": item.original_metadata[
                "goldenshare/basic_silver_content_hash"
            ],
            "added_row_count": len(plan.scope["additions"][item.trade_date]),
            ETF_FACTOR_COMPLETION_METADATA_KEY: plan.to_dict(),
        },
    )


def _completed_target_matches(target, plan, item, lake_root) -> bool:
    return dict(target.metadata) == completion_materialization_metadata(
        plan, item, lake_root
    )


class ReadonlyCompletionStorage:
    """Use existing PostgreSQL configuration, without constructing a Dagster instance."""

    def __init__(self, dagster_home: Path) -> None:
        config = yaml.safe_load((dagster_home / "dagster.yaml").read_text())
        url = config["storage"]["postgres"]["postgres_url"]
        if not isinstance(url, str):
            raise TypeError("completion_existing_postgres_url_required")
        self.engine = sa.create_engine(
            url,
            connect_args={
                "connect_timeout": 5,
                "options": "-c default_transaction_read_only=on -c statement_timeout=15000",
            },
        )

    @contextmanager
    def index_connection(self):
        with self.engine.connect() as connection:
            yield connection

    def close(self) -> None:
        self.engine.dispose()


def _record(row: Mapping) -> FactorMaterializationEvidence:
    entry = deserialize_value(row["event"], EventLogEntry)
    mat = entry.dagster_event.event_specific_data.materialization
    return FactorMaterializationEvidence(
        row["id"], entry.run_id, scalar_metadata(mat.metadata)
    )


def read_completion_inputs(
    storage: Any, scope: Mapping, basic_reference: EtfBasicSilverSnapshotReference
) -> tuple[dict, dict, dict, dict]:
    """26 explicit days, three bounded batches; latest means latest, without fallback."""
    validate_etf_factor_completion_scope(scope)
    days = sorted(scope["additions"])
    parents, raws, original_checks = {}, {}, {}
    assets = ('["silver_etf_adj_factor"]', '["raw_tushare_fund_adj"]')
    with storage.index_connection() as connection:
        for start in range(0, len(days), 10):
            batch = days[start : start + 10]
            ids = (
                sa.select(sa.func.max(Events.c.id))
                .where(
                    Events.c.asset_key.in_(assets),
                    Events.c.partition.in_(batch),
                    Events.c.dagster_event_type == "ASSET_MATERIALIZATION",
                )
                .group_by(Events.c.asset_key, Events.c.partition)
            )
            rows = (
                connection.execute(
                    sa.select(
                        Events.c.id,
                        Events.c.event,
                        Events.c.partition,
                        Events.c.asset_key,
                    )
                    .where(Events.c.id.in_(ids))
                    .limit(21)
                )
                .mappings()
                .all()
            )
            if len(rows) != 2 * len(batch):
                raise ValueError("completion_original_date_pair_missing")
            for row in rows:
                (parents if row["asset_key"] == assets[0] else raws)[
                    row["partition"]
                ] = _record(row)
            check_ids = (
                sa.select(sa.func.max(Checks.c.id))
                .where(
                    Checks.c.asset_key == assets[0],
                    Checks.c.partition.in_(batch),
                    Checks.c.check_name.in_(SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS),
                    sa.or_(
                        *(
                            sa.and_(
                                Checks.c.partition == d,
                                Checks.c.run_id == parents[d].run_id,
                                Checks.c.materialization_event_storage_id
                                == parents[d].storage_id,
                            )
                            for d in batch
                        )
                    ),
                )
                .group_by(Checks.c.partition, Checks.c.check_name)
            )
            checks = (
                connection.execute(
                    sa.select(Checks.c.id, Checks.c.partition, Checks.c.check_name)
                    .where(Checks.c.id.in_(check_ids))
                    .limit(61)
                )
                .mappings()
                .all()
            )
            if len(checks) != 6 * len(batch):
                raise ValueError("completion_original_six_checks_missing")
            for row in checks:
                original_checks.setdefault(row["partition"], {})[row["check_name"]] = (
                    row["id"]
                )
        basic_row = (
            connection.execute(
                sa.select(Events.c.id, Events.c.event)
                .where(
                    Events.c.asset_key == '["silver_etf_basic"]',
                    Events.c.dagster_event_type == "ASSET_MATERIALIZATION",
                )
                .order_by(Events.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )
        basic = _record(basic_row)
        md = basic.metadata
        if (
            md.get("dagster/uri") != basic_reference.silver_uri
            or md.get("goldenshare/raw_snapshot_hash")
            != basic_reference.raw_snapshot_hash
            or md.get("goldenshare/silver_content_hash")
            != basic_reference.silver_content_hash
            or md.get("goldenshare/observed_at") != basic_reference.silver_observed_at
        ):
            raise ValueError("completion_latest_basic_reference_changed")
        latest_basic_check_ids = (
            sa.select(sa.func.max(Checks.c.id))
            .where(
                Checks.c.asset_key == '["silver_etf_basic"]',
                Checks.c.check_name.in_(SILVER_ETF_BASIC_CHECKS),
            )
            .group_by(Checks.c.check_name)
        )
        basic_checks = (
            connection.execute(
                sa.select(Checks)
                .where(Checks.c.id.in_(latest_basic_check_ids))
                .limit(4)
            )
            .mappings()
            .all()
        )
        if len(basic_checks) != 3:
            raise ValueError("completion_latest_basic_checks_missing")
        for row in basic_checks:
            ev = (
                deserialize_value(
                    row["evaluation_event"], EventLogEntry
                ).dagster_event.event_specific_data
                if row["evaluation_event"]
                else None
            )
            if (
                row["execution_status"] != "SUCCEEDED"
                or ev is None
                or not ev.passed
                or ev.target_materialization_data is None
                or ev.target_materialization_data.storage_id != basic.storage_id
            ):
                raise ValueError("completion_latest_basic_not_ready")
    basic_evidence = {
        "storage_id": basic.storage_id,
        "metadata": dict(md),
        "check_ids": {r["check_name"]: r["id"] for r in basic_checks},
    }
    return parents, raws, original_checks, basic_evidence


def build_completion_plan(
    *,
    connection: Any,
    lake_root: Path,
    storage: Any,
    scope: Mapping,
    basic_reference: EtfBasicSilverSnapshotReference,
    basic_cache: CompletionBasicCache,
    check_cancel: Callable[[], bool] = lambda: False,
) -> EtfFactorCompletionPlan:
    started = perf_counter()
    if basic_cache.allow_full_read:
        raise ValueError("completion_maintenance_cache_must_forbid_full_read")
    _budget(started, check_cancel)
    validate_etf_factor_completion_scope(scope)
    parents, raws, checks, basic_evidence = read_completion_inputs(
        storage, scope, basic_reference
    )
    basic_sql = basic_cache.get(basic_reference)
    files = tuple(
        EtfFactorCompletionFile(
            trade_date=d,
            original_storage_id=parents[d].storage_id,
            original_run_id=parents[d].run_id,
            original_metadata=parents[d].metadata,
            original_check_ids=checks[d],
            raw_storage_id=raws[d].storage_id,
            raw_metadata=raws[d].metadata,
            expected_row_count=parents[d].metadata["dagster/row_count"]
            + len(scope["additions"][d]),
            expected_content_hash="0" * 64,
        )
        for d in sorted(scope["additions"])
    )
    if sum(item.original_metadata["dagster/row_count"] for item in files) != 42900:
        raise ValueError("completion_original_42900_changed")
    draft = EtfFactorCompletionPlan(
        scope, basic_reference.model_dump(mode="json"), basic_evidence, files
    ).validate()
    total_bytes = sum(
        Path(f.original_metadata["dagster/uri"]).stat().st_size
        + Path(f.raw_metadata["dagster/uri"]).stat().st_size
        for f in files
    )
    if total_bytes > 16 * 1024 * 1024:
        raise ValueError("completion_inputs_exceed_16_mib")
    outputs = []
    for start in range(0, len(files), 10):
        batch = files[start : start + 10]
        evidence = load_completion_evidence(
            storage=storage, plan=draft, days=[f.trade_date for f in batch]
        )
        for item in batch:
            _budget(started, check_cancel)
            audit = audit_completion_file(
                connection=connection,
                lake_root=lake_root,
                plan=draft,
                trade_date=item.trade_date,
                basic_cache=basic_cache,
                evidence_errors=evidence.errors[item.trade_date],
                expected_complete=False,
            )
            if audit.errors:
                raise ValueError(
                    f"completion_original_not_accepted:{item.trade_date}:{audit.errors}"
                )
            _, _, candidate = completion_relations(
                plan=draft,
                day=item.trade_date,
                lake_root=lake_root,
                basic_sql=basic_sql,
            )
            result = audit_etf_daily_silver_relation(
                connection,
                relation_sql=candidate,
                spec=SPEC,
                partition_key=item.trade_date,
            )
            if result.error_codes or result.row_count != item.expected_row_count:
                raise ValueError("completion_expected_candidate_invalid")
            outputs.append(replace(item, expected_content_hash=result.content_hash))
            _budget(started, check_cancel)
    plan = replace(draft, files=tuple(outputs)).validate()
    EtfFactorCompletionPlan.from_dict(plan.to_dict())
    _budget(started, check_cancel)
    return plan


def completion_directory(staging_root: Path, plan: EtfFactorCompletionPlan) -> Path:
    _reject_links(staging_root)
    if not staging_root.is_dir() or staging_root.is_symlink():
        raise ValueError("completion_staging_root_unavailable")
    return _reject_links(
        staging_root
        / "etf_daily"
        / f"operation_id={plan.plan_hash}"
        / "silver_etf_adj_factor"
    )


def candidate_path(directory: Path, day: str) -> Path:
    return _reject_links(directory / f"trade_date={day}" / "part-000.parquet")


def prepare_completion_candidates(
    *,
    connection: Any,
    lake_root: Path,
    staging_root: Path,
    storage: Any,
    plan: EtfFactorCompletionPlan,
    basic_cache: CompletionBasicCache,
    check_cancel: Callable[[], bool] = lambda: False,
) -> dict:
    """Write staging only. No formal replace, instance creation or event reporting."""
    started = perf_counter()
    _fixed_totals(plan)
    if basic_cache.allow_full_read:
        raise ValueError("completion_maintenance_cache_must_forbid_full_read")
    latest_parents, _, _, _ = read_completion_inputs(
        storage,
        plan.scope,
        EtfBasicSilverSnapshotReference.model_validate(plan.basic_reference),
    )
    if any(
        not _original_target_matches(latest_parents[item.trade_date], item)
        for item in plan.files
    ):
        raise ValueError("completion_original_materialization_changed")
    directory = completion_directory(staging_root, plan)
    _reject_links(directory / "plan.json")
    _reject_links(directory / "candidates.json")
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise ValueError("completion_staging_filesystem_mismatch")
    directory.mkdir(parents=True, exist_ok=True)
    write_immutable_json(directory / "plan.json", plan.to_dict())
    checkpoint_path = directory / "candidates.json"
    checkpoint = _progress(checkpoint_path, plan)
    basic_sql = basic_cache.get(
        EtfBasicSilverSnapshotReference.model_validate(plan.basic_reference)
    )
    input_paths = [
        path
        for item in plan.files
        for path in (
            SPEC.raw_spec.target_path_builder(lake_root, item.trade_date),
            SPEC.target_path_builder(lake_root, item.trade_date),
        )
    ]
    _file_bytes(input_paths)
    for start in range(0, len(plan.files), 10):
        batch = plan.files[start : start + 10]
        evidence = load_completion_evidence(
            storage=storage, plan=plan, days=[f.trade_date for f in batch]
        )
        for item in batch:
            if check_cancel() or perf_counter() - started > 30:
                raise InterruptedError(
                    "completion_candidates_cancelled_or_budget_exceeded"
                )
            before = audit_completion_file(
                connection=connection,
                lake_root=lake_root,
                plan=plan,
                trade_date=item.trade_date,
                basic_cache=basic_cache,
                evidence_errors=evidence.errors[item.trade_date],
                expected_complete=False,
            )
            if before.errors:
                raise ValueError(
                    f"completion_prewrite_failed:{item.trade_date}:{before.errors}"
                )
            path = candidate_path(directory, item.trade_date)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                _, _, sql = completion_relations(
                    plan=plan,
                    day=item.trade_date,
                    lake_root=lake_root,
                    basic_sql=basic_sql,
                )
                connection.execute(
                    f"COPY ({sql}) TO {duckdb_string(path)} (FORMAT PARQUET,COMPRESSION ZSTD)"
                )
            audit = audit_completion_file(
                connection=connection,
                lake_root=lake_root,
                plan=plan,
                trade_date=item.trade_date,
                basic_cache=basic_cache,
                relation_sql=f"SELECT * FROM {read_parquet(path, hive_partitioning=False)}",
                evidence_errors=evidence.errors[item.trade_date],
            )
            if audit.errors:
                raise ValueError(
                    f"completion_candidate_rejected:{item.trade_date}:{audit.errors}"
                )
            _file_bytes(
                [
                    *input_paths,
                    *(
                        candidate_path(directory, entry.trade_date)
                        for entry in plan.files
                        if candidate_path(directory, entry.trade_date).is_file()
                    ),
                ]
            )
            checkpoint["files"][item.trade_date] = {
                "path": str(path),
                "rows": audit.relation.row_count,
                "hash": audit.relation.content_hash,
                "added_rows": len(plan.scope["additions"][item.trade_date]),
                "modified_rows": 0,
                "deleted_rows": 0,
            }
            checkpoint["updated_at"] = datetime.now(
                ZoneInfo("Asia/Shanghai")
            ).isoformat()
            atomic_write_json(checkpoint_path, checkpoint)
            print(
                f"候选核对：{item.trade_date}，{len(checkpoint['files'])}/26，新增{len(plan.scope['additions'][item.trade_date])}行",
                flush=True,
            )
            if check_cancel():
                raise InterruptedError("completion_candidates_cancelled")
            _budget(started, check_cancel)
    return checkpoint


def _latest_records(storage, asset_key: str, days) -> dict:
    """One bounded query, selecting the latest event separately for every day."""
    if len(days) > 10 or len(set(days)) != len(days):
        raise ValueError("completion_latest_query_date_limit")
    latest_ids = (
        sa.select(sa.func.max(Events.c.id))
        .where(
            Events.c.asset_key == dg.AssetKey(asset_key).to_string(),
            Events.c.partition.in_(days),
            Events.c.dagster_event_type == "ASSET_MATERIALIZATION",
        )
        .group_by(Events.c.partition)
    )
    with storage.index_connection() as connection:
        rows = (
            connection.execute(
                sa.select(Events.c.id, Events.c.event, Events.c.partition)
                .where(Events.c.id.in_(latest_ids))
                .limit(len(days) + 1)
            )
            .mappings()
            .all()
        )
    result = {row["partition"]: _record(row) for row in rows}
    if len(rows) != len(days) or set(result) != set(days):
        raise ValueError("completion_latest_date_records_missing_or_duplicate")
    return result


def audit_completion_candidates(
    *,
    connection,
    lake_root: Path,
    staging_root: Path,
    storage,
    plan: EtfFactorCompletionPlan,
    prepared_basic,
    check_cancel=lambda: False,
) -> dict:
    """Audit all staging candidates; never replace a formal file or report events."""
    started = perf_counter()
    _fixed_totals(plan)
    cache = _prepared_cache(prepared_basic, connection, lake_root, plan)
    directory = completion_directory(staging_root, plan)
    _reject_links(directory / "candidate-audit.json")
    if json.loads(_reject_links(directory / "plan.json").read_text()) != plan.to_dict():
        raise ValueError("completion_frozen_plan_mismatch")
    paths = [
        path
        for item in plan.files
        for path in (
            SPEC.raw_spec.target_path_builder(lake_root, item.trade_date),
            SPEC.target_path_builder(lake_root, item.trade_date),
            candidate_path(directory, item.trade_date),
        )
    ]
    total_bytes = _file_bytes(paths)
    files = {}
    for start in range(0, len(plan.files), 10):
        batch = plan.files[start : start + 10]
        days = [item.trade_date for item in batch]
        latest = _latest_records(storage, SPEC.asset_key, days)
        evidence = load_completion_evidence(storage=storage, plan=plan, days=days)
        for item in batch:
            _budget(started, check_cancel)
            if not _original_target_matches(latest[item.trade_date], item):
                raise ValueError("completion_original_materialization_changed")
            audit = audit_completion_file(
                connection=connection,
                lake_root=lake_root,
                plan=plan,
                trade_date=item.trade_date,
                basic_cache=cache,
                evidence_errors=evidence.errors[item.trade_date],
                relation_sql=f"SELECT * FROM {read_parquet(candidate_path(directory, item.trade_date), hive_partitioning=False)}",
            )
            if audit.errors:
                raise ValueError(
                    f"completion_candidate_audit_failed:{item.trade_date}:{audit.errors}"
                )
            files[item.trade_date] = {
                "content_hash": item.expected_content_hash,
                "rows": item.expected_row_count,
                "added_rows": len(plan.scope["additions"][item.trade_date]),
                "modified_rows": 0,
                "deleted_rows": 0,
            }
    _budget(started, check_cancel)
    report = {
        "plan_hash": plan.plan_hash,
        "files": files,
        "added_rows": 701,
        "modified_rows": 0,
        "deleted_rows": 0,
        "input_bytes": total_bytes,
    }
    atomic_write_json(directory / "candidate-audit.json", report)
    _budget(started, check_cancel)
    return report


def _require_candidate_report(directory, plan):
    report = json.loads(_reject_links(directory / "candidate-audit.json").read_text())
    expected = {
        item.trade_date: {
            "content_hash": item.expected_content_hash,
            "rows": item.expected_row_count,
            "added_rows": len(plan.scope["additions"][item.trade_date]),
            "modified_rows": 0,
            "deleted_rows": 0,
        }
        for item in plan.files
    }
    if (
        report.get("plan_hash") != plan.plan_hash
        or report.get("files") != expected
        or report.get("added_rows") != 701
        or report.get("modified_rows") != 0
        or report.get("deleted_rows") != 0
    ):
        raise ValueError("completion_candidate_report_mismatch")


def _no_inflight(instance, day, *, own_run_id=None):
    runs = instance.get_runs(
        filters=dg.RunsFilter(
            job_name=SILVER_ETF_ADJ_FACTOR_JOB_NAME,
            tags={"dagster/partition": day},
            statuses=[
                dg.DagsterRunStatus.QUEUED,
                dg.DagsterRunStatus.NOT_STARTED,
                dg.DagsterRunStatus.STARTING,
                dg.DagsterRunStatus.STARTED,
                dg.DagsterRunStatus.CANCELING,
            ],
        ),
        limit=2,
    )
    if any(run.run_id != own_run_id for run in runs):
        raise ValueError("completion_same_date_run_inflight")


def promote_completion_candidates(
    *,
    connection,
    lake_root: Path,
    staging_root: Path,
    storage,
    instance,
    plan: EtfFactorCompletionPlan,
    prepared_basic,
    approved: bool = False,
    check_cancel=lambda: False,
) -> dict:
    """Only this phase calls os.replace; already promoted dates are read back."""
    started = perf_counter()
    _fixed_totals(plan)
    cache = _prepared_cache(prepared_basic, connection, lake_root, plan)
    if not approved:
        raise ValueError("completion_file_promotion_not_approved")
    directory = completion_directory(staging_root, plan)
    _require_candidate_report(directory, plan)
    for root in (lake_root, staging_root):
        if not root.is_dir() or root.is_symlink():
            raise ValueError("completion_root_unavailable")
    if lake_root == FORMAL_LAKE_ROOT and not lake_root.parent.is_mount():
        raise ValueError("completion_formal_volume_not_mounted")
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise ValueError("completion_staging_filesystem_mismatch")
    candidates = [candidate_path(directory, item.trade_date) for item in plan.files]
    remaining = [path for path in candidates if path.is_file()]
    input_paths = [
        path
        for item in plan.files
        for path in (
            SPEC.raw_spec.target_path_builder(lake_root, item.trade_date),
            SPEC.target_path_builder(lake_root, item.trade_date),
        )
    ]
    _file_bytes([*input_paths, *remaining])
    if shutil.disk_usage(staging_root).free < 2.5 * sum(
        p.stat().st_size for p in remaining
    ):
        raise ValueError("completion_insufficient_free_space")
    progress_path = directory / "files.json"
    progress = _progress(progress_path, plan)
    for start in range(0, len(plan.files), 10):
        batch = plan.files[start : start + 10]
        days = [item.trade_date for item in batch]
        latest = _latest_records(storage, SPEC.asset_key, days)
        evidence = load_completion_evidence(
            storage=storage, plan=plan, days=days, current_targets=latest
        )
        for item in batch:
            _budget(started, check_cancel)
            _no_inflight(instance, item.trade_date)
            target = SPEC.target_path_builder(lake_root, item.trade_date)
            if target.is_symlink() or not os.access(target.parent, os.W_OK):
                raise ValueError("completion_target_not_writable")
            actual = audit_etf_daily_silver_relation(
                connection,
                relation_sql=read_parquet(target, hive_partitioning=False),
                spec=SPEC,
                partition_key=item.trade_date,
            )
            already = (
                not actual.error_codes
                and actual.row_count == item.expected_row_count
                and actual.content_hash == item.expected_content_hash
            )
            if not (
                _original_target_matches(latest[item.trade_date], item)
                or (
                    already
                    and _completed_target_matches(
                        latest[item.trade_date], plan, item, lake_root
                    )
                )
            ):
                raise ValueError("completion_target_materialization_conflict")
            if not already:
                if (
                    actual.error_codes
                    or actual.row_count != item.original_metadata["dagster/row_count"]
                    or actual.content_hash
                    != item.original_metadata["goldenshare/content_hash"]
                ):
                    raise ValueError("completion_target_has_third_content")
                candidate = candidate_path(directory, item.trade_date)
                _file_bytes([candidate])
                audit = audit_completion_file(
                    connection=connection,
                    lake_root=lake_root,
                    plan=plan,
                    trade_date=item.trade_date,
                    basic_cache=cache,
                    evidence_errors=evidence.errors[item.trade_date],
                    relation_sql=f"SELECT * FROM {read_parquet(candidate, hive_partitioning=False)}",
                )
                if audit.errors:
                    raise ValueError(
                        f"completion_promotion_candidate_failed:{audit.errors}"
                    )
                _budget(started, check_cancel)
                os.replace(candidate, target)
            audit = audit_completion_file(
                connection=connection,
                lake_root=lake_root,
                plan=plan,
                trade_date=item.trade_date,
                basic_cache=cache,
                evidence_errors=evidence.errors[item.trade_date],
            )
            if audit.errors:
                raise ValueError(f"completion_promoted_file_failed:{audit.errors}")
            progress["files"][item.trade_date] = {
                "content_hash": item.expected_content_hash,
                "rows": item.expected_row_count,
                "promoted": True,
            }
            _save_progress(progress_path, progress)
            print(
                f"文件提升：{item.trade_date}，{len(progress['files'])}/26", flush=True
            )
            _budget(started, check_cancel)
    return progress


def ensure_completion_materialization(
    *,
    instance,
    plan,
    item,
    lake_root,
    progress_path: Path,
    progress: dict,
) -> FactorMaterializationEvidence:
    """At most two latest-one queries; save the real target before any run UUID."""
    latest = _latest_target(instance, item.trade_date)
    saved = progress["files"].setdefault(item.trade_date, {})
    if _completed_target_matches(latest, plan, item, lake_root):
        if saved.get("target") not in (None, latest.storage_id):
            raise ValueError("completion_saved_target_conflict")
    elif _original_target_matches(latest, item):
        if saved.get("target") is not None or saved.get("run_id") is not None:
            raise ValueError("completion_saved_target_disappeared")
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=SPEC.asset_key,
                partition=item.trade_date,
                metadata=completion_materialization_metadata(plan, item, lake_root),
            )
        )
        latest = _latest_target(instance, item.trade_date)
        if not _completed_target_matches(latest, plan, item, lake_root):
            raise ValueError("completion_new_target_readback_mismatch")
    else:
        raise ValueError("completion_latest_target_conflict")
    saved["target"] = latest.storage_id
    saved["content_hash"] = item.expected_content_hash
    _save_progress(progress_path, progress)
    return latest


def _validate_check_run(instance, run_id, day, target, plan):
    run = instance.get_run_by_id(run_id)
    if (
        run is None
        or run.job_name != SILVER_ETF_ADJ_FACTOR_JOB_NAME
        or run.tags.get("dagster/partition") != day
        or run.tags.get(ETF_FACTOR_COMPLETION_METADATA_KEY) != plan.plan_hash
    ):
        raise ValueError("completion_check_run_identity_mismatch")
    if run.status != dg.DagsterRunStatus.SUCCESS:
        raise ValueError(f"completion_check_run_not_success:{run.status.value}")
    from dagster._core.events import DagsterEventType

    connection = instance.get_records_for_run(
        run_id,
        of_type=DagsterEventType.ASSET_CHECK_EVALUATION,
        limit=7,
    )
    if connection.has_more or len(connection.records) != 6:
        raise ValueError("completion_check_six_results_missing_or_extra")
    names = set()
    for record in connection.records:
        entry = record.event_log_entry
        evaluation = entry.asset_check_evaluation
        if (
            evaluation is None
            or entry.run_id != run_id
            or evaluation.asset_key != dg.AssetKey(SPEC.asset_key)
            or evaluation.partition != day
            or not evaluation.passed
            or not evaluation.blocking
            or evaluation.severity != dg.AssetCheckSeverity.ERROR
            or evaluation.target_materialization_data is None
            or evaluation.target_materialization_data.storage_id != target.storage_id
            or evaluation.check_name in names
        ):
            raise ValueError("completion_check_result_failed_or_wrong_target")
        names.add(evaluation.check_name)
    if names != set(SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS):
        raise ValueError("completion_check_result_names_changed")
    return run


def _validate_latest_checks(instance, day, target):
    """A previous green run cannot hide a later failed or unfinished check."""
    latest_ids = (
        sa.select(sa.func.max(Checks.c.id))
        .where(
            Checks.c.asset_key == dg.AssetKey(SPEC.asset_key).to_string(),
            Checks.c.partition == day,
            Checks.c.check_name.in_(SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS),
        )
        .group_by(Checks.c.check_name)
    )
    with instance.event_log_storage.index_connection() as connection:
        rows = (
            connection.execute(
                sa.select(Checks).where(Checks.c.id.in_(latest_ids)).limit(7)
            )
            .mappings()
            .all()
        )
    if len(rows) != 6 or {row["check_name"] for row in rows} != set(
        SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS
    ):
        raise ValueError("completion_latest_six_checks_missing_or_extra")
    for row in rows:
        event = (
            deserialize_value(row["evaluation_event"], EventLogEntry)
            if row["evaluation_event"]
            else None
        )
        evaluation = event.asset_check_evaluation if event else None
        if (
            row["execution_status"] != "SUCCEEDED"
            or evaluation is None
            or not evaluation.passed
            or not evaluation.blocking
            or evaluation.severity != dg.AssetCheckSeverity.ERROR
            or evaluation.asset_key != dg.AssetKey(SPEC.asset_key)
            or evaluation.partition != day
            or evaluation.check_name != row["check_name"]
            or evaluation.target_materialization_data is None
            or evaluation.target_materialization_data.storage_id != target.storage_id
            or row["materialization_event_storage_id"] != target.storage_id
        ):
            raise ValueError("completion_latest_check_failed_or_unfinished")


def execute_completion_checks(
    *,
    instance,
    job,
    plan,
    item,
    target,
    progress_path: Path,
    progress: dict,
    prepared_basic,
    resources: Mapping,
    previous_process_exited: bool = False,
    check_cancel=lambda: False,
) -> None:
    """Persist one UUID, create a real check run once, and never retry failures."""
    prepared = require_prepared_basic(prepared_basic)
    saved = progress["files"][item.trade_date]
    if (
        saved.get("target") != target.storage_id
        or saved.get("content_hash") != item.expected_content_hash
    ):
        raise ValueError("completion_target_not_saved_before_check")
    if job.name != SILVER_ETF_ADJ_FACTOR_JOB_NAME:
        raise ValueError("completion_wrong_check_job")
    check_keys = {
        dg.AssetCheckKey(dg.AssetKey(SPEC.asset_key), name)
        for name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS
    }
    subset = job.get_subset(asset_selection=set(), asset_check_selection=check_keys)
    if subset.asset_selection or set(subset.asset_check_selection or ()) != check_keys:
        raise ValueError("completion_job_is_not_checks_only")
    _no_inflight(instance, item.trade_date, own_run_id=saved.get("run_id"))
    run_id = saved.get("run_id")
    if run_id is None:
        if check_cancel():
            raise InterruptedError("completion_checks_cancelled")
        run_id = str(uuid4())
        saved["run_id"] = run_id
        _save_progress(progress_path, progress)
        if instance.get_run_by_id(run_id) is not None:
            raise ValueError("completion_new_uuid_already_used")
        create = True
    else:
        existing = instance.get_run_by_id(run_id)
        if existing is not None:
            _validate_check_run(instance, run_id, item.trade_date, target, plan)
            create = False
        elif previous_process_exited:
            create = True
        else:
            raise ValueError(
                "completion_saved_run_missing_confirm_previous_process_exit"
            )
    if create:
        if check_cancel():
            raise InterruptedError("completion_checks_cancelled_after_uuid")
        from dagster._core.errors import DagsterRunAlreadyExists

        try:
            subset.execute_in_process(
                instance=instance,
                partition_key=item.trade_date,
                run_id=run_id,
                resources={
                    **resources,
                    "prepared_basic": dg.ResourceDefinition.hardcoded_resource(
                        prepared
                    ),
                },
                tags={**job.tags, ETF_FACTOR_COMPLETION_METADATA_KEY: plan.plan_hash},
                raise_on_error=False,
            )
        except DagsterRunAlreadyExists:
            # A concurrent/unclear attempt is only inspected under this same UUID.
            _validate_check_run(instance, run_id, item.trade_date, target, plan)
        _validate_check_run(instance, run_id, item.trade_date, target, plan)
    _validate_latest_checks(instance, item.trade_date, target)
    saved["checks_passed"] = True
    _save_progress(progress_path, progress)


def report_completion_events(
    *,
    connection,
    lake_root: Path,
    staging_root: Path,
    instance,
    job,
    plan: EtfFactorCompletionPlan,
    prepared_basic,
    resources: Mapping,
    approved: bool = False,
    previous_process_exited: bool = False,
    check_cancel=lambda: False,
) -> dict:
    """Append one materialization then run real checks for each approved date."""
    started = perf_counter()
    _fixed_totals(plan)
    cache = _prepared_cache(prepared_basic, connection, lake_root, plan)
    if not approved:
        raise ValueError("completion_events_not_approved")
    directory = completion_directory(staging_root, plan)
    files = _progress(directory / "files.json", plan)
    if set(files["files"]) != set(plan.scope["additions"]) or any(
        value
        != {
            "content_hash": item.expected_content_hash,
            "rows": item.expected_row_count,
            "promoted": True,
        }
        for item in plan.files
        for value in [files["files"][item.trade_date]]
    ):
        raise ValueError("completion_all_files_must_be_promoted")
    _file_bytes(
        [
            path
            for item in plan.files
            for path in (
                SPEC.raw_spec.target_path_builder(lake_root, item.trade_date),
                SPEC.target_path_builder(lake_root, item.trade_date),
            )
        ]
    )
    progress_path = directory / "events.json"
    progress = _progress(progress_path, plan)
    for start in range(0, len(plan.files), 10):
        batch = plan.files[start : start + 10]
        evidence = load_completion_evidence(
            storage=instance.event_log_storage,
            plan=plan,
            days=[item.trade_date for item in batch],
            require_current_checks=False,
        )
        for item in batch:
            _budget(started, check_cancel)
            saved = progress["files"].get(item.trade_date, {})
            _no_inflight(instance, item.trade_date, own_run_id=saved.get("run_id"))
            audit = audit_completion_file(
                connection=connection,
                lake_root=lake_root,
                plan=plan,
                trade_date=item.trade_date,
                basic_cache=cache,
                evidence_errors=evidence.errors[item.trade_date],
            )
            if audit.errors:
                raise ValueError(f"completion_before_events_file_failed:{audit.errors}")
            target = ensure_completion_materialization(
                instance=instance,
                plan=plan,
                item=item,
                lake_root=lake_root,
                progress_path=progress_path,
                progress=progress,
            )
            _budget(started, check_cancel)
            execute_completion_checks(
                instance=instance,
                job=job,
                plan=plan,
                item=item,
                target=target,
                progress_path=progress_path,
                progress=progress,
                prepared_basic=prepared_basic,
                resources=resources,
                previous_process_exited=previous_process_exited,
                check_cancel=check_cancel,
            )
            # Read the file after the run too; a successful run cannot excuse drift.
            actual = audit_etf_daily_silver_relation(
                connection,
                relation_sql=read_parquet(
                    SPEC.target_path_builder(lake_root, item.trade_date),
                    hive_partitioning=False,
                ),
                spec=SPEC,
                partition_key=item.trade_date,
            )
            if (
                actual.error_codes
                or actual.content_hash != item.expected_content_hash
                or actual.row_count != item.expected_row_count
            ):
                raise ValueError("completion_file_changed_during_check")
            print(
                f"新记录和检查：{item.trade_date}，{sum(bool(v.get('checks_passed')) for v in progress['files'].values())}/26",
                flush=True,
            )
            _budget(started, check_cancel)
    return progress


class _CountedConnection:
    def __init__(self, connection, owner):
        self.connection, self.owner = connection, owner

    def execute(self, *args, **kwargs):
        self.owner.query_count += 1
        if self.owner.query_count > 14:
            raise ValueError("completion_final_evidence_query_limit")
        return self.connection.execute(*args, **kwargs)


class _CountedEvidence:
    """Count actual metadata queries, reusing fetched targets for final binding."""

    def __init__(self, instance):
        self.instance, self.query_count, self.latest = instance, 0, {}
        self.event_log_storage = self

    @contextmanager
    def index_connection(self):
        with self.instance.event_log_storage.index_connection() as connection:
            yield _CountedConnection(connection, self)

    def fetch_materializations(self, *args, **kwargs):
        self.query_count += 1
        if self.query_count > 14:
            raise ValueError("completion_final_evidence_query_limit")
        result = self.instance.fetch_materializations(*args, **kwargs)
        for record in result.records:
            day = record.asset_materialization.partition
            if (
                day not in self.latest
                or record.storage_id > self.latest[day].storage_id
            ):
                self.latest[day] = FactorMaterializationEvidence.from_record(record)
        return result


def audit_completion_final(
    *,
    lake_root: Path,
    instance,
    duckdb_resource,
    plan: EtfFactorCompletionPlan,
    prepared_basic,
    check_cancel=lambda: False,
) -> dict:
    """Read-only: 26 complete checks and three already complete dates, no other dates."""
    from orchestrator.defs.asset_guards.etf_daily_lake_readiness import (
        batch_etf_adj_factor_silver_lake_readiness,
    )

    started = perf_counter()
    _fixed_totals(plan)
    require_prepared_basic(prepared_basic)
    days = tuple(item.trade_date for item in plan.files)
    all_days = (*days, *_COMPLETE_DAYS)
    paths = [
        path
        for day in all_days
        for path in (
            SPEC.raw_spec.target_path_builder(lake_root, day),
            SPEC.target_path_builder(lake_root, day),
        )
    ]
    if len(set(paths)) != 58:
        raise ValueError("completion_final_file_scope_mismatch")
    total_bytes = _file_bytes(paths)
    evidence = _CountedEvidence(instance)
    total_rows = 0
    for start in range(0, len(days), 10):
        _budget(started, check_cancel)
        with duckdb_resource.connect() as connection:
            result = batch_etf_adj_factor_silver_lake_readiness(
                instance=evidence,
                connection=connection,
                lake_root=lake_root,
                trade_dates=days[start : start + 10],
                prepared_basic=prepared_basic,
            )
        if len(result.statuses) != len(days[start : start + 10]) or not all(
            status.ready for status in result.statuses
        ):
            raise ValueError("completion_final_readiness_failed")
        for status in result.statuses:
            item = plan.file(status.trade_date)
            if (
                status.content_hash != item.expected_content_hash
                or status.row_count != item.expected_row_count
                or not _completed_target_matches(
                    evidence.latest[status.trade_date], plan, item, lake_root
                )
            ):
                raise ValueError("completion_final_plan_or_target_changed")
            total_rows += status.row_count
        _budget(started, check_cancel)
    raw_targets = _latest_records(evidence, SPEC.raw_spec.asset_key, _COMPLETE_DAYS)
    silver_targets = _latest_records(evidence, SPEC.asset_key, _COMPLETE_DAYS)
    codes = ",".join(
        duckdb_string(code) for code in sorted(plan.scope["listing_dates"])
    )
    complete_rows = 0
    with duckdb_resource.connect() as connection:
        for day in _COMPLETE_DAYS:
            _budget(started, check_cancel)
            relations = {}
            for label, spec, targets in (
                ("raw", SPEC.raw_spec, raw_targets),
                ("silver", SPEC, silver_targets),
            ):
                table = f"completion_final_{label}"
                path = spec.target_path_builder(lake_root, day)
                connection.execute(
                    f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
                )
                relations[label] = f"SELECT * FROM {table}"
                audit = (
                    audit_etf_daily_raw_relation(
                        connection,
                        relation_sql=relations[label],
                        spec=spec,
                        partition_key=day,
                    )
                    if label == "raw"
                    else audit_etf_daily_silver_relation(
                        connection,
                        relation_sql=relations[label],
                        spec=spec,
                        partition_key=day,
                    )
                )
                md = targets[day].metadata
                if (
                    audit.error_codes
                    or md.get("dagster/uri") != str(path)
                    or md.get("dagster/row_count") != audit.row_count
                    or md.get("goldenshare/content_hash") != audit.content_hash
                ):
                    raise ValueError("completion_unchanged_date_fingerprint_mismatch")
            raw = f"SELECT ts_code,strptime(trade_date,'%Y%m%d')::DATE AS trade_date,adj_factor,discount_rate FROM completion_final_raw WHERE ts_code IN ({codes})"
            silver = f"SELECT ts_code,trade_date,adj_factor,discount_rate FROM completion_final_silver WHERE ts_code IN ({codes})"
            for relation in (raw, silver):
                if (
                    connection.execute(
                        f"SELECT count(*) FROM ({relation}) v"
                    ).fetchone()[0]
                    != 56
                ):
                    raise ValueError("completion_unchanged_date_56_codes_missing")
            for left, right in ((raw, silver), (silver, raw)):
                if connection.execute(
                    f"SELECT count(*) FROM (({left}) EXCEPT ALL ({right})) v"
                ).fetchone()[0]:
                    raise ValueError("completion_unchanged_date_source_diff")
            complete_rows += 56
    _budget(started, check_cancel)
    if (
        complete_rows != 168
        or sum(len(codes) for codes in plan.scope["additions"].values()) + complete_rows
        != 869
    ):
        raise ValueError("completion_final_869_count_mismatch")
    return {
        "plan_hash": plan.plan_hash,
        "days": 29,
        "different_files": 58,
        "input_bytes": total_bytes,
        "evidence_queries": evidence.query_count,
        "added_rows": 701,
        "already_complete_rows": 168,
        "scope_rows": 869,
        "written_rows": total_rows,
        "modified_rows": 0,
        "deleted_rows": 0,
        "elapsed_ms": (perf_counter() - started) * 1000,
    }
