"""Bounded, read-only ledger observations."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

from src.foundation.clients.announcement_archive.core import Blocked, Control


ARTIFACT_STATES = ('pending', 'downloading', 'prepared', 'succeeded', 'failed', 'blocked')


@dataclass(frozen=True)
class LedgerQueryPolicy:
    page_default: int = 20
    page_max: int = 100
    query_timeout_seconds: float = 4
    sql_progress_steps: int = 1000


class LedgerQuery:
    def __init__(self, ledger, control: Control, policy=LedgerQueryPolicy()):
        if (not 0 < policy.page_default <= policy.page_max <= 100
                or not 0 < policy.query_timeout_seconds <= 4 or policy.sql_progress_steps <= 0):
            raise ValueError('ledger_query_policy_invalid')
        self.conn, self.control, self.policy = ledger.conn, control, policy
        # DELETE journaling: release this read snapshot before the writer's 5s busy budget.
        self.deadline = time.monotonic() + policy.query_timeout_seconds
        self.conn.execute('BEGIN')
        self.archive = self.query('SELECT * FROM archive', cap=1)[0]
        self.version = self.archive['schema_version']

    def query(self, sql, params=(), *, cap=None):
        self.control.check()
        deadline = self.deadline
        if time.monotonic() >= deadline:
            raise Blocked('ledger_query_timeout')
        def interrupt():
            return int(self.control.stop.is_set() or time.monotonic() >= deadline)
        self.conn.set_progress_handler(interrupt, self.policy.sql_progress_steps)
        try:
            try:
                rows = self.conn.execute(sql, params).fetchmany(cap or self.policy.page_max + 1)
            except sqlite3.OperationalError as exc:
                self.control.check()
                if time.monotonic() >= deadline:
                    raise Blocked('ledger_query_timeout') from None
                raise Blocked('ledger_query_failed') from exc
            self.control.check()
            if time.monotonic() >= deadline:
                raise Blocked('ledger_query_timeout')
            return [dict(row) for row in rows]
        finally:
            self.conn.set_progress_handler(None, 0)

    def _limit(self, value):
        if not isinstance(value, int) or not 1 <= value <= self.policy.page_max:
            raise ValueError('ledger_page_limit_invalid')
        return value

    def page(self, sql, params, limit, cursor_column, cursor_name):
        limit = self._limit(limit)
        rows = self.query(sql + ' LIMIT ?', (*params, limit + 1), cap=limit + 1)
        more = len(rows) > limit
        items = rows[:limit]
        return dict(items=items, limit=limit, has_more=more,
                    **{cursor_name: items[-1][cursor_column] if more else None})

    def summary(self):
        return dict(archive=self.archive,
                    files=self.query('SELECT state,COUNT(*) AS count FROM artifacts GROUP BY state'),
                    dates=self.query('SELECT MIN(ann_date) AS first_date,MAX(ann_date) AS last_date,'
                                     'COUNT(*) AS file_tasks FROM artifacts', cap=1)[0],
                    sources=self.query('SELECT COUNT(*) AS records,COALESCE(SUM(artifact_key IS NULL),0) AS missing_url '
                                       'FROM source_records', cap=1)[0],
                    latest_run=self.runs(1)['items'], physical_status='not_checked')

    def runs(self, limit, before_rowid=None, run_id=None):
        conditions, values = [], []
        if before_rowid is not None:
            conditions.append('rowid < ?'); values.append(before_rowid)
        if run_id:
            conditions.append('run_id = ?'); values.append(run_id)
        sql = 'SELECT rowid AS ledger_rowid,* FROM runs'
        if conditions:
            sql += ' WHERE ' + ' AND '.join(conditions)
        result = self.page(sql + ' ORDER BY rowid DESC', values, limit, 'ledger_rowid', 'next_before_rowid')
        for row in result['items']:
            if self.version == 1:
                row['source_kind'] = 'prod_postgres'
        return result

    def files(self, limit, *, start_date=None, end_date=None, ts_code=None, title=None,
              state=None, run_id=None, after_key=None):
        conditions, values = [], []
        for column, op, value in [('ann_date','>=',start_date),('ann_date','<=',end_date),
                                   ('ts_code','=',ts_code),('state','=',state),('artifact_key','>',after_key)]:
            if value is not None:
                conditions.append(f'a.{column} {op} ?'); values.append(str(value))
        if title is not None:
            conditions.append('instr(a.title,?) > 0'); values.append(title)
        if state is not None and state not in ARTIFACT_STATES:
            raise ValueError('ledger_state_invalid')
        if run_id:
            conditions.append('EXISTS (SELECT 1 FROM run_artifacts r WHERE r.artifact_key=a.artifact_key AND r.run_id=?)')
            values.append(run_id)
        sql = 'SELECT a.* FROM artifacts a'
        if conditions:
            sql += ' WHERE ' + ' AND '.join(conditions)
        result = self.page(sql + ' ORDER BY a.artifact_key', values, limit, 'artifact_key', 'next_after_key')
        for row in result['items']:
            row['physical_status'] = 'not_checked'
        return result

    def artifact(self, key):
        rows = self.query('SELECT * FROM artifacts WHERE artifact_key=?', (key,), cap=1)
        if not rows:
            raise Blocked('artifact_not_found')
        return rows[0]

    def show(self, key, limit, after_rowid=None):
        artifact = self.artifact(key)
        artifact['physical_status'] = 'not_checked'
        key_column = 'record_key' if self.version >= 2 else 'row_key_hash'
        id_column = 'legacy_raw_id' if self.version >= 2 else 'raw_id'
        sql = (f'SELECT rowid AS ledger_rowid,source_scope,{key_column} AS record_key,'
               f'{id_column} AS legacy_raw_id,metadata,first_seen_run,last_seen_run '
               'FROM source_records WHERE artifact_key=?')
        values = [key]
        if after_rowid is not None:
            sql += ' AND rowid > ?'; values.append(after_rowid)
        sources = self.page(sql + ' ORDER BY rowid', values, limit, 'ledger_rowid', 'next_after_rowid')
        for row in sources['items']:
            try:
                row['metadata'] = json.loads(row['metadata'])
            except (TypeError, ValueError):
                raise Blocked('ledger_metadata_invalid') from None
        return dict(artifact=artifact, sources=sources)
