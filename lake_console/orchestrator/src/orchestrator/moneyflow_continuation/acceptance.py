"""Bounded native/physical acceptance of the approved seven-date continuation.

No mutation calls or journal writes. Preserved failures remain visible while
only actual, correctly targeted blocking evaluations prove successful delivery.
"""

from collections import Counter
from pathlib import Path
from time import monotonic

import dagster as dg

from orchestrator.defs.run_contracts.moneyflow import moneyflow_peak_rss_bytes
from orchestrator.moneyflow_continuation.contract import (
    DATASETS,
    POLICY,
    REPO,
    file_hash,
    now,
    read_json,
    require,
    unit_identity,
)
from orchestrator.moneyflow_continuation.execution import (
    decision_summary,
    unit_decisions,
)
from orchestrator.moneyflow_continuation.plan import validate_plan
from orchestrator.moneyflow_continuation.recovery import (
    ACTION,
    RAW_ACTION,
    collection_evidence,
    descriptor,
)
from orchestrator.moneyflow_continuation.submission import Journal

DAYS = (
    "2026-10-08",
    "2026-10-09",
    "2026-10-12",
    "2026-10-13",
    "2026-10-14",
    "2026-10-15",
    "2026-10-16",
)


def acceptance_units(plan):
    validate_plan(plan)
    units = [unit_identity(dataset, day) for dataset in DATASETS for day in DAYS]
    require(
        plan["units"] == plan["root_units"] == units[2:], "acceptance_full_scope", 2
    )
    require(
        plan.get("launch_recovery") is not None
        and plan.get("collection_recovery") is not None,
        "acceptance_recoveries_missing",
        2,
    )
    return units


def native_deliveries(backend, plan, units):
    events, native, failures, planned = {}, {}, [], []
    for dataset in DATASETS:
        chosen = [u for u in units if u["dataset"] == dataset]
        dates = [u["trade_date"] for u in chosen]
        expected = Counter({day: 1 for day in dates})
        for layer in ("raw", "silver"):
            identity = chosen[0][layer]
            key = dg.AssetKey(identity["asset"])
            mats = backend.instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=key, asset_partitions=dates),
                limit=len(dates) + 1,
            ).records
            history = (
                backend.instance.event_log_storage.get_asset_check_execution_history(
                    dg.AssetCheckKey(key, identity["check"]), limit=100
                )
            )
            require(len(history) < 100, "acceptance_check_history_truncated")
            actual = []
            for check in history:
                if check.partition not in dates:
                    continue
                event = check.event.dagster_event if check.event else None
                if (
                    event is not None
                    and event.event_type_value == "ASSET_CHECK_EVALUATION"
                ):
                    actual.append(check)
                else:
                    recovery = descriptor(
                        plan, {"dataset": dataset, "trade_date": check.partition}, layer
                    )
                    require(
                        recovery is not None
                        and check.run_id == recovery["failed_run_id"],
                        "acceptance_unexplained_planned_check",
                    )
                    planned.append(
                        {
                            "dataset": dataset,
                            "trade_date": check.partition,
                            "layer": layer,
                            "id": check.id,
                            "run_id": check.run_id,
                            "status": check.status.value,
                            "actual_evaluation": False,
                        }
                    )
            runs = backend.instance.get_runs(
                dg.RunsFilter(
                    job_name=identity["job"], tags={"dagster/partition": dates}
                ),
                limit=len(dates) + 2,
            )
            accepted = []
            for run in runs:
                recovery = descriptor(
                    plan,
                    {
                        "dataset": dataset,
                        "trade_date": run.tags.get("dagster/partition"),
                    },
                    layer,
                )
                if recovery is not None and run.run_id == recovery["failed_run_id"]:
                    require(run.status.value == "FAILURE", "acceptance_parent_state")
                    failures.append(
                        {
                            "dataset": dataset,
                            "trade_date": recovery["trade_date"],
                            "layer": layer,
                            "run_id": run.run_id,
                            "status": "FAILURE",
                        }
                    )
                else:
                    require(
                        run.status.value == "SUCCESS", "acceptance_unsuccessful_run"
                    )
                    accepted.append(run)
            require(
                Counter(r.tags.get("dagster/partition") for r in accepted) == expected,
                "acceptance_run_cardinality",
            )
            require(
                Counter(m.partition_key for m in mats) == expected,
                "acceptance_materialization_cardinality",
            )
            require(
                Counter(c.partition for c in actual) == expected,
                "acceptance_check_cardinality",
            )
            for mat in mats:
                check = next(c for c in actual if c.partition == mat.partition_key)
                evaluation = check.event.dagster_event.event_specific_data
                target = evaluation.target_materialization_data
                require(
                    check.status.value == "SUCCEEDED"
                    and evaluation.passed
                    and evaluation.blocking
                    and target is not None
                    and target.storage_id == mat.storage_id
                    and target.run_id == mat.event_log_entry.run_id
                    and check.run_id == target.run_id
                    and target.timestamp == mat.timestamp,
                    "acceptance_check_target",
                )
                identity_key = (dataset, mat.partition_key, layer)
                events[identity_key] = {
                    "mat_id": mat.storage_id,
                    "check_id": check.id,
                    "run_id": target.run_id,
                    "timestamp": target.timestamp,
                }
                native[identity_key] = next(
                    r
                    for r in accepted
                    if r.tags.get("dagster/partition") == mat.partition_key
                )
    expected_parents = {
        plan[k]["failed_run_id"] for k in ("launch_recovery", "collection_recovery")
    }
    require(
        {r["run_id"] for r in failures} == expected_parents
        and len(failures) == 2
        and Counter(p["run_id"] for p in planned)
        == Counter({p: 1 for p in expected_parents}),
        "acceptance_preserved_failures",
    )
    return events, native, failures, planned


def accepted_records(backend, plan, units, snapshots, events, native, journal):
    records = []
    for unit, snapshot in zip(units, snapshots, strict=True):
        layers = {}
        for layer in ("raw", "silver"):
            identity = unit[layer]
            event = events[(unit["dataset"], unit["trade_date"], layer)]
            require(
                event["mat_id"] == snapshot[layer]["proof"]["materialization_id"],
                "acceptance_delivery_binding",
            )
            run = native[(unit["dataset"], unit["trade_date"], layer)]
            require(run.run_id == event["run_id"], "acceptance_run_binding")
            receipt_state = "previously_accepted_market_sample"
            if unit in plan["root_units"]:
                recovery = descriptor(plan, unit, layer)
                action = (
                    (ACTION if layer == "silver" else RAW_ACTION) if recovery else layer
                )
                files = journal.read(unit, action)
                require(
                    "send_intent" in files,
                    "acceptance_journal_incomplete",
                )
                original = journal.read(unit, layer) if recovery else files
                backend.validate_run(run, unit, layer, original["request"]["body"])
                if "response" in files:
                    backend.check_response(
                        files["response"]["value"], action, {"run_id": run.run_id}
                    )
                    receipt_state = "http_response"
                else:
                    receipt_state = "native_readback_after_uncertain_response"
                if recovery:
                    require(
                        run.parent_run_id
                        == run.root_run_id
                        == recovery["failed_run_id"]
                        and files["request"]["body"]["variables"]
                        == {"parentRunId": recovery["failed_run_id"]},
                        "acceptance_reexecution_binding",
                    )
            else:
                backend.validate_run(run, unit, layer)
            path = Path(identity["target"])
            sha = file_hash(path)
            require(
                sha == snapshot[layer]["proof"]["sha256"], "acceptance_file_changed"
            )
            layers[layer] = {
                **event,
                "target": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha,
                "rows": snapshot[layer]["proof"]["rows"],
                "columns": len(identity["schema"]),
                "submission_evidence": receipt_state,
            }
        receipt_path = (
            backend.staging
            / "moneyflow"
            / layers["raw"]["run_id"]
            / unit["dataset"]
            / unit["trade_date"]
            / "receipt.json"
        )
        receipt = read_json(receipt_path, POLICY.action_bytes)
        require(
            receipt["row_count"] == layers["raw"]["rows"] == layers["silver"]["rows"],
            "acceptance_source_count",
        )
        records.append(
            {
                "dataset": unit["dataset"],
                "trade_date": unit["trade_date"],
                "layers": layers,
                "source": receipt,
                "source_receipt_sha256": file_hash(receipt_path),
                "normalization_or_write_rejects": 0,
            }
        )
    return records


def verify_completed_baseline(records):
    baseline_path = (
        REPO
        / "lake_console/reports/moneyflow_p4_continuation_recovery_20261017/45-partial-acceptance.json"
    )
    baseline = read_json(baseline_path)
    require(len(baseline["records"]) == 45, "acceptance_baseline_scope")
    current = {(r["dataset"], r["trade_date"]): r for r in records}
    require(len(current) == 49, "acceptance_record_cardinality")
    seen = set()
    for old in baseline["records"]:
        key = (old["dataset"], old["trade_date"])
        require(key not in seen and key in current, "acceptance_baseline_scope")
        seen.add(key)
        row = current[key]
        for layer in ("raw", "silver"):
            require(
                all(
                    row["layers"][layer][k] == old["layers"][layer][k]
                    for k in ("sha256", "run_id", "rows")
                ),
                "acceptance_completed_file_changed",
            )
        require(
            row["source_receipt_sha256"] == old["source_receipt_sha256"],
            "acceptance_completed_receipt_changed",
        )
    return {
        "path": str(baseline_path),
        "sha256": file_hash(baseline_path),
        "preserved_dataset_days": 45,
    }


def audit(backend, plan, *, root=None, at=None):
    units = acceptance_units(plan)
    started = monotonic()
    journal = Journal(plan) if root is None else Journal(plan, root)
    snapshots = backend.snapshots(units, journal)
    decisions = unit_decisions(snapshots)
    report = {
        "mode": "audit",
        "complete": False,
        "as_of": (at or now()).isoformat(),
        "root_scope_digest": plan["root_scope_digest"],
        "units": decisions,
        **decision_summary(decisions),
        "formal_mutations": 0,
    }
    try:
        require(
            all(d["next"] == "complete" for d in decisions),
            "acceptance_incomplete_scope",
        )
        events, native, failures, planned = native_deliveries(backend, plan, units)
        records = accepted_records(
            backend, plan, units, snapshots, events, native, journal
        )
        baseline = verify_completed_baseline(records)
        backend.guard(plan, at or now())
        runtime = backend.last_guard["runtime"]
        require(
            len(runtime["sensors"]) == 21
            and all(s == ["STOPPED", "STOPPED"] for s in runtime["sensors"].values()),
            "acceptance_sensors",
        )
        failed_source = collection_evidence(plan["collection_recovery"])
        known_requests = sum(r["source"]["request_count"] for r in records)
        totals = {
            "dataset_days": len(records),
            "successful_native_runs": len(native),
            "preserved_failures": len(failures),
            "native_runs": len(native) + len(failures),
            "files": len(records) * 2,
            "materializations": len(events),
            "blocking_checks": len(events),
            "planned_only_checks": len(planned),
            "rows_per_layer": sum(r["layers"]["raw"]["rows"] for r in records),
            "known_source_requests": known_requests,
            "source_requests_interval": [
                known_requests + failed_source["successful_page_calls_lower_bound"],
                known_requests + failed_source["request_upper_bound_per_original_run"],
            ],
            "source_retries_known": sum(
                r["source"].get("retry_count", 0) for r in records
            ),
            "file_bytes": sum(
                r["layers"][layer]["bytes"]
                for r in records
                for layer in ("raw", "silver")
            ),
        }
        require(
            totals["successful_native_runs"]
            == totals["files"]
            == totals["materializations"]
            == totals["blocking_checks"]
            == 98
            and totals["native_runs"] == 100
            and totals["planned_only_checks"] == 2,
            "acceptance_totals",
        )
        report.update(
            complete=True,
            records=records,
            totals=totals,
            original_47_totals={
                "dataset_days": 47,
                "successful_native_runs": 94,
                "preserved_failures": 2,
                "native_runs": 96,
            },
            preserved_failures=failures,
            preserved_planned_checks_without_evaluation=planned,
            baseline=baseline,
            runtime=runtime,
            history_rescanned=False,
        )
    except Exception as error:  # noqa: BLE001 -- retain partial unit facts, no formal writes
        report.update(
            reason=getattr(error, "reason", "io_or_native_error"),
            error_type=type(error).__name__,
        )
    report.update(
        reads=backend.meter.count,
        elapsed_seconds=monotonic() - started,
        peak_rss_bytes=moneyflow_peak_rss_bytes(),
    )
    require(
        report["reads"] <= POLICY.plan_reads
        and report["elapsed_seconds"] < POLICY.plan_seconds
        and report["peak_rss_bytes"] <= POLICY.rss_bytes,
        "acceptance_budget",
    )
    return (0 if report["complete"] else 3), report
