"""Inspection, explicit freeze and staging candidates for the approved repair.

Fresh, sequential workers keep DuckDB memory bounded across asset families.
No Dagster instance, job, event or formal file writer is imported here.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    APPROVED_FACTOR_RANGES,
    FACTOR_SOURCE_COLUMNS,
    AssetRepairEndpoint,
    FactorRepairError,
    FactorRepairScope,
    RepairBudget,
    check_repair_roots,
    fetch_current_factor_rows,
    freeze_stock_factor_repair,
    indicator_repair_target,
    inspect_factor_rows,
    inspect_repair_asset_rows,
    inspect_repair_daily_seed,
    inspect_repair_file_inventory,
    inspect_repair_minute_seed,
    inspect_repair_writers,
    plan_repair_calculation_windows,
    repair_price_dates,
    repair_units_from_inspection,
    validate_asset_repair_endpoints,
)
from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_TEMP_DIRECTORY,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import duckdb_string


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _scopes(payload) -> tuple[FactorRepairScope, ...]:
    return tuple(FactorRepairScope(**{**s, "factor_ranges": tuple(tuple(r) for r in s["factor_ranges"])})
                 for s in payload["scopes"])


def _calendar(connection, root: Path, end: str) -> tuple[str, ...]:
    return tuple(r[0] for r in connection.execute("""
      SELECT CAST(trade_date AS VARCHAR) FROM read_parquet(?,hive_partitioning=false)
      WHERE exchange='SSE' AND is_open AND trade_date<=CAST(? AS DATE)
      ORDER BY trade_date
    """, [str(paths.silver_trade_calendar_path(root)), end]).fetchall())


def _daily_files(helper, root: Path, start: str, end: str, *, freq=None):
    sample = helper(root, start) if freq is None else helper(root, freq, start)
    return tuple(sorted(p for p in sample.parents[1].glob("trade_date=*/part-000.parquet")
                        if start <= p.parent.name.removeprefix("trade_date=") <= end))


def _year_files(helper, root: Path, scopes, freq: int, end: str):
    return tuple(sorted(p for s in scopes
                        for p in helper(root, freq, s.ts_code, end[:4]).parents[1].glob("year=*/part-000.parquet")
                        if int(p.parent.name.removeprefix("year=")) <= int(end[:4])))


def inspect_repair_daily_source_dates(connection, root: Path, codes, end: str):
    """Independent Silver inventory, including the latest actual row before each target."""
    directory = paths.silver_stock_daily_path(root,end).parents[1]
    inventory = tuple(sorted(p for p in directory.glob("trade_date=*/part-000.parquet")
                             if p.parent.name.removeprefix("trade_date=") <= end))
    observed = {code: [] for code in codes}
    stats = []
    for offset in range(0,len(inventory),64):
        batch = inventory[offset:offset+64]
        before = [(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in batch]
        rows = connection.execute("""SELECT ts_code,CAST(trade_date AS VARCHAR),count(*)
            FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=ANY(?)
            GROUP BY ts_code,trade_date ORDER BY ts_code,trade_date""",
            [[str(p) for p in batch],list(codes)]).fetchall()
        for code,day,count in rows:
            if count != 1 or day in observed[code]:
                raise FactorRepairError("repair_daily_source_duplicate_key")
            observed[code].append(day)
        for name,size,mtime in before:
            st = Path(name).stat()
            if (st.st_size,st.st_mtime_ns) != (size,mtime):
                raise FactorRepairError("input_drift")
        stats.extend(before)
    return {code:tuple(sorted(days)) for code,days in observed.items()}, inventory, stats


def _history_input_counts(connection,profiles,source_paths,*,freq,input_stats):
    """Exact nine-turn full-history counts, bounded reads and independent endpoints."""
    cutoffs=','.join(f"({duckdb_string(p['ts_code'])},{('DATE' if freq is None else 'TIMESTAMP')} {duckdb_string(p['end_time'])})" for p in profiles)
    counts={p['ts_code']:0 for p in profiles}
    field='trade_date' if freq is None else 'trade_time'
    for offset in range(0,len(source_paths),64):
        batch=source_paths[offset:offset+64]
        before={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in batch}
        if any(name in input_stats and input_stats[name]!=identity for name,identity in before.items()):
            raise FactorRepairError('input_drift')
        rows=connection.execute(f"SELECT b.ts_code,count(*) FROM read_parquet(?,hive_partitioning=false) b JOIN (VALUES {cutoffs}) ends(ts_code,end_time) ON b.ts_code=ends.ts_code AND b.{field}<=ends.end_time GROUP BY b.ts_code",[[str(p) for p in source_paths[offset:offset+64]]]).fetchall()
        for code,n in rows:counts[code]+=int(n)
        if any((Path(name).stat().st_size,Path(name).stat().st_mtime_ns)!=identity for name,identity in before.items()):
            raise FactorRepairError('input_drift')
        input_stats.update(before)
    return counts


def _collect_profiles(connection, *, payload, root, scopes, phase, calendar):
    end = max(s.repair_end_trade_date for s in scopes)
    starts = {s.ts_code: s.factor_ranges[0][0] for s in scopes}
    if phase == "daily":
        starts.update({s.ts_code: s.daily_basis_start_trade_date for s in scopes
                       if s.daily_basis_start_trade_date})
        specs = (("gold_stock_daily_qfq", paths.gold_stock_daily_qfq_path),
                 ("gold_stock_daily_trend_channel", paths.gold_stock_daily_trend_channel_path),
                 ("gold_stock_daily_trend_channel_state", paths.gold_stock_daily_trend_channel_state_path),
                 ("gold_stock_daily_qfq_nineturn", paths.gold_stock_daily_qfq_nineturn_path))
        freq = None
    else:
        freq = int(phase)
        specs = ((f"gold_stk_mins_qfq_{freq}m", paths.gold_stk_mins_qfq_path),
                 (f"gold_stk_mins_qfq_macd_kdj_{freq}m", paths.gold_stk_mins_qfq_macd_kdj_path),
                 (f"gold_stk_mins_qfq_macd_kdj_state_{freq}m", paths.gold_stk_mins_qfq_macd_kdj_state_path))
        if freq >= 30:
            specs += ((f"gold_stk_mins_qfq_nineturn_{freq}m", paths.gold_stk_mins_qfq_nineturn_path),)
    dates = tuple(d for d in calendar if d >= min(starts.values()))
    profiles, inputs, targets, seeds = [], set(), set(), {}
    input_stats = {}
    price_profiles = {}
    validation_paths = {}
    if freq is None:
        source_by_code, source_inventory, source_stats = inspect_repair_daily_source_dates(connection,root,starts,end)
        inputs.update(str(p) for p in source_inventory)
        input_stats.update({name:(size,mtime) for name,size,mtime in source_stats})
    factor_dates = {}
    for r in payload["source_rows"]:
        d = r["trade_date"]
        factor_dates.setdefault(r["ts_code"], set()).add(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    for asset, helper in specs:
        annual = freq is not None and "state" not in asset and "nineturn" not in asset
        selected = (_year_files(helper, root, scopes, freq, end) if annual else
                    _daily_files(helper, root, dates[0], end, freq=freq))
        # Propagation starts from an actual price date, not a suspension/factor date.
        effective_starts = ({code: p["calculation_start_date"] for code, p in price_profiles.items()}
                            if price_profiles else starts)
        observed = inspect_repair_asset_rows(connection, paths=selected, scopes=scopes,
                    asset_key=asset, expected_dates=dates, starts=effective_starts, freq=freq)
        inputs.update(p[0] for p in observed["inputs"])
        for name, size, mtime in observed["inputs"]:
            if name in input_stats and input_stats[name] != (size, mtime):
                raise FactorRepairError("input_drift")
            input_stats[name] = (size, mtime)
        for profile in observed["profiles"]:
            code = profile["ts_code"]
            actual = profile["observed_dates"]
            if not price_profiles or asset == specs[0][0]:
                first = min(actual)
                profile["calculation_start_date"] = first
                profile["expected_dates"] = tuple(d for d in profile["expected_dates"] if d >= first)
                profile["trade_date_rows"] = tuple((d,n) for d,n in profile["trade_date_rows"] if d >= first)
                profile["calculation_rows"] = sum(n for d,n in profile["trade_date_rows"])
                profile["calculation_windows"] = plan_repair_calculation_windows(profile["trade_date_rows"])
                price_profiles[code] = dict(profile)
                if freq is None:
                    source = tuple(d for d in source_by_code[code] if d <= profile["end_time"][:10])
                    if not set(actual) <= set(source):
                        raise FactorRepairError("repair_daily_source_row_missing")
                    profile["source_dates"] = source
                    profile["source_inventory_paths"] = [str(p) for p in source_inventory]
                    profile["previous_actual_date"] = max((d for d in source if d < first),default=None)
                profile["target_dates"] = repair_price_dates(
                    {"source_rows":payload["source_rows"],"scopes":[asdict(s) for s in scopes]},
                    profile,daily=freq is None)
            else:
                profile["target_dates"] = profile["expected_dates"] if "state" in asset else actual
                if "macd_kdj" in asset:
                    profile["calculation_windows"] = plan_repair_calculation_windows(
                        profile["trade_date_rows"],max_rows=RepairBudget().max_stock_batch_rows-8)
            if "macd_kdj" in asset:
                first = price_profiles[code]["calculation_start_date"]
                if code not in seeds:
                    previous = max(d for d in calendar if d < first)
                    state = paths.gold_stk_mins_qfq_macd_kdj_state_path(root, freq, previous)
                    prices = _year_files(paths.gold_stk_mins_qfq_path, root,
                                         [next(s for s in scopes if s.ts_code == code)], freq, end)
                    seeds[code] = inspect_repair_minute_seed(connection, ts_code=code,
                                  freq=freq, first_trade_date=first, expected_dates=calendar,
                                  price_paths=prices, state_path=state)
                    inputs.add(str(state))
                    inputs.update(str(p) for p in prices)
                profile.update(seeds[code])
                if "state" not in asset:
                    expected_bars = tuple(d for d in price_profiles[code]["observed_dates"]
                                          if d <= profile["end_time"][:10])
                    if actual != expected_bars:
                        raise FactorRepairError("repair_indicator_price_date_missing")
            for d in profile["target_dates"]:
                p = (helper(root, freq, code, d[:4]) if annual else
                     helper(root, d) if freq is None else helper(root, freq, d))
                if not p.is_file():
                    raise FactorRepairError("repair_target_file_missing")
                targets.add(str(p))
            profiles.append(profile)
    if freq is None:
        for code, profile in price_profiles.items():
            seed = inspect_repair_daily_seed(connection, lake_root=root, ts_code=code,
                first_trade_date=profile["calculation_start_date"],
                previous_actual_date=profile["previous_actual_date"], expected_dates=calendar)
            if seed["state_path"]:
                inputs.add(seed["state_path"])
            for p in profiles:
                if p["ts_code"] == code and "trend_channel" in p["asset_key"]:
                    p["daily_seed"] = seed
        # Nine-turn needs unchanged earlier Gold history as well.
        full = paths.gold_stock_daily_qfq_path(root, end).parents[1]
        history_paths = sorted(p for p in full.glob("trade_date=*/part-000.parquet")
                               if p.parent.name.removeprefix("trade_date=") <= end)
        inputs.update(str(p) for p in history_paths)
        nine_profiles=[p for p in profiles if p['asset_key']=='gold_stock_daily_qfq_nineturn']
        history_counts=_history_input_counts(connection,nine_profiles,history_paths,freq=None,input_stats=input_stats)
        for p in nine_profiles:p['full_history_input_rows']=history_counts[p['ts_code']]
        source_dates = set()
        for p in profiles:
            if p["asset_key"] != "gold_stock_daily_qfq":
                continue
            order = p["source_dates"]
            previous = {d: before for before, d in pairwise(order)}
            if p["previous_actual_date"]:
                previous[order[0]] = p["previous_actual_date"]
            source_dates.update(p["target_dates"])
            source_dates.update(previous[d] for d in p["target_dates"] if d in previous)
        inputs.update(str(paths.silver_stock_daily_path(root, d)) for d in source_dates)
        inputs.update(str(paths.silver_adj_factor_path(root, d)) for d in source_dates)
    else:
        from orchestrator.defs.stk_mins_qfq import gold_stk_mins_qfq_source_freq
        source_freq = gold_stk_mins_qfq_source_freq(freq)
        nine_profiles=[p for p in profiles if 'nineturn' in p['asset_key']]
        if nine_profiles:
            history_paths=sorted({path for p in nine_profiles for path in _year_files(paths.gold_stk_mins_qfq_path,root,
                [next(s for s in scopes if s.ts_code==p['ts_code'])],freq,p['end_time'][:10])})
            inputs.update(str(p) for p in history_paths)
            history_counts=_history_input_counts(connection,nine_profiles,history_paths,freq=freq,input_stats=input_stats)
            for p in nine_profiles:p['full_history_input_rows']=history_counts[p['ts_code']]
        source_dates = {d for p in profiles if p["asset_key"] == specs[0][0] for d in p["target_dates"]}
        inputs.update(str(paths.silver_stk_mins_path(root, source_freq, d)) for d in source_dates)
        inputs.update(str(paths.silver_adj_factor_path(root, d)) for d in source_dates)
        # Full blocking coverage inputs, never repair targets for unapproved stocks.
        expected = set()
        dates = sorted(source_dates)
        for offset in range(0,len(dates),64):
            batch = dates[offset:offset+64]
            source_paths = [paths.silver_stk_mins_path(root,source_freq,d) for d in batch]
            rows = connection.execute("""SELECT DISTINCT ts_code,strftime(trade_date,'%Y')
                FROM read_parquet(?,hive_partitioning=false) WHERE CAST(trade_date AS VARCHAR)=ANY(?)""",
                [[str(p) for p in source_paths],batch]).fetchall()
            expected.update(str(paths.gold_stk_mins_qfq_path(root,freq,code,year)) for code,year in rows)
        if any(not Path(name).is_file() for name in expected):
            raise FactorRepairError("repair_validation_file_missing")
        inputs.update(expected)
        validation_paths[specs[0][0]] = sorted(expected)
        # Indicator coverage spans the replay, including unchanged later prices.
        price_validation=set(expected)
        for p in profiles:
            if p["asset_key"]==specs[0][0]:
                price_validation.update(str(name) for name in _year_files(
                    paths.gold_stk_mins_qfq_path,root,[next(s for s in scopes if s.ts_code==p["ts_code"])],freq,end))
        # Existing price inventory is the exact full-market input for indicator checks.
        directory=paths.gold_stk_mins_qfq_path(root,freq,scopes[0].ts_code,end[:4]).parents[2]
        years={d[:4] for p in profiles for d in p["expected_dates"]}
        price_validation.update(str(p) for y in years for p in directory.glob(f"ts_code=*/year={y}/part-000.parquet"))
        price_validation={p for p in price_validation if Path(p).parent.name.removeprefix("year=") in years}
        inputs.update(price_validation)
        indicator_paths=set()
        replay_dates=sorted({d for p in profiles if 'macd_kdj' in p['asset_key'] for d in p['expected_dates']})
        files=sorted(price_validation)
        for offset in range(0,len(files),64):
            identities=connection.execute("""SELECT DISTINCT ts_code,strftime(trade_date,'%Y')
                FROM read_parquet(?,hive_partitioning=false) WHERE CAST(trade_date AS VARCHAR)=ANY(?)""",
                [files[offset:offset+64],replay_dates]).fetchall()
            indicator_paths.update(str(paths.gold_stk_mins_qfq_macd_kdj_path(root,freq,code,year)) for code,year in identities)
        if any(not Path(p).is_file() for p in indicator_paths):
            raise FactorRepairError("repair_validation_file_missing")
        inputs.update(indicator_paths)
        validation_paths[specs[1][0]]=sorted(indicator_paths)
        validation_paths[specs[0][0]]=sorted(price_validation)
    for asset,_helper in specs[1:]:
        if asset not in validation_paths:
            validation_paths[asset]=sorted(str(indicator_repair_target(root,asset,p["ts_code"],freq,d))
                for p in profiles if p["asset_key"]==asset for d in p["target_dates"])
            validation_paths[asset]=sorted(set(validation_paths[asset]))
    if freq is None:
        previous_dates={max((x for x in calendar if x<d),default=None) for p in profiles
            if 'trend_channel' in p['asset_key'] for d in p['target_dates']}
        inputs.update(str(paths.gold_stock_daily_trend_channel_state_path(root,d)) for d in previous_dates if d is not None)
    return {"profiles": profiles, "input_paths": sorted(inputs), "target_paths": sorted(targets),
            "calendar_dates": list(calendar),
            "validation_paths": validation_paths,
            "profile_input_stats": [(name, *values) for name, values in sorted(input_stats.items())]}


def inspect_repair_worker(payload: dict, phase: str, *, lake_root=None, temp_directory=None) -> dict:
    """One bounded read-only family. Dependency paths are injectable only for tests."""
    root = Path(paths.DEFAULT_LAKE_ROOT if lake_root is None else lake_root)
    temp = DEFAULT_DUCKDB_TEMP_DIRECTORY if temp_directory is None else temp_directory
    scopes = _scopes(payload) if phase != "inventory" else ()
    started = time.monotonic()
    with connect_configured_duckdb(RepairBudget().connection_settings(temp),
                                  temp_policy="existing_no_spill") as connection:
        if phase == "factor":
            result = inspect_factor_rows(connection, root, scopes, payload["source_rows"])
            anchors = payload["anchors"]
            for s in scopes:
                p = paths.silver_adj_factor_path(root, s.as_of_trade_date)
                rows = connection.execute("""SELECT adj_factor FROM read_parquet(?,hive_partitioning=false)
                  WHERE ts_code=? AND trade_date=CAST(? AS DATE)""",
                  [str(p), s.ts_code, s.as_of_trade_date]).fetchall()
                expected = next(a["adj_factor"] for a in anchors if a["ts_code"] == s.ts_code)
                if len(rows) != 1 or rows[0][0] != float(expected):
                    raise FactorRepairError("repair_anchor_drift")
            result["input_paths"] = sorted(set(result["factor_files"]) | {
                str(paths.silver_stock_lifecycle_path(root)), str(paths.silver_trade_calendar_path(root)),
                *(str(paths.silver_adj_factor_path(root, s.as_of_trade_date)) for s in scopes)})
            result["target_paths"] = result["factor_files"]
        elif phase == "inventory":
            result = inspect_repair_file_inventory(connection, payload["paths"])
        else:
            calendar = _calendar(connection, root, max(s.repair_end_trade_date for s in scopes))
            result = _collect_profiles(connection, payload=payload, root=root, scopes=scopes,
                                       phase=phase, calendar=calendar)
    result.update(phase=phase, elapsed_seconds=time.monotonic() - started, peak_rss_bytes=_rss_bytes())
    if result["peak_rss_bytes"] > RepairBudget().max_rss:
        raise FactorRepairError("repair_rss_budget_exceeded")
    return result


def run_repair_inspection(payload: dict, *, progress=None) -> dict:
    """Sequential workers: no source/metadata footer accumulation in a DuckDB process."""
    result = {"workers": [], "profiles": [], "validation_paths": {}}
    inputs, targets, observed_stats = set(), set(), {}
    for phase in ("factor", "daily", "1", "5", "15", "30", "60", "90", "120", "inventory"):
        request = {"paths": sorted(inputs | targets)} if phase == "inventory" else payload
        child = subprocess.Popen([sys.executable, "-B", "-m", __name__, "_inspect_worker", phase],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = child.communicate(json.dumps(request, allow_nan=False))
        if child.returncode:
            raise FactorRepairError(f"repair_inspection_worker_failed:{phase}:{stderr.strip()[-300:]}")
        observed = json.loads(stdout)
        observed["combined_peak_rss_bytes"] = observed["peak_rss_bytes"] + _rss_bytes()
        if observed["combined_peak_rss_bytes"] > RepairBudget().max_rss:
            raise FactorRepairError("repair_rss_budget_exceeded")
        result["workers"].append({k: observed[k] for k in ("phase", "elapsed_seconds", "peak_rss_bytes", "combined_peak_rss_bytes")})
        if phase == "inventory":
            result["inventory"] = observed
            actual_stats = {r[0]: tuple(r[1:3]) for r in observed["files"]}
            if any(actual_stats.get(name) != stats for name, stats in observed_stats.items()):
                raise FactorRepairError("input_drift")
        else:
            for name, size, mtime in observed.get("profile_input_stats", ()):
                if name in observed_stats and observed_stats[name] != (size, mtime):
                    raise FactorRepairError("input_drift")
                observed_stats[name] = (size, mtime)
            inputs.update(observed["input_paths"])
            targets.update(observed["target_paths"])
            result["profiles"].extend(observed.get("profiles", ()))
            result["validation_paths"].update(observed.get("validation_paths", {}))
            if "calendar_dates" in observed:
                if "calendar_dates" in result and result["calendar_dates"]!=observed["calendar_dates"]:
                    raise FactorRepairError("repair_calendar_drift")
                result["calendar_dates"]=observed["calendar_dates"]
            if phase == "factor":
                result["factor"] = observed
        if progress:
            progress(phase, observed)
    endpoints = tuple(AssetRepairEndpoint(**{k: (tuple(p[k]) if k == "expected_dates" else p[k]) for k in (
        "asset_key", "ts_code", "freq", "calculation_start_date", "end_time", "expected_dates", "calculation_rows")},
        **{k: (tuple(p[k]) if k == "context_times" else p[k]) for k in ("previous_expected_date", "seed_last_trade_time", "context_times") if k in p})
        for p in result["profiles"])
    validate_asset_repair_endpoints(_scopes(payload), endpoints)
    target_inventory = [r for r in result["inventory"]["files"] if r[0] in targets]
    result["target_inventory"] = {"files": len(target_inventory),
        "bytes": sum(r[1] for r in target_inventory), "full_file_rows": sum(r[3] for r in target_inventory)}
    result["stop_reasons"] = (["repair_candidate_estimate_exceeded"]
        if result["target_inventory"]["bytes"] > RepairBudget().max_candidate_bytes else [])
    result.update(input_paths=sorted(inputs), target_paths=sorted(targets),
                  budget=asdict(RepairBudget()), status="inspected_not_frozen")
    return result


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
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
    if len(argv) == 2 and argv[0] == "_inspect_worker":
        request = sys.stdin.read(4 * 1024**2 + 1)
        if len(request) > 4 * 1024**2:
            raise FactorRepairError("repair_inspection_input_budget_exceeded")
        print(json.dumps(inspect_repair_worker(json.loads(request), argv[1]), allow_nan=False))
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
                    "elapsed_seconds": data["elapsed_seconds"], "peak_rss_bytes": data["peak_rss_bytes"]}),
                    file=sys.stderr, flush=True))
    if args.command == "freeze":
        if observed["stop_reasons"]:
            raise FactorRepairError(observed["stop_reasons"][0])
        # Require an existing PostgreSQL instance before calling DagsterInstance.get.
        import dagster as dg
        import yaml

        from orchestrator.definitions import defs

        home = os.environ.get("DAGSTER_HOME", "")
        config = Path(home) / "dagster.yaml"
        if not home or not config.is_file() or config.stat().st_size > 64 * 1024:
            raise FactorRepairError("repair_existing_instance_required")
        configured = yaml.safe_load(config.read_text())
        if not isinstance(configured, dict) or "postgres" not in configured.get("storage", {}):
            raise FactorRepairError("repair_existing_postgres_instance_required")
        os.environ["PGOPTIONS"] = (os.environ.get("PGOPTIONS", "")
            + " -c default_transaction_read_only=on -c statement_timeout=10000")
        from orchestrator.defs.stock_factor_price_checks import ADJ_FACTOR_PARTITION_SET

        with dg.DagsterInstance.get() as instance:
            definitions = defs()
            def writer_guard():
                writers = inspect_repair_writers(definitions, instance,
                    input_paths=observed["input_paths"], lake_root=Path(paths.DEFAULT_LAKE_ROOT))
                if not writers["idle"]:
                    raise FactorRepairError("repair_writers_not_idle")
            endpoints = tuple(AssetRepairEndpoint(**{k: (tuple(p[k]) if k in ("expected_dates", "context_times") else p[k])
                for k in AssetRepairEndpoint.__dataclass_fields__ if k in p}) for p in observed["profiles"])
            plan = freeze_stock_factor_repair(lake_root=Path(paths.DEFAULT_LAKE_ROOT),
                run_root=args.run_root, scopes=scopes, source_rows=rows, anchors=anchors,
                endpoints=endpoints, input_stats=[r[:3] for r in observed["inventory"]["files"]],
                target_paths=observed["target_paths"],
                units=repair_units_from_inspection(observed, lake_root=Path(paths.DEFAULT_LAKE_ROOT)),
                writer_guard=writer_guard, partition_validation={
                    "partition_set": ADJ_FACTOR_PARTITION_SET,
                    "registered_keys": sorted(instance.get_dynamic_partitions(ADJ_FACTOR_PARTITION_SET)),
                    "indicator_sets": {name:sorted(instance.get_dynamic_partitions(name)) for name in (
                        "cn_a_stock_daily_trend_channel_trade_days","cn_a_stock_trade_days","cn_a_stock_mins_silver_trade_days")},
                    "checked_on": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()})
        print(json.dumps({"status": "frozen", "plan_hash": plan["plan_hash"],
                          "plan_path": str(args.run_root / "plan.json")}))
    else:
        print(json.dumps(observed, allow_nan=False))
    return int(bool(observed["stop_reasons"]))


if __name__ == "__main__":
    raise SystemExit(main())
