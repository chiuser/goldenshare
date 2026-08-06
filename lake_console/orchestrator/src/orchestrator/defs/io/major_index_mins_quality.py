"""Shared DuckDB quality predicates for major-index minute relations."""

from collections.abc import Sequence
from dataclasses import dataclass

from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_COLUMN_TYPES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    major_index_mins_exchange_for_code,
    major_index_mins_session_times,
    normalize_major_index_mins_silver_freq,
)


@dataclass(frozen=True, slots=True)
class MajorIndexMinsRelationValidation:
    columns: tuple[str, ...]
    column_types: tuple[str, ...]
    row_count: int
    expected_row_count: int
    returned_code_count: int
    missing_code_count: int
    extra_code_count: int
    missing_session_row_count: int
    extra_session_row_count: int
    duplicate_key_count: int
    invalid_row_count: int

    @property
    def errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        expected_types = tuple(
            MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column]
            for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
        )
        if self.columns != MAJOR_INDEX_MINS_SOURCE_COLUMNS:
            errors.append("schema_columns")
        if self.column_types != expected_types:
            errors.append("schema_types")
        if self.row_count <= 0 or self.row_count != self.expected_row_count:
            errors.append("row_count")
        if self.missing_code_count:
            errors.append("missing_codes")
        if self.extra_code_count:
            errors.append("extra_codes")
        if self.missing_session_row_count or self.extra_session_row_count:
            errors.append("session_grid")
        if self.duplicate_key_count:
            errors.append("duplicate_key")
        if self.invalid_row_count:
            errors.append("invalid_rows")
        return tuple(errors)


def prepare_major_index_mins_expected_tables(
    connection,
    *,
    expected_codes: Sequence[str],
    frequency: str,
) -> None:
    normalized_frequency = normalize_major_index_mins_silver_freq(frequency)
    connection.execute("DROP TABLE IF EXISTS expected_session_rows")
    connection.execute("DROP TABLE IF EXISTS expected_codes")
    connection.execute(
        "CREATE TEMP TABLE expected_codes("
        "ts_code VARCHAR PRIMARY KEY, expected_exchange VARCHAR NOT NULL)"
    )
    code_rows = [
        (code, major_index_mins_exchange_for_code(code)) for code in expected_codes
    ]
    connection.executemany("INSERT INTO expected_codes VALUES (?, ?)", code_rows)
    connection.execute(
        "CREATE TEMP TABLE expected_session_rows("
        "ts_code VARCHAR NOT NULL, expected_exchange VARCHAR NOT NULL, "
        "source_time TIME NOT NULL, PRIMARY KEY(ts_code, source_time))"
    )
    session_rows = [
        (code, exchange, source_time)
        for code, exchange in code_rows
        for source_time in major_index_mins_session_times(
            exchange=exchange,
            source_freq=normalized_frequency,
        )
    ]
    connection.executemany(
        "INSERT INTO expected_session_rows VALUES (?, ?, ?)",
        session_rows,
    )


def _relation_select(relation_sql: str) -> str:
    stripped = relation_sql.lstrip()
    return (
        relation_sql
        if stripped.lower().startswith("select")
        else f"SELECT * FROM {relation_sql}"
    )


def validate_major_index_mins_relation(
    connection,
    *,
    relation_sql: str,
    expected_codes: Sequence[str],
    frequency: str,
    partition_key: str,
    require_null_vwap: bool = False,
) -> MajorIndexMinsRelationValidation:
    normalized_frequency = normalize_major_index_mins_silver_freq(frequency)
    select_sql = _relation_select(relation_sql)
    description = connection.execute(f"DESCRIBE {select_sql}").fetchall()
    columns = tuple(str(row[0]) for row in description)
    column_types = tuple(str(row[1]).upper() for row in description)
    expected_types = tuple(
        MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column]
        for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
    )
    expected_row_count = int(
        connection.execute("SELECT count(*) FROM expected_session_rows").fetchone()[0]
        or 0
    )
    if columns != MAJOR_INDEX_MINS_SOURCE_COLUMNS or column_types != expected_types:
        row_count = int(
            connection.execute(f"SELECT count(*) FROM ({select_sql}) relation_rows").fetchone()[0]
            or 0
        )
        returned_code_count = (
            int(
                connection.execute(
                    f"SELECT count(DISTINCT CAST(ts_code AS VARCHAR)) "
                    f"FROM ({select_sql}) relation_rows"
                ).fetchone()[0]
                or 0
            )
            if "ts_code" in columns
            else 0
        )
        return MajorIndexMinsRelationValidation(
            columns=columns,
            column_types=column_types,
            row_count=row_count,
            expected_row_count=expected_row_count,
            returned_code_count=returned_code_count,
            missing_code_count=len(expected_codes),
            extra_code_count=0,
            missing_session_row_count=expected_row_count,
            extra_session_row_count=0,
            duplicate_key_count=0,
            invalid_row_count=row_count,
        )
    (
        row_count,
        returned_code_count,
        duplicate_key_count,
        invalid_row_count,
    ) = connection.execute(
        f"""
        SELECT
          count(*),
          count(DISTINCT ts_code),
          count(*) - count(DISTINCT (ts_code, freq, trade_time)),
          count(*) FILTER (
            WHERE ts_code IS NULL
               OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR freq IS NULL
               OR CAST(freq AS VARCHAR) <> ?
               OR trade_time IS NULL
               OR CAST(trade_time AS DATE) <> CAST(? AS DATE)
               OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
               OR NOT isfinite(CAST(open AS DOUBLE))
               OR NOT isfinite(CAST(close AS DOUBLE))
               OR NOT isfinite(CAST(high AS DOUBLE))
               OR NOT isfinite(CAST(low AS DOUBLE))
               OR open < 0 OR close < 0 OR high < 0 OR low < 0
               OR high < greatest(open, close, low)
               OR low > least(open, close, high)
               OR vol IS NULL OR amount IS NULL
               OR NOT isfinite(CAST(vol AS DOUBLE))
               OR NOT isfinite(CAST(amount AS DOUBLE))
               OR vol < 0 OR amount < 0
               OR exchange IS NULL
               OR NOT EXISTS (
                    SELECT 1 FROM expected_codes expected
                    WHERE expected.ts_code = relation_rows.ts_code
                      AND expected.expected_exchange = relation_rows.exchange
               )
               OR (vwap IS NOT NULL AND (
                    NOT isfinite(CAST(vwap AS DOUBLE)) OR vwap < 0
               ))
               OR (? AND vwap IS NOT NULL)
          )
        FROM ({select_sql}) relation_rows
        """,
        [normalized_frequency, partition_key, require_null_vwap],
    ).fetchone()
    missing_code_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT ts_code FROM expected_codes
              EXCEPT
              SELECT DISTINCT CAST(ts_code AS VARCHAR) FROM ({select_sql}) relation_rows
            ) missing_codes
            """
        ).fetchone()[0]
        or 0
    )
    extra_code_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
              FROM ({select_sql}) relation_rows
              EXCEPT
              SELECT ts_code FROM expected_codes
            ) extra_codes
            """
        ).fetchone()[0]
        or 0
    )
    missing_session_row_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT ts_code, source_time FROM expected_session_rows
              EXCEPT
              SELECT CAST(ts_code AS VARCHAR), CAST(trade_time AS TIME)
              FROM ({select_sql}) relation_rows
            ) missing_session
            """
        ).fetchone()[0]
        or 0
    )
    extra_session_row_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT CAST(ts_code AS VARCHAR) AS ts_code, CAST(trade_time AS TIME) AS source_time
              FROM ({select_sql}) relation_rows
              EXCEPT
              SELECT ts_code, source_time FROM expected_session_rows
            ) extra_session
            """
        ).fetchone()[0]
        or 0
    )
    return MajorIndexMinsRelationValidation(
        columns=columns,
        column_types=column_types,
        row_count=int(row_count or 0),
        expected_row_count=expected_row_count,
        returned_code_count=int(returned_code_count or 0),
        missing_code_count=missing_code_count,
        extra_code_count=extra_code_count,
        missing_session_row_count=missing_session_row_count,
        extra_session_row_count=extra_session_row_count,
        duplicate_key_count=int(duplicate_key_count or 0),
        invalid_row_count=int(invalid_row_count or 0),
    )
