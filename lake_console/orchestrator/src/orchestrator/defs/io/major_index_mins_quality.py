"""Layer-specific DuckDB quality predicates for major-index minute relations."""

from collections.abc import Sequence
from dataclasses import dataclass

from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_COLUMN_TYPES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    major_index_mins_exchange_for_code,
    major_index_mins_historical_fallback_rule,
    major_index_mins_session_times,
    major_index_mins_silver_ohlc_cleanup_scope_rows,
    major_index_mins_silver_opening_price_replacement_rows,
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
    exact_row_count_required: bool = True
    positive_row_count_required: bool = True

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
        if (self.positive_row_count_required and self.row_count <= 0) or (
            self.exact_row_count_required
            and self.row_count != self.expected_row_count
        ):
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


def _prepare_cleanup_scope(connection) -> None:
    connection.execute("DROP TABLE IF EXISTS major_index_mins_cleanup_scope")
    connection.execute(
        "CREATE TEMP TABLE major_index_mins_cleanup_scope("
        "ts_code VARCHAR NOT NULL, frequency VARCHAR NOT NULL, "
        "trade_date DATE NOT NULL, source_time TIME NOT NULL, "
        "cleanup_kind VARCHAR NOT NULL, "
        "PRIMARY KEY(ts_code, frequency, trade_date, source_time))"
    )
    connection.executemany(
        "INSERT INTO major_index_mins_cleanup_scope VALUES (?, ?, ?, ?, ?)",
        major_index_mins_silver_ohlc_cleanup_scope_rows(),
    )
    connection.execute("DROP TABLE IF EXISTS major_index_mins_price_replacements")
    connection.execute(
        "CREATE TEMP TABLE major_index_mins_price_replacements("
        "ts_code VARCHAR NOT NULL, frequency VARCHAR NOT NULL, "
        "trade_date DATE NOT NULL, source_time TIME NOT NULL, "
        "replacement_price DOUBLE NOT NULL, "
        "PRIMARY KEY(ts_code, frequency, trade_date, source_time))"
    )
    connection.executemany(
        "INSERT INTO major_index_mins_price_replacements VALUES (?, ?, ?, ?, ?)",
        major_index_mins_silver_opening_price_replacement_rows(),
    )


def _prepare_expected_tables(
    connection,
    *,
    allowed_codes: Sequence[str],
    strict_codes: Sequence[str],
    frequency: str,
) -> None:
    normalized_frequency = normalize_major_index_mins_silver_freq(frequency)
    connection.execute("DROP TABLE IF EXISTS expected_session_rows")
    connection.execute("DROP TABLE IF EXISTS expected_codes")
    connection.execute("DROP TABLE IF EXISTS allowed_codes")
    connection.execute(
        "CREATE TEMP TABLE allowed_codes(ts_code VARCHAR PRIMARY KEY)"
    )
    connection.executemany(
        "INSERT INTO allowed_codes VALUES (?)",
        [(code,) for code in allowed_codes],
    )
    connection.execute(
        "CREATE TEMP TABLE expected_codes("
        "ts_code VARCHAR PRIMARY KEY, expected_exchange VARCHAR NOT NULL)"
    )
    code_rows = [
        (code, major_index_mins_exchange_for_code(code)) for code in strict_codes
    ]
    if code_rows:
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
    if session_rows:
        connection.executemany(
            "INSERT INTO expected_session_rows VALUES (?, ?, ?)",
            session_rows,
        )
    _prepare_cleanup_scope(connection)


def prepare_major_index_mins_raw_expected_tables(
    connection,
    *,
    expected_codes: Sequence[str],
    frequency: str,
    partition_key: str,
) -> None:
    normalized_frequency = normalize_major_index_mins_silver_freq(frequency)
    relaxed_codes = {code for code in expected_codes if code.endswith(".BJ")}
    fallback = major_index_mins_historical_fallback_rule(
        trade_date=partition_key,
        target_freq=normalized_frequency,
    )
    if fallback is not None:
        relaxed_codes.update(fallback.target_codes)
    _prepare_expected_tables(
        connection,
        allowed_codes=expected_codes,
        strict_codes=tuple(code for code in expected_codes if code not in relaxed_codes),
        frequency=normalized_frequency,
    )


def prepare_major_index_mins_silver_expected_tables(
    connection,
    *,
    expected_codes: Sequence[str],
    frequency: str,
) -> None:
    _prepare_expected_tables(
        connection,
        allowed_codes=expected_codes,
        strict_codes=expected_codes,
        frequency=frequency,
    )


def _relation_select(relation_sql: str) -> str:
    stripped = relation_sql.lstrip().lower()
    return (
        relation_sql
        if stripped.startswith(("select", "with"))
        else f"SELECT * FROM {relation_sql}"
    )


def _schema_and_counts(connection, *, select_sql: str) -> tuple[
    tuple[str, ...], tuple[str, ...], int, int, int
]:
    description = connection.execute(f"DESCRIBE {select_sql}").fetchall()
    columns = tuple(str(row[0]) for row in description)
    column_types = tuple(str(row[1]).upper() for row in description)
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({select_sql}) relation_rows"
        ).fetchone()[0]
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
    expected_row_count = int(
        connection.execute("SELECT count(*) FROM expected_session_rows").fetchone()[0]
        or 0
    )
    return (
        columns,
        column_types,
        row_count,
        returned_code_count,
        expected_row_count,
    )


def _schema_failure(
    *,
    columns: tuple[str, ...],
    column_types: tuple[str, ...],
    row_count: int,
    returned_code_count: int,
    expected_row_count: int,
    expected_codes: Sequence[str],
    exact_row_count_required: bool,
    positive_row_count_required: bool,
) -> MajorIndexMinsRelationValidation:
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
        exact_row_count_required=exact_row_count_required,
        positive_row_count_required=positive_row_count_required,
    )


def _coverage_counts(connection, *, select_sql: str) -> tuple[int, int, int, int]:
    missing_code_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT ts_code FROM expected_codes
              EXCEPT
              SELECT DISTINCT CAST(ts_code AS VARCHAR)
              FROM ({select_sql}) relation_rows
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
              SELECT ts_code FROM allowed_codes
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
              SELECT CAST(rows.ts_code AS VARCHAR), CAST(rows.trade_time AS TIME)
              FROM ({select_sql}) rows
              INNER JOIN expected_codes expected
                ON expected.ts_code = CAST(rows.ts_code AS VARCHAR)
            ) missing_session
            """
        ).fetchone()[0]
        or 0
    )
    extra_session_row_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT CAST(rows.ts_code AS VARCHAR) AS ts_code,
                     CAST(rows.trade_time AS TIME) AS source_time
              FROM ({select_sql}) rows
              INNER JOIN expected_codes expected
                ON expected.ts_code = CAST(rows.ts_code AS VARCHAR)
              EXCEPT
              SELECT ts_code, source_time FROM expected_session_rows
            ) extra_session
            """
        ).fetchone()[0]
        or 0
    )
    return (
        missing_code_count,
        extra_code_count,
        missing_session_row_count,
        extra_session_row_count,
    )


def validate_major_index_mins_raw_relation(
    connection,
    *,
    relation_sql: str,
    expected_codes: Sequence[str],
    frequency: str,
    partition_key: str,
) -> MajorIndexMinsRelationValidation:
    normalized_frequency = normalize_major_index_mins_silver_freq(frequency)
    fallback_rule = major_index_mins_historical_fallback_rule(
        trade_date=partition_key,
        target_freq=normalized_frequency,
    )
    relaxed_empty_codes = {
        code for code in expected_codes if code.endswith(".BJ")
    }
    if fallback_rule is not None:
        relaxed_empty_codes.update(fallback_rule.target_codes)
    allow_published_empty = bool(expected_codes) and set(expected_codes).issubset(
        relaxed_empty_codes
    )
    select_sql = _relation_select(relation_sql)
    (
        columns,
        column_types,
        row_count,
        returned_code_count,
        expected_row_count,
    ) = _schema_and_counts(connection, select_sql=select_sql)
    expected_types = tuple(
        MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column]
        for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
    )
    if columns != MAJOR_INDEX_MINS_SOURCE_COLUMNS or column_types != expected_types:
        return _schema_failure(
            columns=columns,
            column_types=column_types,
            row_count=row_count,
            returned_code_count=returned_code_count,
            expected_row_count=expected_row_count,
            expected_codes=expected_codes,
            exact_row_count_required=False,
            positive_row_count_required=not allow_published_empty,
        )
    duplicate_key_count, invalid_row_count = connection.execute(
        f"""
        SELECT
          count(*) - count(DISTINCT (ts_code, freq, trade_time)),
          count(*) FILTER (
            WHERE ts_code IS NULL
               OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR freq IS NULL
               OR CAST(freq AS VARCHAR) <> ?
               OR trade_time IS NULL
               OR CAST(trade_time AS DATE) <> CAST(? AS DATE)
               OR NOT EXISTS (
                    SELECT 1 FROM allowed_codes allowed
                    WHERE allowed.ts_code = CAST(relation_rows.ts_code AS VARCHAR)
               )
               OR (
                    EXISTS (
                      SELECT 1 FROM expected_codes expected
                      WHERE expected.ts_code = CAST(relation_rows.ts_code AS VARCHAR)
                    )
                    AND (
                      open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
                      OR NOT isfinite(CAST(open AS DOUBLE))
                      OR NOT isfinite(CAST(close AS DOUBLE))
                      OR NOT isfinite(CAST(high AS DOUBLE))
                      OR NOT isfinite(CAST(low AS DOUBLE))
                      OR open < 0 OR close < 0 OR high < 0 OR low < 0
                      OR vol IS NULL OR amount IS NULL
                      OR NOT isfinite(CAST(vol AS DOUBLE))
                      OR NOT isfinite(CAST(amount AS DOUBLE))
                      OR vol < 0 OR amount < 0
                      OR (vwap IS NOT NULL AND (
                           NOT isfinite(CAST(vwap AS DOUBLE)) OR vwap < 0
                      ))
                      OR (
                        (high < greatest(open, close, low)
                         OR low > least(open, close, high))
                        AND NOT EXISTS (
                          SELECT 1 FROM major_index_mins_cleanup_scope cleanup
                          WHERE cleanup.ts_code = CAST(relation_rows.ts_code AS VARCHAR)
                            AND cleanup.frequency = CAST(relation_rows.freq AS VARCHAR)
                            AND cleanup.trade_date = CAST(relation_rows.trade_time AS DATE)
                            AND cleanup.source_time = CAST(relation_rows.trade_time AS TIME)
                            AND (
                              (cleanup.cleanup_kind = 'opening_sentinel'
                               AND relation_rows.high = 0
                               AND relation_rows.low = 0
                               AND relation_rows.open > 0
                               AND relation_rows.close > 0)
                              OR cleanup.cleanup_kind = 'ohlc_envelope'
                            )
                        )
                      )
                    )
               )
          )
        FROM ({select_sql}) relation_rows
        """,
        [normalized_frequency, partition_key],
    ).fetchone()
    (
        missing_code_count,
        extra_code_count,
        missing_session_row_count,
        extra_session_row_count,
    ) = _coverage_counts(connection, select_sql=select_sql)
    return MajorIndexMinsRelationValidation(
        columns=columns,
        column_types=column_types,
        row_count=row_count,
        expected_row_count=expected_row_count,
        returned_code_count=returned_code_count,
        missing_code_count=missing_code_count,
        extra_code_count=extra_code_count,
        missing_session_row_count=missing_session_row_count,
        extra_session_row_count=extra_session_row_count,
        duplicate_key_count=int(duplicate_key_count or 0),
        invalid_row_count=int(invalid_row_count or 0),
        exact_row_count_required=False,
        positive_row_count_required=not allow_published_empty,
    )


def validate_major_index_mins_silver_relation(
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
    (
        columns,
        column_types,
        row_count,
        returned_code_count,
        expected_row_count,
    ) = _schema_and_counts(connection, select_sql=select_sql)
    expected_types = tuple(
        MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column]
        for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
    )
    if columns != MAJOR_INDEX_MINS_SOURCE_COLUMNS or column_types != expected_types:
        return _schema_failure(
            columns=columns,
            column_types=column_types,
            row_count=row_count,
            returned_code_count=returned_code_count,
            expected_row_count=expected_row_count,
            expected_codes=expected_codes,
            exact_row_count_required=True,
            positive_row_count_required=True,
        )
    duplicate_key_count, invalid_row_count = connection.execute(
        f"""
        SELECT
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
               OR open <= 0 OR close <= 0 OR high <= 0 OR low <= 0
               OR high < greatest(open, close, low)
               OR low > least(open, close, high)
               OR vol IS NULL OR amount IS NULL
               OR NOT isfinite(CAST(vol AS DOUBLE))
               OR NOT isfinite(CAST(amount AS DOUBLE))
               OR vol < 0 OR amount < 0
               OR exchange IS NULL
               OR NOT EXISTS (
                    SELECT 1 FROM expected_codes expected
                    WHERE expected.ts_code = CAST(relation_rows.ts_code AS VARCHAR)
                      AND expected.expected_exchange = CAST(relation_rows.exchange AS VARCHAR)
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
    (
        missing_code_count,
        extra_code_count,
        missing_session_row_count,
        extra_session_row_count,
    ) = _coverage_counts(connection, select_sql=select_sql)
    return MajorIndexMinsRelationValidation(
        columns=columns,
        column_types=column_types,
        row_count=row_count,
        expected_row_count=expected_row_count,
        returned_code_count=returned_code_count,
        missing_code_count=missing_code_count,
        extra_code_count=extra_code_count,
        missing_session_row_count=missing_session_row_count,
        extra_session_row_count=extra_session_row_count,
        duplicate_key_count=int(duplicate_key_count or 0),
        invalid_row_count=int(invalid_row_count or 0),
        exact_row_count_required=True,
    )
