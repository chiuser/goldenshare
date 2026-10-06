from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
import uuid
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from src.foundation.clients.announcement_archive.core import (
    SOURCE_CONTRACT_VERSION, Blocked, DownloadOptions, DownloadPolicy, source_projection, timestamp,
)

from src.foundation.clients.announcement_archive.volume import no_symlinks
from .schema import ADDITIONS, REQUIRED, PRIMARY_KEYS, INDEXES, extend_schema


DAY_SCHEMA = """CREATE TABLE run_source_days (
 run_id TEXT NOT NULL, ann_date TEXT NOT NULL, state TEXT NOT NULL,
 opened_dev INTEGER, opened_ino INTEGER, size INTEGER, sha256 TEXT,
 footer_count INTEGER, records_committed INTEGER NOT NULL DEFAULT 0,
 reason TEXT, updated_at TEXT, PRIMARY KEY(run_id,ann_date))"""

RUN_ADDITIONS = (
 ('source_kind', "TEXT NOT NULL DEFAULT 'dg_raw_parquet'"),
 ('source_contract_version', 'INTEGER'), ('source_policy', 'TEXT'),
 ('days_total', 'INTEGER'), ('days_completed', 'INTEGER NOT NULL DEFAULT 0'),
 ('current_day', 'TEXT'), ('enumeration_sealed', 'INTEGER NOT NULL DEFAULT 0'),
)

SCHEMA = (
 """CREATE TABLE archive (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
 volume_uuid TEXT NOT NULL, root_relative_path TEXT NOT NULL, created_at TEXT NOT NULL)""",
 """CREATE TABLE runs (
 run_id TEXT PRIMARY KEY, start_date TEXT, end_date TEXT, interval_seconds REAL,
 source_scope TEXT, legacy_upper_id INTEGER DEFAULT 0, legacy_after_id INTEGER DEFAULT 0,
 phase TEXT NOT NULL, records_read INTEGER DEFAULT 0, reason TEXT, updated_at TEXT,
 missing_url_count INTEGER DEFAULT 0,
 artifacts_total INTEGER DEFAULT 0, completed_count INTEGER DEFAULT 0,
 succeeded_count INTEGER DEFAULT 0, skipped_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0,
 source_kind TEXT NOT NULL DEFAULT 'dg_raw_parquet', source_contract_version INTEGER, source_policy TEXT,
 days_total INTEGER, days_completed INTEGER NOT NULL DEFAULT 0, current_day TEXT,
 enumeration_sealed INTEGER NOT NULL DEFAULT 0)""",
 """CREATE TABLE artifacts (
 artifact_key TEXT PRIMARY KEY, ann_date TEXT, ts_code TEXT, title TEXT, url TEXT,
 relative_path TEXT, path_fold TEXT UNIQUE, state TEXT NOT NULL DEFAULT 'pending',
 error TEXT, attempts INTEGER NOT NULL DEFAULT 0, size INTEGER, sha256 TEXT, updated_at TEXT)""",
 """CREATE TABLE source_records (
 source_scope TEXT, record_key TEXT, legacy_raw_id INTEGER, metadata TEXT, artifact_key TEXT,
 first_seen_run TEXT, last_seen_run TEXT, PRIMARY KEY(source_scope,record_key))""",
 """CREATE TABLE run_artifacts (
 run_id TEXT, artifact_key TEXT, outcome TEXT, attempts INTEGER DEFAULT 0,
 PRIMARY KEY(run_id,artifact_key))""",
 """CREATE TABLE cooldown (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_request_finished_at REAL DEFAULT 0,
 next_request_not_before REAL DEFAULT 0, request_in_flight INTEGER DEFAULT 0, reason TEXT)""",
 'CREATE INDEX run_pending ON run_artifacts(run_id,outcome,artifact_key)',
 DAY_SCHEMA,
 'CREATE INDEX source_day_state ON run_source_days(run_id,state,ann_date)',
)


class Ledger:
    def __init__(self, path: Path, volume_uuid: str, relative_root: str, *, read_only=False):
        path = Path(path).absolute()
        no_symlinks(path)
        if read_only:
            if not path.is_file():
                raise Blocked('archive_ledger_missing')
            self.conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
        else:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not path.exists():
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(handle)
            self.conn = sqlite3.connect(path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.owner_token = uuid.uuid4().hex
        try:
            if read_only:
                self.conn.execute('PRAGMA query_only=ON')
            tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                if read_only:
                    raise Blocked('archive_schema_invalid')
                self.conn.execute('PRAGMA journal_mode=DELETE')
                self.conn.execute('PRAGMA synchronous=FULL')
                self.conn.execute('BEGIN IMMEDIATE')
                try:
                    for sql in SCHEMA:
                        self.conn.execute(sql)
                    self.conn.execute('INSERT INTO archive VALUES(1,2,?,?,?)',
                                      (volume_uuid, relative_root, timestamp()))
                    self.conn.execute('INSERT INTO cooldown(singleton) VALUES(1)')
                    extend_schema(self.conn)
                    self._validate_schema(3)
                    self.conn.commit()
                except BaseException:
                    self.conn.rollback()
                    raise
            else:
                if 'archive' not in tables:
                    raise Blocked('archive_schema_invalid')
                existing = self.conn.execute('SELECT * FROM archive LIMIT 2').fetchmany(2)
                if (len(existing) != 1 or not {'schema_version','volume_uuid','root_relative_path'}
                        <= set(existing[0].keys())):
                    raise Blocked('archive_schema_invalid')
                existing = existing[0]
                if (existing['volume_uuid'] != volume_uuid or existing['root_relative_path'] != relative_root):
                    raise Blocked('archive_identity_mismatch')
                version = existing['schema_version']
                if version not in (1, 2, 3):
                    raise Blocked('archive_schema_version_unsupported')
                self._validate_schema(version)
                if read_only:
                    return
                self.conn.execute('PRAGMA journal_mode=DELETE')
                self.conn.execute('PRAGMA synchronous=FULL')
                if version < 3:
                    self._upgrade(version)
        except BaseException:
            self.conn.close()
            raise

    def _validate_schema(self, version):
        required = dict(
            archive={'singleton','schema_version','volume_uuid','root_relative_path','created_at'},
            runs={'run_id','start_date','end_date','interval_seconds','source_scope','phase','records_read',
                  'reason','updated_at','missing_url_count','artifacts_total','completed_count',
                  'succeeded_count','skipped_count','failed_count'},
            artifacts={'artifact_key','ann_date','ts_code','title','url','relative_path','path_fold',
                       'state','error','attempts','size','sha256','updated_at'},
            source_records={'source_scope','metadata','artifact_key','first_seen_run','last_seen_run'},
            run_artifacts={'run_id','artifact_key','outcome','attempts'},
            cooldown={'singleton','last_request_finished_at','next_request_not_before','request_in_flight','reason'},
        )
        if version == 1:
            required['runs'] |= {'upper_id','after_id'}
            required['source_records'] |= {'row_key_hash','raw_id'}
        else:
            required['runs'] |= {'legacy_upper_id','legacy_after_id', *(n for n,_ in RUN_ADDITIONS)}
            required['source_records'] |= {'record_key','legacy_raw_id'}
            required['run_source_days'] = {'run_id','ann_date','state','opened_dev','opened_ino','size','sha256',
                                          'footer_count','records_committed','reason','updated_at'}
        if version == 3:
            for table, fields in ADDITIONS.items():
                required[table] |= {name for name, _ in fields}
            required.update(REQUIRED)
        actual_tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if actual_tables != set(required):
            raise Blocked('archive_schema_invalid')
        for table, expected in required.items():
            actual = {r[1] for r in self.conn.execute(f'PRAGMA table_info({table})')}
            if version == 1 and table == 'runs' and 'missing_url_count' not in actual:
                expected = expected - {'missing_url_count'}
            if actual != expected:
                raise Blocked('archive_schema_invalid')
        indexes = {'run_pending':['run_id','outcome','artifact_key']}
        if version >= 2:
            indexes['source_day_state'] = ['run_id','state','ann_date']
        if version == 3:
            indexes.update({name:definition[1] for name,definition in INDEXES.items()})
        for index, columns in indexes.items():
            if [r[2] for r in self.conn.execute(f'PRAGMA index_info({index})')] != columns:
                raise Blocked('archive_schema_invalid')
        key = 'row_key_hash' if version == 1 else 'record_key'
        primary_keys = dict(archive=['singleton'], runs=['run_id'], artifacts=['artifact_key'],
                            source_records=['source_scope',key], run_artifacts=['run_id','artifact_key'],
                            cooldown=['singleton'])
        if version >= 2:
            primary_keys['run_source_days'] = ['run_id','ann_date']
        if version == 3:
            primary_keys.update(PRIMARY_KEYS)
        for table, columns in primary_keys.items():
            pk = sorted((r[5],r[1]) for r in self.conn.execute(f'PRAGMA table_info({table})') if r[5])
            if [column for _,column in pk] != columns:
                raise Blocked('archive_schema_invalid')
        path_unique = False
        for index in self.conn.execute('PRAGMA index_list(artifacts)'):
            quoted = index[1].replace('"','""')
            columns = [r[2] for r in self.conn.execute(f'PRAGMA index_info("{quoted}")')]
            if index[2] and not index[4] and columns == ['path_fold']:
                path_unique = True
        if not path_unique:
            raise Blocked('archive_schema_invalid')
        if self.conn.execute('SELECT count(*) FROM cooldown WHERE singleton=1').fetchone()[0] != 1:
            raise Blocked('archive_schema_invalid')
        if version == 3 and self.conn.execute('SELECT count(*) FROM archive_execution WHERE singleton=1').fetchone()[0] != 1:
            raise Blocked('archive_schema_invalid')

    def _upgrade(self, version):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            if version == 1:
                if 'missing_url_count' not in {r[1] for r in self.conn.execute('PRAGMA table_info(runs)')}:
                    self.conn.execute('ALTER TABLE runs ADD COLUMN missing_url_count INTEGER NOT NULL DEFAULT 0')
                self.conn.execute('ALTER TABLE runs RENAME COLUMN upper_id TO legacy_upper_id')
                self.conn.execute('ALTER TABLE runs RENAME COLUMN after_id TO legacy_after_id')
                self.conn.execute('ALTER TABLE source_records RENAME COLUMN row_key_hash TO record_key')
                self.conn.execute('ALTER TABLE source_records RENAME COLUMN raw_id TO legacy_raw_id')
                for name, declaration in RUN_ADDITIONS:
                    self.conn.execute(f'ALTER TABLE runs ADD COLUMN {name} {declaration}')
                self.conn.execute("UPDATE runs SET source_kind='prod_postgres'")
                self.conn.execute(DAY_SCHEMA)
                self.conn.execute('CREATE INDEX source_day_state ON run_source_days(run_id,state,ann_date)')
                self.conn.execute('UPDATE archive SET schema_version=2 WHERE singleton=1')
                self._validate_schema(2)
            extend_schema(self.conn)
            self._validate_schema(3)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def begin_run(self, options: DownloadOptions, scope: str, policy: DownloadPolicy | None = None) -> str:
        run = uuid.uuid4().hex
        with self.conn:
            active = self.conn.execute('SELECT active_run_id,owner_token FROM archive_execution WHERE singleton=1').fetchone()
            if active['active_run_id'] and active['owner_token'] == self.owner_token:
                raise Blocked('archive_already_running')
            now = timestamp()
            self.conn.execute("UPDATE attempt_log SET ended_at=?,outcome='interrupted',reason='process_exit_recovered' WHERE ended_at IS NULL", (now,))
            self.conn.execute("UPDATE run_sessions SET ended_at=?,reason='process_exit_recovered' WHERE ended_at IS NULL", (now,))
            self.conn.execute("UPDATE runs SET finished_at=?,owner_token=NULL WHERE phase IN ('enumerating','downloading')", (now,))
            self.conn.execute("UPDATE run_source_days SET state='cancelled',reason='process_exit_recovered',updated_at=? "
                              "WHERE state='reading'", (timestamp(),))
            self.conn.execute("UPDATE runs SET phase='interrupted',reason='process_exit_recovered',updated_at=? "
                              "WHERE phase IN ('enumerating','downloading')", (timestamp(),))
            self.conn.execute('INSERT INTO runs(run_id,start_date,end_date,interval_seconds,source_scope,phase,updated_at,'
                              'source_contract_version,source_policy,days_total,legacy_upper_id,legacy_after_id) '
                              'VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)',
                              (run, options.start_date.isoformat(), options.end_date.isoformat(), options.interval_seconds,
                               scope, 'enumerating', timestamp(), SOURCE_CONTRACT_VERSION,
                               json.dumps(asdict(policy or DownloadPolicy()), sort_keys=True),
                               (options.end_date-options.start_date).days+1))
            self.conn.execute('UPDATE runs SET created_at=?,started_at=?,owner_token=?,heartbeat_at=?,business_updated_at=? WHERE run_id=?',
                              (now,now,self.owner_token,now,now,run))
            self.conn.execute('INSERT INTO run_sessions(run_id,session_seq,started_at,owner_token) VALUES(?,1,?,?)', (run,now,self.owner_token))
            self.conn.execute('UPDATE archive_execution SET active_run_id=?,owner_token=?,heartbeat=?,revision=revision+1 WHERE singleton=1',
                              (run,self.owner_token,now))
        return run

    def begin_day(self, run: str, day: str):
        with self.conn:
            current = self.conn.execute('SELECT * FROM runs WHERE run_id=?', (run,)).fetchone()
            if (not current or current['phase'] != 'enumerating' or current['enumeration_sealed']
                    or current['days_completed'] >= current['days_total']
                    or (date.fromisoformat(current['start_date']) + timedelta(days=current['days_completed'])).isoformat() != day):
                raise Blocked('source_day_outside_enumeration')
            self.conn.execute("INSERT INTO run_source_days(run_id,ann_date,state,updated_at) VALUES(?,?,'reading',?)",
                              (run, day, timestamp()))
            self.conn.execute('UPDATE runs SET current_day=?,updated_at=? WHERE run_id=?', (day,timestamp(),run))

    def describe_day(self, run: str, day: str, facts: dict):
        with self.conn:
            self.conn.execute('UPDATE run_source_days SET opened_dev=?,opened_ino=?,size=?,sha256=?,footer_count=?,'
                              "updated_at=? WHERE run_id=? AND ann_date=? AND state='reading'",
                              (*[facts[k] for k in ('opened_dev','opened_ino','size','sha256','footer_count')],timestamp(),run,day))

    def ingest(self, run: str, scope: str, day: str, rows: list[dict], batch_size=500):
        if len(rows) > min(batch_size,500):
            raise Blocked('source_batch_limit')
        with self.conn:
            current = self.conn.execute('SELECT phase,source_scope,enumeration_sealed FROM runs WHERE run_id=?',
                                        (run,)).fetchone()
            unit = self.conn.execute('SELECT * FROM run_source_days WHERE run_id=? AND ann_date=?', (run,day)).fetchone()
            if (not current or current['phase'] != 'enumerating' or current['enumeration_sealed']
                    or current['source_scope'] != scope or not unit or unit['state'] != 'reading'):
                raise Blocked('source_batch_outside_enumeration')
            added = missing = 0
            for row in rows:
                record_key, iso_day, key = source_projection(row, day)
                previous = self.conn.execute('SELECT last_seen_run FROM source_records WHERE source_scope=? AND record_key=?',
                                             (scope,record_key)).fetchone()
                if previous and previous['last_seen_run'] == run:
                    raise Blocked('source_duplicate_record')
                if key:
                    self.conn.execute('INSERT OR IGNORE INTO artifacts(artifact_key,ann_date,ts_code,title,url,updated_at,created_run_id,representative_record_key) '
                                      'VALUES(?,?,?,?,?,?,?,?)', (key,iso_day,row['ts_code'],row['title'],row['url'].strip(),timestamp(),run,record_key))
                    self._representative(run, key, record_key, row['title'])
                self.conn.execute('INSERT INTO source_records(source_scope,record_key,legacy_raw_id,metadata,artifact_key,'
                                  'first_seen_run,last_seen_run) VALUES(?,?,NULL,?,?,?,?) '
                                  'ON CONFLICT(source_scope,record_key) DO UPDATE SET last_seen_run=excluded.last_seen_run',
                                  (scope,record_key,json.dumps(row,ensure_ascii=False,separators=(',',':')),key,run,run))
                if key:
                    added += self.conn.execute('INSERT OR IGNORE INTO run_artifacts(run_id,artifact_key) VALUES(?,?)',
                                               (run,key)).rowcount
                    self.conn.execute('UPDATE run_artifacts SET representative_record_key=(SELECT representative_record_key FROM artifacts WHERE artifact_key=?) WHERE run_id=? AND artifact_key=?', (key,run,key))
                else:
                    missing += 1
            self.conn.execute('UPDATE runs SET records_read=records_read+?,artifacts_total=artifacts_total+?,'
                              'missing_url_count=missing_url_count+?,updated_at=?,business_updated_at=?,revision=revision+1 WHERE run_id=?',
                              (len(rows),added,missing,timestamp(),timestamp(),run))
            self.conn.execute('UPDATE run_source_days SET records_committed=records_committed+?,updated_at=? '
                              'WHERE run_id=? AND ann_date=?', (len(rows),timestamp(),run,day))

    def _representative(self, run, key, record_key, title):
        current = self.artifact(key)
        if current['created_run_id'] != run or current['relative_path'] is not None:
            return
        def rank(value, record):
            from src.foundation.clients.announcement_archive.files import title_name
            from src.foundation.clients.announcement_archive.core import FileFailed
            try:
                title_name(value, '', DownloadPolicy.filename_bytes)
                return (0, record)
            except FileFailed:
                return (1, record)
        if rank(title, record_key) < rank(current['title'], current['representative_record_key']):
            self.conn.execute('UPDATE artifacts SET title=?,representative_record_key=? WHERE artifact_key=?',
                              (title,record_key,key))

    def complete_day(self, run: str, day: str, facts: dict):
        with self.conn:
            current = self.conn.execute('SELECT * FROM run_source_days WHERE run_id=? AND ann_date=?', (run,day)).fetchone()
            if (not current or current['state'] != 'reading' or current['records_committed'] != facts['footer_count']
                    or any(current[k] != facts[k] for k in ('opened_dev','opened_ino','size','sha256','footer_count'))):
                raise Blocked('source_day_reconciliation')
            self.conn.execute("UPDATE run_source_days SET state='completed',updated_at=? WHERE run_id=? AND ann_date=?",
                              (timestamp(),run,day))
            self.conn.execute('UPDATE runs SET days_completed=days_completed+1,updated_at=?,business_updated_at=?,revision=revision+1 WHERE run_id=?', (timestamp(),timestamp(),run))

    def seal(self, run: str):
        with self.conn:
            info = self.conn.execute('SELECT * FROM runs WHERE run_id=?', (run,)).fetchone()
            invalid = self.conn.execute("SELECT 1 FROM run_source_days WHERE run_id=? AND "
                                        "(state<>'completed' OR footer_count IS NULL OR records_committed<>footer_count) LIMIT 1",
                                        (run,)).fetchone()
            if (not info or info['phase'] != 'enumerating' or info['days_completed'] != info['days_total'] or invalid):
                raise Blocked('source_enumeration_incomplete')
            self.conn.execute("UPDATE runs SET enumeration_sealed=1,phase='downloading',updated_at=? WHERE run_id=?",
                              (timestamp(),run))

    def phase(self, run: str, phase: str, reason=None):
        with self.conn:
            if phase in ('cancelled','blocked'):
                self.conn.execute("UPDATE run_source_days SET state=?,reason=?,updated_at=? WHERE run_id=? AND state='reading'",
                                  (phase,reason,timestamp(),run))
            self.conn.execute('UPDATE runs SET phase=?,reason=?,updated_at=? WHERE run_id=?', (phase,reason,timestamp(),run))
            if phase in ('completed','partial_failed','cancelled','blocked','stopped','interrupted'):
                now = timestamp()
                self.conn.execute('UPDATE runs SET finished_at=?,revision=revision+1 WHERE run_id=?', (now,run))
                self.conn.execute('UPDATE attempt_log SET ended_at=?,outcome=?,reason=? WHERE run_id=? AND ended_at IS NULL', (now,phase,reason,run))
                self.conn.execute('UPDATE run_sessions SET ended_at=?,reason=? WHERE run_id=? AND ended_at IS NULL', (now,reason or phase,run))
                self.conn.execute('UPDATE archive_execution SET active_run_id=NULL,owner_token=NULL,heartbeat=?,revision=revision+1 WHERE singleton=1 AND active_run_id=?', (now,run))
                self.conn.execute('UPDATE run_artifacts SET claimed_owner=NULL,claimed_at=NULL WHERE run_id=? AND outcome IS NULL', (run,))

    def next_task(self, run: str) -> dict | None:
        info = self.conn.execute('SELECT enumeration_sealed,phase FROM runs WHERE run_id=?', (run,)).fetchone()
        if not info or not info['enumeration_sealed'] or info['phase'] != 'downloading':
            raise Blocked('source_enumeration_not_sealed')
        row = self.conn.execute('SELECT a.* FROM artifacts a JOIN run_artifacts r USING(artifact_key) '
                                'WHERE r.run_id=? AND r.outcome IS NULL ORDER BY r.artifact_key LIMIT 1', (run,)).fetchone()
        if row:
            with self.conn:
                self.conn.execute('UPDATE run_artifacts SET claimed_owner=?,claimed_at=? WHERE run_id=? AND artifact_key=? AND outcome IS NULL',
                                  (self.owner_token,timestamp(),run,row['artifact_key']))
                self.conn.execute('UPDATE runs SET current_artifact_key=? WHERE run_id=?', (row['artifact_key'],run))
        return dict(row) if row else None

    def artifact(self, key: str) -> dict:
        return dict(self.conn.execute('SELECT * FROM artifacts WHERE artifact_key=?', (key,)).fetchone())

    def assign_path(self, key: str, relative: str | None):
        with self.conn:
            self.conn.execute('UPDATE artifacts SET relative_path=?,path_fold=?,updated_at=? WHERE artifact_key=?',
                              (relative, unicodedata.normalize('NFC', relative).casefold() if relative else None, timestamp(), key))

    def path_taken(self, relative: str) -> bool:
        return self.conn.execute('SELECT 1 FROM artifacts WHERE path_fold=?',
                                 (unicodedata.normalize('NFC', relative).casefold(),)).fetchone() is not None

    def state(self, key: str, state: str, error=None):
        with self.conn:
            self.conn.execute('UPDATE artifacts SET state=?,error=?,updated_at=? WHERE artifact_key=?',
                              (state, error, timestamp(), key))

    def attempt(self, run: str, key: str):
        with self.conn:
            self.conn.execute('UPDATE artifacts SET attempts=attempts+1,updated_at=? WHERE artifact_key=?', (timestamp(), key))
            self.conn.execute('UPDATE run_artifacts SET attempts=attempts+1 WHERE run_id=? AND artifact_key=?', (run, key))
            sequence = self.conn.execute('SELECT COALESCE(MAX(attempt_seq),0)+1 FROM attempt_log WHERE run_id=? AND artifact_key=?', (run,key)).fetchone()[0]
            session = self.conn.execute('SELECT MAX(session_seq) FROM run_sessions WHERE run_id=?', (run,)).fetchone()[0]
            self.conn.execute('INSERT INTO attempt_log(run_id,artifact_key,attempt_seq,session_seq,started_at) VALUES(?,?,?,?,?)',
                              (run,key,sequence,session,timestamp()))
            self.conn.execute('UPDATE runs SET attempt_number=? WHERE run_id=?', (sequence,run))

    def finish_attempt(self, run, key, outcome, reason=None, http_status=None, received=0):
        with self.conn:
            self.conn.execute('UPDATE attempt_log SET ended_at=?,outcome=?,reason=?,http_status=?,bytes=? WHERE run_id=? AND artifact_key=? AND ended_at IS NULL',
                              (timestamp(),outcome,reason,http_status,received,run,key))


    def prepared(self, key: str, size: int, digest: str):
        with self.conn:
            self.conn.execute("UPDATE artifacts SET state='prepared',size=?,sha256=?,error=NULL,updated_at=? WHERE artifact_key=?",
                              (size, digest, timestamp(), key))

    def result(self, run: str, key: str, outcome: str):
        columns = {'succeeded': 'succeeded_count', 'skipped': 'skipped_count', 'failed': 'failed_count'}
        column = columns[outcome]
        with self.conn:
            previous = self.conn.execute('SELECT outcome FROM run_artifacts WHERE run_id=? AND artifact_key=?',
                                         (run, key)).fetchone()[0]
            if previous == outcome:
                return
            if previous:
                raise Blocked('run_result_already_final')
            self.conn.execute('UPDATE run_artifacts SET outcome=?,claimed_owner=NULL,claimed_at=NULL WHERE run_id=? AND artifact_key=?', (outcome, run, key))
            self.conn.execute(f'UPDATE runs SET {column}={column}+1,completed_count=completed_count+?,updated_at=?,business_updated_at=?,revision=revision+1 WHERE run_id=?',
                              (0 if previous else 1, timestamp(), timestamp(), run))

    def stats(self, run: str) -> dict:
        counters = self.conn.execute('SELECT * FROM runs WHERE run_id=?', (run,)).fetchone()
        total, done = counters['artifacts_total'], counters['completed_count']
        return dict(records=counters['records_read'], total=total, completed=done, succeeded=counters['succeeded_count'],
                    skipped=counters['skipped_count'], failed=counters['failed_count'],
                    percent=(round(100 * done / total, 2) if total else 100) if counters['enumeration_sealed'] else None,
                    skipped_missing_url=counters['missing_url_count'], current_day=counters['current_day'],
                    days_total=counters['days_total'], days_completed=counters['days_completed'])

    def cooldown(self) -> dict:
        return dict(self.conn.execute('SELECT * FROM cooldown WHERE singleton=1').fetchone())

    def request_started(self):
        with self.conn:
            self.conn.execute('UPDATE cooldown SET request_in_flight=1 WHERE singleton=1')

    def request_finished(self, now: float, until: float, reason: str):
        with self.conn:
            self.conn.execute('UPDATE cooldown SET last_request_finished_at=?,next_request_not_before='
                              'max(next_request_not_before,?),request_in_flight=0,reason=? WHERE singleton=1',
                              (now, until, reason))

    def defer(self, until: float, reason: str):
        with self.conn:
            self.conn.execute('UPDATE cooldown SET next_request_not_before=max(next_request_not_before,?),reason=? WHERE singleton=1',
                              (until, reason))

    def close(self):
        self.conn.close()
