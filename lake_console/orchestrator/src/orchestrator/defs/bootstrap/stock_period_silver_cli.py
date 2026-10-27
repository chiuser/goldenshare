"""Build/resume approved period Silver files; register file facts separately."""

import argparse
import json
import time
from pathlib import Path

import dagster as dg

from orchestrator.defs.io.stock_period_raw import atomic_json, file_version
from orchestrator.defs.io.stock_period_silver import (
    read_json,
    run_directory,
    validate_roots,
    writer_lock,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_period_silver import asset_name, check_names
from orchestrator.defs.stock_period_silver import (
    build,
    checkpoint_path,
    load_execution,
    materialization_metadata,
    recovery_evidence,
    validate_record,
)


def report_file(instance, context, item, identity):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    from orchestrator.defs.asset_guards.stock_period_check_evidence import (
        read_latest_completed_checks,
    )
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        require_recoverable_checks,
    )

    if not context.run_id or instance.get_run_by_id(context.run_id) is None:
        raise ValueError("silver_event_real_run_required")
    asset, partition = dg.AssetKey(asset_name(item["freq"])), item["period"]
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]), limit=1
    ).records
    record = records[0] if records else None
    metadata = record.asset_materialization.metadata if record else {}
    try:
        selected = read_latest_completed_checks(
            instance,
            asset_key=asset,
            check_names=check_names(item["freq"]),
            partition_key=partition,
        )
    except ValueError as error:
        raise ValueError("silver_target_checks_not_ready") from error
    require_recoverable_checks(
        {
            "materialization": record,
            "checks": {name: value[0] for name, value in selected.items()},
            "check_event_storage_ids": {
                name: value[1] for name, value in selected.items()
            },
            "bound_materializations": {
                name: value[2] for name, value in selected.items()
            },
        },
        item["freq"],
        item,
    )
    instance.add_dynamic_partitions(
        "cn_a_stock_week_ends" if item["freq"] == "week" else "cn_a_stock_months",
        [partition],
    )
    if (
        getattr(metadata.get("goldenshare/period_file_version"), "value", None)
        != item["version"]
        or getattr(metadata.get("dagster/uri"), "value", None) != item["target"]
        or getattr(metadata.get("dagster/row_count"), "value", None) != item["rows"]
    ):
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=asset,
                partition=partition,
                metadata=materialization_metadata(item, identity),
            )
        )
        record = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]),
            limit=1,
        ).records[0]
    for name in check_names(item["freq"]):
        evidence = selected.get(name)
        evaluation = evidence[0].evaluation if evidence else None
        if (
            evaluation is not None
            and evaluation.asset_key == asset
            and evaluation.check_name == name
            and evaluation.partition == partition
            and evaluation.passed
            and evaluation.blocking
            and evaluation.target_materialization_data is not None
            and evaluation.target_materialization_data.storage_id == record.storage_id
        ):
            continue
        instance.report_dagster_event(
            DagsterEvent(
                event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                job_name=context.job_name,
                step_key=context.get_step_execution_context().step.key,
                event_specific_data=AssetCheckEvaluation(
                    asset_key=asset,
                    check_name=name,
                    partition=partition,
                    passed=True,
                    blocking=True,
                    metadata={"goldenshare/reused_file_validation": True},
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=record.storage_id,
                        run_id=record.event_log_entry.run_id,
                        timestamp=record.event_log_entry.timestamp,
                    ),
                ),
            ),
            run_id=context.run_id,
        )
    return record.storage_id


def replay_events(lake, staging, run_id, instance, context):
    lake, staging = validate_roots(lake, staging)
    execution = load_execution(lake, staging, run_id)
    if execution["identity"].get("intent") == "update":
        return report_update_events(lake, staging, run_id, instance, context)
    with writer_lock(staging), recovery_evidence():
        execution = load_execution(lake, staging, run_id)
        identity, work = execution["identity"], run_directory(staging, run_id)
        # Files must have completed their aggregate acceptance before any events.
        complete = read_json(work / "complete.json")
        if complete["run_id"] != run_id:
            raise ValueError("silver_files_not_complete")
        for key, path in identity["references"].items():
            if file_version(path) != identity["reference_versions"][key]:
                raise ValueError("silver_event_reference_changed")
        done = []
        began, last_emit = time.monotonic(), 0.0
        for unit in identity["units"]:
            item = read_json(checkpoint_path(work, unit))
            validate_record(
                item, identity, unit, identity_hash=execution["identity_hash"]
            )
            if (
                item["state"] != "committed"
                or file_version(item["target"]) != item["version"]
                or file_version(item["source"]) != item["source_version"]
            ):
                raise ValueError("silver_event_file_changed")
            cp = work / "events" / unit["freq"] / (unit["period"] + ".json")
            if cp.exists():
                receipt = read_json(cp)
                if (
                    receipt["version"] != item["version"]
                    or receipt["identity_hash"] != execution["identity_hash"]
                ):
                    raise ValueError("silver_event_checkpoint_invalid")
            else:
                materialization_id = report_file(instance, context, item, identity)
                atomic_json(
                    cp,
                    {
                        "version": item["version"],
                        "identity_hash": execution["identity_hash"],
                        "materialization_id": materialization_id,
                        "checks": list(check_names(item["freq"])),
                        "event_run_id": context.run_id,
                    },
                )
            done.append(unit)
            now = time.monotonic()
            if now - last_emit >= 5 or len(done) == len(identity["units"]):
                context.log.info(
                    f"Silver events: {len(done)}/{len(identity['units'])} {unit['freq']} {unit['period']}"
                )
                last_emit = now
        result = {
            "run_id": run_id,
            "files": len(done),
            "elapsed_seconds": time.monotonic() - began,
            "materializations": len(done),
            "checks": len(done) * 3,
            "event_run_id": context.run_id,
        }
        atomic_json(work / "events_complete.json", result)
        return result


def report_update_events(
    lake, staging, run_id, instance, context, *, anchor=None, cancel=lambda: False
):
    """Batch event reads. Native anchor is acknowledged only after its real checks exist."""
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        batch_event_evidence,
        require_checks,
        require_recoverable_checks,
    )
    from orchestrator.defs.stock_period_silver import check_cancel

    lake, staging = validate_roots(lake, staging)
    with writer_lock(staging), recovery_evidence():
        execution = load_execution(lake, staging, run_id)
        identity, work = execution["identity"], run_directory(staging, run_id)
        if identity.get("intent") != "update":
            raise ValueError("silver_update_files_incomplete")
        completed = work / "events_complete.json"
        if completed.exists() and read_json(completed).get("covered_by_execution_id"):
            covered = read_json(completed)
            child = load_execution(lake, staging, covered["covered_by_execution_id"])
            if (
                child["identity_hash"] != covered["covered_by_identity_hash"]
                or not (
                    run_directory(staging, covered["covered_by_execution_id"])
                    / "events_complete.json"
                ).exists()
            ):
                raise ValueError("silver_event_coverage_invalid")
            return covered
        for key, path in identity["references"].items():
            if file_version(path) != identity["reference_versions"][key]:
                raise ValueError("silver_event_reference_changed")
        units = identity["units"]
        freq = units[0]["freq"]
        records, pending = [], []
        for unit in units:
            check_cancel(cancel)
            path = checkpoint_path(work, unit)
            if not path.exists():
                pending.append(unit["period"])
                continue
            item = read_json(path)
            validate_record(
                item, identity, unit, identity_hash=execution["identity_hash"]
            )
            if item["state"] != "committed":
                pending.append(unit["period"])
                continue
            if file_version(item["target"]) != item["version"]:
                raise ValueError("silver_event_file_changed")
            if file_version(item["source"]) != item["source_version"]:
                pending.append(unit["period"])
                continue
            if unit["period"] != anchor:
                receipt_path = work / "events" / freq / (item["period"] + ".json")
                if receipt_path.exists():
                    receipt = read_json(receipt_path)
                    if "coverage" in receipt and "version" not in receipt:
                        validate_event_coverage(
                            lake, staging, run_id, item, receipt["coverage"]
                        )
                    elif (
                        receipt.get("version") != item["version"]
                        or receipt.get("identity_hash") != execution["identity_hash"]
                        or receipt.get("checks") != list(check_names(freq))
                    ):
                        raise ValueError("silver_event_checkpoint_invalid")
                records.append(item)
        if not context.run_id or instance.get_run_by_id(context.run_id) is None:
            raise ValueError("silver_event_real_run_required")
        periods = [r["period"] for r in records]
        evidence = batch_event_evidence(instance, freq, periods)
        asset = dg.AssetKey(asset_name(freq))
        # Refuse real failures/misbindings before emitting a new materialization.
        for item in records:
            from orchestrator.defs.stock_period_checks import (
                verify_period_materialization,
            )

            upstream = require_checks(
                evidence.get(
                    (f"raw_tushare_stk_period_bar_adj_{freq}", item["period"])
                ),
                freq,
                raw=True,
            )
            verify_period_materialization(upstream, item["period"], item["source"])
            require_recoverable_checks(
                evidence.get((asset_name(freq), item["period"])), freq, item
            )
        wrote = False
        for item in records:
            check_cancel(cancel)
            old = evidence.get((asset_name(freq), item["period"]))
            materialization = old["materialization"] if old else None
            metadata = (
                materialization.asset_materialization.metadata
                if materialization
                else {}
            )
            if (
                getattr(metadata.get("goldenshare/period_file_version"), "value", None)
                != item["version"]
            ):
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(
                        asset_key=asset,
                        partition=item["period"],
                        metadata=materialization_metadata(item, identity),
                    )
                )
                wrote = True
        if wrote:
            evidence = batch_event_evidence(instance, freq, periods)
        began, last_emit = time.monotonic(), 0.0
        for number, item in enumerate(records, 1):
            check_cancel(cancel)
            if (
                file_version(item["target"]) != item["version"]
                or file_version(item["source"]) != item["source_version"]
            ):
                raise ValueError("silver_event_file_changed")
            current = evidence[(asset_name(freq), item["period"])]
            materialization = current["materialization"]
            metadata = materialization.asset_materialization.metadata
            if (
                metadata["goldenshare/period_file_version"].value != item["version"]
                or metadata["dagster/uri"].value != item["target"]
                or metadata["dagster/row_count"].value != item["rows"]
            ):
                raise ValueError("silver_event_materialization_mismatch")
            for name in check_names(freq):
                record = current["checks"].get(name)
                evaluation = record.evaluation if record else None
                bound = (
                    evaluation is not None
                    and evaluation.target_materialization_data is not None
                    and evaluation.target_materialization_data.storage_id
                    == materialization.storage_id
                )
                if bound:
                    if (
                        not evaluation.passed
                        or not evaluation.blocking
                        or evaluation.asset_key != asset
                        or evaluation.partition != item["period"]
                        or evaluation.check_name != name
                    ):
                        raise ValueError("silver_event_existing_check_failed")
                    continue
                instance.report_dagster_event(
                    DagsterEvent(
                        event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                        job_name=context.job_name,
                        step_key=context.get_step_execution_context().step.key,
                        event_specific_data=AssetCheckEvaluation(
                            asset_key=asset,
                            check_name=name,
                            partition=item["period"],
                            passed=True,
                            blocking=True,
                            metadata={"goldenshare/reused_file_validation": True},
                            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                                storage_id=materialization.storage_id,
                                run_id=materialization.event_log_entry.run_id,
                                timestamp=materialization.event_log_entry.timestamp,
                            ),
                        ),
                    ),
                    run_id=context.run_id,
                )
            if (
                file_version(item["target"]) != item["version"]
                or file_version(item["source"]) != item["source_version"]
                or any(
                    file_version(p) != identity["reference_versions"][k]
                    for k, p in identity["references"].items()
                )
            ):
                raise ValueError("silver_event_file_changed")
            atomic_json(
                work / "events" / freq / (item["period"] + ".json"),
                {
                    "version": item["version"],
                    "identity_hash": execution["identity_hash"],
                    "materialization_id": materialization.storage_id,
                    "checks": list(check_names(freq)),
                    "event_run_id": context.run_id,
                },
            )
            now = time.monotonic()
            if now - last_emit >= 5 or number == len(records):
                context.log.info(
                    f"Silver update events: {number}/{len(records)} {freq} {item['period']}"
                )
                last_emit = now
        result = {
            "run_id": run_id,
            "files": len(records),
            "materializations": len(records),
            "checks": len(records) * 3,
            "event_run_id": context.run_id,
            "elapsed_seconds": time.monotonic() - began,
            "identity_hash": execution["identity_hash"],
            "status": "complete" if not pending and anchor is None else "partial",
            "pending_files": pending,
            "pending_events": [anchor] if anchor is not None else [],
        }
        if anchor is None and not pending:
            atomic_json(work / "events_complete.json", result)
            record_update_coverage(lake, staging, execution, result, cancel=cancel)
        return result


def validate_event_coverage(lake, staging, parent_id, item, coverage):
    """A partially saved ancestor acknowledgement is evidence, not a corrupt own receipt."""
    child = load_execution(lake, staging, coverage["execution_id"])
    if (
        child["identity_hash"] != coverage["identity_hash"]
        or coverage["version"] != item["version"]
    ):
        raise ValueError("silver_event_coverage_invalid")
    current = child
    while current["identity"]["run_id"] != parent_id:
        previous = current["identity"].get("resume_from_execution_id")
        if previous is None:
            raise ValueError("silver_event_coverage_invalid")
        current = load_execution(lake, staging, previous)
    actual = read_json(
        run_directory(staging, coverage["execution_id"])
        / "events"
        / item["freq"]
        / (item["period"] + ".json")
    )
    if any(
        coverage.get(k) != actual.get(k)
        for k in (
            "version",
            "identity_hash",
            "materialization_id",
            "checks",
            "event_run_id",
        )
    ):
        raise ValueError("silver_event_coverage_invalid")


def record_update_coverage(lake, staging, execution, result, *, cancel=lambda: False):
    """Close explicit ancestors only after every period has real bound events."""
    from orchestrator.defs.stock_period_silver import check_cancel

    completed = execution
    receipts = {
        u["period"]: read_json(
            run_directory(staging, execution["identity"]["run_id"])
            / "events"
            / u["freq"]
            / (u["period"] + ".json")
        )
        for u in execution["identity"]["units"]
    }
    while completed["identity"].get("resume_from_execution_id"):
        check_cancel(cancel)
        parent_id = completed["identity"]["resume_from_execution_id"]
        parent = load_execution(lake, staging, parent_id)
        work = run_directory(staging, parent_id)
        for unit in parent["identity"]["units"]:
            check_cancel(cancel)
            path = work / "events" / unit["freq"] / (unit["period"] + ".json")
            previous = read_json(path) if path.exists() else {}
            atomic_json(
                path,
                {
                    **previous,
                    "coverage": {
                        "execution_id": execution["identity"]["run_id"],
                        "identity_hash": execution["identity_hash"],
                        **receipts[unit["period"]],
                    },
                },
            )
        atomic_json(
            work / "events_complete.json",
            {
                **result,
                "run_id": parent_id,
                "identity_hash": parent["identity_hash"],
                "covered_by_execution_id": execution["identity"]["run_id"],
                "covered_by_identity_hash": execution["identity_hash"],
            },
        )
        completed = parent


def run_reporting(instance, operation):
    @dg.op
    def report(context):
        return operation(context)

    @dg.job(name="silver_stock_period_event_backfill_job")
    def reporting():
        report()

    result = reporting.execute_in_process(instance=instance)
    return result.output_for_node("report")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "resume", "events"), nargs="?")
    parser.add_argument("--run-id")
    parser.add_argument("--audit-report", type=Path)
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument(
        "--staging-root", type=Path, default=Path(DEFAULT_LAKE_STAGING_ROOT)
    )
    args = parser.parse_args(argv)
    if args.action is None:
        parser.print_help()
        return 0
    if not args.run_id or (args.action == "build" and args.audit_report is None):
        parser.error("--run-id is required; build also requires --audit-report")
    if args.action != "build" and args.audit_report is not None:
        parser.error("resume/events use their saved execution, not --audit-report")
    if args.action == "events":
        with dg.DagsterInstance.get() as instance:
            result = run_reporting(
                instance,
                lambda context: replay_events(
                    args.lake_root, args.staging_root, args.run_id, instance, context
                ),
            )
    elif (
        args.action == "resume"
        and load_execution(args.lake_root, args.staging_root, args.run_id)[
            "identity"
        ].get("intent")
        == "update"
    ):
        with dg.DagsterInstance.get() as instance:
            result = build(
                args.lake_root, args.staging_root, args.run_id, instance=instance
            )
    else:
        result = build(
            args.lake_root,
            args.staging_root,
            args.run_id,
            audit_report=args.audit_report,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
