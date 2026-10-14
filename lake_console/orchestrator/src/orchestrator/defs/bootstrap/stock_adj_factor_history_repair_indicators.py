"""Bounded indicator replay and complete-file candidates for the approved repair."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    RepairBudget,
    atomic_repair_json,
    check_repair_cancel,
    check_repair_path,
    file_identity,
    indicator_repair_assets,
    indicator_repair_target,
    plan_repair_calculation_windows,
    repair_asset_for_path,
    repair_hash,
    sync_repair_directory,
    validate_indicator_repair_units,
    write_candidate_record,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    RepairCandidateInputs,
    assert_repair_schema,
    build_scoped_file_candidate,
    read_repair_candidate_record,
    repair_record_path,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.run_contracts import asset_column_schemas as schemas


def _read(files):
    if not files:
        raise FactorRepairError("repair_indicator_input_missing")
    queries = [
        f"SELECT * FROM read_parquet([{','.join(duckdb_string(str(p)) for p in files[i : i + 64])}],hive_partitioning=false)"
        for i in range(0, len(files), 64)
    ]
    return "(" + " UNION ALL ".join(queries) + ")"


def _columns(schema):
    return ",".join('"' + c.name + '"' for c in schema)


def _days(days):
    return "(" + ",".join("DATE " + duckdb_string(d) for d in days) + ")"


def _count(connection, query):
    return int(connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0])


def indicator_schema(asset):
    if asset not in indicator_repair_assets():
        raise FactorRepairError("repair_phase_not_supported")
    if asset == "gold_stock_daily_trend_channel":
        return schemas.GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA
    if asset == "gold_stock_daily_trend_channel_state":
        return schemas.GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
    if asset == "gold_stock_daily_qfq_nineturn":
        return schemas.GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
    if "nineturn" in asset:
        return schemas.GOLD_STK_MINS_QFQ_NINETURN_SCHEMA
    return (
        schemas.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA
        if "_state_" in asset
        else schemas.GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA
    )


def indicator_replay_tasks(plan):
    """One stock/family/frequency; result and state share a continuous calculation."""
    tasks = []
    for unit in plan["units"]:
        asset = unit["asset_key"]
        if asset not in indicator_repair_assets() or "_state" in asset:
            continue
        for p in unit["calculation_windows"]:
            state_asset = (
                "gold_stock_daily_trend_channel_state"
                if "trend_channel" in asset
                else f"gold_stk_mins_qfq_macd_kdj_state_{p['freq']}m"
                if "macd_kdj" in asset
                else None
            )
            state = (
                next(
                    w
                    for u in plan["units"]
                    if u["asset_key"] == state_asset
                    for w in u["calculation_windows"]
                    if w["ts_code"] == p["ts_code"]
                )
                if state_asset
                else None
            )
            task = {
                "asset_key": asset,
                "profile": p,
                "state_asset": state_asset,
                "state_profile": state,
                "calendar_dates": unit["calendar_dates"],
            }
            task["task_id"] = repair_hash([plan["plan_hash"], task])
            tasks.append(task)
    return sorted(tasks, key=lambda t: (t["asset_key"], t["profile"]["ts_code"]))


def _task_root(plan, task):
    if task.get("task_id") != repair_hash(
        [plan["plan_hash"], {k: v for k, v in task.items() if k != "task_id"}]
    ):
        raise FactorRepairError("repair_indicator_task_invalid")
    return check_repair_path(
        Path(plan["run_root"]) / "inputs/indicator_replay" / task["task_id"]
    )


def _receipt(plan, task, number):
    return _task_root(plan, task) / f"segment-{number}.json"


def read_indicator_fragment(plan, task, number):
    path = check_repair_path(_receipt(plan, task, number))
    proof = json.loads(path.read_text())
    if (
        proof.get("plan_hash") != plan["plan_hash"]
        or proof.get("task_id") != task["task_id"]
        or proof.get("number") != number
        or proof.get("validated") is not True
        or proof.get("record_hash")
        != repair_hash({k: v for k, v in proof.items() if k != "record_hash"})
    ):
        raise FactorRepairError("repair_indicator_fragment_invalid")
    for kind, identity in proof["outputs"].items():
        expected = _task_root(plan, task) / f"{kind}-{number}.parquet"
        if (
            identity["path"] != str(expected)
            or asdict(file_identity(expected)) != identity
        ):
            raise FactorRepairError("repair_indicator_fragment_drift")
    return proof


def _persist_fragment(
    connection, plan, task, number, days, queries, inputs, previous, *, audit, cancel
):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        bounded_repair_copy,
        check_repair_storage,
    )

    directory = _task_root(plan, task)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = _receipt(plan, task, number)
    binding = {
        "input_paths": sorted(inputs.verified),
        "overlay_hashes": dict(inputs.overlays),
        "previous_record_hash": previous["record_hash"] if previous else None,
    }
    ownership = {
        "plan_hash": plan["plan_hash"],
        "task_id": task["task_id"],
        "number": number,
        "dates": list(days),
        "binding": binding,
        "output_paths": {k: str(directory / f"{k}-{number}.parquet") for k in queries},
    }
    if receipt.exists():
        old = json.loads(check_repair_path(receipt).read_text())
        if any(old.get(k) != v for k, v in ownership.items()):
            raise FactorRepairError("repair_indicator_fragment_binding_drift")
        if old.get("validated") is True:
            proof = read_indicator_fragment(plan, task, number)
            for kind, query in queries.items():
                stored = read_parquet(
                    Path(proof["outputs"][kind]["path"]), hive_partitioning=False
                )
                for left, right in (
                    (f"SELECT * FROM {stored}", query),
                    (query, f"SELECT * FROM {stored}"),
                ):
                    if _count(connection, f"({left}) EXCEPT ALL ({right})"):
                        raise FactorRepairError(
                            "repair_indicator_fragment_value_mismatch"
                        )
            return proof
        if old.get("validated") is not False:
            raise FactorRepairError("repair_indicator_fragment_invalid")
    elif any(
        Path(p).exists() or Path(p + ".partial").exists()
        for p in ownership["output_paths"].values()
    ):
        raise FactorRepairError("repair_indicator_fragment_unowned")
    if audit:
        raise FactorRepairError("repair_indicator_fragment_required")
    atomic_repair_json(receipt, {**ownership, "validated": False})
    outputs = {}
    for kind, query in queries.items():
        check_repair_cancel(cancel)
        output = check_repair_path(Path(ownership["output_paths"][kind]))
        working = check_repair_path(Path(str(output) + ".partial"))
        for unfinished in (output, working):
            if unfinished.exists():
                unfinished.unlink()
        bounded_repair_copy(connection, query, Path(plan["run_root"]), working)
        with working.open("rb") as stream:
            os.fsync(stream.fileno())
        if _count(
            connection,
            f"SELECT * FROM {read_parquet(working, hive_partitioning=False)}",
        ) != _count(connection, query):
            raise FactorRepairError("repair_indicator_fragment_row_mismatch")
        os.replace(working, output)
        sync_repair_directory(directory)
        outputs[kind] = asdict(file_identity(output, cancel=cancel))
        check_repair_storage(Path(plan["run_root"]), plan=plan)
    for name in inputs.verified:
        if asdict(file_identity(Path(name), cancel=cancel)) != inputs.identities[name]:
            raise FactorRepairError("input_drift")
    proof = {**ownership, "validated": True, "outputs": outputs}
    proof["record_hash"] = repair_hash(proof)
    atomic_repair_json(receipt, proof)
    return proof


def _input_relation(connection, plan, inputs, profile):
    root = Path(plan["lake_root"])
    freq = profile["freq"]
    code = profile["ts_code"]
    asset = "gold_stock_daily_qfq" if freq is None else f"gold_stk_mins_qfq_{freq}m"
    frozen = [
        Path(i["path"])
        for i in plan["source_fingerprints"]
        if repair_asset_for_path(root, Path(i["path"])) == asset
        and (freq is None or Path(i["path"]).parent.parent.name == "ts_code=" + code)
    ]
    files = []
    for offset in range(0, len(frozen), 64):
        files.extend(inputs.project(p) for p in frozen[offset : offset + 64])
    time_field = "trade_date" if freq is None else "trade_time"
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW indicator_source AS SELECT * FROM {_read(files)} WHERE ts_code={duckdb_string(code)}"
    )
    return time_field


def replay_indicator_task(
    connection, plan, task, *, audit=False, cancel=None, progress=None
):
    """Persist each complete replay segment; no annual reset and no formal writer."""
    validate_indicator_repair_units(plan)
    if task not in indicator_replay_tasks(plan):
        raise FactorRepairError("repair_indicator_task_invalid")
    p = task["profile"]
    sp = task["state_profile"]
    asset = task["asset_key"]
    code = p["ts_code"]
    freq = p["freq"]
    inputs = RepairCandidateInputs(connection, plan, cancel)
    inputs.require_price_candidates = True
    field = _input_relation(connection, plan, inputs, p)
    calendar_path = inputs.frozen(
        paths.silver_trade_calendar_path(Path(plan["lake_root"]))
    )
    actual_calendar = tuple(
        r[0]
        for r in connection.execute(
            f"SELECT DISTINCT CAST(trade_date AS VARCHAR) FROM {read_parquet(calendar_path, hive_partitioning=False)} WHERE exchange='SSE' AND is_open AND trade_date<=DATE {duckdb_string(max(s['repair_end_trade_date'] for s in plan['scopes']))} ORDER BY 1"
        ).fetchall()
    )
    if actual_calendar != tuple(task["calendar_dates"]):
        raise FactorRepairError("repair_indicator_calendar_drift")
    root = Path(plan["lake_root"])
    last = max(p["end_time"][:10], sp["end_time"][:10] if sp else p["end_time"][:10])
    first = p["trade_date_rows"][0][0]
    nine = "nineturn" in asset
    trend = "trend_channel" in asset
    cutoff = (
        f"{field}<={('DATE' if freq is None else 'TIMESTAMP')} {duckdb_string(p['end_time'])}"
        if nine
        else f"trade_date<=DATE {duckdb_string(last)}"
    )
    rows = connection.execute(
        f"SELECT CAST(trade_date AS VARCHAR),count(*) FROM indicator_source WHERE {cutoff} GROUP BY trade_date ORDER BY trade_date"
    ).fetchall()
    counts = dict(rows)
    if nine:
        if sum(counts.values()) != p["full_history_input_rows"]:
            raise FactorRepairError("repair_nineturn_history_drift")
        replay_days = tuple(counts)
    else:
        replay_days = tuple(d for d in task["calendar_dates"] if first <= d <= last)
        price = next(
            w
            for u in plan["units"]
            if u["asset_key"]
            == (
                "gold_stock_daily_qfq" if freq is None else f"gold_stk_mins_qfq_{freq}m"
            )
            for w in u["calculation_windows"]
            if w["ts_code"] == code
        )
        if any(counts.get(d, 0) != n for d, n in price["trade_date_rows"] if d <= last):
            raise FactorRepairError("repair_indicator_price_inventory_drift")
    context_count = 4 if nine else 0 if trend else 8
    windows = plan_repair_calculation_windows(
        [(d, counts.get(d, 0)) for d in replay_days],
        max_rows=RepairBudget().max_stock_batch_rows - context_count,
    )
    if trend:
        from orchestrator.defs.stock_daily_trend_channel import SEGMENT_TRADE_DAY_LIMIT

        windows = tuple(
            tuple(w[i : i + SEGMENT_TRADE_DAY_LIMIT])
            for w in windows
            for i in range(0, len(w), SEGMENT_TRADE_DAY_LIMIT)
        )
    total_replay_rows = sum(counts.get(d, 0) for w in windows for d in w)
    previous = None
    context_path = None
    seed_path = None
    proofs = []
    if trend:
        seed = p["daily_seed"]
        life = inputs.frozen(paths.silver_stock_lifecycle_path(root))
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW indicator_lifecycle AS SELECT * FROM {read_parquet(life, hive_partitioning=False)} WHERE ts_code={duckdb_string(code)}"
        )
        observed = connection.execute(
            "SELECT CAST(list_date AS VARCHAR) FROM indicator_lifecycle"
        ).fetchall()
        if len(observed) != 1 or (
            seed["initialized_from_listing"] and observed[0][0] != first
        ):
            raise FactorRepairError("repair_daily_initialization_not_proven")
        seed_path = (
            inputs.frozen(Path(seed["state_path"])) if seed["state_path"] else None
        )
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
            inspect_repair_daily_seed,
        )

        price_profile = next(
            w
            for u in plan["units"]
            if u["asset_key"] == "gold_stock_daily_qfq"
            for w in u["calculation_windows"]
            if w["ts_code"] == code
        )
        previous_actual = price_profile["previous_actual_date"]
        checked = inspect_repair_daily_seed(
            connection,
            lake_root=root,
            ts_code=code,
            first_trade_date=first,
            previous_actual_date=previous_actual,
            expected_dates=task["calendar_dates"],
        )
        if any(seed.get(k) != v for k, v in checked.items()):
            raise FactorRepairError("repair_daily_seed_invalid")
    elif not nine:
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
            inspect_repair_minute_seed,
        )

        seed_path = inputs.frozen(
            paths.gold_stk_mins_qfq_macd_kdj_state_path(
                root, freq, p["previous_expected_date"]
            )
        )
        # Validate the exact input seed and context independently of the stored profile.
        checked = inspect_repair_minute_seed(
            connection,
            ts_code=code,
            freq=freq,
            first_trade_date=first,
            expected_dates=task["calendar_dates"],
            price_paths=[
                Path(i["path"])
                for i in plan["source_fingerprints"]
                if repair_asset_for_path(root, Path(i["path"]))
                == f"gold_stk_mins_qfq_{freq}m"
                and Path(i["path"]).parent.parent.name == "ts_code=" + code
            ],
            state_path=seed_path,
        )
        if any(
            list(checked[k]) != list(p[k])
            if k == "context_times"
            else checked[k] != p[k]
            for k in ("previous_expected_date", "seed_last_trade_time", "context_times")
        ):
            raise FactorRepairError("repair_seed_context_invalid")
    for number, days in enumerate(windows):
        check_repair_cancel(cancel)
        if progress:
            progress(
                {
                    "replay_current_window": [days[0], days[-1]],
                    "replay_completed_windows": number,
                    "replay_total_windows": len(windows),
                    "replay_total_rows": total_replay_rows,
                    "replay_completed_rows": sum(
                        counts.get(d, 0) for w in windows[:number] for d in w
                    ),
                    "replay_calculated_rows": sum(
                        counts.get(d, 0) for w in windows[:number] for d in w
                    ),
                }
            )
        source = f"SELECT * FROM indicator_source WHERE trade_date IN {_days(days)}"
        if nine:
            source += f" AND {field}<={('DATE' if freq is None else 'TIMESTAMP')} {duckdb_string(p['end_time'])}"
        before = f"SELECT * FROM indicator_source WHERE trade_date<DATE {duckdb_string(days[0])} ORDER BY {field} DESC LIMIT {context_count}"
        if context_count:
            source = f"{source} UNION ALL SELECT * FROM ({before})"
        if _count(connection, source) > RepairBudget().max_stock_batch_rows:
            raise FactorRepairError("repair_stock_row_budget_exceeded")
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE indicator_segment_source AS {source}"
        )
        queries = {}
        if trend:
            from orchestrator.defs.stock_daily_trend_channel import (
                prepare_stock_daily_trend_channel_repair_tables,
            )

            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE indicator_codes AS SELECT {duckdb_string(code)}::VARCHAR ts_code"
            )
            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE indicator_dates AS SELECT col0 AS trade_date FROM (VALUES {','.join('(DATE ' + duckdb_string(d) + ')' for d in days)})"
            )
            if seed_path:
                seed_cols = "ts_code,state_source_trade_date,short_upper_raw,short_lower_raw,short_state,long_upper_raw,long_lower_raw,long_state,combined_state,formula_version"
                connection.execute(
                    f"CREATE OR REPLACE TEMP VIEW indicator_seed AS SELECT {seed_cols} FROM {read_parquet(seed_path, hive_partitioning=False)} WHERE ts_code={duckdb_string(code)} QUALIFY row_number() OVER(ORDER BY trade_date DESC)=1"
                )
            result_relation, state_relation = (
                prepare_stock_daily_trend_channel_repair_tables(
                    connection=connection,
                    source_relation="indicator_segment_source",
                    dates_relation="indicator_dates",
                    codes_relation="indicator_codes",
                    lifecycle_relation="indicator_lifecycle",
                    segment_trade_day_count=len(days),
                    previous_state_relation="indicator_seed" if seed_path else None,
                )
            )
            queries["seed"] = (
                f"SELECT * FROM {state_relation} WHERE trade_date=DATE {duckdb_string(days[-1])}"
            )
        elif nine:
            from orchestrator.defs.qfq_nineturn import (
                build_gold_stk_mins_qfq_nineturn_history_batch_select_sql,
                build_gold_stock_daily_qfq_nineturn_history_batch_select_sql,
            )

            # Canonical history builders accept bounded projected paths and compact seed/context.
            segment = _task_root(plan, task) / f"source-{number}.parquet"
            _persist_fragment(
                connection,
                plan,
                task,
                number * 2,
                days,
                {"source": "SELECT * FROM indicator_segment_source"},
                inputs,
                previous,
                audit=audit,
                cancel=cancel,
            )
            segment = Path(
                read_indicator_fragment(plan, task, number * 2)["outputs"]["source"][
                    "path"
                ]
            )
            builder = (
                build_gold_stock_daily_qfq_nineturn_history_batch_select_sql
                if freq is None
                else build_gold_stk_mins_qfq_nineturn_history_batch_select_sql
            )
            query = builder(
                source_paths=[segment],
                start_date=days[0],
                end_date=days[-1],
                context_path=context_path,
                seed_path=seed_path,
                **({"freq": freq} if freq is not None else {}),
            )
            connection.execute(
                "CREATE OR REPLACE TEMP TABLE indicator_nine_result AS " + query
            )
            result_relation = "indicator_nine_result"
            state_relation = None
            queries["seed"] = (
                f"SELECT ts_code,CASE WHEN up_count>0 THEN 1 WHEN down_count>0 THEN -1 ELSE 0 END::INTEGER seed_direction,greatest(up_count,down_count)::INTEGER seed_count FROM {result_relation} QUALIFY row_number() OVER(PARTITION BY ts_code ORDER BY {field} DESC)=1"
            )
            bar = "CAST(trade_date AS TIMESTAMP)" if freq is None else "trade_time"
            queries["context"] = (
                f"SELECT ts_code,{('NULL::INTEGER' if freq is None else 'freq')} freq,trade_date,{('NULL::TIMESTAMP' if freq is None else 'trade_time')} trade_time,{bar} bar_time,close close_qfq FROM indicator_segment_source ORDER BY {field} DESC LIMIT 4"
            )
        else:
            from orchestrator.defs.stk_mins_qfq_macd_kdj import (
                prepare_stk_mins_qfq_macd_kdj_replacement_tables,
            )

            source_proof = _persist_fragment(
                connection,
                plan,
                task,
                number * 2,
                days,
                {"source": "SELECT * FROM indicator_segment_source"},
                inputs,
                previous,
                audit=audit,
                cancel=cancel,
            )
            # Source and seed are single-stock projections, never full-market state or annual input.
            if previous is None:
                seed_source = read_parquet(seed_path, hive_partitioning=False)
                seed_query = f"SELECT * FROM {seed_source} WHERE ts_code={duckdb_string(code)} AND freq={freq} AND trade_date=DATE {duckdb_string(p['previous_expected_date'])}"
                seed_proof = _persist_fragment(
                    connection,
                    plan,
                    task,
                    -1,
                    [p["previous_expected_date"]],
                    {"seed": seed_query},
                    inputs,
                    None,
                    audit=audit,
                    cancel=cancel,
                )
                seed_path = Path(seed_proof["outputs"]["seed"]["path"])
            completed_before = sum(
                counts.get(d, 0) for w in windows[:number] for d in w
            )

            def segment_progress(
                calculated, days=days, completed_before=completed_before, number=number
            ):
                check_repair_cancel(cancel)
                if progress:
                    progress(
                        {
                            "replay_current_window": [days[0], days[-1]],
                            "replay_completed_rows": completed_before,
                            "replay_calculated_rows": completed_before + calculated,
                            "replay_total_rows": total_replay_rows,
                            "replay_completed_windows": number,
                            "replay_total_windows": len(windows),
                        }
                    )
                check_repair_cancel(cancel)

            tables = prepare_stk_mins_qfq_macd_kdj_replacement_tables(
                connection,
                source_qfq_paths=[Path(source_proof["outputs"]["source"]["path"])],
                target_trade_dates=days,
                previous_state_paths=[seed_path],
                freq=freq,
                stock_codes=[code],
                progress=segment_progress,
            )
            if tables.initialized_without_previous_state:
                raise FactorRepairError("repair_exact_seed_invalid")
            result_relation = tables.indicator_relation
            state_relation = tables.state_relation
            queries["seed"] = (
                f"SELECT * FROM {state_relation} WHERE trade_date=DATE {duckdb_string(days[-1])}"
            )
        queries["result"] = (
            f"SELECT {_columns(indicator_schema(asset))} FROM {result_relation} WHERE trade_date IN {_days(p['target_dates'])} AND {field}<={('DATE' if freq is None else 'TIMESTAMP')} {duckdb_string(p['end_time'])} ORDER BY ts_code,{field}"
        )
        if sp:
            queries["state"] = (
                f"SELECT {_columns(indicator_schema(task['state_asset']))} FROM {state_relation} WHERE trade_date IN {_days(sp['target_dates'])} ORDER BY ts_code,trade_date"
            )
        proof = _persist_fragment(
            connection,
            plan,
            task,
            number * 2 + 1,
            days,
            queries,
            inputs,
            previous,
            audit=audit,
            cancel=cancel,
        )
        previous = proof
        proofs.append(proof)
        seed_path = Path(proof["outputs"]["seed"]["path"])
        context_path = (
            Path(proof["outputs"]["context"]["path"])
            if "context" in proof["outputs"]
            else None
        )
        if progress:
            progress(
                {
                    "replay_current_window": [days[0], days[-1]],
                    "replay_completed_windows": number + 1,
                    "replay_total_windows": len(windows),
                    "replay_total_rows": total_replay_rows,
                    "replay_completed_rows": sum(
                        counts.get(d, 0) for w in windows[: number + 1] for d in w
                    ),
                    "replay_calculated_rows": sum(
                        counts.get(d, 0) for w in windows[: number + 1] for d in w
                    ),
                }
            )
    for kind, profile in (("result", p), ("state", sp)):
        if profile is None:
            continue
        n = sum(
            _count(
                connection,
                f"SELECT * FROM {read_parquet(Path(r['outputs'][kind]['path']), hive_partitioning=False)}",
            )
            for r in proofs
        )
        if n != sum(v for d, v in profile["trade_date_rows"]):
            raise FactorRepairError("repair_indicator_output_inventory_mismatch")
    result = {
        "plan_hash": plan["plan_hash"],
        "task_id": task["task_id"],
        "fragments": len(proofs),
        "completed_rows": sum(n for d, n in p["trade_date_rows"]),
        "receipts": [
            asdict(
                file_identity(
                    _receipt(plan, task, int(name.stem.removeprefix("segment-")))
                )
            )
            for name in sorted(_task_root(plan, task).glob("segment-*.json"))
        ],
    }
    result["record_hash"] = repair_hash(result)
    marker = _task_root(plan, task) / "task.json"
    if marker.exists():
        if json.loads(marker.read_text()) != result:
            raise FactorRepairError("repair_indicator_task_drift")
    elif audit:
        raise FactorRepairError("repair_indicator_task_required")
    else:
        atomic_repair_json(marker, result)
    return result


def read_indicator_task(plan, task):
    marker = check_repair_path(_task_root(plan, task) / "task.json")
    result = json.loads(marker.read_text())
    if (
        result.get("plan_hash") != plan["plan_hash"]
        or result.get("task_id") != task["task_id"]
        or result.get("record_hash")
        != repair_hash({k: v for k, v in result.items() if k != "record_hash"})
    ):
        raise FactorRepairError("repair_indicator_task_invalid")
    proofs = []
    for identity in result["receipts"]:
        path = check_repair_path(Path(identity["path"]))
        if (
            path.parent != _task_root(plan, task)
            or asdict(file_identity(path)) != identity
        ):
            raise FactorRepairError("repair_indicator_fragment_drift")
        proof = read_indicator_fragment(
            plan, task, int(path.stem.removeprefix("segment-"))
        )
        if "result" in proof["outputs"]:
            proofs.append(proof)
    if len(proofs) != result["fragments"]:
        raise FactorRepairError("repair_indicator_task_invalid")
    return proofs


def _batch_rows(connection, name, files, days, *, annual=False, columns="*"):
    # One materialized scan per input family. Logical file dates survive candidate paths.
    source = _read(files).replace(
        "hive_partitioning=false)", "hive_partitioning=false,filename=true)"
    )
    if columns == "*":
        columns = "* EXCLUDE(filename)"
    expected = (
        "CAST(trade_date AS DATE)"
        if annual
        else "try_cast(regexp_extract(filename,'trade_date=([0-9-]+)/',1) AS DATE)"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT {columns},filename,{expected} AS expected_day FROM {source} WHERE {expected} IN {_days(days)}"
    )


def _batch_rule_rows(connection, days, counts_sql):
    """One statement over monthly temp tables, with the unchanged scalar rule kernel."""
    queries = [
        f"SELECT DATE {duckdb_string(d)} AS day,metrics.* FROM ({counts_sql.replace('days.day', 'DATE ' + duckdb_string(d))}) metrics"
        for d in days
    ]
    return connection.execute(" UNION ALL ".join(queries)).fetchall()


def audit_indicator_batch(connection, plan, unit, targets, *, pending=None):
    """Materialize only one asset/month, then bind the complete batch evidence."""
    asset = unit["asset_key"]
    freq = unit["calculation_windows"][0]["freq"]
    root = Path(plan["lake_root"])
    days = sorted(
        {
            d
            for p in unit["calculation_windows"]
            for d in p["target_dates"]
            if str(indicator_repair_target(root, asset, p["ts_code"], freq, d))
            in set(targets)
        }
    )
    if not days:
        raise FactorRepairError("repair_indicator_target_not_frozen")
    months = {}
    for day in days:
        months.setdefault(day[:7], []).append(day)
    names = set()
    overlays = {}
    inputs = RepairCandidateInputs(connection, plan)
    inputs.require_price_candidates = True
    schemas_checked = set()
    for selected in months.values():
        proof = _audit_indicator_month(
            connection,
            plan,
            unit,
            targets,
            selected,
            inputs=inputs,
            schemas_checked=schemas_checked,
            pending=pending,
        )
        names.update(proof["input_paths"])
        overlays.update(proof["overlay_hashes"])
    return {
        "asset_key": asset,
        "targets": sorted(targets),
        "checked_dates": len(days),
        "input_paths": sorted(names),
        "overlay_hashes": overlays,
    }


def _audit_indicator_month(
    connection, plan, unit, targets, days, *, inputs, schemas_checked, pending=None
):
    """Full-market original rules over already materialized monthly inputs."""
    pending = pending or {}

    def resolve(path):
        inputs.frozen(path)
        if str(path) not in pending:
            return inputs.resolve(path)
        record = pending[str(path)]
        if (
            record["plan_hash"] != plan["plan_hash"]
            or record.get("business_pending") is not True
            or record["validated"] is not False
        ):
            raise FactorRepairError("repair_candidate_record_invalid")
        relative = path.relative_to(Path(plan["lake_root"])).as_posix()
        expected = None if record["no_op"] else "candidates/" + relative
        if (
            record.get("target_relative_path") != relative
            or record.get("candidate_relative_path") != expected
            or record.get("preimage_sha256") != inputs.identities[str(path)]["sha256"]
        ):
            raise FactorRepairError("repair_candidate_path_invalid")
        output = (
            path
            if record["no_op"]
            else check_repair_path(Path(plan["run_root"]) / expected)
        )
        if file_identity(output).sha256 != record["candidate_sha256"]:
            raise FactorRepairError("repair_candidate_drift")
        return output

    asset = unit["asset_key"]
    freq = unit["calculation_windows"][0]["freq"]
    root = Path(plan["lake_root"])
    schema = indicator_schema(asset)
    annual = freq is not None and "macd_kdj" in asset and "_state_" not in asset
    names = [
        Path(p)
        for p in unit["validation_paths"]
        if (
            Path(p).parent.name.removeprefix("year=") in {d[:4] for d in days}
            if annual
            else Path(p).parent.name.removeprefix("trade_date=") in days
        )
    ]
    outputs = [resolve(p) for p in names]
    for p in outputs:
        if p not in schemas_checked:
            assert_repair_schema(connection, p, schema)
            schemas_checked.add(p)
    _batch_rows(
        connection,
        "indicator_market_output",
        outputs,
        days,
        annual=annual,
        columns="ts_code,freq,trade_date,trade_time" if annual else "*",
    )
    price_asset = (
        "gold_stock_daily_qfq" if freq is None else f"gold_stk_mins_qfq_{freq}m"
    )
    if freq is None:
        price_paths = [paths.gold_stock_daily_qfq_path(root, d) for d in days]
    else:
        price_unit = next(u for u in plan["units"] if u["asset_key"] == price_asset)
        price_paths = [
            Path(p)
            for p in price_unit["validation_paths"]
            if Path(p).parent.name.removeprefix("year=") in {d[:4] for d in days}
        ]
    if freq is not None:
        directory = paths.gold_stk_mins_qfq_path(
            root, freq, plan["scopes"][0]["ts_code"], days[0][:4]
        ).parents[2]
        current = {
            str(p)
            for year in {d[:4] for d in days}
            for p in directory.glob(f"ts_code=*/year={year}/part-000.parquet")
        }
        if current != {str(p) for p in price_paths}:
            raise FactorRepairError("repair_price_source_inventory_drift")
    price_files = [inputs.resolve(p) for p in price_paths]
    _batch_rows(
        connection,
        "indicator_market_price",
        price_files,
        days,
        annual=freq is not None,
        columns="ts_code,freq,trade_date,trade_time" if "macd_kdj" in asset else "*",
    )
    target = f"(SELECT {_columns(schema)} FROM indicator_market_output WHERE expected_day=days.day)"
    source = "(SELECT * EXCLUDE(filename,expected_day) FROM indicator_market_price WHERE expected_day=days.day)"
    if "trend_channel" in asset:
        from orchestrator.defs.stock_daily_trend_channel import (
            trend_channel_coverage_counts_sql,
            trend_channel_result_counts_sql,
            trend_channel_state_counts_sql,
        )

        life = read_parquet(
            inputs.frozen(paths.silver_stock_lifecycle_path(root)),
            hive_partitioning=False,
        )
        connection.execute(
            "CREATE OR REPLACE TEMP TABLE indicator_market_lifecycle AS SELECT * FROM "
            + life
        )
        life = "indicator_market_lifecycle"
        if "_state" not in asset:
            counts = trend_channel_result_counts_sql(
                result_sql=target, qfq_sql=source, date_expression="days.day"
            )
            rows = _batch_rule_rows(connection, days, counts)
            if (
                any(any(row[1:]) for row in rows)
                or _count(connection, "SELECT * FROM indicator_market_output") <= 0
            ):
                raise FactorRepairError("repair_trend_result_check_failed")
        else:
            counts = trend_channel_state_counts_sql(
                state_sql=target, lifecycle_sql=life, date_expression="days.day"
            )
            rows = _batch_rule_rows(connection, days, counts)
            if any(any(row[1:]) for row in rows):
                raise FactorRepairError("repair_trend_state_check_failed")
            calendar = unit["calendar_dates"]
            previous = {d: max(x for x in calendar if x < d) for d in days}
            previous_paths = [
                paths.gold_stock_daily_trend_channel_state_path(root, d)
                for d in sorted(set(previous.values()))
            ]
            # Existing previous state may itself have a verified candidate. It remains read-only.
            _batch_rows(
                connection,
                "indicator_market_previous",
                [resolve(p) for p in previous_paths],
                sorted(set(previous.values())),
            )
            previous_values = ",".join(
                "(DATE "
                + duckdb_string(d)
                + ",DATE "
                + duckdb_string(previous[d])
                + ")"
                for d in days
            )
            previous_sql = f"(SELECT * EXCLUDE(filename,expected_day) FROM indicator_market_previous WHERE expected_day=(SELECT col1 FROM (VALUES {previous_values}) WHERE col0=days.day))"
            counts = trend_channel_coverage_counts_sql(
                state_sql=target,
                qfq_sql=source,
                lifecycle_sql=life,
                previous_sql=previous_sql,
                date_expression="days.day",
            )
            rows = _batch_rule_rows(connection, days, counts)
            if any(
                r[2] != r[5]
                or r[4] != r[6]
                or r[1] != r[5] + r[6] + r[7]
                or r[8]
                or r[9]
                for r in rows
            ):
                raise FactorRepairError("repair_trend_coverage_check_failed")
    elif "nineturn" in asset:
        from orchestrator.defs.qfq_nineturn_integrity import (
            qfq_nineturn_coverage_counts_sql,
            qfq_nineturn_output_counts_sql,
        )

        keys = "ts_code,trade_date" if freq is None else "ts_code,freq,trade_time"
        nulls = "ts_code IS NULL OR trim(ts_code)='' OR trade_date IS NULL" + (
            "" if freq is None else " OR freq IS NULL OR trade_time IS NULL"
        )
        mismatch = "trade_date!=days.day" + (
            ""
            if freq is None
            else f" OR CAST(trade_time AS DATE)!=days.day OR freq!={freq}"
        )
        counts = qfq_nineturn_output_counts_sql(
            target=target,
            key_columns=keys,
            null_key_predicate=nulls,
            partition_predicate=mismatch,
        )
        rows = _batch_rule_rows(connection, days, counts)
        if any(r[1] <= 0 or any(r[2:]) for r in rows):
            raise FactorRepairError("repair_nineturn_integrity_failed")
        source_rows = f"SELECT {keys} FROM {source}" + (
            "" if freq is None else f" WHERE freq={freq}"
        )
        counts = qfq_nineturn_coverage_counts_sql(
            source_identity_rows_sql=source_rows,
            source_identity_sql=f"SELECT DISTINCT * FROM ({source_rows})",
            target_identity_sql=f"SELECT DISTINCT {keys} FROM {target}",
            key_columns=keys,
        )
        rows = _batch_rule_rows(connection, days, counts)
        if any(r[1] <= 0 or any(r[2:]) for r in rows):
            raise FactorRepairError("repair_nineturn_source_coverage_failed")
    else:
        from orchestrator.defs.stk_mins_qfq_macd_kdj_rules import (
            macd_kdj_source_coverage_sql,
            macd_kdj_state_coverage_sql,
        )

        if "_state_" not in asset:
            query = macd_kdj_source_coverage_sql(
                source="indicator_market_price",
                indicator="indicator_market_output",
                freq=freq,
                dates=days,
            )
            if any(
                n <= 0 or n != m for d, n, m in connection.execute(query).fetchall()
            ):
                raise FactorRepairError("repair_macd_source_coverage_failed")
            for left, right in (
                ("indicator_market_price", "indicator_market_output"),
                ("indicator_market_output", "indicator_market_price"),
            ):
                if _count(
                    connection,
                    f"SELECT ts_code,freq,trade_time FROM {left} EXCEPT SELECT ts_code,freq,trade_time FROM {right}",
                ):
                    raise FactorRepairError("repair_macd_source_identity_mismatch")
        else:
            result_unit = next(
                u
                for u in plan["units"]
                if u["asset_key"] == f"gold_stk_mins_qfq_macd_kdj_{freq}m"
            )
            result_files = [
                inputs.resolve(Path(p))
                for p in result_unit["validation_paths"]
                if Path(p).parent.name.removeprefix("year=") in {d[:4] for d in days}
            ]
            _batch_rows(
                connection,
                "indicator_market_result",
                result_files,
                days,
                annual=True,
                columns="ts_code,freq,trade_date,trade_time",
            )
            query = macd_kdj_state_coverage_sql(
                indicator="indicator_market_result",
                state="indicator_market_output",
                freq=freq,
                dates=days,
            )
            if any(
                n > m or a or b
                for d, n, m, a, b in connection.execute(query).fetchall()
            ):
                raise FactorRepairError("repair_macd_state_coverage_failed")
    return {
        "asset_key": asset,
        "targets": sorted(targets),
        "checked_dates": len(days),
        "input_paths": sorted(inputs.verified),
        "overlay_hashes": dict(inputs.overlays),
    }


def build_indicator_target_candidate(
    connection, plan, unit, target, *, audit=False, cancel=None
):
    asset = unit["asset_key"]
    schema = indicator_schema(asset)
    root = Path(plan["lake_root"])
    run = Path(plan["run_root"])
    inputs = RepairCandidateInputs(connection, plan, cancel)
    inputs.require_price_candidates = True
    inputs.frozen(target)
    replacements = []
    fragment_files = []
    for task in indicator_replay_tasks(plan):
        if asset not in (task["asset_key"], task["state_asset"]):
            continue
        p = task["profile"] if asset == task["asset_key"] else task["state_profile"]
        wanted = [
            d
            for d in p["target_dates"]
            if indicator_repair_target(root, asset, p["ts_code"], p["freq"], d)
            == target
        ]
        if not wanted:
            continue
        kind = "result" if asset == task["asset_key"] else "state"
        for proof in read_indicator_task(plan, task):
            for name in proof["binding"]["input_paths"]:
                inputs.frozen(Path(name))
            for name, h in proof["binding"]["overlay_hashes"].items():
                if (
                    read_repair_candidate_record(plan, Path(name))["candidate_sha256"]
                    != h
                ):
                    raise FactorRepairError("repair_overlay_drift")
                inputs.overlays[name] = h
            identity = proof["outputs"][kind]
            fragment_files.append(identity)
            replacements.append(
                f"SELECT {_columns(schema)} FROM {read_parquet(Path(identity['path']), hive_partitioning=False)} WHERE ts_code={duckdb_string(p['ts_code'])} AND trade_date IN {_days(wanted)}"
            )
    if not replacements:
        raise FactorRepairError("repair_indicator_target_not_frozen")
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE repair_replacement AS "
        + " UNION ALL ".join(replacements)
    )
    keys = (
        ("ts_code", "trade_date")
        if "trade_time" not in {c.name for c in schema}
        else ("ts_code", "trade_time")
    )
    key_sql = ",".join(keys)
    # Approved keys come from frozen profile dates and existing output identities, never from computed output alone.
    predicates = []
    for p in unit["calculation_windows"]:
        wanted = [
            d
            for d in p["target_dates"]
            if indicator_repair_target(root, asset, p["ts_code"], p["freq"], d)
            == target
        ]
        if wanted:
            predicates.append(
                f"(ts_code={duckdb_string(p['ts_code'])} AND trade_date IN {_days(wanted)})"
            )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE repair_approved AS SELECT {key_sql} FROM {read_parquet(target, hive_partitioning=False)} WHERE {' OR '.join(predicates)}"
    )

    def validate(c, output, _partition):
        assert_repair_schema(c, output, schema)
        source = read_parquet(output, hive_partitioning=False)
        if _count(
            c, f"SELECT {key_sql} FROM {source} GROUP BY {key_sql} HAVING count(*)>1"
        ):
            raise FactorRepairError("repair_duplicate_keys")
        # Scope transfer is checked independently in build_scoped_file_candidate and audit below.

    def finalize(record):
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
            check_repair_storage,
        )

        check_repair_storage(run, plan=plan)
        for name in inputs.verified:
            if (
                asdict(file_identity(Path(name), cancel=cancel))
                != inputs.identities[name]
            ):
                raise FactorRepairError("input_drift")
        for identity in fragment_files:
            if asdict(file_identity(Path(identity["path"]))) != identity:
                raise FactorRepairError("repair_indicator_fragment_drift")
        complete = {
            **record,
            "format_version": 1,
            "input_paths": sorted(inputs.verified),
            "overlay_hashes": inputs.overlays,
            "replay_files": fragment_files,
        }
        # Business completion is sealed only after this whole asset/month batch audit.
        complete.update(validated=False, business_pending=True)
        write_candidate_record(run, complete)
        record.clear()
        record.update(complete)

    record_path = repair_record_path(run, target, root)
    if audit or (
        record_path.exists() and "record_hash" in json.loads(record_path.read_text())
    ):
        record = read_repair_candidate_record(plan, target)
        validation = record.get("business_validation")
        if (
            not validation
            or validation.get("asset_key") != asset
            or str(target) not in validation.get("targets", [])
        ):
            raise FactorRepairError("repair_indicator_business_proof_required")
        for name in validation["input_paths"]:
            inputs.frozen(Path(name))
        for name, h in validation["overlay_hashes"].items():
            if read_repair_candidate_record(plan, Path(name))["candidate_sha256"] != h:
                raise FactorRepairError("repair_overlay_drift")
        output = target if record["no_op"] else run / record["candidate_relative_path"]
        validate(connection, output, None)
        join = " AND ".join(f"o.{k} IS NOT DISTINCT FROM a.{k}" for k in keys)
        actual = f"SELECT {_columns(schema)} FROM {read_parquet(output, hive_partitioning=False)} o WHERE EXISTS(SELECT 1 FROM repair_approved a WHERE {join})"
        for left, right in (
            (actual, "SELECT * FROM repair_replacement"),
            ("SELECT * FROM repair_replacement", actual),
        ):
            if _count(connection, f"({left}) EXCEPT ALL ({right})"):
                raise FactorRepairError("repair_candidate_value_mismatch")
        for left, right in ((output, target), (target, output)):

            def retained(file):
                return f"SELECT {_columns(schema)} FROM {read_parquet(file, hive_partitioning=False)} o WHERE NOT EXISTS(SELECT 1 FROM repair_approved a WHERE {join})"

            if _count(connection, f"{retained(left)} EXCEPT ALL {retained(right)}"):
                raise FactorRepairError("repair_retained_rows_changed")
        changed = _count(
            connection,
            f"SELECT {_columns(schema)} FROM repair_replacement EXCEPT ALL SELECT {_columns(schema)} FROM {read_parquet(target, hive_partitioning=False)}",
        )
        if (
            changed != record["changed_stock_rows"]
            or record.get("replay_files") != fragment_files
            or record.get("overlay_hashes") != inputs.overlays
        ):
            raise FactorRepairError("repair_candidate_record_invalid")
        return record
    return build_scoped_file_candidate(
        connection,
        lake_root=root,
        run_root=run,
        target=target,
        replacement_relation="repair_replacement",
        approved_keys_relation="repair_approved",
        schema=schema,
        key_columns=keys,
        plan_hash=plan["plan_hash"],
        unit_id=repair_hash([plan["plan_hash"], asset, str(target)]),
        asset_key=asset,
        partition_key=target.parent.name,
        validator=validate,
        finalize_record=finalize,
        cancel=cancel,
    )


def seal_indicator_batch(plan, records, validation):
    """After complete blocking semantics, bind all inputs/outputs and seal each file."""
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        check_repair_storage,
    )

    run = Path(plan["run_root"])
    if (
        not validation
        or set(validation["targets"]) != set(records)
        or validation["checked_dates"] <= 0
    ):
        raise FactorRepairError("repair_indicator_business_proof_required")
    identities = {i["path"]: i for i in plan["source_fingerprints"]}
    for name in validation["input_paths"]:
        if (
            name not in identities
            or asdict(file_identity(Path(name))) != identities[name]
        ):
            raise FactorRepairError("input_drift")
    for name, h in validation["overlay_hashes"].items():
        if read_repair_candidate_record(plan, Path(name))["candidate_sha256"] != h:
            raise FactorRepairError("repair_overlay_drift")
    for target, record in records.items():
        if record.get("business_pending") is not True:
            continue
        preimage = next(i for i in plan["target_preimages"] if i["path"] == target)
        if asdict(file_identity(Path(target))) != preimage:
            raise FactorRepairError("target_drift")
        identities = {i["path"]: i for i in plan["source_fingerprints"]}
        for name in record["input_paths"]:
            if asdict(file_identity(Path(name))) != identities[name]:
                raise FactorRepairError("input_drift")
        for name, h in record["overlay_hashes"].items():
            if read_repair_candidate_record(plan, Path(name))["candidate_sha256"] != h:
                raise FactorRepairError("repair_overlay_drift")
        for identity in record["replay_files"]:
            if asdict(file_identity(Path(identity["path"]))) != identity:
                raise FactorRepairError("repair_indicator_fragment_drift")
        output = (
            Path(target) if record["no_op"] else run / record["candidate_relative_path"]
        )
        if file_identity(output).sha256 != record["candidate_sha256"]:
            raise FactorRepairError("repair_candidate_drift")
        check_repair_storage(run, plan=plan)
        if record["asset_key"] != validation["asset_key"]:
            raise FactorRepairError("repair_indicator_business_proof_required")
        record["business_validation"] = validation
        record.update(validated=True)
        record.pop("business_pending")
        record["record_hash"] = repair_hash(record)
        write_candidate_record(run, record)
