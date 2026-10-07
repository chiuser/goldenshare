"""Static PG contract and explicit schema installation; no SQLite runtime dependency."""
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import text

from src.foundation.clients.announcement_archive.core import Blocked, timestamp

SCHEMA = 'announcement_archive'
VERSION = 1
DIRECTORY = Path(__file__).with_name('pg_migrations')
DDL = (DIRECTORY / '001_initial.sql').read_text()
DDL_SHA256 = hashlib.sha256(DDL.encode()).hexdigest()
TABLES = json.loads((DIRECTORY / '001_initial_contract.json').read_text())
LEDGER_TABLES = ('runs', 'artifacts', 'source_records', 'run_artifacts', 'run_source_days',
                 'cooldown', 'archive_execution', 'attempt_log', 'run_sessions', 'command_receipts')
INDEXES = {
    'runs_order': ('runs', 'archive_id,row_seq DESC', None),
    'artifact_date_code': ('artifacts', 'archive_id,ann_date,ts_code,artifact_key', None),
    'artifact_success': ('artifacts', 'archive_id,artifact_key', "state='succeeded'"),
    'source_artifact_order': ('source_records', 'archive_id,artifact_key,row_seq', None),
    'run_pending': ('run_artifacts', 'archive_id,run_id,outcome,artifact_key', None),
    'source_day_state': ('run_source_days', 'archive_id,run_id,state,ann_date', None),
    'attempt_open': ('attempt_log', 'archive_id,run_id,artifact_key', 'ended_at IS NULL'),
    'session_open': ('run_sessions', 'archive_id,run_id', 'ended_at IS NULL'),
    'query_snapshots_pending': ('query_snapshots', 'archive_id,state,created_at', None),
    'query_snapshots_expiry': ('query_snapshots', 'expires_at', None),
    'previews_pending': ('previews', 'archive_id,state,created_at', None),
    'previews_expiry': ('previews', 'expires_at', None),
}


def qualified(table):
    if table not in TABLES:
        raise ValueError('archive_table_invalid')
    return SCHEMA + '.' + table


def schema_exists(connection):
    return connection.scalar(text('SELECT to_regnamespace(:schema)'), {'schema': SCHEMA}) is not None


def validate_schema(connection):
    if not schema_exists(connection):
        raise Blocked('archive_schema_missing')
    objects = set(connection.scalars(text('SELECT table_name FROM information_schema.tables '
        'WHERE table_schema=:schema'), {'schema': SCHEMA}))
    if objects != set(TABLES):
        raise Blocked('archive_schema_invalid')
    version = connection.execute(text('SELECT singleton,version,ddl_sha256 FROM '
                                      'announcement_archive.schema_info')).all()
    if version != [(1, VERSION, DDL_SHA256)]:
        raise Blocked('archive_schema_version_unsupported')
    actual = connection.execute(text('SELECT table_name,column_name,data_type,is_nullable,is_identity '
        'FROM information_schema.columns WHERE table_schema=:schema'), {'schema': SCHEMA}).all()
    types = {'TEXT': 'text', 'BIGINT': 'bigint', 'SMALLINT': 'smallint', 'DOUBLE PRECISION': 'double precision'}
    expected = {(t, c, types[d['type']], 'YES' if d['nullable'] else 'NO',
                 'YES' if d['identity'] else 'NO') for t, table in TABLES.items() for c, d in table['columns'].items()}
    if set(actual) != expected:
        raise Blocked('archive_schema_invalid')
    validate_constraints(connection)


def normalized_sql(value):
    return re.sub(r'\s|[()]|::text|::bigint|::double precision|USING btree', '', value)


def validate_constraints(connection):
    keys = connection.execute(text('''SELECT t.relname,c.contype,
        ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n)
              JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.n),
        c.confdeltype,pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=:schema'''), {'schema': SCHEMA}).all()
    primary = {(table, tuple(columns)) for table, kind, columns, _, _ in keys if kind == 'p'}
    if primary != {(t, tuple(d['primary_key'])) for t, d in TABLES.items()}:
        raise Blocked('archive_schema_invalid')
    unique = {(table, tuple(columns)) for table, kind, columns, _, _ in keys if kind == 'u'}
    if unique != {('archives', ('volume_uuid', 'root_relative_path')), ('artifacts', ('archive_id', 'path_fold')),
                  ('runs', ('archive_id', 'row_seq')), ('source_records', ('archive_id', 'row_seq'))}:
        raise Blocked('archive_schema_invalid')
    foreign = {(table, tuple(columns), delete, definition) for table, kind, columns, delete, definition in keys if kind == 'f'}
    expected_foreign = {(t, ('archive_id',), 'a', 'FOREIGN KEY (archive_id) REFERENCES announcement_archive.archives(archive_id)')
                        for t in TABLES if t not in ('archives', 'schema_info')}
    if foreign != expected_foreign:
        raise Blocked('archive_schema_invalid')
    checks = {(t, normalized_sql(d)) for t, kind, _, _, d in keys if kind == 'c'}
    if checks != {('schema_info', normalized_sql('CHECK ((singleton = 1))')),
                  ('archives', normalized_sql("CHECK ((import_state = ANY (ARRAY['importing'::text, 'ready'::text])))"))}:
        raise Blocked('archive_schema_invalid')
    # Constraint-owned indexes are verified above; explicit query indexes must also match exactly.
    indexes = connection.execute(text('''SELECT i.relname,pg_get_indexdef(i.oid)
        FROM pg_class i JOIN pg_namespace n ON n.oid=i.relnamespace
        WHERE n.nspname=:schema AND i.relkind='i' AND NOT EXISTS (
            SELECT 1 FROM pg_constraint c WHERE c.conindid=i.oid)'''), {'schema': SCHEMA}).all()
    expected_indexes = {name: normalized_sql(f'CREATE INDEX {name} ON {SCHEMA}.{t} ({columns})'
        + (' WHERE '+predicate if predicate else '')) for name, (t, columns, predicate) in INDEXES.items()}
    if {name: normalized_sql(definition) for name, definition in indexes} != expected_indexes:
        raise Blocked('archive_schema_invalid')
    defaults = connection.execute(text('SELECT table_name,column_name,column_default FROM information_schema.columns '
        'WHERE table_schema=:schema AND is_identity=\'NO\''), {'schema': SCHEMA}).all()
    for table, column, value in defaults:
        expected = TABLES[table]['columns'][column]['default']
        if (normalized_sql(value) if value else None) != (normalized_sql(expected) if expected else None):
            raise Blocked('archive_schema_invalid')


def install_schema(connection):
    """Called only by explicit migration APPLY, in its caller's short transaction."""
    if schema_exists(connection):
        validate_schema(connection)
        return False
    connection.exec_driver_sql(DDL)
    connection.execute(text('INSERT INTO announcement_archive.schema_info VALUES(1,:version,:digest,:now)'),
                       {'version': VERSION, 'digest': DDL_SHA256, 'now': timestamp()})
    validate_schema(connection)
    return True
