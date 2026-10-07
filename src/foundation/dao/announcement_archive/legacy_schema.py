"""Legacy SQLite shape contract, used only by explicit migration and fixtures."""
from src.foundation.clients.announcement_archive.core import Blocked
from .schema import ADDITIONS, REQUIRED, PRIMARY_KEYS, INDEXES

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


class LegacyLedgerSchema:
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
