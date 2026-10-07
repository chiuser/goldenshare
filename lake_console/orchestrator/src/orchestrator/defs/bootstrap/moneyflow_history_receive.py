"""Bounded in-memory COPY parsing and date candidate facts, with no CSV files."""

import csv
import hashlib
import threading
from contextlib import contextmanager
from datetime import date

import duckdb

from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    history_business_key_fields,
    history_schema,
)
from orchestrator.defs.checks.moneyflow import audit_market_moneyflow_standardization
from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_equality,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_MAX_BUFFER_BYTES,
    MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW,
    MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT,
    MONEYFLOW_HISTORY_STREAM_BYTES,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_daily import daily_numeric_rejection_sql


@contextmanager
def history_candidate_connection(directory, check):
    """Interrupt blocking native work on cancellation or the caller's unit budget."""
    with moneyflow_candidate_connection(directory) as db:
        stop = threading.Event()
        errors = []

        def monitor():
            while not stop.wait(0.1):
                try:
                    check()
                except (MoneyflowContractError, InterruptedError, OSError) as error:
                    errors.append(error)
                    db.interrupt()
                    return

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            yield db
            check()
            if errors:
                raise errors[0]
        except duckdb.Error as error:
            if errors:
                raise errors[0] from error
            check()
            raise MoneyflowContractError("history_columnar_error") from error
        finally:
            stop.set()
            watcher.join()


def receive_history_rows(db, buffer, plan, unit_id, check):
    """Materialize one date unit columnarly; return only bounded scalar/date facts."""
    check()
    schema = history_schema(plan.dataset)
    fields = tuple(c.name for c in schema)
    size = buffer.tell()
    if not 0 < size <= MONEYFLOW_HISTORY_MAX_BUFFER_BYTES:
        raise MoneyflowContractError("history_buffer_bytes_budget")
    buffer.seek(0)
    header = buffer.readline(4097)
    try:
        if len(header) > 4096 or next(
            csv.reader([header.decode("utf8")], strict=True)
        ) != list(fields):
            raise MoneyflowContractError("history_copy_header")
    except (UnicodeError, csv.Error, StopIteration) as error:
        raise MoneyflowContractError("history_copy_header") from error
    digest = hashlib.sha256()
    parity, last_byte = 0, b""
    buffer.seek(0)
    while block := buffer.read(MONEYFLOW_HISTORY_STREAM_BYTES):
        check()
        digest.update(block)
        parity ^= block.count(b'"') % 2
        last_byte = block[-1:]
    if parity or last_byte != b"\n":
        raise MoneyflowContractError("history_copy_incomplete")
    buffer.seek(0)
    relation = db.read_csv(
        buffer,
        columns=dict.fromkeys(fields, "VARCHAR"),
        header=True,
        auto_detect=False,
        delimiter=",",
        quotechar='"',
        escapechar='"',
        na_values=r"\N",
        allow_quoted_nulls=False,
        parallel=False,
        strict_mode=True,
    )
    relation.create_view("copy_input")
    db.execute("CREATE TEMP TABLE source_rows AS SELECT * FROM copy_input")
    db.execute("DROP VIEW copy_input")
    del relation
    check()
    rows = db.execute("SELECT count(*) FROM source_rows").fetchone()[0]
    if rows > MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT:
        raise MoneyflowContractError("history_rows_budget")
    unit = plan.units[unit_id]
    if rows != unit.row_count:
        raise MoneyflowContractError("history_copy_row_count")
    keys = history_business_key_fields(plan.dataset)
    key_sql = ",".join(f'"{key}"' for key in keys)
    identity = " OR ".join(f'"{key}" IS NULL OR trim("{key}") = \'\'' for key in keys)
    if db.execute(f"SELECT count(*) FROM source_rows WHERE {identity}").fetchone()[0]:
        raise MoneyflowContractError("history_copy_identity")
    if db.execute(
        f"SELECT count(*) FROM (SELECT {key_sql} FROM source_rows GROUP BY {key_sql} HAVING count(*) != 1)"
    ).fetchone()[0]:
        raise MoneyflowContractError("history_copy_duplicate_key")
    if db.execute(
        "SELECT count(*) FROM source_rows WHERE NOT regexp_full_match(trade_date,'[0-9]{4}-[0-9]{2}-[0-9]{2}') OR try_cast(trade_date AS DATE) IS NULL"
    ).fetchone()[0]:
        raise MoneyflowContractError("history_copy_date")
    dates = db.execute(
        "SELECT trade_date,count(*) FROM source_rows GROUP BY trade_date ORDER BY trade_date"
    ).fetchmany(MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW + 1)
    expected = {
        fact.trade_date: fact.row_count
        for fact in plan.date_counts
        if fact.trade_date in unit.dates
    }
    if dict(dates) != expected:
        raise MoneyflowContractError("history_copy_date_counts")
    scopes = []
    if plan.dataset == "moneyflow_ind_dc":
        if db.execute(
            "SELECT count(*) FROM source_rows WHERE content_type NOT IN ('行业','概念','地域')"
        ).fetchone()[0]:
            raise MoneyflowContractError("history_copy_content_type")
        scopes = db.execute(
            "SELECT trade_date,content_type,count(*) FROM source_rows GROUP BY trade_date,content_type ORDER BY trade_date,content_type"
        ).fetchmany(3 * MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW + 1)
    for column in schema:
        if column.type == "VARCHAR":
            continue
        check()
        name = column.name
        db.execute(
            f'CREATE OR REPLACE TEMP VIEW numeric_values AS SELECT "{name}", CASE WHEN "{name}" IS NULL THEN \'NULL\' ELSE \'VARCHAR\' END AS "{name}_json_type" FROM source_rows'
        )
        if db.execute(
            f"SELECT count(*) FROM numeric_values WHERE {daily_numeric_rejection_sql(name, column.type)}"
        ).fetchone()[0]:
            raise MoneyflowContractError("history_copy_numeric:" + name)
    db.execute("DROP VIEW IF EXISTS numeric_values")
    projection = ",".join(
        'strftime(CAST("trade_date" AS DATE),\'%Y%m%d\') AS "trade_date"'
        if column.name == "trade_date"
        else f'CAST("{column.name}" AS {column.type}) AS "{column.name}"'
        for column in schema
    )
    db.execute(
        f"CREATE TEMP TABLE history_rows AS SELECT {projection} FROM source_rows"
    )
    db.execute("DROP TABLE source_rows")
    check()
    return {
        "rows": rows,
        "bytes": size,
        "source_sha256": digest.hexdigest(),
        "date_counts": [list(value) for value in dates],
        "scope_counts": [list(value) for value in scopes],
    }


def audit_history_day(db, raw, silver, day, *, dataset):
    if dataset == "moneyflow_mkt_dc":
        audit_market_moneyflow_standardization(db, raw, silver, day)
        return 1
    # Historical counts use the date-unit limit, not today's daily round/scope rules.
    keys = history_business_key_fields(dataset)
    key_sql = ",".join(f'"{key}"' for key in keys)
    invalid_key = " OR ".join(
        f'"{key}" IS NULL OR trim("{key}")=\'\'' for key in keys if key != "trade_date"
    )
    scope_check = (
        " OR content_type NOT IN ('行业','概念','地域')"
        if dataset == "moneyflow_ind_dc"
        else ""
    )
    counts = []
    for path, is_silver in ((raw, False), (silver, True)):
        schema = history_schema(dataset, silver=is_silver)
        actual = db.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchall()
        if [(r[0], r[1]) for r in actual] != [(c.name, c.type) for c in schema]:
            raise MoneyflowContractError("file_schema")
        count, invalid, keys = db.execute(
            "SELECT count(*),count(*) FILTER(WHERE trade_date IS NULL OR trade_date != ? "
            f"OR {invalid_key}{scope_check}),count(DISTINCT ({key_sql})) "
            "FROM read_parquet(?,hive_partitioning=false)",
            [date.fromisoformat(day) if is_silver else day.replace("-", ""), str(path)],
        ).fetchone()
        if (
            not 0 < count <= MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT
            or invalid
            or keys != count
        ):
            raise MoneyflowContractError("file_count_date_or_key")
        counts.append(count)
    if counts[0] != counts[1]:
        raise MoneyflowContractError("standardization_count")
    audit_daily_moneyflow_equality(db, raw, silver, second_silver=True, dataset=dataset)
    return counts[0]


def history_source_difference(db, raw_files, *, dataset):
    """Compare typed source rows and existing daily Raw, independent of wire order."""
    columns = ",".join(f'"{column.name}"' for column in history_schema(dataset))
    count = db.execute(
        f"SELECT count(*) FROM ((SELECT {columns} FROM history_rows EXCEPT SELECT {columns} FROM read_parquet($paths,hive_partitioning=false)) UNION ALL "
        f"(SELECT {columns} FROM read_parquet($paths,hive_partitioning=false) EXCEPT SELECT {columns} FROM history_rows))",
        {"paths": [str(path) for path in raw_files]},
    ).fetchone()[0]
    samples = []
    if count:
        samples = db.execute(
            f"SELECT {columns} FROM history_rows EXCEPT SELECT {columns} FROM read_parquet($paths,hive_partitioning=false) LIMIT 20",
            {"paths": [str(path) for path in raw_files]},
        ).fetchmany(20)
        # Only rejected samples cross into Python; Decimal is kept as exact text.
        samples = [
            [None if item is None else str(item) for item in row] for row in samples
        ]
    return count, samples
