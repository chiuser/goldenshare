"""Pure-cast Silver writer and reconciliation for ``idx_factor_pro``."""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.idx_factor_pro_raw_writer import (
    validate_idx_factor_pro_raw_relation,
)
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
    silver_index_factor_pro_staging_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_SILVER_COLUMN_TYPES,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
    normalize_idx_factor_pro_trade_date,
)


class IdxFactorProSilverValidationError(ValueError):
    """Raised when Raw, Silver staging, or an existing target is invalid."""


@dataclass(frozen=True, slots=True)
class IdxFactorProSilverAudit:
    columns: tuple[str, ...]
    column_types: tuple[str, ...]
    row_count: int
    distinct_code_count: int
    missing_codes: tuple[str, ...]
    extra_codes: tuple[str, ...]
    duplicate_key_count: int
    invalid_key_count: int
    invalid_date_count: int
    min_trade_date: str | None
    max_trade_date: str | None

    @property
    def expected_column_types(self) -> tuple[str, ...]:
        return tuple(
            IDX_FACTOR_PRO_SILVER_COLUMN_TYPES[column]
            for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
        )

    @property
    def schema_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.columns != IDX_FACTOR_PRO_SOURCE_COLUMNS:
            errors.append("schema_columns")
        if self.column_types != self.expected_column_types:
            errors.append("schema_types")
        return tuple(errors)

    @property
    def scope_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.invalid_date_count:
            errors.append("partition_date")
        if self.missing_codes:
            errors.append("missing_codes")
        if self.extra_codes:
            errors.append("extra_codes")
        return tuple(errors)

    @property
    def key_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.invalid_key_count:
            errors.append("invalid_keys")
        if self.duplicate_key_count:
            errors.append("duplicate_key")
        return tuple(errors)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(self.schema_errors + self.scope_errors + self.key_errors)
        )


@dataclass(frozen=True, slots=True)
class IdxFactorProRawSilverParityAudit:
    raw_row_count: int
    silver_row_count: int
    missing_keys: tuple[tuple[str, str], ...]
    extra_keys: tuple[tuple[str, str], ...]
    numeric_mismatch_count: int
    raw_nonnull_to_silver_null_count: int
    raw_null_to_silver_nonnull_count: int
    mismatch_samples: tuple[tuple[str, str, str | None, str | None], ...]

    @property
    def source_parity_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.raw_row_count != self.silver_row_count:
            errors.append("row_count")
        if self.missing_keys:
            errors.append("missing_keys")
        if self.extra_keys:
            errors.append("extra_keys")
        return tuple(errors)

    @property
    def cast_integrity_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.numeric_mismatch_count:
            errors.append("numeric_value_mismatch")
        if self.raw_nonnull_to_silver_null_count:
            errors.append("nonnull_value_lost")
        if self.raw_null_to_silver_nonnull_count:
            errors.append("source_null_filled")
        return tuple(errors)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                self.source_parity_errors + self.cast_integrity_errors
            )
        )


@dataclass(frozen=True, slots=True)
class IdxFactorProSilverWriteResult:
    partition_key: str
    source_path: Path
    target_path: Path
    staging_path: Path
    write_mode: str
    source_row_count: int
    written_row_count: int
    code_count: int
    min_trade_date: str | None
    max_trade_date: str | None
    output_bytes: int
    elapsed_ms: float

    def to_details(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "source_path": str(self.source_path),
            "target_path": str(self.target_path),
            "write_mode": self.write_mode,
            "source_row_count": self.source_row_count,
            "written_row_count": self.written_row_count,
            "code_count": self.code_count,
            "min_trade_date": self.min_trade_date,
            "max_trade_date": self.max_trade_date,
            "output_bytes": self.output_bytes,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def _relation_select(relation_sql: str) -> str:
    stripped = relation_sql.lstrip().lower()
    return (
        relation_sql
        if stripped.startswith(("select", "with"))
        else f"SELECT * FROM {relation_sql}"
    )


def _prepare_expected_codes(connection, expected_codes: Sequence[str]) -> None:
    connection.execute("DROP TABLE IF EXISTS idx_factor_pro_silver_expected_codes")
    connection.execute(
        "CREATE TEMP TABLE idx_factor_pro_silver_expected_codes("
        "ts_code VARCHAR PRIMARY KEY)"
    )
    connection.executemany(
        "INSERT INTO idx_factor_pro_silver_expected_codes VALUES (?)",
        [(code,) for code in expected_codes],
    )


def validate_idx_factor_pro_silver_relation(
    connection,
    *,
    relation_sql: str,
    expected_codes: Sequence[str],
    partition_key: str,
) -> IdxFactorProSilverAudit:
    """Audit one Silver relation against the exact daily contract."""

    normalized_partition = normalize_idx_factor_pro_trade_date(partition_key)
    select_sql = _relation_select(relation_sql)
    description = connection.execute(f"DESCRIBE {select_sql}").fetchall()
    columns = tuple(str(row[0]) for row in description)
    column_types = tuple(str(row[1]).upper() for row in description)
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({select_sql}) relation_rows"
        ).fetchone()[0]
        or 0
    )
    expected_types = tuple(
        IDX_FACTOR_PRO_SILVER_COLUMN_TYPES[column]
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
    )
    if columns != IDX_FACTOR_PRO_SOURCE_COLUMNS or column_types != expected_types:
        return IdxFactorProSilverAudit(
            columns=columns,
            column_types=column_types,
            row_count=row_count,
            distinct_code_count=0,
            missing_codes=tuple(expected_codes),
            extra_codes=(),
            duplicate_key_count=0,
            invalid_key_count=row_count,
            invalid_date_count=row_count,
            min_trade_date=None,
            max_trade_date=None,
        )

    _prepare_expected_codes(connection, expected_codes)
    missing_codes = tuple(
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT ts_code
            FROM idx_factor_pro_silver_expected_codes
            EXCEPT
            SELECT DISTINCT ts_code FROM ({select_sql}) relation_rows
            ORDER BY ts_code
            """
        ).fetchall()
    )
    extra_codes = tuple(
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT DISTINCT ts_code FROM ({select_sql}) relation_rows
            EXCEPT
            SELECT ts_code FROM idx_factor_pro_silver_expected_codes
            ORDER BY ts_code
            """
        ).fetchall()
    )
    counts = connection.execute(
        f"""
        SELECT
          count(DISTINCT ts_code),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
          ),
          count(*) FILTER (WHERE trade_date != CAST(? AS DATE)),
          min(trade_date),
          max(trade_date)
        FROM ({select_sql}) relation_rows
        """,
        [normalized_partition],
    ).fetchone()
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT coalesce(sum(key_count - 1), 0)
            FROM (
              SELECT count(*) AS key_count
              FROM ({select_sql}) relation_rows
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
        or 0
    )
    return IdxFactorProSilverAudit(
        columns=columns,
        column_types=column_types,
        row_count=row_count,
        distinct_code_count=int(counts[0] or 0),
        missing_codes=missing_codes,
        extra_codes=extra_codes,
        duplicate_key_count=duplicate_key_count,
        invalid_key_count=int(counts[1] or 0),
        invalid_date_count=int(counts[2] or 0),
        min_trade_date=str(counts[3]) if counts[3] is not None else None,
        max_trade_date=str(counts[4]) if counts[4] is not None else None,
    )


def _normalized_raw_sql(relation_sql: str) -> str:
    select_sql = _relation_select(relation_sql)
    columns_sql = ", ".join(
        f'CAST("{column}" AS DOUBLE) AS "{column}"'
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS[2:]
    )
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
      {columns_sql}
    FROM ({select_sql}) raw_rows
    """


def validate_idx_factor_pro_raw_silver_parity(
    connection,
    *,
    raw_relation_sql: str,
    silver_relation_sql: str,
) -> IdxFactorProRawSilverParityAudit:
    """Prove that Silver preserves every Raw key, value, and legitimate NULL."""

    raw_sql = _normalized_raw_sql(raw_relation_sql)
    silver_sql = _relation_select(silver_relation_sql)
    raw_row_count = int(
        connection.execute(f"SELECT count(*) FROM ({raw_sql}) rows").fetchone()[0]
        or 0
    )
    silver_row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({silver_sql}) rows"
        ).fetchone()[0]
        or 0
    )
    missing_keys = tuple(
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            f"""
            SELECT ts_code, trade_date FROM ({raw_sql}) raw_rows
            EXCEPT
            SELECT ts_code, trade_date FROM ({silver_sql}) silver_rows
            ORDER BY ts_code, trade_date
            LIMIT 20
            """
        ).fetchall()
    )
    extra_keys = tuple(
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            f"""
            SELECT ts_code, trade_date FROM ({silver_sql}) silver_rows
            EXCEPT
            SELECT ts_code, trade_date FROM ({raw_sql}) raw_rows
            ORDER BY ts_code, trade_date
            LIMIT 20
            """
        ).fetchall()
    )
    numeric_columns = IDX_FACTOR_PRO_SOURCE_COLUMNS[2:]
    mismatch_expression = " + ".join(
        f'CASE WHEN raw_rows."{column}" IS DISTINCT FROM '
        f'silver_rows."{column}" THEN 1 ELSE 0 END'
        for column in numeric_columns
    )
    lost_expression = " + ".join(
        f'CASE WHEN raw_rows."{column}" IS NOT NULL AND '
        f'silver_rows."{column}" IS NULL THEN 1 ELSE 0 END'
        for column in numeric_columns
    )
    filled_expression = " + ".join(
        f'CASE WHEN raw_rows."{column}" IS NULL AND '
        f'silver_rows."{column}" IS NOT NULL THEN 1 ELSE 0 END'
        for column in numeric_columns
    )
    mismatch_counts = connection.execute(
        f"""
        SELECT
          coalesce(sum({mismatch_expression}), 0),
          coalesce(sum({lost_expression}), 0),
          coalesce(sum({filled_expression}), 0)
        FROM ({raw_sql}) raw_rows
        JOIN ({silver_sql}) silver_rows USING (ts_code, trade_date)
        """
    ).fetchone()
    sample_selects = " UNION ALL ".join(
        f"""
        SELECT raw_rows.ts_code, {duckdb_string(column)} AS column_name,
               CAST(raw_rows."{column}" AS VARCHAR) AS raw_value,
               CAST(silver_rows."{column}" AS VARCHAR) AS silver_value
        FROM ({raw_sql}) raw_rows
        JOIN ({silver_sql}) silver_rows USING (ts_code, trade_date)
        WHERE raw_rows."{column}" IS DISTINCT FROM silver_rows."{column}"
        """
        for column in numeric_columns
    )
    mismatch_samples = tuple(
        (
            str(row[0]),
            str(row[1]),
            str(row[2]) if row[2] is not None else None,
            str(row[3]) if row[3] is not None else None,
        )
        for row in connection.execute(
            f"""
            SELECT ts_code, column_name, raw_value, silver_value
            FROM ({sample_selects}) mismatches
            ORDER BY ts_code, column_name
            LIMIT 20
            """
        ).fetchall()
    )
    return IdxFactorProRawSilverParityAudit(
        raw_row_count=raw_row_count,
        silver_row_count=silver_row_count,
        missing_keys=missing_keys,
        extra_keys=extra_keys,
        numeric_mismatch_count=int(mismatch_counts[0] or 0),
        raw_nonnull_to_silver_null_count=int(mismatch_counts[1] or 0),
        raw_null_to_silver_nonnull_count=int(mismatch_counts[2] or 0),
        mismatch_samples=mismatch_samples,
    )


def _silver_select(raw_path: Path) -> str:
    raw_relation = read_parquet(raw_path, hive_partitioning=False)
    numeric_columns = ",\n      ".join(
        f'CAST("{column}" AS DOUBLE) AS "{column}"'
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS[2:]
    )
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
      {numeric_columns}
    FROM {raw_relation}
    ORDER BY ts_code, trade_date
    """


def _validate_existing_target(
    *,
    duckdb_resource: DuckDBResource,
    raw_path: Path,
    target_path: Path,
    expected_codes: Sequence[str],
    partition_key: str,
) -> None:
    try:
        with duckdb_resource.connect() as connection:
            silver_audit = validate_idx_factor_pro_silver_relation(
                connection,
                relation_sql=read_parquet(target_path, hive_partitioning=False),
                expected_codes=expected_codes,
                partition_key=partition_key,
            )
            parity_audit = validate_idx_factor_pro_raw_silver_parity(
                connection,
                raw_relation_sql=read_parquet(raw_path, hive_partitioning=False),
                silver_relation_sql=read_parquet(
                    target_path,
                    hive_partitioning=False,
                ),
            )
    except Exception as error:
        raise IdxFactorProSilverValidationError(
            "existing Silver target is unreadable and cannot be overwritten: "
            f"path={target_path}, error_type={type(error).__name__}"
        ) from error
    if silver_audit.errors or parity_audit.errors:
        raise IdxFactorProSilverValidationError(
            "existing Silver target is invalid and cannot be overwritten: "
            f"contract_errors={silver_audit.errors!r}, "
            f"parity_errors={parity_audit.errors!r}, path={target_path}"
        )
    raise IdxFactorProSilverValidationError(
        "healthy Silver target already exists; daily writer refuses overwrite: "
        f"{target_path}"
    )


def write_idx_factor_pro_silver_partition(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    run_id: str,
) -> IdxFactorProSilverWriteResult:
    """Pure-cast one validated Raw partition into one atomic Silver file."""

    started_at = perf_counter()
    normalized_partition = normalize_idx_factor_pro_trade_date(partition_key)
    expected_codes = active_idx_factor_pro_daily_codes(normalized_partition)
    if not expected_codes:
        raise IdxFactorProSilverValidationError(
            f"active idx_factor_pro code scope is empty for {normalized_partition}"
        )
    source_path = raw_idx_factor_pro_path(lake_root_path, normalized_partition)
    target_path = silver_index_factor_pro_path(
        lake_root_path,
        normalized_partition,
    )
    staging_path = silver_index_factor_pro_staging_path(
        staging_root_path,
        run_id,
        normalized_partition,
    )
    if not source_path.exists():
        raise IdxFactorProSilverValidationError(
            f"Raw idx_factor_pro source is missing: {source_path}"
        )
    try:
        with duckdb_resource.connect() as connection:
            raw_audit = validate_idx_factor_pro_raw_relation(
                connection,
                relation_sql=read_parquet(source_path, hive_partitioning=False),
                expected_codes=expected_codes,
                partition_key=normalized_partition,
            )
    except Exception as error:
        raise IdxFactorProSilverValidationError(
            "Raw idx_factor_pro source is unreadable: "
            f"path={source_path}, error_type={type(error).__name__}"
        ) from error
    if raw_audit.errors:
        raise IdxFactorProSilverValidationError(
            "Raw idx_factor_pro source failed contract validation: "
            f"errors={raw_audit.errors!r}, path={source_path}"
        )
    if target_path.exists():
        _validate_existing_target(
            duckdb_resource=duckdb_resource,
            raw_path=source_path,
            target_path=target_path,
            expected_codes=expected_codes,
            partition_key=normalized_partition,
        )
    if staging_path.exists():
        raise IdxFactorProSilverValidationError(
            f"run-scoped Silver staging file already exists: {staging_path}"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.parent.stat().st_dev != staging_path.parent.stat().st_dev:
        raise IdxFactorProSilverValidationError(
            "Silver staging and target must share one filesystem for atomic os.replace"
        )

    try:
        with duckdb_resource.connect() as connection:
            connection.execute(
                f"COPY ({_silver_select(source_path)}) TO "
                f"{duckdb_string(staging_path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            staging_audit = validate_idx_factor_pro_silver_relation(
                connection,
                relation_sql=read_parquet(staging_path, hive_partitioning=False),
                expected_codes=expected_codes,
                partition_key=normalized_partition,
            )
            parity_audit = validate_idx_factor_pro_raw_silver_parity(
                connection,
                raw_relation_sql=read_parquet(source_path, hive_partitioning=False),
                silver_relation_sql=read_parquet(
                    staging_path,
                    hive_partitioning=False,
                ),
            )
            if staging_audit.errors:
                raise IdxFactorProSilverValidationError(
                    "Silver staging failed contract validation: "
                    f"errors={staging_audit.errors!r}"
                )
            if parity_audit.errors:
                raise IdxFactorProSilverValidationError(
                    "Raw/Silver staging reconciliation failed: "
                    f"errors={parity_audit.errors!r}, "
                    f"samples={parity_audit.mismatch_samples!r}"
                )
        if target_path.exists():
            raise IdxFactorProSilverValidationError(
                f"Silver target appeared during staging; refusing overwrite: {target_path}"
            )
        os.replace(staging_path, target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return IdxFactorProSilverWriteResult(
        partition_key=normalized_partition,
        source_path=source_path,
        target_path=target_path,
        staging_path=staging_path,
        write_mode="staged_atomic_replace",
        source_row_count=raw_audit.row_count,
        written_row_count=staging_audit.row_count,
        code_count=staging_audit.distinct_code_count,
        min_trade_date=staging_audit.min_trade_date,
        max_trade_date=staging_audit.max_trade_date,
        output_bytes=target_path.stat().st_size,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


__all__ = [
    "IdxFactorProRawSilverParityAudit",
    "IdxFactorProSilverAudit",
    "IdxFactorProSilverValidationError",
    "IdxFactorProSilverWriteResult",
    "validate_idx_factor_pro_raw_silver_parity",
    "validate_idx_factor_pro_silver_relation",
    "write_idx_factor_pro_silver_partition",
]
