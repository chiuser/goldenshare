"""Verified synthetic bootstrap baselines, using isolated files and native events."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_file,
    daily_file_scope_counts,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
)
from orchestrator.defs.io.moneyflow_daily_raw_writer import (
    build_daily_moneyflow_raw_candidate,
)
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts import moneyflow_automation as automation
from orchestrator.defs.run_contracts.moneyflow_daily import daily_fields


def seed_moneyflow_baseline(
    *,
    instance,
    lake: Path,
    staging: Path,
    dataset: str,
    rows,
    day="2026-09-30",
    metadata=None,
):
    assert "/Volumes" not in str(lake) and "/Volumes" not in str(staging)
    staging = staging.parent / "baseline-staging"
    staging.mkdir(exist_ok=True)
    rows = [dict(row, trade_date=day.replace("-", "")) for row in rows]
    scopes = ("行业", "概念", "地域") if dataset == "moneyflow_ind_dc" else (None,)
    responses = [
        [row for row in rows if scope is None or row["content_type"] == scope]
        for scope in scopes
    ] * 2
    source = SimpleNamespace(
        call=lambda *_: SimpleNamespace(
            columns=daily_fields(dataset), rows=responses.pop(0)
        )
    )
    clock = [0]

    def sleep(seconds):
        clock[0] += seconds

    receipt = build_daily_moneyflow_raw_candidate(
        tushare=source,
        dataset=dataset,
        staging_root=staging,
        operation_id="baseline-" + uuid4().hex,
        trade_date=day,
        clock=lambda: clock[0],
        sleep_fn=sleep,
    )
    candidate = receipt.parent / "raw.parquet"
    target = raw_moneyflow_path(lake, dataset, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    with moneyflow_candidate_connection(staging) as db:
        db.execute(
            "COPY (SELECT * FROM read_parquet($source,hive_partitioning=false)) TO $target (FORMAT PARQUET)",
            {"source": str(candidate), "target": str(target)},
        )
        count = audit_daily_moneyflow_file(db, target, day, dataset=dataset)
        counts = daily_file_scope_counts(db, target, dataset=dataset)
    contract = next(
        v
        for v in vars(automation).values()
        if isinstance(v, automation.MoneyflowAutomationContract)
        and v.dataset == dataset
    )
    instance.add_dynamic_partitions(contract.partition_set, [day])
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=contract.raw_asset,
            partition=day,
            metadata={
                "goldenshare/file_sha256": candidate_file_hash(target),
                "dagster/row_count": count,
                "goldenshare/scope_row_counts": counts,
                **(metadata or {}),
            },
        )
    )
    mat = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(contract.raw_asset), asset_partitions=[day]
        ),
        limit=1,
    ).records[0]
    evaluation = AssetCheckEvaluation(
        asset_key=dg.AssetKey(contract.raw_asset),
        check_name=contract.raw_check,
        passed=True,
        partition=day,
        blocking=True,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=mat.storage_id,
            run_id=mat.event_log_entry.run_id,
            timestamp=mat.timestamp,
        ),
        metadata={"goldenshare/checked_row_count": count},
    )
    instance.report_dagster_event(
        dg.DagsterEvent(
            event_type_value=dg.DagsterEventType.ASSET_CHECK_EVALUATION.value,
            job_name="isolated_baseline_check",
            event_specific_data=evaluation,
        ),
        run_id=str(uuid4()),
    )
    return target
