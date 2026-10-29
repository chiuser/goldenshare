"""Pure existing factor/price checks shared by candidates and formal consumers."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_sql import (
    adj_factor_required_stock_select,
    adj_factor_retained_record_predicate_sql,
    adj_factor_retained_stock_select,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
    silver_adj_factor_select,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.run_contracts.adj_factor import (
    ADJ_FACTOR_RETIRED_RETENTION_START_DATE,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
)

ADJ_FACTOR_RAW_COLUMN_TYPES = {c.name: c.type for c in RAW_TUSHARE_ADJ_FACTOR_SCHEMA}
ADJ_FACTOR_SILVER_COLUMN_TYPES = {c.name: c.type for c in SILVER_ADJ_FACTOR_SCHEMA}
ADJ_FACTOR_MIN_TRADE_DATE = "2009-01-05"
ADJ_FACTOR_PARTITION_SET = cn_a_stock_current_trade_days.name
ADJ_FACTOR_INVALID_VALUE_PREDICATE = "adj_factor IS NULL OR NOT isfinite(adj_factor) OR adj_factor <= 0"

def adj_factor_duplicate_keys_sql(path: Path) -> str:
    return f"""SELECT ts_code,trade_date,count(*) AS duplicate_count
               FROM {read_parquet(path, hive_partitioning=False)}
               GROUP BY ts_code,trade_date HAVING count(*)>1"""


def adj_factor_invalid_lifecycle_sql(path: Path, lifecycle_path: Path) -> str:
    lifecycle = adj_factor_retained_stock_select(lifecycle_path)
    return f"""WITH stock_lifecycle AS ({lifecycle})
      SELECT adj.ts_code,adj.trade_date,stock_lifecycle.list_date,
             stock_lifecycle.delist_date,adj.adj_factor
      FROM {read_parquet(path, hive_partitioning=False)} adj
      LEFT JOIN stock_lifecycle ON adj.ts_code=stock_lifecycle.ts_code
      WHERE NOT ({adj_factor_retained_record_predicate_sql("adj.trade_date", lifecycle_alias="stock_lifecycle")})
    """


def adj_factor_coverage_relations_sql(
    path: Path, lifecycle_path: Path, partition_key: str, *, raw_path: Path | None = None,
) -> str:
    """Required identities and permitted/source rows are separate contracts."""
    retained = adj_factor_retained_stock_select(lifecycle_path)
    required = adj_factor_required_stock_select(lifecycle_path, partition_key)
    day = f"DATE {duckdb_string(partition_key)}"
    if partition_key >= ADJ_FACTOR_RETIRED_RETENTION_START_DATE:
        if raw_path is None or not raw_path.exists():
            raise FileNotFoundError("Raw factor partition is required for retained-source validation")
        source_expected = silver_adj_factor_select(raw_path, lifecycle_path)
    else:
        source_expected = "SELECT NULL::VARCHAR ts_code,NULL::DATE trade_date,NULL::DOUBLE adj_factor WHERE false"
    source_actual = (
        f"SELECT ts_code,trade_date,adj_factor FROM {read_parquet(path)} WHERE trade_date={day}"
        if partition_key >= ADJ_FACTOR_RETIRED_RETENTION_START_DATE
        else "SELECT NULL::VARCHAR ts_code,NULL::DATE trade_date,NULL::DOUBLE adj_factor WHERE false"
    )
    return f"""WITH expected AS (
      SELECT DISTINCT ts_code FROM ({required})
    ),actual AS (
      SELECT DISTINCT ts_code FROM {read_parquet(path)} WHERE trade_date={day}
    ),allowed AS (
      SELECT DISTINCT ts_code FROM ({retained}) lifecycle
      WHERE {adj_factor_retained_record_predicate_sql(day)}
    ),source_expected AS ({source_expected}),source_actual AS ({source_actual}),
    source_missing AS (SELECT * FROM source_expected EXCEPT ALL SELECT * FROM source_actual),
    source_unexpected AS (SELECT * FROM source_actual EXCEPT ALL SELECT * FROM source_expected)
    """


def adj_factor_coverage_counts_sql(
    path: Path, lifecycle_path: Path, partition_key: str, *, raw_path: Path | None = None,
) -> str:
    relations = adj_factor_coverage_relations_sql(path, lifecycle_path, partition_key, raw_path=raw_path)
    return f"""{relations}
    SELECT (SELECT count(*) FROM expected), (SELECT count(*) FROM actual),
      (SELECT count(*) FROM (SELECT ts_code FROM expected EXCEPT SELECT ts_code FROM actual)),
      (SELECT count(*) FROM (SELECT ts_code FROM actual EXCEPT SELECT ts_code FROM allowed)),
      (SELECT count(*) FROM source_missing), (SELECT count(*) FROM source_unexpected)
    """


def adj_factor_partition_mismatch_predicate(partition_key: str, *, raw: bool) -> str:
    """One partition rule for formal checks and historical candidates."""
    partition_date = f"DATE {duckdb_string(partition_key)}"
    expression = (
        "CAST(try_strptime(trim(CAST(trade_date AS VARCHAR)), '%Y%m%d') AS DATE)"
        if raw else "trade_date"
    )
    return f"{expression} IS NULL OR {expression} != {partition_date}"


def audit_adj_factor_candidate_rules(connection, path: Path, partition_key: str, *, raw: bool,
                                     lifecycle_path: Path, raw_path: Path | None = None) -> dict[str, int]:
    """Pure existing checks semantics; no resources, instance or formal writes."""
    source = read_parquet(path, hive_partitioning=False)
    expected_schema = ADJ_FACTOR_RAW_COLUMN_TYPES if raw else ADJ_FACTOR_SILVER_COLUMN_TYPES
    if {r[0]: r[1] for r in connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()} != expected_schema:
        raise ValueError("adj_factor candidate schema does not match contract")
    summary = connection.execute(f"""
        SELECT count(*),count(*) FILTER(WHERE {adj_factor_partition_mismatch_predicate(partition_key, raw=raw)}),
          count(*) FILTER(WHERE {ADJ_FACTOR_INVALID_VALUE_PREDICATE}),
          (SELECT count(*) FROM ({adj_factor_duplicate_keys_sql(path)}))
        FROM {source}
    """).fetchone()
    result = dict(zip(("rows", "partition_mismatch", "nonpositive_factor", "duplicate_keys"),
                      map(int, summary), strict=True))
    if not raw:
        counts = connection.execute(adj_factor_coverage_counts_sql(
            path, lifecycle_path, partition_key, raw_path=raw_path,
        )).fetchone()
        invalid = connection.execute(
            f"SELECT count(*) FROM ({adj_factor_invalid_lifecycle_sql(path, lifecycle_path)})"
        ).fetchone()[0]
        result.update({
            "lifecycle_invalid": int(invalid),
            "coverage_missing": int(counts[2]),
            "coverage_unexpected": int(counts[3]),
            "source_missing": int(counts[4]),
            "source_unexpected": int(counts[5]),
        })
    return result


def daily_qfq_sample_dicts(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def daily_qfq_column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [str(row[0]) for row in rows]


def daily_qfq_row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def daily_qfq_contract_rule_counts(
    connection,
    path: Path,
    partition_key: str,
) -> dict[str, int]:
    row = connection.execute(
        f"""
        WITH rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM {read_parquet(path, hive_partitioning=False)}
        ),
        duplicate_keys AS (
          SELECT ts_code, trade_date
          FROM rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        )
        SELECT
          count(*) FILTER (WHERE trade_date IS NULL OR trade_date != DATE '{partition_key}')
            AS partition_date_mismatch_count,
          count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL)
            AS null_key_count,
          (SELECT count(*) FROM duplicate_keys) AS duplicate_key_count
        FROM rows
        """
    ).fetchone()
    return {
        "partition_date_mismatch_count": int(row[0]),
        "null_key_count": int(row[1]),
        "duplicate_key_count": int(row[2]),
    }


def daily_qfq_contract_failure_samples(
    connection,
    path: Path,
    partition_key: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        WITH rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM {read_parquet(path, hive_partitioning=False)}
        ),
        duplicate_keys AS (
          SELECT ts_code, trade_date
          FROM rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        )
        SELECT rows.ts_code, rows.trade_date
        FROM rows
        LEFT JOIN duplicate_keys
          ON rows.ts_code = duplicate_keys.ts_code
         AND rows.trade_date = duplicate_keys.trade_date
        WHERE rows.trade_date IS NULL
           OR rows.trade_date != DATE '{partition_key}'
           OR rows.ts_code IS NULL
           OR trim(rows.ts_code) = ''
           OR duplicate_keys.ts_code IS NOT NULL
        ORDER BY rows.ts_code, rows.trade_date
        LIMIT 10
        """
    ).fetchall()
    return daily_qfq_sample_dicts(("ts_code", "trade_date"), rows)


def minute_qfq_counts_sql(
    *,
    gold_source: str,
    partition_key: str | Sequence[str],
    freq: int,
) -> str:
    dates = (partition_key,) if isinstance(partition_key, str) else tuple(partition_key)
    if not dates:
        raise ValueError("Minute check dates cannot be empty")
    partition_filter = "trade_date IN (" + ",".join("DATE " + duckdb_string(d) for d in dates) + ")"
    return f"""
    WITH gold_rows AS (
      SELECT
        CAST(ts_code AS VARCHAR) AS ts_code,
        CAST(freq AS INTEGER) AS freq,
        CAST(trade_date AS DATE) AS trade_date,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(open AS DOUBLE) AS open,
        CAST(high AS DOUBLE) AS high,
        CAST(low AS DOUBLE) AS low,
        CAST(close AS DOUBLE) AS close,
        CAST(vol AS DOUBLE) AS vol,
        CAST(amount AS DOUBLE) AS amount,
        CAST(exchange AS VARCHAR) AS exchange,
        CAST(filename AS VARCHAR) AS filename,
        regexp_extract(CAST(filename AS VARCHAR), 'ts_code=([^/]+)/year=', 1)
          AS path_ts_code,
        regexp_extract(CAST(filename AS VARCHAR), 'year=([0-9]{{4}})/', 1)
          AS path_year
      FROM {gold_source}
    ),
    target_rows AS (
      SELECT *
      FROM gold_rows
      WHERE {partition_filter}
    ),
    duplicate_groups AS (
      SELECT ts_code, trade_time, count(*) AS duplicate_count
      FROM target_rows
      GROUP BY ts_code, trade_time
      HAVING count(*) > 1
    )
    SELECT
      (SELECT count(*) FROM target_rows) AS gold_target_row_count,
      count(*) FILTER (
        WHERE freq != {freq}
           OR ts_code != path_ts_code
           OR strftime(trade_date, '%Y') != path_year
           OR (
             {partition_filter}
             AND CAST(trade_time AS DATE) != trade_date
           )
      ) AS path_mismatch_row_count,
      (SELECT count(*) FROM duplicate_groups) AS duplicate_key_count,
      (SELECT count(*)
       FROM target_rows
       WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
          OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
          OR high < low
          OR open < low OR open > high
          OR close < low OR close > high
      ) AS invalid_price_row_count
    FROM gold_rows
    """


def minute_qfq_identity_coverage_counts_sql(
    *,
    gold_source: str,
    expected_identity_sql: str,
    partition_key: str | Sequence[str],
) -> str:
    dates = (partition_key,) if isinstance(partition_key,str) else tuple(partition_key)
    if not dates:
        raise ValueError("Minute check dates cannot be empty")
    partition_filter = "CAST(trade_date AS DATE) IN (" + ",".join("DATE " + duckdb_string(d) for d in dates) + ")"
    return f"""
    WITH gold_rows AS (
      SELECT
        CAST(ts_code AS VARCHAR) AS ts_code,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(exchange AS VARCHAR) AS exchange
      FROM {gold_source}
      WHERE {partition_filter}
    ),
    expected_rows AS (
      SELECT
        ts_code,
        trade_time,
        exchange
      FROM ({expected_identity_sql})
    ),
    compared_rows AS (
      SELECT
        coalesce(gold_rows.ts_code, expected_rows.ts_code) AS ts_code,
        coalesce(gold_rows.trade_time, expected_rows.trade_time) AS trade_time,
        gold_rows.exchange AS gold_exchange,
        expected_rows.exchange AS expected_exchange,
        gold_rows.ts_code IS NULL AS missing_gold_row,
        expected_rows.ts_code IS NULL AS unexpected_gold_row
      FROM gold_rows
      FULL OUTER JOIN expected_rows
        ON gold_rows.ts_code = expected_rows.ts_code
       AND gold_rows.trade_time = expected_rows.trade_time
    )
    SELECT
      count(*) FILTER (WHERE missing_gold_row) AS missing_gold_row_count,
      count(*) FILTER (WHERE unexpected_gold_row) AS unexpected_gold_row_count,
      count(*) FILTER (
        WHERE NOT missing_gold_row
          AND NOT unexpected_gold_row
          AND gold_exchange IS DISTINCT FROM expected_exchange
      ) AS exchange_mismatch_row_count
    FROM compared_rows
    """



def adj_factor_partition_allowed_status(
    *,
    partition_key: str,
    registered_keys: set[str],
    today: str,
) -> dict[str, Any]:
    is_registered = partition_key in registered_keys
    is_not_before_start = partition_key >= ADJ_FACTOR_MIN_TRADE_DATE
    is_not_future = partition_key <= today
    return {
        "passed": is_registered and is_not_before_start and is_not_future,
        "partition_key": partition_key,
        "partition_set": ADJ_FACTOR_PARTITION_SET,
        "is_registered": is_registered,
        "min_trade_date": ADJ_FACTOR_MIN_TRADE_DATE,
        "is_not_before_start": is_not_before_start,
        "today": today,
        "is_not_future": is_not_future,
    }
