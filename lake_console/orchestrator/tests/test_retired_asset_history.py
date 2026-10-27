"""Reviewed retirement: real backup rows in an owned PostgreSQL 18 cluster.

No test connects to the formal instance.  Integration is opt-in through the
four DG_RETIRED_* paths in README §7.5; absent inputs skip only integration.
Four-table DDL comes from the actual backup, not Dagster's possibly different
default schema.  Preservation controls use installed SDK run-table DDL and
EventLogEntry/AssetCheckEvaluation producers, with independent literal counts.
They exercise the SQL boundary, not a complete running Dagster deployment.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

import psycopg2
import pytest
from dagster import AssetKey, AssetMaterialization
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.events import DagsterEvent, StepMaterializationData
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.dagster_run import DagsterRun, DagsterRunStatus
from dagster._core.storage.event_log.base import EventLogRecord
from dagster._core.storage.runs.schema import RunsTable, RunTagsTable, SnapshotsTable
from dagster._serdes import serialize_value
from psycopg2 import sql
from psycopg2.extras import execute_values
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from orchestrator.maintenance import retired_asset_history as maintenance

REVIEWED_SHA = "7bbe2a485f3ea2e7d719a8b44186d8c23983d1d689bc67071c85882a2b7896a0"
EXPECTED_COUNTS = {
    "event_logs": 7537,
    "asset_check_executions": 5601,
    "asset_event_tags": 8,
    "asset_keys": 6,
}
EXPECTED_OWNERS = {
    "raw_tushare_stk_period_bar_month": (821, 609, 2, 1),
    "raw_tushare_stk_period_bar_week": (3457, 2583, 3, 1),
    "raw_tushare_weekly": (3213, 2409, 0, 1),
    "silver_index_daily_active_pool": (2, 0, 0, 1),
    "gold_market_major_indices": (42, 0, 3, 1),
    "raw_tushare_index_daily": (2, 0, 0, 1),
}
FIELD_NAMES = {
    "event_logs": "event_logs",
    "asset_check_executions": "asset_check_executions",
    "asset_event_tags": "asset_event_tags",
    "asset_keys": "asset_keys_rows",
}
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "reports/retired_asset_event_audit_20261027/physical-deletion-manifest.json"
)
PG_BIN = Path("/opt/homebrew/opt/postgresql@18/bin")
CONTROL_KEY = "gold_market_major_indices_daily"
CONTROL_BASE = 1_000_000_000_000
# The actual four-table columns use timestamp WITHOUT time zone.
CONTROL_TIME = datetime(2026, 10, 27, 7, 1, 2, 345678)  # noqa: DTZ001
ENV_INPUTS = (
    "DG_RETIRED_BACKUP",
    "DG_RETIRED_MANIFEST",
    "DG_RETIRED_RECEIPT",
    "DG_RETIRED_EVIDENCE",
)


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def _frozen_ids(manifest, table):
    return sorted(row["id"] for row in manifest["payload"][FIELD_NAMES[table]])


def _read_rows(conn, manifest, table):
    # Independent SQL and complete JSON equality, not the production digest helper.
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT to_jsonb(t) FROM public.{} t WHERE id=ANY(%s) ORDER BY id")
            .format(sql.Identifier(table)),
            (_frozen_ids(manifest, table),),
        )
        return [row[0] for row in cur.fetchall()]


def _assert_original_rows(conn, manifest, original):
    for table, count in EXPECTED_COUNTS.items():
        actual = _read_rows(conn, manifest, table)
        assert len(actual) == count
        assert actual == original[table]
    conn.rollback()


@pytest.fixture(scope="module")
def reviewed_manifest():
    return json.loads(DEFAULT_MANIFEST.read_text())


def test_manifest_matches_independent_reviewed_counts(reviewed_manifest):
    assert hashlib.sha256(_canonical(reviewed_manifest["payload"])).hexdigest() == REVIEWED_SHA
    actual = maintenance.load_manifest(DEFAULT_MANIFEST)
    assert actual == reviewed_manifest
    for table, count in EXPECTED_COUNTS.items():
        records = actual["payload"][FIELD_NAMES[table]]
        assert len(records) == count
        assert len({row["id"] for row in records}) == count
        owners = Counter(row["asset_key"] for row in records)
        index = list(EXPECTED_COUNTS).index(table)
        assert owners == {
            key: counts[index] for key, counts in EXPECTED_OWNERS.items() if counts[index]
        }


@pytest.mark.parametrize("change", ["key", "id", "count", "digest"])
def test_changed_manifest_is_rejected(tmp_path, reviewed_manifest, change):
    changed = json.loads(json.dumps(reviewed_manifest))
    if change == "key":
        changed["payload"]["asset_keys"][0] = CONTROL_KEY
    elif change == "id":
        changed["payload"]["event_logs"][0]["id"] = CONTROL_BASE
    elif change == "count":
        changed["payload"]["asset_event_tags"].pop()
    else:
        changed["sha256_canonical_payload"] = "0" * 64
    path = tmp_path / "changed-manifest.json"
    path.write_text(json.dumps(changed))
    with pytest.raises(maintenance.RetirementError):
        maintenance.load_manifest(path)


def test_unapproved_table_is_rejected(reviewed_manifest):
    with pytest.raises(maintenance.RetirementError, match="Unapproved table"):
        maintenance.ids(reviewed_manifest, "runs")


def test_corrupt_or_broadly_readable_recovery_file_is_rejected(tmp_path, reviewed_manifest):
    path = tmp_path / "corrupt.json.gz"
    path.write_bytes(gzip.compress(b'{"payload": {}, "sha256": "wrong"}'))
    path.chmod(0o600)
    with pytest.raises(maintenance.RetirementError, match="digest mismatch"):
        maintenance.load_backup(path, reviewed_manifest)
    path.chmod(0o644)
    with pytest.raises(maintenance.RetirementError, match="permissions"):
        maintenance.load_backup(path, reviewed_manifest)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://test@remote.invalid:5432/goldenshare_dagster",
        "postgresql://test@127.0.0.1:5432/another_database",
        "postgresql://test@127.0.0.1:55439/goldenshare_dagster",
    ],
)
def test_formal_connection_rejects_unapproved_address_before_connect(tmp_path, monkeypatch, url):
    # Only configuration parsing is replaced. No connection (formal or temporary) is made.
    (tmp_path / "dagster.yaml").write_text(
        json.dumps({"storage": {"postgres": {"postgres_url": url}}})
    )
    monkeypatch.setattr(maintenance, "FORMAL_HOME", tmp_path)

    def forbidden_connect(*args, **kwargs):
        raise AssertionError("An unapproved address reached psycopg2.connect")

    monkeypatch.setattr(maintenance.psycopg2, "connect", forbidden_connect)
    with pytest.raises(maintenance.RetirementError, match="approved local formal"):
        maintenance.connect_formal(readonly=True)


def test_valid_formal_url_and_distinct_report_paths(tmp_path):
    maintenance.validate_formal_url("postgresql://test@127.0.0.1:5432/goldenshare_dagster")
    maintenance.validate_paths(
        tmp_path / "manifest.json", tmp_path / "backup.gz", tmp_path / "report.json"
    )


@pytest.mark.parametrize("protected", ["manifest", "backup", "evidence", "receipt"])
def test_report_cannot_overwrite_recovery_inputs(tmp_path, protected):
    paths = {name: tmp_path / name for name in ("manifest", "backup", "evidence", "receipt")}
    paths["evidence"].write_text(json.dumps({"backup_receipt_path": str(paths["receipt"])}))
    with pytest.raises(maintenance.RetirementError, match="cannot overwrite"):
        maintenance.validate_paths(
            paths["manifest"], paths["backup"], paths[protected], paths["evidence"]
        )


@pytest.mark.parametrize("kind", ["ASSET_CHECK_EVALUATION", "ASSET_MATERIALIZATION"])
def test_body_owner_cannot_disagree_with_frozen_owner(kind):
    # Installed SDK produces a valid body for the current asset.  SQL/frozen owner
    # deliberately still name the retired asset. Byte length matches so only the
    # owner disagreement, not a coincidental size change, can reject this case.
    old_owner = "raw_tushare_weekly"
    if kind == "ASSET_CHECK_EVALUATION":
        entry = _control_check(123)
        ownership_basis = "exact_owned_check_events"
    else:
        entry = _entry(kind=kind, data=StepMaterializationData(
            AssetMaterialization(asset_key=CONTROL_KEY)
        ))
        ownership_basis = "direct_owned_events"
    body = serialize_value(entry)
    expected = {
        "id": 77, "run_id": "", "dagster_event_type": kind,
        "event_bytes": len(body.encode()), "asset_key": old_owner,
        "ownership_basis": ownership_basis,
    }
    if kind == "ASSET_CHECK_EVALUATION":
        expected.update(indexed_asset_key=json.dumps([old_owner]),
                        check_name="isolated_control_check", target_materialization_id="123")
    manifest = {"payload": {field: [] for field in FIELD_NAMES.values()}}
    manifest["payload"]["event_logs"] = [expected]
    data = {table: [] for table in EXPECTED_COUNTS}
    data["event_logs"] = [{
        "id": 77, "run_id": "", "dagster_event_type": kind,
        "event": body, "asset_key": json.dumps([old_owner]),
    }]
    with pytest.raises(maintenance.RetirementError, match="Event body identity changed"):
        maintenance.assert_manifest_rows(manifest, data)


class _IsolationEvidence:
    """Registered session hook: a failed/aborted pytest session cannot publish success."""

    def __init__(self, paths):
        self.paths = paths
        self.result = None
        self.cluster_cleaned = False
        self.frozen_hashes = {name: _sha(path) for name, path in paths.items()
                              if name != "DG_RETIRED_EVIDENCE"}
        self.tool_sha = _sha(maintenance.__file__)
        self.test_sha = _sha(__file__)

    def pytest_sessionfinish(self, session, exitstatus):
        if exitstatus != 0 or self.result is None or not self.cluster_cleaned:
            return
        collected = Counter(
            item.nodeid.rsplit("::", 1)[-1].split("[", 1)[0]
            for item in session.items if Path(str(item.path)).resolve() == Path(__file__).resolve()
        )
        expected_tests = {
            "test_manifest_matches_independent_reviewed_counts": 1,
            "test_changed_manifest_is_rejected": 4,
            "test_unapproved_table_is_rejected": 1,
            "test_corrupt_or_broadly_readable_recovery_file_is_rejected": 1,
            "test_formal_connection_rejects_unapproved_address_before_connect": 3,
            "test_valid_formal_url_and_distinct_report_paths": 1,
            "test_report_cannot_overwrite_recovery_inputs": 4,
            "test_body_owner_cannot_disagree_with_frozen_owner": 2,
            "test_real_backup_delete_rollback_and_restore": 1,
        }
        if collected != expected_tests:
            return  # A filtered subset must not authorize formal apply.
        assert self.frozen_hashes == {
            name: _sha(path) for name, path in self.paths.items() if name != "DG_RETIRED_EVIDENCE"
        }, "A tested recovery input changed before evidence publication"
        assert self.tool_sha == _sha(maintenance.__file__) and self.test_sha == _sha(__file__)
        report = {
            **self.result,
            "status": "passed",
            "manifest_sha256": REVIEWED_SHA,
            "backup_sha256": _sha(self.paths["DG_RETIRED_BACKUP"]),
            "tool_sha256": self.tool_sha,
            "backup_receipt_path": str(self.paths["DG_RETIRED_RECEIPT"]),
            "backup_receipt_sha256": _sha(self.paths["DG_RETIRED_RECEIPT"]),
            "test_sha256": self.test_sha,
            "temporary_cluster_removed": True,
        }
        maintenance.atomic_json(self.paths["DG_RETIRED_EVIDENCE"], report)


@pytest.fixture(scope="session")
def recovery_inputs(request):
    present = {name: os.environ.get(name) for name in ENV_INPUTS}
    if not any(present.values()):
        pytest.skip("Real-backup integration requires the four explicit DG_RETIRED_* paths")
    assert all(present.values()), "All four DG_RETIRED_* paths must be supplied together"
    paths = {name: Path(value).resolve() for name, value in present.items()}
    assert len(set(paths.values())) == 4, "Input and evidence paths must be distinct"
    assert not paths["DG_RETIRED_EVIDENCE"].exists(), "Use a fresh isolation evidence path"
    manifest = maintenance.load_manifest(paths["DG_RETIRED_MANIFEST"])
    backup = maintenance.load_backup(paths["DG_RETIRED_BACKUP"], manifest)
    receipt = json.loads(paths["DG_RETIRED_RECEIPT"].read_text())
    assert receipt["status"] == "passed"
    assert receipt["readback_verified"] is True
    assert receipt["manifest_sha256"] == REVIEWED_SHA
    assert receipt["backup_sha256"] == _sha(paths["DG_RETIRED_BACKUP"])
    assert Path(receipt["backup_path"]).resolve() == paths["DG_RETIRED_BACKUP"]
    assert receipt["table_counts"] == EXPECTED_COUNTS
    # Independently decode the actual recovery envelope for all-column expected rows.
    with gzip.open(paths["DG_RETIRED_BACKUP"], "rb") as stream:
        envelope = json.loads(stream.read(64 * 1024 * 1024 + 1))
    assert envelope["payload"] == backup
    assert hashlib.sha256(_canonical(envelope["payload"])).hexdigest() == envelope["sha256"]
    for table, count in EXPECTED_COUNTS.items():
        assert len(envelope["payload"]["tables"][table]) == count
        owners = Counter()
        for row in envelope["payload"]["tables"][table]:
            if row["asset_key"] is not None:
                owner = json.loads(row["asset_key"])
            else:
                assert table == "event_logs"
                owner = json.loads(row["event"])["dagster_event"]["event_specific_data"]["asset_key"]["path"]
            assert len(owner) == 1
            owners[owner[0]] += 1
        index = list(EXPECTED_COUNTS).index(table)
        assert owners == {
            key: counts[index] for key, counts in EXPECTED_OWNERS.items() if counts[index]
        }
    evidence = _IsolationEvidence(paths)
    request.config.pluginmanager.register(evidence, "retired_asset_isolation_evidence")
    return manifest, backup, envelope["payload"]["tables"], evidence


class _TemporaryPostgres:
    def __init__(self, root, env):
        self.root = root
        self.env = env
        self.connection_args = {
            "host": str(root / "socket"),
            "port": 55439,
            "user": "dg_retired_test",
            "dbname": "dg_retired_verify",
            "connect_timeout": 5,
            "options": "-c timezone=UTC -c statement_timeout=15000 -c transaction_timeout=45000",
        }

    def connect(self, *, readonly=False):
        conn = psycopg2.connect(**self.connection_args)
        conn.set_session(
            readonly=readonly,
            isolation_level="REPEATABLE READ" if readonly else "READ COMMITTED",
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_setting('data_directory'),current_setting('listen_addresses'),"
                "inet_server_addr(),current_database()"
            )
            directory, listeners, address, database = cur.fetchone()
        assert Path(directory).resolve() == (self.root / "data").resolve()
        assert listeners == "" and address is None and database == "dg_retired_verify"
        conn.rollback()
        return conn

    def run(self, binary, *arguments):
        return subprocess.run(
            [str(PG_BIN / binary), *map(str, arguments)],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )


@pytest.fixture(scope="session")
def isolated_postgres(recovery_inputs):
    _, _, _, evidence = recovery_inputs
    root = Path(tempfile.mkdtemp(prefix="dg-retired-pg.", dir="/private/tmp"))
    root.chmod(0o700)
    (root / "socket").mkdir(mode=0o700)
    # Also clear the calling Python process: libpq otherwise consults PGHOSTADDR
    # and service settings even when subprocesses receive a sanitized environment.
    environment = pytest.MonkeyPatch()
    for key in list(os.environ):
        if key.startswith("PG") or key in {"DAGSTER_HOME", "TUSHARE_TOKEN"}:
            environment.delenv(key)
    env = dict(os.environ)
    cluster = _TemporaryPostgres(root, env)
    started = False
    try:
        assert "18.4" in cluster.run("initdb", "--version").stdout
        cluster.run(
            "initdb", "-D", root / "data", "-U", "dg_retired_test",
            "--encoding=UTF8", "--no-locale", "--auth=trust",
        )
        cluster.run(
            "pg_ctl", "-D", root / "data", "-l", root / "server.log", "-o",
            f"-c listen_addresses='' -c unix_socket_directories='{root / 'socket'}' "
            "-c unix_socket_permissions=0700 -p 55439", "-w", "start",
        )
        started = True
        with closing(psycopg2.connect(**{**cluster.connection_args, "dbname": "postgres"})) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("CREATE DATABASE dg_retired_verify")
        with closing(cluster.connect()):
            pass
        yield cluster
    finally:
        # Never remove data beneath a running server, including a partially failed start.
        try:
            if started or (root / "data/postmaster.pid").exists():
                cluster.run("pg_ctl", "-D", root / "data", "-m", "fast", "-w", "stop")
            shutil.rmtree(root)
            evidence.cluster_cleaned = True
        finally:
            environment.undo()


def _create_real_schema(conn, backup):
    with conn.cursor() as cur:
        for table, definition in backup["schema"].items():
            not_null = {
                item["definition"].removeprefix("NOT NULL ").strip('"'): item["name"]
                for item in definition["constraints"] if item["type"] == "n"
            }
            columns = []
            for column in definition["columns"]:
                assert not column["identity"], "Identity columns are outside the reviewed schema"
                if column["sequence"]:
                    sequence = sql.Identifier(*column["sequence"].split("."))
                    cur.execute(sql.SQL("CREATE SEQUENCE {} AS bigint").format(sequence))
                clause = sql.SQL("{} {}").format(
                    sql.Identifier(column["name"]), sql.SQL(column["type"])
                )
                if column["default_expr"] is not None:
                    clause += sql.SQL(" DEFAULT " + column["default_expr"])
                if column["not_null"]:
                    clause += sql.SQL(" CONSTRAINT {} NOT NULL").format(
                        sql.Identifier(not_null[column["name"]])
                    )
                columns.append(clause)
            cur.execute(sql.SQL("CREATE TABLE public.{} ({})").format(
                sql.Identifier(table), sql.SQL(",").join(columns)
            ))
            for column in definition["columns"]:
                if column["sequence"]:
                    cur.execute(sql.SQL("ALTER SEQUENCE {} OWNED BY public.{}.{}").format(
                        sql.Identifier(*column["sequence"].split(".")),
                        sql.Identifier(table), sql.Identifier(column["name"]),
                    ))
            for constraint in definition["constraints"]:
                if constraint["type"] == "n":
                    continue
                assert constraint["type"] in {"p", "u", "c"}
                cur.execute(sql.SQL("ALTER TABLE public.{} ADD CONSTRAINT {} {}").format(
                    sql.Identifier(table), sql.Identifier(constraint["name"]),
                    sql.SQL(constraint["definition"]),
                ))
            cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename=%s",
                        (table,))
            existing = {row[0] for row in cur.fetchall()}
            for index in definition["indexes"]:
                if index["indexname"] not in existing:
                    cur.execute(index["indexdef"])
        # Real SDK 1.13.26 types/FKs for these three preservation-control tables.
        for table in (SnapshotsTable, RunsTable, RunTagsTable):
            cur.execute(str(CreateTable(table).compile(dialect=postgresql.dialect())))
    conn.commit()
    assert maintenance.schema_snapshot(conn) == backup["schema"]
    conn.rollback()


def _entry(run_id="", *, kind=None, data=None):
    event = None if kind is None else DagsterEvent(
        event_type_value=kind, job_name="isolated_retirement_control", event_specific_data=data,
    )
    return EventLogEntry(
        error_info=None, level=20, user_message="保留控制行：NULL／微秒", run_id=run_id,
        timestamp=1793084462.345678, job_name="isolated_retirement_control", dagster_event=event,
    )


def _insert_event(conn, event_id, entry, *, owner=None):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO event_logs(id,run_id,event,dagster_event_type,"timestamp",asset_key) '
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (event_id, entry.run_id, serialize_value(entry),
             entry.dagster_event.event_type_value if entry.dagster_event else None,
             CONTROL_TIME, json.dumps([owner]) if owner is not None else None),
        )


def _control_check(target_id):
    return _entry(kind="ASSET_CHECK_EVALUATION", data=AssetCheckEvaluation(
        asset_key=AssetKey(CONTROL_KEY), check_name="isolated_control_check", passed=True,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=target_id, run_id="", timestamp=1793084462.345678,
        ),
    ))


def _insert_preservation_controls(conn, manifest, backup):
    run_ids = sorted({row["run_id"] for row in manifest["payload"]["event_logs"] if row["run_id"]})
    assert len(run_ids) == 9
    names = backup["graph"]["asset_names"]
    assert len(names) == len(set(names)) == 180 and CONTROL_KEY in names
    snapshot_ids = [f"isolated-retirement-snapshot-{index}" for index in range(5)]
    materialization = _entry(kind="ASSET_MATERIALIZATION", data=StepMaterializationData(
        AssetMaterialization(asset_key=CONTROL_KEY, tags={
            "dagster/input_event_pointer/gold_market_major_indices_daily": str(CONTROL_BASE + 1000),
        })
    ))
    with conn.cursor() as cur:
        execute_values(cur, "INSERT INTO snapshots(id,snapshot_id,snapshot_body,snapshot_type) VALUES %s",
                       [(CONTROL_BASE + i, value, b"isolated SDK schema control", "PIPELINE")
                        for i, value in enumerate(snapshot_ids)])
        run_rows = []
        for index, run_id in enumerate(run_ids):
            status = DagsterRunStatus.SUCCESS if index < 8 else DagsterRunStatus.FAILURE
            snapshot = snapshot_ids[index % 5]
            run = DagsterRun(job_name="isolated_retirement_control", run_id=run_id,
                             status=status, job_snapshot_id=snapshot)
            run_rows.append((CONTROL_BASE + index, run_id, snapshot, run.job_name,
                             status.value, serialize_value(run), CONTROL_TIME, CONTROL_TIME))
        execute_values(cur, "INSERT INTO runs(id,run_id,snapshot_id,pipeline_name,status,run_body,"
                       "create_timestamp,update_timestamp) VALUES %s", run_rows)
        execute_values(cur, 'INSERT INTO run_tags(id,run_id,"key",value) VALUES %s',
                       [(CONTROL_BASE + i, run_ids[i % 9], f"isolation/{i}", None if i == 0 else "保留")
                        for i in range(23)])
        asset_rows = []
        for index, name in enumerate(names):
            cache = serialize_value(EventLogRecord(CONTROL_BASE + 1000, materialization)) \
                if name == CONTROL_KEY else None
            asset_rows.append((CONTROL_BASE + index, json.dumps([name]), cache, CONTROL_TIME))
        execute_values(cur, "INSERT INTO asset_keys(id,asset_key,last_materialization,create_timestamp) "
                       "VALUES %s", asset_rows)
    for index in range(319):
        _insert_event(conn, CONTROL_BASE + 2000 + index, _entry(run_ids[index % 9]))
    # Two additional runless events prove empty run_id does not widen deletion.
    _insert_event(conn, CONTROL_BASE + 1000, materialization, owner=CONTROL_KEY)
    check = _control_check(CONTROL_BASE + 1000)
    _insert_event(conn, CONTROL_BASE + 1001, check)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_check_executions(id,asset_key,check_name,run_id,execution_status,"
            "evaluation_event,evaluation_event_storage_id,materialization_event_storage_id) "
            "VALUES(%s,%s,%s,'','SUCCEEDED',%s,%s,%s)",
            (CONTROL_BASE, json.dumps([CONTROL_KEY]), "isolated_control_check", serialize_value(check),
             CONTROL_BASE + 1001, CONTROL_BASE + 1000),
        )
        cur.execute('INSERT INTO asset_event_tags(id,event_id,asset_key,"key",value) VALUES(%s,%s,%s,%s,NULL)',
                    (CONTROL_BASE, CONTROL_BASE + 1000, json.dumps([CONTROL_KEY]), "dagster/data_version"))
    conn.commit()
    assert {table: len(rows) for table, rows in maintenance.protected_state(conn, manifest).items()} == {
        "runs": 9, "run_tags": 23, "snapshots": 5, "event_logs": 319, "asset_keys": 180,
    }
    conn.rollback()


def _control_hashes(conn, manifest):
    """All non-target rows, including the runless controls excluded by run IDs."""
    result = {}
    with conn.cursor() as cur:
        for table in (*EXPECTED_COUNTS, "runs", "run_tags", "snapshots"):
            statement = sql.SQL("SELECT id,md5(to_jsonb(t)::text) FROM public.{} t").format(
                sql.Identifier(table)
            )
            params = ()
            if table in EXPECTED_COUNTS:
                statement += sql.SQL(" WHERE NOT(id=ANY(%s))")
                params = (_frozen_ids(manifest, table),)
            cur.execute(statement + sql.SQL(" ORDER BY id"), params)
            result[table] = cur.fetchall()
    return result


def _sequences(conn, backup):
    result = {}
    with conn.cursor() as cur:
        for definition in backup["schema"].values():
            for column in definition["columns"]:
                if column["sequence"]:
                    cur.execute(sql.SQL("SELECT last_value,is_called FROM {}").format(
                        sql.Identifier(*column["sequence"].split("."))
                    ))
                    result[column["sequence"]] = cur.fetchone()
    return result


def _assert_state(cluster, manifest, backup, expected):
    with closing(cluster.connect(readonly=True)) as reader:
        assert maintenance.classify_state(reader, manifest, backup) == expected


def test_real_backup_delete_rollback_and_restore(isolated_postgres, recovery_inputs):
    """One real import; boundary mutations roll back rather than repeatedly importing."""
    cluster = isolated_postgres
    manifest, backup, original, evidence = recovery_inputs
    conn = cluster.connect()
    try:
        _create_real_schema(conn, backup)
        sequence_before = _sequences(conn, backup)
        conn.rollback()
        assert maintenance.restore_backup_rows(conn, manifest, backup) == "restored"
        _assert_original_rows(conn, manifest, original)
        assert _sequences(conn, backup) == sequence_before
        conn.rollback()
        _insert_preservation_controls(conn, manifest, backup)
        controls = _control_hashes(conn, manifest)
        conn.rollback()
        _assert_state(cluster, manifest, backup, "intact")

        # Exercise the actual backup writer/readback against the owned temporary PG.
        copy_path = cluster.root / "backup-readback/rows.json.gz"
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        receipt = maintenance.create_backup(conn, manifest, backup["graph"], copy_path)
        assert receipt["table_counts"] == EXPECTED_COUNTS and receipt["readback_verified"] is True
        with gzip.open(copy_path, "rb") as stream:
            assert json.load(stream)["payload"]["tables"] == original
        copy_hash = _sha(copy_path)
        with pytest.raises(maintenance.RetirementError, match="overwrite"):
            maintenance.create_backup(conn, manifest, backup["graph"], copy_path)
        assert _sha(copy_path) == copy_hash
        conn.rollback()
        conn.set_session(readonly=False, isolation_level="READ COMMITTED")

        target_id = _frozen_ids(manifest, "event_logs")[0]
        check_id = _frozen_ids(manifest, "asset_check_executions")[0]
        rejected = []

        def reject_after_mutation(label, mutate, *, message):
            mutate()
            with pytest.raises(maintenance.RetirementError, match=message):
                maintenance.apply_backup(conn, manifest, backup)
            _assert_original_rows(conn, manifest, original)
            assert _control_hashes(conn, manifest) == controls
            conn.rollback()
            rejected.append(label)

        def execute(statement, params=()):
            with conn.cursor() as cur:
                cur.execute(statement, params)

        reject_after_mutation("foreign_check", lambda: execute(
            "UPDATE asset_check_executions SET materialization_event_storage_id=%s WHERE id=%s",
            (target_id, CONTROL_BASE)), message="reverse references")
        reject_after_mutation("null_check_owner", lambda: execute(
            "UPDATE asset_check_executions SET asset_key=NULL,evaluation_event_storage_id=%s WHERE id=%s",
            (target_id, CONTROL_BASE)), message="reverse references")
        reject_after_mutation("foreign_tag", lambda: execute(
            "UPDATE asset_event_tags SET event_id=%s WHERE id=%s", (target_id, CONTROL_BASE)),
            message="reverse references")
        reject_after_mutation("foreign_cache", lambda: execute(
            "UPDATE asset_keys SET last_materialization=jsonb_set(last_materialization::jsonb,"
            "'{storage_id}',to_jsonb(%s::bigint))::text WHERE asset_key=%s",
            (target_id, json.dumps([CONTROL_KEY]))), message="reverse references")

        target_materialization = next(
            row["id"] for row in manifest["payload"]["event_logs"]
            if row["dagster_event_type"] == "ASSET_MATERIALIZATION"
        )
        bad_check = json.loads(serialize_value(_control_check(target_materialization)))
        # Deliberate malformed upstream evidence: still valid JSON, no path for NOT/NULL to hide.
        del bad_check["dagster_event"]["event_specific_data"]["asset_key"]
        reject_after_mutation("raw_check_missing_owner", lambda: execute(
            "UPDATE event_logs SET event=%s WHERE id=%s", (json.dumps(bad_check), CONTROL_BASE + 1001)),
            message="reverse references")
        reject_after_mutation("foreign_raw_check", lambda: execute(
            "UPDATE event_logs SET event=%s WHERE id=%s",
            (serialize_value(_control_check(target_materialization)), CONTROL_BASE + 1001)),
            message="reverse references")
        retired_pointer = _entry(kind="ASSET_MATERIALIZATION", data=StepMaterializationData(
            AssetMaterialization(asset_key=CONTROL_KEY, tags={
                "dagster/input_event_pointer/raw_tushare_weekly": str(target_materialization),
            })
        ))
        reject_after_mutation("foreign_materialization_pointer", lambda: execute(
            "UPDATE event_logs SET event=%s WHERE id=%s",
            (serialize_value(retired_pointer), CONTROL_BASE + 1000)), message="reverse references")
        reject_after_mutation("changed_frozen_body", lambda: execute(
            "UPDATE event_logs SET event=event || ' ' WHERE id=%s", (target_id,)),
            message="Full row contents changed")
        reject_after_mutation("changed_frozen_null", lambda: execute(
            "UPDATE asset_check_executions SET check_name=NULL WHERE id=%s", (check_id,)),
            message="Full row contents changed")
        reject_after_mutation("changed_frozen_timestamp", lambda: execute(
            'UPDATE event_logs SET "timestamp"=TIMESTAMP \'2001-01-01 01:02:03.123456\' WHERE id=%s',
            (target_id,)), message="Full row contents changed")
        reject_after_mutation("active_run", lambda: execute(
            "UPDATE runs SET status='STARTED' WHERE id=%s", (CONTROL_BASE,)),
            message="Active/queued")
        reject_after_mutation("changed_schema", lambda: execute(
            "ALTER TABLE event_logs ADD COLUMN isolation_unapproved text"), message="schema changed")

        class InjectedFailure(RuntimeError):
            pass

        for failed_table in ("asset_event_tags", "asset_check_executions", "event_logs", "asset_keys"):
            def fail_after_step(table, target=failed_table):
                if table == target:
                    raise InjectedFailure(table)
            with pytest.raises(InjectedFailure, match=failed_table):
                maintenance.apply_backup(conn, manifest, backup, after_step=fail_after_step)
            _assert_original_rows(conn, manifest, original)
            assert _control_hashes(conn, manifest) == controls
            conn.rollback()

        with closing(cluster.connect()) as blocker:
            with blocker.cursor() as cur:
                cur.execute("UPDATE event_logs SET step_key=step_key WHERE id=%s", (target_id,))
            before = time.monotonic()
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                maintenance.apply_backup(conn, manifest, backup)
            assert time.monotonic() - before < 5, "NOWAIT unexpectedly waited for a writer"
            blocker.rollback()
        _assert_original_rows(conn, manifest, original)

        def disconnect_after_step(table):
            if table == "asset_check_executions":
                conn.close()
                raise InjectedFailure("client disconnected before commit")

        with pytest.raises((InjectedFailure, psycopg2.Error)):
            maintenance.apply_backup(conn, manifest, backup, after_step=disconnect_after_step)
        conn = cluster.connect()
        _assert_original_rows(conn, manifest, original)
        assert _control_hashes(conn, manifest) == controls
        conn.rollback()

        execute("DELETE FROM event_logs WHERE id=%s", (target_id,))
        assert maintenance.classify_state(conn, manifest, backup) == "partial_or_changed"
        with pytest.raises(maintenance.RetirementError, match="partial/conflicting"):
            maintenance.restore_backup_rows(conn, manifest, backup)
        _assert_original_rows(conn, manifest, original)
        assert _control_hashes(conn, manifest) == controls
        conn.rollback()
        execute("UPDATE event_logs SET event=event || ' ' WHERE id=%s", (target_id,))
        assert maintenance.classify_state(conn, manifest, backup) == "partial_or_changed"
        with pytest.raises(maintenance.RetirementError, match="partial/conflicting"):
            maintenance.restore_backup_rows(conn, manifest, backup)
        _assert_original_rows(conn, manifest, original)
        assert _control_hashes(conn, manifest) == controls
        conn.rollback()

        # A genuinely new normal event is allowed; exact-prefix control pointer is already present.
        _insert_event(conn, CONTROL_BASE + 5000, _entry())
        conn.commit()
        controls = _control_hashes(conn, manifest)
        conn.rollback()
        # An existing REPEATABLE READ snapshot must see all four old sets after the writer commits.
        with closing(cluster.connect(readonly=True)) as old_snapshot:
            with old_snapshot.cursor() as cur:
                cur.execute("SELECT count(*) FROM event_logs")
                assert cur.fetchone()[0] > 7537
            result = maintenance.apply_backup(conn, manifest, backup)
            assert result["status"] == "committed"
            assert result["removed"] == EXPECTED_COUNTS
            assert result["protected_counts"] == {
                "runs": 9, "run_tags": 23, "snapshots": 5, "event_logs": 319, "asset_keys": 180,
            }
            assert maintenance.classify_state(old_snapshot, manifest, backup) == "intact"
        _assert_state(cluster, manifest, backup, "deleted")
        for table in EXPECTED_COUNTS:
            assert _read_rows(conn, manifest, table) == []
        assert _control_hashes(conn, manifest) == controls
        conn.rollback()

        # A reused original ID cannot be overwritten during recovery.
        execute("INSERT INTO event_logs(id,event) VALUES(%s,'{}')", (target_id,))
        with pytest.raises(maintenance.RetirementError, match="partial/conflicting"):
            maintenance.restore_backup_rows(conn, manifest, backup)
        _assert_state(cluster, manifest, backup, "deleted")
        assert maintenance.restore_backup_rows(conn, manifest, backup) == "restored"
        _assert_original_rows(conn, manifest, original)
        assert maintenance.restore_backup_rows(conn, manifest, backup) == "already_restored"
        _assert_original_rows(conn, manifest, original)
        assert _control_hashes(conn, manifest) == controls
        assert _sequences(conn, backup) == sequence_before
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute('SELECT "timestamp",step_key FROM event_logs WHERE id=%s', (CONTROL_BASE + 1000,))
            assert cur.fetchone() == (CONTROL_TIME, None)
        conn.rollback()
        evidence.result = {
            "table_counts": EXPECTED_COUNTS,
            "restored_full_columns_equal": True,
            "protected_counts": result["protected_counts"],
            "reverse_reference_and_precondition_cases": rejected,
            "delete_failure_rollback_tables": [
                "asset_event_tags", "asset_check_executions", "event_logs", "asset_keys",
            ],
            "client_disconnect_rollback": True,
            "nowait_writer_rejected": True,
            "consistent_snapshot_verified": True,
            "partial_and_conflicting_restore_rejected": True,
            "repeated_restore_recognized": True,
            "sequence_state_unchanged": True,
            "current_prefix_and_new_normal_event_allowed": True,
        }
    finally:
        if not conn.closed:
            conn.rollback()
            conn.close()
