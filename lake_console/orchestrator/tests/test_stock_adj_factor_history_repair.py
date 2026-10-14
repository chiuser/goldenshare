"""Isolated source, scope and durable-transfer contracts; no formal resources."""

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    APPROVED_FACTOR_RANGES,
    FactorRepairError,
    FactorRepairScope,
    RepairBudget,
    atomic_repair_json,
    check_repair_path,
    fetch_current_factor_rows,
    file_identity,
    inspect_factor_rows,
    normalized_factor_rows,
    write_candidate_record,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    build_scoped_file_candidate,
)
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
)


@pytest.fixture
def scope():
    return FactorRepairScope("688689.SH", (("2026-06-29", "2026-07-07"),),
                             "2026-10-12", "2026-10-12", "2021-01-27")


def rows():
    return [{"ts_code": "688689.SH", "trade_date": d, "adj_factor": 1.0597}
            for d in ("20260629", "20260630", "20260701", "20260702", "20260703", "20260706", "20260707")]


def test_approved_scope_and_budget_are_exact():
    assert len(APPROVED_FACTOR_RANGES) == 25
    assert sum(r[3] for r in APPROVED_FACTOR_RANGES) == 2489
    assert asdict(RepairBudget()) == {
        "memory_limit": "512MiB", "max_rss": 1024**3, "threads": 2,
        "max_spill": 2 * 1024**3, "max_candidate_bytes": 10 * 1024**3,
        "max_stock_batch_rows": 100_000, "progress_interval": 30,
    }


@pytest.mark.parametrize("code,start,end,basis", [
    ("601198.SH", "2026-06-29", "2026-07-07", None),
    ("000668.SZ", "2026-06-29", "2026-07-07", None),
    ("688689.SH", "2021-01-27", "2026-07-07", None),
    ("688689.SH", "2026-06-29", "2026-07-07", "2020-01-01"),
    ("000430.SZ", "2025-12-29", "2026-07-03", "2021-01-27"),
])
def test_scope_cannot_expand_factor_or_daily_history(code, start, end, basis):
    with pytest.raises(FactorRepairError):
        FactorRepairScope(code, ((start, end),), "2026-10-12", "2026-10-12", basis)


def test_source_is_explicit_paginated_and_sorted(scope):
    calls = []
    class Source:
        def call(self, api, params, fields):
            calls.append((api, params, fields))
            return SimpleNamespace(columns=fields, rows=list(reversed(rows())))
    observed = fetch_current_factor_rows(scope, Source())
    assert observed == normalized_factor_rows(scope, rows())
    assert calls == [("adj_factor", {"ts_code": "688689.SH", "start_date": "20260629",
                                   "end_date": "20260707", "limit": 6000, "offset": 0},
                      ("ts_code", "trade_date", "adj_factor"))]


@pytest.mark.parametrize("mutator", [
    lambda r: r.pop(),
    lambda r: r.append(r[0].copy()),
    lambda r: r[0].update(ts_code="000001.SZ"),
    lambda r: r[0].update(trade_date="20260628"),
    lambda r: r[0].update(trade_date="2026-06-29"),
    lambda r: r[0].update(adj_factor=0),
    lambda r: r[0].update(adj_factor=float("nan")),
    lambda r: r[0].update(adj_factor=float("inf")),
    lambda r: r[0].update(extra="not_a_source_field"),
])
def test_invalid_or_incomplete_source_is_rejected(scope, mutator):
    values = rows()
    mutator(values)
    with pytest.raises(FactorRepairError):
        normalized_factor_rows(scope, values)


def test_cancel_and_source_error_are_never_empty_success(scope):
    class Source:
        def call(self, *_args):
            raise ConnectionError("source unavailable")
    with pytest.raises(ConnectionError):
        fetch_current_factor_rows(scope, Source())
    with pytest.raises(FactorRepairError, match="canceled"):
        fetch_current_factor_rows(scope, Source(), cancel=lambda: True)


def test_zero_column_response_is_not_accepted(scope):
    source = SimpleNamespace(call=lambda *args: SimpleNamespace(columns=(), rows=[]))
    with pytest.raises(FactorRepairError, match="columns"):
        fetch_current_factor_rows(scope, source)


def test_atomic_record_and_safe_fingerprint(tmp_path):
    path = tmp_path / "record.json"
    atomic_repair_json(path, {"ready": True})
    assert file_identity(path).size > 0
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(FactorRepairError, match="symlink"):
        check_repair_path(alias / "record.json")
    with pytest.raises(FactorRepairError, match="invalid"):
        check_repair_path(Path("relative"))


@pytest.fixture
def candidate_context(tmp_path):
    lake = tmp_path / "lake"
    run = tmp_path / "staging"
    target = lake / "raw/tushare/adj_factor/trade_date=2026-06-29/part-000.parquet"
    target.parent.mkdir(parents=True)
    with duckdb.connect() as c:
        c.execute("CREATE TABLE original(ts_code VARCHAR,trade_date VARCHAR,adj_factor DOUBLE)")
        c.execute("INSERT INTO original VALUES ('688689.SH','20260629',1.054),('000001.SZ','20260629',123.456789)")
        c.execute("COPY original TO ? (FORMAT PARQUET)", [str(target)])
        c.execute("CREATE TABLE replacement AS SELECT '688689.SH'::VARCHAR ts_code,'20260629'::VARCHAR trade_date,1.0597::DOUBLE adj_factor")
        c.execute("CREATE TABLE approved AS SELECT ts_code,trade_date FROM replacement")
        yield c, lake, run, target


def candidate(c, lake, run, target, **kwargs):
    return build_scoped_file_candidate(
        c, lake_root=lake, run_root=run, target=target,
        replacement_relation="replacement", approved_keys_relation="approved",
        schema=RAW_TUSHARE_ADJ_FACTOR_SCHEMA, key_columns=("ts_code", "trade_date"),
        plan_hash="f" * 64, unit_id="factor:2026-06",
        asset_key="raw_tushare_adj_factor", partition_key="2026-06-29",
        validator=lambda *_args: None, finalize_record=lambda record: write_candidate_record(run,record), **kwargs,
    )


def test_scoped_candidate_preserves_other_stock_and_original(candidate_context):
    c, lake, run, target = candidate_context
    before = file_identity(target)
    record = candidate(c, lake, run, target)
    assert file_identity(target) == before
    result = c.execute("SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                       [str(run / record["candidate_relative_path"])]).fetchall()
    assert result == [("000001.SZ", "20260629", 123.456789), ("688689.SH", "20260629", 1.0597)]
    assert record["changed_stock_rows"] == 1
    assert record["original_rows"] == record["candidate_rows"] == 2
    assert len(list((run / "checkpoints/candidates").glob("*.json"))) == 1


def test_existing_incomplete_candidate_is_rebuilt_and_record_is_independent(candidate_context):
    c, lake, run, target = candidate_context
    record = candidate(c, lake, run, target)
    (run / record["candidate_relative_path"]).write_bytes(b"incomplete")
    for p in (run / "checkpoints/candidates").glob("*.json"):
        import json
        p.write_text(json.dumps({**record,"validated":False}))
    replay = candidate(c, lake, run, target)
    assert replay["candidate_sha256"] == record["candidate_sha256"]
    assert file_identity(target).sha256 == record["preimage_sha256"]


def test_equivalent_factor_does_not_hide_downstream_work(candidate_context):
    c, lake, run, target = candidate_context
    c.execute("UPDATE replacement SET adj_factor=1.054")
    record = candidate(c, lake, run, target)
    assert record["no_op"]
    assert record["candidate_relative_path"] is None
    assert not (run / "candidates").exists()


@pytest.mark.parametrize("query", [
    "INSERT INTO replacement SELECT * FROM replacement",
    "UPDATE replacement SET ts_code='000001.SZ'",
    "UPDATE replacement SET trade_date='20260630'",
    "UPDATE approved SET ts_code='000001.SZ'",
])
def test_unapproved_duplicate_or_missing_key_cannot_write_formal(candidate_context, query):
    c, lake, run, target = candidate_context
    before = file_identity(target)
    c.execute(query)
    with pytest.raises(FactorRepairError):
        candidate(c, lake, run, target)
    assert file_identity(target) == before


def test_factor_inspection_reads_exact_keys_without_writing_candidate(tmp_path, scope):
    root = tmp_path / "lake"
    lifecycle = silver_stock_lifecycle_path(root)
    lifecycle.parent.mkdir(parents=True)
    with duckdb.connect() as c:
        c.execute("""CREATE TABLE lifecycle AS SELECT '688689.SH'::VARCHAR ts_code,
                  DATE '2021-01-27' list_date,NULL::DATE delist_date,true is_cny_stock,
                  'L'::VARCHAR list_status""")
        c.execute("COPY lifecycle TO ? (FORMAT PARQUET)", [str(lifecycle)])
        for r in rows():
            d = r["trade_date"]
            day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            for raw in (True, False):
                p = raw_adj_factor_path(root, day) if raw else silver_adj_factor_path(root, day)
                p.parent.mkdir(parents=True)
                c.execute("CREATE OR REPLACE TABLE factor AS SELECT ?::VARCHAR ts_code,?::VARCHAR trade_date,1.054::DOUBLE adj_factor",
                          [scope.ts_code, d])
                q = "SELECT * FROM factor" if raw else "SELECT ts_code,strptime(trade_date,'%Y%m%d')::DATE trade_date,adj_factor FROM factor"
                c.execute(f"COPY ({q}) TO ? (FORMAT PARQUET)", [str(p)])
        inspection = inspect_factor_rows(c, root, [scope], rows())
        assert inspection["source_rows"] == inspection["changed_factor_keys"] == 7
        assert len(inspection["factor_files"]) == 14
        assert not (tmp_path / "candidates").exists()


@pytest.fixture
def repair_endpoints(scope):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        AssetRepairEndpoint,
        approved_repair_asset_keys,
    )
    context = tuple(f"2026-06-26 14:{n:02}:00" for n in range(8))
    endpoints = []
    for asset in approved_repair_asset_keys()[2:]:
        freq = next((f for f in (1, 5, 15, 30, 60, 90, 120) if asset.endswith(f"_{f}m")), None)
        kwargs = {"asset_key": asset, "ts_code": scope.ts_code, "freq": freq,
                  "calculation_start_date": "2026-06-29", "end_time": "2026-10-12",
                  "expected_dates": ("2026-06-29", "2026-10-12"), "calculation_rows": 10}
        if "macd_kdj" in asset:
            kwargs.update(previous_expected_date="2026-06-26", seed_last_trade_time=context[-1],
                          context_times=context)
        if asset.startswith("gold_stock_daily"):
            kwargs.update(calculation_start_date="2021-01-27", expected_dates=("2021-01-27", "2026-10-12"))
        endpoints.append(AssetRepairEndpoint(**kwargs))
    return tuple(endpoints)


def test_asset_tails_are_independent_and_complete(scope, repair_endpoints):
    from dataclasses import replace

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        validate_asset_repair_endpoints,
    )
    validate_asset_repair_endpoints([scope], repair_endpoints)
    newer = replace(scope, as_of_trade_date="2026-10-13", repair_end_trade_date="2026-10-13")
    tails = tuple(replace(e, end_time="2026-10-13", expected_dates=e.expected_dates + ("2026-10-13",))
                  if "macd_kdj" not in e.asset_key else e for e in repair_endpoints)
    validate_asset_repair_endpoints([newer], tails)
    with pytest.raises(FactorRepairError, match="incomplete"):
        validate_asset_repair_endpoints([scope], repair_endpoints[:-1])
    with pytest.raises(FactorRepairError, match="incomplete"):
        validate_asset_repair_endpoints([scope], repair_endpoints + repair_endpoints[:1])
    with pytest.raises(FactorRepairError, match="range"):
        validate_asset_repair_endpoints([scope], tails)


@pytest.mark.parametrize("field,value", [
    ("context_times", ("2026-06-26 15:00:00",)),
    ("previous_expected_date", "2026-06-29"),
    ("seed_last_trade_time", "2026-06-25 15:00:00"),
    ("freq", 120),
])
def test_endpoint_rejects_invalid_seed_frequency(scope, repair_endpoints, field, value):
    from dataclasses import replace

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        validate_asset_repair_endpoints,
    )
    endpoints = tuple(replace(e, **{field: value}) if e.asset_key == "gold_stk_mins_qfq_macd_kdj_1m"
                      else e for e in repair_endpoints)
    with pytest.raises(FactorRepairError):
        validate_asset_repair_endpoints([scope], endpoints)


def test_windows_keep_days_years_and_suspended_state():
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        plan_repair_calculation_windows,
    )
    assert plan_repair_calculation_windows([
        ("2025-12-30", 50000), ("2025-12-31", 50001), ("2026-01-02", 0), ("2026-01-05", 9),
    ]) == (("2025-12-30",), ("2025-12-31",), ("2026-01-02", "2026-01-05"))
    with pytest.raises(FactorRepairError, match="single_day_budget"):
        plan_repair_calculation_windows([("2026-01-05", 100001)])
    with pytest.raises(FactorRepairError, match="row_budget"):
        plan_repair_calculation_windows([], max_rows=100001)
    with pytest.raises(FactorRepairError, match="counts_invalid"):
        plan_repair_calculation_windows([("2026-01-05", 1), ("2026-01-05", 1)])


def test_bounded_profile_retains_suspension_dates_and_rejects_state_gap(tmp_path, scope):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        inspect_repair_asset_rows,
    )

    files = []
    with duckdb.connect() as c:
        for day in ("2026-06-29", "2026-07-01"):
            p = tmp_path / f"{day}.parquet"
            c.execute("CREATE OR REPLACE TABLE source_rows AS SELECT '688689.SH' ts_code,?::DATE trade_date,1::INTEGER freq", [day])
            c.execute("COPY source_rows TO ? (FORMAT PARQUET)", [str(p)])
            files.append(p)
        args = {"paths": files, "scopes": [scope],
                "expected_dates": ("2026-06-29", "2026-06-30", "2026-07-01"),
                "starts": {scope.ts_code: "2026-06-29"}}
        observed = inspect_repair_asset_rows(c, asset_key="gold_stock_daily_qfq", **args)
        assert observed["profiles"][0]["expected_dates"] == args["expected_dates"]
        assert observed["profiles"][0]["observed_dates"] == ("2026-06-29", "2026-07-01")
        assert observed["profiles"][0]["calculation_rows"] == 2
        with pytest.raises(FactorRepairError, match="state_expected_date_missing"):
            inspect_repair_asset_rows(c, asset_key="gold_stock_daily_trend_channel_state", **args)
        with pytest.raises(FactorRepairError, match="duplicate"):
            inspect_repair_asset_rows(c, asset_key="gold_stock_daily_qfq", **{**args, "paths": files + files})


def test_file_inventory_deduplicates_full_retained_files(candidate_context):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        inspect_repair_file_inventory,
    )

    c, _lake, _run, target = candidate_context
    observed = inspect_repair_file_inventory(c, [target, target])
    assert observed["file_count"] == 1
    assert observed["full_file_rows"] == 2
    assert observed["file_bytes"] == target.stat().st_size
    with pytest.raises(FactorRepairError, match="canceled"):
        inspect_repair_file_inventory(c, [target], cancel=lambda: True)


@pytest.fixture
def freeze_case(tmp_path, monkeypatch, repair_endpoints):
    from datetime import date, timedelta
    from uuid import uuid4

    from orchestrator.defs.bootstrap import stock_adj_factor_history_repair as module

    lake = tmp_path / "lake"
    staging = tmp_path / "staging"
    lake.mkdir(); staging.mkdir()
    monkeypatch.setattr(module, "DEFAULT_LAKE_ROOT", str(lake))
    monkeypatch.setattr(module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    all_scopes, source, anchors, endpoints = [], [], [], []
    from dataclasses import replace
    for code, start, end, count in APPROVED_FACTOR_RANGES:
        s = FactorRepairScope(code, ((start, end),), "2026-10-13", "2026-10-13",
                              "2021-01-27" if code == "688689.SH" else None)
        all_scopes.append(s)
        d = date.fromisoformat(start)
        days = []
        while len(days) < count:
            if d.weekday() < 5:
                days.append(d.strftime("%Y%m%d"))
            d += timedelta(days=1)
        assert days[-1] <= end.replace("-", "")
        source.extend({"ts_code": code, "trade_date": d, "adj_factor": 1.5} for d in days)
        anchors.append({"ts_code": code, "trade_date": s.as_of_trade_date, "adj_factor": 2.0})
        for e in repair_endpoints:
            first = "2021-01-27" if e.asset_key.startswith("gold_stock_daily") and code == "688689.SH" else start
            seed_day = date.fromisoformat(first) - timedelta(days=1)
            while seed_day.weekday() >= 5:
                seed_day -= timedelta(days=1)
            context = tuple(f"{seed_day.isoformat()} 14:{i:02}:00" for i in range(8))
            extra = ({"previous_expected_date": seed_day.isoformat(), "context_times": context,
                      "seed_last_trade_time": context[-1]} if "macd_kdj" in e.asset_key else {})
            endpoints.append(replace(e, ts_code=code, calculation_start_date=first,
                                     expected_dates=(first, "2026-10-12"), **extra))
    from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG
    catalog = {e.asset_key: e for e in LAKE_ASSET_CATALOG}
    units, targets, stats = [], [], []
    for asset in module.approved_repair_asset_keys():
        relative = catalog[asset].path_template.removeprefix("data_lake/").format(
            partition_key="2026-06-29", ts_code="688689.SH", year="2026")
        path = lake / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"formal input untouched")
        st = path.stat()
        targets.append(str(path)); stats.append((str(path), st.st_size, st.st_mtime_ns))
        units.append({"asset_key": asset, "stock_codes": [r[0] for r in APPROVED_FACTOR_RANGES],
                      "target_paths": [str(path)]})
    from dataclasses import asdict

    from orchestrator.defs import paths
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        repair_price_dates,
    )
    for unit in units:
        asset = unit["asset_key"]
        if asset != "gold_stock_daily_qfq" and not (asset.startswith("gold_stk_mins_qfq_") and "macd" not in asset and "nineturn" not in asset):
            continue
        unit["calculation_windows"] = []
        unit["target_paths"] = []
        for index,e in enumerate(endpoints):
            if e.asset_key != asset:
                continue
            endpoints[index] = e = replace(e,calculation_rows=2)
            profile = {"ts_code":e.ts_code,"freq":e.freq,"windows":[[d] for d in e.expected_dates],
                "observed_dates":list(e.expected_dates),"end_time":e.end_time,
                "trade_date_rows":[[d,1] for d in e.expected_dates],"previous_actual_date":None}
            if asset == "gold_stock_daily_qfq":
                profile["source_dates"] = list(e.expected_dates)
            profile["target_dates"] = list(repair_price_dates({"scopes":[asdict(sc) for sc in all_scopes],"source_rows":source},profile,daily=asset=="gold_stock_daily_qfq"))
            unit["calculation_windows"].append(profile)
            for d in profile["target_dates"]:
                name = paths.gold_stock_daily_qfq_path(lake,d) if e.freq is None else paths.gold_stk_mins_qfq_path(lake,e.freq,e.ts_code,d[:4])
                unit["target_paths"].append(str(name))
        unit["target_paths"] = sorted(set(unit["target_paths"]))
        unit["validation_paths"] = unit["target_paths"] if asset != "gold_stock_daily_qfq" else []
    source_inventory = sorted({str(paths.silver_stock_daily_path(lake,d)) for unit in units if unit["asset_key"] == "gold_stock_daily_qfq" for profile in unit["calculation_windows"] for d in profile["source_dates"]})
    for unit in units:
        if unit["asset_key"] == "gold_stock_daily_qfq":
            for profile in unit["calculation_windows"]:
                profile["source_inventory_paths"] = source_inventory
    days = {r["trade_date"] for r in source}
    for unit in units:
        if unit["asset_key"] in ("raw_tushare_adj_factor","silver_adj_factor"):
            helper = paths.raw_adj_factor_path if unit["asset_key"] == "raw_tushare_adj_factor" else paths.silver_adj_factor_path
            unit["target_paths"] = sorted(str(helper(lake,f"{d[:4]}-{d[4:6]}-{d[6:]}")) for d in days)
    targets = sorted({name for unit in units for name in unit["target_paths"]})
    stats = []
    for name in sorted(set(targets)|set(source_inventory)):
        path = Path(name);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b"formal input untouched")
        st = path.stat();stats.append((name,st.st_size,st.st_mtime_ns))
    target = Path(targets[0])
    args = {"lake_root": lake, "run_root": staging / "stock_adj_factor_history_repair" / f"run_id={uuid4()}",
            "scopes": all_scopes, "source_rows": source, "anchors": anchors, "endpoints": endpoints,
            "input_stats": stats, "target_paths": targets, "units": units, "writer_guard": lambda: None,
            "partition_validation":{"partition_set":"cn_a_stock_current_trade_days","checked_on":"2026-10-14",
                "registered_keys":sorted({f"{r['trade_date'][:4]}-{r['trade_date'][4:6]}-{r['trade_date'][6:]}" for r in source})}}
    return args, target


def test_freeze_hash_and_inputs_are_complete_without_formal_write(freeze_case):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        freeze_stock_factor_repair,
        validate_repair_plan,
    )
    args, target = freeze_case
    before = file_identity(target)
    guarded = []
    plan = freeze_stock_factor_repair(**{**args, "writer_guard": lambda: guarded.append(True)})
    assert len(guarded) == 2
    assert len(plan["source_rows"]) == 2489
    assert len(plan["endpoints"]) == 725
    assert (args["run_root"] / "plan.json").is_file()
    assert file_identity(target) == before
    validate_repair_plan(plan, plan["plan_hash"])
    with pytest.raises(FactorRepairError, match="conflict"):
        freeze_stock_factor_repair(**args)


@pytest.mark.parametrize("failure", ["writer", "drift", "source", "anchors", "endpoints", "units", "cancel"])
def test_freeze_rejects_incomplete_or_changed_facts_without_creating_run(freeze_case, failure):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        freeze_stock_factor_repair,
    )

    args, target = freeze_case
    if failure == "writer":
        args["writer_guard"] = lambda: (_ for _ in ()).throw(FactorRepairError("writers_not_idle"))
    elif failure == "drift":
        target.write_bytes(b"external legitimate change")
    elif failure == "source":
        args["source_rows"] = args["source_rows"][:-1]
    elif failure == "anchors":
        args["anchors"] = []
    elif failure == "endpoints":
        args["endpoints"] = args["endpoints"][:-1]
    elif failure == "units":
        args["units"] = []
    else:
        args["cancel"] = lambda: True
    with pytest.raises(FactorRepairError):
        freeze_stock_factor_repair(**args)
    assert not args["run_root"].exists()


def test_catalog_targets_cannot_be_relabelled(tmp_path):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        repair_asset_for_path,
        validate_repair_target_paths,
    )
    from orchestrator.defs.paths import gold_stk_mins_qfq_path

    target = gold_stk_mins_qfq_path(tmp_path, 1, "688689.SH", 2026)
    assert repair_asset_for_path(tmp_path, target) == "gold_stk_mins_qfq_1m"
    validate_repair_target_paths(tmp_path, "gold_stk_mins_qfq_1m", [target])
    with pytest.raises(FactorRepairError, match="mismatch"):
        validate_repair_target_paths(tmp_path, "silver_adj_factor", [target])


def test_exact_seed_uses_context_and_never_earlier_state(tmp_path):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        inspect_repair_minute_seed,
    )
    from orchestrator.defs.stk_mins_qfq_macd_kdj import (
        GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
    )
    price, state = tmp_path / "price.parquet", tmp_path / "seed.parquet"
    with duckdb.connect() as c:
        c.execute("""CREATE TABLE bars AS SELECT '688689.SH' ts_code,1::INTEGER freq,
          DATE '2026-06-26' trade_date,TIMESTAMP '2026-06-26 14:00:00'+i*INTERVAL '1 minute' trade_time
          FROM range(8) r(i)""")
        c.execute("COPY bars TO ? (FORMAT PARQUET)", [str(price)])
        c.execute("""CREATE TABLE seed AS SELECT '688689.SH' ts_code,1::INTEGER freq,
          DATE '2026-06-26' trade_date,TIMESTAMP '2026-06-26 14:07:00' last_trade_time,
          ?::VARCHAR params_key,1::INTEGER indicator_version,1.0::DOUBLE macd_ema_fast,
          1.0::DOUBLE macd_ema_slow,0.0::DOUBLE macd_dea,50.0::DOUBLE kdj_k,50.0::DOUBLE kdj_d""",
          [GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY])
        c.execute("COPY seed TO ? (FORMAT PARQUET)", [str(state)])
        args = {"ts_code": "688689.SH", "freq": 1, "first_trade_date": "2026-06-29",
                "expected_dates": ("2026-06-25", "2026-06-26", "2026-06-29"),
                "price_paths": [price], "state_path": state}
        observed = inspect_repair_minute_seed(c, **args)
        assert observed["previous_expected_date"] == "2026-06-26"
        assert len(observed["context_times"]) == 8
        c.execute("UPDATE seed SET trade_date=DATE '2026-06-25'")
        c.execute("COPY seed TO ? (FORMAT PARQUET)", [str(state)])
        with pytest.raises(FactorRepairError, match="exact_seed_invalid"):
            inspect_repair_minute_seed(c, **args)


def test_writer_guard_distinguishes_enabled_trigger_and_unrelated_job(tmp_path):
    import dagster as dg

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        inspect_repair_writers,
    )
    from orchestrator.defs.paths import silver_stock_daily_path

    related = SimpleNamespace(name="stock_writer", asset_layer=SimpleNamespace(
        selected_asset_keys={dg.AssetKey("silver_stock_daily")}))
    unrelated = SimpleNamespace(name="other_writer", asset_layer=SimpleNamespace(
        selected_asset_keys={dg.AssetKey("silver_index_daily")}))
    sensor = SimpleNamespace(name="stock_writer_sensor", targets=[SimpleNamespace(job_name="stock_writer")],
                             default_status=SimpleNamespace(value="RUNNING"))
    definitions = SimpleNamespace(resolve_all_job_defs=lambda: [related, unrelated],
                                  sensors=[sensor], schedules=[])
    instance = SimpleNamespace(all_instigator_state=list, get_runs=lambda **kwargs: [])
    args = {"input_paths": [str(silver_stock_daily_path(tmp_path, "2026-10-13"))], "lake_root": tmp_path}
    observed = inspect_repair_writers(definitions, instance, **args)
    assert not observed["idle"]
    assert observed["enabled_triggers"] == [sensor.name]
    assert "other_writer" not in observed["writer_jobs"]
    instance.all_instigator_state = lambda: [SimpleNamespace(name=sensor.name, status=SimpleNamespace(value="STOPPED"))]
    assert inspect_repair_writers(definitions, instance, **args)["idle"]


def test_cli_rejects_freeze_without_maintenance_and_inspect_write_flags():
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli import main

    scope = ["--scope", "688689.SH:2026-06-29:2026-07-07", "--as-of", "2026-10-13", "--end", "2026-10-13"]
    with pytest.raises(FactorRepairError, match="confirmation_required"):
        main(["freeze", *scope])
    with pytest.raises(FactorRepairError, match="write_options_forbidden"):
        main(["inspect", *scope, "--run-root", "/private/tmp/disallowed"])


def test_suspended_state_can_extend_beyond_last_price_bar(scope, repair_endpoints):
    from dataclasses import replace

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        validate_asset_repair_endpoints,
    )
    broader = replace(scope, as_of_trade_date="2026-10-13", repair_end_trade_date="2026-10-13")
    tails = tuple(replace(e, end_time="2026-10-13", expected_dates=e.expected_dates + ("2026-10-13",))
                  if "macd_kdj_state" in e.asset_key else e for e in repair_endpoints)
    validate_asset_repair_endpoints([broader], tails)
    invalid = tuple(replace(e, end_time="2026-10-13", expected_dates=e.expected_dates + ("2026-10-13",))
                    if e.asset_key == "gold_stk_mins_qfq_macd_kdj_1m" else e for e in tails)
    with pytest.raises(FactorRepairError, match="price_coverage"):
        validate_asset_repair_endpoints([broader], invalid)


def test_daily_seed_missing_is_not_an_initialization(tmp_path):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        inspect_repair_daily_seed,
    )
    life = silver_stock_lifecycle_path(tmp_path)
    life.parent.mkdir(parents=True)
    with duckdb.connect() as c:
        c.execute("COPY (SELECT '688689.SH' ts_code,DATE '2021-01-27' list_date) TO ? (FORMAT PARQUET)", [str(life)])
        args = {"lake_root": tmp_path, "ts_code": "688689.SH", "first_trade_date": "2021-01-27",
                "previous_actual_date": None, "expected_dates": ("2021-01-26", "2021-01-27")}
        assert inspect_repair_daily_seed(c, **args)["initialized_from_listing"]
        with pytest.raises(FactorRepairError, match="initialization_not_proven"):
            inspect_repair_daily_seed(c, **{**args, "first_trade_date": "2021-01-28"})
        with pytest.raises(FactorRepairError, match="seed_file_missing"):
            inspect_repair_daily_seed(c, **{**args, "previous_actual_date": "2021-01-26"})


def test_rehashed_incomplete_plan_cannot_bypass_structural_contract(freeze_case):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        freeze_stock_factor_repair,
        repair_hash,
        validate_repair_plan,
    )
    args, _target = freeze_case
    plan = freeze_stock_factor_repair(**args)
    del plan["endpoints"]
    plan["plan_hash"] = repair_hash({k: v for k, v in plan.items() if k != "plan_hash"})
    with pytest.raises(FactorRepairError, match="incomplete"):
        validate_repair_plan(plan, plan["plan_hash"])


def test_frozen_units_preserve_price_dates_and_previous_source(freeze_case):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        repair_units_from_inspection,
    )

    args, _ = freeze_case
    profiles = [{"asset_key": e.asset_key, "ts_code": e.ts_code, "freq": e.freq,
                 "calculation_windows": [e.expected_dates], "target_dates": [e.expected_dates[0]],
                 "observed_dates": e.expected_dates, "previous_actual_date": "2020-12-31",
                 "end_time": e.end_time, "trade_date_rows":[[d,1] for d in e.expected_dates],
                 "source_dates": ["2020-12-31",*e.expected_dates],"source_inventory_paths":[]} for e in args["endpoints"]]
    units = repair_units_from_inspection({"target_paths": args["target_paths"], "profiles": profiles},
                                       lake_root=args["lake_root"])
    daily = next(u for u in units if u["asset_key"] == "gold_stock_daily_qfq")
    assert len(daily["calculation_windows"]) == 25
    assert all(p["target_dates"] != p["observed_dates"] and p["previous_actual_date"] == "2020-12-31"
               for p in daily["calculation_windows"])


@pytest.mark.parametrize("fault",["missing_stock","duplicate_stock","missing_date","missing_file","extra_file","missing_window","basis_cut","missing_implementation","partition","future","stock_pool"])
def test_complete_r1_plan_rejects_rehashed_omissions(freeze_case,fault):
    from copy import deepcopy

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        freeze_stock_factor_repair,
        repair_hash,
        validate_repair_plan,
    )
    args,_=freeze_case
    plan=deepcopy(freeze_stock_factor_repair(**args))
    daily=next(u for u in plan["units"] if u["asset_key"]=="gold_stock_daily_qfq")
    p=daily["calculation_windows"][0]
    if fault=="missing_stock": daily["calculation_windows"].pop()
    elif fault=="duplicate_stock": daily["calculation_windows"][-1]=deepcopy(p)
    elif fault=="missing_date": p["observed_dates"].pop()
    elif fault=="missing_file": daily["target_paths"].pop()
    elif fault=="extra_file": daily["target_paths"].append(str(args["lake_root"]/'gold/extra.parquet'))
    elif fault=="missing_window": p["windows"].pop()
    elif fault=="basis_cut":
        p=next(p for p in daily["calculation_windows"] if p["ts_code"]=="688689.SH")
        p["observed_dates"]=p["observed_dates"][1:];p["target_dates"]=p["target_dates"][1:]
    elif fault=="missing_implementation": plan["implementation_fingerprints"].pop()
    elif fault=="partition": plan["partition_validation"]["registered_keys"].pop()
    elif fault=="future": plan["partition_validation"]["checked_on"]="2020-01-01"
    else: daily["stock_codes"].pop()
    plan["plan_hash"]=repair_hash({k:v for k,v in plan.items() if k!="plan_hash"})
    with pytest.raises(FactorRepairError): validate_repair_plan(plan,plan["plan_hash"])


def test_independent_silver_predecessor_does_not_depend_on_gold(tmp_path):
    from orchestrator.defs import paths
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli import (
        inspect_repair_daily_source_dates,
    )
    for d in ("2026-06-25","2026-06-26","2026-06-29"):
        p=paths.silver_stock_daily_path(tmp_path,d);p.parent.mkdir(parents=True,exist_ok=True)
        with duckdb.connect() as c:
            c.execute(f"COPY (SELECT '688689.SH'::VARCHAR ts_code,DATE '{d}' trade_date) TO ? (FORMAT PARQUET)",[str(p)])
    with duckdb.connect() as c:
        dates,inventory,stats=inspect_repair_daily_source_dates(c,tmp_path,["688689.SH"],"2026-06-29")
    assert dates["688689.SH"]==("2026-06-25","2026-06-26","2026-06-29")
    assert max(d for d in dates["688689.SH"] if d<"2026-06-29")=="2026-06-26"
    assert len(inventory)==len(stats)==3
    assert not paths.gold_stock_daily_qfq_path(tmp_path,"2026-06-26").exists()


def test_unowned_candidate_is_not_removed(candidate_context):
    c,lake,run,target=candidate_context
    output=run/'candidates'/target.relative_to(lake)
    output.parent.mkdir(parents=True);output.write_bytes(b'unknown owner')
    with pytest.raises(FactorRepairError,match='unowned_candidate'): candidate(c,lake,run,target)
    assert output.read_bytes()==b'unknown owner'


def test_plan_size_admission_and_hash_are_shared_before_freeze(freeze_case,monkeypatch):
    import hashlib
    import json

    from orchestrator.defs.bootstrap import stock_adj_factor_history_repair as module
    value={'z':[1,2],'a':{'x':'中文'}}
    assert module.repair_hash(value)==hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    args,_=freeze_case
    monkeypatch.setattr(module,'REPAIR_PLAN_MAX_BYTES',1024)
    with pytest.raises(FactorRepairError,match='plan_size_exceeded'): module.freeze_stock_factor_repair(**args)
    assert not args['run_root'].exists()


def test_explicit_no_price_impact_is_not_an_omitted_profile(freeze_case):
    from dataclasses import replace

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        freeze_stock_factor_repair,
    )
    args,_=freeze_case
    unit=next(u for u in args['units'] if u['asset_key']=='gold_stk_mins_qfq_1m')
    profile=next(p for p in unit['calculation_windows'] if p['ts_code']=='600016.SH')
    profile.update(observed_dates=['2026-10-12'],target_dates=[],windows=[['2026-10-12']],trade_date_rows=[['2026-10-12',1]])
    for index,endpoint in enumerate(args['endpoints']):
        if endpoint.asset_key==unit['asset_key'] and endpoint.ts_code=='600016.SH':
            args['endpoints'][index]=replace(endpoint,calculation_start_date='2026-10-12',expected_dates=('2026-10-12',),calculation_rows=1)
    unit['target_paths']=[p for p in unit['target_paths'] if '/ts_code=600016.SH/' not in p]
    args['target_paths']=sorted({p for u in args['units'] for p in u['target_paths']})
    plan=freeze_stock_factor_repair(**args)
    frozen=next(u for u in plan['units'] if u['asset_key']==unit['asset_key'])
    assert len(frozen['calculation_windows'])==25
    assert next(p for p in frozen['calculation_windows'] if p['ts_code']=='600016.SH')['target_dates']==[]
