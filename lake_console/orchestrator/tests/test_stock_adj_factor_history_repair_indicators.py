"""Literal synthetic indicator repair evidence; formal resources are never test inputs."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import duckdb
import pytest

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    AssetRepairEndpoint,
    FactorRepairError,
    FactorRepairScope,
    RepairBudget,
    file_identity,
    freeze_stock_factor_repair,
    indicator_repair_assets,
    repair_hash,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    read_repair_candidate_record,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
    audit_indicator_batch,
    build_indicator_target_candidate,
    indicator_replay_tasks,
    indicator_schema,
    read_indicator_task,
    replay_indicator_task,
    seal_indicator_batch,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.run_contracts import asset_column_schemas as schemas

from . import test_stock_adj_factor_history_repair_candidates as prices

scope = prices.scope
freeze_case = prices.freeze_case
repair_endpoints = prices.repair_endpoints
price_plan = prices.price_plan


def _read(files):
    return (
        "read_parquet(["
        + ",".join(duckdb_string(str(p)) for p in files)
        + "],hive_partitioning=false)"
    )


def _write(c, path, query):
    path.parent.mkdir(parents=True, exist_ok=True)
    c.execute(copy_query_to_parquet(query, path))


def _projection(schema, values):
    return ",".join(
        f'CAST({values[col.name]} AS {col.type}) AS "{col.name}"' for col in schema
    )


@pytest.fixture
def indicator_plan(price_plan):
    """A newly frozen complete contract; baseline indicator values are explicit literals."""
    old = price_plan
    root = Path(old["lake_root"])
    units = deepcopy(old["units"])
    endpoints = deepcopy(old["endpoints"])
    input_paths = {Path(i["path"]) for i in old["source_fingerprints"]}
    by_asset = {u["asset_key"]: u for u in units}
    calendar = by_asset["gold_stock_daily_trend_channel"]["calendar_dates"]
    with duckdb.connect(
        config={"threads": 2, "memory_limit": "1GiB", "max_temp_directory_size": "0B"}
    ) as c:
        for freq in (1, 5, 15, 30, 60, 90, 120):
            price_files = sorted(
                p
                for p in input_paths
                if "/gold/quote/stk_mins_qfq/" in str(p) and f"/freq={freq}/" in str(p)
            )
            # Earliest stock receives real eight-key context; every later seed uses actual existing bars.
            for p in by_asset[f"gold_stk_mins_qfq_macd_kdj_{freq}m"][
                "calculation_windows"
            ]:
                code = p["ts_code"]
                first = p["trade_date_rows"][0][0]
                files = [
                    path
                    for path in price_files
                    if "/ts_code=" + code + "/" in str(path)
                ]
                rows = c.execute(
                    f"SELECT CAST(trade_time AS VARCHAR) FROM {_read(files)} WHERE trade_date<DATE {duckdb_string(first)} ORDER BY trade_time DESC LIMIT 8"
                ).fetchall()
                if len(rows) < 8:
                    previous = p["previous_expected_date"]
                    target = paths.gold_stk_mins_qfq_path(
                        root, freq, code, previous[:4]
                    )
                    c.execute(
                        "CREATE OR REPLACE TEMP TABLE context_original AS SELECT * FROM "
                        + read_parquet(target, hive_partitioning=False)
                    )
                    stamps = [previous + f" 14:{i:02}:00" for i in range(8)]
                    c.execute(
                        "INSERT INTO context_original SELECT ?::VARCHAR,?::INTEGER,?::DATE,t,5.0,5.5,4.5,5.0,100.0,1000.0,CASE WHEN ? LIKE '%.SH' THEN 'SSE' ELSE 'SZSE' END FROM unnest(?::TIMESTAMP[]) x(t)",
                        [code, freq, previous, code, stamps],
                    )
                    _write(
                        c,
                        target,
                        "SELECT * FROM context_original ORDER BY ts_code,trade_time",
                    )
                    rows = c.execute(
                        f"SELECT CAST(trade_time AS VARCHAR) FROM {_read(files)} WHERE trade_date<DATE {duckdb_string(first)} ORDER BY trade_time DESC LIMIT 8"
                    ).fetchall()
                context = sorted(r[0] for r in rows)
                for asset in (
                    f"gold_stk_mins_qfq_macd_kdj_{freq}m",
                    f"gold_stk_mins_qfq_macd_kdj_state_{freq}m",
                ):
                    profile = next(
                        w
                        for w in by_asset[asset]["calculation_windows"]
                        if w["ts_code"] == code
                    )
                    profile.update(
                        context_times=context, seed_last_trade_time=context[-1]
                    )
                    e = next(
                        e
                        for e in endpoints
                        if e["asset_key"] == asset and e["ts_code"] == code
                    )
                    e.update(context_times=context, seed_last_trade_time=context[-1])
            for file in price_files:
                code = file.parent.parent.name.removeprefix("ts_code=")
                year = file.parent.name.removeprefix("year=")
                values = {
                    col.name: col.name
                    for col in schemas.GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA
                }
                values.update(
                    macd_dif_qfq="0.0",
                    macd_dea_qfq="0.0",
                    macd_qfq="0.0",
                    kdj_k_qfq="50.0",
                    kdj_d_qfq="50.0",
                    kdj_qfq="50.0",
                    params_key="'macd_12_26_9__kdj_9_3_3'",
                    indicator_version="1",
                )
                target = paths.gold_stk_mins_qfq_macd_kdj_path(root, freq, code, year)
                _write(
                    c,
                    target,
                    f"SELECT {_projection(schemas.GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA, values)} FROM {read_parquet(file, hive_partitioning=False)}",
                )
                input_paths.add(target)
            for day in calendar:
                target = paths.gold_stk_mins_qfq_macd_kdj_state_path(root, freq, day)
                q = f"SELECT ts_code,{freq}::INTEGER freq,DATE {duckdb_string(day)} trade_date,max(trade_time)::TIMESTAMP last_trade_time,5.0::DOUBLE macd_ema_fast,5.0::DOUBLE macd_ema_slow,0.0::DOUBLE macd_dea,50.0::DOUBLE kdj_k,50.0::DOUBLE kdj_d,'macd_12_26_9__kdj_9_3_3'::VARCHAR params_key,1::INTEGER indicator_version FROM {_read(price_files)} WHERE trade_date<=DATE {duckdb_string(day)} GROUP BY ts_code"
                _write(c, target, q)
                input_paths.add(target)
            for asset in (
                f"gold_stk_mins_qfq_macd_kdj_{freq}m",
                f"gold_stk_mins_qfq_macd_kdj_state_{freq}m",
            ):
                if "_state_" not in asset:
                    by_asset[asset]["validation_paths"] = sorted(
                        str(
                            paths.gold_stk_mins_qfq_macd_kdj_path(
                                root,
                                freq,
                                p.parent.parent.name.removeprefix("ts_code="),
                                p.parent.name.removeprefix("year="),
                            )
                        )
                        for p in price_files
                    )
            if freq >= 30:
                asset = f"gold_stk_mins_qfq_nineturn_{freq}m"
                for day in {
                    d
                    for p in by_asset[asset]["calculation_windows"]
                    for d in p["target_dates"]
                }:
                    target = paths.gold_stk_mins_qfq_nineturn_path(root, freq, day)
                    _write(
                        c,
                        target,
                        f"SELECT ts_code,freq,trade_date,trade_time,0::INTEGER up_count,0::INTEGER down_count,NULL::VARCHAR nine_up_turn,NULL::VARCHAR nine_down_turn FROM {_read(price_files)} WHERE trade_date=DATE {duckdb_string(day)}",
                    )
                    input_paths.add(target)
                for p in by_asset[asset]["calculation_windows"]:
                    p["full_history_input_rows"] = c.execute(
                        f"SELECT count(*) FROM {_read(price_files)} WHERE ts_code=? AND trade_date<=CAST(? AS DATE)",
                        [p["ts_code"], p["end_time"][:10]],
                    ).fetchone()[0]
        _write(
            c,
            paths.silver_trade_calendar_path(root),
            "SELECT 'SSE'::VARCHAR exchange,unnest(?::DATE[]) trade_date,true is_open".replace(
                "unnest(?::DATE[])",
                "unnest(["
                + ",".join("DATE " + duckdb_string(d) for d in calendar)
                + "])",
            ),
        )
        input_paths.add(paths.silver_trade_calendar_path(root))
        # Listing initialization must be proven by absence of pre-listing stock rows.
        for file in sorted(
            p
            for p in input_paths
            if "/silver/quote/stock_daily/" in str(p)
            and p.parent.name < "trade_date=2021-01-27"
        ):
            c.execute(
                "CREATE OR REPLACE TEMP TABLE listing_rows AS SELECT * FROM "
                + read_parquet(file, hive_partitioning=False)
            )
            _write(c, file, "SELECT * FROM listing_rows WHERE ts_code!='688689.SH'")
        for p in by_asset["gold_stock_daily_qfq"]["calculation_windows"]:
            if p["ts_code"] == "688689.SH":
                p["previous_actual_date"] = None
                p["source_dates"] = [d for d in p["source_dates"] if d >= "2021-01-27"]
        for asset in (
            "gold_stock_daily_trend_channel",
            "gold_stock_daily_trend_channel_state",
        ):
            p = next(
                p
                for p in by_asset[asset]["calculation_windows"]
                if p["ts_code"] == "688689.SH"
            )
            p["daily_seed"] = {"initialized_from_listing": True, "state_path": None}
        life = paths.silver_stock_lifecycle_path(root)
        c.execute(
            "CREATE OR REPLACE TEMP TABLE lifecycle_rows AS SELECT * FROM "
            + read_parquet(life, hive_partitioning=False)
        )
        c.execute(
            "UPDATE lifecycle_rows SET list_date=DATE '2021-01-27' WHERE ts_code='688689.SH'"
        )
        _write(c, life, "SELECT * FROM lifecycle_rows")
        daily_files = sorted(
            p for p in input_paths if "/gold/quote/stock_daily_qfq/" in str(p)
        )
        original_daily_files = set(daily_files)
        # State can carry on dates with no approved-stock QFQ observation. Keep
        # a real, nonempty market input for the existing retained stock instead
        # of inventing observations or new repair targets for the approved 25.
        state_days = {
            d
            for p in by_asset["gold_stock_daily_trend_channel_state"][
                "calculation_windows"
            ]
            for d in p["target_dates"]
        }
        for day in sorted(state_days):
            target = paths.gold_stock_daily_qfq_path(root, day)
            if target.exists():
                continue
            _write(
                c,
                target,
                f"SELECT '000001.SZ'::VARCHAR ts_code,DATE {duckdb_string(day)} trade_date,"
                '5.0::DOUBLE open,5.5::DOUBLE high,4.5::DOUBLE low,5.0::DOUBLE AS "close",'
                "5.0::DOUBLE pre_close,0.0::DOUBLE change_amount,0.0::DOUBLE pct_chg,"
                "100.0::DOUBLE vol,1000.0::DOUBLE amount",
            )
            input_paths.add(target)
            daily_files.append(target)
        for asset in (
            "gold_stock_daily_trend_channel",
            "gold_stock_daily_trend_channel_state",
            "gold_stock_daily_qfq_nineturn",
        ):
            for day in (
                {
                    d
                    for p in by_asset[asset]["calculation_windows"]
                    for d in p["target_dates"]
                }
                | {
                    p["daily_seed"]["previous_expected_date"]
                    for p in by_asset[asset]["calculation_windows"]
                    if "daily_seed" in p
                    and not p["daily_seed"]["initialized_from_listing"]
                }
                | (set(calendar) if asset.endswith("_state") else set())
            ):
                if asset == "gold_stock_daily_trend_channel":
                    source = paths.gold_stock_daily_qfq_path(root, day)
                    if source not in original_daily_files:
                        continue
                    v = {
                        col.name: col.name
                        for col in schemas.GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA
                    }
                    v.update(
                        short_upper="5.5",
                        short_lower="4.5",
                        long_upper="5.5",
                        long_lower="4.5",
                        short_position="'INSIDE'",
                        long_position="'INSIDE'",
                        short_state="'UNKNOWN'",
                        long_state="'UNKNOWN'",
                        combined_state="'UNKNOWN'",
                        formula_version="'stock-daily-trend-channel-v1'",
                    )
                    target = paths.gold_stock_daily_trend_channel_path(root, day)
                    _write(
                        c,
                        target,
                        f"SELECT {_projection(schemas.GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA, v)} FROM {read_parquet(source, hive_partitioning=False)}",
                    )
                elif asset == "gold_stock_daily_qfq_nineturn":
                    source = paths.gold_stock_daily_qfq_path(root, day)
                    if not source.exists():
                        continue
                    target = paths.gold_stock_daily_qfq_nineturn_path(root, day)
                    _write(
                        c,
                        target,
                        f"SELECT ts_code,trade_date,0::INTEGER up_count,0::INTEGER down_count,NULL::VARCHAR nine_up_turn,NULL::VARCHAR nine_down_turn FROM {read_parquet(source, hive_partitioning=False)}",
                    )
                else:
                    target = paths.gold_stock_daily_trend_channel_state_path(root, day)
                    v = {
                        col.name: col.name
                        for col in schemas.GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
                    }
                    source = paths.gold_stock_daily_qfq_path(root, day)
                    observed = (
                        f"ts_code IN (SELECT ts_code FROM {read_parquet(source, hive_partitioning=False)})"
                        if source.exists()
                        else "false"
                    )
                    v.update(
                        trade_date="DATE " + duckdb_string(day),
                        state_source_trade_date=(
                            f"coalesce((SELECT max(q.trade_date) FROM {_read(daily_files)} q "
                            f"WHERE q.ts_code=life.ts_code AND q.trade_date<=DATE {duckdb_string(day)}),"
                            f"DATE {duckdb_string(calendar[0])})"
                        ),
                        observed_on_partition=observed,
                        short_upper_raw="5.5",
                        short_lower_raw="4.5",
                        long_upper_raw="5.5",
                        long_lower_raw="4.5",
                        short_state="'UNKNOWN'",
                        long_state="'UNKNOWN'",
                        combined_state="'UNKNOWN'",
                        formula_version="'stock-daily-trend-channel-v1'",
                    )
                    _write(
                        c,
                        target,
                        f"SELECT {_projection(schemas.GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA, v)} FROM {read_parquet(paths.silver_stock_lifecycle_path(root), hive_partitioning=False)} life WHERE list_date<=DATE {duckdb_string(day)}",
                    )
                input_paths.add(target)
        for p in by_asset["gold_stock_daily_qfq_nineturn"]["calculation_windows"]:
            p["full_history_input_rows"] = c.execute(
                f"SELECT count(*) FROM {_read(daily_files)} WHERE ts_code=?",
                [p["ts_code"]],
            ).fetchone()[0]
        for p in by_asset["gold_stock_daily_trend_channel"]["calculation_windows"]:
            if p["daily_seed"]["state_path"]:
                target = Path(p["daily_seed"]["state_path"])
                # A literal prior state binds its source date exactly, including suspended dates.
                c.execute(
                    "CREATE OR REPLACE TEMP TABLE seed_rows AS SELECT * FROM "
                    + read_parquet(target, hive_partitioning=False)
                )
                c.execute(
                    "UPDATE seed_rows SET state_source_trade_date=CAST(? AS DATE) WHERE ts_code=?",
                    [p["daily_seed"]["state_source_trade_date"], p["ts_code"]],
                )
                _write(c, target, "SELECT * FROM seed_rows")
    args = {
        "lake_root": root,
        "run_root": Path(old["run_root"]).parent / f"run_id={uuid4()}",
        "scopes": [
            FactorRepairScope(
                **{**s, "factor_ranges": tuple(tuple(r) for r in s["factor_ranges"])}
            )
            for s in old["scopes"]
        ],
        "source_rows": old["source_rows"],
        "anchors": old["anchors"],
        "endpoints": [
            AssetRepairEndpoint(
                **{
                    k: tuple(v) if k in ("expected_dates", "context_times") else v
                    for k, v in e.items()
                }
            )
            for e in endpoints
        ],
        "units": units,
        "target_paths": [p for u in units for p in u["target_paths"]],
        "input_stats": [
            (str(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(input_paths)
        ],
        "partition_validation": old["partition_validation"],
    }
    return freeze_stock_factor_repair(**args)


def _task(plan, asset="gold_stk_mins_qfq_macd_kdj_1m", code="688689.SH"):
    return next(
        t
        for t in indicator_replay_tasks(plan)
        if t["asset_key"] == asset and t["profile"]["ts_code"] == code
    )


def _prepare_price(c, plan, task):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        build_repair_target_candidate,
    )

    unit = prices.unit_for(
        plan,
        "gold_stock_daily_qfq"
        if task["profile"]["freq"] is None
        else f"gold_stk_mins_qfq_{task['profile']['freq']}m",
    )
    if task["profile"]["freq"] is None:
        targets = unit["target_paths"]
    else:
        targets = unit["target_paths"]
    factors = {d for p in unit["calculation_windows"] for d in p["target_dates"]}
    if task["profile"]["freq"] is None:
        for p in unit["calculation_windows"]:
            factors.update(
                before
                for before, day in zip(p["source_dates"], p["source_dates"][1:])
                if day in p["target_dates"]
            )
    factors = {
        d
        for d in factors
        if d.replace("-", "") in {r["trade_date"] for r in plan["source_rows"]}
    }
    for day in sorted(factors):
        prices.build_factor_day(c, plan, day)
    for target in targets:
        build_repair_target_candidate(c, plan, unit, Path(target))


def test_macd_replay_uses_price_candidate_and_literal_first_bar(
    indicator_plan, tmp_path
):
    plan = indicator_plan
    task = _task(plan)
    target = paths.gold_stk_mins_qfq_macd_kdj_path(
        Path(plan["lake_root"]), 1, "688689.SH", "2026"
    )
    before = file_identity(target)
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        _prepare_price(c, plan, task)
        result = replay_indicator_task(c, plan, task)
        assert result["completed_rows"] > 241
        fragments = read_indicator_task(plan, task)
        output = next(
            Path(r["outputs"]["result"]["path"])
            for r in fragments
            if "2026-06-29" in r["dates"]
        )
        row = c.execute(
            f"SELECT macd_dif_qfq,macd_dea_qfq,macd_qfq,kdj_k_qfq,kdj_d_qfq,kdj_qfq FROM {read_parquet(output, hive_partitioning=False)} WHERE trade_time=TIMESTAMP '2026-06-29 09:30:00'"
        ).fetchone()
        assert row == pytest.approx(
            (
                0.19943019943019943,
                0.039886039886039886,
                0.3190883190883191,
                60.0,
                53.33333333333333,
                73.33333333333333,
            )
        )
        unit = prices.unit_for(plan, task["asset_key"])
        record = build_indicator_target_candidate(c, plan, unit, target)
        assert record["validated"] is False and record["business_pending"]
        proof = audit_indicator_batch(
            c, plan, unit, [str(target)], pending={str(target): record}
        )
        seal_indicator_batch(plan, {str(target): record}, proof)
        assert read_repair_candidate_record(plan, target)["validated"]
        replay_indicator_task(c, plan, task, audit=True)
        build_indicator_target_candidate(c, plan, unit, target, audit=True)
    assert file_identity(target) == before


def test_daily_and_minute_replays_use_original_kernels_and_continue_segments(
    indicator_plan, tmp_path, monkeypatch
):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_indicators as replay,
    )

    plan = indicator_plan
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        for asset in (
            "gold_stock_daily_trend_channel",
            "gold_stock_daily_qfq_nineturn",
            *(f"gold_stk_mins_qfq_nineturn_{f}m" for f in (30, 60, 90, 120)),
        ):
            task = _task(plan, asset)
            _prepare_price(c, plan, task)
            if "nineturn" in asset:
                # Two actual business days per segment exercises compact context and seeds.
                original = replay.plan_repair_calculation_windows

                def two_day_windows(rows, **kw):
                    return tuple(
                        tuple(d for d, n in rows[i : i + 2])
                        for i in range(0, len(rows), 2)
                    )

                monkeypatch.setattr(
                    replay, "plan_repair_calculation_windows", two_day_windows
                )
            result = replay_indicator_task(c, plan, task)
            fragments = read_indicator_task(plan, task)
            assert result["completed_rows"] == sum(
                n for d, n in task["profile"]["trade_date_rows"]
            )
            for fragment in fragments:
                output = Path(fragment["outputs"]["result"]["path"])
                assert_replay_schema = c.execute(
                    "DESCRIBE SELECT * FROM "
                    + read_parquet(output, hive_partitioning=False)
                ).fetchall()
                assert [r[0] for r in assert_replay_schema] == [
                    col.name for col in indicator_schema(asset)
                ]
            if asset == "gold_stock_daily_trend_channel":
                output = Path(fragments[0]["outputs"]["result"]["path"])
                row = c.execute(
                    "SELECT short_upper,short_lower,long_upper,long_lower FROM "
                    + read_parquet(output, hive_partitioning=False)
                    + " WHERE trade_date=DATE '2021-01-27'"
                ).fetchone()
                assert row == pytest.approx((5.5, 4.5, 5.5, 4.5))
                assert sum(
                    c.execute(
                        "SELECT count(*) FROM "
                        + read_parquet(
                            Path(f["outputs"]["state"]["path"]), hive_partitioning=False
                        )
                    ).fetchone()[0]
                    for f in fragments
                ) == len(task["state_profile"]["target_dates"])
            else:
                assert "close" not in [col.name for col in indicator_schema(asset)]
                assert len(fragments) > 1
                replay_indicator_task(c, plan, task, audit=True)
                monkeypatch.setattr(replay, "plan_repair_calculation_windows", original)


def test_complete_contract_rejects_rehashed_indicator_omissions(freeze_case):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        validate_indicator_repair_units,
    )

    args, _ = freeze_case
    plan = freeze_stock_factor_repair(**args)
    indicator = prices.unit_for(plan, "gold_stk_mins_qfq_macd_kdj_1m")
    assert len(indicator_repair_assets()) == 21
    assert (
        sum(
            len(prices.unit_for(plan, a)["calculation_windows"])
            for a in indicator_repair_assets()
        )
        == 525
    )
    mutations = (
        lambda u: u["calculation_windows"].pop(),
        lambda u: u["target_paths"].pop(),
        lambda u: u["validation_paths"].clear(),
        lambda u: u["calendar_dates"].reverse(),
        lambda u: u["calculation_windows"][0]["windows"].pop(),
        lambda u: u["calculation_windows"][0].update(
            previous_expected_date="2020-01-01"
        ),
        lambda u: u["calculation_windows"][0].update(end_time="2026-10-13 15:00:00"),
        lambda u: u["calculation_windows"][0].update(freq=120),
    )
    for mutate in mutations:
        corrupt = deepcopy(plan)
        mutate(prices.unit_for(corrupt, indicator["asset_key"]))
        corrupt["plan_hash"] = repair_hash(
            {k: v for k, v in corrupt.items() if k != "plan_hash"}
        )
        with pytest.raises(FactorRepairError):
            validate_indicator_repair_units(corrupt)


def test_replay_refuses_raw_price_fallback_and_owned_fragment_corruption(
    indicator_plan, tmp_path, monkeypatch
):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_execution as execution,
    )

    plan = indicator_plan
    task = _task(plan)
    before = {
        i["path"]: file_identity(Path(i["path"])) for i in plan["target_preimages"]
    }
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        with pytest.raises(FactorRepairError, match="price_candidate_required"):
            replay_indicator_task(c, plan, task)
        _prepare_price(c, plan, task)
        directory = Path(plan["run_root"]) / "inputs/indicator_replay" / task["task_id"]
        original_copy = execution.bounded_repair_copy

        def failed_copy(*a, **kw):
            original_copy(*a, **kw)
            if Path(a[3]).parent == directory:
                raise RuntimeError("injected COPY exit")

        monkeypatch.setattr(execution, "bounded_repair_copy", failed_copy)
        with pytest.raises(RuntimeError, match="COPY exit"):
            replay_indicator_task(c, plan, task)
        directory = Path(plan["run_root"]) / "inputs/indicator_replay" / task["task_id"]
        assert list(directory.glob("*.partial"))
        monkeypatch.setattr(execution, "bounded_repair_copy", original_copy)
        replay_indicator_task(c, plan, task)
        identities = {str(p): file_identity(p) for p in directory.glob("*")}
        replay_indicator_task(c, plan, task)
        assert identities == {str(p): file_identity(p) for p in directory.glob("*")}
        output = directory / "result-1.parquet"
        output.write_bytes(b"corrupt completed fragment")
        with pytest.raises(FactorRepairError, match="fragment_drift"):
            read_indicator_task(plan, task)
    assert all(file_identity(Path(p)) == i for p, i in before.items())


def test_transferred_indicator_does_not_repeat_copy_before_business_seal(indicator_plan, tmp_path, monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_candidates as candidates,
    )
    plan = indicator_plan
    task = _task(plan)
    target = paths.gold_stk_mins_qfq_macd_kdj_path(Path(plan["lake_root"]), 1, "688689.SH", "2026")
    unit = prices.unit_for(plan, task["asset_key"])
    with connect_configured_duckdb(RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill") as connection:
        _prepare_price(connection, plan, task)
        replay_indicator_task(connection, plan, task)
        replace = candidates.replace_repair_file
        def interrupted(source, output):
            replace(source, output)
            raise OSError("after indicator rename")
        monkeypatch.setattr(candidates, "replace_repair_file", interrupted)
        with pytest.raises(OSError, match="after indicator rename"):
            build_indicator_target_candidate(connection, plan, unit, target)
        output = Path(plan["run_root"]) / "candidates" / target.relative_to(Path(plan["lake_root"]))
        identity = file_identity(output)
        monkeypatch.setattr(candidates, "replace_repair_file", replace)
        class NoSQL:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("transferred indicator must not be recalculated")
        record = build_indicator_target_candidate(NoSQL(), plan, unit, target)
        assert record["business_pending"] is True and record["validated"] is False
        assert file_identity(output) == identity
        proof = audit_indicator_batch(connection, plan, unit, [str(target)], pending={str(target): record})
        seal_indicator_batch(plan, {str(target): record}, proof)
        assert read_repair_candidate_record(plan, target)["validated"] is True


def test_partial_batch_seal_reuses_durable_full_proof_without_business_sql(indicator_plan, tmp_path, monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_indicators as module,
    )
    plan = indicator_plan
    root = Path(plan["lake_root"])
    asset = "gold_stk_mins_qfq_macd_kdj_1m"
    unit = prices.unit_for(plan, asset)
    targets = [paths.gold_stk_mins_qfq_macd_kdj_path(root, 1, code, "2026") for code in ("688689.SH", "600016.SH")]
    with connect_configured_duckdb(RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill") as connection:
        for code in ("688689.SH", "600016.SH"):
            task = _task(plan, asset, code)
            _prepare_price(connection, plan, task)
            replay_indicator_task(connection, plan, task)
        records = {str(target): build_indicator_target_candidate(connection, plan, unit, target) for target in targets}
        identities = [file_identity(Path(plan["run_root"]) / record["candidate_relative_path"]) for record in records.values()]
        proof = audit_indicator_batch(connection, plan, unit, list(records), pending=records)
        write = module.write_candidate_record
        def interrupted(run, record):
            if record.get("validated") is True and record["target_relative_path"] == targets[1].relative_to(root).as_posix():
                raise OSError("before second business seal")
            return write(run, record)
        monkeypatch.setattr(module, "write_candidate_record", interrupted)
        with pytest.raises(OSError, match="before second"):
            seal_indicator_batch(plan, records, proof)
        monkeypatch.setattr(module, "write_candidate_record", write)
        class NoSQL:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("persisted batch proof must not rerun SQL")
        first = build_indicator_target_candidate(NoSQL(), plan, unit, targets[0])
        second = build_indicator_target_candidate(NoSQL(), plan, unit, targets[1])
        assert first["validated"] is True and second["business_pending"] is True
        restored = audit_indicator_batch(NoSQL(), plan, unit, [str(t) for t in targets],
            pending={str(targets[1]): second}, completed={str(targets[0]): first})
        assert restored == proof
        seal_indicator_batch(plan, {str(targets[1]): second}, restored)
        assert all(read_repair_candidate_record(plan, target)["validated"] for target in targets)
        assert [file_identity(Path(identity.path)) for identity in identities] == identities


def test_scoped_indicator_relations_keep_missing_keys_visible(tmp_path):
    """Four-column projection contract used by the real MACD coverage predicates.

    Literal bars below test SQL/identity coverage only, not the indicator formula.
    The separate price/replay goldens remain the formula evidence.
    """
    from datetime import date

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
        _batch_rows,
        _repair_indicator_scope,
    )
    from orchestrator.defs.stk_mins_qfq_macd_kdj_rules import (
        macd_kdj_source_coverage_sql,
    )
    unit={'calculation_windows':[
        {'ts_code':'688689.SH','target_dates':['2026-06-29']},
        {'ts_code':'001331.SZ','target_dates':['2026-06-30']}]}
    with duckdb.connect() as c:
        _repair_indicator_scope(c,unit,['2026-06-29'])
        assert c.execute('SELECT ts_code,day FROM indicator_approved').fetchall()==[('688689.SH',date(2026,6,29))]
        source=tmp_path/'source.parquet';output=tmp_path/'output.parquet'
        rows="""SELECT code::VARCHAR ts_code,1::INTEGER freq,DATE '2026-06-29' trade_date,
            stamp::TIMESTAMP trade_time FROM (VALUES
            ('688689.SH','2026-06-29 09:30:00'),('688689.SH','2026-06-29 09:31:00'),
            ('001331.SZ','2026-06-29 09:30:00'),('000001.SZ','2026-06-29 09:30:00')) x(code,stamp)"""
        c.execute(copy_query_to_parquet(rows,source))
        _batch_rows(c,'scoped_source',[source],['2026-06-29'],annual=True,
                    columns='ts_code,freq,trade_date,trade_time',scope_relation='indicator_approved')
        assert c.execute('SELECT DISTINCT ts_code FROM scoped_source').fetchall()==[('688689.SH',)]
        c.execute(copy_query_to_parquet("SELECT * FROM ("+rows+") WHERE trade_time=TIMESTAMP '2026-06-29 09:30:00'",output))
        _batch_rows(c,'scoped_output',[output],['2026-06-29'],annual=True,
                    columns='ts_code,freq,trade_date,trade_time',scope_relation='indicator_approved')
        query=macd_kdj_source_coverage_sql(source='scoped_source',indicator='scoped_output',freq=1,dates=['2026-06-29'])
        # The shared producer explicitly CASTs its first result column to VARCHAR
        # (stk_mins_qfq_macd_kdj_rules.py), unlike indicator_approved.day above.
        assert c.execute(query).fetchall()==[('2026-06-29',2,1)]
        c.execute(copy_query_to_parquet(rows,output))
        _batch_rows(c,'scoped_output',[output],['2026-06-29'],annual=True,
                    columns='ts_code,freq,trade_date,trade_time',scope_relation='indicator_approved')
        assert c.execute(query).fetchall()==[('2026-06-29',2,2)]
