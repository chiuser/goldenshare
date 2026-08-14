"""Major-index adapters for the shared set-based nine-turn formula."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path

import duckdb

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.nineturn_formula import build_nineturn_formula_select_sql
from orchestrator.defs.paths import (
    gold_major_index_daily_nineturn_path,
    gold_major_index_daily_nineturn_staging_path,
    gold_major_index_mins_nineturn_path,
    gold_major_index_mins_nineturn_staging_path,
    gold_major_index_mins_path,
    gold_market_major_indices_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.column_schema import ColumnContract
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD,
    MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS,
    MajorIndexNineturnPartitionWriteResult,
    MajorIndexNineturnSourcePlan,
    normalize_major_index_nineturn_minute_freq,
)

GOLD_MAJOR_INDEX_DAILY_NINETURN_COLUMNS = tuple(
    column.name for column in GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA
)
GOLD_MAJOR_INDEX_MINS_NINETURN_COLUMNS = tuple(
    column.name for column in GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA
)


def build_gold_major_index_daily_nineturn_select_sql(
    *,
    source_paths: Sequence[Path],
) -> str:
    return _build_select_sql(
        source_sql=_daily_source_sql(source_paths),
        freq=None,
    )


def build_gold_major_index_mins_nineturn_select_sql(
    *,
    source_paths: Sequence[Path],
    freq: int | str,
) -> str:
    normalized_freq = normalize_major_index_nineturn_minute_freq(freq)
    return _build_select_sql(
        source_sql=_minute_source_sql(source_paths, normalized_freq),
        freq=normalized_freq,
    )


def build_gold_major_index_daily_nineturn_partition_select_sql(
    *,
    source_paths: Sequence[Path],
    target_trade_date: str,
    previous_partition_path: Path | None,
) -> str:
    return _build_window_select_sql(
        source_sql=_daily_source_sql(source_paths),
        context_sql=None,
        seed_sql=_seed_sql(previous_partition_path, freq=None),
        start_date=target_trade_date,
        end_date=target_trade_date,
        freq=None,
    )


def build_gold_major_index_mins_nineturn_partition_select_sql(
    *,
    source_paths: Sequence[Path],
    freq: int | str,
    target_trade_date: str,
    previous_partition_path: Path | None,
) -> str:
    normalized_freq = normalize_major_index_nineturn_minute_freq(freq)
    return _build_window_select_sql(
        source_sql=_minute_source_sql(source_paths, normalized_freq),
        context_sql=None,
        seed_sql=_seed_sql(previous_partition_path, freq=normalized_freq),
        start_date=target_trade_date,
        end_date=target_trade_date,
        freq=normalized_freq,
    )


def build_gold_major_index_nineturn_history_batch_select_sql(
    *,
    source_paths: Sequence[Path],
    context_paths: Sequence[Path],
    start_date: str,
    end_date: str,
    freq: int | str | None,
    previous_partition_path: Path | None,
) -> str:
    normalized_freq = (
        None if freq is None else normalize_major_index_nineturn_minute_freq(freq)
    )
    source_sql = (
        _daily_source_sql(source_paths)
        if normalized_freq is None
        else _minute_source_sql(source_paths, normalized_freq)
    )
    context_sql = None
    if context_paths:
        context_sql = (
            _daily_source_sql(context_paths)
            if normalized_freq is None
            else _minute_source_sql(context_paths, normalized_freq)
        )
    return _build_window_select_sql(
        source_sql=source_sql,
        context_sql=context_sql,
        seed_sql=_seed_sql(previous_partition_path, freq=normalized_freq),
        start_date=start_date,
        end_date=end_date,
        freq=normalized_freq,
    )


def plan_gold_major_index_daily_nineturn_source(
    connection: duckdb.DuckDBPyConnection,
    *,
    lake_root: Path,
    partition_key: str,
    previous_trade_date: str | None,
) -> MajorIndexNineturnSourcePlan:
    source_root = Path(lake_root) / "gold" / "market" / "major_indices_daily"
    return _plan_partition_source(
        connection,
        history_paths=tuple(sorted(source_root.glob("trade_date=*/part-000.parquet"))),
        target_path=gold_market_major_indices_daily_path(lake_root, partition_key),
        previous_partition_path=(
            gold_major_index_daily_nineturn_path(lake_root, previous_trade_date)
            if previous_trade_date is not None
            else None
        ),
        partition_key=partition_key,
        freq=None,
    )


def plan_gold_major_index_mins_nineturn_source(
    connection: duckdb.DuckDBPyConnection,
    *,
    lake_root: Path,
    freq: int | str,
    partition_key: str,
    previous_trade_date: str | None,
) -> MajorIndexNineturnSourcePlan:
    normalized_freq = normalize_major_index_nineturn_minute_freq(freq)
    source_root = (
        Path(lake_root)
        / "gold"
        / "quote"
        / "major_index_mins"
        / f"freq={normalized_freq}"
    )
    return _plan_partition_source(
        connection,
        history_paths=tuple(sorted(source_root.glob("trade_date=*/part-000.parquet"))),
        target_path=gold_major_index_mins_path(
            lake_root, normalized_freq, partition_key
        ),
        previous_partition_path=(
            gold_major_index_mins_nineturn_path(
                lake_root, normalized_freq, previous_trade_date
            )
            if previous_trade_date is not None
            else None
        ),
        partition_key=partition_key,
        freq=normalized_freq,
    )


def write_gold_major_index_daily_nineturn_partition(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
    staging_root: Path,
    partition_key: str,
    run_id: str,
    select_sql: str,
    source_paths: Sequence[Path],
    previous_partition_path: Path | None,
    source_row_count: int,
) -> MajorIndexNineturnPartitionWriteResult:
    return _write_partition(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        partition_key=partition_key,
        freq=None,
        select_sql=select_sql,
        source_paths=source_paths,
        previous_partition_path=previous_partition_path,
        source_row_count=source_row_count,
        target_path=gold_major_index_daily_nineturn_path(lake_root, partition_key),
        staging_path=gold_major_index_daily_nineturn_staging_path(
            staging_root, run_id, partition_key
        ),
        schema=GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA,
    )


def write_gold_major_index_mins_nineturn_partition(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
    staging_root: Path,
    freq: int | str,
    partition_key: str,
    run_id: str,
    select_sql: str,
    source_paths: Sequence[Path],
    previous_partition_path: Path | None,
    source_row_count: int,
) -> MajorIndexNineturnPartitionWriteResult:
    normalized_freq = normalize_major_index_nineturn_minute_freq(freq)
    return _write_partition(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        partition_key=partition_key,
        freq=normalized_freq,
        select_sql=select_sql,
        source_paths=source_paths,
        previous_partition_path=previous_partition_path,
        source_row_count=source_row_count,
        target_path=gold_major_index_mins_nineturn_path(
            lake_root, normalized_freq, partition_key
        ),
        staging_path=gold_major_index_mins_nineturn_staging_path(
            staging_root, run_id, normalized_freq, partition_key
        ),
        schema=GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA,
    )


def _plan_partition_source(
    connection: duckdb.DuckDBPyConnection,
    *,
    history_paths: Sequence[Path],
    target_path: Path,
    previous_partition_path: Path | None,
    partition_key: str,
    freq: int | None,
) -> MajorIndexNineturnSourcePlan:
    eligible_paths = tuple(
        path for path in history_paths if _partition_date(path) <= partition_key
    )
    if target_path not in eligible_paths or not target_path.is_file():
        raise FileNotFoundError(
            f"Major-index nine-turn source file is missing: {target_path}"
        )
    source_paths = eligible_paths[-MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS:]
    if previous_partition_path is not None and not previous_partition_path.is_file():
        raise FileNotFoundError(
            "Previous major-index nine-turn partition is missing: "
            f"{previous_partition_path}"
        )
    source = _read_parquet_paths(source_paths)
    freq_predicate = "" if freq is None else f"AND CAST(freq AS INTEGER) = {freq}"
    source_row_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {source}
            WHERE CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
              {freq_predicate}
            """
        ).fetchone()[0]
    )
    if source_row_count <= 0:
        raise ValueError(
            f"Major-index source has no rows for target partition {partition_key}."
        )
    return MajorIndexNineturnSourcePlan(
        source_paths=source_paths,
        previous_partition_path=previous_partition_path,
        source_row_count=source_row_count,
    )


def _build_select_sql(*, source_sql: str, freq: int | None) -> str:
    formula_sql = build_nineturn_formula_select_sql(source_sql=source_sql)
    return _project_formula_sql(formula_sql=formula_sql, freq=freq)


def _build_window_select_sql(
    *,
    source_sql: str,
    context_sql: str | None,
    seed_sql: str,
    start_date: str,
    end_date: str,
    freq: int | None,
) -> str:
    formula_sql = build_nineturn_formula_select_sql(
        source_sql=source_sql,
        context_sql=context_sql,
        seed_sql=seed_sql,
        start_date=start_date,
        end_date=end_date,
    )
    return _project_formula_sql(formula_sql=formula_sql, freq=freq)


def _project_formula_sql(*, formula_sql: str, freq: int | None) -> str:
    if freq is None:
        projection = """
        subject_code AS ts_code,
        bar_date AS trade_date,
        close_value AS close,
        up_count,
        down_count,
        nine_up_turn,
        nine_down_turn
        """
        order_by = "ts_code, trade_date"
    else:
        projection = f"""
        subject_code AS ts_code,
        {freq}::INTEGER AS freq,
        bar_date AS trade_date,
        bar_time AS trade_time,
        close_value AS close,
        up_count,
        down_count,
        nine_up_turn,
        nine_down_turn
        """
        order_by = "ts_code, trade_time"
    return f"""
    WITH formula_rows AS ({formula_sql})
    SELECT {projection}
    FROM formula_rows
    ORDER BY {order_by}
    """


def _daily_source_sql(source_paths: Sequence[Path]) -> str:
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS subject_code,
      CAST(trade_date AS DATE) AS bar_date,
      CAST(trade_date AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_value
    FROM {_read_parquet_paths(source_paths)}
    """


def _minute_source_sql(source_paths: Sequence[Path], freq: int) -> str:
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS subject_code,
      CAST(trade_date AS DATE) AS bar_date,
      CAST(trade_time AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_value
    FROM {_read_parquet_paths(source_paths)}
    WHERE CAST(freq AS INTEGER) = {freq}
    """


def _seed_sql(previous_partition_path: Path | None, *, freq: int | None) -> str:
    if previous_partition_path is None:
        return """
        SELECT NULL::VARCHAR AS subject_code,
               NULL::INTEGER AS seed_direction,
               NULL::INTEGER AS seed_count
        WHERE false
        """
    source = read_parquet(previous_partition_path, hive_partitioning=False)
    qualify = ""
    if freq is not None:
        qualify = f"""
        WHERE CAST(freq AS INTEGER) = {freq}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY ts_code ORDER BY CAST(trade_time AS TIMESTAMP) DESC
        ) = 1
        """
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS subject_code,
      CASE WHEN up_count > 0 THEN 1 WHEN down_count > 0 THEN -1 ELSE 0 END
        AS seed_direction,
      greatest(CAST(up_count AS INTEGER), CAST(down_count AS INTEGER)) AS seed_count
    FROM {source}
    {qualify}
    """


def build_major_index_nineturn_source_fingerprint(
    *,
    lake_root: Path,
    source_paths: Sequence[Path],
) -> str:
    root = lake_root.resolve()
    identities: list[str] = []
    for path in sorted((Path(value) for value in source_paths), key=str):
        if not path.is_file():
            raise FileNotFoundError(f"Missing major-index nine-turn input: {path}")
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Major-index nine-turn input must stay under Lake root.")
        stat = resolved.stat()
        identities.append(
            f"{resolved.relative_to(root).as_posix()}\t{stat.st_size}\t{stat.st_mtime_ns}"
        )
    if not identities:
        raise ValueError("At least one major-index nine-turn input is required.")
    return hashlib.sha256("\n".join(identities).encode()).hexdigest()


def _write_partition(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
    partition_key: str,
    freq: int | None,
    select_sql: str,
    source_paths: Sequence[Path],
    previous_partition_path: Path | None,
    source_row_count: int,
    target_path: Path,
    staging_path: Path,
    schema: Sequence[ColumnContract],
) -> MajorIndexNineturnPartitionWriteResult:
    if source_row_count <= 0:
        raise ValueError("Major-index nine-turn source row count must be positive.")
    fingerprint_paths = tuple(source_paths) + (
        (previous_partition_path,) if previous_partition_path is not None else ()
    )
    source_fingerprint = build_major_index_nineturn_source_fingerprint(
        lake_root=lake_root,
        source_paths=fingerprint_paths,
    )
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    if staging_path.exists():
        staging_path.unlink()
    try:
        with duckdb_resource.connect() as connection:
            connection.execute(copy_query_to_parquet(select_sql, staging_path))
            observed_columns, output_row_count, index_code_count = _validate_partition(
                connection=connection,
                path=staging_path,
                schema=schema,
                partition_key=partition_key,
                freq=freq,
                expected_row_count=source_row_count,
            )
        if (
            build_major_index_nineturn_source_fingerprint(
                lake_root=lake_root,
                source_paths=fingerprint_paths,
            )
            != source_fingerprint
        ):
            raise RuntimeError(
                "Major-index nine-turn input changed while the partition was written."
            )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_path, target_path)
        return MajorIndexNineturnPartitionWriteResult(
            target_path=target_path,
            source_row_count=source_row_count,
            output_row_count=output_row_count,
            index_code_count=index_code_count,
            source_file_count=len(fingerprint_paths),
            source_fingerprint=source_fingerprint,
            observed_columns=observed_columns,
        )
    finally:
        if staging_path.exists():
            staging_path.unlink()


def _validate_partition(
    *,
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    schema: Sequence[ColumnContract],
    partition_key: str,
    freq: int | None,
    expected_row_count: int,
) -> tuple[tuple[str, ...], int, int]:
    observed_schema = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(
            describe_parquet_query(path, hive_partitioning=False)
        ).fetchall()
    )
    expected_schema = tuple((column.name, column.type.upper()) for column in schema)
    if observed_schema != expected_schema:
        raise ValueError(
            "Major-index nine-turn schema mismatch: "
            f"expected={expected_schema}, observed={observed_schema}."
        )
    source = read_parquet(path, hive_partitioning=False)
    key_columns = "ts_code, trade_date" if freq is None else "ts_code, freq, trade_time"
    minute_key_predicate = ""
    freq_mismatch_sql = "0"
    if freq is not None:
        minute_key_predicate = "OR freq IS NULL OR trade_time IS NULL"
        freq_mismatch_sql = f"count(*) FILTER (WHERE freq != {freq} OR CAST(trade_time AS DATE) != trade_date)"
    metrics = connection.execute(
        f"""
        SELECT
          count(*),
          count(DISTINCT ts_code),
          count(*) - count(DISTINCT ({key_columns})),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
              {minute_key_predicate}
          ),
          count(*) FILTER (
            WHERE trade_date != DATE {duckdb_string(partition_key)}
          ),
          {freq_mismatch_sql},
          count(*) FILTER (
            WHERE close IS NULL OR NOT isfinite(close) OR close <= 0
              OR up_count IS NULL OR down_count IS NULL
              OR up_count < 0 OR down_count < 0
              OR (up_count > 0 AND down_count > 0)
              OR (nine_up_turn IS NOT NULL AND nine_up_turn != '+9')
              OR (nine_down_turn IS NOT NULL AND nine_down_turn != '-9')
              OR (nine_up_turn = '+9' AND up_count < {MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_down_turn = '-9' AND down_count < {MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
          )
        FROM {source}
        """
    ).fetchone()
    values = tuple(int(value or 0) for value in metrics)
    (
        row_count,
        code_count,
        duplicate_count,
        null_count,
        date_count,
        freq_count,
        invalid_count,
    ) = values
    if row_count != expected_row_count:
        raise ValueError(
            "Major-index nine-turn output row count must match source: "
            f"source={expected_row_count}, output={row_count}."
        )
    failures = {
        name: value
        for name, value in zip(
            ("duplicate", "null_key", "partition", "freq_or_time", "value"),
            (duplicate_count, null_count, date_count, freq_count, invalid_count),
            strict=True,
        )
        if value
    }
    if failures:
        raise ValueError(f"Major-index nine-turn output contract failed: {failures}.")
    return tuple(name for name, _ in observed_schema), row_count, code_count


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    normalized = tuple(Path(path) for path in paths)
    if not normalized:
        raise ValueError("At least one major-index source path is required.")
    if len(normalized) == 1:
        return read_parquet(normalized[0], hive_partitioning=False)
    values = ", ".join(duckdb_string(path) for path in normalized)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=true)"


def _partition_date(path: Path) -> str:
    return path.parent.name.removeprefix("trade_date=")


__all__ = [
    "GOLD_MAJOR_INDEX_DAILY_NINETURN_COLUMNS",
    "GOLD_MAJOR_INDEX_MINS_NINETURN_COLUMNS",
    "build_gold_major_index_daily_nineturn_partition_select_sql",
    "build_gold_major_index_daily_nineturn_select_sql",
    "build_gold_major_index_mins_nineturn_partition_select_sql",
    "build_gold_major_index_mins_nineturn_select_sql",
    "build_gold_major_index_nineturn_history_batch_select_sql",
    "build_major_index_nineturn_source_fingerprint",
    "plan_gold_major_index_daily_nineturn_source",
    "plan_gold_major_index_mins_nineturn_source",
    "write_gold_major_index_daily_nineturn_partition",
    "write_gold_major_index_mins_nineturn_partition",
]
