-- Frozen schema 1 from 777d6901, before the DG consumer migration.

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
