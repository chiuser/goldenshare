"""Resolver-owned period dates and durable original scope; no Ops imports."""

from dataclasses import asdict
from datetime import timedelta
import json
from uuid import uuid4

from sqlalchemy import select

from src.foundation.dao.stock_period_adj_delivery_dao import StockPeriodAdjDeliveryDAO
from src.foundation.datasets.stock_period_adj_contracts import (
    SOURCE_FIELDS, StockPeriodAdjContractError, canonical_json, check_size, digest, frequency, parse_day, period_date,
)
from src.foundation.ingestion.execution_plan import DatasetTimeInput, PlanUnitSnapshot
from src.foundation.ingestion.stock_period_adj_inputs import open_days, period_inputs, today
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj


def validate_intent(request, definition):
    kind = (request.maintenance_intent or {}).get('kind', 'period')
    time = request.time_input
    if kind not in {'period', 'current_period'}:
        raise StockPeriodAdjContractError('本阶段尚未开放该维护用途', 'source_scope_invalid')
    if request.maintenance_intent is not None and set(request.maintenance_intent) != {'kind'}:
        raise StockPeriodAdjContractError('当前用途不接受额外维护范围', 'source_scope_invalid')
    if kind == 'current_period':
        other = [getattr(time, key) for key in ('trade_date','start_date','end_date','month','start_month','end_month','ann_date')]
        if time.mode != 'point' or time.business_date is None or time.date_field not in {None,'business_date'} or any(value is not None for value in other) or request.filters:
            raise StockPeriodAdjContractError('当前周期更新只接受业务交易日，不接受周期日期、区间或股票过滤', 'source_scope_invalid')
        if time.business_date > today():
            raise StockPeriodAdjContractError('业务交易日不得晚于上海当天', 'source_scope_invalid')
    elif time.business_date is not None:
        raise StockPeriodAdjContractError('指定周期维护不能混入业务交易日', 'source_scope_invalid')
    return kind


def resolve_units(session, request, definition, *, check=lambda: None, report=lambda current, total: None, persist=False):
    policy = definition.planning.stock_period_adj_policy
    kind = validate_intent(request, definition)
    freq = frequency(definition)
    previous = (request.execution_context or {}).get('stock_period_adj')
    if previous:
        return request, restore_units(session, definition, previous), previous
    auto = request.trigger_source in {'probe', 'schedule', 'scheduled'}
    identity = request.time_input.business_date.isoformat() if auto and kind == 'current_period' else str(request.run_id or uuid4())
    intent_key = (request.execution_context or {}).get('stock_period_adj_original_intent_key') or f'{kind}:{freq}:{identity}'
    existing = StockPeriodAdjDeliveryDAO(session).frozen_intent(intent_key)
    if existing:
        context = existing.payload['context']
        return request, restore_units(session, definition, context), context
    if kind == 'current_period':
        days = [request.time_input.business_date]
        periods = [period_date(days[0], freq)]
    else:
        time = request.time_input
        if time.mode == 'point':
            periods = [time.trade_date]
        elif time.mode == 'range' and time.start_date and time.end_date and time.start_date <= time.end_date:
            periods = []
            cursor = time.start_date
            while cursor <= time.end_date:
                check()
                if period_date(cursor, freq) == cursor:
                    periods.append(cursor)
                    if len(periods) > policy.max_units:
                        raise StockPeriodAdjContractError('计划单元数超限', 'plan_budget_exceeded')
                cursor += timedelta(days=1)
        else:
            raise StockPeriodAdjContractError('指定周期维护必须提供原point/range范围', 'source_scope_invalid')
        if not periods or any(day is None or period_date(day, freq) != day or day > today() for day in periods):
            raise StockPeriodAdjContractError('指定周期日期须为已结束的周五或自然月末', 'source_scope_invalid')
        days = []
        for point in periods:
            from src.foundation.datasets.stock_period_adj_contracts import period_start
            available = open_days(session, period_start(point, freq), point)
            if not available:
                raise StockPeriodAdjContractError(f'{point}周期没有可用开市日', 'input_not_ready')
            days.append(available[-1])
    if len(periods) > policy.max_units:
        raise StockPeriodAdjContractError('计划单元数超限', 'plan_budget_exceeded')
    code = request.filters.get('ts_code')
    if code:
        code = code.strip().upper()
    if set(request.filters) - {'ts_code'}:
        raise StockPeriodAdjContractError('本数据集不支持这些过滤字段', 'source_scope_invalid')
    context = {'contract_version': policy.contract_version, 'batch_id': str(uuid4()), 'purpose': kind, 'freq': freq,
        'business_date': request.time_input.business_date.isoformat() if kind == 'current_period' else None,
        'period_date': periods[0].isoformat() if len(periods) == 1 else None,
        'intent_key': intent_key, 'contract_digest': digest(SOURCE_FIELDS),
        'scope_digest': digest({'purpose': kind, 'freq': freq, 'periods': periods, 'code': code}),
        'policy': asdict(policy), 'policy_digest': digest(asdict(policy)), 'plan_revision': 1, 'upstream_revisions': []}
    units = []
    descriptions = []
    for day, point in zip(days, periods):
        check()
        if code and session.scalar(select(RawStkPeriodBarAdj.ts_code).where(RawStkPeriodBarAdj.freq == freq,
                RawStkPeriodBarAdj.trade_date == point).limit(1)) is None:
            raise StockPeriodAdjContractError('单股修订不能创建完整全市场周期', 'source_scope_invalid')
        inputs = period_inputs(session, day=day, freq=freq, selected_code=code, closed_period=kind == 'period')
        # Builder owns source parameter formatting; planner only decides P and scope.
        from src.foundation.ingestion import request_builders
        from types import SimpleNamespace
        builder = getattr(request_builders, definition.source.request_builder_key)
        params = builder(SimpleNamespace(run_profile='point_incremental', trade_date=point, params={'ts_code': code}), point, {})
        units.append(PlanUnitSnapshot(unit_id=f'{kind}:{freq}:{point.isoformat()}', dataset_key=definition.dataset_key,
            source_key=definition.source.source_key_default, trade_date=point, request_params=params,
            progress_context={'purpose': kind, 'business_date': day.isoformat(), 'period_date': point.isoformat(), **inputs},
            pagination_policy='offset_limit', page_limit=policy.page_limit, max_source_rows_per_unit=policy.max_rows_per_unit))
        descriptions.append(unit_payload(units[-1]))
        check_size(descriptions, policy.max_plan_bytes, 'plan_budget_exceeded')
        if persist:
            from sqlalchemy.orm import Session
            from src.foundation.ingestion.stock_period_adj_delivery import bounded_transaction
            with Session(session.get_bind()) as store:
                with bounded_transaction(store, policy, check):
                    StockPeriodAdjDeliveryDAO(store).append(record(context, 'plan_unit', units[-1].unit_id,
                        descriptions[-1], period=point, code=code), policy)
                    store.commit()
        report(point.isoformat(), len(periods))
    context['input_digest'] = digest([u.progress_context['input_digest'] for u in units])
    if persist:
        freeze_plan(session.get_bind(), context, units, policy, check)
    return request, tuple(units), context


def unit_payload(unit):
    return json.loads(canonical_json(asdict(unit)))


def unit_from_payload(payload):
    values = dict(payload)
    values['trade_date'] = parse_day(values['trade_date']) if values['trade_date'] else None
    values['request_variants'] = tuple(values.get('request_variants', ()))
    return PlanUnitSnapshot(**values)


def record(context, kind, unit_id, payload, *, period=None, code=None):
    return {'contract_version': context['contract_version'], 'batch_id': context['batch_id'],
        'intent_key': context['intent_key'], 'record_kind': kind, 'unit_id': unit_id,
        'purpose': context['purpose'], 'freq': context['freq'],
        'business_date': parse_day(context['business_date']) if context['business_date'] else None,
        'period_date': period, 'ts_code': code, 'contract_digest': context['contract_digest'],
        'scope_digest': context['scope_digest'], 'payload': payload}


def freeze_plan(engine, context, units, policy, check):
    from sqlalchemy.orm import Session
    from src.foundation.ingestion.stock_period_adj_delivery import bounded_transaction
    check()
    with Session(engine) as store:
        with bounded_transaction(store, policy, check):
            dao = StockPeriodAdjDeliveryDAO(store)
            for unit in units:
                check()
                dao.append(record(context, 'plan_unit', unit.unit_id, unit_payload(unit),
                    period=unit.trade_date, code=unit.request_params.get('ts_code')), policy)
            header = {'context': context, 'unit_count': len(units),
                      'unit_digests': [digest(unit_payload(unit)) for unit in sorted(units, key=lambda u: u.unit_id)]}
            dao.append(record(context, 'plan_frozen', 'plan_frozen', header), policy)
            check()
            store.commit()


def restore_units(session, definition, context):
    from src.foundation.datasets.stock_period_adj_contracts import StockPeriodAdjExecutionPolicy
    if context['contract_version'] != StockPeriodAdjExecutionPolicy().contract_version or context['freq'] != frequency(definition):
        raise StockPeriodAdjContractError('恢复合同/频率不匹配', 'resume_contract_mismatch')
    dao = StockPeriodAdjDeliveryDAO(session)
    frozen = dao.get(context['batch_id'], 'plan_frozen', 'plan_frozen')
    if frozen is None or frozen.payload['context'] != context:
        raise StockPeriodAdjContractError('恢复缺少原冻结计划', 'resume_contract_mismatch')
    units = []
    after = ''
    while True:
        rows = dao.units(context['batch_id'], after=after)
        if not rows:
            break
        units.extend(unit_from_payload(row.payload) for row in rows)
        after = rows[-1].unit_id
    if [digest(unit_payload(unit)) for unit in units] != frozen.payload['unit_digests']:
        raise StockPeriodAdjContractError('原冻结范围摘要不匹配', 'resume_contract_mismatch')
    return tuple(units)
