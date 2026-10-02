"""Bounded announcement units, with business receipts independent of observation."""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import time
from uuid import uuid4
from sqlalchemy import text, event
from sqlalchemy.orm import Session
from src.foundation.dao.anns_d_sync_dao import AnnsDSyncDAO
from src.foundation.dao.anns_d_dao import AnnsDDAO
from src.foundation.datasets.anns_d_contracts import AnnouncementPersistenceError, digest
from src.foundation.ingestion.errors import IngestionWriteError, StructuredError
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.progress import ProgressSnapshot
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import DatasetWriter

# One shared dataset lock, independent of task/scope tokens. P4 must use this same key.
ANNOUNCEMENT_EXECUTION_LOCK = int.from_bytes(bytes.fromhex(digest(('anns_d','maintenance_execution')))[:8],'big',signed=True)


@contextmanager
def bounded_business_batch(session, seconds, check):
    """Apply one cumulative deadline, rather than renewing it for every group SQL."""
    connection = session.connection()
    deadline = time.monotonic() + seconds
    last_check = 0.0
    def ensure():
        nonlocal last_check
        now = time.monotonic()
        if now - last_check >= 0.2:
            check()
            last_check = time.monotonic()
        remaining = int((deadline-time.monotonic())*1000)
        if remaining < 1:
            raise AnnouncementPersistenceError('anns_d.batch_deadline_exceeded','公告写批超过事务期限，当前批已停止')
        return remaining
    def before_sql(conn, cursor, statement, parameters, context, executemany):
        remaining = ensure()
        if "set_config('statement_timeout'" in statement:
            parameters = {**parameters, 'value':f'{remaining}ms'}
        else:
            cursor.execute(f"SET LOCAL statement_timeout = '{remaining}ms'")
        return statement, parameters
    event.listen(connection,'before_cursor_execute',before_sql,retval=True)
    try:
        yield ensure
    finally:
        event.remove(connection,'before_cursor_execute',before_sql)


class _Control:
    def __init__(self, *, engine, context, maximum, check, emit, statement_timeout, lock_timeout):
        self.engine, self.context, self.maximum = engine, context, maximum
        self.check, self.emit = check, emit
        self.page_number = self.offset = self.issued_requests = 0
        self.statement_timeout, self.lock_timeout = statement_timeout, lock_timeout

    def fetching(self, page_number, offset):
        self.page_number, self.offset = page_number, offset
        self.emit('fetching', True)

    def tick(self):
        self.emit('fetching', False)

    def reserve(self):
        self.check()
        with Session(self.engine) as session:
            session.execute(text("SELECT set_config('statement_timeout',:value,true)"),{'value':f'{self.statement_timeout}s'})
            session.execute(text("SELECT set_config('lock_timeout',:value,true)"),{'value':f'{self.lock_timeout}s'})
            self.issued_requests = AnnsDSyncDAO(session,self.context).reserve_request(self.maximum)
            session.commit()
        self.check()

    def wait(self, delay):
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            self.check()
            self.tick()
            time.sleep(min(0.2,max(deadline-time.monotonic(),0)))
        self.check()


def run_announcements(executor, *, request, definition, units, cancel_checker, progress_reporter):
    from src.foundation.ingestion.executor import IngestionRunSummary
    engine = executor.session.get_bind()
    context = request.execution_context
    if not context:
        raise AnnouncementPersistenceError('anns_d.resume_contract_mismatch','公告缺少冻结执行合同')
    policy = definition.planning.announcement_policy
    totals = Counter()
    quality = Counter()
    rejected_reasons = Counter()
    rejected_samples = {}
    quality_samples = {}
    unit_done = 0
    active = None
    last_emit = 0.0
    controls = None

    def check():
        if cancel_checker is not None and cancel_checker(request.run_id):
            raise IngestionCanceledError('公告任务已收到停止请求')

    def emit(phase, force=True):
        nonlocal last_emit
        now = time.monotonic()
        if not force and now-last_emit < 5:
            return
        last_emit = now
        current = dict(active or {})
        current.update(phase=phase,updated_at=datetime.now(timezone.utc).isoformat())
        if controls:
            current.update(page_number=controls.page_number,offset=controls.offset,issued_requests=controls.issued_requests)
        diagnostic = {'runtime': {'announcement': dict(current, unit_done=unit_done,unit_total=len(units),
                      counters=dict(totals),quality_counts=dict(quality),quality_samples=quality_samples,
                      execution_token=context['execution_token'],eta='unavailable')},
                      'persistence': {'announcement_reconciliation': dict(totals)}}
        snapshot = ProgressSnapshot(run_id=request.run_id,dataset_key=definition.dataset_key,unit_total=len(units),
            unit_done=unit_done,unit_failed=0,rows_fetched=totals['observed'],rows_written=totals['processed'],
            rows_committed=totals['processed'],rows_rejected=totals['rejected'],rows_deduplicated=totals['identical']+totals['covered'],
            ingestion_diagnostics=diagnostic,rejected_reason_counts=dict(rejected_reasons),rejected_reason_samples=rejected_samples,
            current_object={'time': {'field':'ann_date','point':current.get('ann_date')},'entity':{'ts_code':request.params.get('ts_code')}})
        if progress_reporter:
            try:
                progress_reporter(snapshot,f"公告：{unit_done}/{len(units)} 日，{current.get('ann_date','')}，第{current.get('page_number',0)}页，阶段{phase}，已提交输入{totals['processed']}，ETA暂无法估算")
            except Exception:
                logging.getLogger(__name__).warning('公告观察更新失败，业务提交保持',exc_info=True)
        return diagnostic

    def merge_samples(target, incoming):
        for key, samples in incoming.items():
            target.setdefault(key,[]).extend(samples[:max(0,3-len(target.get(key,[])))])

    # Release any read transaction from planning/observation before external waiting.
    executor.session.rollback()
    try:
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
            acquired = lock.execute(text('SELECT pg_try_advisory_lock(:key)'),{'key':ANNOUNCEMENT_EXECUTION_LOCK}).scalar()
            if not acquired:
                raise AnnouncementPersistenceError('anns_d.dataset_busy','公告维护执行已被其他任务占用')
            try:
                emit('planning')
                with Session(engine) as business:
                    writer = DatasetWriter(business)
                    receipts = AnnsDSyncDAO(business,context)
                    def bound_transaction():
                        business.execute(text("SELECT set_config('statement_timeout',:value,true)"),
                            {'value':f'{definition.storage.reconciliation_statement_timeout_seconds}s'})
                        business.execute(text("SELECT set_config('lock_timeout',:value,true)"),
                            {'value':f'{definition.storage.reconciliation_lock_timeout_seconds}s'})
                    bound_transaction()
                    AnnsDDAO(business).require_identity_ready()
                    business.rollback()
                    for unit in units:
                        check()
                        controls = _Control(engine=engine,context=context,maximum=policy.max_requests_per_execution,check=check,emit=emit,
                            statement_timeout=definition.storage.reconciliation_statement_timeout_seconds,
                            lock_timeout=definition.storage.reconciliation_lock_timeout_seconds)
                        active = {'ann_date':unit.trade_date.isoformat()}
                        bound_transaction()
                        controls.issued_requests = receipts.issued_requests()
                        receipt = receipts.receipt(unit.trade_date)
                        if receipt:
                            totals.update(receipt['reason_counts'].get('counters',{}))
                            quality.update(receipt['reason_counts'].get('quality_counts',{}))
                            rejected_reasons.update(receipt['reason_counts'].get('rejected_reasons',{}))
                            business.rollback()
                            unit_done += 1
                            emit('completed')
                            continue
                        business.rollback()
                        local = Counter()
                        local_quality = Counter()
                        local_reasons = Counter()
                        attempt = uuid4()
                        for page in executor.source_client.iter_bounded_pages(definition=definition,unit=unit,control=controls):
                            check()
                            local['observed'] += len(page.rows_raw)
                            totals['observed'] += len(page.rows_raw)
                            emit('persisting')
                            size = definition.storage.reconciliation_batch_rows
                            starts = range(0,len(page.rows_raw),size) if page.rows_raw else (0,)
                            for start in starts:
                                check()
                                batch = executor.normalizer.normalize(definition=definition,
                                    fetch_result=SourceFetchResult(unit_id=unit.unit_id,request_count=0,retry_count=0,latency_ms=0,
                                        rows_raw=page.rows_raw[start:start+size]),expected_unit_date=unit.trade_date)
                                check()
                                with bounded_business_batch(business,definition.storage.reconciliation_statement_timeout_seconds,check) as ensure:
                                    result = writer.write(definition=definition,batch=batch)
                                    counts = Counter(result.persistence_diagnostics.get('announcement_reconciliation',{}))
                                    counts = Counter({k:v for k,v in counts.items() if isinstance(v,int)})
                                    counts['rejected'] = batch.rows_rejected
                                    last = page.is_short_page and start+size >= len(page.rows_raw)
                                    pending = local + counts
                                    if last:
                                        # Receipt and terminal batch share exactly one business commit.
                                        receipts.complete(ann_date=unit.trade_date,attempt_token=attempt,terminal_page_number=page.page_number,
                                            terminal_offset=page.offset or 0,terminal_rows=len(page.rows_raw),rows_observed=local['observed'],
                                            rows_committed=pending['processed'],reason_counts={'counters':dict(pending),
                                                'quality_counts':dict(local_quality+Counter(batch.quality_counts)),
                                                'rejected_reasons':dict(local_reasons+Counter(batch.rejected_reasons))})
                                    check()
                                    ensure()
                                    business.commit()
                                local.update(counts)
                                totals.update(counts)
                                local_quality.update(batch.quality_counts)
                                quality.update(batch.quality_counts)
                                local_reasons.update(batch.rejected_reasons)
                                rejected_reasons.update(batch.rejected_reasons)
                                merge_samples(rejected_samples,batch.rejected_samples)
                                merge_samples(quality_samples,batch.quality_samples)
                                if last:
                                    unit_done += 1
                                emit('completed' if last else 'persisting')
                                del batch, result
                                check()
                            del page
                    diagnostic = emit('completed')
            finally:
                lock.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':ANNOUNCEMENT_EXECUTION_LOCK})
    except BaseException as exc:
        emit('canceled' if isinstance(exc,IngestionCanceledError) else 'failed')
        if isinstance(exc,AnnouncementPersistenceError):
            raise IngestionWriteError(StructuredError(error_code=exc.code,error_type='write',phase='announcement_stream',message=str(exc),retryable=False)) from exc
        raise
    return IngestionRunSummary(dataset_key=request.dataset_key,run_profile=request.run_profile,unit_total=len(units),unit_done=unit_done,
        unit_failed=0,rows_fetched=totals['observed'],rows_written=totals['processed'],rows_committed=totals['processed'],
        rows_rejected=totals['rejected'],rows_deduplicated=totals['identical']+totals['covered'],ingestion_diagnostics=diagnostic,
        rejected_reason_counts=dict(rejected_reasons),rejected_reason_samples=rejected_samples,result_date=units[-1].trade_date if units else None,
        message='公告日窗口已完成',error_counts={})
