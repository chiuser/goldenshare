"""Lossless, bounded columnar audits of Prod moneyflow COPY CSV units."""

import csv
import hashlib
import threading
from contextlib import contextmanager
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    history_schema,
    history_source_key_fields,
)
from orchestrator.defs.io.moneyflow_candidates import (
    moneyflow_candidate_connection,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_MAX_CSV_BYTES,
    MONEYFLOW_HISTORY_MAX_DATE_FACTS,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MONEYFLOW_HISTORY_STREAM_BYTES,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_daily import daily_numeric_rejection_sql


@contextmanager
def _audit_connection(path, timeout_seconds):
    with moneyflow_candidate_connection(path.parent) as db:
        timer = threading.Timer(timeout_seconds, db.interrupt)
        timer.daemon = True
        timer.start()
        try:
            yield db
        finally:
            timer.cancel()
            timer.join()


def audit_moneyflow_history_csv(
    path: Path, request, check, *, timeout_seconds=MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS
) -> dict:
    """Read business rows once into bounded DuckDB; return only scalar/date facts."""
    check()
    if not 0 < timeout_seconds <= MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS:
        raise MoneyflowContractError("history_unit_timeout")
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > MONEYFLOW_HISTORY_MAX_CSV_BYTES
    ):
        raise MoneyflowContractError("history_csv_file")
    schema = history_schema(request.plan.dataset)
    fields = tuple(c.name for c in schema)
    try:
        with path.open("rb") as stream:
            header = stream.readline(4097)
        if len(header) > 4096 or next(
            csv.reader([header.decode("utf8")], strict=True)
        ) != list(fields):
            raise MoneyflowContractError("history_csv_header")
    except (UnicodeError, csv.Error, StopIteration) as error:
        raise MoneyflowContractError("history_csv_header") from error
    # PostgreSQL COPY closes every quoted field and terminates its final record.
    # Some CSV scanners omit an unterminated last record even in strict mode.
    # Count quote bytes in bounded blocks (C-level count), not Python business rows.
    digest = hashlib.sha256()
    parity, last_byte = 0, b""
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(MONEYFLOW_HISTORY_STREAM_BYTES), b""):
            check()
            digest.update(block)
            parity ^= block.count(b'"') % 2
            last_byte = block[-1:]
    if parity or last_byte != b"\n":
        raise MoneyflowContractError("history_csv_incomplete")
    columns = ",".join(f"'{name}':'VARCHAR'" for name in fields)
    quoted = ",".join(f'"{name}"' for name in fields)
    unit = request.plan.source_units[request.unit_id]
    keys = history_source_key_fields(request.plan.dataset)
    try:
        with _audit_connection(path, timeout_seconds) as db:
            db.execute(
                f"CREATE TEMP TABLE source_rows AS SELECT row_number() OVER () AS _ordinal, {quoted} "
                f"FROM read_csv(?, columns={{{columns}}}, header=true, auto_detect=false, "
                "delim=',', quote='\"', escape='\"', nullstr=?, allow_quoted_nulls=false, parallel=false, strict_mode=true)",
                [str(path), r"\N"],
            )
            check()
            rows = db.execute("SELECT count(*) FROM source_rows").fetchone()[0]
            if rows != unit.row_count:
                raise MoneyflowContractError("history_csv_row_count")
            predicate = " OR ".join(
                f'"{key}" IS NULL OR trim("{key}") = \'\'' for key in keys
            )
            if db.execute(
                f"SELECT count(*) FROM source_rows WHERE {predicate}"
            ).fetchone()[0]:
                raise MoneyflowContractError("history_csv_identity")
            key_sql = ",".join(f'"{name}"' for name in keys)
            if db.execute(
                f"SELECT count(*) FROM (SELECT {key_sql} FROM source_rows GROUP BY {key_sql} HAVING count(*) != 1)"
            ).fetchone()[0]:
                raise MoneyflowContractError("history_csv_duplicate_key")
            if db.execute(
                "SELECT count(*) FROM source_rows WHERE NOT regexp_full_match(trade_date, '[0-9]{4}-[0-9]{2}-[0-9]{2}') OR try_cast(trade_date AS DATE) IS NULL"
            ).fetchone()[0]:
                raise MoneyflowContractError("history_csv_date")
            observed_dates = db.execute(
                "SELECT trade_date, count(*) FROM source_rows GROUP BY trade_date ORDER BY trade_date"
            ).fetchmany(MONEYFLOW_HISTORY_MAX_DATE_FACTS + 1)
            expected_dates = {
                f.trade_date: f.row_count for f in request.plan.date_counts
            }
            if len(observed_dates) > MONEYFLOW_HISTORY_MAX_DATE_FACTS or any(
                day not in expected_dates or count > expected_dates[day]
                for day, count in observed_dates
            ):
                raise MoneyflowContractError("history_csv_date_counts")
            if unit.dates and dict(observed_dates) != {
                day: expected_dates[day] for day in unit.dates
            }:
                raise MoneyflowContractError("history_csv_date_counts")
            if (
                request.plan.dataset == "moneyflow_ind_dc"
                and db.execute(
                    "SELECT count(*) FROM source_rows WHERE content_type NOT IN ('行业','概念','地域')"
                ).fetchone()[0]
            ):
                raise MoneyflowContractError("history_csv_content_type")
            first_key = last_key = None
            if request.plan.dataset == "moneyflow":
                if db.execute(
                    "SELECT count(*) FROM (SELECT ts_code,trade_date,lag(ts_code) OVER (ORDER BY _ordinal) AS p_code,lag(trade_date) OVER (ORDER BY _ordinal) AS p_day FROM source_rows) WHERE p_code IS NOT NULL AND (ts_code,trade_date) <= (p_code,p_day)"
                ).fetchone()[0]:
                    raise MoneyflowContractError("history_csv_key_order")
                first_key = db.execute(
                    "SELECT ts_code,trade_date FROM source_rows ORDER BY _ordinal LIMIT 1"
                ).fetchone()
                last_key = db.execute(
                    "SELECT ts_code,trade_date FROM source_rows ORDER BY _ordinal DESC LIMIT 1"
                ).fetchone()
                if request.after_key and first_key <= request.after_key:
                    raise MoneyflowContractError("history_csv_after_key")
                if request.through_key and last_key != request.through_key:
                    raise MoneyflowContractError("history_csv_through_key")
            for column in schema:
                if column.type == "VARCHAR":
                    continue
                name = column.name
                check()
                db.execute(
                    f'CREATE OR REPLACE TEMP VIEW numeric_values AS SELECT "{name}", CASE WHEN "{name}" IS NULL THEN \'NULL\' ELSE \'VARCHAR\' END AS "{name}_json_type" FROM source_rows'
                )
                if db.execute(
                    f"SELECT count(*) FROM numeric_values WHERE {daily_numeric_rejection_sql(name, column.type)}"
                ).fetchone()[0]:
                    raise MoneyflowContractError("history_csv_numeric:" + name)
            check()
    except duckdb.Error as error:
        check()
        raise MoneyflowContractError("history_csv_invalid") from error
    check()
    return {
        "rows": rows,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "first_key": list(first_key) if first_key else None,
        "last_key": list(last_key) if last_key else None,
        "date_counts": [list(value) for value in observed_dates],
    }
