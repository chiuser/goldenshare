"""Retire only the reviewed six-asset manifest; no Dagster instance or Lake access.

The CLI is deliberately bound to this reviewed manifest and local instance.
Library functions accept an explicit connection for isolated PostgreSQL tests.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import stat
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import yaml
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, execute_values

MANIFEST_SHA = "7bbe2a485f3ea2e7d719a8b44186d8c23983d1d689bc67071c85882a2b7896a0"
FORMAL_HOME = Path("/Users/congming/.goldenshare/dagster_home")
BACKUP_ROOT = Path("/Users/congming/.goldenshare/dagster_backups")
COUNTS = {
    "event_logs": 7537,
    "asset_check_executions": 5601,
    "asset_event_tags": 8,
    "asset_keys": 6,
}
FIELDS = {**{t: t for t in COUNTS}, "asset_keys": "asset_keys_rows"}
DELETE_ORDER = (
    "asset_event_tags",
    "asset_check_executions",
    "event_logs",
    "asset_keys",
)
RETIRED_KEYS = frozenset(
    {
        "raw_tushare_stk_period_bar_month",
        "raw_tushare_stk_period_bar_week",
        "raw_tushare_weekly",
        "silver_index_daily_active_pool",
        "gold_market_major_indices",
        "raw_tushare_index_daily",
    }
)
ACTIVE = ["QUEUED", "NOT_STARTED", "STARTING", "STARTED", "CANCELING"]
CHECK_TYPES = ["ASSET_CHECK_EVALUATION", "ASSET_CHECK_EVALUATION_PLANNED"]
CHECK_PATH = "{dagster_event,event_specific_data,asset_key,path}"
TARGET_PATH = (
    "{dagster_event,event_specific_data,target_materialization_data,storage_id}"
)
TAGS_PATH = "{dagster_event,event_specific_data,materialization,tags}"


class RetirementError(RuntimeError):
    """A precondition failed; do not retry or broaden the manifest."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    payload = manifest["payload"]
    if (
        digest(payload) != MANIFEST_SHA
        or manifest["sha256_canonical_payload"] != MANIFEST_SHA
    ):
        raise RetirementError("Manifest differs from the reviewed canonical payload")
    if set(payload["asset_keys"]) != RETIRED_KEYS:
        raise RetirementError("Retired key set differs")
    for table, count in COUNTS.items():
        records = payload[FIELDS[table]]
        if len(records) != count or len({r["id"] for r in records}) != count:
            raise RetirementError(f"Wrong reviewed IDs for {table}")
        if any(r["asset_key"] not in RETIRED_KEYS for r in records):
            raise RetirementError(f"Unexpected owner in {table}")
    return manifest


def ids(manifest: dict, table: str) -> list[int]:
    if table not in COUNTS:
        raise RetirementError("Unapproved table")
    return [r["id"] for r in manifest["payload"][FIELDS[table]]]


def serialized_keys(manifest: dict) -> list[str]:
    return [json.dumps([key]) for key in manifest["payload"]["asset_keys"]]


def query(conn, statement, params=(), *, limit=20000) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(statement, params)
        records = cur.fetchmany(limit + 1)
        if len(records) > limit:
            raise RetirementError("Query exceeded its declared metadata row bound")
        return [dict(r) for r in records]


def scalar(conn, statement, params=()):
    rows = query(conn, statement, params, limit=1)
    return next(iter(rows[0].values()))


def fetch_rows(conn, manifest: dict, table: str) -> list[dict]:
    statement = sql.SQL(
        "SELECT to_jsonb(t) AS row FROM public.{} t "
        "WHERE id=ANY(%s::bigint[]) ORDER BY id"
    ).format(sql.Identifier(table))
    return [
        r["row"]
        for r in query(conn, statement, (ids(manifest, table),), limit=COUNTS[table])
    ]


def schema_snapshot(conn) -> dict:
    schema = {}
    for table in COUNTS:
        relation = "public." + table
        columns = query(
            conn,
            "SELECT a.attname AS name,format_type(a.atttypid,a.atttypmod) AS type,"
            "a.attnotnull AS not_null,pg_get_expr(d.adbin,d.adrelid) AS default_expr,"
            "a.attidentity AS identity,pg_get_serial_sequence(%s,a.attname) AS sequence "
            "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid "
            "AND d.adnum=a.attnum WHERE a.attrelid=%s::regclass "
            "AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum",
            (relation, relation),
            limit=30,
        )
        constraints = query(
            conn,
            "SELECT conname AS name,contype AS type,"
            "pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid=%s::regclass OR confrelid=%s::regclass ORDER BY conname",
            (relation, relation),
            limit=30,
        )
        indexes = query(
            conn,
            "SELECT indexname,indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND tablename=%s ORDER BY indexname",
            (table,),
            limit=20,
        )
        unsafe = query(
            conn,
            "SELECT tgname AS name FROM pg_trigger WHERE tgrelid=%s::regclass "
            "AND NOT tgisinternal UNION ALL SELECT rulename FROM pg_rules "
            "WHERE schemaname='public' AND tablename=%s",
            (relation, table),
            limit=20,
        )
        relation_state = query(
            conn,
            "SELECT relkind,relrowsecurity,relispartition FROM pg_class "
            "WHERE oid=%s::regclass",
            (relation,),
            limit=1,
        )
        if (
            unsafe
            or any(c["type"] == "f" for c in constraints)
            or relation_state
            != [{"relkind": "r", "relrowsecurity": False, "relispartition": False}]
            or any(c["identity"] for c in columns)
        ):
            raise RetirementError(f"Unexpected trigger/rule/FK/RLS/identity on {table}")
        schema[table] = {
            "columns": columns,
            "constraints": constraints,
            "indexes": indexes,
            "relation_state": relation_state,
        }
    return schema


def connection_identity(conn) -> dict:
    return query(
        conn,
        "SELECT current_database() AS database,current_user AS username,"
        "current_setting('data_directory') AS data_directory,"
        "current_setting('server_version') AS server_version,"
        "system_identifier::text FROM pg_control_system()",
        limit=1,
    )[0]


def validate_formal_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.port not in {None, 5432}
        or parsed.path != "/goldenshare_dagster"
        or parsed.query
        or parsed.fragment
    ):
        raise RetirementError("Connection is not the approved local formal database")


def connect_formal(*, readonly: bool):
    config = yaml.safe_load((FORMAL_HOME / "dagster.yaml").read_text())
    url = config["storage"]["postgres"]["postgres_url"]
    validate_formal_url(url)
    conn = psycopg2.connect(
        url,
        application_name="retire_six_reviewed_assets",
        options="-c statement_timeout=15000 -c lock_timeout=1000 "
        "-c timezone=UTC -c transaction_timeout=45000",
    )
    conn.set_session(
        readonly=readonly,
        isolation_level="REPEATABLE READ" if readonly else "READ COMMITTED",
    )
    if connection_identity(conn)["database"] != "goldenshare_dagster":
        conn.close()
        raise RetirementError("Unexpected server database identity")
    return conn


def verify_graph(manifest: dict) -> dict:
    gql = "query { assetNodes { assetKey { path } dependencyKeys { path } } }"
    url = "http://127.0.0.1:3000/graphql?" + urllib.parse.urlencode({"query": gql})
    with urllib.request.urlopen(url, timeout=15) as response:
        response = json.load(response)
    if response.get("errors"):
        raise RetirementError("GraphQL query failed")
    nodes = response["data"]["assetNodes"]
    names = {"/".join(n["assetKey"]["path"]) for n in nodes}
    dependencies = {"/".join(d["path"]) for n in nodes for d in n["dependencyKeys"]}
    from orchestrator.defs.catalog.lake_assets import list_lake_asset_catalog_entries

    registry = {e.asset_key for e in list_lake_asset_catalog_entries()}
    if len(names) != 180 or names != registry or RETIRED_KEYS & (names | dependencies):
        raise RetirementError(
            "Current registry/graph no longer matches the reviewed scope"
        )
    return {"asset_names": sorted(names), "definition_count": len(names)}


def assert_no_active_runs(conn) -> None:
    if scalar(conn, "SELECT count(*) FROM runs WHERE status=ANY(%s)", (ACTIVE,)):
        raise RetirementError("Active/queued runs exist; do not block their writes")


def assert_owned_scope(conn, manifest: dict) -> None:
    keys = serialized_keys(manifest)
    for table, count in COUNTS.items():
        if table == "event_logs":
            statement = (
                "SELECT id FROM event_logs WHERE asset_key=ANY(%s) UNION "
                "SELECT id FROM event_logs WHERE dagster_event_type=ANY(%s) "
                "AND EXISTS(SELECT 1 FROM unnest(%s::text[]) k(v) "
                "WHERE strpos(event,k.v)>0) "
                "AND event::jsonb#>>%s=ANY(%s)"
            )
            params = (
                keys,
                CHECK_TYPES,
                [json.dumps(k) for k in RETIRED_KEYS],
                CHECK_PATH,
                keys,
            )
        else:
            statement = sql.SQL(
                "SELECT id FROM public.{} WHERE asset_key=ANY(%s)"
            ).format(sql.Identifier(table))
            params = (keys,)
        actual = {r["id"] for r in query(conn, statement, params, limit=count + 1)}
        if actual != set(ids(manifest, table)):
            raise RetirementError(f"Owned row set changed for {table}")


def assert_references_clear(conn, manifest: dict) -> dict:
    keys = serialized_keys(manifest)
    event_ids = ids(manifest, "event_logs")
    materialization_ids = {
        r["id"]
        for r in manifest["payload"]["event_logs"]
        if r["dagster_event_type"] == "ASSET_MATERIALIZATION"
    }
    materialization_ids.update(
        r["cached_materialization_storage_id"]
        for r in manifest["payload"]["asset_keys_rows"]
    )
    text_ids = [str(i) for i in materialization_ids]
    pointer_keys = ["dagster/input_event_pointer/" + k for k in RETIRED_KEYS]
    checks = {
        "check_index": (
            (
                "SELECT count(*) FROM asset_check_executions WHERE "
                "NOT(COALESCE(asset_key=ANY(%s),FALSE)) AND (evaluation_event_storage_id=ANY(%s::bigint[]) "
                "OR materialization_event_storage_id=ANY(%s::bigint[]))"
            ),
            (keys, event_ids, list(materialization_ids | set(event_ids))),
        ),
        "foreign_tags": (
            (
                "SELECT count(*) FROM asset_event_tags WHERE event_id=ANY(%s::bigint[]) "
                "AND NOT(COALESCE(asset_key=ANY(%s),FALSE))"
            ),
            (event_ids, keys),
        ),
        "other_cache": (
            (
                "SELECT count(*) FROM asset_keys WHERE NOT(COALESCE(asset_key=ANY(%s),FALSE)) "
                "AND (last_materialization::jsonb->>'storage_id'=ANY(%s) "
                "OR (last_materialization::jsonb#>'{event_log_entry,dagster_event,event_specific_data,materialization,tags}') ?| %s)"
            ),
            (
                keys,
                [str(i) for i in set(event_ids) | materialization_ids],
                pointer_keys,
            ),
        ),
        "raw_check_target": (
            (
                "SELECT count(*) FROM event_logs WHERE "
                "dagster_event_type='ASSET_CHECK_EVALUATION' "
                "AND NOT(COALESCE((event::jsonb#>>%s)=ANY(%s),FALSE)) "
                "AND event::jsonb#>>%s=ANY(%s)"
            ),
            (CHECK_PATH, keys, TARGET_PATH, text_ids),
        ),
        "materialization_pointer": (
            (
                "SELECT count(*) FROM event_logs WHERE "
                "dagster_event_type='ASSET_MATERIALIZATION' "
                "AND (event::jsonb#>%s) ?| %s"
            ),
            (TAGS_PATH, pointer_keys),
        ),
    }
    results = {
        name: scalar(conn, statement, params)
        for name, (statement, params) in checks.items()
    }
    if any(results.values()):
        raise RetirementError(f"New reverse references found: {results}")
    return results


def protected_state(conn, manifest: dict) -> dict:
    run_ids = sorted(
        {r["run_id"] for r in manifest["payload"]["event_logs"] if r["run_id"]}
    )
    tables = {
        "runs": ("run_id=ANY(%s)", (run_ids,)),
        "run_tags": ("run_id=ANY(%s)", (run_ids,)),
        "snapshots": (
            "snapshot_id IN (SELECT snapshot_id FROM runs WHERE run_id=ANY(%s))",
            (run_ids,),
        ),
        "event_logs": (
            "run_id=ANY(%s) AND NOT(id=ANY(%s::bigint[]))",
            (run_ids, ids(manifest, "event_logs")),
        ),
        "asset_keys": ("NOT(asset_key=ANY(%s))", (serialized_keys(manifest),)),
    }
    result = {}
    for table, (predicate, params) in tables.items():
        statement = sql.SQL(
            "SELECT id,md5(to_jsonb(t)::text) AS hash FROM public.{} t WHERE "
            + predicate
            + " ORDER BY id"
        ).format(sql.Identifier(table))
        result[table] = query(conn, statement, params, limit=1000)
    return result


def assert_rows_match_backup(conn, manifest: dict, backup: dict) -> None:
    for table in COUNTS:
        if digest(fetch_rows(conn, manifest, table)) != backup["table_digests"][table]:
            raise RetirementError(f"Full row contents changed for {table}")


def assert_manifest_rows(manifest: dict, data: dict) -> None:
    """Verify frozen identities before making a new full-content recovery copy."""
    for table in COUNTS:
        expected = {r["id"]: r for r in manifest["payload"][FIELDS[table]]}
        for row in data[table]:
            old = expected[row["id"]]
            if table == "event_logs":
                event = json.loads(row["event"])["dagster_event"]
                details = event["event_specific_data"]
                kind = row["dagster_event_type"]
                owner_container = details
                owner_field = "asset_key"
                if kind == "ASSET_MATERIALIZATION":
                    owner_container = details["materialization"]
                elif kind == "FRESHNESS_STATE_CHANGE":
                    owner_field = "key"
                body_owner = owner_container[owner_field]["path"]
                if (
                    body_owner != [old["asset_key"]]
                    or event["event_type_value"] != kind
                ):
                    raise RetirementError(
                        f"Event body identity changed for {row['id']}"
                    )
                projected = {
                    "id": row["id"],
                    "run_id": row["run_id"],
                    "dagster_event_type": kind,
                    "event_bytes": len(row["event"].encode()),
                    "asset_key": old["asset_key"],
                    "ownership_basis": old["ownership_basis"],
                }
                if old["ownership_basis"] == "direct_owned_events":
                    if json.loads(row["asset_key"]) != body_owner:
                        raise RetirementError(
                            "SQL event owner disagrees with actual body"
                        )
                else:
                    target = details.get("target_materialization_data")
                    target_id = target.get("storage_id") if target else None
                    projected.update(
                        {
                            "indexed_asset_key": row["asset_key"],
                            "check_name": details["check_name"],
                            "target_materialization_id": str(target_id)
                            if target_id is not None
                            else None,
                        }
                    )
            elif table == "asset_check_executions":
                projected = {
                    k: row[k] for k in old if k not in {"asset_key", "body_bytes"}
                }
                projected["asset_key"] = json.loads(row["asset_key"])[0]
                projected["body_bytes"] = (
                    len(row["evaluation_event"].encode())
                    if row["evaluation_event"] is not None
                    else None
                )
            elif table == "asset_event_tags":
                projected = {k: row[k] for k in old}
                projected["asset_key"] = json.loads(row["asset_key"])[0]
            else:
                projected = {
                    "id": row["id"],
                    "asset_key": json.loads(row["asset_key"])[0],
                    "last_run_id": row["last_run_id"],
                    "has_cached_materialization": row["last_materialization"]
                    is not None,
                    "has_partition_cache": row["cached_status_data"] is not None,
                    "cached_materialization_storage_id": json.loads(
                        row["last_materialization"]
                    )["storage_id"]
                    if row["last_materialization"]
                    else None,
                }
                for field in ("last_materialization_timestamp", "wipe_timestamp"):
                    projected[field] = row[field]
                    if row[field] is not None:
                        projected[field] = datetime.fromisoformat(
                            row[field]
                        ).isoformat()
                old = dict(old)
                for field in ("last_materialization_timestamp", "wipe_timestamp"):
                    if old[field] is not None:
                        old[field] = datetime.fromisoformat(old[field]).isoformat()
            if projected != old:
                raise RetirementError(
                    f"Frozen projection changed for {table}/{row['id']}"
                )


def classify_state(conn, manifest: dict, backup: dict) -> str:
    """Caller must use one REPEATABLE READ transaction for all four reads."""
    actual = {table: fetch_rows(conn, manifest, table) for table in COUNTS}
    if all(not rows for rows in actual.values()):
        return "deleted"
    if all(
        len(actual[t]) == COUNTS[t] and digest(actual[t]) == backup["table_digests"][t]
        for t in COUNTS
    ):
        return "intact"
    return "partial_or_changed"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_backup(path: Path, manifest: dict) -> dict:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RetirementError("Recovery file permissions are too broad")
    with gzip.open(path, "rb") as stream:
        content = stream.read(64 * 1024 * 1024 + 1)
    if len(content) > 64 * 1024 * 1024:
        raise RetirementError("Recovery file exceeds its scope budget")
    envelope = json.loads(content)
    backup = envelope["payload"]
    if (
        envelope["sha256"] != digest(backup)
        or backup["manifest_sha256"] != MANIFEST_SHA
    ):
        raise RetirementError("Recovery file digest mismatch")
    for table, count in COUNTS.items():
        rows = backup["tables"][table]
        if (
            len(rows) != count
            or [r["id"] for r in rows] != sorted(ids(manifest, table))
            or digest(rows) != backup["table_digests"][table]
        ):
            raise RetirementError(f"Recovery rows changed for {table}")
        expected_columns = {c["name"] for c in backup["schema"][table]["columns"]}
        if any(set(r) != expected_columns for r in rows):
            raise RetirementError(f"Recovery columns incomplete for {table}")
    return backup


def create_backup(conn, manifest: dict, graph: dict, path: Path) -> dict:
    if path.exists():
        raise RetirementError("Do not overwrite an existing recovery file")
    assert_owned_scope(conn, manifest)
    data = {table: fetch_rows(conn, manifest, table) for table in COUNTS}
    assert_manifest_rows(manifest, data)
    backup = {
        "created_at_utc": utc_now(),
        "manifest_sha256": MANIFEST_SHA,
        "identity": connection_identity(conn),
        "schema": schema_snapshot(conn),
        "tables": data,
        "table_digests": {t: digest(rows) for t, rows in data.items()},
        "protected": protected_state(conn, manifest),
        "graph": graph,
    }
    content = canonical({"payload": backup, "sha256": digest(backup)})
    if len(content) > 64 * 1024 * 1024:
        raise RetirementError("Recovery file exceeds the documented scope budget")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as compressed:
                compressed.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    restored = load_backup(path, manifest)
    if restored != backup:
        raise RetirementError("Recovery file readback differs")
    return {
        "status": "passed",
        "created_at_utc": utc_now(),
        "backup_path": str(path),
        "backup_sha256": file_sha(path),
        "uncompressed_bytes": len(content),
        "compressed_bytes": path.stat().st_size,
        "manifest_sha256": MANIFEST_SHA,
        "table_counts": COUNTS,
        "table_digests": backup["table_digests"],
        "schema_sha256": digest(backup["schema"]),
        "readback_verified": True,
    }


def delete_frozen_rows(
    conn, manifest: dict, after_step: Callable | None = None
) -> dict:
    result = {}
    for table in DELETE_ORDER:
        statement = sql.SQL(
            "DELETE FROM public.{} WHERE id=ANY(%s::bigint[]) RETURNING id"
        ).format(sql.Identifier(table))
        rows = query(conn, statement, (ids(manifest, table),), limit=COUNTS[table])
        if {r["id"] for r in rows} != set(ids(manifest, table)):
            raise RetirementError(f"Wrong deletion set for {table}")
        result[table] = len(rows)
        if after_step:
            after_step(table)
    return result


def apply_backup(
    conn, manifest: dict, backup: dict, *, after_step: Callable | None = None
) -> dict:
    """One transaction; caller handles commit errors by a separate read-only status."""
    started = time.monotonic()
    try:
        assert_no_active_runs(conn)
        with conn.cursor() as cur:
            cur.execute(
                "LOCK TABLE public.event_logs, public.asset_check_executions, "
                "public.asset_event_tags, public.asset_keys "
                "IN SHARE ROW EXCLUSIVE MODE NOWAIT"
            )
        assert_no_active_runs(conn)
        if schema_snapshot(conn) != backup["schema"]:
            raise RetirementError("Formal table schema changed since the recovery copy")
        assert_rows_match_backup(conn, manifest, backup)
        assert_owned_scope(conn, manifest)
        references = assert_references_clear(conn, manifest)
        protected = protected_state(conn, manifest)
        expected_counts = {
            "runs": 9,
            "run_tags": 23,
            "snapshots": 5,
            "event_logs": 319,
            "asset_keys": 180,
        }
        if {t: len(rows) for t, rows in protected.items()} != expected_counts:
            raise RetirementError("Protected record identity/count scope changed")
        current_names = {
            json.loads(r["asset_key"])[0]
            for r in query(
                conn,
                "SELECT asset_key FROM asset_keys WHERE NOT(asset_key=ANY(%s))",
                (serialized_keys(manifest),),
                limit=180,
            )
        }
        if current_names != set(backup["graph"]["asset_names"]):
            raise RetirementError(
                "Current asset index names differ from the verified graph"
            )
        removed = delete_frozen_rows(conn, manifest, after_step)
        if protected_state(conn, manifest) != protected:
            raise RetirementError(
                "A protected row changed inside the deletion transaction"
            )
        if any(fetch_rows(conn, manifest, table) for table in COUNTS):
            raise RetirementError("Frozen IDs remain after deletion")
        assert_no_active_runs(conn)
        if time.monotonic() - started > 40:
            raise RetirementError(
                "Do not commit a maintenance transaction over its budget"
            )
        conn.commit()
        return {
            "status": "committed",
            "removed": removed,
            "references": references,
            "protected_sha256": digest(protected),
            "protected_counts": {t: len(r) for t, r in protected.items()},
            "transaction_seconds": round(time.monotonic() - started, 3),
        }
    except BaseException:
        try:
            if not conn.closed:
                conn.rollback()
        except psycopg2.Error:
            conn.close()
        raise


def restore_backup_rows(conn, manifest: dict, backup: dict) -> str:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "LOCK TABLE public.event_logs, public.asset_check_executions, "
                "public.asset_event_tags, public.asset_keys "
                "IN SHARE ROW EXCLUSIVE MODE NOWAIT"
            )
        state = classify_state(conn, manifest, backup)
        if state == "intact":
            conn.rollback()
            return "already_restored"
        if state != "deleted" or schema_snapshot(conn) != backup["schema"]:
            raise RetirementError(
                "Restore refuses partial/conflicting rows or changed schema"
            )
        for table in (
            "event_logs",
            "asset_check_executions",
            "asset_event_tags",
            "asset_keys",
        ):
            columns = [c["name"] for c in backup["schema"][table]["columns"]]
            statement = sql.SQL(
                "INSERT INTO public.{t} ({cols}) "
                "SELECT {selected} FROM (VALUES %s) v(payload) "
                "CROSS JOIN LATERAL jsonb_populate_record(NULL::public.{t}, "
                "v.payload) r"
            ).format(
                t=sql.Identifier(table),
                cols=sql.SQL(",").join(map(sql.Identifier, columns)),
                selected=sql.SQL(",").join(
                    sql.SQL("r.{}").format(sql.Identifier(c)) for c in columns
                ),
            )
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    statement.as_string(conn),
                    [(canonical(r).decode(),) for r in backup["tables"][table]],
                    template="(%s::jsonb)",
                    page_size=250,
                )
        assert_rows_match_backup(conn, manifest, backup)
        conn.commit()
        return "restored"
    except BaseException:
        try:
            if not conn.closed:
                conn.rollback()
        except psycopg2.Error:
            conn.close()
        raise


def status_report(manifest: dict, backup: dict) -> dict:
    conn = connect_formal(readonly=True)
    try:
        state = classify_state(conn, manifest, backup)
        protected = protected_state(conn, manifest)
        retained = {t: len(r) for t, r in protected.items()}
        immutable = {t: r for t, r in protected.items() if t != "asset_keys"}
        old_immutable = {
            t: r for t, r in backup["protected"].items() if t != "asset_keys"
        }
        return {
            "state": state,
            "protected_counts": retained,
            "retained_history_unchanged": immutable == old_immutable,
            "asset_index_names": [
                r["asset_key"]
                for r in query(
                    conn,
                    "SELECT asset_key FROM asset_keys ORDER BY asset_key",
                    limit=200,
                )
            ],
            "checked_at_utc": utc_now(),
        }
    finally:
        conn.rollback()
        conn.close()


def check_isolation_evidence(path: Path, backup_path: Path) -> None:
    evidence = json.loads(path.read_text())
    if (
        evidence.get("status") != "passed"
        or evidence.get("manifest_sha256") != MANIFEST_SHA
        or evidence.get("backup_sha256") != file_sha(backup_path)
        or evidence.get("tool_sha256") != file_sha(Path(__file__))
    ):
        raise RetirementError(
            "Isolation evidence does not match this tool/manifest/recovery copy"
        )
    receipt = json.loads(Path(evidence["backup_receipt_path"]).read_text())
    if (
        evidence["backup_receipt_sha256"]
        != file_sha(Path(evidence["backup_receipt_path"]))
        or receipt.get("status") != "passed"
        or not receipt.get("readback_verified")
        or receipt.get("backup_sha256") != evidence["backup_sha256"]
    ):
        raise RetirementError("Durable recovery receipt missing or inconsistent")


def validate_paths(
    manifest_path: Path,
    backup_path: Path,
    report_path: Path,
    evidence_path: Path | None = None,
) -> None:
    protected = {manifest_path.resolve(), backup_path.resolve()}
    if evidence_path is not None:
        protected.add(evidence_path.resolve())
        if evidence_path.exists():
            evidence = json.loads(evidence_path.read_text())
            if evidence.get("backup_receipt_path"):
                protected.add(Path(evidence["backup_receipt_path"]).resolve())
    if report_path.resolve() in protected:
        raise RetirementError(
            "Report cannot overwrite manifest, backup, evidence or recovery receipt"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["backup", "apply", "status", "restore"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--confirm-manifest")
    parser.add_argument("--confirm-restore-six-retired-assets", action="store_true")
    args = parser.parse_args()
    validate_paths(args.manifest, args.backup, args.report, args.evidence)
    manifest = load_manifest(args.manifest)
    if not args.backup.resolve().is_relative_to(BACKUP_ROOT):
        raise RetirementError("Recovery copy must be in the approved durable directory")
    if args.mode == "backup":
        graph = verify_graph(manifest)
        conn = connect_formal(readonly=True)
        try:
            report = create_backup(conn, manifest, graph, args.backup)
        finally:
            conn.rollback()
            conn.close()
    else:
        backup = load_backup(args.backup, manifest)
        if args.mode == "status":
            report = status_report(manifest, backup)
        else:
            if args.confirm_manifest != MANIFEST_SHA or not args.evidence:
                raise RetirementError(
                    "Explicit manifest confirmation and isolation evidence required"
                )
            check_isolation_evidence(args.evidence, args.backup)
            if args.mode == "apply":
                graph = verify_graph(manifest)
                if graph != backup["graph"]:
                    raise RetirementError("Live graph changed since backup")
            elif not args.confirm_restore_six_retired_assets:
                raise RetirementError(
                    "Explicit restore instruction required; never restore automatically"
                )
            conn = connect_formal(readonly=False)
            if connection_identity(conn) != backup["identity"]:
                conn.close()
                raise RetirementError(
                    "Database server identity differs from recovery copy"
                )
            print(
                f"{utc_now()} begin {args.mode}: reviewed four-table scope", flush=True
            )
            context = {
                "manifest_sha256": MANIFEST_SHA,
                "tool_sha256": file_sha(Path(__file__)),
                "backup_sha256": file_sha(args.backup),
                "mode": args.mode,
            }
            atomic_json(
                args.report,
                {**context, "status": "execution_intent", "started_at_utc": utc_now()},
            )
            try:
                report = (
                    apply_backup(conn, manifest, backup)
                    if args.mode == "apply"
                    else {"status": restore_backup_rows(conn, manifest, backup)}
                )
                report.update(context)
                atomic_json(args.report, report)
            except BaseException as error:
                report = {
                    **context,
                    "status": "failed_or_commit_uncertain",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                conn.close()
                atomic_json(args.report, report)
                try:
                    report["confirmation"] = status_report(manifest, backup)
                except (
                    psycopg2.Error,
                    OSError,
                    ValueError,
                    RetirementError,
                    KeyError,
                ) as confirmation_error:
                    report["confirmation_error"] = str(confirmation_error)
                atomic_json(args.report, report)
                raise
            finally:
                if not conn.closed:
                    conn.close()
            try:
                report["confirmation"] = status_report(manifest, backup)
                if args.mode == "apply":
                    report["graph_after"] = verify_graph(manifest)
                    index_names = {
                        json.loads(k)[0]
                        for k in report["confirmation"]["asset_index_names"]
                    }
                    if (
                        report["confirmation"]["state"] != "deleted"
                        or not report["confirmation"]["retained_history_unchanged"]
                        or report["confirmation"]["protected_counts"]["asset_keys"]
                        != 180
                        or index_names != set(report["graph_after"]["asset_names"])
                    ):
                        raise RetirementError(
                            "Committed cleanup needs investigation; do not auto-restore"
                        )
            except Exception as confirmation_error:
                report["confirmation_error"] = str(confirmation_error)
                atomic_json(args.report, report)
                raise
    report.update(
        {
            "manifest_sha256": MANIFEST_SHA,
            "tool_sha256": file_sha(Path(__file__)),
            "completed_at_utc": utc_now(),
        }
    )
    atomic_json(args.report, report)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"graph_after", "asset_index_names"}
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
