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
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_TYPES,
    DailyBasicValidationError,
    daily_basic_code_hash,
    daily_basic_trade_date,
)
from orchestrator.defs.duckdb_sql import read_parquet
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
        rows, keys, invalid, wrong = connection.execute(
            f"SELECT count(*), count(DISTINCT (ts_code,trade_date)), "
            "count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code)='' OR ts_code!=trim(ts_code) OR trade_date IS NULL), "
            f"count(*) FILTER (WHERE trade_date != ?) FROM {relation}",
            [day],
        ).fetchone()
        codes = tuple(
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT ts_code FROM {relation} WHERE ts_code IS NOT NULL ORDER BY ts_code"
            ).fetchall()
        )
        failures = tuple(
            name
            for name, failed in (
                ("empty_file", not rows),
                ("duplicate_key", rows != keys),
                ("null_key", invalid),
                ("partition_date", wrong),
            )
            if failed
        )
        return DailyBasicFileAudit(failures, rows, codes)
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
    expected_evidence = {
        "delivery_method": "tushare_daily",
        "file_sha256": file_sha256(path),
        "source_row_count": audit.row_count,
        "code_count": len(audit.codes),
        "input_code_count": len(expected),
        "input_code_hash": daily_basic_code_hash(expected),
    }
    for key, value in expected_evidence.items():
        if evidence.get(key) != value:
            rules.append(f"delivery_{key}")
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

                def consume(_offset, rows):
                    nonlocal received
                    if not rows:
                        return
                    frame = pd.DataFrame(rows, columns=DAILY_BASIC_FIELDS)
                    for column in DAILY_BASIC_FIELDS[2:]:
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
                    received += len(rows)

                result = fetch_daily_basic_pages(
                    tushare=tushare,
                    trade_date=trade_date,
                    fields=DAILY_BASIC_FIELDS,
                    consume_page=consume,
                    clock=clock,
                    sleep_fn=sleep_fn,
                )
                connection.execute(
                    f"COPY (SELECT {_COLUMNS} FROM daily_basic_source ORDER BY ts_code) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(candidate)],
                )
                audit = audit_daily_basic_file(connection, candidate, trade_date)
                if (
                    audit.failed_rules
                    or audit.row_count != received
                    or set(expected) - set(audit.codes)
                ):
                    raise DailyBasicValidationError("candidate_contract_or_coverage")
                relation = read_parquet(candidate, hive_partitioning=False)
                for left, right in (
                    ("daily_basic_source", relation),
                    (relation, "daily_basic_source"),
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
                    "delivery_method": "tushare_daily",
                    "file_sha256": file_sha256(target),
                    "source_row_count": received,
                    "code_count": len(audit.codes),
                    "input_code_count": len(expected),
                    "input_code_hash": daily_basic_code_hash(expected),
                    "request_count": result.request_count,
                    "page_count": result.page_count,
                    "elapsed_ms": (clock() - started) * 1000,
                    "result_status": "reused" if same else "written",
                }
        finally:
            candidate.unlink(missing_ok=True)
