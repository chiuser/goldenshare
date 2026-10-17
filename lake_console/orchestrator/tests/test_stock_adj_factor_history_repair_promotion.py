"""Real temporary file submission; metadata unit tests do not claim a 31-asset chain."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import (
    stock_adj_factor_history_repair_promotion as promotion,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    atomic_repair_json,
    file_identity,
    repair_hash,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
    repair_storage_totals,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
    RepairRuntime,
    RepairStorageLedger,
    use_repair_runtime,
)

from . import test_stock_adj_factor_history_repair_candidates as prices

freeze_case = prices.freeze_case
repair_endpoints = prices.repair_endpoints
scope = prices.scope
price_plan = prices.price_plan
candidate_connection = prices.candidate_connection


def unit_case(tmp_path):
    """Literal metadata/bytes: tests physical protocol only, never formula acceptance."""
    lake = tmp_path / "lake"
    run = tmp_path / "repair/run_id=11111111-1111-4111-8111-111111111111"
    target = lake / "gold/result.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-content")
    candidate = run / "candidates/gold/result.parquet"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"new-content")
    preimage = asdict(file_identity(target))
    new = asdict(file_identity(candidate))
    record = {
        "asset_key": "unit-only",
        "unit_id": "unit",
        "record_hash": "literal-metadata-hash",
        "target_relative_path": "gold/result.parquet",
        "preimage_sha256": preimage["sha256"],
        "candidate_sha256": new["sha256"],
        "candidate_relative_path": "candidates/gold/result.parquet",
        "candidate_bytes": new["size"],
        "no_op": False,
    }
    plan = {
        "run_id": run.name.removeprefix("run_id="),
        "plan_hash": "metadata-only",
        "lake_root": str(lake),
        "run_root": str(run),
        "source_fingerprints": [],
        "target_preimages": [preimage],
        "implementation_fingerprints": [],
        "units": [{"asset_key": "unit-only", "target_paths": [str(target)]}],
    }
    return plan, target, candidate, record


def runtime_for(plan):
    runtime = RepairRuntime(plan, admitted=True)
    # These metadata-only unit fixtures are outside the candidate artifact graph.
    # The real producer test below exercises ownership enforcement without a mock.
    runtime.storage = RepairStorageLedger(
        runtime.root, scan=repair_storage_totals, plan=plan, promotion_only=True
    )
    return runtime


@pytest.mark.parametrize("fault", ["none", "after_rename", "before_commit"])
def test_atomic_commit_and_interrupted_acknowledgement_resume(
    tmp_path, monkeypatch, fault
):
    plan, target, candidate, record = unit_case(tmp_path)
    runtime = runtime_for(plan)
    original_replace = promotion.os.replace
    formal_calls = []
    original_write = promotion._write_promotion

    def rename(source, destination):
        if Path(source) == candidate:
            formal_calls.append((source, destination))
            original_replace(source, destination)
            if fault == "after_rename":
                raise OSError("isolated after rename")
        else:
            original_replace(source, destination)

    def write(p, t, value):
        if fault == "before_commit" and value["status"] == "COMMITTED":
            raise OSError("isolated acknowledgement failure")
        return original_write(p, t, value)

    with use_repair_runtime(runtime), monkeypatch.context() as patch:
        patch.setattr(promotion.os, "replace", rename)
        patch.setattr(promotion, "_write_promotion", write)
        if fault == "none":
            result = promotion._commit_file(
                plan, runtime, target, record, None, candidate, "PENDING", "chain"
            )
            assert result["status"] == "COMMITTED"
        else:
            with pytest.raises(OSError):
                promotion._commit_file(
                    plan, runtime, target, record, None, candidate, "PENDING", "chain"
                )
    assert target.read_bytes() == b"new-content" and not candidate.exists()
    assert len(formal_calls) == 1
    resumed = runtime_for(plan)
    with use_repair_runtime(resumed):
        previous = promotion._load_promotion(plan, resumed, target, record, "chain")
        location, status = promotion._output_location(
            plan, resumed, target, record, previous
        )
        assert status == ("COMMITTED" if fault == "none" else "RECOVER")
        result = promotion._commit_file(
            plan, resumed, target, record, previous, location, status, "chain"
        )
        assert result["status"] == "COMMITTED"
        assert (
            result["readback"]["sha256"] == hashlib.sha256(b"new-content").hexdigest()
        )
        assert resumed.storage.snapshot()["candidate_bytes"] == 0
    assert target.read_bytes() == b"new-content"


def test_third_hash_and_wrong_checkpoint_binding_are_rejected(tmp_path):
    plan, target, _candidate, record = unit_case(tmp_path)
    runtime = runtime_for(plan)
    target.write_bytes(b"foreign-write")
    with pytest.raises(FactorRepairError, match="output_drift"):
        promotion._output_location(plan, runtime, target, record, None)
    binding = promotion._promotion_binding(plan, runtime, record, "wrong-chain")
    promotion._write_promotion(plan, target, {**binding, "status": "PREPARED"})
    with pytest.raises(FactorRepairError, match="record_invalid"):
        promotion._load_promotion(plan, runtime, target, record, "chain")


def test_real_price_producer_to_file_committer_preserves_control_stock(
    price_plan, candidate_connection
):
    from orchestrator.defs import paths
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        build_repair_target_candidate,
    )

    plan = price_plan
    c = candidate_connection
    root = Path(plan["lake_root"])
    prices.build_factor_day(c, plan)
    prices.build_factor_day(c, plan, "2026-06-26")
    target = paths.gold_stock_daily_qfq_path(root, "2026-06-29")
    control = c.execute(
        "SELECT * FROM read_parquet(?) WHERE ts_code='000001.SZ'", [str(target)]
    ).fetchall()
    record = build_repair_target_candidate(
        c, plan, prices.unit_for(plan, "gold_stock_daily_qfq"), target
    )
    runtime = RepairRuntime(plan, admitted=True)
    with use_repair_runtime(runtime):
        runtime.storage = RepairStorageLedger(
            runtime.root, scan=repair_storage_totals, plan=plan, promotion_only=True
        )
        checked = promotion._read_record(
            plan, runtime, prices.unit_for(plan, "gold_stock_daily_qfq"), target
        )
        assert checked["business_proof"]["version"] == 2
        output = runtime.root / record["candidate_relative_path"]
        result = promotion._commit_file(
            plan,
            runtime,
            target,
            record,
            None,
            output,
            "PENDING",
            "single-file-integration-only",
        )
        assert result["status"] == "COMMITTED"
    row = c.execute(
        "SELECT open,high,low,close,pre_close,change_amount,pct_chg,vol,amount FROM read_parquet(?) WHERE ts_code='688689.SH'",
        [str(target)],
    ).fetchone()
    assert row == pytest.approx((7.5, 8.25, 6.75, 7.5, 5.0, 2.5, 50.0, 100, 1000))
    assert (
        c.execute(
            "SELECT * FROM read_parquet(?) WHERE ts_code='000001.SZ'", [str(target)]
        ).fetchall()
        == control
    )
    assert not output.exists()


def sealed_metadata_plan(tmp_path, *, asset="unit-only"):
    """Literal bytes exercise orchestration, not formula or 31-asset acceptance.

    Complete candidate metadata follows the real v2 producer/reader contract;
    only load_repair_plan is replaced for this deliberately one-asset fixture.
    """
    plan, target, candidate, _ = unit_case(tmp_path)
    plan["units"][0]["asset_key"] = asset
    targets = [target, target.with_name("second.parquet")]
    candidates = [candidate, candidate.with_name("second.parquet")]
    targets[1].write_bytes(b"old-second")
    candidates[1].write_bytes(b"new-second")
    plan["units"][0]["target_paths"] = [str(p) for p in targets]
    plan["target_preimages"] = [asdict(file_identity(p)) for p in targets]
    plan["source_fingerprints"] = plan["target_preimages"]
    runtime = RepairRuntime(plan, admitted=True)
    for t, output, old in zip(targets, candidates, plan["target_preimages"], strict=True):
        record = {
            "format_version": 2, "plan_hash": plan["plan_hash"],
            "asset_key": asset, "unit_id": repair_hash([plan["plan_hash"], asset, str(t)]),
            "target_relative_path": t.relative_to(runtime.lake_root).as_posix(),
            "preimage_sha256": old["sha256"],
            "candidate_relative_path": output.relative_to(runtime.root).as_posix(),
            "candidate_sha256": file_identity(output).sha256,
            "candidate_bytes": output.stat().st_size, "no_op": False,
            "validated": True, "original_rows": 1, "replacement_rows": 1,
            "changed_stock_rows": 1, "candidate_rows": 1, "input_paths": [str(t)],
        }
        record["business_proof"] = runtime.business_proof(record,
            approved_keys=runtime.approved_scope(t), dependencies=runtime.dependency_digest(record))
        record["record_hash"] = repair_hash(record)
        atomic_repair_json(promotion.repair_record_path(runtime.root, t, runtime.lake_root), record)
    for phase in ("factor", "price", "indicator"):
        atomic_repair_json(runtime.root / (phase + "-audit.json"), {
            "plan_hash": plan["plan_hash"], "sample": False,
            "status": phase.upper() + "_CANDIDATES_VERIFIED"})
    atomic_repair_json(runtime.root / "plan.json", plan)
    promotion.seal_repair_candidate_chain(plan)
    return plan, targets, candidates


def admit_metadata(monkeypatch, plan):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_execution as execution,
    )

    def load(path, digest, **kwargs):
        assert Path(path) == Path(plan["run_root"]) / "plan.json"
        assert digest == plan["plan_hash"]
        return plan
    monkeypatch.setattr(execution, "load_repair_plan", load)


def test_promote_cancel_resume_and_completed_replay_need_no_deadline(tmp_path, monkeypatch):
    plan, targets, candidates = sealed_metadata_plan(tmp_path)
    admit_metadata(monkeypatch, plan)
    root = Path(plan["run_root"])
    plan_bytes = (root / "plan.json").read_bytes()
    queries, updates = [], []
    args = {"plan_path": root / "plan.json", "expected_hash": plan["plan_hash"]}
    preview = promotion.promote_repair_files(**args, dry_run=True,
        writer_guard=lambda p: pytest.fail("dry-run queried writers"))
    assert not preview["completed"]
    assert not (root / "checkpoints/promotions").exists()
    with pytest.raises(FactorRepairError, match="canceled"):
        promotion.promote_repair_files(**args, maintenance_confirmed=True,
            writer_guard=lambda p: queries.append(p["plan_hash"]),
            progress=lambda data: updates.append(data) if data.get("phase") == "promotion" else None,
            cancel=lambda: bool(updates))
    assert len(queries) == 1 and len(updates) == 1
    assert targets[0].read_bytes() == b"new-content"
    assert targets[1].read_bytes() == b"old-second"
    assert not candidates[0].exists() and candidates[1].exists()
    result = promotion.promote_repair_files(**args, maintenance_confirmed=True,
        writer_guard=lambda p: queries.append(p["plan_hash"]))
    assert result["completed"] and len(queries) == 2
    assert targets[1].read_bytes() == b"new-second"
    assert not any(p.exists() for p in candidates)
    assert (root / "plan.json").read_bytes() == plan_bytes
    assert "execution_window" not in json.loads((root / "checkpoint.json").read_text())
    assert len((root / "reports/promotion_manifest.csv").read_text().splitlines()) == 3
    with monkeypatch.context() as patch:
        patch.setattr(promotion.os, "replace", lambda *a: pytest.fail("completed file rewritten"))
        result = promotion.promote_repair_files(**args, maintenance_confirmed=True,
            writer_guard=lambda p: pytest.fail("completed run queried writers"))
    assert result["completed"]


def test_promote_real_conflict_and_third_hash_do_not_write(tmp_path, monkeypatch):
    plan, targets, candidates = sealed_metadata_plan(tmp_path)
    admit_metadata(monkeypatch, plan)
    args = {"plan_path": Path(plan["run_root"]) / "plan.json", "expected_hash": plan["plan_hash"],
            "maintenance_confirmed": True}
    def conflict(_plan):
        raise FactorRepairError("actual_writer_conflict")
    with pytest.raises(FactorRepairError, match="actual_writer_conflict"):
        promotion.promote_repair_files(**args, writer_guard=conflict)
    assert targets[0].read_bytes() == b"old-content" and all(p.exists() for p in candidates)
    targets[0].write_bytes(b"third-version")
    with pytest.raises(FactorRepairError, match="drift"):
        promotion.promote_repair_files(**args, writer_guard=lambda p: None)
    assert targets[0].read_bytes() == b"third-version" and all(p.exists() for p in candidates)


def test_report_failure_after_all_commits_resumes_metadata_only(tmp_path, monkeypatch):
    plan, targets, candidates = sealed_metadata_plan(tmp_path)
    admit_metadata(monkeypatch, plan)
    root = Path(plan["run_root"])
    args = {"plan_path": root / "plan.json", "expected_hash": plan["plan_hash"],
            "maintenance_confirmed": True}
    with monkeypatch.context() as patch:
        def fault(*_args):
            raise OSError("isolated report failure")
        patch.setattr(promotion, "_write_reports", fault)
        with pytest.raises(OSError, match="report failure"):
            promotion.promote_repair_files(**args, writer_guard=lambda p: None)
    assert targets[0].read_bytes() == b"new-content" and targets[1].read_bytes() == b"new-second"
    assert not any(p.exists() for p in candidates)
    changed = []
    real_replace = promotion.os.replace
    def rename(source, destination):
        if Path(destination) in targets:
            changed.append(destination)
        return real_replace(source, destination)
    monkeypatch.setattr(promotion.os, "replace", rename)
    result = promotion.promote_repair_files(**args,
        writer_guard=lambda p: pytest.fail("metadata recovery queried writers"))
    assert result["completed"] and not changed
    assert len((root / "reports/promotion_manifest.csv").read_text().splitlines()) == 3


def test_failed_commit_reports_actual_checkpoint_and_preserves_data(tmp_path, monkeypatch):
    import csv

    plan, targets, _ = sealed_metadata_plan(tmp_path)
    admit_metadata(monkeypatch, plan)
    root = Path(plan["run_root"])
    def fail(*args):
        raise OSError("isolated before prepare")
    monkeypatch.setattr(promotion, "_commit_file", fail)
    with pytest.raises(OSError, match="before prepare"):
        promotion.promote_repair_files(root / "plan.json", plan["plan_hash"],
            maintenance_confirmed=True, writer_guard=lambda p: None)
    with (root / "reports/failures.csv").open(newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert len(failures) == 1
    assert failures[0]["status"] == "ATTEMPT_FAILED"
    assert failures[0]["checkpoint_status"] == "NOT_PREPARED"
    assert failures[0]["reason_code"] == "isolated before prepare"
    assert targets[0].read_bytes() == b"old-content" and targets[1].read_bytes() == b"old-second"


@pytest.mark.parametrize("fault", ["missing_seal", "missing_target", "sample", "wrong_binding"])
def test_incomplete_chain_is_never_promotable(tmp_path, monkeypatch, fault):
    plan, targets, candidates = sealed_metadata_plan(tmp_path)
    admit_metadata(monkeypatch, plan)
    root = Path(plan["run_root"])
    if fault == "missing_seal":
        (root / "checkpoint.json").write_text("{}")
    elif fault == "missing_target":
        promotion.repair_record_path(root, targets[1], Path(plan["lake_root"])).unlink()
    elif fault == "sample":
        path = root / "price-audit.json"
        value = json.loads(path.read_text()); value["sample"] = True
        atomic_repair_json(path, value)
        with pytest.raises(FactorRepairError, match="chain_incomplete"):
            promotion.seal_repair_candidate_chain(plan)
        return
    else:
        path = root / "checkpoint.json"
        value = json.loads(path.read_text()); value["candidate_chain"]["chain_hash"] = "wrong"
        atomic_repair_json(path, value)
    with pytest.raises((FactorRepairError, FileNotFoundError)):
        promotion.promote_repair_files(root / "plan.json", plan["plan_hash"],
            maintenance_confirmed=True, writer_guard=lambda p: None)
    assert targets[0].read_bytes() == b"old-content" and all(p.exists() for p in candidates)


@pytest.mark.parametrize("extra", [[], ["--dry-run", "--maintenance-confirmed"],
    ["--dry-run", "--full"], ["--dry-run", "--maintenance-until", "2099-01-01"]])
def test_cli_promote_rejects_ambiguous_or_extended_scope(extra, monkeypatch):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli import main
    monkeypatch.setattr(promotion, "promote_repair_files", lambda *a, **kw: pytest.fail("invalid CLI executed"))
    with pytest.raises(SystemExit):
        main(["promote", "--plan", "/not-opened", "--expected-plan-hash", "hash", *extra])


def test_cli_promote_routes_without_definitions_or_source(monkeypatch, capsys):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli import main
    calls = []
    def run(path, expected_hash, **kwargs):
        calls.append((path, expected_hash, kwargs["dry_run"], kwargs["maintenance_confirmed"]))
        assert callable(kwargs["writer_guard"])
        return {"completed": False}
    monkeypatch.setattr(promotion, "promote_repair_files", run)
    assert main(["promote", "--plan", "/not-opened", "--expected-plan-hash", "hash", "--dry-run"]) == 0
    assert calls == [(Path("/not-opened"), "hash", True, False)]
    assert json.loads(capsys.readouterr().out) == {"completed": False}


@pytest.mark.parametrize("missing_phase", [False, True])
def test_full_indicator_coordinator_wires_chain_seal_without_recomputing(
    tmp_path, monkeypatch, missing_phase
):
    """Actual coordinator + subprocess + seal; worker is a metadata protocol double.

    Candidate values/contract were tested separately. This tests only final-phase
    orchestration, and deliberately does not claim real 31-asset computation.
    """
    import sys

    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_execution as execution,
    )

    plan, _, candidates = sealed_metadata_plan(tmp_path, asset="gold_stock_daily_trend_channel")
    root = Path(plan["run_root"])
    (root / "checkpoint.json").write_text("{}")
    if missing_phase:
        (root / "price-audit.json").unlink()
    runtime = RepairRuntime(plan, admitted=True)
    runtime.plan_bytes_sha256 = hashlib.sha256((root / "plan.json").read_bytes()).hexdigest()
    runtime.indexes["indicator_tasks"] = []
    monkeypatch.setattr(execution, "_COORDINATOR_RUNTIME", runtime)
    worker = tmp_path / "metadata-worker.py"
    worker.write_text('''import json,sys
from pathlib import Path
for line in sys.stdin:
    request=json.loads(line)
    if request['action']=='init':
        root=Path(request['plan_path']).parent
        response={'status':'ready'}
    elif request['action']=='finish':
        response={'status':'finished'}
    else:
        counts=json.loads((root/'checkpoint.json').read_text())['storage_accounting']['counts']
        response={'status':'batch_done','result':{'storage_accounting':{'counts':counts},
            'peak_rss_bytes':0,'changed_rows':0,'no_op_files':0,'counters':{}}}
    print(json.dumps(response),flush=True)
    if request['action']=='finish':break
''')
    args = {"plan_path": root / "plan.json", "expected_hash": plan["plan_hash"],
            "phase": "indicator", "worker_command": [sys.executable, "-B", str(worker)]}
    if missing_phase:
        with pytest.raises(FileNotFoundError):
            execution.execute_repair_candidates(**args)
        assert not json.loads((root / "checkpoint.json").read_text()).get("candidate_chain")
    else:
        result = execution.execute_repair_candidates(**args)
        assert result["all_chain_ready"] and result["candidate_chain"]["targets"] == 2
        assert json.loads((root / "checkpoint.json").read_text())["candidate_chain"] == result["candidate_chain"]
    assert all(p.exists() for p in candidates)


@pytest.mark.parametrize("audit", [False, True])
def test_build_and_audit_reject_started_promotion_before_worker(tmp_path, monkeypatch, audit):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_execution as execution,
    )

    plan, _, candidates = sealed_metadata_plan(tmp_path, asset="gold_stock_daily_trend_channel")
    root = Path(plan["run_root"])
    atomic_repair_json(root / "checkpoint.json", {"promotion": {"status": "PROMOTING"}})
    runtime = RepairRuntime(plan, admitted=True)
    runtime.indexes["indicator_tasks"] = []
    monkeypatch.setattr(execution, "_COORDINATOR_RUNTIME", runtime)
    monkeypatch.setattr(execution.subprocess, "Popen", lambda *a, **kw: pytest.fail("wrong-stage worker launched"))
    with pytest.raises(FactorRepairError, match="promotion_resume_required"):
        execution.execute_repair_candidates(root / "plan.json", plan["plan_hash"],
            phase="indicator", audit=audit)
    assert all(p.exists() for p in candidates)


def sealed_metadata_with_indicator_receipt(tmp_path):
    """Ownership-only fixture with a planned task and literal saved-file references.

    The marker->receipts->outputs shape comes from the real R4 task.json and
    segment-1.json, and the producer at _indicators.py:679. Bytes are deliberately
    metadata-only; neither this fixture nor its admission double proves formulas.
    """
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
        indicator_replay_tasks,
    )

    plan, targets, candidates = sealed_metadata_plan(tmp_path)
    plan["units"].append({
        "asset_key": "gold_stock_daily_qfq_nineturn", "target_paths": [],
        "calendar_dates": ["2026-10-16"],
        "calculation_windows": [{"ts_code": "688689.SH"}],
    })
    task = indicator_replay_tasks(plan)[0]
    root = Path(plan["run_root"])
    directory = root / "inputs/indicator_replay" / task["task_id"]
    directory.mkdir(parents=True)
    output = directory / "segment-0-result.parquet"
    output.write_bytes(b"owned-metadata-fixture-output")
    receipt = directory / "segment-0.json"
    atomic_repair_json(receipt, {"outputs": {"result": asdict(file_identity(output))}})
    marker = directory / "task.json"
    atomic_repair_json(marker, {"receipts": [asdict(file_identity(receipt))]})
    atomic_repair_json(root / "plan.json", plan)
    checkpoint = root / "checkpoint.json"
    saved = json.loads(checkpoint.read_text())
    saved.pop("storage_accounting", None)
    atomic_repair_json(checkpoint, saved)
    # Establish the starting byte census from actual fixture files, not guessed sizes.
    RepairStorageLedger(root, scan=repair_storage_totals, plan=plan,
        promotion_only=True).persist()
    return plan, targets, candidates, marker, receipt, output


def test_promote_initializes_indicator_census_and_completed_replay_is_read_only(tmp_path, monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_indicators as indicators,
    )

    plan, targets, candidates, marker, receipt, output = sealed_metadata_with_indicator_receipt(tmp_path)
    admit_metadata(monkeypatch, plan)
    root = Path(plan["run_root"])
    preserved = [root / "plan.json", marker, receipt, output]
    before = [file_identity(p) for p in preserved]
    calls = []
    build = indicators.indicator_replay_tasks

    def count(p):
        calls.append(p["plan_hash"])
        return build(p)

    monkeypatch.setattr(indicators, "indicator_replay_tasks", count)
    args = {"plan_path": root / "plan.json", "expected_hash": plan["plan_hash"],
        "maintenance_confirmed": True}
    result = promotion.promote_repair_files(**args, writer_guard=lambda _: None)
    assert result["status"] == "FILES_COMPLETE_EVENTS_PENDING" and calls == [plan["plan_hash"]]
    assert [p.read_bytes() for p in targets] == [b"new-content", b"new-second"]
    assert all(not p.exists() for p in candidates)
    assert [file_identity(p) for p in preserved] == before
    completed = [*targets, root / "checkpoint.json", root / "reports/promotion_manifest.csv"]
    identities = [file_identity(p) for p in completed]
    monkeypatch.setattr(promotion, "_commit_file", lambda *a, **k: pytest.fail("committer called again"))
    assert promotion.promote_repair_files(**args,
        writer_guard=lambda _: pytest.fail("completed run queried writers"))["completed"]
    assert [file_identity(p) for p in completed] == identities
    assert calls == [plan["plan_hash"]]  # No new work on the already-finalized return.


@pytest.mark.parametrize("fault", ["orphan", "unknown", "missing_marker"])
def test_promote_indicator_census_still_rejects_invalid_artifacts(tmp_path, monkeypatch, fault):
    plan, _, _, marker, receipt, _ = sealed_metadata_with_indicator_receipt(tmp_path)
    admit_metadata(monkeypatch, plan)
    root = Path(plan["run_root"])
    if fault == "orphan":
        receipt.with_name("unreferenced.json").write_bytes(b"")
    elif fault == "unknown":
        (root / "unknown.json").write_bytes(b"")
    else:
        marker.unlink()
    error = FileNotFoundError if fault == "missing_marker" else FactorRepairError
    reason = None if fault == "missing_marker" else "unowned_artifact"
    with pytest.raises(error, match=reason):
        promotion.promote_repair_files(root / "plan.json", plan["plan_hash"],
            maintenance_confirmed=True, writer_guard=lambda _: None)
    assert json.loads((root / "checkpoint.json").read_text())["promotion"]["status"] == "PROMOTING"
