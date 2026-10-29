"""Build and audit one normal factor partition or an explicit old-key insert."""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
    silver_adj_factor_select,
)
from orchestrator.defs.run_contracts.adj_factor import (
    ADJ_FACTOR_RETIRED_RETENTION_START_DATE,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_ADJ_FACTOR_SCHEMA,
)
from orchestrator.defs.stock_factor_price_checks import audit_adj_factor_candidate_rules

CODE = re.compile(r"[0-9]{6}\.(SH|SZ|BJ)")


def normalize_restore_keys(
    values: Sequence[Mapping[str, str]], partition_key: str,
) -> tuple[tuple[str, str], ...]:
    if date.fromisoformat(partition_key).isoformat() != partition_key:
        raise ValueError("adj_factor_partition_date")
    keys = []
    for value in values:
        if not isinstance(value, Mapping) or set(value) != {"ts_code", "trade_date"}:
            raise ValueError("adj_factor_restore_key_fields")
        code, day = value["ts_code"], value["trade_date"]
        if (not isinstance(code, str) or CODE.fullmatch(code) is None
                or not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                or day >= ADJ_FACTOR_RETIRED_RETENTION_START_DATE):
            raise ValueError("adj_factor_restore_key_value")
        keys.append((code, day))
    if len(set(keys)) != len(keys):
        raise ValueError("adj_factor_restore_duplicate_keys")
    if partition_key < ADJ_FACTOR_RETIRED_RETENTION_START_DATE:
        if not any(day == partition_key for _, day in keys):
            raise ValueError("historical_partition_requires_explicit_restore")
    elif keys:
        raise ValueError("adj_factor_normal_partition_restore_config")
    return tuple(sorted(keys))


def _audit(connection, path: Path, day: str, raw_path: Path, lifecycle: Path, *, raw=False):
    counts = audit_adj_factor_candidate_rules(
        connection, path, day, raw=raw, lifecycle_path=lifecycle, raw_path=raw_path,
    )
    failures = {key: value for key, value in counts.items() if key != "rows" and value}
    if not counts["rows"] or failures:
        raise ValueError(f"adj_factor_candidate_rules_failed: {failures}")
    return counts


def _restore_sql(connection, target: Path, source_sql: str, day_keys) -> tuple[str, int]:
    if not target.is_file():
        raise FileNotFoundError("Historical factor restore requires the existing Silver file")
    observed = [(r[0], r[1]) for r in connection.execute(
        describe_parquet_query(target, hive_partitioning=False),
    ).fetchall()]
    if observed != [(column.name, column.type) for column in SILVER_ADJ_FACTOR_SCHEMA]:
        raise ValueError("adj_factor_restore_existing_schema")
    values = ",".join(
        f"({duckdb_string(code)},DATE {duckdb_string(day)})" for code, day in day_keys
    )
    requested = f"SELECT * FROM (VALUES {values}) AS keys(ts_code,trade_date)"
    selected = f"SELECT source.* FROM ({source_sql}) source JOIN ({requested}) USING(ts_code,trade_date)"
    selected_count = connection.execute(f"SELECT count(*) FROM ({selected})").fetchone()[0]
    if selected_count != len(day_keys):
        raise ValueError("adj_factor_restore_source_missing_or_identity_invalid")
    prior = f"SELECT ts_code,trade_date,adj_factor FROM {read_parquet(target)}"
    conflict_count = connection.execute(f"""
        SELECT count(*) FROM ({prior}) old JOIN ({selected}) source USING(ts_code,trade_date)
        WHERE old.adj_factor IS DISTINCT FROM source.adj_factor
    """).fetchone()[0]
    if conflict_count:
        raise ValueError("adj_factor_restore_existing_value_differs")
    missing = f"""SELECT source.* FROM ({selected}) source
        WHERE NOT EXISTS (SELECT 1 FROM ({prior}) old
          WHERE old.ts_code=source.ts_code AND old.trade_date=source.trade_date)"""
    missing_count = connection.execute(f"SELECT count(*) FROM ({missing})").fetchone()[0]
    return f"{prior} UNION ALL {missing}", int(missing_count)


def _assert_only_restored_keys(connection, target: Path, candidate: Path, day_keys, added: int):
    values = ",".join(
        f"({duckdb_string(code)},DATE {duckdb_string(day)})" for code, day in day_keys
    )
    # Compare all three original columns; counts alone cannot prove preservation.
    mismatch, row_delta = connection.execute(f"""
        WITH keys(ts_code,trade_date) AS (VALUES {values}),
        old AS (SELECT ts_code,trade_date,adj_factor FROM {read_parquet(target)}),
        new AS (SELECT ts_code,trade_date,adj_factor FROM {read_parquet(candidate)}),
        old_other AS (SELECT * FROM old ANTI JOIN keys USING(ts_code,trade_date)),
        new_other AS (SELECT * FROM new ANTI JOIN keys USING(ts_code,trade_date)),
        delta AS ((SELECT * FROM old_other EXCEPT ALL SELECT * FROM new_other)
          UNION ALL (SELECT * FROM new_other EXCEPT ALL SELECT * FROM old_other))
        SELECT (SELECT count(*) FROM delta),
               (SELECT count(*) FROM new)-(SELECT count(*) FROM old)
    """).fetchone()
    if mismatch or row_delta != added:
        raise ValueError("adj_factor_restore_changes_outside_explicit_keys")


def build_silver_adj_factor_candidate(
    connection, *, candidate: Path, target: Path, raw_path: Path,
    lifecycle: Path, day: str, restore_keys: tuple[tuple[str, str], ...],
    filter_counts: dict, overwrite: bool,
) -> dict:
    for path in (raw_path, lifecycle):
        if not path.is_file():
            raise FileNotFoundError(path)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    _audit(connection, raw_path, day, raw_path, lifecycle, raw=True)
    source_sql = silver_adj_factor_select(raw_path, lifecycle)
    day_keys = tuple(key for key in restore_keys if key[1] == day)
    inserted = 0
    if day < ADJ_FACTOR_RETIRED_RETENTION_START_DATE:
        select_sql, inserted = _restore_sql(connection, target, source_sql, day_keys)
        if inserted == 0:
            counts = _audit(connection, target, day, raw_path, lifecycle)
            return _result(filter_counts, counts["rows"], 0, historical=True, unchanged=True)
    else:
        select_sql = source_sql
    connection.execute(copy_query_to_parquet(select_sql, candidate))
    counts = _audit(connection, candidate, day, raw_path, lifecycle)
    if day_keys:
        _assert_only_restored_keys(connection, target, candidate, day_keys, inserted)
    return _result(filter_counts, counts["rows"], inserted, historical=bool(day_keys),
                   unchanged=False)


def _result(filter_counts, rows, inserted, *, historical, unchanged):
    result = dict(filter_counts, rows=rows, restored_row_count=inserted, unchanged=unchanged,
                  source_eligible_row_count=filter_counts["selected_row_count"],
                  write_mode="restore_missing_keys" if historical else "normal")
    if historical:
        result.update(selected_row_count=inserted,
                      rejected_row_count=filter_counts["source_row_count"] - inserted,
                      preserved_row_count=rows - inserted)
    else:
        result["preserved_row_count"] = 0
    return result
