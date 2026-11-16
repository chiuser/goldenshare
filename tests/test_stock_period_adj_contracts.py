"""Independent source literals and LLD 13.4/13.5/13.23/13.24 boundary cases."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.datasets.stock_period_adj_contracts import (
    SOURCE_FIELDS, READINESS_FIELDS, StockPeriodAdjContractError, StockPeriodAdjExecutionPolicy,
    normalize_rows, select_serving, validate_response,
)
from src.foundation.ingestion.stock_period_adj_execution import PeriodControl, capture
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot


def source_sample():
    # Real MCP output, captured independently of the new normalizer/publisher.
    return json.loads((Path(__file__).parent/'fixtures/stock_period_adj_month_202002.json').read_text(), parse_float=Decimal)


def literal_rows():
    rows = source_sample()['rows']
    for row in rows:
        for key in ('trade_date','end_date'):
            text = row[key]
            row[key] = date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return rows


def test_real_field_order_and_complete_numeric_contract():
    expected = ('ts_code','trade_date','end_date','freq','open','high','low','close','pre_close',
        'open_qfq','high_qfq','low_qfq','close_qfq','open_hfq','high_hfq','low_hfq','close_hfq','vol','amount','change','pct_chg')
    assert tuple(source_sample()['provenance']['fields']) == expected
    assert SOURCE_FIELDS == expected
    rows = normalize_rows(source_sample()['rows'], freq='month', policy=StockPeriodAdjExecutionPolicy())
    assert rows[0]['close_qfq'] == Decimal('11.14')
    assert rows[1]['close_qfq'] == Decimal('12.01')
    assert rows[0]['open_hfq'] == Decimal('1527.27')
    assert rows[1]['open_hfq'] == Decimal('1527.28')


def test_latest_whole_row_is_selected_and_original_dates_retained():
    rows = literal_rows()
    chosen = select_serving(rows, 'month')
    assert len(rows) == 2 and len(chosen) == 1
    assert chosen[0] == rows[0]
    assert chosen[0]['trade_date'] == date(2020,2,29)
    assert chosen[0]['close_qfq'] == Decimal('11.14')
    assert chosen[0]['open_hfq'] == Decimal('1527.27')


def test_newer_28th_wins_without_being_renamed_to_month_end():
    rows = literal_rows()
    rows[1]['end_date'] = date(2026,11,14)  # intentional normal later platform delivery
    chosen = select_serving(rows, 'month')
    assert chosen == [rows[1]]
    assert chosen[0]['trade_date'] == date(2020,2,28)
    assert chosen[0]['close_qfq'] == Decimal('12.01')


def test_equal_latest_identical_business_values_use_later_source_date():
    rows = literal_rows()
    rows[1] = {**rows[0], 'trade_date': date(2020,2,28)}
    assert select_serving(rows, 'month') == [rows[0]]


@pytest.mark.parametrize('field,value', [('close_qfq',Decimal('9')),('vol',None)])
def test_equal_latest_business_conflict_and_null_difference_fail(field,value):
    rows = literal_rows()
    rows[1] = {**rows[0], 'trade_date': date(2020,2,28), field: value}
    with pytest.raises(StockPeriodAdjContractError, match='最新计算截至日期'):
        select_serving(rows, 'month')


def test_old_null_candidate_does_not_defeat_valid_latest_but_null_only_fails():
    rows = literal_rows()
    rows[1]['end_date'] = None
    assert select_serving(rows, 'month') == [rows[0]]
    with pytest.raises(StockPeriodAdjContractError):
        select_serving([rows[1]], 'month')


@pytest.mark.parametrize('mutation', ['missing','extra','duplicate','width','wrong_freq','bad_date','float','precision'])
def test_formal_source_schema_cannot_be_silently_repaired(mutation):
    sample = source_sample()
    fields = list(sample['provenance']['fields'])
    row = deepcopy(sample['rows'][0])
    if mutation == 'wrong_freq': row['freq'] = 'week'
    if mutation == 'bad_date': row['end_date'] = ''
    if mutation == 'float': row['close'] = 1.1
    if mutation == 'precision': row['close'] = Decimal('1.00001')
    items = [[row[key] for key in fields]]
    if mutation == 'missing': fields.pop(); items[0].pop()
    if mutation == 'extra': fields.append('unexpected'); items[0].append(1)
    if mutation == 'duplicate': fields[-1] = fields[0]
    if mutation == 'width': items[0].pop()
    with pytest.raises(StockPeriodAdjContractError):
        validate_response({'data':{'fields':fields,'items':items}},freq='month')


def test_three_field_readiness_has_its_own_contract():
    response = {'data':{'fields':['ts_code','trade_date','end_date'],
        'items':[['000001.SZ','20261130','20261113']]}}
    rows = validate_response(response,freq='month',readiness=True)
    assert rows == [{'ts_code':'000001.SZ','trade_date':date(2026,11,30),'end_date':date(2026,11,13)}]
    with pytest.raises(StockPeriodAdjContractError):
        validate_response(response,freq='month')


@pytest.mark.parametrize('key', ['stk_period_bar_adj_week','stk_period_bar_adj_month'])
def test_definitions_share_the_named_contract_but_keep_original_time_buckets(key):
    definition = get_dataset_definition(key)
    policy = definition.planning.stock_period_adj_policy
    assert policy == StockPeriodAdjExecutionPolicy()
    assert definition.planning.weekly_adj_policy is None
    assert definition.source.source_fields == SOURCE_FIELDS
    assert definition.planning.page_limit == 6000
    assert definition.planning.max_source_rows_per_unit == 12000
    assert definition.planning.max_units_per_execution == 1000
    assert definition.date_model.bucket_rule == ('week_friday' if key.endswith('week') else 'month_last_calendar_day')
    assert policy.maintenance_intents == ('period','current_period')
    assert not hasattr(policy,'memory_target_bytes')


def test_current_coverage_accepts_later_execution_date_and_optional_suspension(monkeypatch):
    from types import SimpleNamespace
    import src.foundation.ingestion.stock_period_adj_execution as module
    monkeypatch.setattr(module,'today',lambda:date(2026,11,16))
    unit = PlanUnitSnapshot(unit_id='current',dataset_key='stk_period_bar_adj_month',source_key='tushare',
        trade_date=date(2026,11,30),request_params={'freq':'month','trade_date':'20261130'},
        progress_context={'purpose':'current_period','eligible_codes':['000001.SZ','600000.SH'], 'required_dates':{'000001.SZ':'2026-11-09'}})
    rows = [{**literal_rows()[0], 'trade_date':date(2026,11,30),'end_date':date(2026,11,10)}]
    class Client:
        def iter_stock_period_adj_pages(self,**kwargs):
            yield SimpleNamespace(rows_raw=rows)
    actual,counts = capture(SimpleNamespace(source_client=Client()),get_dataset_definition(unit.dataset_key),unit,
        PeriodControl(lambda:None,lambda *args:None))
    assert actual[0]['end_date'] == date(2026,11,10)
    assert counts['admitted'] == 1
    rows[0]['end_date'] = date(2026,11,6)
    with pytest.raises(StockPeriodAdjContractError,match='未达到'):
        capture(SimpleNamespace(source_client=Client()),get_dataset_definition(unit.dataset_key),unit,
            PeriodControl(lambda:None,lambda *args:None))
    rows[0]['end_date'] = date(2026,11,17)
    with pytest.raises(StockPeriodAdjContractError,match='越界'):
        capture(SimpleNamespace(source_client=Client()),get_dataset_definition(unit.dataset_key),unit,
            PeriodControl(lambda:None,lambda *args:None))


@pytest.mark.parametrize('case',['missing','same_count_wrong_code','duplicate'])
def test_coverage_checks_codes_not_only_counts(case):
    from types import SimpleNamespace
    unit = PlanUnitSnapshot(unit_id='period',dataset_key='stk_period_bar_adj_month',source_key='tushare',
        trade_date=date(2020,2,29),request_params={},progress_context={'purpose':'current_period','eligible_codes':['000001.SZ'],
            'required_dates':{'000001.SZ':'2020-02-28'}})
    rows = literal_rows()[:1]
    if case == 'missing': rows = []
    if case == 'same_count_wrong_code': rows[0]['ts_code'] = '600000.SH'
    if case == 'duplicate': rows = rows + deepcopy(rows)
    class Client:
        def iter_stock_period_adj_pages(self,**kwargs):
            yield SimpleNamespace(rows_raw=rows)
    with pytest.raises(StockPeriodAdjContractError):
        capture(SimpleNamespace(source_client=Client()),get_dataset_definition(unit.dataset_key),unit,
            PeriodControl(lambda:None,lambda *args:None))


def test_frontend_fixture_is_the_actual_manual_action_contract():
    from src.ops.queries.manual_action_query_service import ManualActionQueryService
    fixture=json.loads(Path('frontend/src/test/fixtures/stock-period-manual-actions.json').read_text())
    actual=ManualActionQueryService().build_manual_actions().model_dump(mode='json')
    expected={a['action_key']:a for g in actual['groups'] for a in g['actions']}
    for group in fixture['groups']:
        for action in group['actions']:
            assert action==expected[action['action_key']]
            assert [i['kind'] for i in action['maintenance_intents']]==['period','current_period']


@pytest.mark.parametrize('readiness',[False,True])
def test_real_pager_limits_offsets_empty_terminal_page_and_request_contract(monkeypatch,readiness):
    from types import SimpleNamespace
    import src.foundation.ingestion.source_client as module
    definition=get_dataset_definition('stk_period_bar_adj_month')
    policy=definition.planning.stock_period_adj_policy
    calls=[]
    def bounded(**kw):
        calls.append(kw)
        return [None]*6000 if len(calls)<=2 else []
    monkeypatch.setattr(module,'create_source_connector',lambda source:SimpleNamespace(call_bounded=bounded))
    unit=PlanUnitSnapshot(unit_id='pager',dataset_key=definition.dataset_key,source_key='tushare',trade_date=date(2026,11,30),
        request_params={'freq':'month','trade_date':'20261130'},progress_context={})
    checks=[]
    control=PeriodControl(lambda:checks.append(1),lambda *a:None)
    pages=list(module.DatasetSourceClient().iter_stock_period_adj_pages(definition=definition,unit=unit,control=control,readiness=readiness))
    assert [c['params']['offset'] for c in calls]==[0,6000,12000]
    assert all(c['params']['limit']==6000 and c['timeout']==20 for c in calls)
    assert all(tuple(c['fields'])==(READINESS_FIELDS if readiness else SOURCE_FIELDS) for c in calls)
    assert all(c['response_contract']==('stock_period_adj_readiness/v1' if readiness else 'stock_period_adj/v1') for c in calls)
    assert [len(p.rows_raw) for p in pages]==[6000,6000,0]
    assert pages[-1].is_short_page and len(checks)==6


def test_pager_does_not_accept_truncation_or_retry_failure(monkeypatch):
    from types import SimpleNamespace
    import src.foundation.ingestion.source_client as module
    from src.foundation.clients.bounded_tushare_call import BoundedTushareError
    definition=get_dataset_definition('stk_period_bar_adj_month')
    unit=PlanUnitSnapshot(unit_id='pager',dataset_key=definition.dataset_key,source_key='tushare',trade_date=date(2026,11,30),request_params={'freq':'month'},progress_context={})
    calls=[]
    def full(**kw): calls.append(kw); return [None]*6000
    monkeypatch.setattr(module,'create_source_connector',lambda source:SimpleNamespace(call_bounded=full))
    with pytest.raises(StockPeriodAdjContractError,match='行数限制'):
        list(module.DatasetSourceClient().iter_stock_period_adj_pages(definition=definition,unit=unit,control=PeriodControl(lambda:None,lambda *a:None)))
    assert len(calls)==3
    calls.clear()
    def timeout(**kw): calls.append(kw); raise BoundedTushareError('stock_period_adj.source_deadline_exceeded','deadline')
    monkeypatch.setattr(module,'create_source_connector',lambda source:SimpleNamespace(call_bounded=timeout))
    with pytest.raises(StockPeriodAdjContractError,match='deadline'):
        list(module.DatasetSourceClient().iter_stock_period_adj_pages(definition=definition,unit=unit,control=PeriodControl(lambda:None,lambda *a:None)))
    assert len(calls)==1


def test_task_progress_display_keeps_stage_business_day_update_and_unknown_eta():
    from src.ops.queries.task_run_query_service import TaskRunQueryService
    displayed=TaskRunQueryService._display_current_object({'entity':{'code':'000001.SZ','kind':'stock'},
        'time':{'trade_date':'2026-11-30','business_date':'2026-11-13'},
        'attributes':{'stage':'下载源行情','updated_at':'2026-11-13T12:00:05+00:00','eta':'暂无法估算'}},status='running')
    assert '000001.SZ' in displayed.title
    assert all(text in displayed.description for text in ['下载源行情','2026-11-13','12:00:05','暂无法估算'])


def test_frontend_automation_fixture_matches_real_catalog_producer():
    from src.ops.queries.catalog_query_service import OpsCatalogQueryService
    from src.ops.services.schedule_automation_capability_resolver import ScheduleAutomationCapabilityResolver
    fixture=json.loads(Path('frontend/src/test/fixtures/stock-period-automation-catalog.json').read_text())
    service=OpsCatalogQueryService(); resolver=ScheduleAutomationCapabilityResolver()
    expected=[service._build_dataset_action_catalog_item(get_dataset_definition('stk_period_bar_adj_'+freq),{},resolver).model_dump(mode='json') for freq in ['week','month']]
    assert fixture=={'actions':expected,'workflows':[]}
