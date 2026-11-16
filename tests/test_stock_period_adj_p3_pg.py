"""LLD13.29 acceptance in task-owned PostgreSQL; no configured Prod connections.

Factor/master fixtures follow their actual ORM producer contracts. Price literals
come from the independently captured 21-field source sample; deliberate code and
date variants exercise scope, not market-price correctness.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, UTC
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.dao.stock_period_adj_delivery_dao import StockPeriodAdjDeliveryDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput
from src.foundation.ingestion.stock_period_adj_inputs import factor_changes
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor as Factor
from src.ops.services.stock_period_adj_probe_service import HISTORY_CONDITION, active_task, evaluate
from test_stock_period_adj_p2_pg import (
    pg as period_pg, Basic, Mapping, Raw, Serving, Delivery, TaskRun, TaskRunNode, ProbeRule, ProbeRunLog, OpsSchedule,
    plan, request, row_for, execute, rule_for, patch_source,
)
from test_stock_period_adj_contracts import literal_rows


@pytest.fixture
def pg(period_pg):
    Factor.__table__.create(period_pg)
    return period_pg


def maintain(kind='stock_history', *, freq='month', codes=None, keys=None, run_id=301):
    intent = {'kind':kind}
    if codes is not None: intent['stock_codes'] = codes
    if keys is not None: intent['remove_keys'] = keys
    return DatasetActionRequest(dataset_key='stk_period_bar_adj_'+freq, action='maintain',
        time_input=DatasetTimeInput(mode='none'), maintenance_intent=intent, run_id=run_id)


def key(code='000001.SZ', stamp='2020-02-29', freq='month'):
    return {'ts_code':code, 'trade_date':stamp, 'freq':freq}


def add_stocks(engine, *codes):
    with Session(engine) as session:
        session.add_all(Basic(ts_code=code, curr_type='CNY', list_status='L', list_date=date(2000,1,1)) for code in codes)
        session.commit()


def add_factors(engine, values, previous=date(2026,11,12), day=date(2026,11,13)):
    with Session(engine) as session:
        for code, before, after in values:
            for stamp, value in [(previous,before),(day,after)]:
                if value is not None:
                    session.add(Factor(ts_code=code, trade_date=stamp, adj_factor=Decimal(value)))
        session.commit()


def finish_current(engine, day=date(2026,11,13)):
    with Session(engine) as session:
        codes=list(session.scalars(select(Basic.ts_code)))
    for freq in ('week','month'):
        req=request(freq,day=day)
        execute(engine, req, plan(engine,req), rows=lambda unit:[row_for(unit,code,end=day) for code in codes])


def automatic(freq='week', day=date(2026,11,13)):
    return DatasetActionRequest(dataset_key='stk_period_bar_adj_'+freq, action='maintain', run_id=401,
        time_input=DatasetTimeInput(mode='point',business_date=day), maintenance_intent={'kind':'factor_history'}, trigger_source='probe')


def seed_quotes(engine, codes=('000001.SZ',)):
    with Session(engine) as session:
        for code in codes:
            session.add_all(Raw(**{**row,'ts_code':code}) for row in literal_rows())
            selected={**literal_rows()[0],'ts_code':code}
            selected['change_amount']=selected.pop('change')
            session.add(Serving(**selected))
        session.commit()


def test_adjacent_factors_weekend_zero_first_appearance_and_identity(pg):
    add_stocks(pg,'600000.SH','600001.SH','600002.SH')
    add_factors(pg,[('000001.SZ','1','2'),('600000.SH','3','3'),('600001.SH',None,'4'),('600002.SH','5',None)],
        previous=date(2026,11,13),day=date(2026,11,16))
    with Session(pg) as session:
        value=factor_changes(session,date(2026,11,16))
        assert value['previous_business_date']=='2026-11-13'
        assert (value['factor_rows_previous'],value['factor_rows_current'],value['compared_stocks'])==(3,3,2)
        assert value['changed_codes']==['000001.SZ']
        zero=factor_changes(session,date(2026,11,12))
        assert (zero['factor_rows_previous'],zero['factor_rows_current'],zero['compared_stocks'],zero['changed_count'])==(0,0,0,0)


def test_automatic_pair_uses_first_list_even_after_factors_change_and_other_frequency_not_queued(pg,monkeypatch):
    import src.foundation.ingestion.stock_period_adj_planning as module
    add_stocks(pg,'600000.SH','600001.SH'); finish_current(pg)
    add_factors(pg,[('000001.SZ','1','2'),('600000.SH','1','2'),('600001.SH','1','1')])
    first=plan(pg,automatic())
    assert [u.request_params['ts_code'] for u in first.units]==['000001.SZ','600000.SH']
    with Session(pg) as session:
        heads=StockPeriodAdjDeliveryDAO(session).frozen_history_pair(date(2026,11,13))
        assert set(heads)=={'week','month'}
        assert heads['week'].payload['context']['history_plan_refs']==heads['month'].payload['context']['history_plan_refs']
        assert session.scalar(select(func.count()).select_from(TaskRun))==0
        session.get(Factor,('600000.SH',date(2026,11,13))).adj_factor=Decimal('1')
        session.get(Factor,('600001.SH',date(2026,11,13))).adj_factor=Decimal('2')
        session.commit()
    monkeypatch.setattr(module,'factor_changes',lambda *a,**kw:pytest.fail('frozen automatic plan must not compare again'))
    second=plan(pg,automatic('month'))
    assert [u.request_params for u in second.units]==[{'freq':'month','ts_code':'000001.SZ'},{'freq':'month','ts_code':'600000.SH'}]
    assert first.execution_context['stock_period_adj']['input_digest']==second.execution_context['stock_period_adj']['input_digest']


def test_automatic_pair_concurrent_planners_commit_only_one_pair(pg,monkeypatch):
    import src.foundation.ingestion.stock_period_adj_planning as module
    finish_current(pg); add_factors(pg,[('000001.SZ','1','2')])
    barrier=Barrier(2); original=module.plan_header
    def header(context,units):
        if context['freq']=='week': barrier.wait(timeout=10)
        return original(context,units)
    monkeypatch.setattr(module,'plan_header',header)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda freq:plan(pg,automatic(freq)), ['week','month']))
    refs=[p.execution_context['stock_period_adj']['history_plan_refs'] for p in results]
    assert refs[0]==refs[1]
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.purpose=='factor_history',Delivery.record_kind=='plan_frozen'))==2


def test_freeze_interruption_never_leaves_an_executable_half_pair(pg,monkeypatch):
    import src.foundation.ingestion.stock_period_adj_planning as module
    finish_current(pg); add_factors(pg,[('000001.SZ','1','2')])
    original=module.plan_header
    def fail_month(context,units):
        if context['freq']=='month': raise SystemExit('process exited before both headers committed')
        return original(context,units)
    monkeypatch.setattr(module,'plan_header',fail_month)
    with pytest.raises(SystemExit): plan(pg,automatic())
    with Session(pg) as session:
        assert StockPeriodAdjDeliveryDAO(session).frozen_history_pair(date(2026,11,13))=={}
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.purpose=='factor_history',Delivery.record_kind=='plan_unit'))==2
    monkeypatch.setattr(module,'plan_header',original)
    assert len(plan(pg,automatic()).units)==1


def test_zero_factors_do_not_freeze_empty_business_batch_or_download(pg):
    finish_current(pg)
    req=automatic(); planned=plan(pg,req)
    result=execute(pg,req,planned,rows=lambda unit:pytest.fail('zero history cannot download'))
    assert result.unit_total==result.unit_done==result.rows_written==0
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.purpose=='factor_history'))==0


@pytest.mark.parametrize('freq',['week','month'])
def test_explicit_history_has_no_dates_no_factor_query_no_2010_cutoff(pg,freq,monkeypatch):
    import src.foundation.ingestion.stock_period_adj_planning as module
    monkeypatch.setattr(module,'factor_changes',lambda *a,**kw:pytest.fail('manual stock scope cannot compare daily factors'))
    progress=[]
    req=maintain(freq=freq,codes=['000001.SZ']); planned=plan(pg,req,planning_report=lambda current,total:progress.append((current,total)))
    assert progress==[({'entity':{'code':'000001.SZ','name':None,'kind':'stock'},'time':{'business_date':None}},1)]
    unit=planned.units[0]
    assert unit.trade_date is None and unit.request_params=={'ts_code':'000001.SZ','freq':freq}
    source=[{**literal_rows()[0],'freq':freq,'trade_date':date(1991,4,5) if freq=='week' else date(1991,4,30)}]
    result=execute(pg,req,planned,rows=lambda u:source)
    assert (result.rows_fetched,result.rows_written,result.rows_rejected)==(1,1,0)
    with Session(pg) as session:
        assert session.scalar(select(Raw.trade_date))==source[0]['trade_date']
        assert session.scalar(select(Serving.close_qfq))==Decimal('11.14')
        assert set(session.scalars(select(Delivery.purpose)))=={'stock_history'}


def test_history_older_rows_cannot_overwrite_current_and_absent_keys_remain(pg):
    req=request(); planned=plan(pg,req)
    execute(pg,req,planned,rows=lambda u:[row_for(u,end=date(2026,11,16),qfq='11.16')])
    history=maintain(codes=['000001.SZ']); planned_history=plan(pg,history)
    incoming=[row_for(planned.units[0],end=date(2026,11,13),qfq='9.99'),literal_rows()[0]]
    result=execute(pg,history,planned_history,rows=lambda u:incoming)
    assert result.ingestion_diagnostics['stock_period_adj']['raw_protected']==1
    with Session(pg) as session:
        assert session.scalar(select(Raw.close_qfq).where(Raw.trade_date==date(2026,11,30)))==Decimal('11.16')
    again=maintain(codes=['000001.SZ'],run_id=302)
    execute(pg,again,plan(pg,again),rows=lambda u:[])
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Raw))==2


def test_confirmed_bse_new_code_and_delisted_manual_history_are_supported(pg):
    with Session(pg) as session:
        session.add(Basic(ts_code='832000.BJ',curr_type='CNY',list_status='D',list_date=date(2000,1,1),delist_date=date(2020,1,1)))
        session.add(Mapping(o_code='832000.BJ',n_code='920000.BJ',fetched_at=datetime.now(UTC)))
        session.commit()
    req=maintain(codes=['832000.BJ']); planned=plan(pg,req)
    assert planned.units[0].request_params=={'ts_code':'920000.BJ','freq':'month'}
    execute(pg,req,planned,rows=lambda u:[{**literal_rows()[0],'ts_code':'920000.BJ'}])
    with Session(pg) as session:
        assert session.scalar(select(Raw.ts_code))=='920000.BJ'


def test_exact_removal_reselects_remaining_candidate_and_only_empty_cycle_disappears(pg):
    seed_quotes(pg)
    req=maintain('remove_keys',keys=[key()]); planned=plan(pg,req)
    result=execute(pg,req,planned,rows=lambda unit:pytest.fail('pure withdrawal must not download'))
    assert result.rows_fetched==0 and result.ingestion_diagnostics['stock_period_adj']['raw_deleted']==1
    with Session(pg) as session:
        selected=session.scalar(select(Serving))
        assert selected.trade_date==date(2020,2,28) and selected.close_qfq==Decimal('12.01')
    last=maintain('remove_keys',keys=[key(stamp='2020-02-28')],run_id=302)
    execute(pg,last,plan(pg,last),rows=lambda unit:pytest.fail('pure withdrawal must not download'))
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Raw))==0
        assert session.scalar(select(func.count()).select_from(Serving))==0


@pytest.mark.parametrize('exit_process',[False,True])
def test_removal_commit_cancel_or_exit_resume_only_remaining_stock_and_replay(pg,exit_process):
    seed_quotes(pg,('000001.SZ','600000.SH'))
    req=maintain('remove_keys',keys=[key(),key(stamp='2020-02-28'),key('600000.SH')])
    planned=plan(pg,req); stop={'value':False}
    def report(snapshot,message):
        if snapshot.unit_done==1:
            if exit_process: raise SystemExit('process exit after committed stock A')
            stop['value']=True
    with pytest.raises(SystemExit if exit_process else IngestionCanceledError):
        execute(pg,req,planned,cancel=lambda run:stop['value'],report=report)
    with Session(pg) as session:
        assert list(session.scalars(select(Delivery.ts_code).where(Delivery.record_kind=='unit')))==['000001.SZ']
        assert set(session.scalars(select(Raw.ts_code)))=={'600000.SH'}
    result=execute(pg,req,planned,rows=lambda u:pytest.fail('withdrawal resume must not download'))
    replay=execute(pg,req,planned,rows=lambda u:pytest.fail('committed replay must not download'))
    assert result.unit_done==replay.unit_done==2
    assert result.ingestion_diagnostics['stock_period_adj']['raw_deleted']==3
    with Session(pg) as session:
        assert session.scalar(select(Serving.trade_date))==date(2020,2,28)
        assert session.scalar(select(Serving.ts_code))=='600000.SH'


def test_combination_removal_wins_and_removal_only_stock_never_downloads(pg):
    seed_quotes(pg,('000001.SZ','600000.SH'))
    req=maintain('stock_history_and_remove',codes=['000001.SZ'],keys=[key(),key('600000.SH')])
    planned=plan(pg,req); calls=[]
    def source(unit):
        calls.append(unit.request_params)
        assert unit.progress_context['ts_code']=='000001.SZ'
        return literal_rows()
    result=execute(pg,req,planned,rows=source)
    assert calls==[{'ts_code':'000001.SZ','freq':'month'}]
    assert result.unit_done==2 and result.ingestion_diagnostics['stock_period_adj']['raw_deleted']==2
    with Session(pg) as session:
        assert set(session.scalars(select(Raw.trade_date)))=={date(2020,2,28)}
        assert set(session.scalars(select(Serving.close_qfq)))=={Decimal('12.01')}


def test_combination_failed_download_does_not_remove_same_stock(pg):
    seed_quotes(pg)
    req=maintain('stock_history_and_remove',codes=['000001.SZ'],keys=[key()]); planned=plan(pg,req)
    def fail(unit): raise RuntimeError('source failed')
    with pytest.raises(RuntimeError,match='source failed'): execute(pg,req,planned,rows=fail)
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Raw))==2
        assert session.scalar(select(Serving.close_qfq))==Decimal('11.14')
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.record_kind=='unit'))==0


@pytest.mark.parametrize('bad',[{'kind':'stock_history','stock_codes':[]},
    {'kind':'remove_keys','remove_keys':[key(freq='week')]}, {'kind':'remove_keys','remove_keys':[]},
    {'kind':'stock_history','stock_codes':['000001.SZ'],'end_date':'2026-11-13'}])
def test_invalid_history_ranges_are_not_frozen(pg,bad):
    req=replace(maintain(codes=['000001.SZ']),maintenance_intent=bad)
    with pytest.raises(Exception): plan(pg,req)
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Delivery))==0


def test_history_wrong_source_identity_rolls_back_and_frequency_check_still_applies(pg):
    req=maintain(codes=['000001.SZ']); planned=plan(pg,req)
    for wrong in [{'ts_code':'600000.SH'},{'freq':'week'}]:
        with pytest.raises(Exception): execute(pg,req,planned,rows=lambda u:[{**literal_rows()[0],**wrong}])
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Raw))==0


def test_history_probe_requires_both_current_results_zero_logs_and_later_arrival_triggers(pg):
    from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService
    rule=rule_for(); rule.probe_condition_json={'type':HISTORY_CONDITION}; current=datetime(2026,11,13,20,tzinfo=ZoneInfo('Asia/Shanghai'))
    with Session(pg) as session:
        assert evaluate(session,rule,current=current)[0] is False
    finish_current(pg)
    with Session(pg) as session:
        session.add(rule); session.commit()
        tasks,counts=ProbeRuntimeService().run_once(session,now=current)
        assert not tasks and counts.triggered_rules==0
        log=session.scalar(select(ProbeRunLog))
        assert log.condition_matched is False and log.payload_json['changed_count']==0
        assert log.payload_json['factor_rows_current']==log.payload_json['factor_rows_previous']==0
        rule.last_probed_at=datetime(2026,11,13,11,58,tzinfo=UTC); session.commit()
    add_factors(pg,[('000001.SZ','1','2')])
    with Session(pg) as session:
        tasks,counts=ProbeRuntimeService().run_once(session,now=current)
        assert len(tasks)==counts.triggered_rules==1
        assert tasks[0].request_payload_json['maintenance_intent']=={'kind':'factor_history'}
        assert tasks[0].time_input_json=={'mode':'point','business_date':'2026-11-13'}


def test_history_activity_does_not_block_current_purpose_or_next_day(pg):
    from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext
    with Session(pg) as session:
        TaskRunCommandService().create_task_run(session,context=TaskRunCreateContext(task_type='dataset_action',
            resource_key='stk_period_bar_adj_month',action='maintain',time_input={'mode':'point','business_date':'2026-11-13'},
            filters={},request_payload={'maintenance_intent':{'kind':'factor_history'}},trigger_source='probe',requested_by_user_id=1))
        assert active_task(session,'stk_period_bar_adj_month',date(2026,11,13),'factor_history') is not None
        assert active_task(session,'stk_period_bar_adj_month',date(2026,11,13),'current_period') is None
        assert active_task(session,'stk_period_bar_adj_month',date(2026,11,16),'current_period') is None


def test_frozen_unqueued_frequency_probe_does_not_compare_changed_factors(pg,monkeypatch):
    import src.ops.services.stock_period_adj_probe_service as module
    finish_current(pg); add_factors(pg,[('000001.SZ','1','2')]); plan(pg,automatic())
    monkeypatch.setattr(module,'factor_changes',lambda *a,**kw:pytest.fail('frozen other frequency must not compare factors'))
    rule=rule_for(); rule.probe_condition_json={'type':HISTORY_CONDITION}
    with Session(pg) as session:
        hit,_,payload=evaluate(session,rule,current=datetime(2026,11,13,20,tzinfo=ZoneInfo('Asia/Shanghai')))
        assert hit and payload['batch_id']


def test_manual_history_worker_and_explicit_resume_preserve_scope_and_terminal_state(pg,monkeypatch):
    from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext
    from src.ops.runtime.worker import OperationsWorker
    patch_source(monkeypatch,lambda unit:literal_rows())
    with Session(pg) as session:
        service=TaskRunCommandService()
        task=service.create_task_run(session,context=TaskRunCreateContext(task_type='dataset_action',resource_key='stk_period_bar_adj_month',
            action='maintain',time_input={'mode':'none'},filters={},request_payload={'maintenance_intent':{'kind':'stock_history','stock_codes':['000001.SZ']}},
            trigger_source='manual',requested_by_user_id=1))
        assert session.scalar(select(func.count()).select_from(Delivery))==0
        finished=OperationsWorker().run_task_run(session,task.id)
        assert finished.status=='success' and (finished.unit_done,finished.unit_total)==(1,1)
        assert session.get(TaskRunNode,finished.current_node_id).status=='success'
        resumed=service.create_task_run(session,context=TaskRunCreateContext(task_type='dataset_action',resource_key='stk_period_bar_adj_month',
            action='maintain',time_input={},filters={},request_payload={},trigger_source='manual',requested_by_user_id=1,resume_from_task_run_id=task.id))
        patch_source(monkeypatch,lambda unit:pytest.fail('resume must not download committed history'))
        replay=OperationsWorker().run_task_run(session,resumed.id)
        assert replay.status=='success' and replay.unit_done==1


def test_parent_schedule_binds_two_rules_updates_both_and_pause_removes_both(pg):
    from src.ops.services.schedule_probe_binding_service import ScheduleProbeBindingService
    from src.ops.services.stock_period_adj_probe_service import CURRENT_CONDITION
    with Session(pg) as session:
        schedule=OpsSchedule(target_type='dataset_action',target_key='stk_period_bar_adj_month.maintain',display_name='月线日更',
            status='active',schedule_type='cron',trigger_mode='probe',timezone='Asia/Shanghai',params_json={},
            probe_config_json={'condition_kind':CURRENT_CONDITION,'window_start':'20:00','window_end':'00:00',
                'probe_interval_seconds':60,'max_triggers_per_day':1})
        session.add(schedule); session.flush()
        binding=ScheduleProbeBindingService(); binding.sync_for_schedule(session,schedule=schedule,actor_user_id=1); session.commit()
        rules=list(session.scalars(select(ProbeRule)))
        assert {r.probe_condition_json['type'] for r in rules}=={CURRENT_CONDITION,HISTORY_CONDITION}
        assert all((r.window_start,r.window_end,r.probe_interval_seconds,r.schedule_id)==('20:00','00:00',60,schedule.id) for r in rules)
        schedule.display_name='编辑后的月线日更'; binding.sync_for_schedule(session,schedule=schedule,actor_user_id=1); session.commit()
        assert all(r.name.startswith('编辑后的月线日更') for r in session.scalars(select(ProbeRule)))
        assert session.scalar(select(func.count()).select_from(ProbeRule))==2
        schedule.status='paused'; binding.sync_for_schedule(session,schedule=schedule,actor_user_id=1); session.commit()
        assert session.scalar(select(func.count()).select_from(ProbeRule))==0


def test_both_automatic_frequencies_execute_independently_and_late_source_is_allowed(pg):
    finish_current(pg); add_factors(pg,[('000001.SZ','1','2')])
    week=automatic(); first=plan(pg,week); month=automatic('month'); second=plan(pg,month)
    def history(unit):
        return [{**literal_rows()[0],'freq':unit.request_params['freq'],'end_date':date(2026,11,16)}]
    execute(pg,week,first,rows=history)
    with Session(pg) as session:
        assert StockPeriodAdjDeliveryDAO(session).get(first.execution_context['stock_period_adj']['batch_id'],'batch_closed','batch_closed')
        assert StockPeriodAdjDeliveryDAO(session).get(second.execution_context['stock_period_adj']['batch_id'],'batch_closed','batch_closed') is None
    execute(pg,month,second,rows=history)
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.purpose=='factor_history',Delivery.record_kind=='batch_closed'))==2
        assert session.scalar(select(Raw.end_date).where(Raw.trade_date==date(2020,2,29),Raw.freq=='month'))==date(2026,11,16)


def test_closed_period_single_stock_repair_accepts_existing_non_month_end_source_date(pg):
    with Session(pg) as session:
        session.add(Raw(**literal_rows()[1])); session.commit()
    req=request(kind='period',day=date(2020,2,29),filters={'ts_code':'000001.SZ'})
    execute(pg,req,plan(pg,req),rows=lambda unit:[literal_rows()[0]])
    with Session(pg) as session:
        assert session.scalar(select(Serving.trade_date))==date(2020,2,29)


def test_history_observation_failure_preserves_business_and_resume_avoids_download(pg):
    req=maintain(codes=['000001.SZ']); planned=plan(pg,req)
    def observation(*args): raise RuntimeError('observation unavailable')
    execute(pg,req,planned,rows=lambda u:literal_rows(),report=observation)
    replay=execute(pg,req,planned,rows=lambda u:pytest.fail('committed history must not be fetched'))
    assert replay.unit_done==1 and replay.rows_written==2


@pytest.mark.parametrize('case',['date','filter','internal'])
def test_manual_history_mixed_date_filters_and_internal_purpose_are_rejected(pg,case):
    req=maintain(codes=['000001.SZ'])
    if case=='date': req=replace(req,time_input=DatasetTimeInput(mode='none',end_date=date(2026,11,13)))
    if case=='filter': req=replace(req,filters={'ts_code':'000001.SZ'})
    if case=='internal': req=replace(automatic(),trigger_source='manual')
    with pytest.raises(Exception): plan(pg,req)


@pytest.mark.parametrize('freq,row_count',[('week',1786),('month',428)])
def test_single_stock_history_budget_replay_and_bounded_final_readback(pg,tmp_path,freq,row_count):
    """Synthetic full-stock lengths match LLD13.22's bounded source counts.

    Literal prices are deliberately constant; this measures the new SQL path,
    not real network or adjustment arithmetic, and does not forecast all-market time.
    """
    from calendar import monthrange
    from datetime import timedelta
    import json
    import time
    from src.foundation.datasets.stock_period_adj_contracts import canonical_json
    req=maintain(freq=freq,codes=['000001.SZ'])
    started=time.perf_counter(); planned=plan(pg,req); planning_seconds=time.perf_counter()-started
    rows=[]; base=literal_rows()[0]
    for i in range(row_count):
        if freq=='week': stamp=date(1991,4,5)+timedelta(days=7*i)
        else:
            year,month=divmod(1991*12+3+i,12); month+=1
            stamp=date(year,month,monthrange(year,month)[1])
        rows.append({**base,'freq':freq,'trade_date':stamp})
    started=time.perf_counter(); result=execute(pg,req,planned,rows=lambda unit:rows); execution_seconds=time.perf_counter()-started
    started=time.perf_counter(); replay=execute(pg,req,planned,rows=lambda unit:pytest.fail('committed history cannot be fetched again')); replay_seconds=time.perf_counter()-started
    started=time.perf_counter()
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Raw).where(Raw.ts_code=='000001.SZ',Raw.freq==freq))==row_count
        assert session.scalar(select(func.count()).select_from(Serving).where(Serving.ts_code=='000001.SZ',Serving.freq==freq))==row_count
        fact=session.scalar(select(Delivery).where(Delivery.record_kind=='unit'))
        assert fact.payload['source_received']==fact.payload['source_unique']==fact.payload['raw_written']==fact.payload['serving_written']==row_count
        assert fact.payload['raw_deleted']==0
    readback_seconds=time.perf_counter()-started
    assert result.rows_written==replay.rows_written==row_count
    (tmp_path/f'{freq}-history-performance.json').write_text(json.dumps({'synthetic_history_rows':row_count,
        'canonical_bytes':len(canonical_json(rows).encode()),'planning_seconds':planning_seconds,
        'capture_publish_seconds':execution_seconds,'replay_seconds':replay_seconds,'final_count_readback_seconds':readback_seconds}))


@pytest.mark.parametrize('limit',['units','bytes','rows'])
def test_history_and_withdrawal_reuse_existing_policy_limits_before_freeze(pg,limit):
    from src.foundation.ingestion.stock_period_adj_planning import resolve_units
    from src.foundation.datasets.stock_period_adj_contracts import StockPeriodAdjContractError
    add_stocks(pg,'600000.SH'); definition=get_dataset_definition('stk_period_bar_adj_month')
    original=definition.planning.stock_period_adj_policy
    if limit=='units':
        policy=replace(original,max_units=1); req=maintain(codes=['000001.SZ','600000.SH'])
    elif limit=='bytes':
        policy=replace(original,max_plan_bytes=100); req=maintain(codes=['000001.SZ'])
    else:
        policy=replace(original,max_rows_per_unit=1); req=maintain('remove_keys',keys=[key(),key(stamp='2020-02-28')])
    definition=replace(definition,planning=replace(definition.planning,stock_period_adj_policy=policy))
    with Session(pg) as session:
        with pytest.raises(StockPeriodAdjContractError): resolve_units(session,req,definition,persist=True)
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.record_kind=='plan_frozen'))==0
        assert session.scalar(select(func.count()).select_from(Raw))==0


def test_withdrawal_worker_cancel_and_resume_keep_task_node_terminal_states_consistent(pg,monkeypatch):
    from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext
    from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
    from src.ops.runtime.worker import OperationsWorker
    seed_quotes(pg,('000001.SZ','600000.SH'))
    patch_source(monkeypatch,lambda unit:pytest.fail('pure withdrawal never downloads'))
    original=TaskRunIngestionContext.update_progress; progress=[]
    def observe(self,**kwargs):
        original(self,**kwargs)
        progress.append(kwargs['unit_done'])
        if kwargs['unit_done']==1:
            with Session(pg) as cancel:
                task=cancel.get(TaskRun,kwargs['run_id']); task.cancel_requested_at=datetime.now(UTC); cancel.commit()
    monkeypatch.setattr(TaskRunIngestionContext,'update_progress',observe)
    with Session(pg) as session:
        service=TaskRunCommandService()
        task=service.create_task_run(session,context=TaskRunCreateContext(task_type='dataset_action',resource_key='stk_period_bar_adj_month',
            action='maintain',time_input={'mode':'none'},filters={},request_payload={'maintenance_intent':{'kind':'remove_keys',
                'remove_keys':[key(),key('600000.SH')]}},trigger_source='manual',requested_by_user_id=1))
        result=OperationsWorker().run_task_run(session,task.id)
        assert result.status=='canceled' and (result.unit_done,result.unit_total,result.progress_percent)==(1,2,50)
        assert session.get(TaskRunNode,result.current_node_id).status=='canceled'
        assert progress==sorted(progress)
        monkeypatch.setattr(TaskRunIngestionContext,'update_progress',original)
        resumed=service.create_task_run(session,context=TaskRunCreateContext(task_type='dataset_action',resource_key='stk_period_bar_adj_month',
            action='maintain',time_input={},filters={},request_payload={},trigger_source='manual',requested_by_user_id=1,resume_from_task_run_id=task.id))
        final=OperationsWorker().run_task_run(session,resumed.id)
        assert final.status=='success' and final.unit_done==2 and final.progress_percent==100
        assert session.get(TaskRunNode,final.current_node_id).status=='success'
        assert set(session.scalars(select(Serving.trade_date)))=={date(2020,2,28)}


def test_failed_automatic_history_can_be_explicitly_resumed_without_rescreening(pg,monkeypatch):
    import src.foundation.ingestion.stock_period_adj_planning as planning
    from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext
    from src.ops.runtime.worker import OperationsWorker
    finish_current(pg); add_factors(pg,[('000001.SZ','1','2')])
    with Session(pg) as session:
        service=TaskRunCommandService()
        task=service.create_task_run(session,context=TaskRunCreateContext(task_type='dataset_action',resource_key='stk_period_bar_adj_month',
            action='maintain',time_input={'mode':'point','business_date':'2026-11-13'},filters={},
            request_payload={'maintenance_intent':{'kind':'factor_history'}},trigger_source='probe',requested_by_user_id=1))
        patch_source(monkeypatch,lambda unit:[{**literal_rows()[0],'ts_code':'600000.SH'}])
        failed=OperationsWorker().run_task_run(session,task.id)
        assert failed.status=='failed' and failed.unit_done==0
        assert session.get(TaskRunNode,failed.current_node_id).status=='failed'
        original_batch=StockPeriodAdjDeliveryDAO(session).frozen_intent('factor_history:month:2026-11-13').batch_id
        monkeypatch.setattr(planning,'factor_changes',lambda *a,**kw:pytest.fail('original automatic history must not rescreen factors'))
        resumed=service.create_task_run(session,context=TaskRunCreateContext(task_type='dataset_action',resource_key='stk_period_bar_adj_month',
            action='maintain',time_input={},filters={},request_payload={},trigger_source='manual',requested_by_user_id=1,resume_from_task_run_id=task.id))
        patch_source(monkeypatch,lambda unit:literal_rows())
        final=OperationsWorker().run_task_run(session,resumed.id)
        assert final.status=='success' and final.unit_done==1
        assert session.get(TaskRunNode,final.current_node_id).status=='success'
        assert StockPeriodAdjDeliveryDAO(session).get(original_batch,'batch_closed','batch_closed')


def test_combination_publication_conflict_rolls_back_exact_deletion_and_raw_merge(pg):
    seed_quotes(pg)
    with Session(pg) as session:
        session.get(Raw,('000001.SZ',date(2020,2,29),'month')).end_date=date(2026,11,16)
        session.add(Raw(**{**literal_rows()[0],'trade_date':date(2020,3,31)})); session.commit()
    req=maintain('stock_history_and_remove',codes=['000001.SZ'],keys=[key(stamp='2020-03-31')])
    planned=plan(pg,req)
    with pytest.raises(Exception,match='最新计算截至日期'):
        execute(pg,req,planned,rows=lambda unit:[{**literal_rows()[1],'end_date':date(2026,11,16)}])
    with Session(pg) as session:
        assert session.get(Raw,('000001.SZ',date(2020,3,31),'month')) is not None
        assert session.get(Raw,('000001.SZ',date(2020,2,28),'month')).end_date==date(2025,9,10)
        assert session.scalar(select(Serving.close_qfq))==Decimal('11.14')
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.record_kind=='unit'))==0


def test_exact_withdrawal_does_not_touch_other_frequency(pg):
    seed_quotes(pg)
    with Session(pg) as session:
        session.add(Raw(**{**literal_rows()[0],'freq':'week'}))
        row={**literal_rows()[0],'freq':'week'}; row['change_amount']=row.pop('change')
        session.add(Serving(**row)); session.commit()
    req=maintain('remove_keys',keys=[key()]); execute(pg,req,plan(pg,req),rows=lambda unit:pytest.fail('no download'))
    with Session(pg) as session:
        assert session.scalar(select(Raw.close_qfq).where(Raw.freq=='week'))==Decimal('11.14')
        assert session.scalar(select(Serving.close_qfq).where(Serving.freq=='week'))==Decimal('11.14')
        assert session.scalar(select(Serving.close_qfq).where(Serving.freq=='month'))==Decimal('12.01')


def test_factor_comparison_does_not_query_cancellation_once_per_stock(pg):
    from src.foundation.datasets.stock_period_adj_contracts import ROW_BLOCK_SIZE
    # Cross multiple existing row blocks; expected check count is independent of
    # the number of comparable securities, not computed by the tested function.
    codes=[f'{value:06d}.SZ' for value in range(100001,100001+2*ROW_BLOCK_SIZE+1)]
    add_stocks(pg,*codes); add_factors(pg,[(code,'1','2') for code in codes]); checks=[]
    with Session(pg) as session:
        result=factor_changes(session,date(2026,11,13),check=lambda:checks.append(True))
    assert result['changed_codes']==codes and result['compared_stocks']==257
    assert len(checks)==4
