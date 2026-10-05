"""Real isolated instance/file tests; no formal service or Lake access."""

from dataclasses import asdict
from pathlib import Path

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
)

from orchestrator.defs.bootstrap.stock_monthly_events import (
    MonthlyEventPolicy,
    _asset,
    _matching_check,
    apply_monthly_events,
    audit_monthly_event_files,
    audit_monthly_readiness_samples,
    freeze_monthly_event_plan,
    read_monthly_event_state,
    verify_monthly_event_plan,
)
from orchestrator.defs.bootstrap.stock_monthly_events_cli import main
from orchestrator.defs.bootstrap.stock_monthly_files import (
    monthly_file_hash,
    write_monthly_json,
)
from orchestrator.defs.bootstrap.stock_monthly_history import (
    execute_monthly_history,
    monthly_history_preflight,
)
from orchestrator.defs.bootstrap.stock_monthly_history_plan import (
    monthly_history_plan_payload,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    STOCK_MONTHLY_PARTITIONS,
    monthly_contract_hash,
)
from tests.test_stock_monthly_history import fixture


@pytest.fixture
def context(tmp_path):
    lake, stage = tmp_path / "lake", tmp_path / "stage"
    lake.mkdir()
    stage.mkdir()
    refs = []
    for source in ("primary_unadjusted", "primary_adjusted"):
        child = tmp_path / source
        child.mkdir()
        plan, _, _, exporter = fixture(child, source)
        execute_monthly_history(
            plan, monthly_history_preflight(plan, lake, stage), exporter=exporter
        )
        path = child / "history_plan.json"
        write_monthly_json(path, monthly_history_plan_payload(plan), 8 * 1024**2)
        refs.append({"path": str(path), "sha256": monthly_file_hash(path)})
    evidence = {
        "lake_root": str(lake),
        "staging_root": str(stage),
        "history_plans": refs,
    }
    entries, metrics = audit_monthly_event_files(evidence)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = freeze_monthly_event_plan(
            instance, entries, instance_identity={"isolated": True}, evidence=evidence
        )
        yield instance, plan, tmp_path / "progress.json", metrics


def apply_all(ctx, **kwargs):
    instance, plan, checkpoint, _ = ctx
    apply_monthly_events(instance, plan, checkpoint=checkpoint, register=True)
    return apply_monthly_events(instance, plan, checkpoint=checkpoint, **kwargs)


def test_two_sources_full_semantics_and_idempotent_replay(context):
    instance, plan, _, metrics = context
    assert plan["counts"]["materializations"] == 4 and plan["counts"]["checks"] == 12
    assert len(plan["missing_registrations"]) == 2
    assert sum(m["year_scans"] for m in metrics) == 2
    assert apply_all(context)["writes"] == 16
    assert apply_all(context) == {"writes": 0, "skipped": 16, "records_returned": 28}
    samples = audit_monthly_readiness_samples(
        instance, plan["entries"], Path(plan["evidence"]["lake_root"])
    )
    assert all(s["ready"] for s in samples)
    from orchestrator.defs.run_contracts.stock_monthly import StockMonthlySource
    from orchestrator.defs.stock_monthly_update_state import monthly_period_status

    assert all(
        monthly_period_status(
            instance,
            Path(plan["evidence"]["lake_root"]),
            StockMonthlySource(e["source"]),
            e["month"],
        )
        == "ready"
        for e in plan["entries"]
    )
    current = freeze_monthly_event_plan(
        instance,
        plan["entries"],
        instance_identity={"isolated": True},
        evidence=plan["evidence"],
    )
    assert current["counts"]["materializations"] == current["counts"]["checks"] == 0
    assert current["missing_registrations"] == []


def test_cancel_after_committed_event_resumes_from_database(context, monkeypatch):
    instance, plan, checkpoint, _ = context
    apply_monthly_events(instance, plan, checkpoint=checkpoint, register=True)
    original = instance.report_runless_asset_event
    called = False

    def report(event):
        nonlocal called
        original(event)
        called = True

    monkeypatch.setattr(instance, "report_runless_asset_event", report)
    with pytest.raises(ValueError, match="monthly_cancelled"):
        apply_monthly_events(
            instance, plan, checkpoint=checkpoint, cancel=lambda: called
        )
    monkeypatch.setattr(instance, "report_runless_asset_event", original)
    assert apply_all(context)["writes"] == 15


def test_checkpoint_failure_does_not_undo_event(context, monkeypatch):
    import orchestrator.defs.bootstrap.stock_monthly_events as module

    instance, plan, checkpoint, _ = context
    apply_monthly_events(instance, plan, checkpoint=checkpoint, register=True)
    original = module.write_monthly_json
    monkeypatch.setattr(
        module,
        "write_monthly_json",
        lambda *a: (_ for _ in ()).throw(RuntimeError("exit")),
    )
    with pytest.raises(RuntimeError, match="exit"):
        apply_monthly_events(instance, plan, checkpoint=checkpoint)
    monkeypatch.setattr(module, "write_monthly_json", original)
    assert apply_all(context)["writes"] == 15


@pytest.mark.parametrize("count", [0, 26, 101, True])
def test_write_budget_rejects_before_any_event(context, count):
    with pytest.raises(ValueError, match="batch_invalid"):
        apply_monthly_events(context[0], context[1], checkpoint=context[2], count=count)
    assert context[0].get_dynamic_partitions(STOCK_MONTHLY_PARTITIONS) == []


@pytest.mark.parametrize("kind", ["file", "receipt", "audit", "history_plan"])
def test_changed_physical_evidence_cannot_be_reported_green(context, kind):
    instance, plan, checkpoint, _ = context
    entry = plan["entries"][0]
    if kind == "history_plan":
        path = Path(plan["evidence"]["history_plans"][0]["path"])
    elif kind == "file":
        path = Path(entry["path"])
    elif kind == "audit":
        path = Path(entry["audit_path"])
    else:
        path = next(Path(plan["evidence"]["staging_root"]).rglob("receipt.json"))
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        if kind == "history_plan":
            audit_monthly_event_files(plan["evidence"])
        else:
            apply_monthly_events(instance, plan, checkpoint=checkpoint, register=True)
    assert instance.get_dynamic_partitions(STOCK_MONTHLY_PARTITIONS) == []


def test_foreign_latest_materialization_cannot_be_overwritten(context):
    apply_all(context)
    instance, plan, checkpoint, _ = context
    entry = plan["entries"][0]
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key=_asset(entry), partition=entry["month"])
    )
    with pytest.raises(ValueError, match="materialization_changed"):
        apply_monthly_events(instance, plan, checkpoint=checkpoint)


def test_failed_latest_check_cannot_be_overwritten(context):
    instance, plan, checkpoint, _ = context
    entry = plan["entries"][0]
    name = entry["missing_checks"][0]
    instance.report_runless_asset_event(
        AssetCheckEvaluation(
            asset_key=_asset(entry),
            check_name=name,
            partition=entry["month"],
            passed=False,
        )
    )
    with pytest.raises(ValueError, match="check_changed"):
        apply_monthly_events(instance, plan, checkpoint=checkpoint)
    new = freeze_monthly_event_plan(
        instance, plan["entries"], instance_identity={}, evidence=plan["evidence"]
    )
    assert new["counts"]["historical_latest_failed"] == 1
    with pytest.raises(ValueError, match="requires_review"):
        apply_monthly_events(instance, new, checkpoint=checkpoint)


def test_read_return_cap_is_enforced(context):
    apply_all(context)
    with pytest.raises(ValueError, match="record_read_cap_exceeded"):
        read_monthly_event_state(context[0], context[1]["entries"], record_cap=1)


def test_checks_bind_exact_latest_materialization(context):
    apply_all(context)
    instance, plan, _, _ = context
    entry = plan["entries"][0]
    state, _ = read_monthly_event_state(instance, [entry])
    current = state[(entry["source"], entry["month"])]
    name, (_, record) = next(iter(current["checks"].items()))
    assert _matching_check(record, name, current["mat"], entry)
    assert not _matching_check(
        record, name, current["mat"], {**entry, "month": "2020-03"}
    )
    assert not _matching_check(record, name, current["mat"], {**entry, "rows": 3})


@pytest.mark.parametrize("kind", ["hash", "policy", "duplicate", "check", "path"])
def test_invalid_plan_fails_closed(context, kind):
    import copy

    plan = copy.deepcopy(context[1])
    if kind == "hash":
        plan["plan_hash"] = "wrong"
    if kind == "policy":
        plan["policy"] = {**asdict(MonthlyEventPolicy()), "event_write_batch": 200}
    if kind == "duplicate":
        plan["entries"].append(plan["entries"][0])
    if kind == "check":
        plan["entries"][0]["missing_checks"].append("foreign")
    if kind == "path":
        plan["entries"][0]["path"] = "/private/tmp/foreign.parquet"
    if kind != "hash":
        plan["plan_hash"] = monthly_contract_hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        )
    with pytest.raises(ValueError):
        verify_monthly_event_plan(plan)


def test_cli_requires_explicit_apply_and_never_opens_instance(context, monkeypatch):
    import orchestrator.defs.bootstrap.stock_monthly_events_cli as module

    plan = context[2].parent / "events.json"
    write_monthly_json(plan, context[1], 8 * 1024**2)
    monkeypatch.setattr(
        module,
        "open_weekly_event_instance",
        lambda **kw: pytest.fail("no instance expected"),
    )
    with pytest.raises(SystemExit):
        main(
            [
                "--mode",
                "apply",
                "--plan",
                str(plan),
                "--report",
                str(context[2]),
                "--lake-root",
                context[1]["evidence"]["lake_root"],
                "--staging-root",
                context[1]["evidence"]["staging_root"],
            ]
        )


def test_sample_scope_only_selected_complete_asset_partitions(context):
    instance, plan, checkpoint, _ = context
    apply_monthly_events(instance, plan, checkpoint=checkpoint, register=True)
    assert (
        apply_monthly_events(instance, plan, checkpoint=checkpoint, months=["2020-02"])[
            "writes"
        ]
        == 8
    )
    state, _ = read_monthly_event_state(instance, plan["entries"])
    assert all(
        v["mat"] is None for (_, month), v in state.items() if month == "2020-01"
    )
    assert apply_all(context)["writes"] == 8


def test_actual_process_exit_keeps_events_and_resumes(context, tmp_path):
    import subprocess
    import sys

    instance_root = tmp_path / "persistent_instance"
    instance_root.mkdir()
    plan_path = tmp_path / "process_plan.json"
    write_monthly_json(plan_path, context[1], 8 * 1024**2)
    worker = """
import os, sys, dagster as dg
from pathlib import Path
from orchestrator.defs.bootstrap.stock_monthly_files import read_monthly_json
from orchestrator.defs.bootstrap.stock_monthly_events import apply_monthly_events
plan=read_monthly_json(Path(sys.argv[2]), 8*1024**2)
with dg.DagsterInstance.local_temp(tempdir=sys.argv[1], overrides={"telemetry":{"enabled":False}}) as instance:
    apply_monthly_events(instance, plan, checkpoint=Path(sys.argv[3]), register=True)
    original=instance.report_runless_asset_event
    calls=0
    def report(event):
        global calls
        original(event)
        calls+=1
        if calls==5: os._exit(29)
    instance.report_runless_asset_event=report
    apply_monthly_events(instance, plan, checkpoint=Path(sys.argv[3]))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            worker,
            str(instance_root),
            str(plan_path),
            str(context[2]),
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 29, result.stderr.decode()
    with dg.DagsterInstance.local_temp(
        tempdir=str(instance_root), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        assert (
            apply_monthly_events(instance, context[1], checkpoint=context[2])["writes"]
            == 11
        )
        assert (
            apply_monthly_events(instance, context[1], checkpoint=context[2])["writes"]
            == 0
        )


def test_yearly_event_state_is_three_queries_per_source_not_per_check(
    context, monkeypatch
):
    apply_all(context)
    instance, plan, _, _ = context
    counts = {"mats": 0, "index": 0, "bodies": 0}
    for owner, attr, key in (
        (instance, "fetch_materializations", "mats"),
        (instance.event_log_storage, "get_asset_check_partition_info", "index"),
        (instance.event_log_storage, "get_event_records", "bodies"),
    ):
        original = getattr(owner, attr)

        def wrap(*args, _original=original, _key=key, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, attr, wrap)
    state, returned = read_monthly_event_state(instance, plan["entries"])
    assert len(state) == 4 and returned == 28
    assert counts == {"mats": 2, "index": 2, "bodies": 2}


def test_logical_hash_drift_rejected_even_with_rehashed_plan(context):
    import copy

    plan = copy.deepcopy(context[1])
    plan["entries"][0]["logical_hash"] = "0" * 64
    plan["plan_hash"] = monthly_contract_hash(
        {k: v for k, v in plan.items() if k != "plan_hash"}
    )
    with pytest.raises(ValueError, match="logical_hash_changed"):
        apply_monthly_events(context[0], plan, checkpoint=context[2], register=True)


@pytest.mark.parametrize("sha", [None, "0" * 64])
def test_cli_apply_requires_external_frozen_plan_sha(context, monkeypatch, sha):
    import orchestrator.defs.bootstrap.stock_monthly_events_cli as module

    plan = context[2].parent / "sha_plan.json"
    write_monthly_json(plan, context[1], 8 * 1024**2)
    monkeypatch.setattr(
        module,
        "open_weekly_event_instance",
        lambda **kw: pytest.fail("must reject before instance"),
    )
    argv = [
        "--mode",
        "apply",
        "--apply",
        "--plan",
        str(plan),
        "--report",
        str(context[2]),
        "--lake-root",
        context[1]["evidence"]["lake_root"],
        "--staging-root",
        context[1]["evidence"]["staging_root"],
    ]
    if sha:
        argv += ["--plan-sha256", sha]
    with pytest.raises(SystemExit):
        main(argv)
