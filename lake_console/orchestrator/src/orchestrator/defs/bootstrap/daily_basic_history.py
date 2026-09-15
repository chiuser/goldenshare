"""Offline daily-basic history checkpoints and atomic file publication.

No Dagster state writes. A plan without explicit execution budgets is advisory.
"""

import fcntl
import hashlib
import json
import math
import os
import re
import shutil
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pandas as pd

from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_TYPES,
    DailyBasicValidationError,
    daily_basic_trade_date,
)
from orchestrator.defs.daily_basic_raw_io import _decimal_text, file_sha256
from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import raw_daily_basic_path
from orchestrator.defs.prod_db.daily_basic import HISTORY_BATCH_SIZE

COLUMNS = ", ".join(f'"{name}"' for name in DAILY_BASIC_FIELDS)
SOURCE_POLICY = "operator_confirmed_stable_single_pass"
LIMIT_NAMES = (
    "max_source_rows",
    "max_source_seconds",
    "max_stage_seconds",
    "max_spill_bytes",
)


def history_fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def seal_history_report(value):
    value = {key: item for key, item in value.items() if key != "fingerprint"}
    return {**value, "fingerprint": history_fingerprint(value)}


def verify_history_report(value):
    if seal_history_report(value) != value:
        raise DailyBasicValidationError("history_report_fingerprint")


def save_history_report(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(seal_history_report(value), stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_history_report(path):
    value = json.loads(Path(path).read_text())
    verify_history_report(value)
    return value


def _safe_root(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise DailyBasicValidationError("history_path_must_be_absolute")
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise DailyBasicValidationError("history_symlink_path")
    return path


def _existing_parent(path):
    while not path.exists():
        path = path.parent
    return path


def _parquet_files(paths, *, filename=False):
    if not paths:
        raise DailyBasicValidationError("history_empty_file_set")
    option = ", filename=true" if filename else ""
    return (
        "read_parquet(["
        + ",".join(duckdb_string(p) for p in paths)
        + "], hive_partitioning=false"
        + option
        + ")"
    )


def _explain_node_types(value):
    if isinstance(value, dict):
        node_type = value.get("Node Type")
        if isinstance(node_type, str):
            yield node_type
        for child in value.values():
            yield from _explain_node_types(child)
    elif isinstance(value, list):
        for child in value:
            yield from _explain_node_types(child)


def make_history_plan(
    *,
    start,
    end,
    batch_id,
    lake_root,
    staging_root,
    calendar_path,
    dates,
    source_evidence,
    cost_evidence,
    limits=None,
):
    start, end = daily_basic_trade_date(start), daily_basic_trade_date(end)
    if start > end or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", batch_id):
        raise DailyBasicValidationError("history_range_or_batch_id")
    lake, staging = _safe_root(lake_root), _safe_root(staging_root)
    if staging.is_relative_to(lake) or lake.is_relative_to(staging):
        raise DailyBasicValidationError("history_roots_overlap")
    if limits is not None and (
        set(limits) != set(LIMIT_NAMES)
        or any(type(v) is not int or v <= 0 for v in limits.values())
    ):
        raise DailyBasicValidationError("history_execution_limits")
    dates = sorted(set(dates))
    if not dates or any(not start <= daily_basic_trade_date(d) <= end for d in dates):
        raise DailyBasicValidationError("history_calendar_range")
    reasons = []
    columns = {row[0]: row for row in source_evidence["columns"]}
    if not set(DAILY_BASIC_FIELDS) <= set(columns):
        reasons.append("source_columns_missing")
    else:
        if columns["trade_date"][1] != "date" or columns["ts_code"][1] not in (
            "character varying",
            "text",
        ):
            reasons.append("source_key_types")
        if any(columns[name][1] != "numeric" for name in DAILY_BASIC_FIELDS[2:]):
            reasons.append("source_numeric_types")
        if any(
            tuple(columns[name][3:])
            != (int(DAILY_BASIC_TYPES[name].split("(")[1].split(",")[0]), 4)
            for name in DAILY_BASIC_FIELDS[2:]
        ):
            reasons.append("source_numeric_precision")
    if source_evidence["primary_key"] != ["ts_code", "trade_date"]:
        reasons.append("source_primary_key")
    if len(source_evidence["explain"]) != 2:
        reasons.append("source_explain_missing")
    for explain in source_evidence["explain"]:
        node_types = set(_explain_node_types(explain))
        if not node_types.intersection({"Index Scan", "Index Only Scan"}):
            reasons.append("source_plan_not_indexed")
        if node_types.intersection({"Seq Scan", "Sort", "Incremental Sort"}):
            reasons.append("source_plan_io_amplification")
    targets = [d for d in dates if raw_daily_basic_path(lake, d).exists()]
    if targets:
        reasons.append("existing_targets_require_content_audit")
    return seal_history_report(
        {
            "schema_version": 1,
            "stage": "plan",
            "created_at": datetime.now(UTC).isoformat(),
            "start": start,
            "end": end,
            "batch_id": batch_id,
            "lake_root": str(lake),
            "staging_root": str(staging),
            "calendar_path": str(_safe_root(calendar_path)),
            "calendar_sha256": file_sha256(Path(calendar_path)),
            "dates": dates,
            "candidate_calendar_count": len(dates),
            "source_evidence": source_evidence,
            "source_policy": SOURCE_POLICY,
            "cost_evidence": cost_evidence,
            "limits": limits,
            "existing_targets": targets,
            "stop_reasons": sorted(set(reasons)),
            "source_rows_actual": None,
            "source_dates_actual": None,
            "disk_free_bytes": shutil.disk_usage(_existing_parent(staging)).free,
            "execution_budget_frozen": limits is not None,
            "materializations_upper": len(dates),
            "checks_upper": min(len(dates), 20) * 2,
        }
    )


def _validate_plan(plan, *, apply=False):
    verify_history_report(plan)
    if plan["stage"] != "plan" or plan["stop_reasons"]:
        raise DailyBasicValidationError("history_plan_not_green")
    if plan.get("source_policy") != SOURCE_POLICY:
        raise DailyBasicValidationError("history_source_policy_changed")
    _safe_root(plan["lake_root"])
    _safe_root(plan["staging_root"])
    if file_sha256(Path(plan["calendar_path"])) != plan["calendar_sha256"]:
        raise DailyBasicValidationError("history_calendar_changed")
    if apply and not plan["limits"]:
        raise DailyBasicValidationError("history_execution_budget_not_frozen")
    if apply:
        costs = plan["cost_evidence"]
        base = sum(
            max(costs.get(name, [0]))
            for name in (
                "chunk_gib",
                "formal_gib",
                "annual_intermediate_gib",
                "candidate_gib",
                "fragment_gib",
            )
        )
        if costs.get("baseline_rows"):
            base *= max(1, plan["limits"]["max_source_rows"] / costs["baseline_rows"])
        required = base * (1024**3) + plan["limits"]["max_spill_bytes"]
        if (
            shutil.disk_usage(_existing_parent(Path(plan["staging_root"]))).free
            < required
        ):
            raise DailyBasicValidationError("history_disk_budget")


def _workspace(plan):
    return Path(plan["staging_root"]) / "daily_basic_history" / plan["batch_id"]


@contextmanager
def _history_lock(plan):
    workspace = _safe_root(_workspace(plan))
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / "history.lock").open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield workspace


@contextmanager
def _connection(plan, *, readonly=False):
    settings = replace(
        DEFAULT_DUCKDB_CONNECTION_SETTINGS, temp_directory=_workspace(plan) / "spill"
    )
    if plan["limits"]:
        settings = replace(
            settings, max_temp_directory_size=f"{plan['limits']['max_spill_bytes']}B"
        )
    # An audit may not create a spill directory or write data files.
    if readonly:
        settings = replace(settings, temp_directory=_workspace(plan))
    with connect_configured_duckdb(
        settings, temp_policy="existing_no_spill" if readonly else "managed"
    ) as connection:
        yield connection


def _deadline(started, seconds):
    if monotonic() - started >= seconds:
        raise DailyBasicValidationError("history_elapsed_budget")


def _canonical_page(rows, plan, last_key):
    if len(rows) > HISTORY_BATCH_SIZE:
        raise DailyBasicValidationError("history_page_too_large")
    normalized = []
    previous = last_key
    allowed = set(plan["dates"])
    for row in rows:
        if len(row) != len(DAILY_BASIC_FIELDS):
            raise DailyBasicValidationError("history_source_width")
        code, day = row[:2]
        if not isinstance(code, str) or not code or code != code.strip():
            raise DailyBasicValidationError("history_source_code")
        if not isinstance(day, str) or not re.fullmatch(r"\d{8}", day):
            raise DailyBasicValidationError("history_source_date")
        iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        key = (code, iso)
        if iso not in allowed or (previous is not None and key <= tuple(previous)):
            raise DailyBasicValidationError("history_source_key_or_calendar")
        values = [code, day]
        for name, value in zip(DAILY_BASIC_FIELDS[2:], row[2:], strict=True):
            text = _decimal_text(value)
            if value is not None and text is None:
                raise DailyBasicValidationError("history_non_finite_numeric")
            precision = int(DAILY_BASIC_TYPES[name].split("(")[1].split(",")[0])
            if text is not None:
                number = Decimal(text)
                if abs(number) >= Decimal(10) ** (precision - 4):
                    raise DailyBasicValidationError("history_numeric_overflow")
                text = format(number, ".4f") if number else "0.0000"
            values.append(text)
        normalized.append(values)
        previous = key
    return normalized, previous


def _write_chunk(connection, rows, path):
    frame = pd.DataFrame(rows, columns=DAILY_BASIC_FIELDS)
    connection.register("history_page", frame)
    projection = ", ".join(
        f'CAST("{n}" AS {t}) AS "{n}"' for n, t in DAILY_BASIC_TYPES.items()
    )
    try:
        connection.execute(
            f"COPY (SELECT {projection} FROM history_page ORDER BY ts_code, trade_date) "
            "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(path)],
        )
        if connection.execute(
            f"SELECT count(*) FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchone()[0] != len(rows):
            raise DailyBasicValidationError("history_chunk_row_count")
        back = connection.execute(
            f"SELECT {COLUMNS} FROM {read_parquet(path, hive_partitioning=False)} "
            "ORDER BY ts_code, trade_date"
        ).fetchmany(HISTORY_BATCH_SIZE)
        normalized = [
            [
                r[0],
                r[1],
                *(
                    None if v is None else format(v, ".4f") if v else "0.0000"
                    for v in r[2:]
                ),
            ]
            for r in back
        ]
        if normalized != rows:
            raise DailyBasicValidationError("history_chunk_roundtrip")
    finally:
        connection.unregister("history_page")


def _validate_chunks(plan, state):
    verify_history_report(state)
    if state["plan_fingerprint"] != plan["fingerprint"]:
        raise DailyBasicValidationError("history_checkpoint_plan_changed")
    for index, chunk in enumerate(state["chunks"]):
        expected = _workspace(plan) / "chunks" / f"{index:06d}.parquet"
        if chunk["path"] != str(expected) or file_sha256(expected) != chunk["sha256"]:
            raise DailyBasicValidationError("history_checkpoint_chunk_changed")


def export_daily_basic_history(plan, source, *, apply=False):
    if not apply:
        raise DailyBasicValidationError("history_apply_required")
    _validate_plan(plan, apply=True)
    started = monotonic()
    expected_schema = {
        "columns": plan["source_evidence"]["columns"],
        "primary_key": plan["source_evidence"]["primary_key"],
    }
    fresh = source.inspect(plan["start"], plan["end"])
    if history_fingerprint(
        {k: fresh[k] for k in expected_schema}
    ) != history_fingerprint(expected_schema):
        raise DailyBasicValidationError("history_source_schema_changed")
    with _history_lock(plan) as workspace, _connection(plan) as connection:
        checkpoint = workspace / "export.json"
        state = (
            load_history_report(checkpoint)
            if checkpoint.exists()
            else seal_history_report(
                {
                    "stage": "export",
                    "plan_fingerprint": plan["fingerprint"],
                    "chunks": [],
                    "frozen": False,
                }
            )
        )
        _validate_chunks(plan, state)
        if state["frozen"]:
            return state
        chunks = state["chunks"]
        # Only an interrupted export rechecks its persisted prefix.
        last, index, count = None, 0, 0
        while True:
            _deadline(started, plan["limits"]["max_source_seconds"])
            raw = source.fetch_page(plan["start"], plan["end"], last)
            _deadline(started, plan["limits"]["max_source_seconds"])
            rows, next_key = _canonical_page(raw, plan, last)
            count += len(rows)
            if count > plan["limits"]["max_source_rows"]:
                raise DailyBasicValidationError("history_row_budget")
            if not rows:
                if index != len(chunks) or not count:
                    raise DailyBasicValidationError("history_source_deleted_or_empty")
                break
            digest = history_fingerprint(rows)
            if index < len(chunks):
                if (
                    digest != chunks[index]["content_hash"]
                    or len(rows) != chunks[index]["rows"]
                ):
                    raise DailyBasicValidationError("history_source_changed")
            else:
                path = workspace / "chunks" / f"{index:06d}.parquet"
                path.parent.mkdir(parents=True, exist_ok=True)
                candidate = path.with_suffix(".candidate.parquet")
                candidate.unlink(missing_ok=True)
                _write_chunk(connection, rows, candidate)
                os.replace(candidate, path)
                chunks.append(
                    {
                        "path": str(path),
                        "rows": len(rows),
                        "last_key": list(next_key),
                        "content_hash": digest,
                        "sha256": file_sha256(path),
                    }
                )
                save_history_report(checkpoint, state)
            last = next_key
            index += 1
            print(f"每日指标历史导出 batch={index} rows={count}", flush=True)
        fresh = source.inspect(plan["start"], plan["end"])
        _deadline(started, plan["limits"]["max_source_seconds"])
        if history_fingerprint(
            {k: fresh[k] for k in expected_schema}
        ) != history_fingerprint(expected_schema):
            raise DailyBasicValidationError("history_source_schema_changed")
        state.update(
            frozen=True,
            source_policy=SOURCE_POLICY,
            rows=count,
            verified_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=monotonic() - started,
        )
        save_history_report(checkpoint, state)
        return load_history_report(checkpoint)


def _chunk_relation(state):
    return _parquet_files([Path(c["path"]) for c in state["chunks"]])


def _schema_and_counts(connection, relation):
    schema = [
        (r[0], r[1])
        for r in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    ]
    if schema != list(DAILY_BASIC_TYPES.items()):
        raise DailyBasicValidationError("history_schema")
    counts = connection.execute(
        f"SELECT trade_date, count(*), count(DISTINCT ts_code), "
        "count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code)='' OR ts_code!=trim(ts_code)) "
        f"FROM {relation} GROUP BY trade_date ORDER BY trade_date"
    ).fetchall()
    if any(
        not n or n != keys or invalid or day is None for day, n, keys, invalid in counts
    ):
        raise DailyBasicValidationError("history_keys")
    return {day: n for day, n, _, _ in counts}


def _compact_history_partition(connection, folder):
    parts = list(folder.glob("*.parquet"))
    if not parts:
        raise DailyBasicValidationError("history_partition_file_count")
    path = folder / "part-000.parquet"
    if path in parts:
        raise DailyBasicValidationError("history_partition_already_compacted")
    if len(parts) == 1:
        os.replace(parts[0], path)
    else:
        # A partition may be reopened by DuckDB. Read this date's fragments only.
        connection.execute(
            f"COPY (SELECT {COLUMNS} FROM {_parquet_files(parts)} ORDER BY ts_code) "
            "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(path)],
        )
    return path


def build_daily_basic_history(plan, *, apply=False):
    if not apply:
        raise DailyBasicValidationError("history_apply_required")
    _validate_plan(plan, apply=True)
    started = monotonic()
    with _history_lock(plan) as workspace, _connection(plan) as connection:
        state = load_history_report(workspace / "export.json")
        _validate_chunks(plan, state)
        if not state["frozen"]:
            raise DailyBasicValidationError("history_source_not_frozen")
        relation = _chunk_relation(state)
        counts = _schema_and_counts(connection, relation)
        if set(counts) != {d.replace("-", "") for d in plan["dates"]}:
            raise DailyBasicValidationError("history_calendar_source_difference")
        years = sorted({d[:4] for d in counts})
        annual = workspace / f"annual_{uuid4().hex}"
        manifest_path = workspace / "build.json"
        annual_state = workspace / "annual.json"
        if annual_state.exists():
            annual_report = load_history_report(annual_state)
            if annual_report["export_fingerprint"] != state["fingerprint"]:
                raise DailyBasicValidationError("history_annual_version_changed")
            for item in annual_report["files"]:
                if file_sha256(Path(item["path"])) != item["sha256"]:
                    raise DailyBasicValidationError("history_annual_changed")
            annual = Path(annual_report["root"])
        else:
            connection.execute(
                f"COPY (SELECT {COLUMNS}, substr(trade_date,1,4) AS history_year FROM {relation}) "
                "TO ? (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY(history_year))",
                [str(annual)],
            )
            files = [
                {"path": str(p), "sha256": file_sha256(p)}
                for p in sorted(annual.rglob("*.parquet"))
            ]
            save_history_report(
                annual_state,
                {
                    "export_fingerprint": state["fingerprint"],
                    "root": str(annual),
                    "files": files,
                },
            )
        completed = (
            load_history_report(manifest_path)
            if manifest_path.exists()
            else {
                "stage": "build",
                "plan_fingerprint": plan["fingerprint"],
                "export_fingerprint": state["fingerprint"],
                "files": [],
                "completed_years": [],
            }
        )
        if completed["export_fingerprint"] != state["fingerprint"]:
            raise DailyBasicValidationError("history_build_version_changed")
        for year in years:
            _deadline(started, plan["limits"]["max_stage_seconds"])
            if year in completed["completed_years"]:
                continue
            inputs = sorted((annual / f"history_year={year}").glob("*.parquet"))
            output = workspace / "by_date" / year / uuid4().hex
            output.parent.mkdir(parents=True, exist_ok=True)
            annual_relation = _parquet_files(inputs)
            connection.execute(
                f"COPY (SELECT {COLUMNS}, substr(trade_date,1,4)||'-'||substr(trade_date,5,2)||'-'||substr(trade_date,7,2) AS partition_date "
                f"FROM {annual_relation} ORDER BY trade_date, ts_code) "
                "TO ? (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY(partition_date), FILENAME_PATTERN 'part-{i}')",
                [str(output)],
            )
            for day in (d for d in plan["dates"] if d.startswith(year)):
                folder = output / f"partition_date={day}"
                path = _compact_history_partition(connection, folder)
                _deadline(started, plan["limits"]["max_stage_seconds"])
                completed["files"].append(
                    {
                        "date": day,
                        "path": str(path),
                        "sha256": file_sha256(path),
                        "rows": counts[day.replace("-", "")],
                    }
                )
            completed["completed_years"].append(year)
            save_history_report(manifest_path, completed)
            print(
                f"每日指标历史构建 year={year} files={len(completed['files'])}",
                flush=True,
            )
        _deadline(started, plan["limits"]["max_stage_seconds"])
        return load_history_report(manifest_path)


def _equal_rows(connection, left, right):
    return all(
        connection.execute(
            f"SELECT count(*) FROM (SELECT {COLUMNS} FROM {a} EXCEPT ALL SELECT {COLUMNS} FROM {b})"
        ).fetchone()[0]
        == 0
        for a, b in ((left, right), (right, left))
    )


def audit_daily_basic_history(plan):
    _validate_plan(plan, apply=True)
    workspace = _workspace(plan)
    state = load_history_report(workspace / "export.json")
    build = load_history_report(workspace / "build.json")
    _validate_chunks(plan, state)
    if not state["frozen"] or build["export_fingerprint"] != state["fingerprint"]:
        raise DailyBasicValidationError("history_audit_version")
    if sorted(f["date"] for f in build["files"]) != plan["dates"]:
        raise DailyBasicValidationError("history_build_dates")
    started = monotonic()
    with _connection(plan, readonly=True) as connection:
        source = _chunk_relation(state)
        # Single scan into a bounded DuckDB temporary table, not one source scan per date/year.
        connection.execute(
            f"CREATE TEMP TABLE history_frozen AS SELECT {COLUMNS} FROM {source} ORDER BY trade_date, ts_code"
        )
        for year in sorted({d[:4] for d in plan["dates"]}):
            files = [f for f in build["files"] if f["date"].startswith(year)]
            for item in files:
                expected = _safe_root(item["path"])
                if (
                    not expected.is_relative_to(workspace / "by_date" / year)
                    or expected.name != "part-000.parquet"
                    or expected.parent.name != f"partition_date={item['date']}"
                    or file_sha256(expected) != item["sha256"]
                ):
                    raise DailyBasicValidationError("history_candidate_changed")
                schema = connection.execute(
                    f"DESCRIBE SELECT * FROM {read_parquet(expected, hive_partitioning=False)}"
                ).fetchall()
                if [(r[0], r[1]) for r in schema] != list(DAILY_BASIC_TYPES.items()):
                    raise DailyBasicValidationError("history_candidate_schema")
            target = _parquet_files([Path(f["path"]) for f in files])
            counts = _schema_and_counts(connection, target)
            if counts != {f["date"].replace("-", ""): f["rows"] for f in files}:
                raise DailyBasicValidationError("history_candidate_counts")
            by_file = connection.execute(
                "SELECT filename, trade_date, count(*) FROM "
                f"{_parquet_files([Path(f['path']) for f in files], filename=True)} "
                "GROUP BY filename, trade_date"
            ).fetchall()
            if sorted(by_file) != sorted(
                (f["path"], f["date"].replace("-", ""), f["rows"]) for f in files
            ):
                raise DailyBasicValidationError("history_file_partition_alignment")
            if not _equal_rows(
                connection,
                f"(SELECT {COLUMNS} FROM history_frozen WHERE trade_date BETWEEN '{year}0101' AND '{year}1231')",
                target,
            ):
                raise DailyBasicValidationError("history_value_difference")
            for item in files:
                existing = raw_daily_basic_path(Path(plan["lake_root"]), item["date"])
                if existing.exists():
                    relation = read_parquet(existing, hive_partitioning=False)
                    _schema_and_counts(connection, relation)
                    if not _equal_rows(
                        connection,
                        relation,
                        read_parquet(Path(item["path"]), hive_partitioning=False),
                    ):
                        raise DailyBasicValidationError("history_target_conflict")
            _deadline(started, plan["limits"]["max_stage_seconds"])
    return seal_history_report(
        {
            "stage": "audit",
            "plan_fingerprint": plan["fingerprint"],
            "export_fingerprint": state["fingerprint"],
            "build_fingerprint": build["fingerprint"],
            "files": build["files"],
            "rows": sum(f["rows"] for f in build["files"]),
            "elapsed_seconds": monotonic() - started,
            "passed": True,
        }
    )


def promote_daily_basic_history(plan, audit, *, apply=False):
    if not apply:
        raise DailyBasicValidationError("history_apply_required")
    _validate_plan(plan, apply=True)
    verify_history_report(audit)
    with _history_lock(plan) as workspace:
        fresh = audit_daily_basic_history(plan)
        if any(
            fresh[key] != audit.get(key)
            for key in (
                "stage",
                "passed",
                "plan_fingerprint",
                "export_fingerprint",
                "build_fingerprint",
                "files",
                "rows",
            )
        ):
            raise DailyBasicValidationError("history_stale_audit")
        started = monotonic()
        checkpoint = workspace / "promote.json"
        done = {
            "stage": "promote",
            "plan_fingerprint": plan["fingerprint"],
            "files": [],
        }
        with _connection(plan) as connection:
            for item in audit["files"]:
                _deadline(started, plan["limits"]["max_stage_seconds"])
                candidate = _safe_root(item["path"])
                target = _safe_root(
                    raw_daily_basic_path(Path(plan["lake_root"]), item["date"])
                )
                lock = (
                    Path(plan["staging_root"])
                    / "daily_basic"
                    / "locks"
                    / f"{item['date']}.lock"
                )
                _safe_root(lock).parent.mkdir(parents=True, exist_ok=True)
                with lock.open("a") as stream:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if file_sha256(candidate) != item["sha256"]:
                        raise DailyBasicValidationError("history_candidate_changed")
                    if target.exists():
                        _schema_and_counts(
                            connection, read_parquet(target, hive_partitioning=False)
                        )
                        if not _equal_rows(
                            connection,
                            read_parquet(candidate, hive_partitioning=False),
                            read_parquet(target, hive_partitioning=False),
                        ):
                            raise DailyBasicValidationError("history_target_conflict")
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if candidate.stat().st_dev != target.parent.stat().st_dev:
                            raise DailyBasicValidationError("history_cross_device")
                        temporary = candidate.with_suffix(".promote")
                        temporary.unlink(missing_ok=True)
                        # Preserve the audited candidate for resumable verification, not a backup of old data.
                        shutil.copyfile(candidate, temporary)
                        if file_sha256(temporary) != item["sha256"]:
                            raise DailyBasicValidationError(
                                "history_promotion_copy_changed"
                            )
                        os.replace(temporary, target)
                    if file_sha256(target) != item["sha256"] and not _equal_rows(
                        connection,
                        read_parquet(candidate, hive_partitioning=False),
                        read_parquet(target, hive_partitioning=False),
                    ):
                        raise DailyBasicValidationError("history_promoted_content")
                    done["files"].append(
                        {"date": item["date"], "sha256": file_sha256(target)}
                    )
                    save_history_report(checkpoint, done)
        return load_history_report(checkpoint)


def history_cost_estimate(p0):
    rows = p0["row_baseline"]
    return {
        "basis": "P0 measured samples; extrapolation, not SLA",
        "baseline_rows": rows,
        "baseline_asof": p0["row_baseline_asof"],
        "estimated_pages_per_pass": math.ceil(rows / HISTORY_BATCH_SIZE) + 1,
        "source_policy": SOURCE_POLICY,
        "source_pass_count": 1,
        "export_minutes": p0["one_export_minutes_linear_scenarios"],
        "source_recheck_minutes": 0,
        "chunk_gib": p0["estimated_chunk_GiB"],
        "formal_gib": p0["estimated_date_files_GiB"],
        "candidate_gib": p0["estimated_date_files_GiB"],
        "fragment_gib": p0["estimated_date_files_GiB"],
        "annual_intermediate_gib": p0["estimated_chunk_GiB"],
        "build_audit_promote_seconds": None,
        "spill_peak_bytes": None,
        "full_execution_approved": False,
    }
