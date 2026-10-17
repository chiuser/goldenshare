"""Isolated whole-file candidates with literal price expectations and frozen inputs."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    RepairBudget,
    file_identity,
    freeze_stock_factor_repair,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    build_repair_target_candidate,
    read_repair_candidate_record,
    repair_record_path,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.stk_mins_qfq import build_canonical_gold_stk_mins_qfq_select_sql

from . import test_stock_adj_factor_history_repair as contracts

freeze_case = contracts.freeze_case
repair_endpoints = contracts.repair_endpoints
scope = contracts.scope


@pytest.fixture
def price_plan(freeze_case, request):
    """Complete 25-stock price plan; only literal 688689/001331 sample rows start stale."""
    from dataclasses import replace
    from datetime import date

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        repair_price_dates,
    )
    args,_ = freeze_case
    root = args["lake_root"]
    codes = [s.ts_code for s in args["scopes"]]
    market_codes = [*codes,"000001.SZ"]
    day,previous,anchor,tail = "2026-06-29","2026-06-26","2026-10-16","2026-10-16"
    source_days = sorted({r["trade_date"] for r in args["source_rows"]})
    daily_days = sorted({"2021-01-27",day,tail,*[s.factor_ranges[0][0] for s in args["scopes"]]})
    minute_days = sorted({day,tail,*[s.factor_ranges[0][0] for s in args["scopes"]]})
    prior_days = []
    for d in daily_days:
        before = date.fromisoformat(d)-timedelta(days=1)
        while before.weekday() >= 5:
            before -= timedelta(days=1)
        prior_days.append(before.isoformat())
    source_dates = sorted(set(daily_days)|{previous}|set(prior_days))
    source_inventory = [str(paths.silver_stock_daily_path(root,d)) for d in source_dates]
    inputs = {Path(p) for p in args["target_paths"]}
    old_factor = 1.5 if getattr(request,"param",False) else 1.0
    count_by_freq = {1:241,5:48,15:16,30:8,60:4,90:3,120:2}
    with duckdb.connect(config={"threads":2,"memory_limit":"512MiB","max_temp_directory_size":"0B"}) as c:
        c.execute("CREATE TABLE stocks AS SELECT unnest(?::VARCHAR[]) ts_code",[market_codes])
        c.execute("CREATE TABLE factor AS SELECT ts_code,'20260629'::VARCHAR trade_date,CASE WHEN ts_code='600016.SH' THEN 123.456789 ELSE ? END::DOUBLE adj_factor FROM stocks",[old_factor])
        factor_units = {u["asset_key"]:u for u in args["units"] if "adj_factor" in u["asset_key"]}
        for u in factor_units.values(): u["target_paths"] = []
        for compact in source_days:
            d=f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
            for asset,helper,raw in (("raw_tushare_adj_factor",paths.raw_adj_factor_path,True),("silver_adj_factor",paths.silver_adj_factor_path,False)):
                p=helper(root,d);p.parent.mkdir(parents=True,exist_ok=True)
                q=f"SELECT ts_code,'{compact}'::VARCHAR trade_date,adj_factor FROM factor" if raw else f"SELECT ts_code,DATE '{d}' trade_date,adj_factor FROM factor"
                c.execute(copy_query_to_parquet(q,p));inputs.add(p);factor_units[asset]["target_paths"].append(str(p))
        for d in sorted(set(source_dates)|{anchor}):
            p=paths.silver_adj_factor_path(root,d);p.parent.mkdir(parents=True,exist_ok=True)
            if d==anchor or not p.exists():
                q=f"SELECT ts_code,DATE '{d}' trade_date,2.0::DOUBLE adj_factor FROM stocks" if d==anchor else f"SELECT ts_code,DATE '{d}' trade_date,adj_factor FROM factor"
                c.execute(copy_query_to_parquet(q,p))
            inputs.add(p)
        life=paths.silver_stock_lifecycle_path(root);life.parent.mkdir(parents=True,exist_ok=True)
        c.execute(copy_query_to_parquet("SELECT ts_code,DATE '2020-01-01' list_date,NULL::DATE delist_date,true is_cny_stock,'L'::VARCHAR list_status FROM stocks",life));inputs.add(life)
        for d in source_dates:
            p=paths.silver_stock_daily_path(root,d);p.parent.mkdir(parents=True,exist_ok=True)
            c.execute(copy_query_to_parquet(f"SELECT ts_code,DATE '{d}' trade_date,10.0::DOUBLE open,11.0::DOUBLE high,9.0::DOUBLE low,10.0::DOUBLE AS close,100.0::DOUBLE vol,1000.0::DOUBLE amount FROM stocks",p));inputs.add(p)
        c.execute("CREATE TABLE desired(ts_code VARCHAR,trade_date VARCHAR,adj_factor DOUBLE)")
        c.execute("INSERT INTO desired SELECT unnest(?::VARCHAR[]),unnest(?::VARCHAR[]),1.5",[[r["ts_code"] for r in args["source_rows"]],[r["trade_date"] for r in args["source_rows"]]])
        for d in daily_days:
            prev=source_dates[source_dates.index(d)-1] if source_dates.index(d)>0 else None
            prev_compact=(prev or "").replace("-","")
            q=f"""WITH f AS (SELECT o.ts_code,coalesce(n.adj_factor,o.adj_factor)/2 AS current_ratio,
                 coalesce(p.adj_factor,o.adj_factor)/2 AS previous_ratio FROM factor o
                 LEFT JOIN desired n ON n.ts_code=o.ts_code AND n.trade_date='{d.replace('-','')}'
                 LEFT JOIN desired p ON p.ts_code=o.ts_code AND p.trade_date='{prev_compact}')
              SELECT ts_code,DATE '{d}' trade_date,10*current_ratio AS open,11*current_ratio AS high,
                 9*current_ratio AS low,10*current_ratio AS close,10*previous_ratio AS pre_close,
                 10*current_ratio-10*previous_ratio AS change_amount,
                 (10*current_ratio-10*previous_ratio)/(10*previous_ratio)*100 AS pct_chg,100.0::DOUBLE vol,1000.0::DOUBLE amount FROM f"""
            # Initial fixture values may be generated; every asserted repaired sample stays literal.
            c.execute("CREATE OR REPLACE TABLE daily_rows AS "+q)
            if d==day:
                c.execute("UPDATE daily_rows SET open=5,high=5.5,low=4.5,close=5,pre_close=5,change_amount=0,pct_chg=0 WHERE ts_code IN ('688689.SH','001331.SZ')")
            p=paths.gold_stock_daily_qfq_path(root,d);p.parent.mkdir(parents=True,exist_ok=True)
            c.execute(copy_query_to_parquet("SELECT * FROM daily_rows",p));inputs.add(p)
        templates={}
        for source_freq in (1,5,30,60):
            times=[]
            if source_freq==1:
                for begin,end in (("09:30","11:30"),("13:01","15:00")):
                    now=datetime.fromisoformat(day+' '+begin)
                    while now<=datetime.fromisoformat(day+' '+end): times.append(now);now+=timedelta(minutes=1)
            else:
                times=[datetime.fromisoformat(day+' 09:30')]
                for begin,end in (("09:30","11:30"),("13:00","15:00")):
                    now=datetime.fromisoformat(day+' '+begin)+timedelta(minutes=source_freq)
                    while now<=datetime.fromisoformat(day+' '+end): times.append(now);now+=timedelta(minutes=source_freq)
            templates[source_freq]=times
            for d in minute_days:
                p=paths.silver_stk_mins_path(root,source_freq,d);p.parent.mkdir(parents=True,exist_ok=True)
                stamps=[datetime.combine(date.fromisoformat(d),t.time()) for t in times]
                c.execute("CREATE OR REPLACE TABLE minute_input AS SELECT ts_code,?::INTEGER freq,?::DATE trade_date,t.trade_time,10.0::DOUBLE open,11.0::DOUBLE high,9.0::DOUBLE low,10.0::DOUBLE AS close,100.0::DOUBLE vol,1000.0::DOUBLE amount,CASE WHEN ts_code LIKE '%.SH' THEN 'SSE' ELSE 'SZSE' END::VARCHAR exchange FROM stocks CROSS JOIN (SELECT unnest(?::TIMESTAMP[]) trade_time) t",[source_freq,d,stamps])
                c.execute(copy_query_to_parquet("SELECT * FROM minute_input",p));inputs.add(p)
        for freq in count_by_freq:
            frames=[]
            for d in minute_days:
                sql=build_canonical_gold_stk_mins_qfq_select_sql(
                    silver_paths=[paths.silver_stk_mins_path(root,{1:1,5:1,15:5,30:5,60:30,90:30,120:60}[freq],d)],
                    trade_adj_factor_paths=[paths.silver_adj_factor_path(root,d)],as_of_adj_factor_paths=[paths.silver_adj_factor_path(root,anchor)],target_freq=freq,partition_keys=[d])
                c.execute("CREATE OR REPLACE TEMP TABLE initial_bars AS "+sql)
                # All nonsample bars already match the corrected values; only Jun29/688689 is stale.
                c.execute(f"CREATE OR REPLACE TEMP TABLE desired_bars AS SELECT b.* REPLACE(CASE WHEN n.adj_factor IS NOT NULL AND NOT (b.ts_code='688689.SH' AND b.trade_date=DATE '{day}') THEN b.open*n.adj_factor/o.adj_factor ELSE b.open END AS open,CASE WHEN n.adj_factor IS NOT NULL AND NOT (b.ts_code='688689.SH' AND b.trade_date=DATE '{day}') THEN b.high*n.adj_factor/o.adj_factor ELSE b.high END AS high,CASE WHEN n.adj_factor IS NOT NULL AND NOT (b.ts_code='688689.SH' AND b.trade_date=DATE '{day}') THEN b.low*n.adj_factor/o.adj_factor ELSE b.low END AS low,CASE WHEN n.adj_factor IS NOT NULL AND NOT (b.ts_code='688689.SH' AND b.trade_date=DATE '{day}') THEN b.close*n.adj_factor/o.adj_factor ELSE b.close END AS close) FROM initial_bars b JOIN factor o USING(ts_code) LEFT JOIN desired n ON n.ts_code=b.ts_code AND n.trade_date=strftime(b.trade_date,'%Y%m%d')")
                frames.append("SELECT * FROM desired_bars")
                if d==minute_days[0]: c.execute("CREATE OR REPLACE TABLE all_bars AS SELECT * FROM desired_bars")
                else: c.execute("INSERT INTO all_bars SELECT * FROM desired_bars")
            # A retained auction row is outside 688689's approved minute price dates.
            if previous not in minute_days:
                c.execute(f"INSERT INTO all_bars SELECT * REPLACE(DATE '{previous}' AS trade_date,TIMESTAMP '{previous} 09:30:00' AS trade_time) FROM all_bars WHERE ts_code='688689.SH' AND trade_date=DATE '{day}' ORDER BY trade_time LIMIT 1")
            years=sorted({d[:4] for d in minute_days})
            for code in market_codes:
                for year in years:
                    p=paths.gold_stk_mins_qfq_path(root,freq,code,year);p.parent.mkdir(parents=True,exist_ok=True)
                    c.execute(copy_query_to_parquet(f"SELECT * FROM all_bars WHERE ts_code='{code}' AND strftime(trade_date,'%Y')='{year}'",p));inputs.add(p)
        for unit in args["units"]:
            asset=unit["asset_key"]
            daily=asset=='gold_stock_daily_qfq'
            minute=asset.startswith('gold_stk_mins_qfq_') and 'macd' not in asset and 'nineturn' not in asset
            if not daily and not minute: continue
            unit["calculation_windows"]=[];unit["target_paths"]=[]
            freq=None if daily else int(asset.rsplit('_',1)[1][:-1])
            for scope in args["scopes"]:
                first=scope.daily_basis_start_trade_date if daily and scope.daily_basis_start_trade_date else scope.factor_ranges[0][0]
                observed=[d for d in (daily_days if daily else minute_days) if d>=first]
                end=tail if daily else tail+' 15:00:00'
                profile={"ts_code":scope.ts_code,"freq":freq,"windows":[[d for d in observed if d[:4]==y] for y in sorted({d[:4] for d in observed})],"observed_dates":observed,"end_time":end,"previous_actual_date":None,"trade_date_rows":[[d,1 if daily else count_by_freq[freq]] for d in observed]}
                if daily:
                    profile.update(source_dates=source_dates,source_inventory_paths=source_inventory,previous_actual_date=max((d for d in source_dates if d<first),default=None))
                profile["target_dates"]=list(repair_price_dates({"source_rows":args["source_rows"],"scopes":[s.__dict__ for s in args["scopes"]]},profile,daily=daily))
                unit["calculation_windows"].append(profile)
                index=next(i for i,e in enumerate(args["endpoints"]) if e.asset_key==asset and e.ts_code==scope.ts_code)
                args["endpoints"][index]=replace(args["endpoints"][index],calculation_start_date=first,end_time=end,expected_dates=tuple(observed),calculation_rows=sum(n for d,n in profile["trade_date_rows"]))
                unit["target_paths"].extend(str(paths.gold_stock_daily_qfq_path(root,d) if daily else paths.gold_stk_mins_qfq_path(root,freq,scope.ts_code,d[:4])) for d in profile["target_dates"])
            unit["target_paths"]=sorted(set(unit["target_paths"]))
            unit["validation_paths"]=[] if daily else sorted(str(paths.gold_stk_mins_qfq_path(root,freq,code,y)) for code in market_codes for y in sorted({d[:4] for d in minute_days}))
    args["target_paths"]=sorted({p for u in args["units"] for p in u["target_paths"]})
    inputs.update(Path(p) for p in args["target_paths"])
    args["input_stats"]=[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(inputs)]
    contracts.complete_indicator_contract(args)
    return freeze_stock_factor_repair(**args)


def unit_for(plan, asset):
    return next(u for u in plan["units"] if u["asset_key"]==asset)


def build_factor_day(c, plan, day="2026-06-29"):
    for current in ([day,"2026-07-06"] if day=="2026-06-29" else [day]):
        for asset,helper in (("raw_tushare_adj_factor",paths.raw_adj_factor_path),("silver_adj_factor",paths.silver_adj_factor_path)):
            build_repair_target_candidate(c,plan,unit_for(plan,asset),helper(Path(plan["lake_root"]),current))


@pytest.fixture
def candidate_connection(price_plan,tmp_path):
    with connect_configured_duckdb(RepairBudget().connection_settings(tmp_path),temp_policy="existing_no_spill") as c:
        yield c


def test_factor_daily_candidates_preserve_other_stocks_and_are_audited(price_plan,candidate_connection):
    c,plan=candidate_connection,price_plan
    root=Path(plan["lake_root"])
    before=file_identity(paths.gold_stock_daily_qfq_path(root,"2026-06-29"))
    build_factor_day(c,plan)
    build_factor_day(c,plan,"2026-06-26")
    target=paths.gold_stock_daily_qfq_path(root,"2026-06-29")
    record=build_repair_target_candidate(c,plan,unit_for(plan,"gold_stock_daily_qfq"),target)
    output=Path(plan["run_root"])/record["candidate_relative_path"]
    value=c.execute("SELECT open,high,low,close,pre_close,change_amount,pct_chg,vol,amount FROM read_parquet(?,hive_partitioning=false) WHERE ts_code='688689.SH'",[str(output)]).fetchone()
    assert value==pytest.approx((7.5,8.25,6.75,7.5,5.0,2.5,50.0,100,1000))
    assert file_identity(target)==before
    assert record["changed_stock_rows"]==2
    assert c.execute("SELECT open,pre_close,change_amount FROM read_parquet(?,hive_partitioning=false) WHERE ts_code='001331.SZ'",[str(output)]).fetchone()==(7.5,7.5,0.0)
    assert build_repair_target_candidate(c,plan,unit_for(plan,"gold_stock_daily_qfq"),target,audit=True)==record
    modified=file_identity(output)
    assert build_repair_target_candidate(c,plan,unit_for(plan,"gold_stock_daily_qfq"),target)==record
    assert file_identity(output)==modified


@pytest.mark.parametrize("freq,count,first",[(1,241,"09:30:00"),(5,48,"09:35:00"),(15,16,"09:45:00"),(30,8,"10:00:00"),(60,4,"10:30:00"),(90,3,"11:00:00"),(120,2,"11:30:00")])
def test_seven_frequency_literals_and_quantities(price_plan,candidate_connection,freq,count,first):
    c,plan=candidate_connection,price_plan
    build_factor_day(c,plan)
    target=paths.gold_stk_mins_qfq_path(Path(plan["lake_root"]),freq,"688689.SH","2026")
    record=build_repair_target_candidate(c,plan,unit_for(plan,f"gold_stk_mins_qfq_{freq}m"),target)
    output=Path(plan["run_root"])/record["candidate_relative_path"]
    actual=c.execute("SELECT count(*),min(strftime(trade_time,'%H:%M:%S')),min(open),max(close) FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=DATE '2026-06-29'",[str(output)]).fetchone()
    assert actual==(count,first,7.5,7.5)
    assert c.execute("SELECT count(*) FROM (SELECT ts_code,trade_time,vol,amount FROM read_parquet(?,hive_partitioning=false) EXCEPT ALL SELECT ts_code,trade_time,vol,amount FROM read_parquet(?,hive_partitioning=false))",[str(output),str(target)]).fetchone()[0]==0
    assert c.execute("SELECT count(*) FROM (SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=DATE '2026-06-26' EXCEPT ALL SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=DATE '2026-06-26')",[str(output),str(target)]).fetchone()[0]==0
    assert build_repair_target_candidate(c,plan,unit_for(plan,f"gold_stk_mins_qfq_{freq}m"),target,audit=True)==record


def test_record_tamper_and_original_drift_rejected(price_plan,candidate_connection):
    c,plan=candidate_connection,price_plan
    build_factor_day(c,plan)
    target=paths.raw_adj_factor_path(Path(plan["lake_root"]),"2026-06-29")
    proof=repair_record_path(Path(plan["run_root"]),target,Path(plan["lake_root"]))
    record=json.loads(proof.read_text());record["changed_stock_rows"]+=1;proof.write_text(json.dumps(record))
    with pytest.raises(FactorRepairError,match="record_invalid"):
        read_repair_candidate_record(plan,target)


def test_factor_overlay_is_required_and_scope_cannot_expand(price_plan,candidate_connection):
    c,plan=candidate_connection,price_plan
    target=paths.silver_adj_factor_path(Path(plan["lake_root"]),"2026-06-29")
    with pytest.raises(FactorRepairError,match="candidate_required"):
        build_repair_target_candidate(c,plan,unit_for(plan,"silver_adj_factor"),target)
    unit=unit_for(plan,"gold_stk_mins_qfq_1m")
    unit["calculation_windows"][0]["target_dates"].append("2026-10-13")
    with pytest.raises(FactorRepairError,match="dates_not_approved"):
        build_repair_target_candidate(c,plan,unit,paths.gold_stk_mins_qfq_path(Path(plan["lake_root"]),1,"688689.SH","2026"))


def test_cancellation_and_partial_record_rebuild(price_plan,candidate_connection):
    c,plan=candidate_connection,price_plan
    target=paths.raw_adj_factor_path(Path(plan["lake_root"]),"2026-06-29")
    unit=unit_for(plan,"raw_tushare_adj_factor")
    with pytest.raises(FactorRepairError,match="canceled"):
        build_repair_target_candidate(c,plan,unit,target,cancel=lambda:True)
    record=build_repair_target_candidate(c,plan,unit,target)
    path=repair_record_path(Path(plan["run_root"]),target,Path(plan["lake_root"]))
    incomplete=json.loads(path.read_text());incomplete.pop("record_hash");incomplete["validated"]=False;path.write_text(json.dumps(incomplete))
    restored=build_repair_target_candidate(c,plan,unit,target)
    assert restored["candidate_sha256"]==record["candidate_sha256"]
    assert read_repair_candidate_record(plan,target)==restored


@pytest.mark.parametrize("price_plan",[True],indirect=True)
def test_factor_noop_does_not_hide_stale_daily_prices(price_plan,candidate_connection):
    c,plan=candidate_connection,price_plan
    build_factor_day(c,plan)
    build_factor_day(c,plan,"2026-06-26")
    factor=paths.raw_adj_factor_path(Path(plan["lake_root"]),"2026-06-29")
    assert read_repair_candidate_record(plan,factor)["no_op"]
    assert not (Path(plan["run_root"])/"candidates"/factor.relative_to(Path(plan["lake_root"]))).exists()
    daily=paths.gold_stock_daily_qfq_path(Path(plan["lake_root"]),"2026-06-29")
    record=build_repair_target_candidate(c,plan,unit_for(plan,"gold_stock_daily_qfq"),daily)
    assert record["changed_stock_rows"]==2 and not record["no_op"]


@pytest.mark.parametrize("fault",["copy","directory_sync"])
def test_copy_and_sync_failure_never_complete_a_candidate(price_plan,candidate_connection,monkeypatch,fault):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_candidates as module,
    )
    c,plan=candidate_connection,price_plan
    target=paths.raw_adj_factor_path(Path(plan["lake_root"]),"2026-06-29")
    before=file_identity(target)
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_execution as copying,
    )
    owner=copying if fault=="copy" else module
    name="bounded_repair_copy" if fault=="copy" else "sync_repair_directory"
    original=getattr(owner,name)
    def fail(*args,**kwargs):
        if "/candidates/" in str(args[-1]):
            raise OSError("isolated write failure")
        return original(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(owner,name,fail)
        with pytest.raises(OSError,match="write failure"):
            build_repair_target_candidate(c,plan,unit_for(plan,"raw_tushare_adj_factor"),target)
    incomplete=json.loads(repair_record_path(Path(plan["run_root"]),target,Path(plan["lake_root"])).read_text())
    assert incomplete["validated"] is False and "record_hash" not in incomplete
    assert file_identity(target)==before
    assert build_repair_target_candidate(c,plan,unit_for(plan,"raw_tushare_adj_factor"),target)["validated"]


def test_missing_previous_source_cannot_initialize_mid_history(price_plan,candidate_connection,monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_candidates as module,
    )
    c,plan=candidate_connection,price_plan
    build_factor_day(c,plan);build_factor_day(c,plan,"2026-06-26")
    target=paths.gold_stock_daily_qfq_path(Path(plan["lake_root"]),"2026-06-29")
    original=module.RepairCandidateInputs.project
    changed=Path(plan["run_root"])/"missing_previous.parquet"
    source=paths.silver_stock_daily_path(Path(plan["lake_root"]),"2026-06-26")
    from orchestrator.defs.duckdb_sql import read_parquet
    c.execute(copy_query_to_parquet(f"SELECT * FROM {read_parquet(source, hive_partitioning=False)} WHERE ts_code!='688689.SH'",changed))
    def missing(self,path):
        return changed if path==source else original(self,path)
    with monkeypatch.context() as patch:
        patch.setattr(module.RepairCandidateInputs,"project",missing)
        with pytest.raises(FactorRepairError,match="daily_source_inventory_drift|previous_source_row_missing"):
            build_repair_target_candidate(c,plan,unit_for(plan,"gold_stock_daily_qfq"),target)


@pytest.mark.parametrize("fault",["quantity","missing_factor","extra_key","source_window"])
def test_price_input_failures_cannot_create_complete_candidates(price_plan,candidate_connection,monkeypatch,fault):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_candidates as module,
    )
    from orchestrator.defs.duckdb_sql import read_parquet
    c,plan=candidate_connection,price_plan
    build_factor_day(c,plan);build_factor_day(c,plan,"2026-06-26")
    root=Path(plan["lake_root"])
    source=paths.silver_stk_mins_path(root,1,"2026-06-29") if fault=="source_window" else paths.silver_adj_factor_path(root,"2026-06-26") if fault=="missing_factor" else paths.silver_stock_daily_path(root,"2026-06-29")
    projected=Path(plan["run_root"])/"isolated_invalid.parquet"
    query=f"SELECT * FROM {read_parquet(source,hive_partitioning=False)}"
    if fault=="quantity":
        query=f"SELECT * REPLACE(vol+1 AS vol) FROM ({query})"
    elif fault=="missing_factor":
        query+=" WHERE ts_code!='688689.SH'"
    elif fault=="extra_key":
        query+= " UNION ALL " + query + " WHERE ts_code='688689.SH'"
    else:
        query+=" WHERE strftime(trade_time,'%H:%M:%S')!='09:31:00'"
    c.execute(copy_query_to_parquet(query,projected))
    original=module.RepairCandidateInputs.project
    monkeypatch.setattr(module.RepairCandidateInputs,"project",lambda self,path:projected if path==source else original(self,path))
    asset="gold_stk_mins_qfq_5m" if fault=="source_window" else "gold_stock_daily_qfq"
    target=paths.gold_stk_mins_qfq_path(root,5,"688689.SH","2026") if fault=="source_window" else paths.gold_stock_daily_qfq_path(root,"2026-06-29")
    before=file_identity(target)
    with pytest.raises(FactorRepairError):
        build_repair_target_candidate(c,plan,unit_for(plan,asset),target)
    assert file_identity(target)==before
    assert not repair_record_path(Path(plan["run_root"]),target,root).exists()


@pytest.mark.parametrize("kind",["wide_daily","annual_1m"])
def test_large_retained_file_merge_budget(price_plan,freeze_case,tmp_path,kind):
    import resource
    import sys
    import time
    from uuid import uuid4

    args,_=freeze_case
    root=Path(price_plan["lake_root"])
    target=paths.gold_stock_daily_qfq_path(root,"2026-06-29") if kind=="wide_daily" else paths.gold_stk_mins_qfq_path(root,1,"688689.SH","2026")
    asset="gold_stock_daily_qfq" if kind=="wide_daily" else "gold_stk_mins_qfq_1m"
    from orchestrator.defs.duckdb_sql import read_parquet
    with connect_configured_duckdb(RepairBudget().connection_settings(tmp_path),temp_policy="existing_no_spill") as c:
        c.execute(f"CREATE TABLE existing_fixture AS SELECT * FROM {read_parquet(target,hive_partitioning=False)}")
        existing_rows=c.execute("SELECT count(*) FROM existing_fixture").fetchone()[0]
        if kind=="wide_daily":
            extra="SELECT CAST(i AS VARCHAR)||'.SZ' AS ts_code,DATE '2026-06-29' trade_date,5.0::DOUBLE open,5.5::DOUBLE high,4.5::DOUBLE low,5.0::DOUBLE AS close,5.0::DOUBLE pre_close,0.0::DOUBLE change_amount,0.0::DOUBLE pct_chg,100.0::DOUBLE vol,1000.0::DOUBLE amount FROM range(100000,104974) t(i)"
        else:
            extra="SELECT '688689.SH'::VARCHAR ts_code,1::INTEGER freq,CAST(TIMESTAMP '2026-10-20 09:30:00'+i*INTERVAL 1 MINUTE AS DATE) trade_date,TIMESTAMP '2026-10-20 09:30:00'+i*INTERVAL 1 MINUTE trade_time,5.0::DOUBLE open,5.5::DOUBLE high,4.5::DOUBLE low,5.0::DOUBLE AS close,100.0::DOUBLE vol,1000.0::DOUBLE amount,'SSE'::VARCHAR exchange FROM range(60000) t(i)"
        c.execute(copy_query_to_parquet("SELECT * FROM existing_fixture UNION ALL "+extra,target))
        args["run_root"]=args["run_root"].parent/f"run_id={uuid4()}"
        args["input_stats"]=[(p,Path(p).stat().st_size,Path(p).stat().st_mtime_ns) for p,_,_ in args["input_stats"]]
        plan=freeze_stock_factor_repair(**args)
        build_factor_day(c,plan);build_factor_day(c,plan,"2026-06-26")
        started=time.monotonic()
        record=build_repair_target_candidate(c,plan,unit_for(plan,asset),target)
        assert record["candidate_rows"]==(5000 if kind=="wide_daily" else existing_rows+60000)
        assert record["changed_stock_rows"]==(2 if kind=="wide_daily" else 241)
        assert build_repair_target_candidate(c,plan,unit_for(plan,asset),target,audit=True)==record
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss=int(rss if sys.platform=="darwin" else rss*1024)
        assert rss<RepairBudget().max_rss
        print(json.dumps({"isolated_benchmark":kind,"rows":record["candidate_rows"],
            "changed_rows":record["changed_stock_rows"],"candidate_bytes":record["candidate_bytes"],
            "elapsed_seconds":round(time.monotonic()-started,3),"peak_rss_bytes":rss}))


def refreeze_test_price_plan(plan):
    from uuid import uuid4

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        AssetRepairEndpoint,
        FactorRepairScope,
    )
    return freeze_stock_factor_repair(lake_root=Path(plan['lake_root']),
        run_root=Path(plan['run_root']).parent/f'run_id={uuid4()}',
        scopes=[FactorRepairScope(**{**s,'factor_ranges':tuple(tuple(r) for r in s['factor_ranges'])}) for s in plan['scopes']],
        source_rows=plan['source_rows'],anchors=plan['anchors'],
        endpoints=[AssetRepairEndpoint(**{**e,'expected_dates':tuple(e['expected_dates']),'context_times':tuple(e['context_times'])}) for e in plan['endpoints']],
        input_stats=[(i['path'],Path(i['path']).stat().st_size,Path(i['path']).stat().st_mtime_ns) for i in plan['source_fingerprints']],
        target_paths=[i['path'] for i in plan['target_preimages']],units=plan['units'],writer_guard=lambda:None,
        partition_validation=plan['partition_validation'])


def test_gold_gap_still_uses_latest_actual_silver_row(price_plan,candidate_connection):
    c=candidate_connection;plan=price_plan;root=Path(plan['lake_root'])
    from orchestrator.defs.duckdb_sql import read_parquet
    gold=paths.gold_stock_daily_qfq_path(root,'2026-06-26')
    silver=paths.silver_stock_daily_path(root,'2026-06-26')
    c.execute(f"CREATE TABLE before_gap AS SELECT * FROM {read_parquet(gold,hive_partitioning=False)}")
    c.execute(copy_query_to_parquet("SELECT * FROM before_gap WHERE ts_code!='688689.SH'",gold))
    c.execute(f"CREATE TABLE actual_source AS SELECT * FROM {read_parquet(silver,hive_partitioning=False)}")
    c.execute(copy_query_to_parquet("SELECT * REPLACE(CASE WHEN ts_code='688689.SH' THEN 20.0 ELSE open END AS open,CASE WHEN ts_code='688689.SH' THEN 21.0 ELSE high END AS high,CASE WHEN ts_code='688689.SH' THEN 19.0 ELSE low END AS low,CASE WHEN ts_code='688689.SH' THEN 20.0 ELSE close END AS close) FROM actual_source",silver))
    unit=unit_for(plan,'gold_stock_daily_qfq');profile=next(p for p in unit['calculation_windows'] if p['ts_code']=='688689.SH')
    profile['observed_dates'].remove('2026-06-26');profile['target_dates'].remove('2026-06-26')
    profile['trade_date_rows']=[[d,0 if d=='2026-06-26' else n] for d,n in profile['trade_date_rows']]
    endpoint=next(e for e in plan['endpoints'] if e['asset_key']==unit['asset_key'] and e['ts_code']=='688689.SH')
    endpoint['calculation_rows']-=1
    plan=refreeze_test_price_plan(plan)
    build_factor_day(c,plan);build_factor_day(c,plan,'2026-06-26')
    target=paths.gold_stock_daily_qfq_path(root,'2026-06-29')
    record=build_repair_target_candidate(c,plan,unit_for(plan,'gold_stock_daily_qfq'),target)
    out=Path(plan['run_root'])/record['candidate_relative_path']
    assert c.execute(f"SELECT close,pre_close,change_amount,pct_chg FROM {read_parquet(out,hive_partitioning=False)} WHERE ts_code='688689.SH'").fetchone()==(7.5,10.0,-2.5,-25.0)
    assert c.execute(f"SELECT count(*) FROM {read_parquet(gold,hive_partitioning=False)} WHERE ts_code='688689.SH'").fetchone()[0]==0


def test_scope_omission_is_rejected_before_build_or_replay(price_plan,candidate_connection):
    unit=unit_for(price_plan,'gold_stock_daily_qfq')
    unit['calculation_windows'].pop()
    target=paths.gold_stock_daily_qfq_path(Path(price_plan['lake_root']),'2026-06-29')
    before=file_identity(target)
    for audit in (False,True):
        with pytest.raises(FactorRepairError,match='profiles_incomplete'):
            build_repair_target_candidate(candidate_connection,price_plan,unit,target,audit=audit)
    assert file_identity(target)==before


def test_full_coverage_rejects_untargeted_exchange_without_repair(price_plan,candidate_connection):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        audit_price_repair_partition_coverage,
    )
    from orchestrator.defs.duckdb_sql import read_parquet
    c=candidate_connection;root=Path(price_plan['lake_root'])
    other=paths.gold_stk_mins_qfq_path(root,1,'000001.SZ','2026')
    c.execute(f'CREATE TABLE outside_before AS SELECT * FROM {read_parquet(other,hive_partitioning=False)}')
    c.execute(copy_query_to_parquet("SELECT * REPLACE(CASE WHEN trade_date=DATE '2026-06-29' THEN 'WRONG' ELSE exchange END AS exchange) FROM outside_before",other))
    plan=refreeze_test_price_plan(price_plan);before=file_identity(other)
    build_factor_day(c,plan)
    unit=unit_for(plan,'gold_stk_mins_qfq_1m');target=paths.gold_stk_mins_qfq_path(root,1,'688689.SH','2026')
    build_repair_target_candidate(c,plan,unit,target)
    with pytest.raises(FactorRepairError,match='source_coverage_failed'):
        audit_price_repair_partition_coverage(c,plan,unit,[target])
    assert file_identity(other)==before
    assert not repair_record_path(Path(plan['run_root']),other,root).exists()


def test_legitimate_first_source_row_keeps_zero_previous_contract(price_plan,candidate_connection):
    from orchestrator.defs.duckdb_sql import read_parquet
    c=candidate_connection;root=Path(price_plan['lake_root'])
    earliest=paths.silver_stock_daily_path(root,'2021-01-26')
    life=paths.silver_stock_lifecycle_path(root)
    c.execute(f'CREATE TABLE earliest_source AS SELECT * FROM {read_parquet(earliest,hive_partitioning=False)}')
    c.execute(copy_query_to_parquet("SELECT * FROM earliest_source WHERE ts_code!='688689.SH'",earliest))
    c.execute(f'CREATE TABLE original_life AS SELECT * FROM {read_parquet(life,hive_partitioning=False)}')
    c.execute(copy_query_to_parquet("SELECT * REPLACE(CASE WHEN ts_code='688689.SH' THEN DATE '2021-01-27' ELSE list_date END AS list_date) FROM original_life",life))
    profile=next(p for p in unit_for(price_plan,'gold_stock_daily_qfq')['calculation_windows'] if p['ts_code']=='688689.SH')
    profile['source_dates'].remove('2021-01-26');profile['previous_actual_date']=None
    plan=refreeze_test_price_plan(price_plan)
    target=paths.gold_stock_daily_qfq_path(root,'2021-01-27')
    before=file_identity(target)
    record=build_repair_target_candidate(c,plan,unit_for(plan,'gold_stock_daily_qfq'),target)
    output=Path(plan['run_root'])/record['candidate_relative_path']
    assert c.execute(f"SELECT close,pre_close,change_amount,pct_chg FROM {read_parquet(output,hive_partitioning=False)} WHERE ts_code='688689.SH'").fetchone()==(5.0,0.0,0.0,0.0)
    assert file_identity(target)==before


def test_projection_pending_copy_recovers_and_completed_copy_is_not_rewritten(price_plan,candidate_connection,monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_execution as copying,
    )
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        RepairCandidateInputs,
    )
    plan=price_plan;root=Path(plan['lake_root']);run=Path(plan['run_root'])
    source=paths.silver_stock_daily_path(root,'2026-06-29')
    original=file_identity(source)
    output=run/'inputs'/source.relative_to(root)
    copy=copying.bounded_repair_copy
    def failed_after_copy(*args,**kwargs):
        copy(*args,**kwargs);raise OSError('projection interrupted before seal')
    with monkeypatch.context() as patch:
        patch.setattr(copying,'bounded_repair_copy',failed_after_copy)
        with pytest.raises(OSError,match='projection interrupted'):
            RepairCandidateInputs(candidate_connection,plan).project(source)
    proof=json.loads(output.with_suffix('.json').read_text())
    assert proof['validated'] is False and output.with_suffix('.parquet.partial').exists()
    projected=RepairCandidateInputs(candidate_connection,plan).project(source)
    sealed=file_identity(projected)
    assert json.loads(output.with_suffix('.json').read_text())['validated'] is True
    assert RepairCandidateInputs(candidate_connection,plan).project(source)==projected
    assert file_identity(projected)==sealed and file_identity(source)==original
    assert candidate_connection.execute('SELECT count(*) FROM read_parquet(?,hive_partitioning=false)',[str(projected)]).fetchone()[0]==25


def test_projection_without_ownership_is_preserved_and_rejected(price_plan,candidate_connection):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        RepairCandidateInputs,
    )
    source=paths.silver_stock_daily_path(Path(price_plan['lake_root']),'2026-06-29')
    output=Path(price_plan['run_root'])/'inputs'/source.relative_to(Path(price_plan['lake_root']))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(b'unknown projection owner')
    with pytest.raises(FactorRepairError,match='projection_unowned'):
        RepairCandidateInputs(candidate_connection,price_plan).project(source)
    assert output.read_bytes()==b'unknown projection owner'


def test_completed_candidate_reuses_full_proof_without_business_sql(price_plan, candidate_connection):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import repair_hash
    target = paths.raw_adj_factor_path(Path(price_plan["lake_root"]), "2026-06-29")
    unit = unit_for(price_plan, "raw_tushare_adj_factor")
    built = build_repair_target_candidate(candidate_connection, price_plan, unit, target)
    class NoBusinessSQL:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("a sealed candidate must not execute SQL")
    for audit in (False, True):
        assert build_repair_target_candidate(NoBusinessSQL(), price_plan, unit, target, audit=audit) == built
    path = repair_record_path(Path(price_plan["run_root"]), target, Path(price_plan["lake_root"]))
    broken = dict(built)
    broken.pop("business_proof")
    broken["record_hash"] = repair_hash({k: v for k, v in broken.items() if k != "record_hash"})
    path.write_text(json.dumps(broken))
    with pytest.raises(FactorRepairError, match="business_proof_required"):
        build_repair_target_candidate(NoBusinessSQL(), price_plan, unit, target, audit=True)


@pytest.mark.parametrize("when", ["before", "after"])
def test_prepared_candidate_finishes_commit_without_sql_or_copy(price_plan, candidate_connection, monkeypatch, when):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_candidates as candidates,
    )
    plan = price_plan
    target = paths.raw_adj_factor_path(Path(plan["lake_root"]), "2026-06-29")
    unit = unit_for(plan, "raw_tushare_adj_factor")
    replace = candidates.replace_repair_file
    def interruption(source, output):
        if when == "after":
            replace(source, output)
        raise OSError("interrupted candidate commit")
    monkeypatch.setattr(candidates, "replace_repair_file", interruption)
    with pytest.raises(OSError, match="interrupted candidate"):
        build_repair_target_candidate(candidate_connection, plan, unit, target)
    saved = json.loads(repair_record_path(Path(plan["run_root"]), target, Path(plan["lake_root"])).read_text())
    assert saved["commit_pending"] is True and saved["transfer_hash"] and saved["business_proof"]
    with pytest.raises(FactorRepairError, match="commit_pending"):
        read_repair_candidate_record(plan, target)
    with pytest.raises(FactorRepairError, match="commit_pending"):
        build_repair_target_candidate(None, plan, unit, target, audit=True)
    output = Path(plan["run_root"]) / saved["candidate_relative_path"]
    present = output if output.exists() else output.with_suffix(output.suffix + ".partial")
    proof = file_identity(present)
    monkeypatch.setattr(candidates, "replace_repair_file", replace)
    class NoSQL:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("prepared output must not be recalculated")
    resumed = build_repair_target_candidate(NoSQL(), plan, unit, target)
    assert resumed["candidate_sha256"] == proof.sha256
    assert file_identity(output).sha256 == proof.sha256
    assert "commit_pending" not in resumed
    assert read_repair_candidate_record(plan, target) == resumed


def test_warm_input_identity_does_not_repeat_path_probes(price_plan, monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_candidates as module,
    )
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
        RepairRuntime,
        use_repair_runtime,
    )
    target = paths.raw_adj_factor_path(Path(price_plan["lake_root"]), "2026-06-29")
    runtime = RepairRuntime(price_plan)
    with use_repair_runtime(runtime):
        module.RepairCandidateInputs(None, price_plan).frozen(target)
        def forbidden(_path):
            raise AssertionError("a stable verified input must not repeat path probes")
        monkeypatch.setattr(module, "check_repair_path", forbidden)
        for _ in range(20):
            assert module.RepairCandidateInputs(None, price_plan).frozen(target) == target
    assert runtime.counters["hash_files"] == 1


def test_daily_anchor_and_source_dates_are_checked_once_per_stock(price_plan, candidate_connection):
    from collections import Counter

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
        RepairRuntime,
        use_repair_runtime,
    )
    plan = price_plan
    build_factor_day(candidate_connection, plan, "2023-06-01")
    observed = Counter()
    class CountQueries:
        def execute(self, query, *args, **kwargs):
            observed["anchor"] += query.startswith("SELECT adj_factor FROM")
            observed["dates"] += query.startswith("SELECT CAST(trade_date AS VARCHAR),count(*) FROM repair_daily_source_inventory")
            return candidate_connection.execute(query, *args, **kwargs)
    connection = CountQueries()
    with use_repair_runtime(RepairRuntime(plan)):
        for day in ("2021-01-27", "2023-06-01"):
            build_repair_target_candidate(connection, plan, unit_for(plan, "gold_stock_daily_qfq"),
                paths.gold_stock_daily_qfq_path(Path(plan["lake_root"]), day))
    # Jan27 uses 688689; Jun1 uses 688689 and 600016. The same 688689
    # anchor/history has no new evidence on Jun1 and must not be queried again.
    assert observed == {"anchor": 2, "dates": 2}
