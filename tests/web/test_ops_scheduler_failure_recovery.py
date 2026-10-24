"""Prod incident: Ops scheduled must reach the weekly schedule contract.

Dates/source values below are independent literal fixtures, using current production
models and Definition. All database effects are isolated SQLite; no source calls.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from src.app.exceptions import WebAppError
from src.foundation.datasets.stock_weekly_adj_contracts import SOURCE_FIELDS
from src.foundation.ingestion import DatasetActionResolver
from src.foundation.models.core.stock_weekly_adj_delivery import StockWeeklyAdjDelivery
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj
from src.ops.models.ops.task_run import TaskRun
from src.ops.runtime import TaskRunDispatcher
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.task_run_service import TaskRunCommandService

NOW = datetime(2026, 10, 22, 9, tzinfo=timezone.utc)  # Thursday 17:00 Shanghai
DUE = datetime(2026, 10, 21, 14, 4, tzinfo=timezone.utc)
WEEKLY = 'stk_period_bar_adj_week'


def seed_weekly(session):
    """Real producer schemas; one stock, prior Fri + five open days, constant factor.

    bootstrap_closed is a literal durable frontier fixture, not a publication test.
    Expected automatic work is independently one market week, no changed stocks.
    """
    for model in (StockWeeklyAdjDelivery, EquityAdjFactor, EquityDailyBar, RawStkPeriodBarAdj):
        model.__table__.create(session.get_bind(), checkfirst=True)
    for day in (date(2026, 10, 9), *(date(2026, 10, n) for n in range(12, 17))):
        session.add(TradeCalendar(exchange='SSE', trade_date=day, is_open=True))
        session.add(EquityDailyBar(ts_code='000001.SZ', trade_date=day, close=Decimal('10'), source='tushare'))
        session.add(EquityAdjFactor(ts_code='000001.SZ', trade_date=day, adj_factor=Decimal('1')))
    session.add(RawStkPeriodBarAdj(**{
        **dict.fromkeys(SOURCE_FIELDS, Decimal('1')),
        'ts_code': '000001.SZ', 'trade_date': date(2026, 10, 9),
        'end_date': date(2026, 10, 9), 'freq': 'week', 'fetched_at': NOW,
    }))
    session.add(StockWeeklyAdjDelivery(
        contract_version=1, batch_id=UUID('00000000-0000-0000-0000-000000000001'),
        unit_id='bootstrap_closed', record_kind='bootstrap_closed', intent={},
        cutoff_week=date(2026, 10, 9), factor_scan_end=date(2026, 10, 9),
        outcome='published', payload={}, published_at=NOW, rows_received=0, rows_unique=0,
        rows_written=0, rows_preserved=0, payload_digest='0'*64,
        scope_digest='0'*64, reason_summary={},
    ))
    session.commit()


def weekly_schedule(factory):
    # Mirrors production schedule 14's target, policy and Ops trigger source.
    return factory(target_key=f'{WEEKLY}.maintain', schedule_type='cron',
                   cron_expr='4 22 * * *', next_run_at=DUE,
                   calendar_policy='latest_completed_calendar_week',
                   params_json={'time_input': {'mode': 'point'}, 'filters': {}})


def test_real_scheduler_weekly_creation_preflight_and_worker_request(db_session, ops_schedule_factory):
    seed_weekly(db_session)
    schedule = weekly_schedule(ops_schedule_factory)
    created = OperationsScheduleService().enqueue_due_schedules(db_session, now=NOW)
    assert len(created) == 1, 'normal automatic weekly task must not be rejected'
    task = created[0]
    assert task.trigger_source == 'scheduled'  # existing Ops/API/UI contract
    frozen = task.request_payload_json['execution_context']
    assert frozen['trigger_source'] == 'schedule'
    assert frozen['intent'] == 'scheduled_week'
    request = TaskRunDispatcher()._build_dataset_action_request(task)
    assert request.trigger_source == 'schedule'
    plan = DatasetActionResolver(db_session).build_plan(request)
    assert plan.execution_context['execution_token'] == frozen['execution_token']
    assert plan.execution_context['intent'] == 'scheduled_week'
    assert len(plan.units) == 1
    assert plan.units[0].request_params == {'freq': 'week', 'trade_date': '20261016'}
    context = TaskRunCommandService().build_schedule_task_context(
        db_session, target_type='dataset_action', target_key=f'{WEEKLY}.maintain',
        params_json={'time_input': {'mode': 'point'}, 'filters': {}},
        trigger_source='scheduled', requested_by_user_id=None, schedule_id=schedule.id,
        calendar_policy='latest_completed_calendar_week', scheduled_at=DUE,
        timezone_name='Asia/Shanghai',
    )
    TaskRunCommandService.preflight_dataset_context(db_session, context=context)
    assert db_session.get(type(schedule), schedule.id).next_run_at > DUE.replace(tzinfo=None)


def test_unmapped_prod_source_reproduces_original_weekly_failure(db_session, ops_schedule_factory, monkeypatch):
    seed_weekly(db_session)
    weekly_schedule(ops_schedule_factory)
    # Reproduce the pre-fix exact boundary: Ops source passed through unchanged.
    # Keep the actual scheduler, command, resolver and weekly guard in the path.
    monkeypatch.setattr('src.ops.services.task_run_service.dataset_action_trigger_source', lambda key, source: source)
    with pytest.raises(WebAppError, match='周线触发来源无效'):
        OperationsScheduleService().enqueue_due_schedules(db_session, now=NOW)
    db_session.rollback()
    assert list(db_session.scalars(select(TaskRun))) == []


def test_all_other_dataset_sources_and_worker_inputs_unchanged():
    from src.foundation.datasets.registry import list_dataset_definitions
    from src.ops.services.dataset_action_request_adapter import dataset_action_trigger_source
    definitions = [d for d in list_dataset_definitions() if d.planning.weekly_adj_policy is None]
    assert {d.dataset_key for d in definitions} == {d.dataset_key for d in list_dataset_definitions()} - {WEEKLY}
    for definition in definitions:
        for source in ('scheduled', 'manual', 'retry', 'probe', 'system', 'workflow'):
            assert dataset_action_trigger_source(definition.dataset_key, source) == source
            request = TaskRunDispatcher()._build_dataset_action_request(TaskRun(
                id=1, resource_key=definition.dataset_key, action='maintain',
                trigger_source=source, time_input_json={'mode': 'none'}, filters_json={},
                request_payload_json={},
            ))
            assert request.dataset_key == definition.dataset_key
            assert request.trigger_source == source
            assert request.filters == {} and request.time_input.mode == 'none'


@pytest.mark.parametrize('source,expected', [
    ('scheduled','schedule'), ('schedule','schedule'), ('manual','manual'),
    ('retry','retry'), ('probe','probe'), ('system','system'), ('typo','typo'),
])
def test_weekly_mapping_only_changes_ops_automatic_source(source, expected):
    from src.ops.services.dataset_action_request_adapter import dataset_action_trigger_source
    assert dataset_action_trigger_source(WEEKLY, source) == expected


@pytest.mark.parametrize('source', ['probe', 'system', 'typo', 'scheduled'])
def test_weekly_contract_still_rejects_invalid_or_unadapted_source(source):
    from src.foundation.datasets.registry import get_dataset_definition
    from src.foundation.datasets.stock_weekly_adj_contracts import WeeklyAdjContractError
    from src.foundation.ingestion.stock_weekly_adj_scope import freeze_weekly_adj_execution
    with pytest.raises(WeeklyAdjContractError, match='周线触发来源无效'):
        freeze_weekly_adj_execution(get_dataset_definition(WEEKLY),
            scope={'mode':'point', 'start':'2026-10-16', 'end':'2026-10-16'},
            filters={}, trigger_source=source)


def test_weekly_retry_keeps_original_frozen_automatic_intent(db_session, ops_schedule_factory):
    seed_weekly(db_session)
    weekly_schedule(ops_schedule_factory)
    original = OperationsScheduleService().enqueue_due_schedules(db_session, now=NOW)[0]
    original.status = 'failed'
    db_session.commit()
    frozen = original.request_payload_json['execution_context']
    retried = TaskRunCommandService().retry_task_run(db_session, task_run_id=original.id, requested_by_user_id=1)
    assert retried.trigger_source == 'retry'
    resumed = retried.request_payload_json['execution_context']
    assert resumed['execution_token'] == frozen['execution_token']
    assert resumed['intent'] == 'scheduled_week' and resumed['trigger_source'] == 'schedule'
    plan = DatasetActionResolver(db_session).build_plan(TaskRunDispatcher()._build_dataset_action_request(retried))
    assert plan.execution_context['execution_token'] == frozen['execution_token']
    assert plan.execution_context['intent'] == 'scheduled_week'
