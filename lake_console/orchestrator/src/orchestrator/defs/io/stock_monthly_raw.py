"""Strict source mirror and month-version classification using bounded DuckDB SQL."""

from __future__ import annotations

import csv
from pathlib import Path

from orchestrator.defs.run_contracts.stock_monthly import (
    monthly_column_specs,
    monthly_contract_hash,
)

MONTH_SQL = "substr(trade_date,1,4)||'-'||substr(trade_date,5,2)"
ANCHOR_SQL = "CASE WHEN substr(trade_date,1,6)='202002' THEN '20200228' ELSE strftime(last_day(try_strptime(trade_date,'%Y%m%d')), '%Y%m%d') END"


def monthly_columns(source) -> str:
    return ",".join(f'"{name}"' for name, _ in monthly_column_specs(source))


def validate_month_relation(
    connection, relation, source, policy, *, max_rows, allow_excluded=False
):
    if relation not in (
        "monthly_csv",
        "monthly_capture",
        "monthly_year",
        "monthly_candidate",
    ):
        raise ValueError("monthly_relation_invalid")
    specs = list(monthly_column_specs(source))
    observed = [
        row[:2] for row in connection.execute(f"DESCRIBE {relation}").fetchall()
    ]
    if observed != specs:
        raise ValueError("monthly_schema_mismatch")
    count, codes = connection.execute(
        f"SELECT count(*), count(DISTINCT ts_code) FROM {relation}"
    ).fetchone()
    if count > max_rows or codes > policy.max_codes:
        raise ValueError("monthly_row_budget_exceeded")
    invalid = "ts_code IS NULL OR NOT regexp_full_match(ts_code, '[0-9]{6}\\.(SH|SZ|BJ)') OR freq IS NULL OR freq <> 'month' OR trade_date IS NULL OR NOT regexp_full_match(trade_date,'[0-9]{8}') OR try_strptime(trade_date,'%Y%m%d') IS NULL OR (end_date IS NOT NULL AND (NOT regexp_full_match(end_date,'[0-9]{8}') OR try_strptime(end_date,'%Y%m%d') IS NULL))"
    if connection.execute(
        f"SELECT count(*) FROM {relation} WHERE {invalid}"
    ).fetchone()[0]:
        raise ValueError("monthly_key_or_date_invalid")
    exemption = " AND trade_date <> '20200229'" if allow_excluded else ""
    if connection.execute(
        f"SELECT count(*) FROM {relation} WHERE trade_date <> {ANCHOR_SQL}{exemption}"
    ).fetchone()[0]:
        raise ValueError("unexpected_month_source_date")
    if connection.execute(
        f"SELECT count(*) FROM (SELECT ts_code,trade_date,freq FROM {relation} GROUP BY ts_code,trade_date,freq HAVING count(*)>1)"
    ).fetchone()[0]:
        raise ValueError("monthly_duplicate_key")
    return count


def load_monthly_csv(connection, path: Path, unit, policy, expected_rows):
    specs = monthly_column_specs(unit.source)
    with path.open(newline="", encoding="utf-8") as stream:
        if next(csv.reader(stream), None) != [n for n, _ in specs]:
            raise ValueError("monthly_source_schema_mismatch")
    csv_columns = "{" + ",".join(f"'{n}':'VARCHAR'" for n, _ in specs) + "}"
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE monthly_csv AS SELECT * FROM read_csv(?, columns={csv_columns}, header=true, auto_detect=false, nullstr='\\N', allow_quoted_nulls=false, strict_mode=true) LIMIT {unit.max_rows + 1}",
        [str(path)],
    )
    count = connection.execute("SELECT count(*) FROM monthly_csv").fetchone()[0]
    if count > unit.max_rows:
        raise ValueError("monthly_unit_row_budget_exceeded")
    if count != expected_rows:
        raise ValueError("monthly_source_count_changed")
    invalid_numbers = []
    for name, kind in specs:
        if kind.startswith("DECIMAL"):
            invalid_numbers.append(
                f'("{name}" IS NOT NULL AND (NOT regexp_full_match("{name}", \'[+-]?[0-9]+(\\.[0-9]{{1,4}})?\') OR try_cast("{name}" AS {kind}) IS NULL))'
            )
    if connection.execute(
        "SELECT count(*) FROM monthly_csv WHERE " + " OR ".join(invalid_numbers)
    ).fetchone()[0]:
        raise ValueError("monthly_decimal_invalid_or_lossy")
    projection = ",".join(f'CAST("{n}" AS {t}) AS "{n}"' for n, t in specs)
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE monthly_capture AS SELECT {projection} FROM monthly_csv"
    )
    validate_month_relation(
        connection,
        "monthly_capture",
        unit.source,
        policy,
        max_rows=unit.max_rows,
        allow_excluded=True,
    )
    escaped_codes = ",".join(f"'{code}'" for code in unit.sorted_codes)
    if connection.execute(
        f"SELECT count(*) FROM monthly_capture WHERE ts_code NOT IN ({escaped_codes}) OR try_strptime(trade_date,'%Y%m%d') < CAST(? AS DATE) OR try_strptime(trade_date,'%Y%m%d') >= CAST(? AS DATE)",
        [unit.source_date_start, unit.source_date_end],
    ).fetchone()[0]:
        raise ValueError("monthly_source_outside_unit")
    return count


def load_monthly_parquets(connection, relation, paths, source):
    if relation not in ("monthly_capture", "monthly_year", "monthly_candidate"):
        raise ValueError("monthly_relation_invalid")
    specs = list(monthly_column_specs(source))
    for path in paths:
        observed = [
            r[:2]
            for r in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(path)],
            ).fetchall()
        ]
        if observed != specs:
            raise ValueError("monthly_schema_mismatch")
    if paths:
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {relation} AS SELECT * FROM read_parquet(?,hive_partitioning=false,union_by_name=false)",
            [[str(p) for p in paths]],
        )
    else:
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {relation} ("
            + ",".join(f'"{n}" {t}' for n, t in specs)
            + ")"
        )


def canonical_month_hashes(connection, relation, source):
    if relation not in ("monthly_capture", "monthly_year", "monthly_candidate"):
        raise ValueError("monthly_relation_invalid")
    values = ",".join(
        f'CAST("{n}" AS VARCHAR)' for n, _ in monthly_column_specs(source)
    )
    prefix = (
        "monthly-canonical-v1:"
        + monthly_contract_hash(monthly_column_specs(source))
        + ":"
    )
    return {
        month: {"rows": rows, "logical_hash": digest}
        for month, rows, digest in connection.execute(
            f"SELECT {MONTH_SQL}, count(*), sha256(? || string_agg(sha256(to_json(list_value({values}))), '' ORDER BY ts_code,trade_date,freq)) FROM {relation} GROUP BY 1 ORDER BY 1",
            [prefix],
        ).fetchall()
    }
