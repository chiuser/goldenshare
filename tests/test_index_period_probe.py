"""LLD §10: real PostgreSQL, probe -> TaskRun -> Worker -> Serving.

Uses the current producer models and the existing isolated fixture. Prices and
weekday calendars are explicit artificial inputs, not alleged Tushare results.
No existing database or real download connector is used.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
import json
import subprocess
import sys

import pytest
from sqlalchemy import delete, event, func, insert, select, update

from tests.test_index_period_cards_integration import cluster, pg_env, CODES, DAY, NOW, card_map, source_mock
from src.foundation.ingestion.index_period_serving import SHANGHAI
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.queries.probe_query_service import ProbeQueryService
from src.ops.queries.biz_table_card_query_service import BizTableCardQueryService
from src.ops.services.index_period_schedule import INDEX_PERIOD_SERVING_PROBE_CONDITION
from src.ops.services.index_period_serving_probe_service import IndexPeriodServingProbeService
from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService
from src.ops.services.operations_schedule_service import OperationsScheduleService


def set_probe_time(mocker, now):
    class ProbeClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)
    mocker.patch('src.ops.services.operations_probe_runtime_service.datetime', ProbeClock)
    mocker.patch('src.ops.runtime.index_period_serving_executor.datetime').now.side_effect=lambda zone:now.astimezone(zone)


@pytest.fixture
def env(pg_env, mocker):
    session, worker, engine = pg_env
    set_probe_time(mocker, NOW)
    ProbeRunLog.__table__.create(engine)
    ConfigRevision.__table__.create(engine)
    mocker.patch('src.ops.services.index_daily_remote_probe_service.create_source_connector',
                 side_effect=AssertionError('Serving probe must not request Tushare'))
    return session, worker, engine


def serving_model(frequency):
    return IndexWeeklyServing if frequency == 'week' else IndexMonthlyServing


def raw_model(frequency):
    return RawIndexWeeklyBar if frequency == 'week' else RawIndexMonthlyBar


def scope(session, frequency, day=DAY):
    start = day - timedelta(days=day.weekday()) if frequency == 'week' else day.replace(day=1)
    dates = list(session.scalars(select(TradeCalendar.trade_date).where(
        TradeCalendar.exchange == 'SSE', TradeCalendar.is_open.is_(True),
        TradeCalendar.trade_date.between(start, day),
    ).order_by(TradeCalendar.trade_date)))
    return dates


def ready_daily(session, frequency, *, day=DAY, codes=CODES):
    dates = scope(session, frequency, day)
    for code in codes:
        session.execute(insert(RawIndexDaily), [dict(ts_code=code, trade_date=d, open=100,
            high=106, low=98, close=102, pre_close=100, vol=7, amount=250) for d in dates])
        if len(dates) > 1:
            session.execute(insert(serving_model(frequency)), dict(ts_code=code,
                period_start_date=dates[0], trade_date=dates[-2], source='derived_daily', close=100))
    session.commit()


def configure(session, frequency, **probe_changes):
    key = f'maintenance.update_index_{"weekly" if frequency == "week" else "monthly"}_serving'
    schedule = session.scalar(select(OpsSchedule).where(OpsSchedule.target_key == key))
    probe_config = dict(condition_kind=INDEX_PERIOD_SERVING_PROBE_CONDITION,
        window_start='19:00', window_end='00:00', probe_interval_seconds=300, max_triggers_per_day=1)
    probe_config.update(probe_changes)
    OperationsScheduleService().update_schedule(session, schedule_id=schedule.id, updated_by_user_id=1,
        changes=dict(trigger_mode='probe', cron_expr=None, next_run_at=None, probe_config=probe_config))
    return session.scalar(select(ProbeRule).where(ProbeRule.schedule_id == schedule.id))


def evaluate(session, rule, now=NOW):
    return IndexPeriodServingProbeService().evaluate(session, rule, current=now)


@pytest.mark.parametrize('frequency', ['week', 'month'])
def test_probe_is_readonly_and_full_pool_task_executes_and_is_not_reenqueued(env, frequency):
    session, worker, engine = env
    ready_daily(session, frequency)
    rule = configure(session, frequency)
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    started = perf_counter()
    try:
        matched, _, payload = evaluate(session, rule)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert matched and payload['ready_count'] == payload['required_count'] == 10
    assert payload['rows_fetched'] == (20 if frequency == 'week' else 70)
    assert all(sql.lstrip().startswith('SELECT') and 'FOR UPDATE' not in sql for sql in statements)
    daily_sql = next(sql for sql in statements if 'raw_tushare.index_daily' in sql)
    assert 'raw_payload' not in daily_sql and 'fetched_at' not in daily_sql
    print('probe measurement',frequency,len(statements),payload['rows_fetched'],perf_counter()-started)
    repeated_sql=[]
    def capture_repeat(_conn,_cursor,statement,_params,_context,_many):
        repeated_sql.append(statement)
    event.listen(engine,'before_cursor_execute',capture_repeat)
    repeated_started=perf_counter()
    try:
        assert evaluate(session,rule)[0] is True
    finally:
        event.remove(engine,'before_cursor_execute',capture_repeat)
    print('probe repeat measurement',frequency,len(repeated_sql),payload['rows_fetched'],perf_counter()-repeated_started)


    tasks, tick = ProbeRuntimeService().run_once(session, now=NOW)
    assert tick.created_task_runs == len(tasks) == 1
    task = tasks[0]
    assert task.resource_key is None and task.task_type == 'maintenance_action'
    assert task.trigger_source == 'probe' and task.schedule_id == rule.schedule_id
    assert task.time_input_json == {'mode':'point','trade_date':'2026-11-10'}
    assert task.request_payload_json['target_key'] == rule.on_success_action_json['action_key']
    assert all(row.trade_date == date(2026,11,9) for row in session.scalars(select(serving_model(frequency))))
    task = worker.run_task_run(session, task.id)
    assert task.status == 'success' and task.rows_saved == task.unit_done == 10
    assert session.get(TaskRunNode,task.current_node_id).status == 'success'
    period_start = scope(session, frequency)[0]
    readback_started=perf_counter()
    model = serving_model(frequency)
    rows = list(session.scalars(select(model).where(
        model.ts_code.in_(CODES), model.period_start_date == period_start,
    )))
    print('probe final readback',frequency,len(rows),perf_counter()-readback_started)
    assert len(rows) == 10 and all(r.trade_date == DAY and r.source == 'derived_daily' for r in rows)
    assert all(r.close == Decimal('102.0000') and r.pct_chg == Decimal('0.0200') for r in rows)
    assert all(r.vol == (1400 if frequency == 'week' else 4900) for r in rows)
    assert all(r.amount == (500000 if frequency == 'week' else 1750000) for r in rows)

    # A fresh runtime must find the already committed maintenance task by action,
    # despite resource_key being NULL. Let the limit allow another check.
    rule.max_triggers_per_day = 2
    session.commit()
    restarted = subprocess.run([sys.executable, "-B", "-c", """
import json,sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import src.ops.services.operations_probe_runtime_service as runtime
when = datetime.fromisoformat(sys.argv[2])
class Clock(datetime):
    @classmethod
    def now(cls,tz=None): return when.astimezone(tz)
runtime.datetime=Clock
with Session(create_engine(sys.argv[1])) as session:
    tasks,tick=runtime.ProbeRuntimeService().run_once(session,now=when)
    print(json.dumps({'created':len(tasks),'processed':tick.processed_rules}))
""", str(engine.url), (NOW+timedelta(minutes=5)).isoformat()], check=True, capture_output=True, text=True)
    assert json.loads(restarted.stdout) == {'created':0,'processed':1}
    log = session.scalar(select(ProbeRunLog).order_by(ProbeRunLog.id.desc()))
    assert log.result_code == 'deduplicated'
    assert session.scalar(select(func.count()).select_from(TaskRun)) == 1


@pytest.mark.parametrize('frequency',['week','month'])
@pytest.mark.parametrize('problem',['today_missing','middle_missing','continuity','invalid_value'])
def test_one_unready_code_prevents_full_pool_trigger_and_records_reason(env,frequency,problem):
    session,_,_=env
    ready_daily(session,frequency)
    dates=scope(session,frequency)
    if problem in {'today_missing','middle_missing'}:
        day=DAY if problem=='today_missing' else dates[0]
        session.execute(delete(RawIndexDaily).where(RawIndexDaily.ts_code=='899050.BJ',RawIndexDaily.trade_date==day))
    elif problem=='continuity':
        session.execute(update(serving_model(frequency)).where(serving_model(frequency).ts_code=='899050.BJ')
                        .values(trade_date=date(2026,11,6)))
    else:
        session.execute(update(RawIndexDaily).where(RawIndexDaily.ts_code=='899050.BJ',RawIndexDaily.trade_date==DAY)
                        .values(close=None))
    session.commit()
    rule=configure(session,frequency)
    tasks,_=ProbeRuntimeService().run_once(session,now=NOW)
    assert tasks==[]
    log=session.scalar(select(ProbeRunLog))
    assert log.condition_matched is False and log.payload_json['ready_count']==9
    failure,=log.payload_json['failures']
    assert failure['ts_code']=='899050.BJ'
    if problem.endswith('missing'):assert failure['missing_dates']==[day.isoformat()]
    elif problem=='continuity':
        assert failure['expected_trade_date']=='2026-11-09' and failure['actual_trade_date']=='2026-11-06'
    else:assert failure['invalid_dates']==['2026-11-10']
    assert session.scalar(select(func.count()).select_from(TaskRun))==0


@pytest.mark.parametrize('frequency,day', [('week',date(2026,11,13)),('month',date(2026,11,30))])
def test_formal_raw_bypasses_missing_daily_and_continuity_mixed_with_bse_daily(env,mocker,frequency,day):
    session,worker,_=env
    now=datetime.combine(day,datetime.min.time(),SHANGHAI)+timedelta(hours=21)
    set_probe_time(mocker,now)
    ready_daily(session,frequency,day=day,codes=['899050.BJ'])
    for code in CODES:
        if code=='899050.BJ':continue
        session.execute(insert(raw_model(frequency)),dict(ts_code=code,trade_date=day,
            open=100,high=106,low=98,close=105,pre_close=0,change=5,pct_chg=0,vol=700,amount=250000,
            api_name='index_weekly' if frequency=='week' else 'index_monthly'))
    session.commit()
    configure(session,frequency)
    tasks,_=ProbeRuntimeService().run_once(session,now=now)
    assert len(tasks)==1
    result=worker.run_task_run(session,tasks[0].id)
    assert result.status=='success' and result.rows_saved==10
    rows=list(session.scalars(select(serving_model(frequency))))
    assert sum(r.source=='api' for r in rows)==9
    assert next(r for r in rows if r.ts_code=='899050.BJ').source=='derived_daily'
    assert all(r.pre_close==0 for r in rows if r.source=='api')


@pytest.mark.parametrize('frequency,day',[('week',date(2026,11,9)),('month',date(2026,11,2))])
def test_period_first_day_does_not_require_prior_serving(env,frequency,day):
    session,_,_=env
    ready_daily(session,frequency,day=day)
    rule=configure(session,frequency)
    now=datetime.combine(day,datetime.min.time(),SHANGHAI)+timedelta(hours=19)
    assert evaluate(session,rule,now)[0] is True


@pytest.mark.parametrize('frequency',['week','month'])
def test_same_day_replay_is_ready_but_synthetic_monthly_raw_is_not_formal(env,frequency):
    session,_,_=env
    ready_daily(session,frequency)
    session.execute(update(serving_model(frequency)).values(trade_date=DAY))
    session.commit()
    rule=configure(session,frequency)
    assert evaluate(session,rule)[0] is True
    if frequency=='month':
        session.execute(insert(RawIndexMonthlyBar),dict(ts_code='899050.BJ',trade_date=date(2026,11,30),api_name='derived_daily'))
        session.execute(delete(RawIndexDaily).where(RawIndexDaily.ts_code=='899050.BJ',RawIndexDaily.trade_date==DAY))
        session.commit()
        matched,_,payload=evaluate(session,rule)
        assert matched is False and payload['failures'][0]['missing_dates']==['2026-11-10']


def test_intervals_window_midnight_nontrading_and_frequency_independence(env):
    session,_,_=env
    ready_daily(session,'week')
    weekly=configure(session,'week')
    monthly=configure(session,'month')
    for now in [datetime(2026,11,10,18,59,tzinfo=SHANGHAI),datetime(2026,11,11,0,tzinfo=SHANGHAI)]:
        tasks,tick=ProbeRuntimeService().run_once(session,now=now)
        assert tasks==[] and tick.processed_rules==0
    tasks,_=ProbeRuntimeService().run_once(session,now=NOW)
    assert len(tasks)==1 and tasks[0].schedule_id==weekly.schedule_id
    logs=list(session.scalars(select(ProbeRunLog).order_by(ProbeRunLog.id)))
    assert len(logs)==2 and sum(log.condition_matched for log in logs)==1
    _,tick=ProbeRuntimeService().run_once(session,now=NOW+timedelta(seconds=299))
    assert tick.processed_rules==0
    saturday=datetime(2026,11,14,19,tzinfo=SHANGHAI)
    assert evaluate(session,weekly,saturday)[0] is False


def test_probe_rule_names_logs_pause_and_card_target_follow_probe_window(env,mocker):
    session,_,_=env
    ready_daily(session,'week')
    rule=configure(session,'week')
    rules=ProbeQueryService().list_probe_rules(session,schedule_id=rule.schedule_id)
    assert rules.items[0].dataset_display_name=='指数周线 Serving'
    assert rules.items[0].source_key is None and rules.items[0].source_display_name=='Prod Raw'
    ProbeRuntimeService().run_once(session,now=NOW)
    for hour,expected in [(18,date(2026,11,9)),(19,DAY)]:
        mocker.patch.object(BizTableCardQueryService,'_local_now',return_value=NOW.replace(hour=hour,minute=0))
        card=card_map(session,'biz_tableset')['index_weekly_serving']
        assert card.expected_business_date==expected and card.auto_schedule_status=='active'
    OperationsScheduleService().pause_schedule(session,schedule_id=rule.schedule_id,updated_by_user_id=1)
    assert session.scalar(select(ProbeRule).where(ProbeRule.schedule_id==rule.schedule_id)) is None
    logs=ProbeQueryService().list_probe_run_logs(session,schedule_id=rule.schedule_id)
    assert logs.items[0].dataset_display_name=='指数周线 Serving'
    assert logs.items[0].source_display_name=='Prod Raw'


@pytest.mark.parametrize('frequency',['week','month'])
def test_execution_rechecks_after_ready_probe_and_preserves_nine_successes(env,frequency):
    session,worker,_=env
    ready_daily(session,frequency)
    configure(session,frequency)
    tasks,_=ProbeRuntimeService().run_once(session,now=NOW)
    assert len(tasks)==1
    session.execute(delete(RawIndexDaily).where(RawIndexDaily.ts_code=='899050.BJ',RawIndexDaily.trade_date==DAY))
    session.commit()
    result=worker.run_task_run(session,tasks[0].id)
    assert result.status=='failed' and result.rows_saved==9 and result.unit_failed==1
    assert session.get(TaskRunNode,result.current_node_id).status=='failed'
    row=session.scalar(select(serving_model(frequency)).where(serving_model(frequency).ts_code=='899050.BJ'))
    assert row.trade_date==date(2026,11,9)


@pytest.mark.parametrize('other_target,other_day',[
    ('maintenance.update_index_monthly_serving','2026-11-10'),
    ('maintenance.update_index_weekly_serving','2026-11-09'),
])
def test_other_frequency_or_date_does_not_block_probe(env,other_target,other_day):
    session,_,_=env
    ready_daily(session,'week')
    rule=configure(session,'week')
    session.add(TaskRun(task_type='maintenance_action',resource_key=None,action='maintain',
        title='previous task',trigger_source='probe',schedule_id=rule.schedule_id,status='success',requested_at=NOW,
        time_input_json={'mode':'point','trade_date':other_day},
        request_payload_json={'target_type':'maintenance_action','target_key':other_target}))
    session.commit()
    tasks,_=ProbeRuntimeService().run_once(session,now=NOW)
    assert len(tasks)==1 and tasks[0].time_input_json['trade_date']=='2026-11-10'


def test_formal_weekly_raw_creates_independent_serving_after_commit_even_after_probe(env,mocker):
    session,worker,_=env
    day=date(2026,11,13)
    now=datetime(2026,11,13,19,10,tzinfo=SHANGHAI)
    set_probe_time(mocker,now)
    ready_daily(session,'week',day=day)
    rule=configure(session,'week')
    tasks,_=ProbeRuntimeService().run_once(session,now=now)
    assert len(tasks)==1
    early=worker.run_task_run(session,tasks[0].id)
    assert early.status=='success' and early.rows_saved==10
    assert all(r.source=='derived_daily' for r in session.scalars(select(IndexWeeklyServing)))
    # Confirmed Tushare field contract, artificial price literals; BSE has no formal row.
    source_mock(mocker,lambda period_end,_:[dict(ts_code=code,trade_date=period_end.strftime('%Y%m%d'),
        open=100,high=106,low=98,close=105,pre_close=100,change=5,pct_chg=.05,vol=700,amount=250000)
        for code in CODES if code!='899050.BJ'])
    schedule=session.scalar(select(OpsSchedule).where(OpsSchedule.target_key=='index_weekly.maintain'))
    due=datetime(2026,11,13,20,50,tzinfo=SHANGHAI)
    schedule.next_run_at=due
    session.commit()
    parent,=OperationsScheduleService().enqueue_due_schedules(session,now=due)
    result=worker.run_task_run(session,parent.id)
    assert result.status=='success' and result.rows_saved==9
    child=session.scalar(select(TaskRun).where(TaskRun.trigger_source=='system'))
    assert child is not None and child.schedule_id is None
    assert child.time_input_json=={'mode':'point','trade_date':'2026-11-13'}
    assert child.request_payload_json['target_key']=='maintenance.update_index_weekly_serving'
    assert session.scalar(select(func.count()).select_from(RawIndexWeeklyBar))==9
    result=worker.run_task_run(session,child.id)
    assert result.status=='success' and result.rows_saved==10
    rows=list(session.scalars(select(IndexWeeklyServing)))
    assert len(rows)==10 and sum(r.source=='api' for r in rows)==9
    assert next(r for r in rows if r.ts_code=='899050.BJ').source=='derived_daily'
    assert session.scalar(select(func.count()).select_from(ProbeRunLog).where(ProbeRunLog.condition_matched.is_(True)))==1
    assert session.scalar(select(ProbeRunLog.probed_at)).astimezone(SHANGHAI).date()==day
