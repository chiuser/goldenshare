"""Sequential, resumable R1 candidate workers. No formal writer or Dagster instance."""

from __future__ import annotations

import fcntl
import json
import os
import resource
import select
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    REPAIR_PLAN_MAX_BYTES,
    FactorRepairError,
    RepairBudget,
    atomic_repair_json,
    check_repair_cancel,
    check_repair_path,
    file_identity,
    repair_implementation_files,
    validate_repair_plan,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    PRICE_REPAIR_ASSETS,
    build_repair_target_candidate,
    read_repair_candidate_record,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb


def load_price_repair_plan(path: Path, expected_hash: str) -> dict:
    path = check_repair_path(path)
    if path.stat().st_size > REPAIR_PLAN_MAX_BYTES:
        raise FactorRepairError("repair_plan_size_exceeded")
    plan = json.loads(path.read_text())
    validate_repair_plan(plan, expected_hash)
    if path != Path(plan["run_root"]) / "plan.json":
        raise FactorRepairError("repair_plan_path_invalid")
    implementations = {i["path"] for i in plan["implementation_fingerprints"]}
    if implementations != {str(p) for p in repair_implementation_files()} or len(implementations) != len(plan["implementation_fingerprints"]):
        raise FactorRepairError("repair_implementation_not_frozen")
    for identity in plan["implementation_fingerprints"]:
        if asdict(file_identity(Path(identity["path"]))) != identity:
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
    if any(not check_repair_path(Path(i["path"])).is_relative_to(Path(plan["lake_root"])) for i in plan["source_fingerprints"]):
        raise FactorRepairError("repair_input_not_approved")
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
    current = {str(p) for p in directory.glob("trade_date=*/part-000.parquet") if p.parent.name.removeprefix("trade_date=") <= cutoff}
    if current != inventory or any(set(p["source_inventory_paths"]) != inventory for p in daily["calculation_windows"]):
        raise FactorRepairError("repair_daily_source_inventory_drift")
    gold_directory = paths.gold_stock_daily_qfq_path(Path(plan["lake_root"]),cutoff).parents[1]
    original_gold = {i["path"] for i in plan["source_fingerprints"] if Path(i["path"]).parent.parent == gold_directory}
    current_gold = {str(p) for p in gold_directory.glob("trade_date=*/part-000.parquet") if p.parent.name.removeprefix("trade_date=") <= cutoff}
    if current_gold != original_gold:
        raise FactorRepairError("repair_price_source_inventory_drift")
    return plan


def price_repair_work(plan, phase: str, *, selected_targets=None):
    if phase not in ("factor", "price"):
        raise FactorRepairError("repair_phase_not_supported")
    assets = set(PRICE_REPAIR_ASSETS[:2] if phase == "factor" else PRICE_REPAIR_ASSETS[2:])
    work = [(index, path) for index, unit in enumerate(plan["units"])
            if unit["asset_key"] in assets for path in sorted(unit["target_paths"])]
    work.sort(key=lambda item: (PRICE_REPAIR_ASSETS.index(plan["units"][item[0]]["asset_key"]), item[1]))
    if selected_targets is not None:
        selected = tuple(selected_targets)
        if not selected or len(set(selected)) != len(selected) or set(selected) - {p for _, p in work}:
            raise FactorRepairError("repair_sample_not_frozen")
        work = [w for w in work if w[1] in selected]
    if not work:
        raise FactorRepairError("repair_phase_empty")
    return work


def price_repair_batches(work):
    """Group one asset/month or asset/year, at most 64 full-file merges per fresh process."""
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
    for directory,dirs,files in os.walk(check_repair_path(root),followlinks=False):
        for name in dirs + files:
            path = Path(directory)/name
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise FactorRepairError("repair_path_symlink")
            if not stat.S_ISREG(st.st_mode):
                continue
            counts["staging_bytes"] += st.st_size
            for label,sub in (("candidate_bytes","candidates"),("spill_bytes","temp"),("input_bytes","inputs")):
                if path.is_relative_to(root/sub):
                    counts[label] += st.st_size
    return counts


def repair_storage_bytes(root: Path) -> tuple[int,int]:
    counts = repair_storage_totals(root)
    return counts["candidate_bytes"],counts["spill_bytes"]


def check_repair_storage(root: Path, *, plan=None, reserve_bytes=0) -> dict:
    import shutil
    candidates,spill = repair_storage_bytes(root)
    counts = repair_storage_totals(root)
    counts.update(candidate_bytes=candidates,spill_bytes=spill)
    budget = RepairBudget()
    if candidates > budget.max_candidate_bytes or spill > budget.max_spill:
        raise FactorRepairError("repair_storage_budget_exceeded")
    remaining = max(0,(plan or {}).get("space_required_bytes",0)-counts["staging_bytes"])
    required = max(remaining,(reserve_bytes+max(0,budget.max_spill-spill))*6//5)
    if shutil.disk_usage(root).free < required:
        raise FactorRepairError("repair_space_insufficient")
    return counts


def bounded_repair_copy(connection,query,root,output,*,candidate=False,reserve_bytes=0):
    """OS file-size limit enforces candidate quota; space is checked before and after COPY."""
    from orchestrator.defs.duckdb_sql import copy_query_to_parquet
    storage = check_repair_storage(root,reserve_bytes=reserve_bytes)
    remaining = RepairBudget().max_candidate_bytes-storage["candidate_bytes"]
    if candidate and (remaining <= 0 or reserve_bytes > remaining):
        raise FactorRepairError("repair_storage_budget_exceeded")
    original = resource.getrlimit(resource.RLIMIT_FSIZE)
    handler = signal.getsignal(signal.SIGXFSZ)
    def too_large(_signal,_frame):
        raise FactorRepairError("repair_storage_budget_exceeded")
    try:
        if candidate:
            signal.signal(signal.SIGXFSZ,too_large)
            limit = remaining if original[0] == resource.RLIM_INFINITY else min(remaining,original[0])
            resource.setrlimit(resource.RLIMIT_FSIZE,(limit,original[1]))
        connection.execute(copy_query_to_parquet(query,output))
        check_repair_storage(root)
    finally:
        if candidate:
            resource.setrlimit(resource.RLIMIT_FSIZE,original)
            signal.signal(signal.SIGXFSZ,handler)


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


def run_price_repair_worker(request: dict) -> dict:
    plan = load_price_repair_plan(Path(request["plan_path"]), request["expected_hash"])
    unit = plan["units"][request["unit_index"]]
    targets = [check_repair_path(Path(p)) for p in request["targets"]]
    if (unit["asset_key"] not in PRICE_REPAIR_ASSETS or not 1 <= len(targets) <= 64
            or len(set(targets)) != len(targets) or any(str(p) not in unit["target_paths"] for p in targets)):
        raise FactorRepairError("repair_phase_not_supported")
    root = Path(plan["run_root"])
    temporary = check_repair_path(root / "temp")
    temporary.mkdir(exist_ok=True)
    changed, no_op, delta = 0, 0, 0
    from dataclasses import replace
    storage = check_repair_storage(root,plan=plan)
    settings = replace(RepairBudget().connection_settings(temporary),
        max_temp_directory_size=f"{max(0,RepairBudget().max_spill-storage['spill_bytes'])}B")
    with connect_configured_duckdb(settings) as connection:
        connection.execute("SET autoinstall_known_extensions=false")
        connection.execute("SET autoload_known_extensions=false")
        for number, target in enumerate(targets, 1):
            check_repair_storage(root,plan=plan)
            before = root / "candidates" / target.relative_to(Path(plan["lake_root"]))
            old_bytes = before.stat().st_size if before.exists() else 0
            record = build_repair_target_candidate(connection, plan, unit, target, audit=request["audit"])
            delta += record["candidate_bytes"] - old_bytes
            if request.get("candidate_bytes", 0) + delta > RepairBudget().max_candidate_bytes:
                raise FactorRepairError("repair_storage_budget_exceeded")
            changed += record["changed_stock_rows"]
            no_op += int(record["no_op"])
            atomic_repair_json(root / "checkpoints/active.json", {
                "plan_hash": plan["plan_hash"], "batch_id": request["batch_id"],
                "completed": number, "current_target": str(target)})
        if unit["asset_key"].startswith("gold_stk_mins_qfq_"):
            audit_price_repair_partition_coverage(connection,plan,unit,targets)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"changed_rows": changed, "no_op_files": no_op, "candidate_delta": delta,
            "peak_rss_bytes": int(rss if sys.platform == "darwin" else rss*1024)}


def _rss(pid: int) -> int:
    result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True,
                            text=True, check=False)
    return int(result.stdout.strip() or "0") * 1024


def _stop_worker(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)


def execute_price_repair(plan_path: Path, expected_hash: str, *, phase: str, audit=False,
                         selected_targets=None, cancel=None, progress=None, worker_command=None) -> dict:
    """Tests inject a worker launcher, never a CLI option for alternate production roots."""
    plan = load_price_repair_plan(plan_path, expected_hash)
    work = price_repair_work(plan, phase, selected_targets=selected_targets)
    root = check_repair_path(Path(plan["run_root"]))
    storage = None
    started, completed, changed, no_op, peak = time.monotonic(), 0, 0, 0, 0
    summary = {"plan_hash": expected_hash, "phase": phase, "status": "BUILDING",
               "total": len(work), "completed": 0, "all_chain_ready": False}
    def emit(current=None, **extra):
        summary.update(completed=completed, changed_rows=changed, no_op_files=no_op,
                       peak_rss_bytes=peak, elapsed_seconds=time.monotonic()-started,
                       current_target=current, updated_at=time.time(), **extra)
        if progress:
            progress(dict(summary))

    # Advisory lock on the existing immutable plan: no separate lock service or file.
    with plan_path.open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise FactorRepairError("repair_candidate_writer_busy") from error
        try:
            storage = check_repair_storage(root,plan=plan)
            verified_bytes = 0
            total_bytes = sum(i["size"] for i in plan["source_fingerprints"])
            last_preflight = time.monotonic()
            emit(activity="冻结输入指纹核验",verified_inputs=0,verified_bytes=0,total_input_bytes=total_bytes)
            for number,identity in enumerate(plan["source_fingerprints"],1):
                check_repair_cancel(cancel)
                def hashing(read_bytes,_size,identity=identity,number=number,verified_bytes=verified_bytes):
                    nonlocal last_preflight
                    if time.monotonic()-last_preflight >= RepairBudget().progress_interval:
                        emit(identity["path"],activity="冻结输入指纹核验",verified_inputs=number-1,
                            verified_bytes=verified_bytes,hashed_current_bytes=read_bytes,total_input_bytes=total_bytes)
                        last_preflight = time.monotonic()
                if asdict(file_identity(Path(identity["path"]),cancel=cancel,progress=hashing)) != identity:
                    raise FactorRepairError("input_drift")
                verified_bytes += identity["size"]
                if number % 64 == 0 or number == len(plan["source_fingerprints"]):
                    emit(identity["path"],activity="冻结输入指纹核验",verified_inputs=number,
                        verified_bytes=verified_bytes,hashed_current_bytes=0,total_input_bytes=total_bytes)
                    last_preflight = time.monotonic()
            for batch_number, (index, targets) in enumerate(price_repair_batches(work)):
                check_repair_cancel(cancel)
                emit(targets[0])
                request = {"plan_path": str(plan_path), "expected_hash": expected_hash,
                           "unit_index": index, "targets": targets, "audit": audit,
                           "batch_id": str(batch_number),
                           "candidate_bytes": storage["candidate_bytes"]}
                active = root / "checkpoints/active.json"
                atomic_repair_json(active, {"plan_hash": expected_hash, "batch_id": str(batch_number),
                                           "completed": 0, "current_target": targets[0]})
                command = worker_command or [sys.executable, "-B", "-m", __name__, "_worker"]
                with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, start_new_session=True) as child:
                    try:
                        try:
                            child.stdin.write(json.dumps(request)); child.stdin.close()
                        except BrokenPipeError:
                            pass
                        captured = {child.stdout.fileno(): bytearray(), child.stderr.fileno(): bytearray()}
                        def drain(captured=captured):
                            for fd in select.select(list(captured), [], [], 0)[0]:
                                captured[fd].extend(os.read(fd, 4096))
                                if len(captured[fd]) > 16384:
                                    raise FactorRepairError("repair_worker_output_exceeded")
                        last_update = time.monotonic()
                        last_storage = last_update
                        while child.poll() is None:
                            drain()
                            if time.monotonic()-last_storage >= 1:
                                storage = check_repair_storage(root,plan=plan)
                                last_storage = time.monotonic()
                            check_repair_cancel(cancel)
                            peak = max(peak, _rss(os.getpid()) + _rss(child.pid))
                            if peak > RepairBudget().max_rss:
                                raise FactorRepairError("repair_rss_budget_exceeded")
                            observed = json.loads(active.read_text())
                            if observed["completed"] != summary.get("worker_completed", 0) or time.monotonic() - last_update >= RepairBudget().progress_interval:
                                emit(observed["current_target"], worker_completed=observed["completed"],
                                     visible_completed=completed+observed["completed"],
                                     activity="当前片段/文件校验；暂无法估算剩余时间。")
                                last_update = time.monotonic()
                            time.sleep(0.1)
                        for _ in range(5):
                            drain()
                        stdout, stderr = (captured[p.fileno()].decode() for p in (child.stdout, child.stderr))
                        if child.returncode or len(stdout) > 16384:
                            raise FactorRepairError("repair_worker_failed:" + stderr.strip()[-300:])
                        result = json.loads(stdout)
                        peak = max(peak, _rss(os.getpid()) + result["peak_rss_bytes"])
                        if peak > RepairBudget().max_rss:
                            raise FactorRepairError("repair_rss_budget_exceeded")
                    finally:
                        _stop_worker(child)
                check_repair_cancel(cancel)
                for target in targets:
                    read_repair_candidate_record(plan, Path(target))
                completed += len(targets)
                changed += result["changed_rows"]
                no_op += result["no_op_files"]
                storage = check_repair_storage(root,plan=plan)
                if storage["candidate_bytes"] > RepairBudget().max_candidate_bytes:
                    raise FactorRepairError("repair_storage_budget_exceeded")
                emit(targets[-1], worker_completed=0, visible_completed=completed, **storage)
                atomic_repair_json(root / "checkpoint.json", summary)
            summary.update(status="FACTOR_CANDIDATES_VERIFIED" if phase == "factor" else "PRICE_CANDIDATES_VERIFIED",
                           sample=selected_targets is not None, audited=audit)
            emit()
            check_repair_storage(root,plan=plan)
            atomic_repair_json(root / (f"{phase}-sample-audit.json" if selected_targets is not None else f"{phase}-audit.json"), summary)
            atomic_repair_json(root / "checkpoint.json", summary)
        except (Exception, KeyboardInterrupt) as error:
            summary.update(status="CANCELLED" if isinstance(error, KeyboardInterrupt) or str(error)=="canceled" else "FAILED",
                           reason_code=str(error)[:300])
            emit()
            atomic_repair_json(root / "checkpoint.json", summary)
            raise
    return summary


def main():
    if sys.argv[1:] != ["_worker"]:
        raise FactorRepairError("repair_worker_command_invalid")
    request = sys.stdin.read(16385)
    if len(request) > 16384:
        raise FactorRepairError("repair_worker_request_exceeded")
    print(json.dumps(run_price_repair_worker(json.loads(request)), allow_nan=False))


if __name__ == "__main__":
    main()
