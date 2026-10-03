"""Bounded annual Raw assembly; original business values remain unchanged."""

from __future__ import annotations

from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.run_contracts.stock_weekly import (
    weekly_column_specs,
    weekly_key_columns,
    weekly_required_columns,
    weekly_schema_hash,
)

WEEK_SQL = "strftime(date_trunc('week', strptime(trade_date, '%Y%m%d')) + INTERVAL 4 DAY, '%Y-%m-%d')"
HASH_VERSION = "weekly-canonical-v1"


def columns(source):
    return ", ".join(f'"{name}"' for name, _, _ in weekly_column_specs(source))


def load_relation(connection, name, paths, source):
    """Each file must have the exact physical schema, before unioning."""
    expected = [(n, t) for n, t, _ in weekly_column_specs(source)]
    for path in paths:
        observed = [
            r[:2]
            for r in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                [str(path)],
            ).fetchall()
        ]
        if observed != expected:
            raise WeeklyCaptureError("raw_schema_mismatch")
    if paths:
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT * FROM read_parquet(?, hive_partitioning=false, union_by_name=false)",
            [[str(p) for p in paths]],
        )
    else:
        schema = ", ".join(f'"{n}" {t}' for n, t in expected)
        connection.execute(f"CREATE OR REPLACE TEMP TABLE {name} ({schema})")


def validate_relation(connection, name, source, budget, *, unique):
    required = " OR ".join(f'"{n}" IS NULL' for n in weekly_required_columns(source))
    invalid = f"{required} OR NOT regexp_full_match(ts_code, '[0-9]{{6}}\\.(SH|SZ|BJ)') OR NOT regexp_full_match(trade_date, '[0-9]{{8}}') OR try_strptime(trade_date, '%Y%m%d') IS NULL"
    if any(n == "freq" for n, _, _ in weekly_column_specs(source)):
        invalid += " OR freq <> 'week'"
    finite = [n for n, t, _ in weekly_column_specs(source) if t == "DOUBLE"]
    if source.value == "weekly":
        invalid += " OR vol < 0 OR amount < 0"
    if finite:
        invalid += " OR " + " OR ".join(f'NOT isfinite("{n}")' for n in finite)
    if connection.execute(f"SELECT count(*) FROM {name} WHERE {invalid}").fetchone()[0]:
        raise WeeklyCaptureError("raw_key_or_value_invalid")
    count, codes = connection.execute(
        f"SELECT count(*), count(DISTINCT ts_code) FROM {name}"
    ).fetchone()
    if count > budget.max_phase_rows or codes > budget.max_codes:
        raise WeeklyCaptureError("raw_row_budget_exceeded")
    keys = ", ".join(weekly_key_columns(source))
    if (
        unique
        and connection.execute(
            f"SELECT count(*) FROM (SELECT {keys} FROM {name} GROUP BY {keys} HAVING count(*)>1)"
        ).fetchone()[0]
    ):
        raise WeeklyCaptureError("raw_duplicate_key")
    return count


def relation_hashes(connection, name, source, budget):
    """JSON list preserves NULL; typed decimal text and normalized signed zero."""
    values = []
    for n, t, _ in weekly_column_specs(source):
        values.append(
            f'CASE WHEN "{n}"=0 THEN \'0.0\' ELSE CAST("{n}" AS VARCHAR) END'
            if t == "DOUBLE"
            else f'CAST("{n}" AS VARCHAR)'
        )
    row_hash = f"sha256(to_json(list_value({', '.join(values)})))"
    keys = ", ".join(weekly_key_columns(source))
    grouped = connection.execute(
        f"SELECT {WEEK_SQL} AS week_end, count(*) AS rows FROM {name} GROUP BY week_end"
    ).fetchall()
    if len(grouped) > 54 or any(r[1] > budget.max_codes * 7 for r in grouped):
        raise WeeklyCaptureError("raw_partition_budget_exceeded")
    return {
        week: {"rows": rows, "logical_hash": digest}
        for week, rows, digest in connection.execute(
            f"SELECT {WEEK_SQL} AS week_end, count(*), sha256(? || string_agg({row_hash}, '' ORDER BY {keys})) FROM {name} GROUP BY week_end ORDER BY week_end",
            [HASH_VERSION + ":" + weekly_schema_hash(source) + ":"],
        ).fetchall()
    }


def assemble_relation(connection, source, year, budget, excluded):
    cols = columns(source)
    source_rows = validate_relation(
        connection, "weekly_input", source, budget, unique=False
    )
    existing_rows = validate_relation(
        connection, "weekly_existing", source, budget, unique=True
    )
    if source_rows + existing_rows > budget.max_phase_rows:
        raise WeeklyCaptureError("raw_row_budget_exceeded")
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_owned AS SELECT * FROM weekly_input WHERE substr({WEEK_SQL},1,4)=?",
        [str(year)],
    )
    owned = connection.execute("SELECT count(*) FROM weekly_owned").fetchone()[0]
    connection.execute("CREATE OR REPLACE TEMP TABLE weekly_excluded(week_end VARCHAR)")
    if excluded:
        connection.executemany(
            "INSERT INTO weekly_excluded VALUES (?)", [(w,) for w in excluded]
        )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_selected AS SELECT * FROM weekly_owned WHERE {WEEK_SQL} NOT IN (SELECT week_end FROM weekly_excluded)"
    )
    selected = connection.execute("SELECT count(*) FROM weekly_selected").fetchone()[0]
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_unique AS SELECT DISTINCT {cols} FROM weekly_selected"
    )
    unique = validate_relation(connection, "weekly_unique", source, budget, unique=True)
    # Conflicts, including NULL versus a value, fail before any candidate write.
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_combined AS SELECT {cols} FROM weekly_existing UNION SELECT {cols} FROM weekly_unique"
    )
    total = validate_relation(
        connection, "weekly_combined", source, budget, unique=True
    )
    if connection.execute(
        f"SELECT count(*) FROM weekly_existing WHERE substr({WEEK_SQL},1,4)<>?",
        [str(year)],
    ).fetchone()[0]:
        raise WeeklyCaptureError("target_year_mismatch")
    non_friday = connection.execute(
        "SELECT count(*) FROM weekly_selected WHERE dayofweek(strptime(trade_date,'%Y%m%d'))<>5"
    ).fetchone()[0]
    optional = [
        n
        for n, _, _ in weekly_column_specs(source)
        if n not in weekly_required_columns(source)
    ]
    nulls = " OR ".join(f'"{n}" IS NULL' for n in optional)
    null_rows = connection.execute(
        f"SELECT count(*) FROM weekly_selected WHERE {nulls}"
    ).fetchone()[0]
    abnormal_ohlc = connection.execute(
        "SELECT count(*) FROM weekly_selected WHERE high<low OR open>high OR open<low OR close>high OR close<low OR vol<0 OR amount<0"
    ).fetchone()[0]
    return {
        "null_business_rows": null_rows,
        "abnormal_ohlc_or_volume_rows": abnormal_ohlc,
        "source_rows": source_rows,
        "owned_rows": owned,
        "boundary_rows": source_rows - owned,
        "excluded_rows": owned - selected,
        "duplicate_rows": selected - unique,
        "unique_source_rows": unique,
        "existing_rows": existing_rows,
        "new_keys": total - existing_rows,
        "candidate_rows": total,
        "non_friday_rows": non_friday,
    }


def write_and_audit_candidates(connection, source, budget, directory: Path):
    expected = relation_hashes(connection, "weekly_combined", source, budget)
    if expected:
        connection.execute(
            f"COPY (SELECT {columns(source)}, {WEEK_SQL} AS week_end FROM weekly_combined ORDER BY {', '.join(weekly_key_columns(source))}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (week_end), WRITE_PARTITION_COLUMNS false, FILENAME_PATTERN 'part-{{i}}')",
            [str(directory)],
        )
    paths = sorted(directory.glob("week_end=*/*.parquet"))
    if len(paths) != len(expected):
        raise WeeklyCaptureError("candidate_file_count_mismatch")
    load_relation(connection, "weekly_candidate", paths, source)
    validate_relation(connection, "weekly_candidate", source, budget, unique=True)
    difference = connection.execute(
        "SELECT count(*) FROM ((SELECT * FROM weekly_combined EXCEPT ALL SELECT * FROM weekly_candidate) UNION ALL (SELECT * FROM weekly_candidate EXCEPT ALL SELECT * FROM weekly_combined))"
    ).fetchone()[0]
    if (
        difference
        or relation_hashes(connection, "weekly_candidate", source, budget) != expected
    ):
        raise WeeklyCaptureError("candidate_readback_mismatch")
    for path in paths:
        week = path.parent.name.removeprefix("week_end=")
        if connection.execute(
            f"SELECT count(*) FROM read_parquet(?, hive_partitioning=false) WHERE {WEEK_SQL}<>?",
            [str(path), week],
        ).fetchone()[0]:
            raise WeeklyCaptureError("candidate_partition_mismatch")
    return expected, paths
