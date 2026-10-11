"""One closed Prod batch: annual promotion and accurately bound normal run events."""

from __future__ import annotations

import fcntl
import resource
import sys
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.stock_weekly_candidates import validate_root
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    _atomic_json,
    check_capture_path,
    check_weekly_cancel,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import (
    promote_weekly_candidates,
    read_audit,
)
from orchestrator.defs.prod_db.stock_weekly_adj_delivery import (
    PsqlWeeklyAdjDeliveryReader,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    weekly_check_names,
    weekly_column_specs,
)
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    ADJUSTED_DELIVERY_ASSET,
    WeeklyAdjProdDeliveryBudget,
)
from orchestrator.defs.stock_period_checks import verify_period_materialization
from orchestrator.defs.stock_weekly_adj_delivery import (
    ADJUSTED_SOURCE,
    _read_json,
    capture_closed_adjusted_batch,
    prepare_adjusted_delivery_year,
)
from orchestrator.defs.stock_weekly_file_checks import audit_weekly_file

DELIVERY_METADATA_KEY = "goldenshare/weekly_adjusted_delivery"


def _same_delivery(metadata, header):
    value = metadata.get(DELIVERY_METADATA_KEY)
    data = value.value if value is not None else None
    return isinstance(data, dict) and (
        data.get("contract_version"),
        data.get("batch_id"),
        data.get("closure_revision"),
    ) == (header.contract_version, header.batch_id, header.revision)


class _RunEvents:
    """Incremental bounded run scans; no per-partition full-history queries."""

    def __init__(self, instance, header, budget):
        self.instance, self.header, self.budget = instance, header, budget
        self.cursors, self.counts, self.materializations, self.checks = {}, {}, {}, {}

    def refresh(self, run_id):
        cursor = self.cursors.get(run_id)
        while True:
            connection = self.instance.get_records_for_run(
                run_id,
                cursor=cursor,
                of_type={
                    dg.DagsterEventType.ASSET_MATERIALIZATION,
                    dg.DagsterEventType.ASSET_CHECK_EVALUATION,
                },
                limit=500,
                ascending=True,
            )
            self.counts[run_id] = self.counts.get(run_id, 0) + len(connection.records)
            if self.counts[run_id] > self.budget.max_target_files * 4:
                raise WeeklyCaptureError("adjusted_delivery_run_event_budget_exceeded")
            for record in connection.records:
                event = record.event_log_entry.dagster_event
                if event.event_type == dg.DagsterEventType.ASSET_MATERIALIZATION:
                    materialization = record.asset_materialization
                    if materialization.asset_key == dg.AssetKey(
                        ADJUSTED_DELIVERY_ASSET
                    ) and _same_delivery(materialization.metadata, self.header):
                        self.materializations[materialization.partition] = record
                else:
                    evaluation = event.event_specific_data
                    if evaluation.asset_key == dg.AssetKey(ADJUSTED_DELIVERY_ASSET):
                        target = evaluation.target_materialization_data
                        if target is not None:
                            self.checks[(target.storage_id, evaluation.check_name)] = (
                                evaluation
                            )
            cursor = connection.cursor
            self.cursors[run_id] = cursor
            if not connection.has_more:
                return

    def complete(self, record):
        return all(
            (evaluation := self.checks.get((record.storage_id, name))) is not None
            and evaluation.passed
            and evaluation.blocking
            and evaluation.partition == record.partition_key
            and evaluation.target_materialization_data.run_id
            == record.event_log_entry.run_id
            and evaluation.target_materialization_data.timestamp
            == record.event_log_entry.timestamp
            for name in weekly_check_names(ADJUSTED_SOURCE)
        )


def _run_budget(root, budget):
    # Standard-library process peak, bytes on macOS and KiB on Linux.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    if peak_bytes > budget.max_process_rss_bytes:
        raise WeeklyCaptureError("adjusted_delivery_process_rss_budget_exceeded")
    total = 0
    for path in root.rglob("*"):
        check_capture_path(path)
        if path.is_file():
            total += path.stat().st_size
            if total > budget.max_staging_bytes:
                raise WeeklyCaptureError("adjusted_delivery_staging_budget_exceeded")


def _metadata(header, item, *, summary=None):
    data = {
        "contract_version": header.contract_version,
        "batch_id": header.batch_id,
        "closure_revision": header.revision,
        "cutoff_week": header.cutoff_week,
        "input_rows": header.rows_written,
    }
    if summary is not None:
        data.update(summary)
    return build_materialization_metadata(
        uri=item["target"],
        row_count=item["rows"],
        observed_columns=tuple(n for n, _, _ in weekly_column_specs(ADJUSTED_SOURCE)),
        extra_metadata={DELIVERY_METADATA_KEY: dg.MetadataValue.json(data)},
    )


def deliver_closed_adjusted_batch(
    context,
    config,
    *,
    target_root,
    staging_root,
    reader=None,
    budget=None,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """A generator used only by the adjusted asset; bootstrap remains a separate stage."""
    budget = budget or WeeklyAdjProdDeliveryBudget()
    validate_root(staging_root, staging=True)
    validate_root(target_root, staging=False)
    if staging_root.is_relative_to(target_root) or target_root.is_relative_to(
        staging_root
    ):
        raise WeeklyCaptureError("weekly_roots_overlap")
    reader = reader or PsqlWeeklyAdjDeliveryReader(budget=budget)
    header = reader.closed_batch_header(
        config.delivery_batch_id,
        config.closure_revision,
        cancel=cancel,
        progress=progress,
    )
    if (
        header.batch_id != config.delivery_batch_id
        or header.revision != config.closure_revision
        or header.contract_version != config.contract_version
        or header.anchor_partition != context.partition_key
    ):
        raise WeeklyCaptureError("adjusted_delivery_execution_identity_mismatch")
    root = staging_root / "stock_weekly_adj_delivery" / header.intent_id
    check_capture_path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "execution.lock"
    check_capture_path(lock_path)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WeeklyCaptureError("adjusted_delivery_intent_active") from None
        _run_budget(root, budget)
        root, manifest = capture_closed_adjusted_batch(
            reader,
            header,
            staging_root=staging_root,
            budget=budget,
            cancel=cancel,
            progress=progress,
        )
        years = sorted({c["year"] for u in manifest["units"] for c in u["chunks"]})
        audits, total_files, replaced, preserved = [], 0, 0, 0
        # Discover the entire batch before any formal replacement. Each annual
        # assembly uses its own DuckDB connection and only affected files.
        for year in years:
            check_weekly_cancel(cancel)
            _run_budget(root, budget)
            path = prepare_adjusted_delivery_year(
                root,
                manifest,
                target_root=target_root,
                year=year,
                budget=budget,
                cancel=cancel,
                progress=progress,
            )
            audit = read_audit(path)
            total_files += len(audit["files"])
            if total_files > budget.max_target_files:
                raise WeeklyCaptureError("adjusted_delivery_target_budget_exceeded")
            replaced += audit["stats"]["replaced_keys"]
            preserved += audit["stats"]["preserved_keys"]
            audits.append((path, audit))
        _run_budget(root, budget)
        if total_files == 0:
            raise WeeklyCaptureError(
                "adjusted_delivery_empty_batch_has_no_asset_partition"
            )
        checkpoint_path = root / "events.json"
        journal = (
            _read_json(checkpoint_path, budget.max_plan_bytes)
            if checkpoint_path.exists()
            else {
                "version": 1,
                "run_ids": [],
                "partitions": {},
            }
        )
        if (
            set(journal) != {"version", "run_ids", "partitions"}
            or journal["version"] != 1
        ):
            raise WeeklyCaptureError("adjusted_delivery_event_checkpoint_invalid")
        states, run_ids = journal["partitions"], journal["run_ids"]
        if len(states) > budget.max_target_files:
            raise WeeklyCaptureError(
                "adjusted_delivery_event_checkpoint_budget_exceeded"
            )
        if (
            not isinstance(run_ids, list)
            or len(run_ids) > budget.max_target_files
            or len(run_ids) != len(set(run_ids))
        ):
            raise WeeklyCaptureError("adjusted_delivery_event_checkpoint_invalid")
        if context.run.run_id not in run_ids:
            run_ids.append(context.run.run_id)
        # Persist the run identity before yielding any event: a crash after the
        # event is stored but before its per-file checkpoint must still recover.
        _atomic_json(checkpoint_path, journal)
        index = _RunEvents(context.instance, header, budget)
        for run_id in run_ids:
            index.refresh(run_id)
        anchor, historical = None, []
        for path, audit in audits:
            check_weekly_cancel(cancel)
            promote_weekly_candidates(
                path, apply=True, cancel=cancel, progress=progress
            )
            _run_budget(root, budget)
            for item in audit["files"]:
                check_weekly_cancel(cancel)
                week = item["week"]
                if week == header.anchor_partition:
                    anchor = item
                    continue
                historical.append(week)
                record = index.materializations.get(week)
                if record is None:
                    yield dg.AssetMaterialization(
                        asset_key=ADJUSTED_DELIVERY_ASSET,
                        partition=week,
                        description="接收Prod闭合批的历史周线修正。",
                        metadata=_metadata(header, item),
                    )
                    index.refresh(context.run.run_id)
                    record = index.materializations.get(week)
                if record is None:
                    raise WeeklyCaptureError(
                        "adjusted_delivery_materialization_not_stored"
                    )
                states[week] = {
                    "run_id": record.event_log_entry.run_id,
                    "storage_id": record.storage_id,
                    "complete": False,
                }
                _atomic_json(checkpoint_path, journal)
                rows = audit_weekly_file(ADJUSTED_SOURCE, week, target_root)
                verify_period_materialization(
                    record, week, Path(item["target"]), rows=rows
                )
                target = AssetCheckEvaluationTargetMaterializationData(
                    storage_id=record.storage_id,
                    run_id=record.event_log_entry.run_id,
                    timestamp=record.event_log_entry.timestamp,
                )
                for name, scope in zip(
                    weekly_check_names(ADJUSTED_SOURCE),
                    (
                        CheckScope.SCHEMA,
                        CheckScope.PARTITION_ALIGNMENT,
                        CheckScope.RECONCILIATION,
                    ),
                    strict=True,
                ):
                    evaluation = index.checks.get((record.storage_id, name))
                    if (
                        evaluation is None
                        or not evaluation.passed
                        or not evaluation.blocking
                    ):
                        context.log_event(
                            AssetCheckEvaluation(
                                asset_key=dg.AssetKey(ADJUSTED_DELIVERY_ASSET),
                                check_name=name,
                                passed=True,
                                partition=week,
                                blocking=True,
                                target_materialization_data=target,
                                metadata=build_check_metadata(
                                    check_scope=scope,
                                    checked_row_count=rows,
                                    extra_metadata={"goldenshare/reason_code": "ok"},
                                ),
                            )
                        )
                progress(
                    {
                        "stage": "historical_events",
                        "week": week,
                        "completed_files": len(historical),
                        "total_files": total_files,
                    }
                )
        if anchor is None:
            raise WeeklyCaptureError("adjusted_delivery_anchor_missing")
        check_weekly_cancel(cancel)
        # Yield flushes the final buffered historical checks. The generator
        # verifies storage before returning; normal check nodes then audit anchor.
        yield dg.MaterializeResult(
            metadata=_metadata(
                header,
                anchor,
                summary={
                    "files_expected": total_files,
                    "files_verified": total_files,
                    "historical_materializations": len(historical),
                    "historical_checks": len(historical) * 3,
                    "anchor_checks_expected": 3,
                    "replaced_keys": replaced,
                    "preserved_keys": preserved,
                    "complete": True,
                },
            )
        )
        index.refresh(context.run.run_id)
        for week in historical:
            record = index.materializations[week]
            if not index.complete(record):
                raise WeeklyCaptureError(
                    "adjusted_delivery_historical_checks_not_stored"
                )
            states[week]["complete"] = True
        _atomic_json(checkpoint_path, journal)
        _run_budget(root, budget)
        progress(
            {
                "stage": "batch_complete",
                "files": total_files,
                "historical_checks": len(historical) * 3,
            }
        )
