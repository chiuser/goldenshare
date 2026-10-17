"""Explicit preparation, candidates and promotion for this one DG repair."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    APPROVED_FACTOR_RANGES,
    FACTOR_SOURCE_COLUMNS,
    AssetRepairEndpoint,
    FactorRepairError,
    FactorRepairScope,
    check_repair_path,
    check_repair_roots,
    fetch_current_factor_rows,
    freeze_stock_factor_repair,
    inspect_repair_writers,
    repair_units_from_inspection,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_planning import (
    prepare_scoped_repair_inputs,
    run_repair_inspection,
)


@contextmanager
def _readonly_instance():
    """Read the existing instance only; never initialize a temporary/formal one."""
    import dagster as dg
    import yaml

    home = os.environ.get("DAGSTER_HOME", "")
    config = Path(home) / "dagster.yaml"
    if not home or not config.is_file() or config.stat().st_size > 64 * 1024:
        raise FactorRepairError("repair_existing_instance_required")
    configured = yaml.safe_load(config.read_text())
    if not isinstance(configured, dict) or "postgres" not in configured.get("storage", {}):
        raise FactorRepairError("repair_existing_postgres_instance_required")
    previous = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = (previous or "") + " -c default_transaction_read_only=on -c statement_timeout=10000"
    try:
        with dg.DagsterInstance.get() as instance:
            yield instance
    finally:
        if previous is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous


def _writer_guard(plan):
    from orchestrator.definitions import defs

    with _readonly_instance() as instance:
        writers = inspect_repair_writers(defs(), instance,
            input_paths=[i["path"] for i in plan["source_fingerprints"]],
            lake_root=Path(plan["lake_root"]))
        if not writers["idle"]:
            raise FactorRepairError("repair_writers_not_idle")


def _freeze(args, scopes, source, *, source_root=None):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        repair_coordinator_termination_guard,
    )
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import (
        repair_writer_lock,
    )
    from orchestrator.defs.stock_factor_price_checks import ADJ_FACTOR_PARTITION_SET

    with repair_coordinator_termination_guard(), repair_writer_lock(args.run_root) as lock:
        prepared = prepare_scoped_repair_inputs(root=args.run_root, scopes=scopes,
            source=source, parent_lock=lock, source_root=source_root,
            progress=lambda data: print(json.dumps(data), file=sys.stderr, flush=True))
        if "frozen_plan" in prepared:
            return prepared["frozen_plan"]
        observed = prepared["observed"]
        if observed["stop_reasons"]:
            raise FactorRepairError(observed["stop_reasons"][0])
        endpoints = tuple(AssetRepairEndpoint(**{
            k: (tuple(p[k]) if k in ("expected_dates", "context_times") else p[k])
            for k in AssetRepairEndpoint.__dataclass_fields__ if k in p
        }) for p in observed["profiles"])
        with _readonly_instance() as instance:
            partitions = {
                "partition_set": ADJ_FACTOR_PARTITION_SET,
                "registered_keys": sorted(instance.get_dynamic_partitions(ADJ_FACTOR_PARTITION_SET)),
                "indicator_sets": {name: sorted(instance.get_dynamic_partitions(name)) for name in (
                    "cn_a_stock_daily_trend_channel_trade_days", "cn_a_stock_trade_days",
                    "cn_a_stock_mins_silver_trade_days")},
                "checked_on": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            }
        return freeze_stock_factor_repair(lake_root=Path(paths.DEFAULT_LAKE_ROOT),
            run_root=args.run_root, scopes=scopes, source_rows=prepared["source_rows"],
            anchors=prepared["anchors"], endpoints=endpoints,
            input_stats=[r[:3] for r in observed["inventory"]["files"]],
            target_paths=observed["target_paths"],
            units=repair_units_from_inspection(observed, lake_root=Path(paths.DEFAULT_LAKE_ROOT)),
            partition_validation=partitions, preparation=prepared["preparation"])


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "promote":
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import (
            promote_repair_files,
        )
        parser = argparse.ArgumentParser(description="预览或逐文件提升本专项完整候选。")
        parser.add_argument("command", choices=("promote",))
        parser.add_argument("--plan", type=Path, required=True)
        parser.add_argument("--expected-plan-hash", required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--maintenance-confirmed", action="store_true")
        args = parser.parse_args(argv)
        result = promote_repair_files(args.plan, args.expected_plan_hash,
            dry_run=args.dry_run, maintenance_confirmed=args.maintenance_confirmed,
            writer_guard=_writer_guard,
            progress=lambda data: print(json.dumps(data), file=sys.stderr, flush=True))
        print(json.dumps(result, allow_nan=False))
        return 0
    if argv and argv[0] in ("build", "audit"):
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
            execute_repair_candidates,
        )
        parser = argparse.ArgumentParser(description="构建或审计冻结计划内的因子/价格候选；不写正式Lake。")
        parser.add_argument("command", choices=("build", "audit"))
        parser.add_argument("--plan", type=Path, required=True)
        parser.add_argument("--expected-plan-hash", required=True)
        parser.add_argument("--phase", choices=("factor", "price", "indicator"), required=True)
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument("--full", action="store_true")
        selection.add_argument("--sample-target", action="append")
        args = parser.parse_args(argv)
        result = execute_repair_candidates(args.plan, args.expected_plan_hash, phase=args.phase,
            audit=args.command == "audit", selected_targets=args.sample_target,
            progress=lambda data: print(json.dumps(data), file=sys.stderr, flush=True))
        print(json.dumps(result))
        return 0
    parser = argparse.ArgumentParser(description="只读核验批准股票的历史因子修复范围；不创建候选或正式任务。",
        epilog="专项候选：build/audit --plan PATH --expected-plan-hash HASH --phase factor|price|indicator (--full|--sample-target PATH)。")
    parser.add_argument("command", choices=("inspect", "freeze"))
    parser.add_argument("--scope", action="append", required=True, help="CODE:START:END；逐股重复输入")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--daily-basis-start", help="仅688689.SH允许2021-01-27")
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--maintenance-confirmed", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "freeze" and (not args.run_root or not args.maintenance_confirmed):
        raise FactorRepairError("repair_maintenance_confirmation_required")
    if args.command == "inspect" and (args.run_root or args.maintenance_confirmed):
        raise FactorRepairError("repair_inspect_write_options_forbidden")
    scopes = []
    for value in args.scope:
        code, start, end = value.split(":")
        scopes.append(FactorRepairScope(code, ((start, end),), args.as_of, args.end,
                      args.daily_basis_start if code == "688689.SH" else None))
    if len({s.ts_code for s in scopes}) != len(scopes):
        raise FactorRepairError("factor_scope_duplicate")
    if args.daily_basis_start and not any(s.ts_code == "688689.SH" for s in scopes):
        raise FactorRepairError("daily_basis_scope_not_approved")
    if args.command == "freeze":
        check_repair_roots(Path(paths.DEFAULT_LAKE_ROOT), args.run_root)
        if {s.ts_code for s in scopes} != {r[0] for r in APPROVED_FACTOR_RANGES} or len(scopes) != 25:
            raise FactorRepairError("factor_scope_not_approved")
        if next(s for s in scopes if s.ts_code == "688689.SH").daily_basis_start_trade_date != "2021-01-27":
            raise FactorRepairError("daily_basis_scope_not_approved")
    from orchestrator.defs.resources import TushareResource

    source = TushareResource(token=os.environ.get("TUSHARE_TOKEN", ""))
    if args.command == "freeze":
        plan = _freeze(args, scopes, source)
        result = {"status": "frozen", "plan_hash": plan["plan_hash"],
                  "plan_path": str(args.run_root / "plan.json")}
        checkpoint = check_repair_path(args.run_root / "checkpoint.json")
        promotion = json.loads(checkpoint.read_text()).get("promotion") if checkpoint.is_file() else None
        if promotion:
            if promotion.get("plan_hash") != plan["plan_hash"]:
                raise FactorRepairError("repair_promotion_record_invalid")
            result.update(status=promotion["status"], next_action="promote")
        print(json.dumps(result))
        return 0
    rows, anchors = [], []
    for scope in scopes:
        print(json.dumps({"phase": "source", "ts_code": scope.ts_code}), file=sys.stderr, flush=True)
        rows.extend(fetch_current_factor_rows(scope, source))
        response = source.call("adj_factor", {"ts_code": scope.ts_code,
                               "trade_date": scope.as_of_trade_date.replace("-", ""),
                               "limit": 6000, "offset": 0}, FACTOR_SOURCE_COLUMNS)
        if (response.columns != FACTOR_SOURCE_COLUMNS or len(response.rows) != 1
                or response.rows[0]["ts_code"] != scope.ts_code
                or response.rows[0]["trade_date"] != scope.as_of_trade_date.replace("-", "")):
            raise FactorRepairError("repair_anchor_source_invalid")
        anchors.append({**response.rows[0], "trade_date": scope.as_of_trade_date})
    observed = run_repair_inspection({"scopes": [asdict(s) for s in scopes],
                                     "source_rows": rows, "anchors": anchors},
                progress=lambda phase, data: print(json.dumps({"phase": phase,
                    "elapsed_seconds": data["elapsed_seconds"], "completed_sql": data["completed_sql"]}),
                    file=sys.stderr, flush=True))
    print(json.dumps(observed, allow_nan=False))
    return int(bool(observed["stop_reasons"]))


if __name__ == "__main__":
    raise SystemExit(main())
