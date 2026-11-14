"""Daily-basic columnar candidate validation and single-partition promotion."""

import fcntl
import hashlib
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter, sleep

import pandas as pd

from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_B_SHARE_PATTERN,
    DAILY_BASIC_DECIMAL_FIELDS,
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_TYPES,
    DailyBasicValidationError,
    daily_basic_code_hash,
    daily_basic_is_b_share,
    daily_basic_trade_date,
    validate_daily_basic_limit_status,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import raw_daily_basic_path, raw_daily_basic_staging_path
from orchestrator.defs.source_readiness.daily_basic import fetch_daily_basic_pages

_COLUMNS = ", ".join(f'"{name}"' for name in DAILY_BASIC_FIELDS)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class DailyBasicFileAudit:
    failed_rules: tuple[str, ...]
    row_count: int = 0
    codes: tuple[str, ...] = ()
    null_limit_status_codes: tuple[str, ...] = ()
    b_share_row_count: int = 0


def audit_daily_basic_file(
    connection, path: Path, trade_date: str
) -> DailyBasicFileAudit:
    day = daily_basic_trade_date(trade_date).replace("-", "")
    if not path.is_file():
        return DailyBasicFileAudit(("file_missing",))
    relation = read_parquet(path, hive_partitioning=False)
    try:
        schema = connection.execute(
            f"DESCRIBE SELECT {_COLUMNS} FROM {relation}"
        ).fetchall()
        actual = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
        if [(r[0], r[1]) for r in actual] != list(DAILY_BASIC_TYPES.items()):
            return DailyBasicFileAudit(("schema",))
        if len(schema) != len(DAILY_BASIC_FIELDS):
            return DailyBasicFileAudit(("schema",))
        rows, keys, invalid, wrong, invalid_status, b_shares = connection.execute(
            f"SELECT count(*), count(DISTINCT (ts_code,trade_date)), "
            "count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code)='' OR ts_code!=trim(ts_code) OR trade_date IS NULL), "
            "count(*) FILTER (WHERE trade_date != ?), "
            "count(*) FILTER (WHERE limit_status NOT BETWEEN 0 AND 6), "
            f"count(*) FILTER (WHERE regexp_full_match(ts_code, ?)) FROM {relation}",
            [day, DAILY_BASIC_B_SHARE_PATTERN],
        ).fetchone()
        codes = tuple(
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT ts_code FROM {relation} WHERE ts_code IS NOT NULL ORDER BY ts_code"
            ).fetchall()
        )
        null_codes = tuple(row[0] for row in connection.execute(
            f"SELECT ts_code FROM {relation} WHERE limit_status IS NULL ORDER BY ts_code"
        ).fetchall())
        failures = tuple(
            name
            for name, failed in (
                ("empty_file", not rows),
                ("duplicate_key", rows != keys),
                ("null_key", invalid),
                ("partition_date", wrong),
                ("limit_status_range", invalid_status),
            )
            if failed
        )
        return DailyBasicFileAudit(failures, rows, codes, null_codes, b_shares)
    except Exception:  # noqa: BLE001 -- corrupt candidates/check files fail closed.
        return DailyBasicFileAudit(("file_unreadable_or_schema",))


def audit_daily_basic_coverage(
    path: Path,
    audit: DailyBasicFileAudit,
    expected_codes: Sequence[str],
    evidence: dict,
) -> tuple[str, ...]:
    if audit.failed_rules:
        return ("file_contract",)
    if evidence.get("delivery_method") == "prod_history":
        expected_evidence = {
            "file_sha256": file_sha256(path),
            "source_row_count": audit.row_count,
            "code_count": len(audit.codes),
            "source_system": "prod_raw_db",
            "trade_date": path.parent.name.removeprefix("trade_date="),
        }
        rules = [
            f"delivery_{key}"
            for key, value in expected_evidence.items()
            if evidence.get(key) != value
        ]
        for key in (
            "history_plan_fingerprint",
            "history_export_fingerprint",
            "history_audit_fingerprint",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(key, ""))):
                rules.append(f"delivery_{key}")
        return tuple(rules)
    expected = set(expected_codes)
    rules = []
    if not expected or expected - set(audit.codes):
        rules.append("missing_upstream_codes")
    if expected.intersection(audit.null_limit_status_codes):
        rules.append("null_required_limit_status")
    expected_evidence = {
        "delivery_method": "tushare_daily",
        "file_sha256": file_sha256(path),
        "source_row_count": audit.row_count,
        "code_count": len(audit.codes),
        "input_code_count": len(expected),
        "input_code_hash": daily_basic_code_hash(expected),
        "null_limit_status_count": len(audit.null_limit_status_codes),
        "retained_b_share_row_count": audit.b_share_row_count,
    }
    for key, value in expected_evidence.items():
        if evidence.get(key) != value:
            rules.append(f"delivery_{key}")
    if not {"fetched_row_count", "excluded_b_share_row_count"} <= evidence.keys() or (
        evidence["fetched_row_count"] + audit.b_share_row_count
        != audit.row_count + evidence["excluded_b_share_row_count"]
    ):
        rules.append("delivery_row_counts")
    return tuple(rules)


def _decimal_text(value):
    if value is None or pd.isna(value):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number != number.quantize(
            Decimal("0.0001"), context=Context(prec=80)
        ):
            raise DailyBasicValidationError(
                "numeric_precision：数值超出4位小数或非有限数"
            )
    except InvalidOperation as error:
        raise DailyBasicValidationError(
            "numeric_precision：数值无法无损解析"
        ) from error
    return str(number)


def write_daily_basic_partition(
    *,
    lake_root: Path,
    staging_root: Path,
    trade_date: str,
    run_id: str,
    duckdb_resource,
    tushare,
    load_expected_codes: Callable[[], Sequence[str]],
    write_mode: str = "write_new",
    clock=perf_counter,
    sleep_fn=sleep,
) -> dict:
    if write_mode not in ("write_new", "replace"):
        raise DailyBasicValidationError("invalid_write_mode")
    target = raw_daily_basic_path(lake_root, trade_date)
    candidate = raw_daily_basic_staging_path(staging_root, run_id, trade_date)
    if staging_root.resolve().is_relative_to(lake_root.resolve()):
        raise DailyBasicValidationError("staging_inside_lake")
    lock_path = staging_root / "daily_basic" / "locks" / f"{trade_date}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DailyBasicValidationError(
                "partition_locked：该日期正在写入"
            ) from error
        expected = tuple(sorted(set(load_expected_codes())))
        if not expected:
            raise DailyBasicValidationError("empty_upstream_codes")
        original = file_sha256(target) if target.exists() else None
        candidate.parent.mkdir(parents=True, exist_ok=True)
        started = clock()
        try:
            with duckdb_resource.connect() as connection:
                schema = ", ".join(
                    f'"{name}" {kind}' for name, kind in DAILY_BASIC_TYPES.items()
                )
                connection.execute(f"CREATE TEMP TABLE daily_basic_source ({schema})")
                received = 0
                excluded = 0
                retained = 0
                expected_set = set(expected)
                delivery_relation = "daily_basic_source"
                if target.exists():
                    old_relation = read_parquet(target, hive_partitioning=False)
                    old_schema = connection.execute(f"DESCRIBE SELECT * FROM {old_relation}").fetchall()
                    if [(r[0], r[1]) for r in old_schema] != list(DAILY_BASIC_TYPES.items()):
                        raise DailyBasicValidationError("existing_target_schema：18到19字段只能通过bootstrap切换")
                    retained = connection.execute(
                        f"SELECT count(*) FROM {old_relation} "
                        "WHERE regexp_full_match(ts_code, ?)", [DAILY_BASIC_B_SHARE_PATTERN],
                    ).fetchone()[0]
                    delivery_relation = (
                        f"(SELECT {_COLUMNS} FROM daily_basic_source UNION ALL "
                        f"SELECT {_COLUMNS} FROM {old_relation} WHERE regexp_full_match("
                        f"ts_code, {duckdb_string(DAILY_BASIC_B_SHARE_PATTERN)}))"
                    )

                def consume(_offset, rows):
                    nonlocal received, excluded
                    received += len(rows)
                    accepted = []
                    statuses = []
                    for row in rows:
                        if daily_basic_is_b_share(row["ts_code"]):
                            excluded += 1
                            continue
                        status = row["limit_status"]
                        validate_daily_basic_limit_status(
                            status, row["ts_code"], trade_date,
                            required=row["ts_code"] in expected_set,
                        )
                        accepted.append(row)
                        statuses.append(status)
                    rows = accepted
                    if not rows:
                        return
                    frame = pd.DataFrame(rows, columns=DAILY_BASIC_FIELDS[:-1])
                    frame["limit_status"] = pd.array(statuses, dtype="Int64")
                    for column in DAILY_BASIC_DECIMAL_FIELDS:
                        frame[column] = frame[column].map(_decimal_text)
                    connection.register("daily_basic_page", frame)
                    try:
                        projection = ", ".join(
                            f'CAST("{name}" AS {kind}) AS "{name}"'
                            for name, kind in DAILY_BASIC_TYPES.items()
                        )
                        connection.execute(
                            f"INSERT INTO daily_basic_source SELECT {projection} FROM daily_basic_page"
                        )
                    finally:
                        connection.unregister("daily_basic_page")

                result = fetch_daily_basic_pages(
                    tushare=tushare,
                    trade_date=trade_date,
                    fields=DAILY_BASIC_FIELDS,
                    consume_page=consume,
                    clock=clock,
                    sleep_fn=sleep_fn,
                )
                connection.execute(
                    f"COPY (SELECT {_COLUMNS} FROM {delivery_relation} ORDER BY ts_code) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(candidate)],
                )
                audit = audit_daily_basic_file(connection, candidate, trade_date)
                evidence = {
                    "delivery_method": "tushare_daily",
                    "file_sha256": file_sha256(candidate),
                    "source_row_count": received - excluded + retained,
                    "fetched_row_count": received,
                    "excluded_b_share_row_count": excluded,
                    "retained_b_share_row_count": retained,
                    "null_limit_status_count": len(audit.null_limit_status_codes),
                    "code_count": len(audit.codes),
                    "input_code_count": len(expected),
                    "input_code_hash": daily_basic_code_hash(expected),
                }
                if (
                    audit_daily_basic_coverage(candidate, audit, expected, evidence)
                ):
                    raise DailyBasicValidationError("candidate_contract_or_coverage")
                relation = read_parquet(candidate, hive_partitioning=False)
                for left, right in (
                    (delivery_relation, relation),
                    (relation, delivery_relation),
                ):
                    if connection.execute(
                        f"SELECT count(*) FROM (SELECT {_COLUMNS} FROM {left} EXCEPT ALL SELECT {_COLUMNS} FROM {right})"
                    ).fetchone()[0]:
                        raise DailyBasicValidationError("candidate_value_mismatch")
                if tuple(sorted(set(load_expected_codes()))) != expected:
                    raise DailyBasicValidationError("upstream_changed")
                if (file_sha256(target) if target.exists() else None) != original:
                    raise DailyBasicValidationError("target_changed")
                same = False
                if target.exists():
                    target_audit = audit_daily_basic_file(
                        connection, target, trade_date
                    )
                    if write_mode == "write_new":
                        if target_audit.failed_rules:
                            raise DailyBasicValidationError("existing_target_invalid")
                        old = read_parquet(target, hive_partitioning=False)
                        same = all(
                            connection.execute(
                                f"SELECT count(*) FROM (SELECT {_COLUMNS} FROM {a} EXCEPT ALL SELECT {_COLUMNS} FROM {b})"
                            ).fetchone()[0]
                            == 0
                            for a, b in ((old, relation), (relation, old))
                        )
                        if not same:
                            raise DailyBasicValidationError("target_content_conflict")
                if not same:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if candidate.stat().st_dev != target.parent.stat().st_dev:
                        raise DailyBasicValidationError("cross_device_promotion")
                    os.replace(candidate, target)
                return {
                    **evidence,
                    "file_sha256": file_sha256(target),
                    "request_count": result.request_count,
                    "page_count": result.page_count,
                    "elapsed_ms": (clock() - started) * 1000,
                    "result_status": "reused" if same else "written",
                }
        finally:
            candidate.unlink(missing_ok=True)
