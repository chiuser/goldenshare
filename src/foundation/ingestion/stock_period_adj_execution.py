"""Bounded current-period capture, independent commits and original-plan resume."""

from collections import Counter
from dataclasses import replace
from datetime import datetime, UTC
import logging
import time

from sqlalchemy.orm import Session

from src.foundation.dao.stock_period_adj_delivery_dao import StockPeriodAdjDeliveryDAO
from src.foundation.datasets.stock_period_adj_contracts import (
    ROW_BLOCK_SIZE, StockPeriodAdjContractError, StockPeriodAdjExecutionPolicy, frequency, normalize_rows, parse_day, period_start,
)
from src.foundation.ingestion.errors import IngestionWriteError, StructuredError
from src.foundation.ingestion.progress import ProgressSnapshot
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.stock_period_adj_delivery import bounded_transaction, publish_unit
from src.foundation.ingestion.stock_period_adj_inputs import today
from src.foundation.ingestion.stock_period_adj_planning import freeze_plan, record, restore_units


class PeriodControl:
    def __init__(self, check, emit, poll=None):
        self.check = check
        self.emit = emit
        self.poll = poll or check
        self.page_number = 0
        self.offset = 0

    def fetching(self, page_number, offset):
        self.page_number, self.offset = page_number, offset
        self.emit('下载源行情', True)

    def tick(self):
        self.emit('下载源行情', False)


def capture(executor, definition, unit, control, *, readiness=False):
    policy = definition.planning.stock_period_adj_policy
    rows = []
    pages = 0
    for page in executor.source_client.iter_stock_period_adj_pages(definition=definition, unit=unit,
            control=control, readiness=readiness):
        control.check()
        rows.extend(page.rows_raw)
        normalize_rows(rows, freq=frequency(definition), policy=policy, readiness=readiness)
        pages += 1
    normalized = normalize_rows(rows, freq=frequency(definition), policy=policy, readiness=readiness)
    current_period = unit.progress_context['purpose'] == 'current_period'
    if not current_period:
        normalized = list({(row['ts_code'], row['trade_date']): row for row in normalized}.values())
    if unit.progress_context['purpose'] in {'factor_history','stock_history','stock_history_and_remove'}:
        code = unit.progress_context['ts_code']
        for row in normalized:
            control.poll()
            if row['ts_code'] != code or row['end_date'] > today():
                raise StockPeriodAdjContractError(f'{code}完整历史返回其他股票或未来截至日期', 'source_scope_invalid')
        return normalized, {'source_received':len(rows), 'source_unique':len(normalized), 'admitted':len(normalized),
            'excluded_not_admitted':0, 'pages':pages, 'terminal_short_page':True, 'admission_excluded_reasons':{}}
    seen = set()
    eligible = set(unit.progress_context['eligible_codes'])
    required = unit.progress_context['required_dates']
    actual = {}
    admitted = []
    for index, row in enumerate(normalized):
        if index % ROW_BLOCK_SIZE == 0:
            control.poll()
        code = row['ts_code']
        if current_period and code in seen:
            raise StockPeriodAdjContractError(f'{code}当期源代码重复', 'source_key_conflict')
        seen.add(code)
        valid_period = row['trade_date'] == unit.trade_date if current_period else period_start(row['trade_date'], frequency(definition)) == period_start(unit.trade_date, frequency(definition))
        if not valid_period or row['end_date'] > today():
            raise StockPeriodAdjContractError(f'{code}源周期或截至日期越界', 'source_scope_invalid')
        if code not in eligible:
            continue
        actual[code] = max(actual.get(code, row['end_date']), row['end_date'])
        admitted.append(row)
    for code, minimum in required.items():
        if code not in actual or actual[code] < parse_day(minimum):
            raise StockPeriodAdjContractError(f'{code}源数据未达到{minimum}', 'source_not_ready')
    return admitted, {'source_received': len(rows), 'source_unique': len(normalized),
        'admitted': len(admitted), 'excluded_not_admitted': len(normalized) - len(admitted),
        'pages': pages, 'terminal_short_page': True,
        'admission_excluded_reasons': {'stock_period_adj.not_admitted': len(normalized) - len(admitted)}}


def run_stock_period_adj(executor, *, request, definition, units, cancel_checker, progress_reporter):
    from src.foundation.ingestion.executor import IngestionRunSummary
    context = request.execution_context['stock_period_adj']
    policy = StockPeriodAdjExecutionPolicy(**context['policy'])
    definition = replace(definition, planning=replace(definition.planning, stock_period_adj_policy=policy,
        page_limit=policy.page_limit, max_units_per_execution=policy.max_units, max_source_rows_per_unit=policy.max_rows_per_unit))
    engine = executor.session.get_bind()
    totals = Counter()
    done = 0
    current = {}
    last_emit = 0.0
    last_cancel = 0.0

    def check(force=False):
        nonlocal last_cancel
        now = time.monotonic()
        if force or now - last_cancel >= policy.cancel_poll_seconds:
            last_cancel = now
            if cancel_checker is not None and request.run_id is not None and cancel_checker(request.run_id):
                raise IngestionCanceledError('股票复权周/月线已取消；已提交单元保留，可恢复原计划')

    def emit(stage, force=True):
        nonlocal last_emit
        if not force and time.monotonic() - last_emit < policy.progress_interval_seconds:
            return
        last_emit = time.monotonic()
        diagnostics = {'stock_period_adj': {'batch_id': context['batch_id'], 'business_date': context['business_date'],
            'freq': context['freq'], 'stage': stage, 'unit_done': done, 'unit_total': len(units),
            'eta': '暂无法估算', 'updated_at': datetime.now(UTC).isoformat(), **dict(totals)}}
        snapshot = ProgressSnapshot(run_id=request.run_id, dataset_key=definition.dataset_key,
            unit_total=len(units), unit_done=done, unit_failed=0,
            rows_fetched=totals['source_received'], rows_written=totals['raw_written'], rows_committed=totals['raw_written'],
            rows_rejected=0, ingestion_diagnostics=diagnostics,
            current_object={'entity': {'code': current.get('ts_code'), 'name': None if current.get('ts_code') else '全市场', 'kind': 'stock'},
                'time': {'trade_date': current.get('period_date'), 'business_date': context['business_date']},
                'attributes': {'stage': stage, 'updated_at': diagnostics['stock_period_adj']['updated_at'], 'eta': '暂无法估算'}})
        if progress_reporter:
            try:
                progress_reporter(snapshot, f'{definition.display_name}：{stage}，{done}/{len(units)}；ETA暂无法估算')
            except Exception:
                # Observations never change a committed business result.
                logging.getLogger(__name__).warning('股票周期线观察写入失败，业务记录保持', exc_info=True)

    try:
        check(True)
        if context.get('zero_history'):
            emit('复权因子比较结果为0，无历史回刷')
            return IngestionRunSummary(dataset_key=definition.dataset_key, run_profile=request.run_profile,
                unit_total=0, unit_done=0, unit_failed=0, rows_fetched=0, rows_written=0, rows_committed=0,
                rows_rejected=0, rows_deduplicated=0, rejected_reason_counts={}, rejected_reason_samples={},
                ingestion_diagnostics={'stock_period_adj':context['zero_history']}, result_date=None,
                message='复权因子比较结果为0，无历史回刷', error_counts={})
        with Session(engine) as business:
            header = StockPeriodAdjDeliveryDAO(business).get(context['batch_id'], 'plan_frozen', 'plan_frozen')
        if header is None:
            if context['purpose'] == 'factor_history':
                raise StockPeriodAdjContractError('自动历史必须先共同冻结两频计划', 'resume_contract_mismatch')
            freeze_plan(engine, context, units, policy, lambda: check(True))
        with Session(engine) as business:
            if tuple(units) != restore_units(business, definition, context):
                raise StockPeriodAdjContractError('执行单元与原冻结计划不同', 'resume_contract_mismatch')
            for old in StockPeriodAdjDeliveryDAO(business).committed(context['batch_id']):
                totals.update({key: value for key, value in old.payload.items() if type(value) is int})
                done += 1
        emit('恢复已提交进度')
        for unit in units:
            check(True)
            with Session(engine) as business:
                if StockPeriodAdjDeliveryDAO(business).get(context['batch_id'], 'unit', unit.unit_id) is not None:
                    continue
            current.update(period_date=unit.trade_date.isoformat() if unit.trade_date else None,
                ts_code=unit.progress_context.get('ts_code') or unit.request_params.get('ts_code'))
            control = PeriodControl(lambda: check(True), emit, check)
            if unit.progress_context.get('has_source', True):
                rows, counts = capture(executor, definition, unit, control)
            else:
                rows, counts = [], {'source_received':0, 'source_unique':0, 'admitted':0,
                    'pages':0, 'terminal_short_page':False, 'excluded_not_admitted':0, 'admission_excluded_reasons':{}}
            check(True)
            emit('提交Raw、Serving及业务完成记录')
            with Session(engine) as business:
                result = publish_unit(business, context=context, unit=unit, rows=rows, counts=counts, policy=policy, check=lambda: check(True))
            totals.update({key: value for key, value in result.items() if type(value) is int})
            done += 1
            emit('单元已提交')
            check(True)
        with Session(engine) as business:
            with bounded_transaction(business, policy, lambda: check(True)):
                dao = StockPeriodAdjDeliveryDAO(business)
                committed = dao.committed(context['batch_id'])
                if {row.unit_id for row in committed} != {unit.unit_id for unit in units}:
                    raise StockPeriodAdjContractError('原计划尚有未提交单元', 'resume_contract_mismatch')
                dao.append(record(context, 'batch_closed', 'batch_closed',
                    {'unit_count': len(units), 'scope_digest': context['scope_digest'], 'counts': dict(totals)}), policy)
                business.commit()
        emit('全部单元已完成')
    except Exception as exc:
        progress = {'unit_done': done, 'unit_total': len(units), 'unit_failed': 0,
            'rows_fetched': totals['source_received'], 'rows_saved': totals['raw_written'],
            'rows_rejected': 0, 'ingestion_diagnostics': {'stock_period_adj': {'batch_id': context['batch_id'], **dict(totals)}}}
        if isinstance(exc, StockPeriodAdjContractError):
            exc = IngestionWriteError(StructuredError(error_code=exc.code, error_type='write',
                phase='stock_period_adj', message=str(exc), retryable=False, details={'current': current}))
        exc.stock_period_adj_progress = progress
        raise exc
    return IngestionRunSummary(dataset_key=definition.dataset_key, run_profile=request.run_profile,
        unit_total=len(units), unit_done=done, unit_failed=0, rows_fetched=totals['source_received'],
        rows_written=totals['raw_written'], rows_committed=totals['raw_written'], rows_rejected=0,
        rows_deduplicated=0, ingestion_diagnostics={'stock_period_adj': {'batch_id': context['batch_id'], **dict(totals)}},
        rejected_reason_counts={}, rejected_reason_samples={}, result_date=units[-1].trade_date if units else None,
        message=f'{definition.display_name}已完成{done}/{len(units)}单元', error_counts={})
