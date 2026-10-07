"""Static legacy catalog schema validation for explicit read-only migration only.

No file opener, runtime query, initialization, schema upgrade or write API.
"""
import sqlite3

from src.foundation.clients.announcement_archive.core import Blocked

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
# Preview facts remain local and never authorize HTTP by themselves.
'''CREATE TABLE previews(preview_id TEXT PRIMARY KEY,start_date TEXT,end_date TEXT,interval_seconds REAL,
 source_scope TEXT,archive_identity TEXT,state TEXT,statistics TEXT,expires_at REAL)''',
'''CREATE TABLE preview_days(preview_id TEXT,ann_date TEXT,generation TEXT,source_facts TEXT,
 PRIMARY KEY(preview_id,ann_date))''',
)

SCHEMA_V1 = SCHEMA

PREVIEW_ARTIFACTS = "CREATE TABLE preview_artifacts(preview_id TEXT NOT NULL,artifact_key TEXT NOT NULL,PRIMARY KEY(preview_id,artifact_key))"

SCHEMA = (*SCHEMA, PREVIEW_ARTIFACTS)


class LegacyCatalogSchema:
    def __init__(self, scope):
        self.scope = scope

    def validate(self, conn, version=2):
        # Compare to the declared schema, including PKs and indexes; no silent auto-rebuild.
        reference = sqlite3.connect(':memory:')
        try:
            for sql in (SCHEMA_V1 if version == 1 else SCHEMA):
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
            if meta is None or tuple(meta) != (version, self.scope):
                raise Blocked('catalog_schema_invalid')
        finally:
            reference.close()
