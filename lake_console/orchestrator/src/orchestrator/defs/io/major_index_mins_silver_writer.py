"""DuckDB Silver writer for major-index minute bars."""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io.major_index_mins_quality import (
    MajorIndexMinsRelationValidation,
    prepare_major_index_mins_raw_expected_tables,
    prepare_major_index_mins_silver_expected_tables,
    validate_major_index_mins_raw_relation,
    validate_major_index_mins_silver_relation,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
    silver_major_index_mins_staging_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_COLUMN_TYPES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    effective_raw_request_codes_for_date,
    effective_silver_codes_for_date,
    major_index_mins_derived_windows,
    major_index_mins_historical_fallback_rule,
    normalize_major_index_mins_silver_freq,
    normalize_major_index_mins_trade_date,
    silver_scope_hash_for_date,
    source_freq_for_major_index_mins_derived_freq,
)


class MajorIndexMinsSilverValidationError(ValueError):
    """Raised when a Silver source, staging file, or target is invalid."""


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSilverWriteResult:
    partition_key: str
    silver_freq: str
    source_freq: str
    source_mode: str
    source_path: Path
    target_path: Path
    staging_path: Path
    write_mode: str
    expected_code_count: int
    source_row_count: int
    output_row_count: int
    expected_window_count: int
    generated_window_count: int
    incomplete_window_count: int
    elapsed_ms: float
    scope_hash: str

    def to_details(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "silver_freq": self.silver_freq,
            "source_freq": self.source_freq,
            "source_mode": self.source_mode,
            "source_path": str(self.source_path),
            "target_path": str(self.target_path),
            "write_mode": self.write_mode,
            "expected_code_count": self.expected_code_count,
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "expected_window_count": self.expected_window_count,
            "generated_window_count": self.generated_window_count,
            "incomplete_window_count": self.incomplete_window_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "scope_hash": self.scope_hash,
        }


def _relation_select(relation_sql: str) -> str:
    return (
        relation_sql
        if relation_sql.lstrip().lower().startswith("select")
        else f"SELECT * FROM {relation_sql}"
    )


def _assert_physical_schema(connection, *, relation_sql: str, label: str) -> None:
    select_sql = _relation_select(relation_sql)
    try:
        description = connection.execute(f"DESCRIBE {select_sql}").fetchall()
    except Exception as error:  # noqa: BLE001 - normalize corrupt Parquet failures.
        raise MajorIndexMinsSilverValidationError(
            f"{label} cannot be read as Parquet."
        ) from error
    observed = tuple((str(row[0]), str(row[1]).upper()) for row in description)
    expected = tuple(
        (column, MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column])
        for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
    )
    if observed != expected:
        raise MajorIndexMinsSilverValidationError(
            f"{label} schema does not match the contract: "
            f"expected={expected!r}, observed={observed!r}."
        )


def _normalized_source_sql(relation_sql: str) -> str:
    select_sql = _relation_select(relation_sql)
    return f"""
    WITH normalized AS (
      SELECT
        upper(trim(CAST(ts_code AS VARCHAR)))::VARCHAR AS ts_code,
        trim(CAST(freq AS VARCHAR))::VARCHAR AS freq,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(open AS DOUBLE) AS open,
        CAST(close AS DOUBLE) AS close,
        CAST(high AS DOUBLE) AS high,
        CAST(low AS DOUBLE) AS low,
        CAST(vol AS DOUBLE) AS vol,
        CAST(amount AS DOUBLE) AS amount,
        CAST(vwap AS DOUBLE) AS vwap
      FROM ({select_sql}) source_rows
    )
    SELECT
      normalized.ts_code,
      normalized.freq,
      normalized.trade_time,
      normalized.open,
      normalized.close,
      CASE
        WHEN cleanup.cleanup_kind = 'opening_sentinel'
         AND normalized.high = 0
         AND normalized.low = 0
         AND normalized.open > 0
         AND normalized.close > 0
          THEN greatest(normalized.open, normalized.close)
        WHEN cleanup.cleanup_kind = 'ohlc_envelope'
         AND (normalized.high < greatest(
                normalized.open, normalized.close, normalized.low
              )
              OR normalized.low > least(
                normalized.open, normalized.close, normalized.high
              ))
          THEN greatest(normalized.high, normalized.open, normalized.close)
        ELSE normalized.high
      END::DOUBLE AS high,
      CASE
        WHEN cleanup.cleanup_kind = 'opening_sentinel'
         AND normalized.high = 0
         AND normalized.low = 0
         AND normalized.open > 0
         AND normalized.close > 0
          THEN least(normalized.open, normalized.close)
        WHEN cleanup.cleanup_kind = 'ohlc_envelope'
         AND (normalized.high < greatest(
                normalized.open, normalized.close, normalized.low
              )
              OR normalized.low > least(
                normalized.open, normalized.close, normalized.high
              ))
          THEN least(normalized.low, normalized.open, normalized.close)
        ELSE normalized.low
      END::DOUBLE AS low,
      normalized.vol,
      normalized.amount,
      CASE
        WHEN right(normalized.ts_code, 3) = '.SH' THEN 'XSHG'
        WHEN right(normalized.ts_code, 3) = '.SZ' THEN 'XSHE'
        ELSE NULL
      END::VARCHAR AS exchange,
      normalized.vwap
    FROM normalized
    LEFT JOIN major_index_mins_cleanup_scope cleanup
      ON cleanup.ts_code = normalized.ts_code
     AND cleanup.frequency = normalized.freq
     AND cleanup.trade_date = CAST(normalized.trade_time AS DATE)
     AND cleanup.source_time = CAST(normalized.trade_time AS TIME)
    WHERE normalized.ts_code <> '899050.BJ'
    """


def _normalized_raw_validation_sql(relation_sql: str) -> str:
    select_sql = _relation_select(relation_sql)
    return f"""
    SELECT
      upper(trim(CAST(ts_code AS VARCHAR)))::VARCHAR AS ts_code,
      trim(CAST(freq AS VARCHAR))::VARCHAR AS freq,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(open AS DOUBLE) AS open,
      CAST(close AS DOUBLE) AS close,
      CAST(high AS DOUBLE) AS high,
      CAST(low AS DOUBLE) AS low,
      CAST(vol AS DOUBLE) AS vol,
      CAST(amount AS DOUBLE) AS amount,
      CAST(exchange AS VARCHAR) AS exchange,
      CAST(vwap AS DOUBLE) AS vwap
    FROM ({select_sql}) source_rows
    """


def _ordered_output_sql(relation_sql: str) -> str:
    return f"""
    SELECT ts_code, freq, trade_time, open, close, high, low, vol, amount,
           exchange, vwap
    FROM ({relation_sql}) output_rows
    ORDER BY ts_code, trade_time
    """


def _prepare_derived_window_map(connection, *, silver_freq: str) -> None:
    connection.execute("DROP TABLE IF EXISTS derived_window_map")
    connection.execute(
        "CREATE TEMP TABLE derived_window_map("
        "exchange VARCHAR NOT NULL, source_time TIME NOT NULL, "
        "window_id INTEGER NOT NULL, target_time TIME NOT NULL, "
        "expected_source_count INTEGER NOT NULL, "
        "PRIMARY KEY(exchange, source_time))"
    )
    rows: list[tuple[object, ...]] = []
    for exchange in ("XSHG", "XSHE", "BSE"):
        rows.extend(
            (
                exchange,
                window.source_time,
                window.window_id,
                window.target_time,
                window.expected_source_count,
            )
            for window in major_index_mins_derived_windows(
                silver_freq=silver_freq,
                exchange=exchange,
            )
        )
    connection.executemany(
        "INSERT INTO derived_window_map VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def _derived_aggregate_sql(*, source_sql: str, silver_freq: str) -> str:
    return f"""
    WITH windowed AS (
      SELECT source_rows.*, window_map.window_id, window_map.target_time,
             window_map.expected_source_count
      FROM ({source_sql}) source_rows
      INNER JOIN derived_window_map window_map
        ON source_rows.exchange = window_map.exchange
       AND CAST(source_rows.trade_time AS TIME) = window_map.source_time
    ), aggregated AS (
      SELECT
        ts_code,
        '{silver_freq}'::VARCHAR AS freq,
        CAST(CAST(trade_time AS DATE) AS VARCHAR) || ' ' ||
          CAST(max(target_time) AS VARCHAR) AS target_timestamp,
        arg_min(open, trade_time)::DOUBLE AS open,
        arg_max(close, trade_time)::DOUBLE AS close,
        max(high)::DOUBLE AS high,
        min(low)::DOUBLE AS low,
        sum(vol)::DOUBLE AS vol,
        sum(amount)::DOUBLE AS amount,
        max(exchange)::VARCHAR AS exchange,
        count(*)::INTEGER AS source_row_count,
        max(expected_source_count)::INTEGER AS expected_source_count
      FROM windowed
      GROUP BY ts_code, CAST(trade_time AS DATE), window_id
    )
    SELECT
      ts_code,
      freq,
      CAST(target_timestamp AS TIMESTAMP) AS trade_time,
      open,
      close,
      high,
      low,
      vol,
      amount,
      exchange,
      CAST(NULL AS DOUBLE) AS vwap
    FROM aggregated
    WHERE source_row_count = expected_source_count
    """


def _derived_diagnostics(
    connection,
    *,
    output_sql: str,
) -> tuple[int, int, int]:
    expected_window_count = int(
        connection.execute(
            """
            SELECT count(*) FROM (
              SELECT expected.ts_code, window_map.window_id
              FROM expected_codes expected
              INNER JOIN derived_window_map window_map
                ON expected.expected_exchange = window_map.exchange
              GROUP BY expected.ts_code, window_map.window_id
            ) expected_windows
            """
        ).fetchone()[0]
        or 0
    )
    generated_window_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({output_sql}) generated_rows"
        ).fetchone()[0]
        or 0
    )
    return (
        expected_window_count,
        generated_window_count,
        expected_window_count - generated_window_count,
    )


def _require_clean(
    validation: MajorIndexMinsRelationValidation,
    *,
    label: str,
) -> None:
    if validation.errors:
        readable_errors = tuple(
            "session grid" if error == "session_grid" else error
            for error in validation.errors
        )
        raise MajorIndexMinsSilverValidationError(
            f"{label} validation failed: errors={readable_errors!r}."
        )


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000


def _write_major_index_mins_silver_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    freq: int | str,
    partition_key: str,
    run_id: str,
    historical_fallback_path: Path | None,
    historical_fallback_codes: Sequence[str],
) -> MajorIndexMinsSilverWriteResult:
    """Write one native or derived Silver partition through staging."""

    started_at = perf_counter()
    silver_freq = normalize_major_index_mins_silver_freq(freq)
    normalized_partition = normalize_major_index_mins_trade_date(partition_key)
    raw_expected_codes = effective_raw_request_codes_for_date(normalized_partition)
    expected_codes = effective_silver_codes_for_date(normalized_partition)
    scope_hash = silver_scope_hash_for_date(normalized_partition)
    if not expected_codes:
        raise MajorIndexMinsSilverValidationError(
            f"source scope is empty for {normalized_partition}."
        )
    derived = silver_freq not in MAJOR_INDEX_MINS_SOURCE_FREQS
    source_freq = (
        source_freq_for_major_index_mins_derived_freq(silver_freq)
        if derived
        else silver_freq
    )
    source_mode = "derived" if derived else "native"
    normalized_fallback_codes = tuple(
        sorted({str(code).strip().upper() for code in historical_fallback_codes})
    )
    if historical_fallback_path is not None:
        published_rule = major_index_mins_historical_fallback_rule(
            trade_date=normalized_partition,
            target_freq=silver_freq,
        )
        if derived or published_rule is None:
            raise MajorIndexMinsSilverValidationError(
                "historical fallback is only allowed for a published native scope."
            )
        if normalized_fallback_codes != tuple(sorted(published_rule.target_codes)):
            raise MajorIndexMinsSilverValidationError(
                "historical fallback codes do not match the published scope."
            )
        if not historical_fallback_path.is_file():
            raise MajorIndexMinsSilverValidationError(
                f"historical fallback file is missing: {historical_fallback_path}"
            )
        source_mode = "native_with_historical_fallback"
    elif normalized_fallback_codes:
        raise MajorIndexMinsSilverValidationError(
            "historical fallback codes require an explicit fallback file."
        )
    source_path = (
        silver_major_index_mins_path(
            lake_root_path,
            source_freq,
            normalized_partition,
        )
        if derived
        else raw_major_index_mins_path(
            lake_root_path,
            source_freq,
            normalized_partition,
        )
    )
    if not source_path.exists():
        raise MajorIndexMinsSilverValidationError(
            "major-index minute Silver source is missing: "
            f"freq={source_freq}, partition={normalized_partition}, "
            f"path={source_path}."
        )
    target_path = silver_major_index_mins_path(
        lake_root_path,
        silver_freq,
        normalized_partition,
    )
    staging_path = silver_major_index_mins_staging_path(
        lake_root_path,
        run_id,
        silver_freq,
        normalized_partition,
    )

    try:
        with duckdb_resource.connect() as connection:
            source_relation = read_parquet(source_path, hive_partitioning=False)
            _assert_physical_schema(
                connection,
                relation_sql=source_relation,
                label="major-index minute Silver source",
            )
            if derived:
                prepare_major_index_mins_silver_expected_tables(
                    connection,
                    expected_codes=expected_codes,
                    frequency=source_freq,
                )
                source_validation = validate_major_index_mins_silver_relation(
                    connection,
                    relation_sql=source_relation,
                    expected_codes=expected_codes,
                    frequency=source_freq,
                    partition_key=normalized_partition,
                )
            else:
                prepare_major_index_mins_raw_expected_tables(
                    connection,
                    expected_codes=raw_expected_codes,
                    frequency=source_freq,
                    partition_key=normalized_partition,
                )
                source_validation = validate_major_index_mins_raw_relation(
                    connection,
                    relation_sql=_normalized_raw_validation_sql(source_relation),
                    expected_codes=raw_expected_codes,
                    frequency=source_freq,
                    partition_key=normalized_partition,
                )
            _require_clean(source_validation, label="Silver source")
            source_sql = _normalized_source_sql(source_relation)
            if historical_fallback_path is not None:
                fallback_relation = read_parquet(
                    historical_fallback_path,
                    hive_partitioning=False,
                )
                _assert_physical_schema(
                    connection,
                    relation_sql=fallback_relation,
                    label="major-index minute historical fallback",
                )
                prepare_major_index_mins_silver_expected_tables(
                    connection,
                    expected_codes=normalized_fallback_codes,
                    frequency=silver_freq,
                )
                fallback_validation = validate_major_index_mins_silver_relation(
                    connection,
                    relation_sql=fallback_relation,
                    expected_codes=normalized_fallback_codes,
                    frequency=silver_freq,
                    partition_key=normalized_partition,
                    require_null_vwap=True,
                )
                _require_clean(
                    fallback_validation,
                    label="historical fallback",
                )
                fallback_code_sql = ", ".join(
                    duckdb_string(code) for code in normalized_fallback_codes
                )
                source_sql = f"""
                SELECT * FROM ({source_sql}) native_rows
                WHERE ts_code NOT IN ({fallback_code_sql})
                UNION ALL
                SELECT * FROM {fallback_relation}
                """

            expected_window_count = 0
            generated_window_count = 0
            incomplete_window_count = 0
            output_sql = _ordered_output_sql(source_sql)
            if derived:
                _prepare_derived_window_map(connection, silver_freq=silver_freq)
                derived_sql = _derived_aggregate_sql(
                    source_sql=source_sql,
                    silver_freq=silver_freq,
                )
                (
                    expected_window_count,
                    generated_window_count,
                    incomplete_window_count,
                ) = _derived_diagnostics(connection, output_sql=derived_sql)
                if incomplete_window_count:
                    raise MajorIndexMinsSilverValidationError(
                        "derived Silver window is incomplete: "
                        f"freq={silver_freq}, partition={normalized_partition}, "
                        f"expected={expected_window_count}, "
                        f"generated={generated_window_count}."
                    )
                output_sql = _ordered_output_sql(derived_sql)

            prepare_major_index_mins_silver_expected_tables(
                connection,
                expected_codes=expected_codes,
                frequency=silver_freq,
            )
            output_validation = validate_major_index_mins_silver_relation(
                connection,
                relation_sql=output_sql,
                expected_codes=expected_codes,
                frequency=silver_freq,
                partition_key=normalized_partition,
                require_null_vwap=derived,
            )
            _require_clean(output_validation, label="Silver output")

            if target_path.exists():
                target_relation = read_parquet(target_path, hive_partitioning=False)
                _assert_physical_schema(
                    connection,
                    relation_sql=target_relation,
                    label="existing major-index minute Silver target",
                )
                target_validation = validate_major_index_mins_silver_relation(
                    connection,
                    relation_sql=target_relation,
                    expected_codes=expected_codes,
                    frequency=silver_freq,
                    partition_key=normalized_partition,
                    require_null_vwap=derived,
                )
                _require_clean(target_validation, label="existing Silver target")
                return MajorIndexMinsSilverWriteResult(
                    partition_key=normalized_partition,
                    silver_freq=silver_freq,
                    source_freq=source_freq,
                    source_mode=source_mode,
                    source_path=source_path,
                    target_path=target_path,
                    staging_path=staging_path,
                    write_mode="reuse_existing",
                    expected_code_count=len(expected_codes),
                    source_row_count=source_validation.row_count,
                    output_row_count=target_validation.row_count,
                    expected_window_count=expected_window_count,
                    generated_window_count=generated_window_count,
                    incomplete_window_count=incomplete_window_count,
                    elapsed_ms=_elapsed_ms(started_at),
                    scope_hash=scope_hash,
                )

            target_path.parent.mkdir(parents=True, exist_ok=True)
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            connection.execute(copy_query_to_parquet(output_sql, staging_path))
            staging_relation = read_parquet(staging_path, hive_partitioning=False)
            _assert_physical_schema(
                connection,
                relation_sql=staging_relation,
                label="major-index minute Silver staging",
            )
            staging_validation = validate_major_index_mins_silver_relation(
                connection,
                relation_sql=staging_relation,
                expected_codes=expected_codes,
                frequency=silver_freq,
                partition_key=normalized_partition,
                require_null_vwap=derived,
            )
            _require_clean(staging_validation, label="Silver staging")
            if staging_validation.row_count != output_validation.row_count:
                raise MajorIndexMinsSilverValidationError(
                    "Silver staging row reconciliation failed: "
                    f"output={output_validation.row_count}, "
                    f"staging={staging_validation.row_count}."
                )
        if target_path.exists():
            raise MajorIndexMinsSilverValidationError(
                f"Silver target appeared during staging; refusing overwrite: {target_path}"
            )
        os.replace(staging_path, target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return MajorIndexMinsSilverWriteResult(
        partition_key=normalized_partition,
        silver_freq=silver_freq,
        source_freq=source_freq,
        source_mode=source_mode,
        source_path=source_path,
        target_path=target_path,
        staging_path=staging_path,
        write_mode="staged_atomic_replace",
        expected_code_count=len(expected_codes),
        source_row_count=source_validation.row_count,
        output_row_count=staging_validation.row_count,
        expected_window_count=expected_window_count,
        generated_window_count=generated_window_count,
        incomplete_window_count=incomplete_window_count,
        elapsed_ms=_elapsed_ms(started_at),
        scope_hash=scope_hash,
    )


def write_major_index_mins_silver_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    freq: int | str,
    partition_key: str,
    run_id: str,
) -> MajorIndexMinsSilverWriteResult:
    """Write one ordinary native or derived Silver partition through staging."""

    return _write_major_index_mins_silver_partition(
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb_resource,
        freq=freq,
        partition_key=partition_key,
        run_id=run_id,
        historical_fallback_path=None,
        historical_fallback_codes=(),
    )


def write_major_index_mins_silver_partition_with_historical_fallback(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    freq: int | str,
    partition_key: str,
    run_id: str,
    historical_fallback_path: Path,
    historical_fallback_codes: Sequence[str],
) -> MajorIndexMinsSilverWriteResult:
    """Write one published Bootstrap-only native fallback partition."""

    return _write_major_index_mins_silver_partition(
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb_resource,
        freq=freq,
        partition_key=partition_key,
        run_id=run_id,
        historical_fallback_path=historical_fallback_path,
        historical_fallback_codes=historical_fallback_codes,
    )
