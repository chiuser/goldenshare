"""Inspection, explicit freeze and staging candidates for the approved repair.

Fresh, sequential workers keep DuckDB memory bounded across asset families.
No Dagster instance, job, event or formal file writer is imported here.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FACTOR_SOURCE_COLUMNS,
    REPAIR_PLAN_MAX_BYTES,
    AssetRepairEndpoint,
    FactorRepairError,
    FactorRepairScope,
    RepairBudget,
    atomic_repair_json,
    check_repair_cancel,
    check_repair_path,
    check_repair_roots,
    fetch_current_factor_rows,
    file_identity,
    indicator_repair_target,
    inspect_factor_rows,
    inspect_repair_asset_rows,
    inspect_repair_daily_seed,
    inspect_repair_file_inventory,
    inspect_repair_minute_seed,
    plan_repair_calculation_windows,
    repair_hash,
    repair_implementation_files,
    repair_price_dates,
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
    return tuple(
        FactorRepairScope(
            **{**s, "factor_ranges": tuple(tuple(r) for r in s["factor_ranges"])}
        )
        for s in payload["scopes"]
    )


def _calendar(connection, root: Path, end: str) -> tuple[str, ...]:
    return tuple(
        r[0]
        for r in connection.execute(
            """
      SELECT CAST(trade_date AS VARCHAR) FROM read_parquet(?,hive_partitioning=false)
      WHERE exchange='SSE' AND is_open AND trade_date<=CAST(? AS DATE)
      ORDER BY trade_date
    """,
            [str(paths.silver_trade_calendar_path(root)), end],
        ).fetchall()
    )


def _daily_files(helper, root: Path, start: str, end: str, *, freq=None):
    sample = helper(root, start) if freq is None else helper(root, freq, start)
    return tuple(
        sorted(
            p
            for p in sample.parents[1].glob("trade_date=*/part-000.parquet")
            if start <= p.parent.name.removeprefix("trade_date=") <= end
        )
    )


def _year_files(helper, root: Path, scopes, freq: int, end: str):
    return tuple(
        sorted(
            p
            for s in scopes
            for p in helper(root, freq, s.ts_code, end[:4])
            .parents[1]
            .glob("year=*/part-000.parquet")
            if int(p.parent.name.removeprefix("year=")) <= int(end[:4])
        )
    )


def inspect_repair_daily_source_dates(connection, root: Path, codes, end: str):
    """Independent Silver inventory, including the latest actual row before each target."""
    directory = paths.silver_stock_daily_path(root, end).parents[1]
    inventory = tuple(
        sorted(
            p
            for p in directory.glob("trade_date=*/part-000.parquet")
            if p.parent.name.removeprefix("trade_date=") <= end
        )
    )
    observed = {code: [] for code in codes}
    stats = []
    for offset in range(0, len(inventory), 64):
        batch = inventory[offset : offset + 64]
        before = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in batch]
        rows = connection.execute(
            """SELECT ts_code,CAST(trade_date AS VARCHAR),count(*)
            FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=ANY(?)
            GROUP BY ts_code,trade_date ORDER BY ts_code,trade_date""",
            [[str(p) for p in batch], list(codes)],
        ).fetchall()
        for code, day, count in rows:
            if count != 1 or day in observed[code]:
                raise FactorRepairError("repair_daily_source_duplicate_key")
            observed[code].append(day)
        for name, size, mtime in before:
            st = Path(name).stat()
            if (st.st_size, st.st_mtime_ns) != (size, mtime):
                raise FactorRepairError("input_drift")
        stats.extend(before)
    return (
        {code: tuple(sorted(days)) for code, days in observed.items()},
        inventory,
        stats,
    )


def _history_input_counts(connection, profiles, source_paths, *, freq, input_stats):
    """Exact nine-turn full-history counts, bounded reads and independent endpoints."""
    cutoffs = ",".join(
        f"({duckdb_string(p['ts_code'])},{('DATE' if freq is None else 'TIMESTAMP')} {duckdb_string(p['end_time'])})"
        for p in profiles
    )
    counts = {p["ts_code"]: 0 for p in profiles}
    field = "trade_date" if freq is None else "trade_time"
    for offset in range(0, len(source_paths), 64):
        batch = source_paths[offset : offset + 64]
        before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in batch}
        if any(
            name in input_stats and input_stats[name] != identity
            for name, identity in before.items()
        ):
            raise FactorRepairError("input_drift")
        rows = connection.execute(
            f"SELECT b.ts_code,count(*) FROM read_parquet(?,hive_partitioning=false) b JOIN (VALUES {cutoffs}) ends(ts_code,end_time) ON b.ts_code=ends.ts_code AND b.{field}<=ends.end_time GROUP BY b.ts_code",
            [[str(p) for p in source_paths[offset : offset + 64]]],
        ).fetchall()
        for code, n in rows:
            counts[code] += int(n)
        if any(
            (Path(name).stat().st_size, Path(name).stat().st_mtime_ns) != identity
            for name, identity in before.items()
        ):
            raise FactorRepairError("input_drift")
        input_stats.update(before)
    return counts


def _collect_profiles(connection, *, payload, root, scopes, phase, calendar):
    end = max(s.repair_end_trade_date for s in scopes)
    starts = {s.ts_code: s.factor_ranges[0][0] for s in scopes}
    if phase == "daily":
        starts.update(
            {
                s.ts_code: s.daily_basis_start_trade_date
                for s in scopes
                if s.daily_basis_start_trade_date
            }
        )
        specs = (
            ("gold_stock_daily_qfq", paths.gold_stock_daily_qfq_path),
            (
                "gold_stock_daily_trend_channel",
                paths.gold_stock_daily_trend_channel_path,
            ),
            (
                "gold_stock_daily_trend_channel_state",
                paths.gold_stock_daily_trend_channel_state_path,
            ),
            ("gold_stock_daily_qfq_nineturn", paths.gold_stock_daily_qfq_nineturn_path),
        )
        freq = None
    else:
        freq = int(phase)
        specs = (
            (f"gold_stk_mins_qfq_{freq}m", paths.gold_stk_mins_qfq_path),
            (
                f"gold_stk_mins_qfq_macd_kdj_{freq}m",
                paths.gold_stk_mins_qfq_macd_kdj_path,
            ),
            (
                f"gold_stk_mins_qfq_macd_kdj_state_{freq}m",
                paths.gold_stk_mins_qfq_macd_kdj_state_path,
            ),
        )
        if freq >= 30:
            specs += (
                (
                    f"gold_stk_mins_qfq_nineturn_{freq}m",
                    paths.gold_stk_mins_qfq_nineturn_path,
                ),
            )
    dates = tuple(d for d in calendar if d >= min(starts.values()))
    profiles, inputs, targets, seeds = [], set(), set(), {}
    input_stats = {}
    price_profiles = {}
    validation_paths = {}
    history_counts = {}
    if freq is None:
        source_by_code, source_inventory, source_stats = (
            inspect_repair_daily_source_dates(connection, root, starts, end)
        )
        inputs.update(str(p) for p in source_inventory)
        input_stats.update({name: (size, mtime) for name, size, mtime in source_stats})
    factor_dates = {}
    for r in payload["source_rows"]:
        d = r["trade_date"]
        factor_dates.setdefault(r["ts_code"], set()).add(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    for asset, helper in specs:
        annual = freq is not None and "state" not in asset and "nineturn" not in asset
        collect_history = asset == specs[0][0] and (freq is None or freq >= 30)
        selected = (
            _year_files(helper, root, scopes, freq, end)
            if annual
            else _daily_files(
                helper,
                root,
                "0001-01-01" if collect_history else dates[0],
                end,
                freq=freq,
            )
        )
        # Propagation starts from an actual price date, not a suspension/factor date.
        effective_starts = (
            {code: p["calculation_start_date"] for code, p in price_profiles.items()}
            if price_profiles
            else starts
        )
        observed = inspect_repair_asset_rows(
            connection,
            paths=selected,
            scopes=scopes,
            asset_key=asset,
            expected_dates=dates,
            starts=effective_starts,
            freq=freq,
            collect_history=collect_history,
        )
        if collect_history:
            history_counts = observed["history_counts"]
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
                profile["expected_dates"] = tuple(
                    d for d in profile["expected_dates"] if d >= first
                )
                profile["trade_date_rows"] = tuple(
                    (d, n) for d, n in profile["trade_date_rows"] if d >= first
                )
                profile["calculation_rows"] = sum(
                    n for d, n in profile["trade_date_rows"]
                )
                profile["calculation_windows"] = plan_repair_calculation_windows(
                    profile["trade_date_rows"]
                )
                price_profiles[code] = dict(profile)
                if freq is None:
                    source = tuple(
                        d for d in source_by_code[code] if d <= profile["end_time"][:10]
                    )
                    if not set(actual) <= set(source):
                        raise FactorRepairError("repair_daily_source_row_missing")
                    profile["source_dates"] = source
                    profile["source_inventory_paths"] = [
                        str(p) for p in source_inventory
                    ]
                    profile["previous_actual_date"] = max(
                        (d for d in source if d < first), default=None
                    )
                profile["target_dates"] = repair_price_dates(
                    {
                        "source_rows": payload["source_rows"],
                        "scopes": [asdict(s) for s in scopes],
                    },
                    profile,
                    daily=freq is None,
                )
            else:
                profile["target_dates"] = (
                    profile["expected_dates"] if "state" in asset else actual
                )
                if "macd_kdj" in asset:
                    profile["calculation_windows"] = plan_repair_calculation_windows(
                        profile["trade_date_rows"],
                        max_rows=RepairBudget().max_stock_batch_rows - 8,
                    )
            if "macd_kdj" in asset:
                first = price_profiles[code]["calculation_start_date"]
                if code not in seeds:
                    previous = max(d for d in calendar if d < first)
                    state = paths.gold_stk_mins_qfq_macd_kdj_state_path(
                        root, freq, previous
                    )
                    prices = _year_files(
                        paths.gold_stk_mins_qfq_path,
                        root,
                        [next(s for s in scopes if s.ts_code == code)],
                        freq,
                        end,
                    )
                    seeds[code] = inspect_repair_minute_seed(
                        connection,
                        ts_code=code,
                        freq=freq,
                        first_trade_date=first,
                        expected_dates=calendar,
                        price_paths=prices,
                        state_path=state,
                    )
                    inputs.add(str(state))
                    inputs.update(str(p) for p in prices)
                profile.update(seeds[code])
                if "state" not in asset:
                    expected_bars = tuple(
                        d
                        for d in price_profiles[code]["observed_dates"]
                        if d <= profile["end_time"][:10]
                    )
                    if actual != expected_bars:
                        raise FactorRepairError("repair_indicator_price_date_missing")
            for d in profile["target_dates"]:
                p = (
                    helper(root, freq, code, d[:4])
                    if annual
                    else helper(root, d)
                    if freq is None
                    else helper(root, freq, d)
                )
                if not p.is_file():
                    raise FactorRepairError("repair_target_file_missing")
                targets.add(str(p))
            profiles.append(profile)
    if freq is None:
        for code, profile in price_profiles.items():
            seed = inspect_repair_daily_seed(
                connection,
                lake_root=root,
                ts_code=code,
                first_trade_date=profile["calculation_start_date"],
                previous_actual_date=profile["previous_actual_date"],
                expected_dates=calendar,
            )
            if seed["state_path"]:
                inputs.add(seed["state_path"])
            for p in profiles:
                if p["ts_code"] == code and "trend_channel" in p["asset_key"]:
                    p["daily_seed"] = seed
        # Nine-turn needs unchanged earlier Gold history as well.
        nine_profiles = [
            p for p in profiles if p["asset_key"] == "gold_stock_daily_qfq_nineturn"
        ]
        for p in nine_profiles:
            p["full_history_input_rows"] = sum(
                n
                for d, n in history_counts[p["ts_code"]].items()
                if d <= p["end_time"][:10]
            )
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
        nine_profiles = [p for p in profiles if "nineturn" in p["asset_key"]]
        if nine_profiles:
            for p in nine_profiles:
                p["full_history_input_rows"] = sum(
                    n
                    for d, n in history_counts[p["ts_code"]].items()
                    if d <= p["end_time"][:10]
                )
        source_dates = {
            d
            for p in profiles
            if p["asset_key"] == specs[0][0]
            for d in p["target_dates"]
        }
        inputs.update(
            str(paths.silver_stk_mins_path(root, source_freq, d)) for d in source_dates
        )
        inputs.update(str(paths.silver_adj_factor_path(root, d)) for d in source_dates)
        # Only the approved stocks' existing price/result years are dependencies.
        # Shared day files contain other stocks; they never expand annual inventory.
        price_validation = set()
        for profile in price_profiles.values():
            stock = next(s for s in scopes if s.ts_code == profile["ts_code"])
            years = {
                d[:4]
                for p in profiles
                if p["ts_code"] == stock.ts_code
                for d in p["expected_dates"]
            }
            price_validation.update(
                str(p)
                for p in _year_files(
                    paths.gold_stk_mins_qfq_path, root, [stock], freq, end
                )
                if p.parent.name.removeprefix("year=") in years
            )
        indicator_paths = {
            str(paths.gold_stk_mins_qfq_macd_kdj_path(root, freq, p["ts_code"], year))
            for p in profiles
            if "macd_kdj" in p["asset_key"]
            for year in {d[:4] for d in p["expected_dates"]}
        }
        if any(not Path(p).is_file() for p in price_validation | indicator_paths):
            raise FactorRepairError("repair_validation_file_missing")
        inputs.update(price_validation | indicator_paths)
        validation_paths[specs[0][0]] = sorted(price_validation)
        validation_paths[specs[1][0]] = sorted(indicator_paths)
    for asset, _helper in specs[1:]:
        if asset not in validation_paths:
            validation_paths[asset] = sorted(
                str(indicator_repair_target(root, asset, p["ts_code"], freq, d))
                for p in profiles
                if p["asset_key"] == asset
                for d in p["target_dates"]
            )
            validation_paths[asset] = sorted(set(validation_paths[asset]))
    if freq is None:
        previous_dates = {
            max((x for x in calendar if x < d), default=None)
            for p in profiles
            if "trend_channel" in p["asset_key"]
            for d in p["target_dates"]
        }
        inputs.update(
            str(paths.gold_stock_daily_trend_channel_state_path(root, d))
            for d in previous_dates
            if d is not None
        )
    return {
        "profiles": profiles,
        "input_paths": sorted(inputs),
        "target_paths": sorted(targets),
        "calendar_dates": list(calendar),
        "validation_paths": validation_paths,
        "profile_input_stats": [
            (name, *values) for name, values in sorted(input_stats.items())
        ],
    }


class RepairInspectionConnection:
    """Expose completed SQL work, without inventing a total or recalculating it."""

    def __init__(self, connection, phase, progress):
        self.connection = connection
        self.phase = phase
        self.progress = progress
        self.completed = 0

    def execute(self, *args, **kwargs):
        self.connection.execute(*args, **kwargs)
        self.completed += 1
        if self.progress:
            self.progress(
                {
                    "phase": self.phase,
                    "completed_sql": self.completed,
                    "updated_at": time.time(),
                }
            )
        return self

    def __getattr__(self, name):
        return getattr(self.connection, name)


def inspect_repair_worker(
    payload: dict, phase: str, *, lake_root=None, temp_directory=None, progress=None
) -> dict:
    """One bounded read-only family. Dependency paths are injectable only for tests."""
    root = Path(paths.DEFAULT_LAKE_ROOT if lake_root is None else lake_root)
    temp = DEFAULT_DUCKDB_TEMP_DIRECTORY if temp_directory is None else temp_directory
    scopes = _scopes(payload) if phase != "inventory" else ()
    started = time.monotonic()
    with connect_configured_duckdb(
        RepairBudget().connection_settings(temp), temp_policy="existing_no_spill"
    ) as raw_connection:
        connection = RepairInspectionConnection(raw_connection, phase, progress)
        if phase == "factor":
            result = inspect_factor_rows(
                connection, root, scopes, payload["source_rows"]
            )
            anchors = payload["anchors"]
            for s in scopes:
                p = paths.silver_adj_factor_path(root, s.as_of_trade_date)
                rows = connection.execute(
                    """SELECT adj_factor FROM read_parquet(?,hive_partitioning=false)
                  WHERE ts_code=? AND trade_date=CAST(? AS DATE)""",
                    [str(p), s.ts_code, s.as_of_trade_date],
                ).fetchall()
                expected = next(
                    a["adj_factor"] for a in anchors if a["ts_code"] == s.ts_code
                )
                if len(rows) != 1 or rows[0][0] != float(expected):
                    raise FactorRepairError("repair_anchor_drift")
            result["input_paths"] = sorted(
                set(result["factor_files"])
                | {
                    str(paths.silver_stock_lifecycle_path(root)),
                    str(paths.silver_trade_calendar_path(root)),
                    *(
                        str(paths.silver_adj_factor_path(root, s.as_of_trade_date))
                        for s in scopes
                    ),
                }
            )
            result["target_paths"] = result["factor_files"]
        elif phase == "inventory":
            result = inspect_repair_file_inventory(connection, payload["paths"])
        else:
            calendar = _calendar(
                connection, root, max(s.repair_end_trade_date for s in scopes)
            )
            result = _collect_profiles(
                connection,
                payload=payload,
                root=root,
                scopes=scopes,
                phase=phase,
                calendar=calendar,
            )
    result.update(
        phase=phase,
        elapsed_seconds=time.monotonic() - started,
        peak_rss_bytes=_rss_bytes(),
    )
    result["completed_sql"] = connection.completed
    if result["peak_rss_bytes"] > RepairBudget().max_rss:
        raise FactorRepairError("repair_rss_budget_exceeded")
    return result


def run_repair_inspection(payload: dict, *, progress=None, run_phase=None) -> dict:
    """Sequential workers: no source/metadata footer accumulation in a DuckDB process."""
    result = {"workers": [], "profiles": [], "validation_paths": {}}
    inputs, targets, observed_stats = set(), set(), {}
    for phase in (
        "factor",
        "daily",
        "1",
        "5",
        "15",
        "30",
        "60",
        "90",
        "120",
        "inventory",
    ):
        request = (
            {"paths": sorted(inputs | targets)} if phase == "inventory" else payload
        )
        observed = (run_phase or run_repair_preparation_phase)(phase, request)
        observed["combined_peak_rss_bytes"] = observed["peak_rss_bytes"] + _rss_bytes()
        if observed["combined_peak_rss_bytes"] > RepairBudget().max_rss:
            raise FactorRepairError("repair_rss_budget_exceeded")
        result["workers"].append(
            {
                k: observed[k]
                for k in (
                    "phase",
                    "elapsed_seconds",
                    "peak_rss_bytes",
                    "combined_peak_rss_bytes",
                )
            }
        )
        if phase == "inventory":
            result["inventory"] = observed
            actual_stats = {r[0]: tuple(r[1:3]) for r in observed["files"]}
            if any(
                actual_stats.get(name) != stats
                for name, stats in observed_stats.items()
            ):
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
                if (
                    "calendar_dates" in result
                    and result["calendar_dates"] != observed["calendar_dates"]
                ):
                    raise FactorRepairError("repair_calendar_drift")
                result["calendar_dates"] = observed["calendar_dates"]
            if phase == "factor":
                result["factor"] = observed
        if progress:
            progress(phase, observed)
    endpoints = tuple(
        AssetRepairEndpoint(
            **{
                k: (tuple(p[k]) if k == "expected_dates" else p[k])
                for k in (
                    "asset_key",
                    "ts_code",
                    "freq",
                    "calculation_start_date",
                    "end_time",
                    "expected_dates",
                    "calculation_rows",
                )
            },
            **{
                k: (tuple(p[k]) if k == "context_times" else p[k])
                for k in (
                    "previous_expected_date",
                    "seed_last_trade_time",
                    "context_times",
                )
                if k in p
            },
        )
        for p in result["profiles"]
    )
    validate_asset_repair_endpoints(_scopes(payload), endpoints)
    target_inventory = [r for r in result["inventory"]["files"] if r[0] in targets]
    result["target_inventory"] = {
        "files": len(target_inventory),
        "bytes": sum(r[1] for r in target_inventory),
        "full_file_rows": sum(r[3] for r in target_inventory),
    }
    result["stop_reasons"] = (
        ["repair_candidate_estimate_exceeded"]
        if result["target_inventory"]["bytes"] > RepairBudget().max_candidate_bytes
        else []
    )
    result.update(
        input_paths=sorted(inputs),
        target_paths=sorted(targets),
        budget=asdict(RepairBudget()),
        status="inspected_not_frozen",
    )
    return result


def run_repair_preparation_phase(
    phase, request, *, cancel=None, progress=None, parent_lock=None
):
    """Owned subprocess, bounded polling and real completed-SQL progress."""
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        _stop_worker,
        repair_coordinator_termination_guard,
    )

    if parent_lock is not None:
        request = {
            **request,
            "_parent": {
                "coordinator_pid": os.getpid(),
                "plan_lock_fd": parent_lock.fileno(),
                "plan_path": parent_lock.name,
            },
        }
    command = [
        sys.executable,
        "-B",
        "-m",
        "orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli",
        "_inspect_worker",
        phase,
    ]
    with (
        repair_coordinator_termination_guard(),
        subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            pass_fds=(() if parent_lock is None else (parent_lock.fileno(),)),
        ) as child,
    ):
        initial = json.dumps(request, allow_nan=False)
        seen = 0
        try:
            while True:
                check_repair_cancel(cancel)
                try:
                    stdout, stderr = child.communicate(input=initial, timeout=0.1)
                    break
                except subprocess.TimeoutExpired as waiting:
                    initial = None
                    messages = (
                        (waiting.stderr or b"").decode()
                        if isinstance(waiting.stderr, bytes)
                        else (waiting.stderr or "")
                    )
                    for line in messages[seen:].splitlines(keepends=True):
                        if not line.endswith("\n"):
                            break
                        seen += len(line)
                        data = json.loads(line)
                        if progress:
                            progress(data)
            if child.returncode:
                raise FactorRepairError(
                    f"repair_inspection_worker_failed:{phase}:{stderr.strip()[-300:]}"
                )
            return json.loads(stdout)
        finally:
            _stop_worker(child)


class RepairPreparation:
    """Same-run drafts; no candidate can execute before a complete immutable plan."""

    def __init__(self, root, *, request, implementation):
        self.root = check_repair_path(Path(root))
        self.directory = self.root / "checkpoints/preparation"
        self.binding = {
            "version": 2,
            "run_id": self.root.name.removeprefix("run_id="),
            "request_hash": repair_hash(request),
            "implementation_hash": repair_hash(implementation),
        }
        self.implementation = implementation
        self.artifacts = set()
        self.identities = {}
        marker = self.directory / "request.json"
        if self.root.exists() and not marker.is_file():
            raise FactorRepairError("repair_preparation_owner_invalid")
        if marker.exists():
            if json.loads(check_repair_path(marker).read_text()) != self.binding:
                raise FactorRepairError("repair_preparation_binding_invalid")
        else:
            atomic_repair_json(marker, self.binding)
        self.artifacts.add(marker.relative_to(self.root).as_posix())

    def unit(self, name, request, produce, *, cancel=None):
        path = check_repair_path(
            self.directory / (hashlib.sha256(name.encode()).hexdigest() + ".json")
        )
        binding = {
            **self.binding,
            "unit": name,
            "unit_request_hash": repair_hash(request),
        }
        if path.exists():
            record = json.loads(path.read_text())
            if any(record.get(k) != v for k, v in binding.items()) or record.get(
                "record_hash"
            ) != repair_hash({k: v for k, v in record.items() if k != "record_hash"}):
                raise FactorRepairError("repair_preparation_unit_invalid")
            for identity in record.get("identities", []):
                p = check_repair_path(Path(identity["path"]))
                st = p.stat()
                if (st.st_size, st.st_mtime_ns) != (
                    identity["size"],
                    identity["mtime_ns"],
                ):
                    raise FactorRepairError("input_drift")
                self.identities[str(p)] = identity
            value = record["result"]
        else:
            check_repair_cancel(cancel)
            value = produce()
            observed = (
                value.get("profile_input_stats", []) if isinstance(value, dict) else []
            )
            if name == "profile:inventory":
                observed = value["files"]
            elif isinstance(value, dict):
                by_name = {row[0]: row for row in observed}
                for filename in set(value.get("input_paths", ())) | set(
                    value.get("target_paths", ())
                ):
                    if filename not in by_name:
                        st = check_repair_path(Path(filename)).stat()
                        by_name[filename] = (filename, st.st_size, st.st_mtime_ns)
                observed = list(by_name.values())
            identities = []
            for row in observed:
                check_repair_cancel(cancel)
                filename, size, mtime = row[:3]
                identity = self.identities.get(filename)
                if identity is None:
                    identity = asdict(file_identity(Path(filename), cancel=cancel))
                    self.identities[filename] = identity
                if (identity["size"], identity["mtime_ns"]) != (size, mtime):
                    raise FactorRepairError("input_drift")
                identities.append(identity)
            record = {**binding, "result": value, "identities": identities}
            record["record_hash"] = repair_hash(record)
            check_repair_cancel(cancel)
            atomic_repair_json(path, record)
        self.artifacts.add(path.relative_to(self.root).as_posix())
        return value

    def seal(self, source_rows):
        expected = {str(self.root / p) for p in self.artifacts}

        def walk_error(error):
            raise error

        for directory, dirs, files in os.walk(
            self.root, followlinks=False, onerror=walk_error
        ):
            for name in dirs + files:
                check_repair_path(Path(directory) / name)
            for name in files:
                if str(Path(directory) / name) not in expected:
                    raise FactorRepairError("repair_unowned_artifact")
        return {
            **self.binding,
            "source_hash": repair_hash(source_rows),
            "identities": self.identities,
            "implementation": self.implementation,
            "artifacts": sorted(self.artifacts),
        }


def prepare_scoped_repair_inputs(
    *, root, scopes, source, parent_lock, progress=None, cancel=None, run_phase=None
):
    """One resumable authoritative planner for freeze; inspect remains read-only."""
    request = {"scopes": [asdict(s) for s in scopes]}
    check_repair_roots(Path(paths.DEFAULT_LAKE_ROOT), Path(root))
    existing = Path(root) / "plan.json"
    if existing.exists():
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
            load_repair_plan,
        )

        if check_repair_path(existing).stat().st_size > REPAIR_PLAN_MAX_BYTES:
            raise FactorRepairError("repair_plan_size_exceeded")
        saved = json.loads(existing.read_text())
        plan = load_repair_plan(existing, saved["plan_hash"], cancel=cancel)
        if repair_hash(plan["scopes"]) != repair_hash(request["scopes"]):
            raise FactorRepairError("repair_preparation_binding_invalid")
        return {"frozen_plan": plan}
    if parent_lock.closed:
        raise FactorRepairError("repair_parent_guard_invalid")
    # The CLI holds this lock through preparation and the atomic plan freeze.
    implementation = [
        asdict(file_identity(p, cancel=cancel))
        for p in repair_implementation_files()
    ]
    draft = RepairPreparation(root, request=request, implementation=implementation)
    rows = []
    anchors = []
    for scope in scopes:
        check_repair_cancel(cancel)
        rows.extend(
            draft.unit(
                "source:" + scope.ts_code,
                asdict(scope),
                lambda s=scope: list(
                    fetch_current_factor_rows(s, source, cancel=cancel)
                ),
                cancel=cancel,
            )
        )
        params = {
            "ts_code": scope.ts_code,
            "trade_date": scope.as_of_trade_date.replace("-", ""),
            "limit": 6000,
            "offset": 0,
        }

        def anchor(params=params, scope=scope):
            response = source.call("adj_factor", params, FACTOR_SOURCE_COLUMNS)
            if (
                tuple(response.columns) != FACTOR_SOURCE_COLUMNS
                or len(response.rows) != 1
                or response.rows[0]["ts_code"] != scope.ts_code
                or response.rows[0]["trade_date"] != params["trade_date"]
            ):
                raise FactorRepairError("repair_anchor_source_invalid")
            return {**response.rows[0], "trade_date": scope.as_of_trade_date}

        anchors.append(
            draft.unit("anchor:" + scope.ts_code, params, anchor, cancel=cancel)
        )
        if progress:
            progress(
                {
                    "phase": "source",
                    "completed_source_units": len(anchors) * 2,
                    "ts_code": scope.ts_code,
                }
            )
    payload = {**request, "source_rows": rows, "anchors": anchors}

    def family(phase, data):
        return draft.unit(
            "profile:" + phase,
            data,
            lambda: (
                run_phase(phase, data)
                if run_phase
                else run_repair_preparation_phase(
                    phase, data, cancel=cancel, progress=progress, parent_lock=parent_lock
                )
            ),
            cancel=cancel,
        )

    observed = run_repair_inspection(
        payload,
        run_phase=family,
        progress=lambda phase, data: (
            progress(
                {
                    "phase": phase,
                    "elapsed_seconds": data["elapsed_seconds"],
                    "peak_rss_bytes": data["peak_rss_bytes"],
                }
            )
            if progress
            else None
        ),
    )
    return {
        "observed": observed,
        "source_rows": rows,
        "anchors": anchors,
        "preparation": draft.seal(rows),
    }
