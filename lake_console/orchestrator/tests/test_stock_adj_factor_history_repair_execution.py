"""Real child exit/cancel and candidate replay, using only isolated temporary roots."""

import json
import os
import sys
from pathlib import Path

import pytest

from orchestrator.defs import paths
from orchestrator.defs.bootstrap import (
    stock_adj_factor_history_repair_execution as execution,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    file_identity,
)

from . import test_stock_adj_factor_history_repair as contracts

freeze_case = contracts.freeze_case
repair_endpoints = contracts.repair_endpoints
scope = contracts.scope
from . import test_stock_adj_factor_history_repair_candidates as candidate_fixtures

price_plan = candidate_fixtures.price_plan


def launcher(plan,tmp_path):
    script=tmp_path/"isolated_worker.py"
    script.write_text("""import json,sys
def guard(event,args):
    if event=='socket.connect': raise RuntimeError('network forbidden in R1 isolated worker')
    if event=='open' and isinstance(args[0],str) and (args[0].startswith('/Volumes/') or '/.goldenshare/' in args[0]):
        raise RuntimeError('formal resource forbidden in R1 isolated worker')
sys.addaudithook(guard)
from orchestrator.defs.bootstrap import stock_adj_factor_history_repair as contract
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import run_repair_candidate_worker
request=json.loads(sys.stdin.read())
plan=json.load(open(request['plan_path']))
contract.DEFAULT_LAKE_ROOT=plan['lake_root']
contract.DEFAULT_LAKE_STAGING_ROOT=str(__import__('pathlib').Path(plan['run_root']).parents[1])
print(json.dumps(run_repair_candidate_worker(request)))
""")
    return [sys.executable,"-B",str(script)]


def raw_target(plan):
    return paths.raw_adj_factor_path(Path(plan["lake_root"]),"2026-06-29")


def test_real_child_build_audit_and_replay_are_candidate_only(price_plan,tmp_path):
    plan=price_plan
    target=raw_target(plan)
    original=file_identity(target)
    args={"plan_path": Path(plan["run_root"])/"plan.json","expected_hash": plan["plan_hash"],
        "phase": "factor","selected_targets": [str(target)],"worker_command": launcher(plan,tmp_path)}
    updates=[]
    result=execution.execute_repair_candidates(**args,progress=updates.append)
    assert result["completed"]==1 and result["sample"] and not result["all_chain_ready"]
    assert result["peak_rss_bytes"]<1024**3
    candidate=Path(plan["run_root"])/"candidates"/target.relative_to(Path(plan["lake_root"]))
    identity=file_identity(candidate)
    assert execution.execute_repair_candidates(**args,audit=True)["audited"]
    assert execution.execute_repair_candidates(**args)["completed"]==1
    assert file_identity(candidate)==identity and file_identity(target)==original
    assert all(u["completed"] in (0,1) for u in updates)
    assert not (Path(plan["run_root"])/"checkpoints/promoted").exists()


def test_checkpoint_failure_keeps_completed_candidate_and_same_plan_recovers(price_plan,tmp_path,monkeypatch):
    plan=price_plan
    args={"plan_path": Path(plan["run_root"])/"plan.json","expected_hash": plan["plan_hash"],
        "phase": "factor","selected_targets": [str(raw_target(plan))],"worker_command": launcher(plan,tmp_path)}
    write=execution.atomic_repair_json
    failed=[]
    def fault(path,payload):
        if path.name=="checkpoint.json" and not failed:
            failed.append(True);raise OSError("isolated checkpoint failure")
        write(path,payload)
    monkeypatch.setattr(execution,"atomic_repair_json",fault)
    with pytest.raises(OSError,match="checkpoint failure"):
        execution.execute_repair_candidates(**args)
    candidate=Path(plan["run_root"])/"candidates"/raw_target(plan).relative_to(Path(plan["lake_root"]))
    before=file_identity(candidate)
    assert execution.execute_repair_candidates(**args)["completed"]==1
    assert file_identity(candidate)==before


def test_child_exit_and_cancel_leave_no_live_worker(price_plan,tmp_path):
    plan=price_plan
    args={"plan_path": Path(plan["run_root"])/"plan.json","expected_hash": plan["plan_hash"],"phase": "factor","selected_targets": [str(raw_target(plan))]}
    with pytest.raises(FactorRepairError,match="worker_failed"):
        execution.execute_repair_candidates(**args,worker_command=[sys.executable,"-c","import os;os._exit(23)"])
    checks=[]
    def cancel():
        checks.append(1)
        return len(checks)>len(plan["source_fingerprints"])+4
    script=tmp_path/"wait_worker.py";pid_file=tmp_path/"worker.pid"
    script.write_text(f"import os,time\nopen({str(pid_file)!r},'w').write(str(os.getpid()))\ntime.sleep(30)\n")
    with pytest.raises(FactorRepairError,match="canceled"):
        execution.execute_repair_candidates(**args,worker_command=[sys.executable,str(script)],cancel=cancel)
    if pid_file.exists():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()),0)
    checkpoint=json.loads((Path(plan["run_root"])/"checkpoint.json").read_text())
    assert checkpoint["status"]=="CANCELLED" and checkpoint["completed"]==0


def test_phase_hash_scope_and_source_drift_are_rejected(price_plan):
    plan=price_plan;path=Path(plan["run_root"])/"plan.json"
    with pytest.raises(FactorRepairError,match="plan_invalid"):
        execution.execute_repair_candidates(path,"bad",phase="factor")
    with pytest.raises(FactorRepairError,match="phase_not_supported"):
        execution.execute_repair_candidates(path,plan["plan_hash"],phase="promote")
    with pytest.raises(FactorRepairError,match="sample_not_frozen"):
        execution.execute_repair_candidates(path,plan["plan_hash"],phase="factor",selected_targets=["/outside.parquet"])
    raw_target(plan).write_bytes(b"external change")
    with pytest.raises(FactorRepairError,match="input_drift"):
        execution.execute_repair_candidates(path,plan["plan_hash"],phase="factor")


def test_resource_rejection_stops_child_and_has_no_formal_output(price_plan,tmp_path,monkeypatch):
    plan=price_plan
    monkeypatch.setattr(execution,"_rss",lambda _pid:3*1024**3)
    target=raw_target(plan);before=file_identity(target)
    with pytest.raises(FactorRepairError,match="rss_budget_exceeded"):
        execution.execute_repair_candidates(Path(plan["run_root"])/"plan.json",plan["plan_hash"],phase="factor",
            selected_targets=[str(target)],worker_command=[sys.executable,"-c","import time;time.sleep(30)"])
    assert file_identity(target)==before


def test_batches_are_bounded_and_do_not_cross_assets_or_years():
    work=[(1,f"/lake/gold/ts_code={code:06}/year=2025/part-000.parquet") for code in range(100)]
    work += [(1,"/lake/gold/ts_code=688689/year=2026/part-000.parquet"),(2,"/lake/gold/trade_date=2026-01-02/part-000.parquet")]
    batches=execution.repair_candidate_batches(work)
    assert [len(targets) for _,targets in batches]==[64,36,1,1]
    assert sum(len(targets) for _,targets in batches)==len(work)


def test_storage_budget_is_checked_before_any_worker(price_plan,monkeypatch):
    plan=price_plan;target=raw_target(plan);before=file_identity(target)
    monkeypatch.setattr(execution,"repair_storage_bytes",lambda _root:(10*1024**3+1,0))
    with pytest.raises(FactorRepairError,match="storage_budget_exceeded"):
        execution.execute_repair_candidates(Path(plan["run_root"])/"plan.json",plan["plan_hash"],phase="factor",selected_targets=[str(target)])
    assert file_identity(target)==before


def test_excess_worker_output_is_bounded_and_terminated(price_plan):
    plan=price_plan;target=raw_target(plan);before=file_identity(target)
    with pytest.raises(FactorRepairError,match="worker_output_exceeded"):
        execution.execute_repair_candidates(Path(plan["run_root"])/"plan.json",plan["plan_hash"],phase="factor",
            selected_targets=[str(target)],worker_command=[sys.executable,"-c","import sys,time;sys.stdout.write('x'*20000);sys.stdout.flush();time.sleep(30)"])
    assert file_identity(target)==before


def test_manual_cli_requires_explicit_selection_and_never_accepts_other_phases():
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli import main
    for args in (["build","--plan","/not-read","--expected-plan-hash","bad","--phase","price"],
                 ["audit","--plan","/not-read","--expected-plan-hash","bad","--phase","promote","--full"]):
        with pytest.raises(SystemExit):
            main(args)


def test_real_price_batch_consumes_sealed_factor_candidates(price_plan,tmp_path):
    plan=price_plan;root=Path(plan["lake_root"])
    args={"plan_path":Path(plan["run_root"])/"plan.json","expected_hash":plan["plan_hash"],
          "worker_command":launcher(plan,tmp_path)}
    factors=[str(helper(root,day)) for helper in (paths.raw_adj_factor_path,paths.silver_adj_factor_path)
             for day in ("2026-06-26","2026-06-29","2026-07-06")]
    execution.execute_repair_candidates(**args,phase="factor",selected_targets=factors)
    targets=[str(paths.gold_stock_daily_qfq_path(root,"2026-06-29")),
             str(paths.gold_stk_mins_qfq_path(root,1,"688689.SH","2026"))]
    before=[file_identity(Path(p)) for p in targets]
    result=execution.execute_repair_candidates(**args,phase="price",selected_targets=targets)
    assert result["completed"]==2 and result["changed_rows"]==243 and not result["all_chain_ready"]
    assert execution.execute_repair_candidates(**args,phase="price",selected_targets=targets,audit=True)["audited"]
    assert [file_identity(Path(p)) for p in targets]==before


def test_hash_progress_is_time_bounded_before_any_worker(price_plan,monkeypatch):
    clock=[0.0];updates=[]
    original=execution.file_identity
    def hashing(path,*,cancel=None,progress=None):
        if progress:
            clock[0]+=31
            progress(max(1,path.stat().st_size//2),path.stat().st_size)
        return original(path,cancel=cancel)
    monkeypatch.setattr(execution.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(execution,'file_identity',hashing)
    def canceled(): return any(u.get('hashed_current_bytes',0)>0 for u in updates)
    with pytest.raises(FactorRepairError,match='canceled'):
        execution.execute_repair_candidates(Path(price_plan['run_root'])/'plan.json',price_plan['plan_hash'],phase='factor',selected_targets=[str(raw_target(price_plan))],cancel=canceled,progress=updates.append)
    partial=next(u for u in updates if u.get('hashed_current_bytes',0)>0)
    assert partial['verified_inputs']==partial['completed']==partial['verified_bytes']==0
    assert partial['total_input_bytes']>0 and partial['updated_at']>0
    assert not (Path(price_plan['run_root'])/'candidates').exists()


def test_space_accounts_for_frozen_remaining_work_and_unsealed_files(tmp_path,monkeypatch):
    from types import SimpleNamespace
    (tmp_path/'candidates').mkdir();(tmp_path/'temp').mkdir();(tmp_path/'inputs').mkdir()
    (tmp_path/'candidates/complete.parquet').write_bytes(b'12')
    (tmp_path/'candidates/work.parquet.partial').write_bytes(b'345')
    (tmp_path/'temp/leftover').write_bytes(b'678')
    (tmp_path/'inputs/projection.parquet').write_bytes(b'910')
    assert execution.repair_storage_totals(tmp_path)=={'candidate_bytes':5,'spill_bytes':3,'input_bytes':3,'staging_bytes':11}
    import shutil
    monkeypatch.setattr(shutil,'disk_usage',lambda root:SimpleNamespace(free=2700*1024**2))
    with pytest.raises(FactorRepairError,match='space_insufficient'):
        execution.check_repair_storage(tmp_path,plan={'space_required_bytes':3*1024**3})


def test_child_exit_after_partial_copy_recovers_without_rewriting_completed(price_plan,tmp_path):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
        repair_record_path,
    )
    plan=price_plan;root=Path(plan['lake_root']);run=Path(plan['run_root'])
    targets=[paths.raw_adj_factor_path(root,d) for d in ('2026-06-26','2026-06-29')]
    command=launcher(plan,tmp_path);script=Path(command[-1]);source=script.read_text()
    insertion="""from orchestrator.defs.bootstrap import stock_adj_factor_history_repair_execution as ex
import os
copy=ex.bounded_repair_copy
counter=0
def crash_after_copy(*args,**kwargs):
    global counter
    copy(*args,**kwargs)
    if kwargs.get('candidate'):
        counter+=1
        if counter==2: os._exit(23)
ex.bounded_repair_copy=crash_after_copy
"""
    source=source.replace('print(json.dumps(run_repair_candidate_worker(request)))',insertion+'print(json.dumps(run_repair_candidate_worker(request)))')
    script.write_text(source)
    args={'plan_path':run/'plan.json','expected_hash':plan['plan_hash'],'phase':'factor','selected_targets':[str(p) for p in targets]}
    originals=[file_identity(p) for p in targets]
    with pytest.raises(FactorRepairError,match='worker_failed'):
        execution.execute_repair_candidates(**args,worker_command=command)
    first=run/'candidates'/targets[0].relative_to(root)
    completed=file_identity(first)
    unfinished=json.loads(repair_record_path(run,targets[1],root).read_text())
    assert unfinished['validated'] is False and 'record_hash' not in unfinished
    normal=launcher(plan,tmp_path)
    result=execution.execute_repair_candidates(**args,worker_command=normal)
    assert result['completed']==2 and not result['all_chain_ready']
    assert file_identity(first)==completed
    assert [file_identity(p) for p in targets]==originals
    assert not list((run/'candidates').rglob('*.partial'))


def test_real_file_size_limit_prevents_candidate_quota_overshoot(tmp_path):
    import subprocess
    script=tmp_path/'quota_worker.py'
    script.write_text("""import json,resource,sys
from pathlib import Path
import duckdb
from orchestrator.defs.bootstrap import stock_adj_factor_history_repair_execution as ex
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import RepairBudget,FactorRepairError
root=Path(sys.argv[1]);output=root/'candidates/limited.parquet.partial'
output.parent.mkdir(exist_ok=True)
ex.repair_storage_bytes=lambda root:(RepairBudget().max_candidate_bytes-1024,0)
before=resource.getrlimit(resource.RLIMIT_FSIZE)
try:
    with duckdb.connect(config={'threads':2,'memory_limit':'512MiB','max_temp_directory_size':'0B'}) as c:
        ex.bounded_repair_copy(c,'SELECT i, md5(i::VARCHAR) value FROM range(100000) t(i)',root,output,candidate=True,reserve_bytes=1)
except (FactorRepairError,duckdb.Error):
    print(json.dumps({'rejected':True,'bytes':output.stat().st_size if output.exists() else 0,'limit_restored':resource.getrlimit(resource.RLIMIT_FSIZE)==before}))
else: raise AssertionError('COPY unexpectedly passed quota')
""")
    result=subprocess.run([sys.executable,'-B',str(script),str(tmp_path)],capture_output=True,text=True,check=True)
    proof=json.loads(result.stdout)
    assert proof['rejected'] and proof['bytes']<=1024 and proof['limit_restored']


def test_implementation_dependency_drift_rejected_without_replacing_source(price_plan,monkeypatch):
    from dataclasses import replace
    original=execution.file_identity
    def drift(path,**kwargs):
        identity=original(path,**kwargs)
        return replace(identity,sha256='f'*64) if path.name=='stk_mins_qfq_derived_history.py' else identity
    monkeypatch.setattr(execution,'file_identity',drift)
    with pytest.raises(FactorRepairError,match='implementation_drift'):
        execution.load_repair_plan(Path(price_plan['run_root'])/'plan.json',price_plan['plan_hash'])


def test_full_25_stock_frozen_year_batches_have_complete_market_coverage(price_plan,tmp_path):
    import subprocess
    plan=price_plan;root=Path(plan['lake_root']);run=Path(plan['run_root'])
    unit=next(u for u in plan['units'] if u['asset_key']=='gold_stk_mins_qfq_1m')
    targets=[next(p for p in sorted(unit['target_paths']) if f"/ts_code={scope['ts_code']}/" in p) for scope in plan['scopes']]
    assert len(targets)==25
    dates=sorted({d for p in unit['calculation_windows'] for d in p['target_dates']})
    factors=[str(helper(root,d)) for helper in (paths.raw_adj_factor_path,paths.silver_adj_factor_path) for d in dates]
    originals=[file_identity(Path(p)) for p in targets]
    script=tmp_path/'isolated_coordinator.py'
    script.write_text("""import json,sys
from pathlib import Path
def guard(event,args):
    if event=='socket.connect': raise RuntimeError('network forbidden')
    if event=='open' and isinstance(args[0],str) and (args[0].startswith('/Volumes/') or '/.goldenshare/' in args[0]): raise RuntimeError('formal resources forbidden')
sys.addaudithook(guard)
from orchestrator.defs.bootstrap import stock_adj_factor_history_repair as contract
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import execute_repair_candidates
request=json.loads(sys.stdin.read())
plan=json.load(open(request['plan_path']))
contract.DEFAULT_LAKE_ROOT=plan['lake_root']
contract.DEFAULT_LAKE_STAGING_ROOT=str(Path(plan['run_root']).parents[1])
args={'plan_path':Path(request['plan_path']),'expected_hash':plan['plan_hash'],'worker_command':request['worker']}
execute_repair_candidates(**args,phase='factor',selected_targets=request['factors'])
result=execute_repair_candidates(**args,phase='price',selected_targets=request['targets'])
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import file_identity
files=[Path(plan['run_root'])/'candidates'/Path(p).relative_to(Path(plan['lake_root'])) for p in request['targets']]
proof=[file_identity(p) for p in files if p.exists()]
audit=execute_repair_candidates(**args,phase='price',selected_targets=request['targets'],audit=True)
assert [file_identity(Path(i.path)) for i in proof]==proof
print(json.dumps({'build':result,'audit':audit,'sealed_files':len(proof)}))
""")
    request={'plan_path':str(run/'plan.json'),'worker':launcher(plan,tmp_path),'targets':targets,'factors':factors}
    process=subprocess.run([sys.executable,'-B',str(script)],input=json.dumps(request),text=True,capture_output=True,check=True)
    proof=json.loads(process.stdout);result=proof['build'];audit=proof['audit']
    assert result['completed']==result['total']==25 and result['sample'] and not result['all_chain_ready']
    assert result['peak_rss_bytes']<1024**3 and audit['peak_rss_bytes']<1024**3
    assert audit['completed']==25 and audit['audited'] and not audit['all_chain_ready']
    assert [file_identity(Path(p)) for p in targets]==originals
    print(json.dumps({'isolated_25_stock_year':True,'completed':25,'changed_rows':result['changed_rows'],'peak_rss_bytes':max(result['peak_rss_bytes'],audit['peak_rss_bytes']),'candidate_bytes':result['candidate_bytes'],'elapsed_seconds':result['elapsed_seconds']}))


def test_plan_capacity_accepts_inventory_above_128m_and_rejects_over_192m(price_plan,tmp_path):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        REPAIR_PLAN_MAX_BYTES,
    )
    assert REPAIR_PLAN_MAX_BYTES == 192 * 1024**2
    plan=price_plan
    path=Path(plan['run_root'])/'plan.json'
    encoded=path.read_bytes()
    with path.open('wb') as stream:
        stream.write(encoded)
        stream.write(b' '*((144*1024**2)-len(encoded)))
    assert execution.load_repair_plan(path,plan['plan_hash'])['budget']['max_rss']==4*1024**3
    with path.open('r+b') as stream:stream.truncate(REPAIR_PLAN_MAX_BYTES+1)
    with pytest.raises(FactorRepairError,match='plan.*(size|exceed|large)'):
        execution.load_repair_plan(path,plan['plan_hash'])
