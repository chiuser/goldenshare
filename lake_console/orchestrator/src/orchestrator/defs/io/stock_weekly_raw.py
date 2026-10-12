"""Bounded annual Raw assembly; original business values remain unchanged."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
    weekly_key_columns,
    weekly_required_columns,
    weekly_schema_hash,
)

WEEK_SQL = "strftime(date_trunc('week', strptime(trade_date, '%Y%m%d')) + INTERVAL 4 DAY, '%Y-%m-%d')"
HASH_VERSION = "weekly-canonical-v1"


def columns(source):
    return ", ".join(f'"{name}"' for name, _, _ in weekly_column_specs(source))


def load_relation(connection, name, paths, source, *, materialize=True):
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
    if paths and not materialize:
        connection.from_parquet(
            [str(p) for p in paths], hive_partitioning=False, union_by_name=False
        ).create_view(name, replace=True)
    elif paths:
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT * FROM read_parquet(?, hive_partitioning=false, union_by_name=false)",
            [[str(p) for p in paths]],
        )
    else:
        schema = ", ".join(f'"{n}" {t}' for n, t in expected)
        connection.execute(f"CREATE OR REPLACE TEMP TABLE {name} ({schema})")


def validate_relation(connection, name, source, budget, *, unique):
    required = " OR ".join(f'"{n}" IS NULL' for n in weekly_required_columns(source))
    code_invalid = (
        "length(trim(ts_code))=0 OR length(ts_code)>16"
        if source is StockWeeklySource.PRIMARY_ADJUSTED
        else "NOT regexp_full_match(ts_code, '[0-9]{6}\\.(SH|SZ|BJ)')"
    )
    invalid = f"{required} OR {code_invalid} OR NOT regexp_full_match(trade_date, '[0-9]{{8}}') OR try_strptime(trade_date, '%Y%m%d') IS NULL"
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


def assemble_adjusted_bootstrap_relation(connection, *, year, budget):
    """Complete captured Prod keys replace values; DG-only keys remain intact."""
    source = StockWeeklySource.PRIMARY_ADJUSTED
    cols = columns(source)
    keys = ", ".join(weekly_key_columns(source))
    incoming = validate_relation(
        connection, "weekly_input", source, budget, unique=True
    )
    existing = validate_relation(
        connection, "weekly_existing", source, budget, unique=True
    )
    if incoming + existing > budget.max_phase_rows:
        raise WeeklyCaptureError("raw_row_budget_exceeded")
    for relation in ("weekly_input", "weekly_existing"):
        if connection.execute(
            f"SELECT count(*) FROM {relation} WHERE substr({WEEK_SQL},1,4)<>?",
            [str(year)],
        ).fetchone()[0]:
            raise WeeklyCaptureError("target_year_mismatch")
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW weekly_unique AS SELECT {cols} FROM weekly_input"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW weekly_preserved AS SELECT {cols} FROM weekly_existing "
        f"ANTI JOIN weekly_unique USING ({keys})"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW weekly_combined AS SELECT {cols} FROM weekly_preserved "
        f"UNION ALL SELECT {cols} FROM weekly_unique"
    )
    replaced = connection.execute(
        f"SELECT count(*) FROM weekly_existing SEMI JOIN weekly_unique USING ({keys})"
    ).fetchone()[0]
    return {
        "source_rows": incoming,
        "owned_source_rows": incoming,
        "unique_source_rows": incoming,
        "duplicate_rows": 0,
        "existing_rows": existing,
        "replaced_keys": replaced,
        "new_keys": incoming - replaced,
        "preserved_keys": existing - replaced,
        "candidate_rows": existing + incoming - replaced,
        "value_difference_rows": 0,
        "preserved_difference_rows": 0,
    }


def assemble_adjusted_delivery_relation(connection, *, year, budget):
    """Replace whole input rows; preserve every unselected old key and value.

    weekly_input carries the 21 columns plus immutable unit id/revision/kind.
    Scope validation happens when each closed unit is captured. This relation
    only permits the planned point/history overlap, ordered by publication.
    """
    source = StockWeeklySource.PRIMARY_ADJUSTED
    cols = columns(source)
    keys = ", ".join(weekly_key_columns(source))
    incoming = validate_relation(
        connection, "weekly_input", source, budget, unique=False
    )
    existing = validate_relation(
        connection, "weekly_existing", source, budget, unique=True
    )
    if incoming + existing > budget.max_phase_rows:
        raise WeeklyCaptureError("raw_row_budget_exceeded")
    for relation in ("weekly_input", "weekly_existing"):
        if connection.execute(
            f"SELECT count(*) FROM {relation} WHERE substr({WEEK_SQL},1,4)<>?",
            [str(year)],
        ).fetchone()[0]:
            raise WeeklyCaptureError("target_year_mismatch")
    if connection.execute(
        "SELECT count(*) FROM weekly_input WHERE _unit_kind NOT IN ('point_week','stock_history') "
        "OR _unit_kind IS NULL OR _unit_id IS NULL OR _unit_revision IS NULL OR _unit_revision<1"
    ).fetchone()[0]:
        raise WeeklyCaptureError("adjusted_delivery_unit_metadata_invalid")
    if connection.execute(
        "SELECT count(*) FROM (SELECT _unit_id FROM weekly_input GROUP BY _unit_id "
        "HAVING count(DISTINCT _unit_revision)<>1 OR count(DISTINCT _unit_kind)<>1)"
    ).fetchone()[0]:
        raise WeeklyCaptureError("adjusted_delivery_unit_metadata_conflict")
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_unit_unique AS SELECT DISTINCT {cols},"
        "_unit_id,_unit_revision,_unit_kind FROM weekly_input"
    )
    if connection.execute(
        f"SELECT count(*) FROM (SELECT {keys},_unit_id FROM weekly_unit_unique "
        f"GROUP BY {keys},_unit_id HAVING count(*)>1)"
    ).fetchone()[0]:
        raise WeeklyCaptureError("adjusted_delivery_same_unit_key_conflict")
    if connection.execute(
        f"SELECT count(*) FROM (SELECT {keys} FROM weekly_unit_unique GROUP BY {keys} "
        "HAVING count(*)>1 AND (count(*)<>2 OR count(DISTINCT _unit_revision)<>2 "
        "OR count(*) FILTER (WHERE _unit_kind='point_week')<>1 "
        "OR count(*) FILTER (WHERE _unit_kind='stock_history')<>1))"
    ).fetchone()[0]:
        raise WeeklyCaptureError("adjusted_delivery_unplanned_overlap")
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_unique AS SELECT {cols} FROM weekly_unit_unique "
        f"QUALIFY row_number() OVER (PARTITION BY {keys} ORDER BY _unit_revision DESC)=1"
    )
    unique = validate_relation(connection, "weekly_unique", source, budget, unique=True)
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW weekly_preserved AS SELECT {cols} FROM weekly_existing "
        f"ANTI JOIN weekly_unique USING ({keys})"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW weekly_combined AS SELECT {cols} FROM weekly_preserved "
        f"UNION ALL SELECT {cols} FROM weekly_unique"
    )
    total = validate_relation(
        connection, "weekly_combined", source, budget, unique=True
    )
    # EXCEPT ALL compares every typed value, preserving SQL NULL semantics.
    selected_difference = connection.execute(
        f"SELECT count(*) FROM ((SELECT {cols} FROM weekly_unique EXCEPT ALL "
        f"SELECT {cols} FROM weekly_combined SEMI JOIN weekly_unique USING ({keys})) "
        f"UNION ALL (SELECT {cols} FROM weekly_combined SEMI JOIN weekly_unique USING ({keys}) "
        f"EXCEPT ALL SELECT {cols} FROM weekly_unique))"
    ).fetchone()[0]
    preserved_difference = 0
    weeks = connection.execute(
        f"SELECT DISTINCT {WEEK_SQL} FROM weekly_input ORDER BY 1"
    ).fetchall()
    for (week,) in weeks:
        predicate = _week_date_predicate(week)
        preserved_difference += connection.execute(
            f"SELECT count(*) FROM ((SELECT {cols} FROM weekly_preserved WHERE {predicate} "
            f"EXCEPT ALL SELECT {cols} FROM weekly_combined ANTI JOIN weekly_unique USING ({keys}) WHERE {predicate}) "
            f"UNION ALL (SELECT {cols} FROM weekly_combined ANTI JOIN weekly_unique USING ({keys}) WHERE {predicate} "
            f"EXCEPT ALL SELECT {cols} FROM weekly_preserved WHERE {predicate}))"
        ).fetchone()[0]
    if selected_difference or preserved_difference:
        raise WeeklyCaptureError("adjusted_delivery_value_reconciliation_failed")
    replaced = connection.execute(
        f"SELECT count(*) FROM weekly_existing SEMI JOIN weekly_unique USING ({keys})"
    ).fetchone()[0]
    return {
        "source_rows": incoming,
        "unique_source_rows": unique,
        "duplicate_rows": incoming - unique,
        "existing_rows": existing,
        "replaced_keys": replaced,
        "new_keys": unique - replaced,
        "preserved_keys": existing - replaced,
        "candidate_rows": total,
        "value_difference_rows": selected_difference,
        "preserved_difference_rows": preserved_difference,
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


def _week_date_predicate(week):
    # Validated ISO partition -> source dates, allowing Parquet range pruning.
    friday = date.fromisoformat(week)
    if friday.weekday() != 4:
        raise WeeklyCaptureError("candidate_partition_mismatch")
    monday = (friday - timedelta(days=4)).strftime("%Y%m%d")
    sunday = (friday + timedelta(days=2)).strftime("%Y%m%d")
    return f"trade_date BETWEEN '{monday}' AND '{sunday}'"


def write_and_audit_adjusted_delivery_candidates(
    connection,
    budget,
    directory: Path,
    *,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """Keep annual planning; write/compare one affected week at a time."""
    from orchestrator.defs.bootstrap.stock_weekly_capture import check_weekly_cancel

    source = StockWeeklySource.PRIMARY_ADJUSTED
    cols = columns(source)
    keys = ", ".join(weekly_key_columns(source))
    weeks = connection.execute(
        f"SELECT DISTINCT {WEEK_SQL} FROM weekly_combined ORDER BY 1"
    ).fetchall()
    if len(weeks) > 54:
        raise WeeklyCaptureError("raw_partition_budget_exceeded")
    expected, paths = {}, []
    for index, (week,) in enumerate(weeks):
        check_weekly_cancel(cancel)
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW weekly_expected AS SELECT {cols} "
            f"FROM weekly_combined WHERE {_week_date_predicate(week)}"
        )
        hashes = relation_hashes(connection, "weekly_expected", source, budget)
        if set(hashes) != {week}:
            raise WeeklyCaptureError("candidate_partition_mismatch")
        path = directory / f"week_end={week}" / "part-0.parquet"
        path.parent.mkdir(parents=True)
        connection.execute(
            f"COPY (SELECT {cols} FROM weekly_expected ORDER BY {keys}) TO ? "
            "(FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(path)],
        )
        load_relation(connection, "weekly_candidate", [path], source, materialize=False)
        validate_relation(connection, "weekly_candidate", source, budget, unique=True)
        difference = connection.execute(
            f"SELECT count(*) FROM ((SELECT {cols} FROM weekly_expected EXCEPT ALL "
            f"SELECT {cols} FROM weekly_candidate) UNION ALL (SELECT {cols} FROM weekly_candidate "
            f"EXCEPT ALL SELECT {cols} FROM weekly_expected))"
        ).fetchone()[0]
        if (
            difference
            or relation_hashes(connection, "weekly_candidate", source, budget) != hashes
        ):
            raise WeeklyCaptureError("candidate_readback_mismatch")
        expected.update(hashes)
        paths.append(path)
        progress(
            {
                "stage": "candidate_verified",
                "week": week,
                "completed_files": index + 1,
                "total_files": len(weeks),
            }
        )
        check_weekly_cancel(cancel)
    return expected, paths
