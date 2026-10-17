"""Sequential, resumable factor/price/indicator candidate workers. No formal writer or Dagster instance."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import resource
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from pathlib import Path

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    REPAIR_PLAN_MAX_BYTES,
    FactorRepairError,
    RepairBudget,
    check_repair_cancel,
    check_repair_path,
    file_identity,
    indicator_repair_assets,
    repair_hash,
    repair_implementation_files,
    validate_repair_plan,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    PRICE_REPAIR_ASSETS,
    build_repair_target_candidate,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
    RepairRuntime,
    RepairStorageLedger,
    current_repair_runtime,
    runtime_storage,
    use_repair_runtime,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
    write_repair_json as atomic_repair_json,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb


def load_repair_plan(path: Path, expected_hash: str, *, cancel=None, progress=None, admission=None) -> dict:
    """Validate the same immutable contract, with bounded read/path checkpoints."""
    last_emit = time.monotonic()
    def emit(activity, **data):
        nonlocal last_emit
        last_emit = time.monotonic()
        if progress:
            progress({"activity": activity, "plan_validation_complete": False, **data})
        check_repair_cancel(cancel)

    emit("冻结计划读取", plan_bytes_read=0, verified_plan_paths=0)
    path = check_repair_path(path)
    if path.stat().st_size > REPAIR_PLAN_MAX_BYTES:
        raise FactorRepairError("repair_plan_size_exceeded")
    total_bytes = path.stat().st_size
    encoded = bytearray()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            check_repair_cancel(cancel)
            encoded.extend(chunk)
            if len(encoded) > REPAIR_PLAN_MAX_BYTES:
                raise FactorRepairError("repair_plan_size_exceeded")
            if len(encoded) % (64 * 1024 * 1024) == 0 or time.monotonic() - last_emit >= RepairBudget().progress_interval * 5 / 6:
                emit("冻结计划读取", plan_bytes_read=len(encoded), total_plan_bytes=total_bytes)
    emit("冻结计划解析", plan_bytes_read=len(encoded), total_plan_bytes=total_bytes)
    plan = json.loads(encoded.decode("utf-8"))
    if admission is not None:
        admission["plan_bytes_sha256"] = hashlib.sha256(encoded).hexdigest()
    del encoded
    emit("冻结计划合同校验", plan_bytes_read=total_bytes, total_plan_bytes=total_bytes)
    validate_repair_plan(plan, expected_hash)
    emit("冻结计划实现指纹校验", total_plan_paths=len(plan["source_fingerprints"]), verified_plan_paths=0)
    if path != Path(plan["run_root"]) / "plan.json":
        raise FactorRepairError("repair_plan_path_invalid")
    implementations = {i["path"] for i in plan["implementation_fingerprints"]}
    if implementations != {str(p) for p in repair_implementation_files()} or len(implementations) != len(plan["implementation_fingerprints"]):
        raise FactorRepairError("repair_implementation_not_frozen")
    for identity in plan["implementation_fingerprints"]:
        check_repair_cancel(cancel)
        if asdict(file_identity(Path(identity["path"]), cancel=cancel)) != identity:
            raise FactorRepairError("repair_implementation_drift")
    targets = [p for unit in plan["units"] for p in unit["target_paths"]]
    if len(set(targets)) != len(targets) or set(targets) != {i["path"] for i in plan["target_preimages"]}:
        raise FactorRepairError("repair_target_ownership_invalid")
    if len({i["path"] for i in plan["source_fingerprints"]}) != len(plan["source_fingerprints"]):
        raise FactorRepairError("repair_input_inventory_invalid")
    if len({a["ts_code"] for a in plan["anchors"]}) != 25:
        raise FactorRepairError("repair_anchors_incomplete")
    anchors = {a["ts_code"]: a for a in plan["anchors"]}
    for scope in plan["scopes"]:
        if scope["ts_code"] not in anchors or anchors[scope["ts_code"]]["trade_date"] != scope["as_of_trade_date"]:
            raise FactorRepairError("repair_anchor_invalid")
    lake_root = Path(plan["lake_root"])
    for number, identity in enumerate(plan["source_fingerprints"], 1):
        check_repair_cancel(cancel)
        if not check_repair_path(Path(identity["path"])).is_relative_to(lake_root):
            raise FactorRepairError("repair_input_not_approved")
        if number % 64 == 0 or number == len(plan["source_fingerprints"]) or time.monotonic() - last_emit >= RepairBudget().progress_interval * 5 / 6:
            emit("冻结计划路径归属校验", verified_plan_paths=number,
                total_plan_paths=len(plan["source_fingerprints"]), current_target=identity["path"])
    emit("冻结计划库存校验", verified_plan_paths=len(plan["source_fingerprints"]), total_plan_paths=len(plan["source_fingerprints"]))
    from orchestrator.defs import paths
    days = {r["trade_date"] for r in plan["source_rows"]}
    for asset, helper in (("raw_tushare_adj_factor", paths.raw_adj_factor_path),
                          ("silver_adj_factor", paths.silver_adj_factor_path)):
        expected = {str(helper(Path(plan["lake_root"]), f"{d[:4]}-{d[4:6]}-{d[6:]}")) for d in days}
        if expected != set(next(u for u in plan["units"] if u["asset_key"] == asset)["target_paths"]):
            raise FactorRepairError("repair_factor_inventory_incomplete")
    daily = next(u for u in plan["units"] if u["asset_key"] == "gold_stock_daily_qfq")
    inventory = set(daily["calculation_windows"][0]["source_inventory_paths"])
    cutoff = max(s["repair_end_trade_date"] for s in plan["scopes"])
    directory = paths.silver_stock_daily_path(Path(plan["lake_root"]),cutoff).parents[1]
    current = {i["path"] for i in plan["source_fingerprints"] if Path(i["path"]).parent.parent == directory}
    if current != inventory or any(set(p["source_inventory_paths"]) != inventory for p in daily["calculation_windows"]):
        raise FactorRepairError("repair_daily_source_inventory_drift")
    check_repair_cancel(cancel)
    if progress:
        progress({"activity": "冻结计划完整校验通过", "plan_validation_complete": True,
            "verified_plan_paths": len(plan["source_fingerprints"]), "total_plan_paths": len(plan["source_fingerprints"])})
    check_repair_cancel(cancel)
    return plan


def repair_candidate_work(plan, phase: str, *, selected_targets=None):
    if phase not in ("factor", "price", "indicator"):
        raise FactorRepairError("repair_phase_not_supported")
    order=PRICE_REPAIR_ASSETS[:2] if phase=='factor' else PRICE_REPAIR_ASSETS[2:] if phase=='price' else indicator_repair_assets()
    assets = set(order)
    work = [(index, path) for index, unit in enumerate(plan["units"])
            if unit["asset_key"] in assets for path in sorted(unit["target_paths"])]
    work.sort(key=lambda item: (order.index(plan["units"][item[0]]["asset_key"]), item[1]))
    if selected_targets is not None:
        selected = tuple(selected_targets)
        if not selected or len(set(selected)) != len(selected) or set(selected) - {p for _, p in work}:
            raise FactorRepairError("repair_sample_not_frozen")
        work = [w for w in work if w[1] in selected]
    if not work:
        raise FactorRepairError("repair_phase_empty")
    return work


def repair_candidate_batches(work):
    """Group one asset/month or asset/year, at most 64 full-file merges per logical batch."""
    groups = {}
    for index, target in work:
        coordinate = Path(target).parent.name
        coordinate = coordinate.removeprefix("trade_date=")[:7] if coordinate.startswith("trade_date=") else coordinate
        groups.setdefault((index, coordinate), []).append(target)
    return [(index, targets[start:start+64]) for (index, _), targets in groups.items()
            for start in range(0, len(targets), 64)]


def repair_storage_totals(root: Path) -> dict:
    import stat
    counts = {"candidate_bytes":0,"spill_bytes":0,"input_bytes":0,"staging_bytes":0}
    def fail_scan(error):
        raise error
    for directory,dirs,files in os.walk(check_repair_path(root),followlinks=False,onerror=fail_scan):
        for name in dirs + files:
            path = Path(directory)/name
            try:
                st = path.lstat()
            except FileNotFoundError:
                # A worker may atomically rename a temporary file after enumeration.
                continue
            if stat.S_ISLNK(st.st_mode):
                raise FactorRepairError("repair_path_symlink")
            if not stat.S_ISREG(st.st_mode):
                continue
            runtime = current_repair_runtime()
            if runtime is not None and runtime.admitted and runtime.root == root and not runtime.owns_artifact(path):
                raise FactorRepairError("repair_unowned_artifact")
            counts["staging_bytes"] += st.st_size
            for label,sub in (("candidate_bytes","candidates"),("spill_bytes","temp"),("input_bytes","inputs")):
                if path.is_relative_to(root/sub):
                    counts[label] += st.st_size
    return counts


def check_repair_storage(root: Path, *, plan=None, reserve_bytes=0) -> dict:
    ledger = runtime_storage(root)
    if ledger is None:
        ledger = RepairStorageLedger(root, scan=repair_storage_totals, plan=plan)
        runtime = current_repair_runtime()
        if runtime is not None:
            runtime.storage = ledger
    return ledger.check(reserve_bytes=reserve_bytes)


def bounded_repair_copy(connection, query, root, output, *, candidate=False, reserve_bytes=0):
    """Reserve once and settle actual bytes; no recursive scan around COPY."""
    from orchestrator.defs.duckdb_sql import copy_query_to_parquet
    ledger = runtime_storage(root)
    if ledger is None:
        runtime = current_repair_runtime()
        ledger = RepairStorageLedger(root, scan=repair_storage_totals, plan=runtime.plan if runtime else None)
        if runtime is not None:
            runtime.storage = ledger
    remaining = RepairBudget().max_candidate_bytes - ledger.counts["candidate_bytes"]
    if candidate and (remaining <= 0 or reserve_bytes > remaining):
        raise FactorRepairError("repair_storage_budget_exceeded")
    original = resource.getrlimit(resource.RLIMIT_FSIZE)
    handler = signal.getsignal(signal.SIGXFSZ)
    def too_large(_signal, _frame):
        raise FactorRepairError("repair_storage_budget_exceeded")
    try:
        if candidate:
            signal.signal(signal.SIGXFSZ, too_large)
            limit = remaining if original[0] == resource.RLIM_INFINITY else min(remaining, original[0])
            resource.setrlimit(resource.RLIMIT_FSIZE, (limit, original[1]))
        with ledger.writing(output, reserve_bytes=reserve_bytes, candidate=candidate):
            copied_rows = int(connection.execute(copy_query_to_parquet(query, output)).fetchone()[0])
        runtime = current_repair_runtime()
        if runtime is not None:
            runtime.forget(output)
            runtime.counters["copy_calls"] += 1
        return copied_rows
    finally:
        if candidate:
            resource.setrlimit(resource.RLIMIT_FSIZE, original)
            signal.signal(signal.SIGXFSZ, handler)


def audit_price_repair_partition_coverage(connection,plan,unit,targets):
    """One complete market coverage audit per asset/month, using only frozen file inventory."""
    from orchestrator.defs import paths
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        RepairCandidateInputs,
        repair_target_scope,
    )
    from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
    from orchestrator.defs.stk_mins_qfq import (
        build_canonical_gold_stk_mins_qfq_coverage_identities_sql,
        build_canonical_gold_stk_mins_qfq_diagnostics_sql,
        gold_stk_mins_qfq_source_freq,
    )
    from orchestrator.defs.stock_factor_price_checks import (
        minute_qfq_counts_sql,
        minute_qfq_identity_coverage_counts_sql,
    )
    freq = int(unit["asset_key"].rsplit("_",1)[1][:-1])
    dates = sorted({d for target in targets for profile in repair_target_scope(plan,unit,Path(target))["profiles"] for d in profile["dates"]})
    inputs = RepairCandidateInputs(connection,plan)
    inputs.require_factor_candidates = True
    root = Path(plan["lake_root"])
    months = {}
    for day in dates:
        months.setdefault(day[:7],[]).append(day)
    for month,days in months.items():
        silver = [inputs.frozen(paths.silver_stk_mins_path(root,gold_stk_mins_qfq_source_freq(freq),d)) for d in days]
        factors = [inputs.resolve(paths.silver_adj_factor_path(root,d)) for d in days]
        diagnostics = connection.execute(build_canonical_gold_stk_mins_qfq_diagnostics_sql(silver_paths=silver,target_freq=freq,partition_keys=days)).fetchone()
        if diagnostics[3] <= 0 or diagnostics[4] != diagnostics[5] or diagnostics[6] or diagnostics[7]:
            raise FactorRepairError("repair_minute_source_incomplete")
        expected = build_canonical_gold_stk_mins_qfq_coverage_identities_sql(silver_paths=silver,
            trade_adj_factor_paths=factors,as_of_adj_factor_paths=factors,target_freq=freq,
            partition_keys=days,match_as_of_by_trade_date=True)
        connection.execute("CREATE OR REPLACE TEMP TABLE repair_validation_expected AS " + expected)
        expected_rows = connection.execute("SELECT count(*) FROM repair_validation_expected").fetchone()[0]
        if expected_rows != diagnostics[5]:
            raise FactorRepairError("repair_minute_source_coverage_failed")
        codes = {r[0] for r in connection.execute("SELECT DISTINCT ts_code FROM repair_validation_expected").fetchall()}
        expected_paths = {str(paths.gold_stk_mins_qfq_path(root,freq,code,month[:4])) for code in codes}
        if not expected_paths <= set(unit["validation_paths"]):
            raise FactorRepairError("repair_validation_inventory_incomplete")
        connection.execute("CREATE OR REPLACE TEMP TABLE repair_validation_actual(ts_code VARCHAR,trade_time TIMESTAMP,exchange VARCHAR,trade_date DATE)")
        outputs = sorted(expected_paths)
        for offset in range(0,len(outputs),64):
            relations = []
            for name in outputs[offset:offset+64]:
                target = Path(name)
                output = inputs.resolve(target)
                from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
                    assert_repair_schema,
                    repair_asset_schema,
                )
                assert_repair_schema(connection,output,repair_asset_schema(unit["asset_key"]))
                relations.append(f"SELECT *,{duckdb_string(target)} filename FROM {read_parquet(output,hive_partitioning=False)}")
            source = "(" + " UNION ALL ".join(relations) + ")"
            counts = connection.execute(minute_qfq_counts_sql(gold_source=source,partition_key=days,freq=freq)).fetchone()
            if any(counts[1:]):
                raise FactorRepairError("repair_minute_contract_failed")
            date_filter = ",".join("DATE " + duckdb_string(d) for d in days)
            connection.execute(f"INSERT INTO repair_validation_actual SELECT ts_code,trade_time,exchange,trade_date FROM {source} WHERE trade_date IN ({date_filter})")
        if any(connection.execute(minute_qfq_identity_coverage_counts_sql(gold_source="repair_validation_actual",expected_identity_sql="SELECT * FROM repair_validation_expected",partition_key=days)).fetchone()):
            raise FactorRepairError("repair_minute_source_coverage_failed")
        for name in inputs.verified:
            if asdict(file_identity(Path(name))) != inputs.identities[name]:
                raise FactorRepairError("input_drift")
        check_repair_storage(Path(plan["run_root"]),plan=plan)


def run_repair_candidate_worker(request: dict, *, plan, connection) -> dict:
    """One logical unit inside the admitted phase worker and its shared connection."""
    runtime = current_repair_runtime(plan)
    root = Path(plan["run_root"])
    if "replay_task_index" in request:
        if request["phase"] != "indicator":
            raise FactorRepairError("repair_phase_not_supported")
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
            indicator_replay_tasks,
            replay_indicator_task,
        )
        tasks = runtime.once("indicator_tasks", lambda: indicator_replay_tasks(plan))
        index = request["replay_task_index"]
        if type(index) is not int or not 0 <= index < len(tasks):
            raise FactorRepairError("repair_indicator_task_invalid")
        task = tasks[index]
        def progress(data):
            atomic_repair_json(root / "checkpoints/active.json", {
                "plan_hash": plan["plan_hash"], "batch_id": request["batch_id"],
                "completed": 0, "current_target": task["profile"]["ts_code"] + ":" + task["asset_key"], **data})
        replay = replay_indicator_task(connection, plan, task, audit=request["audit"], progress=progress)
        return {"changed_rows": 0, "no_op_files": 0, "candidate_delta": 0, "replay_result": {k: replay[k] for k in ("task_id", "fragments", "completed_rows")}}
    index = request["unit_index"]
    if type(index) is not int or not 0 <= index < len(plan["units"]):
        raise FactorRepairError("repair_phase_not_supported")
    unit = plan["units"][index]
    targets = [check_repair_path(Path(p)) for p in request["targets"]]
    phase_assets = PRICE_REPAIR_ASSETS[:2] if request["phase"] == "factor" else PRICE_REPAIR_ASSETS[2:] if request["phase"] == "price" else indicator_repair_assets()
    if (unit["asset_key"] not in phase_assets or not 1 <= len(targets) <= 64
            or len(set(targets)) != len(targets) or any(str(p) not in unit["target_paths"] for p in targets)):
        raise FactorRepairError("repair_phase_not_supported")
    changed, no_op, delta = 0, 0, 0
    pending, completed_records = {}, {}
    indicator = unit["asset_key"] in indicator_repair_assets()
    for number, target in enumerate(targets, 1):
        before = root / "candidates" / target.relative_to(Path(plan["lake_root"]))
        old_bytes = before.stat().st_size if before.exists() else 0
        if indicator:
            from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
                build_indicator_target_candidate,
            )
            record = build_indicator_target_candidate(connection, plan, unit, target, audit=request["audit"])
            if record.get("business_pending"):
                pending[str(target)] = record
            else:
                completed_records[str(target)] = record
        else:
            record = build_repair_target_candidate(connection, plan, unit, target, audit=request["audit"])
        delta += record["candidate_bytes"] - old_bytes
        changed += record["changed_stock_rows"]
        no_op += int(record["no_op"])
        atomic_repair_json(root / "checkpoints/active.json", {
            "plan_hash": plan["plan_hash"], "batch_id": request["batch_id"],
            "completed": 0 if pending else number, "current_target": str(target),
            "pending_files": len(pending)})
    if pending:
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
            audit_indicator_batch,
            seal_indicator_batch,
        )
        proof = audit_indicator_batch(connection, plan, unit, [str(p) for p in targets],
            pending=pending, completed=completed_records)
        seal_indicator_batch(plan, pending, proof)
        atomic_repair_json(root / "checkpoints/active.json", {
            "plan_hash": plan["plan_hash"], "batch_id": request["batch_id"],
            "completed": len(targets), "current_target": str(targets[-1])})
    return {"changed_rows": changed, "no_op_files": no_op, "candidate_delta": delta}


def _rss(pid: int) -> int:
    result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True,
                            text=True, check=False)
    return int(result.stdout.strip() or "0") * 1024


def _stop_worker(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            child.wait(timeout=5)
            return
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)


@contextmanager
def repair_coordinator_termination_guard():
    """Route TERM through the same durable cancellation and child cleanup as Ctrl-C."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(_signal, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt("repair_coordinator_terminated")

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextmanager
def repair_worker_parent_guard(request):
    """Retain the coordinator's plan lock and kill our owned group if it exits."""
    parent, descriptor = request.get("coordinator_pid"), request.get("plan_lock_fd")
    if (type(parent) is not int or parent <= 0 or parent != os.getppid()
            or type(descriptor) is not int or descriptor < 3
            or os.getpgrp() != os.getpid()):
        raise FactorRepairError("repair_worker_parent_invalid")
    try:
        path = check_repair_path(Path(request["plan_path"]))
        inherited, expected = os.fstat(descriptor), path.stat()
        if (not stat.S_ISREG(inherited.st_mode)
                or (inherited.st_dev, inherited.st_ino) != (expected.st_dev, expected.st_ino)):
            raise FactorRepairError("repair_worker_lock_invalid")
        # A different open-file description must be blocked by the inherited flock.
        with path.open("rb") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise FactorRepairError("repair_worker_lock_invalid")
        # A same-inode descriptor opened independently cannot acquire the parent's lock.
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, KeyError) as error:
        raise FactorRepairError("repair_worker_lock_invalid") from error
    stopped = threading.Event()

    def watch_parent():
        while not stopped.wait(0.1):
            if os.getppid() != parent:
                os.killpg(os.getpid(), signal.SIGKILL)

    watcher = threading.Thread(target=watch_parent, daemon=True)
    watcher.start()
    try:
        if os.getppid() != parent:
            raise FactorRepairError("repair_worker_parent_invalid")
        yield
    finally:
        stopped.set()
        watcher.join()
        # Never LOCK_UN: the inherited description is shared with the coordinator.
        os.close(descriptor)


_COORDINATOR_RUNTIME = None


def _read_worker_message(stream):
    encoded = stream.readline(16386)
    if len(encoded.encode("utf-8")) > 16384:
        raise FactorRepairError("repair_worker_request_exceeded")
    if not encoded:
        raise FactorRepairError("repair_worker_protocol_eof")
    return json.loads(encoded)


def _write_worker_message(stream, message):
    encoded = json.dumps(message, allow_nan=False)
    if len(encoded.encode()) + 1 > 16384:
        raise FactorRepairError("repair_worker_request_exceeded")
    stream.write(encoded + "\n")
    stream.flush()


def serve_repair_worker(*, prepare=None):
    """Bounded init/work/finish protocol. The parent alone performs plan admission."""
    request = _read_worker_message(sys.stdin)
    if request.get("action") != "init" or request.get("phase") not in ("factor", "price", "indicator"):
        raise FactorRepairError("repair_worker_request_invalid")
    with repair_worker_parent_guard(request):
        path = check_repair_path(Path(request["plan_path"]))
        if path.stat().st_size > REPAIR_PLAN_MAX_BYTES:
            raise FactorRepairError("repair_plan_size_exceeded")
        encoded = path.read_bytes()
        if len(encoded) > REPAIR_PLAN_MAX_BYTES or hashlib.sha256(encoded).hexdigest() != request.get("plan_bytes_sha256"):
            raise FactorRepairError("repair_worker_admission_invalid")
        plan = json.loads(encoded.decode("utf-8"))
        del encoded
        if prepare is not None:
            prepare(plan)
        runtime = RepairRuntime(plan, admitted=True, selection=request.get("selection"))
        if (plan["plan_hash"] != request["expected_hash"] or runtime.binding != request.get("admission")
                or path != Path(plan["run_root"]) / "plan.json"):
            raise FactorRepairError("repair_worker_admission_invalid")
        root = runtime.root
        temporary = check_repair_path(root / "temp")
        temporary.mkdir(exist_ok=True)
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
            indicator_replay_tasks,
        )
        runtime.indexes["indicator_tasks"] = indicator_replay_tasks(plan)
        with use_repair_runtime(runtime):
            runtime.storage = RepairStorageLedger(root, scan=repair_storage_totals, plan=plan)
        settings = RepairBudget().connection_settings(temporary)
        from dataclasses import replace
        settings = replace(settings, max_temp_directory_size=f"{max(0, RepairBudget().max_spill-runtime.storage.counts['spill_bytes'])}B")
        manager = nullcontext(None) if request["audit"] else connect_configured_duckdb(settings)
        with use_repair_runtime(runtime), manager as connection:
            if connection is not None:
                connection.execute("SET autoinstall_known_extensions=false")
                connection.execute("SET autoload_known_extensions=false")
                runtime.counters["connections"] += 1
            _write_worker_message(sys.stdout, {"status": "ready"})
            while True:
                work = _read_worker_message(sys.stdin)
                if work.get("action") == "finish":
                    break
                if work.get("action") != "work":
                    raise FactorRepairError("repair_worker_request_invalid")
                if work.get("phase") != request["phase"] or work.get("audit") != request["audit"]:
                    raise FactorRepairError("repair_worker_request_invalid")
                result = run_repair_candidate_worker(work, plan=plan, connection=connection)
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                result.update(peak_rss_bytes=int(rss if sys.platform == "darwin" else rss*1024),
                    storage_accounting=runtime.storage.payload(), counters=dict(runtime.counters))
                _write_worker_message(sys.stdout, {"status": "batch_done", "result": result})
        # Connection closure removes only DuckDB-owned spill; no directory walk.
        _write_worker_message(sys.stdout, {"status": "finished", "storage_accounting": runtime.storage.payload()})


def execute_repair_candidates(plan_path: Path, expected_hash: str, *, phase: str, audit=False,
                         selected_targets=None, cancel=None, progress=None, worker_command=None) -> dict:
    """Admit once, reuse each phase worker, never enumerate market data."""
    global _COORDINATOR_RUNTIME
    started = time.monotonic()
    completed, changed, no_op, peak = 0, 0, 0, 0
    summary = {"plan_hash": expected_hash, "phase": phase, "status": "BUILDING",
               "total": None, "completed": 0, "all_chain_ready": False,
               "replay_total": 0, "replay_completed": 0}
    last_emit = started
    update_after = RepairBudget().progress_interval * 5 / 6
    def emit(current=None, **extra):
        nonlocal last_emit
        last_emit = time.monotonic()
        summary.update(completed=completed, changed_rows=changed, no_op_files=no_op,
                       peak_rss_bytes=peak, elapsed_seconds=last_emit-started,
                       current_target=current, updated_at=time.time(), **extra)
        if progress:
            progress(dict(summary))
    def loading_progress(data):
        emit(data.get("current_target"), **{k: v for k, v in data.items() if k != "current_target"})
    emit(activity="准备已批准阶段")
    try:
        with repair_coordinator_termination_guard():
            check_repair_cancel(cancel)
            runtime = _COORDINATOR_RUNTIME
            if (runtime is None or runtime.root / "plan.json" != plan_path
                    or runtime.plan["plan_hash"] != expected_hash):
                admission = {}
                plan = load_repair_plan(plan_path, expected_hash, cancel=cancel, progress=loading_progress, admission=admission)
                runtime = RepairRuntime(plan, admitted=True)
                runtime.plan_bytes_sha256 = admission["plan_bytes_sha256"]
                runtime.counters["plan_admissions"] += 1
                from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
                    indicator_replay_tasks,
                )
                runtime.indexes["indicator_tasks"] = indicator_replay_tasks(plan)
                _COORDINATOR_RUNTIME = runtime
            else:
                plan = runtime.plan
    except (Exception, KeyboardInterrupt) as error:
        summary.update(status="CANCELLED" if isinstance(error, KeyboardInterrupt) or str(error) == "canceled" else "FAILED", reason_code=str(error)[:300])
        emit()
        raise
    work = repair_candidate_work(plan, phase, selected_targets=selected_targets)
    replay_work = []
    if phase == "indicator":
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
            indicator_repair_target,
        )
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
            indicator_replay_tasks,
        )
        selected = {p for _, p in work}
        for index, task in enumerate(runtime.once("indicator_tasks", lambda: indicator_replay_tasks(plan))):
            needed = any(str(indicator_repair_target(runtime.lake_root, asset, p["ts_code"], p["freq"], d)) in selected
                for asset, p in ((task["asset_key"], task["profile"]), (task["state_asset"], task["state_profile"]))
                if p is not None for d in p["target_dates"])
            if needed:
                replay_work.append((-index-1, [task["profile"]["ts_code"] + ":" + task["asset_key"]]))
    root = check_repair_path(runtime.root)
    summary.update(total=len(work), replay_total=len(replay_work))
    with repair_coordinator_termination_guard(), plan_path.open("rb") as lock, use_repair_runtime(runtime):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise FactorRepairError("repair_candidate_writer_busy") from error
        try:
            if runtime.storage is None:
                runtime.storage = RepairStorageLedger(root, scan=repair_storage_totals, plan=plan)
            runtime.storage.check()
            runtime.storage.persist()
            active = root / "checkpoints/active.json"
            atomic_repair_json(active, {"plan_hash": expected_hash, "batch_id": "init", "completed": 0, "current_target": None})
            command = worker_command or [sys.executable, "-B", "-m", __name__, "_worker"]
            with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, start_new_session=True, pass_fds=(lock.fileno(),)) as child:
                runtime.counters["workers"] += 1
                buffers = {child.stdout.fileno(): bytearray(), child.stderr.fileno(): bytearray()}
                messages = []
                def drain():
                    for fd in select.select(list(buffers), [], [], 0)[0]:
                        data = os.read(fd, 4096)
                        if not data:
                            continue
                        buffers[fd].extend(data)
                        if fd == child.stdout.fileno():
                            while b"\n" in buffers[fd]:
                                line, _, rest = buffers[fd].partition(b"\n")
                                if len(line) + 1 > 16384 or len(messages) >= 2:
                                    raise FactorRepairError("repair_worker_output_exceeded")
                                messages.append(json.loads(line))
                                buffers[fd] = bytearray(rest)
                        if len(buffers[fd]) > 16384:
                            raise FactorRepairError("repair_worker_output_exceeded")
                def receive(status):
                    nonlocal peak
                    while True:
                        drain()
                        if messages:
                            message = messages.pop(0)
                            if message.get("status") != status:
                                raise FactorRepairError("repair_worker_protocol_invalid")
                            return message
                        if child.poll() is not None:
                            drain()
                            if messages:
                                continue
                            raise FactorRepairError("repair_worker_failed:" + buffers[child.stderr.fileno()].decode(errors="replace")[-300:])
                        check_repair_cancel(cancel)
                        peak = max(peak, _rss(os.getpid()) + _rss(child.pid))
                        if peak > RepairBudget().max_rss:
                            raise FactorRepairError("repair_rss_budget_exceeded")
                        if active.exists():
                            observed = json.loads(active.read_text())
                            matching = status == "batch_done" and observed.get("batch_id") == str(batch_number)
                            worker_completed = observed.get("completed", 0) if matching else 0
                            if (worker_completed != summary.get("worker_completed", 0)
                                    or matching and observed.get("replay_calculated_rows", 0) != summary.get("replay_calculated_rows", 0)
                                    or time.monotonic()-last_emit >= update_after):
                                emit(observed.get("current_target") if matching else summary.get("current_target"),
                                    worker_completed=worker_completed, visible_completed=completed+worker_completed,
                                    activity="当前片段/文件处理；暂无法估算剩余时间。",
                                    **({k: v for k, v in observed.items() if k.startswith("replay_")} if matching else {}))
                        time.sleep(0.1)
                try:
                    _write_worker_message(child.stdin, {"action": "init", "plan_path": str(plan_path),
                        "expected_hash": expected_hash, "phase": phase, "audit": audit,
                        "admission": runtime.binding, "selection": repair_hash([phase, selected_targets]),
                        "plan_bytes_sha256": runtime.plan_bytes_sha256,
                        "coordinator_pid": os.getpid(), "plan_lock_fd": lock.fileno()})
                    receive("ready")
                    for batch_number, (index, targets) in enumerate([*replay_work, *repair_candidate_batches(work)]):
                        check_repair_cancel(cancel)
                        emit(targets[0], worker_completed=0)
                        request = {"action": "work", "phase": phase, "audit": audit,
                            "unit_index": index, "targets": targets, "batch_id": str(batch_number)}
                        if index < 0:
                            request["replay_task_index"] = -index-1
                        _write_worker_message(child.stdin, request)
                        result = receive("batch_done")["result"]
                        runtime.storage.counts = result["storage_accounting"]["counts"]
                        peak = max(peak, _rss(os.getpid()) + result["peak_rss_bytes"])
                        if peak > RepairBudget().max_rss:
                            raise FactorRepairError("repair_rss_budget_exceeded")
                        if index < 0:
                            summary["replay_completed"] += 1
                        else:
                            # Worker proofs already seal each file. Parent doesn't repeat SQL or hashes.
                            completed += len(targets)
                        changed += result["changed_rows"]
                        no_op += result["no_op_files"]
                        summary["worker_counters"] = result["counters"]
                        emit(targets[-1], worker_completed=0, visible_completed=completed, **runtime.storage.snapshot())
                        atomic_repair_json(root / "checkpoint.json", summary)
                    _write_worker_message(child.stdin, {"action": "finish"})
                    receive("finished")
                    child.stdin.close()
                    child.wait(timeout=5)
                    if child.returncode:
                        raise FactorRepairError("repair_worker_failed")
                finally:
                    _stop_worker(child)
            summary.update(status={"factor": "FACTOR_CANDIDATES_VERIFIED", "price": "PRICE_CANDIDATES_VERIFIED", "indicator": "INDICATOR_CANDIDATES_VERIFIED"}[phase],
                sample=selected_targets is not None, audited=audit, counters=dict(runtime.counters))
            if phase == "indicator" and audit and selected_targets is None:
                runtime.storage.reconcile()
            emit()
            atomic_repair_json(root / (f"{phase}-sample-audit.json" if selected_targets is not None else f"{phase}-audit.json"), summary)
            atomic_repair_json(root / "checkpoint.json", summary)
        except (Exception, KeyboardInterrupt) as error:
            runtime.storage = None
            summary.update(status="CANCELLED" if isinstance(error, KeyboardInterrupt) or str(error) == "canceled" else "FAILED", reason_code=str(error)[:300])
            emit()
            # Preserve the worker's durable accounting and any unsettled reservation.
            from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
                _atomic_runtime_json as write,
            )
            checkpoint = root / "checkpoint.json"
            previous = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
            write(checkpoint, {**previous, **summary})
            raise
    summary.update(runtime.storage.snapshot())
    return summary


def main():
    if sys.argv[1:] != ["_worker"]:
        raise FactorRepairError("repair_worker_command_invalid")
    serve_repair_worker()


if __name__ == "__main__":
    main()
