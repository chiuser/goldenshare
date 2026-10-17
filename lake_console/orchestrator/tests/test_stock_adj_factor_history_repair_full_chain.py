"""R3 integration and recovery evidence. Every writable resource is an isolated fixture."""

from __future__ import annotations

import fcntl
import inspect
import json
import os
import resource
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path
from uuid import uuid4

import pytest

from orchestrator.defs import paths
from orchestrator.defs.bootstrap import stock_adj_factor_history_repair as contract
from orchestrator.defs.bootstrap import (
    stock_adj_factor_history_repair_execution as execution,
)
from orchestrator.defs.bootstrap import (
    stock_adj_factor_history_repair_indicators as indicators,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    AssetRepairEndpoint,
    FactorRepairError,
    FactorRepairScope,
    RepairBudget,
    atomic_repair_json,
    file_identity,
    freeze_stock_factor_repair,
    repair_hash,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    read_repair_candidate_record,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import read_parquet

from . import test_stock_adj_factor_history_repair_indicators as samples

freeze_case = samples.freeze_case
repair_endpoints = samples.repair_endpoints
scope = samples.scope
price_plan = samples.price_plan
indicator_plan = samples.indicator_plan
PHASES = ("factor", "price", "indicator")


def _evidence_path(plan, name):
    return Path(plan["run_root"]).parent / "r3-evidence" / Path(plan["run_root"]).name / name


def _append(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, separators=(",", ":")) + "\n")


def _guard():
    for key in ("DAGSTER_HOME", "TUSHARE_TOKEN", "DATABASE_URL"):
        os.environ.pop(key, None)

    def audit(event, args):
        if event in ("os.scandir", "os.listdir") and args and isinstance(args[0], (str, bytes)) and str(args[0]).startswith("/Volumes/"):
            raise RuntimeError("R3 formal/global directory scans forbidden")
        if event == "socket.connect":
            raise RuntimeError("R3 network forbidden")
        if event == "open" and isinstance(args[0], str):
            name, mode, flags = args
            if name.startswith("/Volumes/") or "/.goldenshare/" in name:
                raise RuntimeError("R3 formal resources forbidden")
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & 3
            )
            if write and getattr(sys, "_r3_readonly_lake", None) and name.startswith(sys._r3_readonly_lake + "/"):
                raise RuntimeError("R3 fixture inputs are read only")
            if (
                write
                and not name.startswith(("/private/tmp/", "/tmp/"))
                and name != "/dev/null"
            ):
                raise RuntimeError("R3 writes outside temporary fixtures")

    sys.addaudithook(audit)


def _roots(plan):
    assert Path(plan["lake_root"]).is_relative_to(Path("/private/tmp"))
    assert Path(plan["run_root"]).is_relative_to(Path("/private/tmp"))
    sys._r3_readonly_lake = plan["lake_root"]
    contract.DEFAULT_LAKE_ROOT = plan["lake_root"]
    contract.DEFAULT_LAKE_STAGING_ROOT = str(Path(plan["run_root"]).parents[1])


def _launcher(tmp_path, role, *args):
    path = tmp_path / (role + "-launcher.py")
    project = Path(__file__).parents[1]
    path.write_text(
        "import os,sys\n"
        + inspect.getsource(_guard)
        + "\n_guard()\n"
        + f"sys.path.insert(0,{str(project)!r})\n"
        + "from tests.test_stock_adj_factor_history_repair_full_chain import "
        + role
        + "\n"
        + role
        + "()\n"
    )
    return [sys.executable, "-B", str(path), *map(str, args)]


def _worker():
    holder = {}
    def prepare(plan):
        holder["plan"] = plan
        _roots(plan)
    metrics = {
        "sql_calls": 0,
        "copy_calls": 0,
        "sql_seconds": 0.0,
        "hash_calls": 0,
        "hash_bytes": 0,
        "hash_seconds": 0.0,
        "storage_calls": 0,
        "storage_seconds": 0.0,
        "fsync_calls": 0,
        "fsync_seconds": 0.0,
    }
    original_identity = execution.file_identity

    def identity(*args, **kwargs):
        started = time.monotonic()
        result = original_identity(*args, **kwargs)
        metrics["hash_calls"] += 1
        metrics["hash_bytes"] += result.size
        metrics["hash_seconds"] += time.monotonic() - started
        return result


    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_runtime as runtime,
    )
    runtime.file_identity = identity
    original_connect = execution.connect_configured_duckdb

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, *args, **kwargs):
            started = time.monotonic()
            try:
                return self.connection.execute(query, *args, **kwargs)
            finally:
                metrics["sql_calls"] += 1
                metrics["copy_calls"] += int(query.lstrip().upper().startswith("COPY"))
                metrics["sql_seconds"] += time.monotonic() - started

        def __getattr__(self, name):
            return getattr(self.connection, name)

    @contextmanager
    def connect(*args, **kwargs):
        with original_connect(*args, **kwargs) as connection:
            yield Connection(connection)

    execution.connect_configured_duckdb = connect
    original_storage = execution.check_repair_storage

    def storage(*args, **kwargs):
        started = time.monotonic()
        try:
            return original_storage(*args, **kwargs)
        finally:
            metrics["storage_calls"] += 1
            metrics["storage_seconds"] += time.monotonic() - started

    execution.check_repair_storage = storage
    original_fsync = os.fsync

    def fsync(fd):
        started = time.monotonic()
        try:
            return original_fsync(fd)
        finally:
            metrics["fsync_calls"] += 1
            metrics["fsync_seconds"] += time.monotonic() - started

    os.fsync = fsync
    fault = sys.argv[1] if len(sys.argv) > 1 else "none"
    original_copy = execution.bounded_repair_copy

    def copy(connection, query, root, output, **kwargs):
        plan = holder["plan"]
        if fault == "hold":
            _evidence_path(plan, "r3-worker-started.json").parent.mkdir(parents=True, exist_ok=True)
            atomic_repair_json(
                _evidence_path(plan, "r3-worker-started.json"),
                {
                    "pid": os.getpid(),
                    "child_pid": subprocess.Popen(
                        [sys.executable, "-B", "-c", "import time;time.sleep(60)"]
                    ).pid,
                },
            )
            time.sleep(60)
        if fault == "copy_exit":
            with runtime.runtime_storage(root).writing(output):
                Path(output).write_bytes(b"PAR1-incomplete-owned-test-output")
                os._exit(23)
        result = original_copy(connection, query, root, output, **kwargs)
        if fault == "fsync_fail":

            def fail(_fd):
                raise OSError("R3 injected fsync failure")

            os.fsync = fail
        return result

    execution.bounded_repair_copy = copy
    if fault == "replace_fail":
        original_replace = os.replace

        def replace(source, destination):
            if Path(destination).is_relative_to(Path(holder["plan"]["run_root"]) / "candidates"):
                raise OSError("R3 injected candidate replace failure")
            return original_replace(source, destination)

        os.replace = replace
    if fault == "checkpoint_fail":
        original_atomic = runtime._atomic_runtime_json

        def atomic(path, payload):
            original_atomic(path, payload)
            if (
                "checkpoints/candidates" in str(path)
                and payload.get("validated") is True
            ):
                raise OSError("R3 injected checkpoint acknowledgement failure")

        runtime._atomic_runtime_json = atomic
    original_work = execution.run_repair_candidate_worker
    def tracked_work(request, **kwargs):
        metrics["audit"] = request["audit"]
        metrics["phase"] = request["phase"]
        before_sql, before_copy = metrics["sql_calls"], metrics["copy_calls"]
        result = original_work(request, **kwargs)
        metrics["completed_only"] = fault == "completed_only"
        if request["audit"] or fault == "completed_only":
            assert metrics["sql_calls"] == before_sql and metrics["copy_calls"] == before_copy
        return result
    execution.run_repair_candidate_worker = tracked_work
    if True:
        started = time.monotonic()
        try:
            execution.serve_repair_worker(prepare=prepare)
        finally:
            metrics.update(
                worker_pid=os.getpid(),
                elapsed_seconds=time.monotonic() - started,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            )
            if holder:
                _append(_evidence_path(holder["plan"], "r3-worker-metrics.jsonl"), metrics)


def _durable(plan, *, phase=None):
    """Only the completed current phase; discover paths from its existing manifests."""
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        repair_record_path,
    )
    root, lake = Path(plan["run_root"]), Path(plan["lake_root"])
    files = []
    if phase in (None, "indicator"):
        for task in indicators.indicator_replay_tasks(plan):
            marker = root / "inputs/indicator_replay" / task["task_id"] / "task.json"
            if not marker.exists():
                continue
            files.append(marker)
            for identity in json.loads(marker.read_text())["receipts"]:
                receipt = Path(identity["path"])
                proof = json.loads(receipt.read_text())
                files.append(receipt)
                files.extend(Path(i["path"]) for i in proof["outputs"].values())
    for unit in plan["units"]:
        asset = unit["asset_key"]
        family = "factor" if asset in ("raw_tushare_adj_factor", "silver_adj_factor") else "indicator" if asset in contract.indicator_repair_assets() else "price"
        if phase is not None and family != phase:
            continue
        for name in unit["target_paths"]:
            path = repair_record_path(root, Path(name), lake)
            if not path.exists():
                continue
            record = json.loads(path.read_text())
            if "record_hash" in record and not record.get("commit_pending"):
                files.append(path)
                if not record["no_op"]:
                    files.append(root / record["candidate_relative_path"])
    return {str(path): asdict(file_identity(path)) for path in set(files)}


def _complete_file_versions(plan):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        repair_record_path,
    )
    root, lake = Path(plan["run_root"]), Path(plan["lake_root"])
    files = [repair_record_path(root, Path(i["path"]), lake) for i in plan["target_preimages"]]
    files += [root / "candidates" / Path(i["path"]).relative_to(lake) for i in plan["target_preimages"]
              if (root / "candidates" / Path(i["path"]).relative_to(lake)).exists()]
    files += [root / "inputs/indicator_replay" / t["task_id"] / "task.json" for t in indicators.indicator_replay_tasks(plan)]
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in files}


def _assert_durable(snapshot):
    assert all(
        asdict(file_identity(Path(p))) == identity for p, identity in snapshot.items()
    )


def _coordinator():
    request = json.loads(sys.stdin.read())
    plan = json.loads(Path(request["plan_path"]).read_text())
    _roots(plan)
    root = Path(plan["run_root"])
    results, cancellations = [], []
    original_scan = execution.repair_storage_totals
    def scan(run_root):
        assert Path(run_root) == root
        _append(_evidence_path(plan, "r3-directory-scans.jsonl"), {"root": str(run_root)})
        return original_scan(run_root)
    execution.repair_storage_totals = scan
    for phase in PHASES:
        state = {"cancelled": False, "interrupted": False}
        audit = request.get("audit", False)

        def progress(update, phase=phase, audit=audit, state=state):
            _append(
                _evidence_path(plan, "r3-progress.jsonl"), {"phase": phase, "audit": audit, **update}
            )
            if (
                request.get("interrupt")
                and not state["interrupted"]
                and (
                    (phase == "indicator" and update.get("replay_completed", 0) >= 1)
                    or (
                        phase != "indicator" and update.get("visible_completed", 0) >= 1
                    )
                )
            ):
                if not state["cancelled"]:
                    state["cancel_requested_at"] = time.monotonic()
                state["cancelled"] = True

        args = {
            "plan_path": Path(request["plan_path"]),
            "expected_hash": plan["plan_hash"],
            "phase": phase,
            "worker_command": request["worker"],
            "progress": progress,
            "audit": audit,
        }
        if request.get("interrupt"):
            started = time.monotonic()
            with pytest.raises(FactorRepairError, match="canceled"):
                execution.execute_repair_candidates(
                    **args, cancel=lambda state=state: state["cancelled"]
                )
            checkpoint = json.loads((root / "checkpoint.json").read_text())
            assert checkpoint["status"] == "CANCELLED"
            snapshot = _durable(plan, phase=phase)
            assert snapshot
            assert time.monotonic() - state["cancel_requested_at"] <= 30
            state["interrupted"] = True
            cancellations.append(
                {
                    "phase": phase,
                    "elapsed_seconds": time.monotonic() - started,
                    "durable_files": len(snapshot),
                    "cancel_latency_seconds": time.monotonic()
                    - state["cancel_requested_at"],
                }
            )
        else:
            snapshot = {}  # Explicit boundary assertions belong to the calling test.
        result = execution.execute_repair_candidates(**args)
        assert result["completed"] == result["total"] and not result["sample"]
        assert result["all_chain_ready"] == (phase == "indicator" and not audit)
        _assert_durable(snapshot)
        results.append(result)
        print(
            json.dumps({"R3_phase_completed": phase, "audit": audit, "result": result}),
            flush=True,
        )
    assert results[-1]["replay_completed"] == results[-1]["replay_total"] == 325
    _append(
        _evidence_path(plan, "r3-full-chain.jsonl"),
        {"results": results, "cancellations": cancellations, "audit": request.get("audit", False),
         "completed_only": request.get("completed_only", False)},
    )


def _clone(plan):
    return freeze_stock_factor_repair(
        lake_root=Path(plan["lake_root"]),
        run_root=Path(plan["run_root"]).parent / ("run_id=" + str(uuid4())),
        scopes=[
            FactorRepairScope(
                **{**s, "factor_ranges": tuple(map(tuple, s["factor_ranges"]))}
            )
            for s in plan["scopes"]
        ],
        source_rows=plan["source_rows"],
        anchors=plan["anchors"],
        endpoints=[
            AssetRepairEndpoint(
                **{
                    k: tuple(v) if k in ("expected_dates", "context_times") else v
                    for k, v in e.items()
                }
            )
            for e in plan["endpoints"]
        ],
        input_stats=[
            (i["path"], i["size"], i["mtime_ns"]) for i in plan["source_fingerprints"]
        ],
        target_paths=[i["path"] for i in plan["target_preimages"]],
        units=plan["units"],
        partition_validation=plan["partition_validation"],
    )


def _run_chain(plan, tmp_path, *, interrupt=False, audit=False, completed_only=False):
    request = {
        "plan_path": str(Path(plan["run_root"]) / "plan.json"),
        "worker": _launcher(tmp_path, "_worker", "completed_only" if completed_only else "none"),
        "completed_only": completed_only,
        "interrupt": interrupt,
        "audit": audit,
    }
    subprocess.run(
        _launcher(tmp_path, "_coordinator"),
        input=json.dumps(request),
        text=True,
        check=True,
    )


def assert_full_chain_fixture_dependencies(plan):
    """Reject an incomplete synthetic inventory before starting the long chain."""
    root = Path(plan["lake_root"])
    identities = {i["path"]: i for i in plan["source_fingerprints"]}
    required = set(identities)
    for unit in plan["units"]:
        required.update(unit["target_paths"])
        required.update(unit.get("validation_paths", []))
        for profile in unit.get("calculation_windows", []):
            required.update(profile.get("source_inventory_paths", []))
        if unit["asset_key"] not in contract.indicator_repair_assets():
            continue
        freq = unit["calculation_windows"][0]["freq"]
        days = {d for p in unit["calculation_windows"] for d in p["target_dates"]}
        if freq is None:
            required.update(str(paths.gold_stock_daily_qfq_path(root, d)) for d in days)
        if unit["asset_key"] == "gold_stock_daily_trend_channel_state":
            required.update(
                str(
                    paths.gold_stock_daily_trend_channel_state_path(
                        root, max(d for d in unit["calendar_dates"] if d < day)
                    )
                )
                for day in days
            )
    required.update(
        (
            str(paths.silver_trade_calendar_path(root)),
            str(paths.silver_stock_lifecycle_path(root)),
        )
    )
    for task in indicators.indicator_replay_tasks(plan):
        profile = task["profile"]
        if "daily_seed" in profile:
            if profile["daily_seed"]["state_path"]:
                required.add(profile["daily_seed"]["state_path"])
        elif "macd_kdj" in task["asset_key"]:
            required.add(
                str(
                    paths.gold_stk_mins_qfq_macd_kdj_state_path(
                        root, profile["freq"], profile["previous_expected_date"]
                    )
                )
            )
    for name in sorted(required):
        if name not in identities:
            raise FactorRepairError("repair_fixture_dependency_not_frozen:" + name)
        if not Path(name).is_file():
            raise FileNotFoundError(name)
    return required


def test_fixture_state_carry_dependencies_pass_original_full_market_rules(
    indicator_plan, price_plan, tmp_path
):
    plan = indicator_plan
    root = Path(plan["lake_root"])
    required = assert_full_chain_fixture_dependencies(plan)
    assert len(plan["scopes"]) == 25
    assert len(plan["target_preimages"]) == len({p for unit in plan["units"] for p in unit["target_paths"]})
    assert len(plan["units"]) == 31 and len(plan["endpoints"]) == 725
    assert plan["source_rows"] == price_plan["source_rows"]
    assert {u["asset_key"]: sorted(u["target_paths"]) for u in plan["units"]} == {
        u["asset_key"]: sorted(u["target_paths"]) for u in price_plan["units"]
    }
    assert {
        (e["asset_key"], e["ts_code"]): e["end_time"] for e in plan["endpoints"]
    } == {
        (e["asset_key"], e["ts_code"]): e["end_time"] for e in price_plan["endpoints"]
    }
    unit = next(
        u
        for u in plan["units"]
        if u["asset_key"] == "gold_stock_daily_trend_channel_state"
    )
    carry_days = []
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        for day in sorted(
            {d for p in unit["calculation_windows"] for d in p["target_dates"]}
        ):
            price = paths.gold_stock_daily_qfq_path(root, day)
            rows = c.execute(
                f"SELECT ts_code,open,close,vol,amount FROM {read_parquet(price, hive_partitioning=False)} ORDER BY ts_code"
            ).fetchall()
            if len(rows) != 1:
                continue
            assert rows == [("000001.SZ", 5.0, 5.0, 100.0, 1000.0)]
            carry_days.append(day)
            assert str(price) in required
            assert str(price) not in {
                p for u in plan["units"] for p in u["target_paths"]
            }
            state = paths.gold_stock_daily_trend_channel_state_path(root, day)
            observed = c.execute(
                f"SELECT ts_code,observed_on_partition FROM {read_parquet(state, hive_partitioning=False)} ORDER BY ts_code"
            ).fetchall()
            assert len(observed) == 26
            assert [code for code, value in observed if value] == ["000001.SZ"]
        assert len(carry_days) == 18
        proof = indicators.audit_indicator_batch(
            c,
            plan,
            unit,
            [
                str(paths.gold_stock_daily_trend_channel_state_path(root, d))
                for d in carry_days
            ],
        )
        assert proof["checked_dates"] == 18
    print(
        "R3_fixture_dependencies",
        json.dumps(
            {
                "input_files": len(required),
                "target_files": len(plan["target_preimages"]),
                "carry_dates": len(carry_days),
            }
        ),
        flush=True,
    )


@pytest.mark.parametrize("invalid", ["missing", "unfrozen"])
def test_fixture_dependency_precheck_and_native_audit_reject_missing_inputs(
    indicator_plan, tmp_path, invalid
):
    plan = deepcopy(indicator_plan)
    root, run = Path(plan["lake_root"]), Path(plan["run_root"])
    price = paths.gold_stock_daily_qfq_path(root, "2023-05-31")
    target = paths.gold_stock_daily_trend_channel_state_path(root, "2023-05-31")
    unit = next(
        u
        for u in plan["units"]
        if u["asset_key"] == "gold_stock_daily_trend_channel_state"
    )
    before = file_identity(price)
    checkpoint = {str(p): file_identity(p) for p in run.rglob("*") if p.is_file()}
    held = price.with_suffix(".held")
    if invalid == "missing":
        os.replace(price, held)
    else:
        plan["source_fingerprints"] = [
            i for i in plan["source_fingerprints"] if i["path"] != str(price)
        ]
    try:
        error = FileNotFoundError if invalid == "missing" else FactorRepairError
        with pytest.raises(error):
            assert_full_chain_fixture_dependencies(plan)
        with (
            connect_configured_duckdb(
                RepairBudget().connection_settings(tmp_path),
                temp_policy="existing_no_spill",
            ) as c,
            pytest.raises(
                error, match=None if invalid == "missing" else "repair_input_not_frozen"
            ),
        ):
            indicators.audit_indicator_batch(c, plan, unit, [str(target)])
    finally:
        if held.exists():
            os.replace(held, price)
    assert file_identity(price) == before
    assert {
        str(p): file_identity(p) for p in run.rglob("*") if p.is_file()
    } == checkpoint
    assert not list(run.glob("candidates/**/*.parquet"))


def test_fixture_carry_day_rejects_wrong_retained_stock_observation(
    indicator_plan, tmp_path
):
    plan = indicator_plan
    root, run = Path(plan["lake_root"]), Path(plan["run_root"])
    target = paths.gold_stock_daily_trend_channel_state_path(root, "2023-05-31")
    before = file_identity(target)
    relative = target.relative_to(root).as_posix()
    output = run / "candidates" / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        samples._write(
            c,
            output,
            f"SELECT * REPLACE(false AS observed_on_partition) FROM {read_parquet(target, hive_partitioning=False)}",
        )
        pending = {
            str(target): {
                "plan_hash": plan["plan_hash"],
                "business_pending": True,
                "validated": False,
                "no_op": False,
                "target_relative_path": relative,
                "candidate_relative_path": "candidates/" + relative,
                "preimage_sha256": before.sha256,
                "candidate_sha256": file_identity(output).sha256,
            }
        }
        unit = next(
            u
            for u in plan["units"]
            if u["asset_key"] == "gold_stock_daily_trend_channel_state"
        )
        with pytest.raises(
            FactorRepairError, match="repair_trend_coverage_check_failed"
        ):
            indicators.audit_indicator_batch(
                c, plan, unit, [str(target)], pending=pending
            )
    assert file_identity(target) == before
    assert not list(run.glob("checkpoints/candidates/*.json"))


def test_full_25_stock_chain_cancel_resume_and_proof_audit(indicator_plan, tmp_path):
    """One calculation chain; cancellation and proof-only reruns share its run ID."""
    plan = indicator_plan
    assert len(plan["scopes"]) == 25 and len(plan["source_rows"]) == 2489
    assert len(plan["units"]) == 31 and len(plan["endpoints"]) == 725
    assert {s["repair_end_trade_date"] for s in plan["scopes"]} == {"2026-10-16"}
    assert len(indicators.indicator_replay_tasks(plan)) == 325
    assert_full_chain_fixture_dependencies(plan)
    print(json.dumps({"R3_isolated_start": True, "run_root": plan["run_root"],
        "input_files": len(plan["source_fingerprints"]),
        "target_files": len(plan["target_preimages"])}), flush=True)
    _run_chain(plan, tmp_path, interrupt=True)
    versions = _complete_file_versions(plan)
    _run_chain(plan, tmp_path, audit=True)
    assert _complete_file_versions(plan) == versions
    _run_chain(plan, tmp_path, completed_only=True)
    assert _complete_file_versions(plan) == versions
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
        RepairRuntime,
        use_repair_runtime,
    )
    with use_repair_runtime(RepairRuntime(plan, admitted=True)), connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as connection:
        root = Path(plan["lake_root"])
        selected = [paths.gold_stock_daily_qfq_path(root, "2026-06-29"),
                    paths.gold_stk_mins_qfq_path(root, 1, "688689.SH", "2026")]
        for target in selected:
            record = read_repair_candidate_record(plan, target)
            output = target if record["no_op"] else Path(plan["run_root"]) / record["candidate_relative_path"]
            date_filter = "trade_date=DATE '2026-06-29'" if target == selected[0] else "trade_time=TIMESTAMP '2026-06-29 09:30:00'"
            observed = connection.execute(f'SELECT open,high,low,close FROM {read_parquet(output,hive_partitioning=False)} WHERE ts_code=\'688689.SH\' AND {date_filter}').fetchone()
            assert observed == (7.5, 8.25, 6.75, 7.5)  # Literal 10/11/9/10 * 1.5 / 2.
    assert_full_chain_evidence(plan)



def test_completed_indicator_replay_keeps_receipts_and_task_marker(
    indicator_plan, tmp_path
):
    from .test_stock_adj_factor_history_repair_replay import samples as replay_samples

    plan = indicator_plan
    print(
        json.dumps(
            {
                "R3_fixture_inventory": True,
                "input_files": len(plan["source_fingerprints"]),
                "target_files": len(plan["target_preimages"]),
                "calendar_days": len(
                    next(
                        u
                        for u in plan["units"]
                        if u["asset_key"] == "gold_stock_daily_trend_channel"
                    )["calendar_dates"]
                ),
                "input_bytes": sum(i["size"] for i in plan["source_fingerprints"]),
            }
        ),
        flush=True,
    )
    task = replay_samples._task(plan)
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        replay_samples._prepare_price(c, plan, task)
        indicators.replay_indicator_task(c, plan, task)
        before = _durable(plan)
        indicators.replay_indicator_task(c, plan, task, audit=True)
        _assert_durable(before)


@pytest.mark.parametrize(
    "fault", ["copy_exit", "replace_fail", "fsync_fail", "checkpoint_fail"]
)
def test_worker_faults_preserve_source_and_owned_output_can_resume(
    price_plan, tmp_path, fault
):
    plan = price_plan
    target = Path(
        next(u for u in plan["units"] if u["asset_key"] == "raw_tushare_adj_factor")[
            "target_paths"
        ][0]
    )
    before = file_identity(target)
    args = {
        "plan_path": Path(plan["run_root"]) / "plan.json",
        "expected_hash": plan["plan_hash"],
        "phase": "factor",
        "selected_targets": [str(target)],
    }
    with pytest.raises(FactorRepairError, match="repair_worker_failed"):
        execution.execute_repair_candidates(
            **args, worker_command=_launcher(tmp_path, "_worker", fault)
        )
    assert file_identity(target) == before
    assert (
        json.loads((Path(plan["run_root"]) / "checkpoint.json").read_text())["status"]
        == "FAILED"
    )
    durable = _durable(plan) if fault == "checkpoint_fail" else {}
    result = execution.execute_repair_candidates(
        **args, worker_command=_launcher(tmp_path, "_worker")
    )
    assert result["completed"] == 1 and not result["all_chain_ready"]
    _assert_durable(durable)
    assert file_identity(target) == before
    read_repair_candidate_record(plan, target)


def test_bounded_inventory_admission_and_first_use_missing_file_rejection(
    freeze_case, tmp_path
):
    args, _ = freeze_case
    from orchestrator.defs import paths

    known = {name: (size, mtime) for name, size, mtime in args["input_stats"]}
    directory = paths.gold_stock_daily_qfq_path(
        args["lake_root"], "2026-10-13"
    ).parents[1]
    for file in directory.glob("trade_date=*/part-000.parquet"):
        st = file.stat()
        known[str(file)] = (st.st_size, st.st_mtime_ns)
    args["input_stats"] = [(name, *values) for name, values in sorted(known.items())]
    plan = freeze_stock_factor_repair(**args)
    inventory = {i["path"]: i for i in plan["source_fingerprints"]}
    for number in range(10000):
        if len(inventory) == 4096:
            break
        path = (
            Path(plan["lake_root"])
            / f"gold/quote/stk_mins_qfq/freq=1/ts_code={number + 100000:06}.SZ/year=2025/part-000.parquet"
        )
        if str(path) in inventory:
            continue
        inventory[str(path)] = {
            "path": str(path),
            "size": 4096,
            "mtime_ns": 1700000000000000000,
            "sha256": "0" * 64,
        }
    plan["source_fingerprints"] = list(inventory.values())
    plan.pop("plan_hash")
    plan["plan_hash"] = repair_hash(plan)
    path = Path(plan["run_root"]) / "plan.json"
    atomic_repair_json(path, plan)
    started = time.monotonic()
    updates = []
    loaded = execution.load_repair_plan(
        path,
        plan["plan_hash"],
        progress=lambda update: updates.append(
            {"seconds": time.monotonic() - started, **update}
        ),
    )
    load_seconds = time.monotonic() - started
    assert len(loaded["source_fingerprints"]) == 4096
    assert path.stat().st_size < contract.REPAIR_PLAN_MAX_BYTES
    # Descriptor-only pressure evidence must never be mistaken for executable input proof.
    assert not Path(loaded["source_fingerprints"][-1]["path"]).exists()
    assert updates[0]["seconds"] <= 30
    assert max(b["seconds"] - a["seconds"] for a, b in pairwise(updates)) <= 30
    verified = [u["verified_plan_paths"] for u in updates if "verified_plan_paths" in u]
    assert verified == sorted(verified) and verified[-1] == 4096
    assert updates[-1]["plan_validation_complete"] is True
    for timing in ("before_read", "during_paths"):
        cancel_updates, state = [], {"cancelled": timing == "before_read"}
        cancel_started = time.monotonic()

        def progress(
            update,
            cancel_updates=cancel_updates,
            cancel_started=cancel_started,
            state=state,
        ):
            cancel_updates.append(
                {"seconds": time.monotonic() - cancel_started, **update}
            )
            if update.get("verified_plan_paths", 0) >= 64 and not state["cancelled"]:
                state["cancelled"] = True
                state["requested_at"] = time.monotonic()

        before = _durable(plan)
        with pytest.raises(FactorRepairError, match="canceled"):
            execution.execute_repair_candidates(
                path,
                plan["plan_hash"],
                phase="factor",
                cancel=lambda state=state: state["cancelled"],
                progress=progress,
                worker_command=[
                    sys.executable,
                    "-c",
                    "raise AssertionError('must not launch')",
                ],
            )
        response = time.monotonic() - state.get("requested_at", cancel_started)
        assert response <= 30 and cancel_updates[0]["seconds"] <= 30
        assert cancel_updates[-1]["status"] == "CANCELLED"
        assert all(
            u["completed"] == 0 and u["total"] is None and not u["all_chain_ready"]
            for u in cancel_updates
        )
        assert not any(u.get("plan_validation_complete") for u in cancel_updates)
        _assert_durable(before)
        print(
            json.dumps(
                {
                    "R3_plan_cancel": timing,
                    "response_seconds": response,
                    "first_update_seconds": cancel_updates[0]["seconds"],
                    "verified_plan_paths": max(
                        u.get("verified_plan_paths", 0) for u in cancel_updates
                    ),
                }
            ),
            flush=True,
        )
    refusal_started = time.monotonic()
    target = next(u for u in plan["units"] if u["asset_key"] == "raw_tushare_adj_factor")["target_paths"][0]
    Path(target).unlink()  # An actually used input must fail at first use.
    with pytest.raises(FactorRepairError, match="repair_worker_failed"):
        execution.execute_repair_candidates(path, plan["plan_hash"], phase="factor", selected_targets=[target],
            worker_command=_launcher(tmp_path, "_worker"))
    assert not list(Path(plan["run_root"]).glob("candidates/**/*.parquet"))

    print(
        json.dumps(
            {
                "R3_inventory_structure": 4096,
                "encoded_bytes": path.stat().st_size,
                "load_seconds": load_seconds,
                "missing_input_refusal_seconds": time.monotonic() - refusal_started,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            }
        ),
        flush=True,
    )


def test_same_plan_concurrent_writer_is_rejected_before_worker(price_plan):
    import fcntl

    plan = price_plan
    path = Path(plan["run_root"]) / "plan.json"
    before = _durable(plan)
    with path.open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(FactorRepairError, match="repair_candidate_writer_busy"):
            execution.execute_repair_candidates(
                path,
                plan["plan_hash"],
                phase="factor",
                worker_command=[
                    sys.executable,
                    "-c",
                    "raise AssertionError('worker must not start')",
                ],
            )
    _assert_durable(before)


def _single_phase():
    request = json.loads(sys.stdin.read())
    plan = json.loads(Path(request["plan_path"]).read_text())
    _roots(plan)
    execution.execute_repair_candidates(
        Path(request["plan_path"]),
        plan["plan_hash"],
        phase="factor",
        selected_targets=[request["target"]],
        worker_command=request["worker"],
    )


def _alive(pid):
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGKILL])
def test_coordinator_termination_does_not_leave_a_worker_running(
    price_plan, tmp_path, termination
):
    plan = price_plan
    target = next(
        u for u in plan["units"] if u["asset_key"] == "raw_tushare_adj_factor"
    )["target_paths"][0]
    original = file_identity(Path(target))
    request = {
        "plan_path": str(Path(plan["run_root"]) / "plan.json"),
        "target": target,
        "worker": _launcher(tmp_path, "_worker", "hold"),
    }
    started = _evidence_path(plan, "r3-worker-started.json")
    worker_pid = None
    child_pid = None
    process = subprocess.Popen(
        _launcher(tmp_path, "_single_phase"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        process.stdin.write(json.dumps(request))
        process.stdin.close()
        deadline = time.monotonic() + 20
        while (
            not started.exists()
            and time.monotonic() < deadline
            and process.poll() is None
        ):
            time.sleep(0.05)
        assert started.exists()
        worker = json.loads(started.read_text())
        worker_pid, child_pid = worker["pid"], worker["child_pid"]
        assert _alive(worker_pid) and _alive(child_pid)
        if termination == signal.SIGKILL:
            os.kill(worker_pid, signal.SIGSTOP)
        terminated = time.monotonic()
        process.send_signal(termination)
        process.wait(timeout=10)
        if termination == signal.SIGKILL:
            assert _alive(worker_pid)
            with (
                Path(request["plan_path"]).open("rb") as probe,
                pytest.raises(BlockingIOError),
            ):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.kill(worker_pid, signal.SIGCONT)
        deadline = time.monotonic() + 10
        while _alive(worker_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(worker_pid), (
            f"coordinator exited but worker {worker_pid} still running"
        )
        assert not _alive(child_pid)
        latency = time.monotonic() - terminated
        assert latency < 10
        if termination == signal.SIGTERM:
            assert (
                json.loads((Path(plan["run_root"]) / "checkpoint.json").read_text())[
                    "status"
                ]
                == "CANCELLED"
            )
        print(
            json.dumps(
                {"R3_termination": int(termination), "latency_seconds": latency}
            ),
            flush=True,
        )
        result = execution.execute_repair_candidates(
            Path(request["plan_path"]),
            plan["plan_hash"],
            phase="factor",
            selected_targets=[target],
            worker_command=_launcher(tmp_path, "_worker"),
        )
        assert result["completed"] == 1
        assert file_identity(Path(target)) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if worker_pid is not None and (
            _alive(worker_pid) or (child_pid is not None and _alive(child_pid))
        ):
            os.killpg(worker_pid, signal.SIGKILL)
        process.stdout.close()
        process.stderr.close()


def _guard_probe():
    request = json.loads(sys.stdin.read())
    if request.get("await_parent_exit"):
        Path(request["ready_path"]).write_text(str(os.getpid()))
        while os.getppid() == request["coordinator_pid"]:
            time.sleep(0.01)
    with execution.repair_worker_parent_guard(request):
        Path(request["output_path"]).write_text("guard accepted")


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "missing_pid",
        "missing_fd",
        "bool_pid",
        "bool_fd",
        "wrong_pid",
        "wrong_file",
        "same_file_uninherited",
        "unlocked",
        "process_group",
    ],
)
def test_worker_parent_protocol_rejects_invalid_requests_before_writes(
    tmp_path, invalid
):
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    output = tmp_path / "guard-output"
    other = tmp_path / "other.json"
    other.write_text("{}")
    with (
        plan.open("rb") as lock,
        other.open("rb") as alternate,
        plan.open("rb") as uninherited,
    ):
        if invalid != "unlocked":
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = {
            "plan_path": str(plan),
            "coordinator_pid": os.getpid(),
            "plan_lock_fd": lock.fileno(),
            "output_path": str(output),
        }
        if invalid in ("missing_pid", "missing_fd"):
            request.pop(
                "coordinator_pid" if invalid == "missing_pid" else "plan_lock_fd"
            )
        if invalid == "bool_pid":
            request["coordinator_pid"] = True
        if invalid == "bool_fd":
            request["plan_lock_fd"] = True
        if invalid == "wrong_pid":
            request["coordinator_pid"] += 1
        if invalid == "wrong_file":
            request["plan_lock_fd"] = alternate.fileno()
        if invalid == "same_file_uninherited":
            request["plan_lock_fd"] = uninherited.fileno()
        result = subprocess.run(
            _launcher(tmp_path, "_guard_probe"),
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
            pass_fds=(lock.fileno(), alternate.fileno(), uninherited.fileno()),
            start_new_session=invalid != "process_group",
        )
        assert (result.returncode == 0) == (invalid is None), result.stderr
        assert output.exists() == (invalid is None)
        if invalid != "unlocked":
            with plan.open("rb") as probe, pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _guard_launch_and_exit():
    request = json.loads(sys.stdin.read())
    with Path(request["plan_path"]).open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request.update(coordinator_pid=os.getpid(), plan_lock_fd=lock.fileno())
        child = subprocess.Popen(
            request.pop("worker"),
            stdin=subprocess.PIPE,
            start_new_session=True,
            pass_fds=(lock.fileno(),),
        )
        child.stdin.write(json.dumps(request).encode())
        child.stdin.close()
        deadline = time.monotonic() + 10
        while not Path(request["ready_path"]).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert Path(request["ready_path"]).exists()
        os._exit(23)


def test_worker_parent_exit_before_guard_cannot_start_business_writes(tmp_path):
    plan, ready, output = (tmp_path / name for name in ("plan.json", "ready", "output"))
    plan.write_text("{}")
    request = {
        "plan_path": str(plan),
        "ready_path": str(ready),
        "output_path": str(output),
        "await_parent_exit": True,
        "worker": _launcher(tmp_path, "_guard_probe"),
    }
    result = subprocess.run(
        _launcher(tmp_path, "_guard_launch_and_exit"),
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 23
    pid = int(ready.read_text())
    assert not _alive(pid) and not output.exists()
    assert "repair_worker_parent_invalid" in result.stderr
    with plan.open("rb") as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_storage_scan_tolerates_disappearing_atomic_json_but_counts_stable_files(
    tmp_path, monkeypatch
):
    root = tmp_path / "run"
    (root / "candidates").mkdir(parents=True)
    (root / "checkpoints").mkdir()
    candidate = root / "candidates/stable.parquet"
    candidate.write_bytes(b"12345")
    transient = root / "checkpoints/checkpoint.json.tmp"
    transient.write_bytes(b"123")
    walk = execution.os.walk
    moved = []

    def raced_walk(*args, **kwargs):
        for directory, dirs, files in walk(*args, **kwargs):
            if transient.name in files:
                os.replace(transient, transient.with_suffix(""))
                moved.append(True)
            yield directory, dirs, files

    monkeypatch.setattr(execution.os, "walk", raced_walk)
    totals = execution.repair_storage_totals(root)
    assert moved and totals["candidate_bytes"] == 5
    assert totals["staging_bytes"] == 5
    assert execution.repair_storage_totals(root)["staging_bytes"] == 8


@pytest.mark.parametrize(
    "failure", ["symlink", "permission", "candidate_quota", "spill_quota"]
)
def test_storage_scan_still_rejects_other_errors_and_stable_over_budget_files(
    tmp_path, monkeypatch, failure
):
    root = tmp_path / "run"
    (root / "candidates").mkdir(parents=True)
    (root / "temp").mkdir()
    candidate = root / "candidates/stable.parquet"
    candidate.write_bytes(b"12345")
    if failure == "symlink":
        (root / "candidates/link").symlink_to(candidate)
        with pytest.raises(FactorRepairError, match="repair_path_symlink"):
            execution.repair_storage_totals(root)
    elif failure == "permission":
        lstat = Path.lstat

        def denied(path, *args, **kwargs):
            if path == candidate:
                raise PermissionError("R3 isolated denial")
            return lstat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "lstat", denied)
        with pytest.raises(PermissionError, match="isolated denial"):
            execution.repair_storage_totals(root)
    else:
        output = candidate if failure == "candidate_quota" else root / "temp/spill"
        maximum = (
            RepairBudget().max_candidate_bytes
            if failure == "candidate_quota"
            else RepairBudget().max_spill
        )
        with output.open("wb") as handle:
            handle.truncate(maximum + 1)
        with pytest.raises(FactorRepairError, match="repair_storage_budget_exceeded"):
            execution.check_repair_storage(root)


def test_storage_scan_counts_all_categories(tmp_path):
    root = tmp_path / "run"
    for directory, size in (
        ("candidates", 11),
        ("temp", 13),
        ("inputs", 17),
        ("checkpoints", 19),
    ):
        output = root / directory / "nested" / "stable"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"x" * size)
    assert execution.repair_storage_totals(root) == {
        "candidate_bytes": 11,
        "spill_bytes": 13,
        "input_bytes": 17,
        "staging_bytes": 60,
    }


def test_storage_scan_rejects_real_unreadable_directory(tmp_path):
    blocked = tmp_path / "candidates" / "blocked"
    blocked.mkdir(parents=True)
    (blocked / "stable.parquet").write_bytes(b"x" * 1024)
    try:
        blocked.chmod(0)
        with pytest.raises(PermissionError):
            list(blocked.iterdir())
        with pytest.raises(PermissionError):
            execution.repair_storage_totals(tmp_path)
    finally:
        blocked.chmod(0o700)
    assert execution.repair_storage_totals(tmp_path)["candidate_bytes"] == 1024


@pytest.mark.parametrize(
    "error",
    [
        OSError(5, "isolated traversal I/O"),
        FileNotFoundError("isolated directory vanished"),
    ],
)
def test_storage_scan_propagates_directory_enumeration_errors(
    tmp_path, monkeypatch, error
):
    blocked = tmp_path / "candidates"
    blocked.mkdir()
    scandir = os.scandir

    def failed_scandir(path):
        if Path(path) == blocked:
            raise error
        return scandir(path)

    monkeypatch.setattr(os, "scandir", failed_scandir)
    with pytest.raises(type(error)) as raised:
        execution.repair_storage_totals(tmp_path)
    assert raised.value is error


@pytest.mark.parametrize("when", ["startup", "final"])
def test_directory_permission_failure_rejects_required_census(tmp_path, when):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
        RepairStorageLedger,
    )
    blocked = tmp_path / "candidates/blocked"
    blocked.mkdir(parents=True)
    (blocked / "stable").write_bytes(b"x" * 1024)
    ledger = None if when == "startup" else RepairStorageLedger(tmp_path, scan=execution.repair_storage_totals)
    try:
        blocked.chmod(0)
        with pytest.raises(PermissionError):
            if ledger is None:
                RepairStorageLedger(tmp_path, scan=execution.repair_storage_totals)
            else:
                ledger.reconcile()
    finally:
        blocked.chmod(0o700)


def assert_full_chain_evidence(plan):
    """Read complete isolated run evidence; measurements never grant formal readiness."""
    progress = [
        json.loads(line)
        for line in (_evidence_path(plan, "r3-progress.jsonl")).read_text().splitlines()
    ]
    metrics = [
        json.loads(line)
        for line in (_evidence_path(plan, "r3-worker-metrics.jsonl")).read_text().splitlines()
    ]
    chains = [
        json.loads(line)
        for line in (_evidence_path(plan, "r3-full-chain.jsonl")).read_text().splitlines()
    ]
    budget = RepairBudget()
    assert metrics and progress and chains
    assert sum(not c["audit"] and not c["completed_only"] for c in chains) == 1
    assert sum(c["audit"] for c in chains) == 1 and sum(c["completed_only"] for c in chains) == 1
    scans = _evidence_path(plan, "r3-directory-scans.jsonl").read_text().splitlines()
    assert len(scans) == 2  # One initial census and one closeout, both of this run only.
    for chain in chains:
        assert len(chain["results"]) == 3
        assert [item["phase"] for item in chain["results"]] == list(PHASES)
        assert sum(item["total"] for item in chain["results"]) == len(
            plan["target_preimages"]
        )
        assert all(
            item["completed"] == item["total"]
            and not item["sample"]
            and not item["all_chain_ready"]
            for item in chain["results"]
        )
        assert chain["results"][-1]["replay_completed"] == 325
        for cancellation in chain["cancellations"]:
            assert cancellation["durable_files"] > 0
            assert cancellation["cancel_latency_seconds"] <= 30
    gaps = active_progress_gaps(progress)
    for previous, current in pairwise(progress):
        if (previous["phase"], previous["audit"]) == (
            current["phase"],
            current["audit"],
        ) and current["elapsed_seconds"] >= previous["elapsed_seconds"]:
            assert current["completed"] >= previous["completed"]
            assert current["replay_completed"] >= previous["replay_completed"]
    assert max(gaps, default=0) <= 30
    peak_rss = max(item["peak_rss_bytes"] for item in progress)
    peak_staging = max(item.get("staging_bytes", 0) for item in progress)
    assert peak_rss <= budget.max_rss
    assert (
        max(item.get("candidate_bytes", 0) for item in progress)
        <= budget.max_candidate_bytes
    )
    assert max(item.get("spill_bytes", 0) for item in progress) <= budget.max_spill
    assert all(item["hash_calls"] > 0 for item in metrics)
    assert all(item["copy_calls"] == item["sql_calls"] == 0 for item in metrics if item.get("audit"))
    assert len(metrics) <= 12  # Three phases: interrupted+resumed, proof audit, empty resume.
    summary = {
        "plan_hash": plan["plan_hash"],
        "identity_profile": "synthetic",
        "formal_operations": 0,
        "chain_count": len(chains),
        "directory_scans": len(scans),
        "worker_count": len(metrics),
        "peak_rss_bytes": peak_rss,
        "peak_staging_bytes": peak_staging,
        "max_progress_gap_seconds": max(gaps, default=0),
        "final_storage": {k: chains[-1]["results"][-1][k] for k in ("candidate_bytes", "spill_bytes", "input_bytes", "staging_bytes")},
        "phase_results": chains,
        "worker_totals": {
            key: sum(item[key] for item in metrics)
            for key in (
                "sql_calls",
                "copy_calls",
                "sql_seconds",
                "hash_calls",
                "hash_bytes",
                "hash_seconds",
                "storage_calls",
                "storage_seconds",
                "fsync_calls",
                "fsync_seconds",
            )
        },
    }
    atomic_repair_json(_evidence_path(plan, "r3-isolated-acceptance.json"), summary)
    return summary


@pytest.mark.parametrize(
    "invalid", ["outside_root", "symlink", "duplicate", "bad_hash"]
)
def test_loading_callbacks_preserve_invalid_plan_rejections(
    price_plan, tmp_path, invalid
):
    plan = price_plan
    path = Path(plan["run_root"]) / "plan.json"
    descriptor = {
        "path": str(tmp_path / "outside.parquet"),
        "size": 1,
        "mtime_ns": 1,
        "sha256": "0" * 64,
    }
    if invalid == "outside_root":
        plan["source_fingerprints"].append(descriptor)
    elif invalid == "symlink":
        link = Path(plan["lake_root"]) / "extra.parquet"
        link.symlink_to(Path(plan["source_fingerprints"][0]["path"]))
        descriptor["path"] = str(link)
        plan["source_fingerprints"].append(descriptor)
    elif invalid == "duplicate":
        plan["source_fingerprints"].append(dict(plan["source_fingerprints"][0]))
    plan["plan_hash"] = repair_hash({k: v for k, v in plan.items() if k != "plan_hash"})
    atomic_repair_json(path, plan)
    expected = "bad" if invalid == "bad_hash" else plan["plan_hash"]
    reason = {
        "outside_root": "repair_input_not_approved",
        "symlink": "repair_path_symlink",
        "duplicate": "repair_input_inventory_invalid",
        "bad_hash": "repair_plan_invalid",
    }[invalid]
    updates = []
    with pytest.raises(FactorRepairError, match=reason):
        execution.execute_repair_candidates(
            path,
            expected,
            phase="factor",
            progress=updates.append,
            worker_command=[
                sys.executable,
                "-c",
                "raise AssertionError('must not launch')",
            ],
        )
    assert updates and updates[-1]["status"] == "FAILED"
    assert not any(u.get("plan_validation_complete") for u in updates)
    assert not list(Path(plan["run_root"]).glob("candidates/**/*.parquet"))


def test_pre_cancelled_loading_never_opens_untrusted_plan(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("pre-cancelled plan must not be read")

    monkeypatch.setattr(execution, "check_repair_path", forbidden)
    updates = []
    with pytest.raises(FactorRepairError, match="canceled"):
        execution.execute_repair_candidates(
            tmp_path / "missing-plan.json",
            "untrusted",
            phase="factor",
            cancel=lambda: True,
            progress=updates.append,
        )
    assert [u["status"] for u in updates] == ["BUILDING", "CANCELLED"]
    assert all(u["completed"] == 0 and u["total"] is None for u in updates)
    assert not list(tmp_path.iterdir())


def active_progress_gaps(progress):
    """Only an active invocation owes updates; terminal readback is a separate activity."""
    return [
        current["updated_at"] - previous["updated_at"]
        for previous, current in pairwise(progress)
        if previous["status"] == "BUILDING"
        and (previous["phase"], previous["audit"])
        == (current["phase"], current["audit"])
        and current["elapsed_seconds"] >= previous["elapsed_seconds"]
    ]


def test_progress_deadline_includes_active_terminal_update_but_excludes_idle_readback():
    start = {
        "phase": "factor",
        "audit": False,
        "status": "BUILDING",
        "updated_at": 0,
        "elapsed_seconds": 0,
    }
    completed = {
        **start,
        "status": "FACTOR_CANDIDATES_VERIFIED",
        "updated_at": 5,
        "elapsed_seconds": 5,
    }
    next_phase = {**start, "phase": "price", "updated_at": 105}
    cancelled = {
        **next_phase,
        "status": "CANCELLED",
        "updated_at": 110,
        "elapsed_seconds": 5,
    }
    resumed = {**next_phase, "updated_at": 210}
    assert active_progress_gaps([start, completed, next_phase, cancelled, resumed]) == [
        5,
        5,
    ]
    overdue = {**start, "updated_at": 31, "elapsed_seconds": 31}
    assert max(active_progress_gaps([start, overdue])) > 30
    assert max(active_progress_gaps([start, {**overdue, "status": "FAILED"}])) > 30


def test_storage_check_scans_once_and_reuses_one_complete_measurement(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    totals = {
        "candidate_bytes": 5,
        "spill_bytes": 3,
        "staging_bytes": 11,
        "input_bytes": 3,
    }
    scans = []

    def measure(root):
        scans.append(root)
        assert len(scans) == 1
        return dict(totals)

    monkeypatch.setattr(execution, "repair_storage_totals", measure)
    monkeypatch.setattr(
        "shutil.disk_usage", lambda _path: SimpleNamespace(free=20 * 1024**3)
    )
    assert (
        execution.check_repair_storage(tmp_path, plan={"space_required_bytes": 19})
        == totals
    )
    assert scans == [tmp_path]


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "utf-8-sig"])
def test_loading_retains_original_utf8_json_encoding_rejections(price_plan, encoding):
    plan = price_plan
    path = Path(plan["run_root"]) / "plan.json"
    path.write_bytes(path.read_text().encode(encoding))
    updates = []
    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        execution.execute_repair_candidates(
            path, plan["plan_hash"], phase="factor", progress=updates.append
        )
    assert updates[-1]["status"] == "FAILED"
    assert not any(u.get("plan_validation_complete") for u in updates)
    assert not list(Path(plan["run_root"]).glob("candidates/**/*.parquet"))


def test_slow_worker_launch_and_storage_delay_keep_actual_emit_deadline(
    price_plan, tmp_path, monkeypatch
):
    plan = price_plan
    root = Path(plan["run_root"])
    target = next(
        u for u in plan["units"] if u["asset_key"] == "raw_tushare_adj_factor"
    )["target_paths"][0]
    before = file_identity(Path(target))
    pid_file = tmp_path / "slow-worker.pid"
    worker = tmp_path / "slow-worker.py"
    worker.write_text(
        "import json,os,sys,time\n"
        "from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution "
        "import repair_worker_parent_guard\n"
        "request=json.loads(sys.stdin.readline())\n"
        "with repair_worker_parent_guard(request):\n"
        f"    open({str(pid_file)!r},'w').write(str(os.getpid()))\n"
        "    time.sleep(60)\n"
    )
    original_popen = subprocess.Popen
    original_storage = execution.check_repair_storage
    launch_started = []
    delayed_scans = []

    def slow_launch(*args, **kwargs):
        if args[0] == [sys.executable, "-B", str(worker)]:
            launch_started.append(time.monotonic())
            time.sleep(6)
        return original_popen(*args, **kwargs)

    def delayed_storage(*args, **kwargs):
        if (
            launch_started
            and not delayed_scans
            and time.monotonic() - launch_started[0] >= 23
        ):
            delayed_scans.append(True)
            time.sleep(4)
        return original_storage(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", slow_launch)
    monkeypatch.setattr(execution, "check_repair_storage", delayed_storage)
    updates = []
    with pytest.raises(FactorRepairError, match="canceled"):
        execution.execute_repair_candidates(
            root / "plan.json",
            plan["plan_hash"],
            phase="factor",
            selected_targets=[target],
            worker_command=[sys.executable, "-B", str(worker)],
            progress=lambda update: updates.append({**update, "audit": False}),
            cancel=lambda: (
                bool(launch_started) and time.monotonic() - launch_started[0] >= 37
            ),
        )
    assert launch_started and not delayed_scans and pid_file.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
    gaps = active_progress_gaps(updates)
    assert 25 <= max(gaps) <= 30
    assert updates[-1]["status"] == "CANCELLED"
    assert all(u["completed"] == u.get("visible_completed", 0) == 0 for u in updates)
    assert all(
        u.get("worker_completed", 0) == u["replay_completed"] == 0 for u in updates
    )
    assert RepairBudget().progress_interval == 30
    assert file_identity(Path(target)) == before
    assert not list(root.glob("candidates/**/*.parquet"))
    print(
        "R3_slow_worker_progress",
        json.dumps(
            {
                "max_gap": max(gaps),
                "updates": len(updates),
                "launch_delay_seconds": 6,
                "scan_delay_seconds": 4,
                "completed": 0,
            }
        ),
        flush=True,
    )
