"""Short PostgreSQL publication of Raw, selected Serving and the unit fact."""

from contextlib import contextmanager
from datetime import datetime, timedelta, UTC
import time

from sqlalchemy import and_, delete, event, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from src.foundation.dao.stock_period_adj_delivery_dao import StockPeriodAdjDeliveryDAO
from src.foundation.datasets.stock_period_adj_contracts import (
    SOURCE_FIELDS, ROW_BLOCK_SIZE, StockPeriodAdjContractError, check_size, digest, parse_day, period_start, select_serving,
)
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj as Raw
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj as Serving


@contextmanager
def bounded_transaction(session, policy, check):
    check()
    connection = session.connection()
    deadline = time.monotonic() + policy.db_statement_timeout_seconds
    session.execute(text("SELECT set_config('lock_timeout', :value, true)"), {'value': f'{policy.lock_timeout_seconds}s'})

    def before_sql(conn, cursor, statement, parameters, context, executemany):
        check()
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            raise StockPeriodAdjContractError('当前单元业务事务超时', 'business_deadline_exceeded')
        cursor.execute(f"SET LOCAL statement_timeout = '{remaining}ms'")

    def before_commit(store):
        check()
        if time.monotonic() > deadline:
            raise StockPeriodAdjContractError('当前单元业务事务超时', 'business_deadline_exceeded')

    event.listen(connection, 'before_cursor_execute', before_sql)
    event.listen(session, 'before_commit', before_commit)
    try:
        yield
        # After COMMIT the unit is durable. Cancellation is checked by the runner
        # after it accounts for that fact, never presented as an uncommitted unit.
        if session.in_transaction():
            before_commit(session)
    except DBAPIError as exc:
        state = getattr(exc.orig, 'sqlstate', None)
        if state == '57014':
            raise StockPeriodAdjContractError('当前单元业务事务累计超时，当前事务回滚', 'business_deadline_exceeded') from exc
        if state == '55P03':
            raise StockPeriodAdjContractError('当前单元业务锁等待超时，当前事务回滚', 'writer_busy') from exc
        raise
    finally:
        event.remove(connection, 'before_cursor_execute', before_sql)
        event.remove(session, 'before_commit', before_commit)


def acquire_writer(session, freq):
    key = int.from_bytes(bytes.fromhex(digest(('stock_period_adj', freq)))[:8], 'big', signed=True)
    if not session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': key}):
        raise StockPeriodAdjContractError('本频率已有发布事务', 'writer_busy')


def group_predicate(model, groups, freq):
    return and_(model.freq == freq, or_(*(and_(model.ts_code == code, model.trade_date >= start,
        model.trade_date < (start + timedelta(days=7) if freq == 'week' else
            start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)))
        for code, start in groups)))


def source_row(row):
    return {field: getattr(row, field) for field in SOURCE_FIELDS}


def select_groups(session, groups, freq, policy, check):
    selected = []
    scanned = []
    for start in range(0, len(groups), ROW_BLOCK_SIZE):
        check()
        chunk = groups[start:start + ROW_BLOCK_SIZE]
        candidates = [source_row(row) for row in session.scalars(select(Raw).where(group_predicate(Raw, chunk, freq))
            .limit(policy.max_rows_per_unit - len(scanned) + 1))]
        scanned.extend(candidates)
        if len(scanned) > policy.max_rows_per_unit:
            raise StockPeriodAdjContractError('受影响周期原候选行数超限', 'row_budget_exceeded')
        check_size(scanned, policy.max_payload_bytes)
        selected.extend(select_serving(candidates, freq))
    return selected, len(scanned)


def republish_groups(session, groups, freq, policy, check):
    selected, scanned_count = select_groups(session, groups, freq, policy, check)
    for start in range(0, len(groups), ROW_BLOCK_SIZE):
        check()
        session.execute(delete(Serving).where(group_predicate(Serving, groups[start:start + ROW_BLOCK_SIZE], freq)))
    values = [{('change_amount' if key == 'change' else key): value for key, value in row.items()} for row in selected]
    for start in range(0, len(values), ROW_BLOCK_SIZE):
        check()
        session.execute(insert(Serving).values(values[start:start + ROW_BLOCK_SIZE]))
    observed = []
    for start in range(0, len(groups), ROW_BLOCK_SIZE):
        for row in session.scalars(select(Serving).where(group_predicate(Serving, groups[start:start + ROW_BLOCK_SIZE], freq))
                                   .execution_options(populate_existing=True)):
            observed.append({field: getattr(row, 'change_amount' if field == 'change' else field) for field in SOURCE_FIELDS})
    order = lambda row: (row['ts_code'], row['trade_date'])
    if sorted(observed, key=order) != sorted(selected, key=order):
        raise StockPeriodAdjContractError('Serving读回与完整行选择不一致', 'latest_version_conflict')
    return observed, scanned_count


def publish_unit(session, *, context, unit, rows, counts, policy, check):
    from src.foundation.ingestion.stock_period_adj_planning import record
    dao = StockPeriodAdjDeliveryDAO(session)
    with bounded_transaction(session, policy, check):
        acquire_writer(session, context['freq'])
        old = dao.get(context['batch_id'], 'unit', unit.unit_id)
        if old is not None:
            return old.payload
        if dao.get(context['batch_id'], 'plan_frozen', 'plan_frozen') is None:
            raise StockPeriodAdjContractError('行情写入前必须有完整冻结计划', 'resume_contract_mismatch')
        removals = [(key['ts_code'], parse_day(key['trade_date']), key['freq'])
                    for key in unit.progress_context.get('remove_keys', [])]
        source_digest = digest(rows)
        removed_set = set(removals)
        merge_rows = [row for row in rows if (row['ts_code'], row['trade_date'], row['freq']) not in removed_set]
        excluded_withdrawal = len(rows) - len(merge_rows)
        rows = merge_rows
        deleted = []
        for start in range(0, len(removals), ROW_BLOCK_SIZE):
            check()
            deleted.extend(session.execute(delete(Raw).where(tuple_(Raw.ts_code, Raw.trade_date, Raw.freq)
                .in_(removals[start:start + ROW_BLOCK_SIZE])).returning(Raw.ts_code, Raw.trade_date, Raw.freq)).all())
        written = 0
        for start in range(0, len(rows), ROW_BLOCK_SIZE):
            check()
            block = rows[start:start + ROW_BLOCK_SIZE]
            stmt = insert(Raw).values([{**row, 'fetched_at': datetime.now(UTC), 'api_name': 'stk_week_month_adj'} for row in block])
            stmt = stmt.on_conflict_do_update(index_elements=['ts_code', 'trade_date', 'freq'],
                set_={field: getattr(stmt.excluded, field) for field in SOURCE_FIELDS if field not in {'ts_code','trade_date','freq'}} |
                     {'fetched_at': stmt.excluded.fetched_at, 'api_name': stmt.excluded.api_name},
                where=or_(Raw.end_date.is_(None), stmt.excluded.end_date >= Raw.end_date)).returning(Raw.ts_code)
            written += len(session.scalars(stmt).all())
        groups = sorted({(row['ts_code'], period_start(row['trade_date'], context['freq'])) for row in rows} |
                        {(code, period_start(stamp, freq)) for code, stamp, freq in removals})
        serving, candidates = republish_groups(session, groups, context['freq'], policy, check)
        raw_after = []
        for start in range(0, len(rows), ROW_BLOCK_SIZE):
            keys = [(row['ts_code'], row['trade_date'], row['freq']) for row in rows[start:start + ROW_BLOCK_SIZE]]
            raw_after.extend(source_row(row) for row in session.scalars(select(Raw).where(
                tuple_(Raw.ts_code, Raw.trade_date, Raw.freq).in_(keys)).execution_options(populate_existing=True)))
        by_key = {(row['ts_code'], row['trade_date'], row['freq']): row for row in raw_after}
        for incoming in rows:
            actual = by_key[(incoming['ts_code'], incoming['trade_date'], incoming['freq'])]
            if actual['end_date'] < incoming['end_date'] or (actual['end_date'] == incoming['end_date'] and actual != incoming):
                raise StockPeriodAdjContractError('Raw读回不符合较新保护及整行写入', 'source_key_conflict')
        for start in range(0, len(removals), ROW_BLOCK_SIZE):
            if session.scalar(select(Raw.ts_code).where(tuple_(Raw.ts_code, Raw.trade_date, Raw.freq)
                    .in_(removals[start:start + ROW_BLOCK_SIZE])).limit(1)) is not None:
                raise StockPeriodAdjContractError('指定撤回键读回仍存在', 'source_key_conflict')
        payload = {**counts, 'admitted':len(rows), 'withdrawal_excluded':excluded_withdrawal,
            'raw_deleted':len(deleted), 'raw_written': written, 'raw_protected': len(rows) - written,
            'serving_written': len(serving), 'candidate_rows': candidates,
            'source_digest': source_digest, 'result_digest': digest({'raw': sorted(raw_after, key=lambda r: (r['ts_code'],r['trade_date'])),
                'serving': serving, 'deleted':sorted(tuple(key) for key in deleted)}),
            'period_date': unit.trade_date.isoformat() if unit.trade_date else None, 'scope_digest': context['scope_digest']}
        dao.append(record(context, 'unit', unit.unit_id, payload, period=unit.trade_date,
                          code=unit.progress_context.get('ts_code') or unit.request_params.get('ts_code')), policy)
        check()
        session.commit()
    return payload
