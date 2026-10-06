"""Versioned, additive SQLite archive schema; no runtime orchestration."""
RUN_FIELDS = (
 ('batch_kind', "TEXT NOT NULL DEFAULT 'date'"), ('parent_run_id', 'TEXT'),
 ('retry_of_run_id', 'TEXT'), ('preview_id', 'TEXT'), ('created_at', 'TEXT'),
 ('started_at', 'TEXT'), ('finished_at', 'TEXT'), ('actor_id', 'TEXT'),
 ('owner_token', 'TEXT'), ('heartbeat_at', 'TEXT'), ('business_updated_at', 'TEXT'),
 ('stop_requested_at', 'TEXT'), ('resume_count', 'INTEGER NOT NULL DEFAULT 0'),
 ('current_artifact_key', 'TEXT'), ('attempt_number', 'INTEGER NOT NULL DEFAULT 0'),
 ('bytes_received', 'INTEGER NOT NULL DEFAULT 0'), ('bytes_total', 'INTEGER'),
 ('wait_kind', 'TEXT'), ('next_request_at', 'REAL'), ('revision', 'INTEGER NOT NULL DEFAULT 0'),
 ('check_state', 'TEXT'), ('check_kind', 'TEXT'), ('check_code', 'TEXT'), ('check_updated_at', 'TEXT'),
)
ADDITIONS = dict(runs=RUN_FIELDS,
 artifacts=(('created_run_id','TEXT'),('representative_record_key','TEXT')),
 run_artifacts=(('representative_record_key','TEXT'),('claimed_owner','TEXT'),('claimed_at','TEXT')))
TABLES = (
 """CREATE TABLE attempt_log (
 run_id TEXT NOT NULL, artifact_key TEXT NOT NULL, attempt_seq INTEGER NOT NULL,
 session_seq INTEGER NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
 outcome TEXT, reason TEXT, http_status INTEGER, bytes INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,artifact_key,attempt_seq))""",
 """CREATE TABLE archive_execution (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_run_id TEXT,
 owner_token TEXT, heartbeat TEXT, revision INTEGER NOT NULL DEFAULT 0)""",
 """CREATE TABLE run_sessions (
 run_id TEXT NOT NULL, session_seq INTEGER NOT NULL, started_at TEXT NOT NULL,
 ended_at TEXT, owner_token TEXT NOT NULL, reason TEXT,
 PRIMARY KEY(run_id,session_seq))""",
 """CREATE TABLE command_receipts (
 key TEXT PRIMARY KEY, kind TEXT NOT NULL, payload_hash TEXT NOT NULL,
 result_run_id TEXT, state TEXT NOT NULL, created_at TEXT NOT NULL)""",
)
REQUIRED = dict(
 attempt_log={'run_id','artifact_key','attempt_seq','session_seq','started_at','ended_at',
              'outcome','reason','http_status','bytes'},
 archive_execution={'singleton','active_run_id','owner_token','heartbeat','revision'},
 run_sessions={'run_id','session_seq','started_at','ended_at','owner_token','reason'},
 command_receipts={'key','kind','payload_hash','result_run_id','state','created_at'})
PRIMARY_KEYS = dict(attempt_log=['run_id','artifact_key','attempt_seq'],
 archive_execution=['singleton'],run_sessions=['run_id','session_seq'],command_receipts=['key'])

INDEXES = dict(
 attempt_open=('attempt_log',['run_id','artifact_key'], 'ended_at IS NULL'),
 session_open=('run_sessions',['run_id'], 'ended_at IS NULL'))


def extend_schema(connection):
    for table, fields in ADDITIONS.items():
        for name, declaration in fields:
            connection.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
    for sql in TABLES:
        connection.execute(sql)
    for name, (table, columns, predicate) in INDEXES.items():
        connection.execute(f'CREATE INDEX {name} ON {table}({",".join(columns)}) WHERE {predicate}')
    connection.execute('INSERT INTO archive_execution(singleton) VALUES(1)')
    connection.execute('UPDATE archive SET schema_version=3 WHERE singleton=1')
