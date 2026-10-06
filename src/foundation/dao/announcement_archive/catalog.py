"""Rebuildable local catalog SQL; no source reads or business ranking here."""
from contextlib import contextmanager
import json
import os
import sqlite3
import time
from pathlib import Path

from src.foundation.clients.announcement_archive.core import Blocked, timestamp
from src.foundation.clients.announcement_archive.volume import no_symlinks
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.foundation.clients.announcement_archive.budget import remaining

SCHEMA = (
'''CREATE TABLE catalog_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
 source_scope TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, name_generation TEXT,
 name_version TEXT, dictionary_version TEXT, published_at TEXT,name_facts TEXT)''',
'''CREATE TABLE catalog_days(ann_date TEXT PRIMARY KEY, active_generation TEXT NOT NULL,
 opened_dev INTEGER, opened_ino INTEGER, size INTEGER, mtime_ns INTEGER, sha256 TEXT,
 footer_count INTEGER, published_at TEXT NOT NULL,dictionary_version TEXT NOT NULL)''',
'''CREATE TABLE catalog_records(ann_date TEXT NOT NULL,generation TEXT NOT NULL,record_key TEXT NOT NULL,
 raw_ann_date TEXT NOT NULL,ts_code TEXT,name TEXT,title TEXT,url TEXT,rec_time TEXT,
 artifact_key TEXT,download_url TEXT, PRIMARY KEY(ann_date,generation,record_key))''',
'''CREATE INDEX catalog_code_date ON catalog_records(ts_code,ann_date,generation,record_key)''',
'''CREATE INDEX catalog_date_code ON catalog_records(ann_date,generation,ts_code,record_key)''',
'''CREATE INDEX catalog_artifact ON catalog_records(artifact_key)''',
'''CREATE INDEX catalog_order ON catalog_records(ann_date DESC,(ts_code IS NULL),ts_code,record_key,generation,artifact_key)''',
'''CREATE TABLE company_sources(source_kind TEXT NOT NULL,ts_code TEXT NOT NULL,name TEXT NOT NULL,
 cnspell TEXT,initials TEXT,name_normalized TEXT NOT NULL,ann_date TEXT NOT NULL,generation TEXT NOT NULL,
 record_key TEXT NOT NULL,PRIMARY KEY(source_kind,ts_code,name,ann_date,generation))''',
'''CREATE INDEX company_code ON company_sources(ts_code)''',
'''CREATE INDEX company_initials ON company_sources(initials,ts_code)''',
'''CREATE TABLE catalog_builds(build_id TEXT PRIMARY KEY,start_date TEXT,end_date TEXT,state TEXT,
 current_day TEXT,days_scanned INTEGER DEFAULT 0,records_scanned INTEGER DEFAULT 0,reason TEXT,updated_at TEXT)''',
'''CREATE TABLE query_snapshots(query_id TEXT PRIMARY KEY,conditions TEXT NOT NULL,state TEXT NOT NULL,
 revision INTEGER,archive_identity TEXT,checked_at TEXT,expires_at REAL,reason TEXT,
 dates_scanned INTEGER NOT NULL DEFAULT 0,dates_total INTEGER NOT NULL,records_scanned INTEGER NOT NULL DEFAULT 0,
 status_available INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 preparation_stage TEXT NOT NULL DEFAULT 'indexing',dates_counted INTEGER NOT NULL DEFAULT 0,
 artifacts_checked INTEGER NOT NULL DEFAULT 0)''',
'''CREATE INDEX query_pending ON query_snapshots(state,expires_at)''',
'''CREATE TABLE query_day_counts(query_id TEXT NOT NULL,ann_date TEXT NOT NULL,generation TEXT NOT NULL,
 match_count INTEGER NOT NULL,PRIMARY KEY(query_id,ann_date))''',
'''CREATE TABLE query_presence(query_id TEXT NOT NULL,artifact_key TEXT NOT NULL,
 PRIMARY KEY(query_id,artifact_key))''',
# Preview persistence is consumed in DC3; no HTTP or preview command implemented here.
'''CREATE TABLE previews(preview_id TEXT PRIMARY KEY,start_date TEXT,end_date TEXT,interval_seconds REAL,
 source_scope TEXT,archive_identity TEXT,state TEXT,statistics TEXT,expires_at REAL)''',
'''CREATE TABLE preview_days(preview_id TEXT,ann_date TEXT,generation TEXT,source_facts TEXT,
 PRIMARY KEY(preview_id,ann_date))''',
)


def catalog_path(scope):
    from src.foundation.clients.announcement_archive.core import identity
    return Path.home() / 'Library/Application Support/Goldenshare/announcement-catalog' / identity([scope]) / 'catalog.sqlite'


class Catalog:
    def __init__(self, path, scope, policy=DataCenterPolicy()):
        self.path, self.scope, self.policy = Path(path).absolute(), scope, policy

    @contextmanager
    def connection(self, *, write=False, initialize=False):
        no_symlinks(self.path)
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not self.path.exists():
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
        if not self.path.is_file():
            raise Blocked('catalog_unavailable')
        conn = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'),
                               uri=True, timeout=remaining(self.policy.sql_seconds))
        conn.row_factory = sqlite3.Row
        deadline = time.monotonic() + remaining(self.policy.sql_seconds)
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        try:
            if write:
                conn.execute('PRAGMA synchronous=FULL')
            else:
                conn.execute('PRAGMA query_only=ON')
            if initialize:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not tables:
                    conn.execute('PRAGMA journal_mode=WAL')
                    conn.execute('BEGIN IMMEDIATE')
                    for sql in SCHEMA:
                        conn.execute(sql)
                    conn.execute('INSERT INTO catalog_meta(singleton,schema_version,source_scope) VALUES(1,1,?)', (self.scope,))
                    conn.commit()
                self.validate(conn)
            else:
                meta = conn.execute('SELECT schema_version,source_scope FROM catalog_meta WHERE singleton=1').fetchone()
                if meta is None or tuple(meta) != (1, self.scope):
                    raise Blocked('catalog_schema_invalid')
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield conn
            if write:
                conn.commit()
        except sqlite3.Error as error:
            conn.rollback()
            if getattr(error,'sqlite_errorcode',None)==sqlite3.SQLITE_FULL:
                raise Blocked('insufficient_disk_space') from None
            raise Blocked('catalog_sql_timeout' if time.monotonic() >= deadline else 'catalog_sql_failed') from None
        finally:
            conn.close()

    def validate(self, conn):
        # Compare to the declared schema, including PKs and indexes; no silent auto-rebuild.
        reference = sqlite3.connect(':memory:')
        try:
            for sql in SCHEMA:
                reference.execute(sql)
            tables = {r[0] for r in reference.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                raise Blocked('catalog_schema_invalid')
            for table in tables:
                actual = [tuple(r) for r in conn.execute(f'PRAGMA table_info({table})')]
                expected = reference.execute(f'PRAGMA table_info({table})').fetchall()
                if actual != expected:
                    raise Blocked('catalog_schema_invalid')
            for index, sql in reference.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
                actual = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (index,)).fetchone()
                if actual is None or actual[0] != sql:
                    raise Blocked('catalog_schema_invalid')
            meta = conn.execute('SELECT schema_version,source_scope FROM catalog_meta WHERE singleton=1').fetchone()
            if meta is None or tuple(meta) != (1, self.scope):
                raise Blocked('catalog_schema_invalid')
        finally:
            reference.close()

    def meta(self):
        with self.connection() as conn:
            return dict(conn.execute('SELECT * FROM catalog_meta WHERE singleton=1').fetchone())

    def day(self, day):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM catalog_days WHERE ann_date=?', (day,)).fetchone()
            return dict(row) if row else None

    def add_records(self, day, generation, rows, names):
        with self.connection(write=True) as conn:
            try:
                conn.executemany('INSERT INTO catalog_records VALUES(?,?,?,?,?,?,?,?,?,?,?)', rows)
            except sqlite3.IntegrityError:
                raise Blocked('source_duplicate_record') from None
            conn.executemany('''INSERT INTO company_sources VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_kind,ts_code,name,ann_date,generation) DO UPDATE
                SET record_key=MIN(record_key,excluded.record_key)''', names)

    def add_names(self, rows):
        with self.connection(write=True) as conn:
            conn.executemany('INSERT OR IGNORE INTO company_sources VALUES(?,?,?,?,?,?,?,?,?)', rows)

    def publish_day(self, day, generation, facts, mtime, dictionary_version):
        with self.connection(write=True) as conn:
            actual = conn.execute('SELECT COUNT(*) FROM catalog_records WHERE ann_date=? AND generation=?', (day,generation)).fetchone()[0]
            if actual != facts['footer_count']:
                raise Blocked('source_row_count_mismatch')
            conn.execute('INSERT OR REPLACE INTO catalog_days VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (day,generation,facts['opened_dev'],facts['opened_ino'],facts['size'],mtime,
                          facts['sha256'],facts['footer_count'],timestamp(),dictionary_version))
            conn.execute('UPDATE catalog_meta SET revision=revision+1,published_at=? WHERE singleton=1', (timestamp(),))

    def publish_names(self, generation, version, dictionary_version,facts):
        with self.connection(write=True) as conn:
            conn.execute('''UPDATE catalog_meta SET revision=revision+1,name_generation=?,name_version=?,
              dictionary_version=?,published_at=?,name_facts=? WHERE singleton=1''', (generation,version,dictionary_version,timestamp(),json.dumps(facts,sort_keys=True)))

    def days_after(self,start,end,after=''):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM catalog_days WHERE ann_date BETWEEN ? AND ? AND ann_date>? ORDER BY ann_date LIMIT 500',
                                                     (start,end,after)).fetchmany(500)]

    def query_counts(self,query_id,rows):
        with self.connection(write=True) as conn:
            conn.executemany('INSERT OR REPLACE INTO query_day_counts VALUES(?,?,?,?)',
                             ((query_id,day,generation,count) for day,generation,count in rows))
            conn.execute('UPDATE query_snapshots SET dates_counted=(SELECT COUNT(*) FROM query_day_counts WHERE query_id=?),updated_at=? WHERE query_id=?',
                         (query_id,timestamp(),query_id))

    def create_query(self, query_id, conditions):
        from datetime import date
        days = (date.fromisoformat(conditions['endDate']) - date.fromisoformat(conditions['startDate'])).days + 1
        with self.connection(write=True) as conn:
            conn.execute('''INSERT INTO query_snapshots(query_id,conditions,state,expires_at,dates_total,created_at,updated_at)
                VALUES(?,?,'preparing',?,?,?,?)''',
                         (query_id,json.dumps(conditions,ensure_ascii=False),None,days,timestamp(),timestamp()))

    def query(self, query_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM query_snapshots WHERE query_id=?', (query_id,)).fetchone()
            return dict(row) if row else None

    def update_query(self, query_id, **fields):
        allowed = {'state','revision','archive_identity','checked_at','reason','dates_scanned','records_scanned','status_available','preparation_stage'}
        if not fields or not set(fields) <= allowed:
            raise ValueError('invalid_query_observation')
        fields['updated_at']=timestamp()
        if fields.get('state') in {'ready','error'}:
            fields['expires_at']=time.time()+self.policy.ttl_seconds
        with self.connection(write=True) as conn:
            conn.execute('UPDATE query_snapshots SET '+','.join(k+'=?' for k in fields)+' WHERE query_id=?', (*fields.values(),query_id))

    def reset_presence(self,query_id,check=lambda:None):
        while True:
            check()
            with self.connection(write=True) as conn:
                removed=conn.execute('DELETE FROM query_presence WHERE rowid IN (SELECT rowid FROM query_presence WHERE query_id=? LIMIT 500)',(query_id,)).rowcount
                if removed<500:
                    conn.execute("UPDATE query_snapshots SET artifacts_checked=0,preparation_stage='checkingStatus',updated_at=? WHERE query_id=?",(timestamp(),query_id))
                    return

    def presence(self, query_id, keys,checked_count=None):
        with self.connection(write=True) as conn:
            conn.executemany('INSERT OR IGNORE INTO query_presence VALUES(?,?)', ((query_id,k) for k in keys))
            if checked_count is not None:
                conn.execute('UPDATE query_snapshots SET artifacts_checked=artifacts_checked+?,updated_at=? WHERE query_id=?',
                             (checked_count,timestamp(),query_id))

    def build_progress(self, build_id, start, end, state, current=None, days=0, records=0, reason=None):
        with self.connection(write=True) as conn:
            conn.execute('''INSERT INTO catalog_builds VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(build_id) DO UPDATE SET state=excluded.state,current_day=excluded.current_day,
                days_scanned=excluded.days_scanned,records_scanned=excluded.records_scanned,
                reason=excluded.reason,updated_at=excluded.updated_at''',
                         (build_id,start,end,state,current,days,records,reason,timestamp()))
