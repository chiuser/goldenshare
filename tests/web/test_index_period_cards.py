"""Card contract on real project tables. Calendars/quotes below are explicit synthetic inputs.

November 2 / October 30 and April 30 / May 1 boundaries are independently verified
in index-period LLD §2.3 and §9.3; no expected value is calculated by the tested helper.
"""
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import insert, select, update, event
from sqlalchemy.exc import SQLAlchemyError

from src.foundation.ingestion.index_period_serving import SHANGHAI
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.queries.biz_table_card_query_service import BizTableCardQueryService
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.services.index_period_schedule import latest_index_period_occurrence
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot

NOW = datetime(2026, 11, 10, 22, 30, tzinfo=SHANGHAI)
DAY = date(2026, 11, 10)
CODES = ('000001.SH','399001.SZ','399006.SZ','000688.SH','000300.SH',
         '000905.SH','000852.SH','899050.BJ','000510.SH','000016.SH')


@pytest.fixture
def period_env(db_session, monkeypatch, request):
    options = getattr(request, 'param', {})
    for model in (RawIndexWeeklyBar, RawIndexMonthlyBar):
        model.__table__.create(db_session.get_bind(), checkfirst=True)
    start = date(2026, 4, 1)
    days = [start + timedelta(days=i) for i in range((date(2026, 11, 30)-start).days+1)]
    # Synthetic weekdays plus specifically declared holiday examples; not a downloaded calendar.
    closed = {date(2026, 5, 1), *(date(2026, 10, i) for i in range(1, 8))}
    db_session.execute(insert(TradeCalendar), [dict(exchange='SSE', trade_date=d, is_open=d.weekday()<5 and d not in closed)
        for d in days if d not in options.get('omit', ())])
    if not options.get('empty_pool'):
        db_session.execute(insert(IndexSeriesActive), [dict(resource='index_period_serving',ts_code=c,
            first_seen_date=DAY,last_seen_date=DAY,last_checked_at=NOW) for c in CODES])
    for frequency, model, first in (('weekly',IndexWeeklyServing,date(2026,11,9)),('monthly',IndexMonthlyServing,date(2026,11,2))):
        count = options.get('rows',10)
        db_session.execute(insert(model), [dict(ts_code=c,period_start_date=first,
            trade_date=DAY if i<options.get('updated',9) else date(2026,11,9), source='derived_daily',close=100)
            for i,c in enumerate(CODES[:count])])
        if options.get('outside'):
            db_session.execute(insert(model),dict(ts_code='000999.SH',period_start_date=first,trade_date=DAY,source='api',close=100))
    for frequency,model,end in (('weekly',RawIndexWeeklyBar,date(2026,11,6)),('monthly',RawIndexMonthlyBar,date(2026,10,30))):
        # Raw's production default is PostgreSQL now(); SQLite fixtures provide the same timestamp field explicitly.
        db_session.execute(insert(model), dict(ts_code=CODES[0],trade_date=end,api_name=f'index_{frequency}',close=100,fetched_at=NOW))
        if options.get('derived_only'):
            db_session.execute(update(model).values(api_name='derived_daily'))
        for serving in (False,True):
            if options.get('no_schedules'):
                continue
            db_session.add(OpsSchedule(target_type='maintenance_action' if serving else 'dataset_action',
                target_key=f'maintenance.update_index_{frequency}_serving' if serving else f'index_{frequency}.maintain',
                display_name=f'{frequency} {serving}',status='active',schedule_type='cron',trigger_mode='schedule',
                cron_expr='0 22 * * *' if serving else '0 19 * * *', timezone='Asia/Shanghai',
                calendar_policy='trading_day_point' if serving else
                    'weekly_last_trading_day' if frequency=='weekly' else 'monthly_first_trading_day'))
    db_session.commit()
    monkeypatch.setattr(BizTableCardQueryService,'_local_now',staticmethod(lambda:NOW))
    monkeypatch.setattr(OpsFreshnessQueryService,'_business_reference_now',staticmethod(lambda today=None,now=None:now or NOW))
    return db_session


def cards(app_client,user_factory,source):
    user_factory(username='admin',password='secret',is_admin=True)
    token=app_client.post('/api/v1/auth/login',json={'username':'admin','password':'secret'}).json()['token']
    response=app_client.get(f'/api/v1/ops/dataset-cards?source_key={source}',headers={'Authorization':f'Bearer {token}'})
    assert response.status_code==200
    return {c['card_key']:c for g in response.json()['groups'] for c in g['items']}


@pytest.mark.parametrize('policy,instant,expected',[
    ('monthly_first_trading_day',datetime(2026,11,2,18,59,tzinfo=SHANGHAI),date(2026,10,8)),
    ('monthly_first_trading_day',datetime(2026,11,2,19,0,tzinfo=SHANGHAI),date(2026,11,2)),
    ('weekly_last_trading_day',datetime(2026,11,13,18,59,tzinfo=SHANGHAI),date(2026,11,6)),
    ('weekly_last_trading_day',datetime(2026,11,13,19,0,tzinfo=SHANGHAI),date(2026,11,13)),
    ('weekly_last_trading_day',datetime(2026,4,30,19,0,tzinfo=SHANGHAI),date(2026,4,30)),
    ('trading_day_point',datetime(2026,11,9,18,59,tzinfo=SHANGHAI),date(2026,11,6)),
])
def test_recent_occurrence_uses_real_period_boundaries(period_env,policy,instant,expected):
    result=latest_index_period_occurrence(period_env,policy,time(19),instant)
    assert result.astimezone(SHANGHAI).date()==expected


@pytest.mark.parametrize('period_env,expected',[
    ({'updated':10},10), ({},9), ({'rows':1,'updated':1},1), ({'outside':True},9),
],indirect=['period_env'])
def test_serving_cards_use_full_pool_current_period_and_dates(period_env,app_client,user_factory,expected):
    result=cards(app_client,user_factory,'biz_tableset')
    for frequency in ('weekly','monthly'):
        card=result[f'index_{frequency}_serving']
        assert card['expected_business_date']=='2026-11-10'
        assert (card['updated_code_count'],card['expected_code_count'])==(expected,10)
        assert card['status']==('healthy' if expected==10 else 'warning')
        assert card['primary_action_key']==f'maintenance.update_index_{frequency}_serving'


@pytest.mark.parametrize('period_env', [{'empty_pool':True},{'omit':{date(2026,11,11)}}],indirect=True)
def test_missing_pool_or_calendar_cannot_report_healthy(period_env,app_client,user_factory):
    result=cards(app_client,user_factory,'biz_tableset')
    for frequency in ('weekly','monthly'):
        assert result[f'index_{frequency}_serving']['status']=='unknown'


def test_history_task_does_not_replace_current_coverage_or_hide_failure(period_env,app_client,user_factory):
    for frequency in ('weekly','monthly'):
        for target,when,status in (('2026-11-10',NOW,'failed'),('2026-10-30',NOW+timedelta(seconds=1),'success')):
            period_env.add(TaskRun(task_type='maintenance_action',resource_key=None,action='maintain',
                title='指数周期线',trigger_source='manual',status=status,requested_at=when,
                time_input_json={'mode':'point','trade_date':target},request_payload_json={'target_key':f'maintenance.update_index_{frequency}_serving'},rows_saved=9))
    period_env.commit()
    result=cards(app_client,user_factory,'biz_tableset')
    for frequency in ('weekly','monthly'):
        card=result[f'index_{frequency}_serving']
        assert card['expected_business_date']=='2026-11-10'
        assert card['updated_code_count']==9 and card['status']=='failed'
        assert card['latest_task_run']['status']=='success'
        assert card['latest_task_run']['time_scope']['start']=='2026-10-30'


@pytest.mark.parametrize('period_env,observed', [({},'2026-10-30'),({'derived_only':True},None)],indirect=['period_env'])
def test_raw_cards_use_formal_source_not_serving(period_env,app_client,user_factory,observed):
    result=cards(app_client,user_factory,'tushare')
    card=result['index_monthly']
    assert card['target_table']=='raw_tushare.index_monthly_bar'
    assert card['latest_business_date']==observed
    if observed is None:
        assert card['status']!='healthy' and card['freshness_status']!='fresh'
    assert card['expected_business_date']=='2026-10-30'
    assert card['updated_code_count'] is None
    assert result['index_weekly']['expected_business_date']=='2026-11-06'


def test_snapshot_rebuild_and_read_use_same_source_and_configured_time(period_env):
    service=OpsFreshnessQueryService()
    snapshots=DatasetStatusSnapshotService(service)
    assert snapshots.refresh_resources(period_env,['index_weekly','index_monthly'],strict=True)==2
    before=service.build_freshness(period_env,now=datetime(2026,11,2,18,59,tzinfo=SHANGHAI))
    after=service.build_freshness(period_env,now=datetime(2026,11,2,19,0,tzinfo=SHANGHAI))
    def monthly(response):
        return next(c for g in response.groups for c in g.items if c.dataset_key=='index_monthly')
    assert monthly(before).expected_business_date==date(2026,9,30)
    assert monthly(after).expected_business_date==date(2026,10,30)
    row=period_env.get(DatasetStatusSnapshot,'index_monthly')
    row.target_table='core_serving.index_monthly_serving'
    period_env.commit()
    old=monthly(service.build_freshness(period_env))
    assert old.latest_business_date is None and old.freshness_status=='unconfirmed'


def test_snapshot_write_failure_keeps_committed_serving(period_env,monkeypatch):
    def fail(*args,**kwargs):
        raise SQLAlchemyError('injected status write failure')
    monkeypatch.setattr(DatasetStatusSnapshotService,'_upsert_items',fail)
    assert DatasetStatusSnapshotService().refresh_resources(period_env,['index_weekly'])==0
    assert len(period_env.scalars(select(IndexWeeklyServing)).all())==10


@pytest.mark.parametrize('period_env',[{'no_schedules':True}],indirect=True)
def test_no_schedule_has_no_invented_due_date(period_env,app_client,user_factory):
    result=cards(app_client,user_factory,'biz_tableset')
    for frequency in ('weekly','monthly'):
        card=result[f'index_{frequency}_serving']
        assert card['expected_business_date'] is None
        assert card['updated_code_count'] is None
        assert card['status']=='unknown'
    live=OpsFreshnessQueryService().build_live_items(period_env,resource_keys=['index_weekly','index_monthly'])
    assert all(c.expected_business_date is None and c.freshness_status=='unconfirmed' for c in live)


def test_coverage_reads_one_period_and_pool_only_and_isolates_query_failure(period_env,app_client,user_factory):
    statements=[]
    def observe(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('SELECT') and any(f'FROM {model.__table__.fullname}' in statement for model in (IndexWeeklyServing,IndexMonthlyServing)):
            statements.append(statement)
        if statement.startswith('SELECT') and 'core_serving.index_weekly_serving' in statement:
            raise SQLAlchemyError('injected weekly coverage read failure')
    bind=period_env.get_bind()
    event.listen(bind,'before_cursor_execute',observe)
    try:
        result=cards(app_client,user_factory,'biz_tableset')
    finally:
        event.remove(bind,'before_cursor_execute',observe)
    assert result['index_weekly_serving']['status']=='unknown'
    assert result['index_monthly_serving']['updated_code_count']==9
    assert len(statements)==2
    assert all('period_start_date =' in sql and 'ts_code IN' in sql for sql in statements)
