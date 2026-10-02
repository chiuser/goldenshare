from __future__ import annotations

import json
import sqlite3
import unicodedata
import uuid
from pathlib import Path

from .core import Blocked, DownloadOptions, identity, timestamp


SCHEMA = '''
CREATE TABLE IF NOT EXISTS archive (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
 volume_uuid TEXT NOT NULL, root_relative_path TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, start_date TEXT, end_date TEXT, interval_seconds REAL,
 source_scope TEXT, upper_id INTEGER DEFAULT 0, after_id INTEGER DEFAULT 0,
 phase TEXT NOT NULL, records_read INTEGER DEFAULT 0, reason TEXT, updated_at TEXT,
 missing_url_count INTEGER DEFAULT 0,
 artifacts_total INTEGER DEFAULT 0, completed_count INTEGER DEFAULT 0,
 succeeded_count INTEGER DEFAULT 0, skipped_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS artifacts (
 artifact_key TEXT PRIMARY KEY, ann_date TEXT, ts_code TEXT, title TEXT, url TEXT,
 relative_path TEXT, path_fold TEXT UNIQUE, state TEXT NOT NULL DEFAULT 'pending',
 error TEXT, attempts INTEGER NOT NULL DEFAULT 0, size INTEGER, sha256 TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS source_records (
 source_scope TEXT, row_key_hash TEXT, raw_id INTEGER, metadata TEXT, artifact_key TEXT,
 first_seen_run TEXT, last_seen_run TEXT, PRIMARY KEY(source_scope,row_key_hash));
CREATE TABLE IF NOT EXISTS run_artifacts (
 run_id TEXT, artifact_key TEXT, outcome TEXT, attempts INTEGER DEFAULT 0,
 PRIMARY KEY(run_id,artifact_key));
CREATE TABLE IF NOT EXISTS cooldown (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_request_finished_at REAL DEFAULT 0,
 next_request_not_before REAL DEFAULT 0, request_in_flight INTEGER DEFAULT 0, reason TEXT);
CREATE INDEX IF NOT EXISTS run_pending ON run_artifacts(run_id,outcome,artifact_key);
'''


class Ledger:
    def __init__(self, path: Path, volume_uuid: str, relative_root: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute('PRAGMA journal_mode=DELETE')
            self.conn.execute('PRAGMA synchronous=FULL')
            self.conn.executescript(SCHEMA)
            if "missing_url_count" not in {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}:
                self.conn.execute("ALTER TABLE runs ADD COLUMN missing_url_count INTEGER NOT NULL DEFAULT 0")
            with self.conn:
                self.conn.execute('INSERT OR IGNORE INTO archive VALUES(1,1,?,?,?)',
                                  (volume_uuid, relative_root, timestamp()))
                existing = self.conn.execute('SELECT * FROM archive').fetchone()
                if (existing['schema_version'] != 1 or existing['volume_uuid'] != volume_uuid
                        or existing['root_relative_path'] != relative_root):
                    raise Blocked('archive_identity_mismatch')
                self.conn.execute('INSERT OR IGNORE INTO cooldown(singleton) VALUES(1)')
        except BaseException:
            self.conn.close()
            raise

    def begin_run(self, options: DownloadOptions, scope: str) -> str:
        run = uuid.uuid4().hex
        with self.conn:
            self.conn.execute("UPDATE runs SET phase='cancelled',reason='process_exit_recovered',updated_at=? "
                              "WHERE phase IN ('enumerating','downloading')", (timestamp(),))
            self.conn.execute('INSERT INTO runs(run_id,start_date,end_date,interval_seconds,source_scope,phase,updated_at) '
                              "VALUES(?,?,?,?,?,'enumerating',?)", (run, options.start_date.isoformat(),
                              options.end_date.isoformat(), options.interval_seconds, scope, timestamp()))
        return run

    def set_upper(self, run: str, upper_id: int):
        with self.conn:
            self.conn.execute('UPDATE runs SET upper_id=?,updated_at=? WHERE run_id=?',
                              (upper_id, timestamp(), run))

    def ingest(self, run: str, scope: str, rows: list[dict]):
        # Rows and cursor commit together. A failed batch never advances after_id.
        with self.conn:
            added = 0
            for row in rows:
                day, code, url = str(row['ann_date']), row['ts_code'], (row['url'] or '').strip()
                key = identity([day, code, url]) if url else None
                if key:
                    self.conn.execute('INSERT OR IGNORE INTO artifacts(artifact_key,ann_date,ts_code,title,url,updated_at) '
                                      'VALUES(?,?,?,?,?,?)', (key, day, code, row['title'], url, timestamp()))
                self.conn.execute('INSERT INTO source_records VALUES(?,?,?,?,?,?,?) '
                                  'ON CONFLICT(source_scope,row_key_hash) DO UPDATE SET '
                                  'raw_id=excluded.raw_id,metadata=excluded.metadata,artifact_key=excluded.artifact_key,'
                                  'last_seen_run=excluded.last_seen_run', (scope, row['row_key_hash'], row['id'],
                                  json.dumps(row, ensure_ascii=False, default=str), key, run, run))
                if key:
                    added += self.conn.execute('INSERT OR IGNORE INTO run_artifacts(run_id,artifact_key) VALUES(?,?)',
                                               (run, key)).rowcount
                else:
                    self.conn.execute('UPDATE runs SET missing_url_count=missing_url_count+1 WHERE run_id=?', (run,))
            if rows:
                self.conn.execute('UPDATE runs SET after_id=?,records_read=records_read+?,artifacts_total=artifacts_total+?, '
                                  'updated_at=? WHERE run_id=?', (max(r['id'] for r in rows), len(rows), added, timestamp(), run))

    def phase(self, run: str, phase: str, reason=None):
        with self.conn:
            self.conn.execute('UPDATE runs SET phase=?,reason=?,updated_at=? WHERE run_id=?',
                              (phase, reason, timestamp(), run))

    def next_task(self, run: str) -> dict | None:
        row = self.conn.execute('SELECT a.* FROM artifacts a JOIN run_artifacts r USING(artifact_key) '
                                'WHERE r.run_id=? AND r.outcome IS NULL ORDER BY r.artifact_key LIMIT 1', (run,)).fetchone()
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
            self.conn.execute('UPDATE run_artifacts SET outcome=? WHERE run_id=? AND artifact_key=?', (outcome, run, key))
            if previous:
                self.conn.execute(f'UPDATE runs SET {columns[previous]}={columns[previous]}-1 WHERE run_id=?', (run,))
            self.conn.execute(f'UPDATE runs SET {column}={column}+1,completed_count=completed_count+?,updated_at=? WHERE run_id=?',
                              (0 if previous else 1, timestamp(), run))

    def stats(self, run: str) -> dict:
        counters = self.conn.execute('SELECT * FROM runs WHERE run_id=?', (run,)).fetchone()
        total, done = counters['artifacts_total'], counters['completed_count']
        return dict(records=counters['records_read'], total=total, completed=done, succeeded=counters['succeeded_count'],
                    skipped=counters['skipped_count'], failed=counters['failed_count'],
                    percent=round(100 * done / total, 2) if total else 100,
                    skipped_missing_url=counters['missing_url_count'])

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
