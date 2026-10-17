"""Tiny metadata gold cases for 49 deliveries and both retained failures.

Outer storage envelopes are substitutes; actual evaluation/target values use
Dagster's installed producer types. Physical SQL/jobs are exercised separately.
"""

import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.events import DagsterEvent

from orchestrator.moneyflow_continuation import acceptance
from orchestrator.moneyflow_continuation.contract import DATASETS, ContinuationError
from orchestrator.moneyflow_continuation.execution import unit_decisions
from orchestrator.moneyflow_continuation.state import ReadMeter
from tests.test_moneyflow_collection_recovery import DAYS, PARENT, setup
from tests.test_moneyflow_continuation_plan import AT
from tests.test_moneyflow_continuation_state import snapshot

SILVER_PARENT = "656aa7d0-94c5-477e-a72e-452a48618d2c"


def bundle(tmp_path, monkeypatch):
    child_plan, *_ = setup(tmp_path, monkeypatch)
    plan = copy.deepcopy(child_plan)
    plan["units"] = plan["root_units"]
    plan["launch_recovery"] = {
        "dataset": "moneyflow_ths",
        "trade_date": "2026-10-14",
        "layer": "silver",
        "failed_run_id": SILVER_PARENT,
        "raw_sha256": "b" * 64,
        "evidence": {
            "path": str(tmp_path / "silver-evidence.json"),
            "sha256": "a" * 64,
        },
    }
    units = acceptance.acceptance_units(plan)
    mats, checks, runs = {}, {}, {}
    for index, unit in enumerate(units):
        for layer in ("raw", "silver"):
            identity = unit[layer]
            run_id, mat_id = (
                f"success-{index}-{layer}",
                index * 2 + (1 if layer == "raw" else 2),
            )
            mat = NS(
                partition_key=unit["trade_date"],
                storage_id=mat_id,
                timestamp=100.0,
                event_log_entry=NS(run_id=run_id),
            )
            target = AssetCheckEvaluationTargetMaterializationData(
                storage_id=mat_id, run_id=run_id, timestamp=100.0
            )
            evaluation = AssetCheckEvaluation(
                asset_key=dg.AssetKey(identity["asset"]),
                check_name=identity["check"],
                passed=True,
                blocking=True,
                target_materialization_data=target,
            )
            event = DagsterEvent(
                event_type_value="ASSET_CHECK_EVALUATION",
                job_name=identity["job"],
                event_specific_data=evaluation,
            )
            check = NS(
                partition=unit["trade_date"],
                id=mat_id,
                run_id=run_id,
                status=NS(value="SUCCEEDED"),
                event=NS(dagster_event=event),
            )
            run = NS(
                run_id=run_id,
                status=NS(value="SUCCESS"),
                tags={"dagster/partition": unit["trade_date"]},
            )
            mats.setdefault(identity["asset"], []).append(mat)
            checks.setdefault(identity["asset"], []).append(check)
            runs.setdefault(identity["job"], []).append(run)
    for dataset, day, layer, parent in (
        ("moneyflow", "2026-10-13", "raw", PARENT),
        ("moneyflow_ths", "2026-10-14", "silver", SILVER_PARENT),
    ):
        unit = next(
            u for u in units if u["dataset"] == dataset and u["trade_date"] == day
        )
        checks[unit[layer]["asset"]].append(
            NS(
                partition=day,
                id=1000 + len(checks[unit[layer]["asset"]]),
                run_id=parent,
                status=NS(value="FAILED"),
                event=None,
            )
        )
        runs[unit[layer]["job"]].append(
            NS(
                run_id=parent,
                status=NS(value="FAILURE"),
                tags={"dagster/partition": day},
            )
        )
    instance = NS(
        fetch_materializations=lambda filt, limit: NS(
            records=mats[filt.asset_key.path[0]]
        ),
        event_log_storage=NS(
            get_asset_check_execution_history=lambda key, limit: checks[
                key.asset_key.path[0]
            ]
        ),
        get_runs=lambda filt, limit: runs[filt.job_name],
    )
    return plan, units, NS(instance=instance), mats, checks, runs


def test_two_parent_failures_and_planned_only_are_counted_separately(
    tmp_path, monkeypatch
):
    plan, units, backend, *_ = bundle(tmp_path, monkeypatch)
    events, native, failures, planned = acceptance.native_deliveries(
        backend, plan, units
    )
    assert len(units) == 49 and len(events) == len(native) == 98
    assert len(failures) == len(planned) == 2
    assert {r["run_id"] for r in failures} == {PARENT, SILVER_PARENT}
    assert all(not r["actual_evaluation"] for r in planned)


@pytest.mark.parametrize(
    "damage",
    [
        "third_run",
        "wrong_target",
        "wrong_check_run",
        "unexplained_planned",
        "planned_as_actual",
        "missing_success",
        "duplicate_parent",
    ],
)
def test_independent_cardinality_and_target_errors_are_not_hidden(
    tmp_path, monkeypatch, damage
):
    plan, units, backend, _mats, checks, runs = bundle(tmp_path, monkeypatch)
    first = units[0]
    key, job = first["raw"]["asset"], first["raw"]["job"]
    if damage == "wrong_check_run":
        checks[key][0].run_id = "unrelated-evaluator"
    if damage == "third_run":
        runs[job].append(copy.deepcopy(runs[job][0]))
    if damage == "wrong_target":
        check = checks[key][0]
        evaluation = check.event.dagster_event.event_specific_data
        check.event.dagster_event = DagsterEvent(
            event_type_value="ASSET_CHECK_EVALUATION",
            job_name=job,
            event_specific_data=AssetCheckEvaluation(
                asset_key=evaluation.asset_key,
                check_name=evaluation.check_name,
                passed=True,
                blocking=True,
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=999, run_id="wrong", timestamp=100.0
                ),
            ),
        )
    if damage == "unexplained_planned":
        checks[key].append(
            NS(
                partition=DAYS[0],
                id=999,
                run_id="unknown",
                status=NS(value="FAILED"),
                event=None,
            )
        )
    if damage == "planned_as_actual":
        checks[key].append(copy.deepcopy(checks[key][0]))
    if damage == "missing_success":
        runs[job].pop()
    if damage == "duplicate_parent":
        runs["raw_tushare_moneyflow_update_job"].append(
            copy.deepcopy(runs["raw_tushare_moneyflow_update_job"][-1])
        )
    with pytest.raises(ContinuationError):
        acceptance.native_deliveries(backend, plan, units)


def test_complete_report_uses_producer_runtime_dictionary_and_source_interval(
    tmp_path, monkeypatch
):
    plan, units, backend, *_ = bundle(tmp_path, monkeypatch)
    states = []
    for unit in units:
        state = snapshot()
        state.update(
            dataset=unit["dataset"], trade_date=unit["trade_date"], registered=True
        )
        for layer in ("raw", "silver"):
            state[layer].update(ready=True, reason="ready")
        states.append(state)
    # Existing NativeBackend.runtime producer returns a dictionary, not a list.
    report_root = (
        Path(__file__).resolve().parents[2]
        / "reports/moneyflow_p4_continuation_recovery_20261017"
    )
    runtime = json.loads((report_root / "verification.json").read_text())["runtime"]
    backend.snapshots = lambda *_: states
    backend.meter = ReadMeter()
    backend.guard = lambda *_: None
    backend.last_guard = {"runtime": runtime}
    rows = [
        {
            "dataset": u["dataset"],
            "trade_date": u["trade_date"],
            "source": {"request_count": 2},
            "layers": {
                "raw": {"rows": 1, "bytes": 1},
                "silver": {"rows": 1, "bytes": 1},
            },
        }
        for u in units
    ]
    monkeypatch.setattr(acceptance, "accepted_records", lambda *_: rows)
    monkeypatch.setattr(
        acceptance,
        "verify_completed_baseline",
        lambda *_: {"preserved_dataset_days": 45},
    )
    code, report = acceptance.audit(backend, plan, root=tmp_path / "unused", at=AT)
    assert code == 0, report
    assert report["totals"]["native_runs"] == 100
    assert report["totals"]["source_requests_interval"] == [101, 162]
    assert report["totals"]["planned_only_checks"] == 2
    assert report["original_47_totals"]["native_runs"] == 96


def test_unknown_unit_is_not_clean_absence_or_a_write_permission():
    value = snapshot()
    value.update(unknown=True, error="unread_storage")
    result = unit_decisions([value])[0]
    assert result["next"] == "unknown" and result["reason"] == "unread_storage"


def test_full_scope_cannot_be_silently_replaced_by_remaining_four(
    tmp_path, monkeypatch
):
    plan, *_ = bundle(tmp_path, monkeypatch)
    plan["units"] = [
        u
        for u in plan["units"]
        if u["dataset"] == DATASETS[-1] and u["trade_date"] >= "2026-10-13"
    ]
    with pytest.raises(ContinuationError, match="acceptance_full_scope"):
        acceptance.acceptance_units(plan)


def test_original_47_resume_preserves_45_global_facts_and_repeats_without_posts(
    tmp_path, monkeypatch
):
    from orchestrator.moneyflow_continuation.execution import apply
    from orchestrator.moneyflow_continuation.submission import Journal, submit_once
    from tests.test_moneyflow_collection_recovery import RawRecoveryNative
    from tests.test_moneyflow_continuation_submission import FakeNative

    plan, units, *_ = bundle(tmp_path, monkeypatch)

    class WholeScopeNative(RawRecoveryNative):
        def snapshots(self, selected, journal=None):
            results = []
            for unit in selected:
                if (
                    unit["dataset"] == "moneyflow"
                    and unit["trade_date"] >= "2026-10-13"
                ):
                    method = (
                        RawRecoveryNative.snapshots
                        if unit["trade_date"] == "2026-10-13"
                        else FakeNative.snapshots
                    )
                    results.extend(method(self, [unit], journal))
                else:
                    value = snapshot()
                    value.update(
                        dataset=unit["dataset"],
                        trade_date=unit["trade_date"],
                        registered=True,
                    )
                    for layer in ("raw", "silver"):
                        value[layer].update(ready=True, reason="ready")
                    if (
                        unit["dataset"] == "moneyflow_ths"
                        and unit["trade_date"] == "2026-10-14"
                    ):
                        value["silver"]["preserved_failure"] = {
                            "run_id": SILVER_PARENT,
                            "status": "FAILURE",
                        }
                    results.append(value)
            return results

    native, journal = WholeScopeNative(), Journal(plan, tmp_path / "journal")
    first = next(
        u
        for u in units
        if u["dataset"] == "moneyflow" and u["trade_date"] == "2026-10-13"
    )
    prior = unit_decisions(native.snapshots(units, journal))
    assert sum(d["next"] == "complete" for d in prior) == 45
    native.lose_response = True
    with pytest.raises(OSError):
        submit_once(native, journal, first, "raw_reexecution", AT)
    native.lose_response = False
    for _ in range(2):
        code, result = apply(
            native, plan, root=journal.root, clock=lambda: AT, output=lambda _: None
        )
        assert code == 0, result
        assert result["completed"] == 47 and len(result["preserved_failures"]) == 2
    assert len(native.posts) == 11 and len(native.native) == 8
    final = unit_decisions(native.snapshots(units, journal))
    assert sum(d["next"] == "complete" for d in final) == 49
    assert all(
        before == after
        for before, after in zip(prior, final, strict=True)
        if before["next"] == "complete"
    )
