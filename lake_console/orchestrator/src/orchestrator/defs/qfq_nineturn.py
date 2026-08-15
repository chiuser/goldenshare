"""Set-based QFQ nine-turn calculation and partition writing helpers."""

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
    gold_stk_mins_qfq_nineturn_path,
    gold_stk_mins_qfq_nineturn_staging_path,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_staging_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.column_schema import ColumnContract
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_COMPARISON_LAG,
    QFQ_NINETURN_FALLBACK_CODE_LIMIT,
    QFQ_NINETURN_SIGNAL_THRESHOLD,
    QFQ_NINETURN_SOURCE_CONTEXT_TRADE_DAYS,
    QfqNineturnPartitionWriteResult,
    QfqNineturnSourcePlan,
    normalize_qfq_nineturn_minute_freq,
)

GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS = tuple(
    column.name for column in GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
)
GOLD_STK_MINS_QFQ_NINETURN_COLUMNS = tuple(
    column.name for column in GOLD_STK_MINS_QFQ_NINETURN_SCHEMA
)


def build_gold_stock_daily_qfq_nineturn_select_sql(
    *,
    source_paths: Sequence[Path],
    stock_codes: Sequence[str] = (),
) -> str:
    """Build the exact full-history daily QFQ nine-turn projection."""

    source = _read_parquet_paths(source_paths)
    code_filter = _stock_code_filter_sql(stock_codes)
    source_sql = f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(trade_date AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_qfq
    FROM {source}
    {code_filter}
    """
    return _build_qfq_nineturn_select_sql(
        source_sql=source_sql,
        freq=None,
        output_columns=(
            "ts_code",
            "trade_date",
            "close_qfq",
            "up_count",
            "down_count",
            "nine_up_turn",
            "nine_down_turn",
        ),
        order_by="ts_code, trade_date",
    )


def build_gold_stk_mins_qfq_nineturn_select_sql(
    *,
    source_paths: Sequence[Path],
    freq: int | str,
    stock_codes: Sequence[str] = (),
) -> str:
    """Build the exact full-history minute QFQ nine-turn projection."""

    normalized_freq = normalize_qfq_nineturn_minute_freq(freq)
    source = _read_parquet_paths(source_paths)
    code_filter = _stock_code_filter_sql(stock_codes, has_where=True)
    source_sql = f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS INTEGER) AS freq,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(trade_time AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_qfq
    FROM {source}
    WHERE CAST(freq AS INTEGER) = {normalized_freq}
      {code_filter}
    """
    return _build_qfq_nineturn_select_sql(
        source_sql=source_sql,
        freq=normalized_freq,
        output_columns=(
            "ts_code",
            "freq",
            "trade_date",
            "trade_time",
            "up_count",
            "down_count",
            "nine_up_turn",
            "nine_down_turn",
        ),
        order_by="ts_code, trade_time",
    )


def build_gold_stock_daily_qfq_nineturn_history_batch_select_sql(
    *,
    source_paths: Sequence[Path],
    start_date: str,
    end_date: str,
    context_path: Path | None = None,
    seed_path: Path | None = None,
) -> str:
    """Build one exact annual daily history batch with compact prior state."""

    source = _read_parquet_paths(source_paths)
    source_sql = f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      NULL::INTEGER AS freq,
      CAST(trade_date AS DATE) AS trade_date,
      NULL::TIMESTAMP AS trade_time,
      CAST(trade_date AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_qfq
    FROM {source}
    WHERE CAST(trade_date AS DATE) BETWEEN DATE {duckdb_string(start_date)}
                                      AND DATE {duckdb_string(end_date)}
    """
    return _build_qfq_nineturn_history_batch_select_sql(
        source_sql=source_sql,
        context_sql=_history_context_sql(context_path, freq=None),
        seed_sql=_history_seed_sql(seed_path),
        start_date=start_date,
        end_date=end_date,
        freq=None,
        output_columns=GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
        order_by="ts_code, trade_date",
    )


def build_gold_stk_mins_qfq_nineturn_history_batch_select_sql(
    *,
    source_paths: Sequence[Path],
    freq: int | str,
    start_date: str,
    end_date: str,
    context_path: Path | None = None,
    seed_path: Path | None = None,
) -> str:
    """Build one exact annual minute history batch with compact prior state."""

    normalized_freq = normalize_qfq_nineturn_minute_freq(freq)
    source = _read_parquet_paths(source_paths)
    source_sql = f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS INTEGER) AS freq,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(trade_time AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_qfq
    FROM {source}
    WHERE CAST(freq AS INTEGER) = {normalized_freq}
      AND CAST(trade_date AS DATE) BETWEEN DATE {duckdb_string(start_date)}
                                        AND DATE {duckdb_string(end_date)}
    """
    return _build_qfq_nineturn_history_batch_select_sql(
        source_sql=source_sql,
        context_sql=_history_context_sql(context_path, freq=normalized_freq),
        seed_sql=_history_seed_sql(seed_path),
        start_date=start_date,
        end_date=end_date,
        freq=normalized_freq,
        output_columns=GOLD_STK_MINS_QFQ_NINETURN_COLUMNS,
        order_by="ts_code, trade_time",
    )


def build_gold_stock_daily_qfq_nineturn_partition_select_sql(
    *,
    source_paths: Sequence[Path],
    target_trade_date: str,
    previous_partition_path: Path | None = None,
    fallback_source_paths: Sequence[Path] = (),
    fallback_codes: Sequence[str] = (),
) -> str:
    """Build one daily partition from bounded context and explicit fallback scope."""

    source = _read_parquet_paths(source_paths)
    source_sql = f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(trade_date AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_qfq
    FROM {source}
    """
    seed_sql = _daily_seed_sql(previous_partition_path)
    return _build_qfq_nineturn_partition_select_sql(
        source_sql=source_sql,
        seed_sql=seed_sql,
        target_trade_date=target_trade_date,
        freq=None,
        fallback_source_paths=fallback_source_paths,
        fallback_codes=fallback_codes,
        output_columns=GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
        order_by="ts_code, trade_date",
    )


def build_gold_stk_mins_qfq_nineturn_partition_select_sql(
    *,
    source_paths: Sequence[Path],
    freq: int | str,
    target_trade_date: str,
    previous_partition_path: Path | None = None,
    fallback_source_paths: Sequence[Path] = (),
    fallback_codes: Sequence[str] = (),
) -> str:
    """Build one minute partition from bounded context and explicit fallback scope."""

    normalized_freq = normalize_qfq_nineturn_minute_freq(freq)
    source = _read_parquet_paths(source_paths)
    source_sql = f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS INTEGER) AS freq,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(trade_time AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_qfq
    FROM {source}
    WHERE CAST(freq AS INTEGER) = {normalized_freq}
    """
    seed_sql = _minute_seed_sql(previous_partition_path, normalized_freq)
    return _build_qfq_nineturn_partition_select_sql(
        source_sql=source_sql,
        seed_sql=seed_sql,
        target_trade_date=target_trade_date,
        freq=normalized_freq,
        fallback_source_paths=fallback_source_paths,
        fallback_codes=fallback_codes,
        output_columns=GOLD_STK_MINS_QFQ_NINETURN_COLUMNS,
        order_by="ts_code, trade_time",
    )


def build_qfq_nineturn_source_fingerprint(
    *,
    lake_root: Path,
    source_paths: Sequence[Path],
) -> str:
    """Hash source file identities without reading their business rows."""

    root = lake_root.resolve()
    identities: list[str] = []
    for source_path in sorted((Path(path) for path in source_paths), key=str):
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing QFQ nine-turn source file: {source_path}")
        resolved_path = source_path.resolve()
        try:
            relative_path = resolved_path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(
                "QFQ nine-turn source file must be under lake root: "
                f"source_path={source_path}, lake_root={lake_root}."
            ) from exc
        stat = resolved_path.stat()
        identities.append(f"{relative_path}\t{stat.st_size}\t{stat.st_mtime_ns}")
    if not identities:
        raise ValueError("At least one QFQ nine-turn source file is required.")
    return hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()


def plan_gold_stock_daily_qfq_nineturn_source(
    connection: duckdb.DuckDBPyConnection,
    *,
    lake_root: Path,
    partition_key: str,
    previous_trade_date: str | None,
) -> QfqNineturnSourcePlan:
    source_root = Path(lake_root) / "gold" / "quote" / "stock_daily_qfq"
    history_paths = tuple(
        path
        for path in sorted(source_root.glob("trade_date=*/part-000.parquet"))
        if _partition_date_from_path(path) <= partition_key
    )
    target_path = gold_stock_daily_qfq_path(lake_root, partition_key)
    if target_path not in history_paths:
        raise FileNotFoundError(f"Daily QFQ source file is missing: {target_path}")
    source_paths = history_paths[-QFQ_NINETURN_SOURCE_CONTEXT_TRADE_DAYS:]
    previous_partition_path = _existing_previous_nineturn_path(
        gold_stock_daily_qfq_nineturn_path(lake_root, previous_trade_date)
        if previous_trade_date is not None
        else None
    )
    source_row_count, fallback_codes = _plan_fallback_codes(
        connection,
        source_paths=source_paths,
        history_paths=history_paths,
        partition_key=partition_key,
        previous_partition_path=previous_partition_path,
        freq=None,
    )
    return QfqNineturnSourcePlan(
        source_paths=source_paths,
        fingerprint_source_paths=tuple(
            sorted(set(source_paths).union(history_paths if fallback_codes else ()))
        ),
        fallback_source_paths=history_paths if fallback_codes else (),
        fallback_codes=fallback_codes,
        previous_partition_path=previous_partition_path,
        source_row_count=source_row_count,
    )


def plan_gold_stk_mins_qfq_nineturn_source(
    connection: duckdb.DuckDBPyConnection,
    *,
    lake_root: Path,
    freq: int | str,
    partition_key: str,
    previous_trade_date: str | None,
) -> QfqNineturnSourcePlan:
    normalized_freq = normalize_qfq_nineturn_minute_freq(freq)
    target_year = int(partition_key[:4])
    source_root = (
        Path(lake_root) / "gold" / "quote" / "stk_mins_qfq" / f"freq={normalized_freq}"
    )
    source_paths = tuple(
        sorted(
            path
            for year in (target_year - 1, target_year)
            for path in source_root.glob(f"ts_code=*/year={year}/part-000.parquet")
        )
    )
    if not source_paths:
        raise FileNotFoundError(
            "Minute QFQ source files are missing: "
            f"freq={normalized_freq}, trade_date={partition_key}."
        )
    previous_partition_path = _existing_previous_nineturn_path(
        gold_stk_mins_qfq_nineturn_path(
            lake_root,
            normalized_freq,
            previous_trade_date,
        )
        if previous_trade_date is not None
        else None
    )
    candidate_paths_by_code = _minute_paths_by_code(source_root)
    source_row_count, candidate_codes = _bounded_candidate_codes(
        connection,
        source_paths=source_paths,
        partition_key=partition_key,
        previous_partition_path=previous_partition_path,
        freq=normalized_freq,
    )
    fallback_codes = _fallback_codes_with_history(
        connection,
        history_paths=tuple(
            path
            for code in candidate_codes
            for path in candidate_paths_by_code.get(code, ())
        ),
        candidate_codes=candidate_codes,
        partition_key=partition_key,
        freq=normalized_freq,
    )
    fallback_source_paths = tuple(
        path
        for code in fallback_codes
        for path in candidate_paths_by_code.get(code, ())
    )
    return QfqNineturnSourcePlan(
        source_paths=source_paths,
        fingerprint_source_paths=tuple(
            sorted(set(source_paths).union(fallback_source_paths))
        ),
        fallback_source_paths=fallback_source_paths,
        fallback_codes=fallback_codes,
        previous_partition_path=previous_partition_path,
        source_row_count=source_row_count,
    )


def write_gold_stock_daily_qfq_nineturn_partition(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
    partition_key: str,
    run_id: str,
    select_sql: str,
    source_paths: Sequence[Path],
    fingerprint_source_paths: Sequence[Path] | None = None,
    source_row_count: int,
    fallback_recomputed_code_count: int = 0,
) -> QfqNineturnPartitionWriteResult:
    return _write_qfq_nineturn_partition(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        partition_key=partition_key,
        freq=None,
        select_sql=select_sql,
        source_paths=source_paths,
        fingerprint_source_paths=fingerprint_source_paths,
        source_row_count=source_row_count,
        fallback_recomputed_code_count=fallback_recomputed_code_count,
        target_path=gold_stock_daily_qfq_nineturn_path(lake_root, partition_key),
        staging_path=gold_stock_daily_qfq_nineturn_staging_path(
            lake_root,
            run_id,
            partition_key,
        ),
        schema=GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
    )


def write_gold_stk_mins_qfq_nineturn_partition(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
    freq: int | str,
    partition_key: str,
    run_id: str,
    select_sql: str,
    source_paths: Sequence[Path],
    fingerprint_source_paths: Sequence[Path] | None = None,
    source_row_count: int,
    fallback_recomputed_code_count: int = 0,
) -> QfqNineturnPartitionWriteResult:
    normalized_freq = normalize_qfq_nineturn_minute_freq(freq)
    return _write_qfq_nineturn_partition(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        partition_key=partition_key,
        freq=normalized_freq,
        select_sql=select_sql,
        source_paths=source_paths,
        fingerprint_source_paths=fingerprint_source_paths,
        source_row_count=source_row_count,
        fallback_recomputed_code_count=fallback_recomputed_code_count,
        target_path=gold_stk_mins_qfq_nineturn_path(
            lake_root,
            normalized_freq,
            partition_key,
        ),
        staging_path=gold_stk_mins_qfq_nineturn_staging_path(
            lake_root,
            run_id,
            normalized_freq,
            partition_key,
        ),
        schema=GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    )


def _build_qfq_nineturn_select_sql(
    *,
    source_sql: str,
    freq: int | None,
    output_columns: Sequence[str],
    order_by: str,
) -> str:
    formula_sql = build_nineturn_formula_select_sql(
        source_sql=_normalized_qfq_source_sql(source_sql),
    )
    return _project_qfq_formula_sql(
        formula_sql=formula_sql,
        freq=freq,
        output_columns=output_columns,
        order_by=order_by,
    )


def _build_qfq_nineturn_partition_select_sql(
    *,
    source_sql: str,
    seed_sql: str,
    target_trade_date: str,
    freq: int | None,
    fallback_source_paths: Sequence[Path],
    fallback_codes: Sequence[str],
    output_columns: Sequence[str],
    order_by: str,
) -> str:
    normalized_fallback_codes = _normalize_fallback_codes(fallback_codes)
    if len(normalized_fallback_codes) > QFQ_NINETURN_FALLBACK_CODE_LIMIT:
        raise ValueError(
            "QFQ nine-turn fallback code count exceeds the daily-run limit: "
            f"count={len(normalized_fallback_codes)}, "
            f"limit={QFQ_NINETURN_FALLBACK_CODE_LIMIT}."
        )
    if normalized_fallback_codes and not fallback_source_paths:
        raise ValueError("Fallback source paths are required for fallback stock codes.")

    fallback_codes_sql = _fallback_codes_sql(normalized_fallback_codes)
    normal_code_predicate = (
        "subject_code NOT IN (SELECT ts_code FROM fallback_codes)"
        if normalized_fallback_codes
        else "true"
    )
    fallback_select = _fallback_partition_select_sql(
        fallback_source_paths=fallback_source_paths,
        fallback_codes=normalized_fallback_codes,
        target_trade_date=target_trade_date,
        freq=freq,
    )
    formula_sql = build_nineturn_formula_select_sql(
        source_sql=_normalized_qfq_source_sql(source_sql),
        seed_sql=_normalized_qfq_seed_sql(seed_sql),
        start_date=target_trade_date,
        end_date=target_trade_date,
        target_subject_predicate_sql=normal_code_predicate,
    )
    normal_projection = _qfq_formula_projection_sql(freq=freq)
    return f"""
WITH fallback_codes AS (
  {fallback_codes_sql}
),
normal_output AS (
  SELECT
    {normal_projection}
  FROM ({formula_sql}) AS formula_rows
),
fallback_output AS (
  {fallback_select}
),
combined_output AS (
  SELECT {", ".join(output_columns)} FROM normal_output
  UNION ALL
  SELECT {", ".join(output_columns)} FROM fallback_output
)
SELECT {", ".join(output_columns)}
FROM combined_output
ORDER BY {order_by}
"""


def _fallback_partition_select_sql(
    *,
    fallback_source_paths: Sequence[Path],
    fallback_codes: Sequence[str],
    target_trade_date: str,
    freq: int | None,
) -> str:
    if not fallback_codes:
        return _empty_nineturn_select(freq=freq)
    if freq is None:
        full_select = build_gold_stock_daily_qfq_nineturn_select_sql(
            source_paths=fallback_source_paths,
            stock_codes=fallback_codes,
        )
    else:
        full_select = build_gold_stk_mins_qfq_nineturn_select_sql(
            source_paths=fallback_source_paths,
            freq=freq,
            stock_codes=fallback_codes,
        )
    return f"""
    SELECT full_history.*
    FROM ({full_select}) AS full_history
    INNER JOIN fallback_codes USING (ts_code)
    WHERE full_history.trade_date = DATE {duckdb_string(target_trade_date)}
    """


def _build_qfq_nineturn_history_batch_select_sql(
    *,
    source_sql: str,
    context_sql: str,
    seed_sql: str,
    start_date: str,
    end_date: str,
    freq: int | None,
    output_columns: Sequence[str],
    order_by: str,
) -> str:
    """Continue one set-based history window from compact context and count seeds."""

    formula_sql = build_nineturn_formula_select_sql(
        source_sql=_normalized_qfq_source_sql(source_sql),
        context_sql=_normalized_qfq_source_sql(context_sql),
        seed_sql=_normalized_qfq_seed_sql(seed_sql),
        start_date=start_date,
        end_date=end_date,
    )
    return _project_qfq_formula_sql(
        formula_sql=formula_sql,
        freq=freq,
        output_columns=output_columns,
        order_by=order_by,
    )


def _normalized_qfq_source_sql(source_sql: str) -> str:
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS subject_code,
      CAST(trade_date AS DATE) AS bar_date,
      CAST(bar_time AS TIMESTAMP) AS bar_time,
      CAST(close_qfq AS DOUBLE) AS close_value
    FROM ({source_sql}) AS qfq_source
    """


def _normalized_qfq_seed_sql(seed_sql: str) -> str:
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS subject_code,
      CAST(seed_direction AS INTEGER) AS seed_direction,
      CAST(seed_count AS INTEGER) AS seed_count
    FROM ({seed_sql}) AS qfq_seed
    """


def _qfq_formula_projection_sql(*, freq: int | None) -> str:
    if freq is None:
        return """
    subject_code AS ts_code,
    bar_date AS trade_date,
    close_value AS close_qfq,
    up_count,
    down_count,
    nine_up_turn,
    nine_down_turn
        """.strip()
    return f"""
    subject_code AS ts_code,
    {freq}::INTEGER AS freq,
    bar_date AS trade_date,
    bar_time AS trade_time,
    up_count,
    down_count,
    nine_up_turn,
    nine_down_turn
    """.strip()


def _project_qfq_formula_sql(
    *,
    formula_sql: str,
    freq: int | None,
    output_columns: Sequence[str],
    order_by: str,
) -> str:
    expected_columns = (
        GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS
        if freq is None
        else GOLD_STK_MINS_QFQ_NINETURN_COLUMNS
    )
    if tuple(output_columns) != expected_columns:
        raise ValueError(
            "QFQ nine-turn projection columns do not match the frozen schema: "
            f"expected={expected_columns}, actual={tuple(output_columns)}."
        )
    projection = _qfq_formula_projection_sql(freq=freq)
    return f"""
WITH formula_rows AS (
  {formula_sql}
)
SELECT
  {projection}
FROM formula_rows
ORDER BY {order_by}
"""


def _daily_seed_sql(previous_partition_path: Path | None) -> str:
    if previous_partition_path is None:
        return _empty_seed_select()
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CASE WHEN up_count > 0 THEN 1 WHEN down_count > 0 THEN -1 ELSE 0 END
        AS seed_direction,
      greatest(CAST(up_count AS INTEGER), CAST(down_count AS INTEGER)) AS seed_count
    FROM {read_parquet(previous_partition_path, hive_partitioning=False)}
    """


def _history_context_sql(context_path: Path | None, *, freq: int | None) -> str:
    if context_path is None:
        return """
        SELECT
          NULL::VARCHAR AS ts_code,
          NULL::INTEGER AS freq,
          NULL::DATE AS trade_date,
          NULL::TIMESTAMP AS trade_time,
          NULL::TIMESTAMP AS bar_time,
          NULL::DOUBLE AS close_qfq
        WHERE false
        """
    freq_predicate = "" if freq is None else f"WHERE CAST(freq AS INTEGER) = {freq}"
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS INTEGER) AS freq,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(bar_time AS TIMESTAMP) AS bar_time,
      CAST(close_qfq AS DOUBLE) AS close_qfq
    FROM {read_parquet(context_path, hive_partitioning=False)}
    {freq_predicate}
    """


def _history_seed_sql(seed_path: Path | None) -> str:
    if seed_path is None:
        return _empty_seed_select()
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(seed_direction AS INTEGER) AS seed_direction,
      CAST(seed_count AS INTEGER) AS seed_count
    FROM {read_parquet(seed_path, hive_partitioning=False)}
    """


def _minute_seed_sql(previous_partition_path: Path | None, freq: int) -> str:
    if previous_partition_path is None:
        return _empty_seed_select()
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CASE WHEN up_count > 0 THEN 1 WHEN down_count > 0 THEN -1 ELSE 0 END
        AS seed_direction,
      greatest(CAST(up_count AS INTEGER), CAST(down_count AS INTEGER)) AS seed_count
    FROM {read_parquet(previous_partition_path, hive_partitioning=False)}
    WHERE CAST(freq AS INTEGER) = {freq}
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY ts_code
      ORDER BY CAST(trade_time AS TIMESTAMP) DESC
    ) = 1
    """


def _empty_seed_select() -> str:
    return """
    SELECT
      NULL::VARCHAR AS ts_code,
      NULL::INTEGER AS seed_direction,
      NULL::INTEGER AS seed_count
    WHERE false
    """


def _empty_nineturn_select(*, freq: int | None) -> str:
    schema = (
        GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
        if freq is None
        else GOLD_STK_MINS_QFQ_NINETURN_SCHEMA
    )
    columns = ",\n      ".join(
        f"NULL::{column.type} AS {column.name}" for column in schema
    )
    return f"SELECT\n      {columns}\n    WHERE false"


def _normalize_fallback_codes(stock_codes: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(stock_code).strip().upper()
                for stock_code in stock_codes
                if str(stock_code).strip()
            }
        )
    )


def _fallback_codes_sql(stock_codes: Sequence[str]) -> str:
    if not stock_codes:
        return "SELECT NULL::VARCHAR AS ts_code WHERE false"
    values = ", ".join(f"({duckdb_string(stock_code)})" for stock_code in stock_codes)
    return (
        f"SELECT ts_code::VARCHAR AS ts_code FROM (VALUES {values}) AS codes(ts_code)"
    )


def _stock_code_filter_sql(
    stock_codes: Sequence[str],
    *,
    has_where: bool = False,
) -> str:
    normalized_codes = _normalize_fallback_codes(stock_codes)
    if not normalized_codes:
        return ""
    keyword = "AND" if has_where else "WHERE"
    values = ", ".join(duckdb_string(code) for code in normalized_codes)
    return f"{keyword} CAST(ts_code AS VARCHAR) IN ({values})"


def _partition_date_from_path(path: Path) -> str:
    return path.parent.name.removeprefix("trade_date=")


def _existing_previous_nineturn_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    if not path.is_file():
        raise FileNotFoundError(f"Previous QFQ nine-turn partition is missing: {path}")
    return path


def _minute_paths_by_code(source_root: Path) -> dict[str, tuple[Path, ...]]:
    paths_by_code: dict[str, list[Path]] = {}
    for path in sorted(source_root.glob("ts_code=*/year=*/part-000.parquet")):
        code = path.parent.parent.name.removeprefix("ts_code=")
        paths_by_code.setdefault(code, []).append(path)
    return {code: tuple(paths) for code, paths in paths_by_code.items()}


def _plan_fallback_codes(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_paths: Sequence[Path],
    history_paths: Sequence[Path],
    partition_key: str,
    previous_partition_path: Path | None,
    freq: int | None,
) -> tuple[int, tuple[str, ...]]:
    source_row_count, candidate_codes = _bounded_candidate_codes(
        connection,
        source_paths=source_paths,
        partition_key=partition_key,
        previous_partition_path=previous_partition_path,
        freq=freq,
    )
    return source_row_count, _fallback_codes_with_history(
        connection,
        history_paths=history_paths,
        candidate_codes=candidate_codes,
        partition_key=partition_key,
        freq=freq,
    )


def _bounded_candidate_codes(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_paths: Sequence[Path],
    partition_key: str,
    previous_partition_path: Path | None,
    freq: int | None,
) -> tuple[int, tuple[str, ...]]:
    source_rows = _source_identity_rows_sql(source_paths, freq=freq)
    seed_rows = (
        _daily_seed_sql(previous_partition_path)
        if freq is None
        else _minute_seed_sql(previous_partition_path, freq)
    )
    rows = connection.execute(
        f"""
        WITH source_rows AS (
          {source_rows}
        ),
        target_codes AS (
          SELECT DISTINCT ts_code
          FROM source_rows
          WHERE trade_date = DATE {duckdb_string(partition_key)}
        ),
        prior_counts AS (
          SELECT ts_code, count(*) AS prior_count
          FROM source_rows
          WHERE trade_date < DATE {duckdb_string(partition_key)}
          GROUP BY ts_code
        ),
        seed_codes AS (
          SELECT DISTINCT ts_code FROM ({seed_rows})
        )
        SELECT
          target_codes.ts_code,
          coalesce(prior_counts.prior_count, 0) AS prior_count,
          seed_codes.ts_code IS NOT NULL AS has_seed
        FROM target_codes
        LEFT JOIN prior_counts USING (ts_code)
        LEFT JOIN seed_codes USING (ts_code)
        ORDER BY target_codes.ts_code
        """
    ).fetchall()
    source_row_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM ({source_rows})
            WHERE trade_date = DATE {duckdb_string(partition_key)}
            """
        ).fetchone()[0]
    )
    if source_row_count <= 0:
        raise ValueError(
            f"QFQ source has no rows for target partition {partition_key}."
        )
    candidates = tuple(
        str(code)
        for code, prior_count, has_seed in rows
        if int(prior_count or 0) < QFQ_NINETURN_COMPARISON_LAG or not bool(has_seed)
    )
    return source_row_count, candidates


def _fallback_codes_with_history(
    connection: duckdb.DuckDBPyConnection,
    *,
    history_paths: Sequence[Path],
    candidate_codes: Sequence[str],
    partition_key: str,
    freq: int | None,
) -> tuple[str, ...]:
    normalized_codes = _normalize_fallback_codes(candidate_codes)
    if not normalized_codes:
        return ()
    if not history_paths:
        raise FileNotFoundError("QFQ fallback source history is missing.")
    source_rows = _source_identity_rows_sql(history_paths, freq=freq)
    code_filter = _stock_code_filter_sql(normalized_codes, has_where=True)
    rows = connection.execute(
        f"""
        SELECT ts_code, count(*) AS prior_count
        FROM ({source_rows})
        WHERE trade_date < DATE {duckdb_string(partition_key)}
          {code_filter}
        GROUP BY ts_code
        HAVING count(*) >= {QFQ_NINETURN_COMPARISON_LAG}
        ORDER BY ts_code
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _source_identity_rows_sql(
    source_paths: Sequence[Path],
    *,
    freq: int | None,
) -> str:
    source = _read_parquet_paths(source_paths)
    if freq is None:
        return f"""
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(trade_date AS DATE) AS trade_date
        FROM {source}
        """
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS DATE) AS trade_date
    FROM {source}
    WHERE CAST(freq AS INTEGER) = {int(freq)}
    """


def _write_qfq_nineturn_partition(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
    partition_key: str,
    freq: int | None,
    select_sql: str,
    source_paths: Sequence[Path],
    fingerprint_source_paths: Sequence[Path] | None,
    source_row_count: int,
    fallback_recomputed_code_count: int,
    target_path: Path,
    staging_path: Path,
    schema: Sequence[ColumnContract],
) -> QfqNineturnPartitionWriteResult:
    if source_row_count <= 0:
        raise ValueError("QFQ nine-turn source row count must be positive.")
    if fallback_recomputed_code_count < 0:
        raise ValueError("QFQ nine-turn fallback code count must not be negative.")

    source_paths = tuple(Path(path) for path in source_paths)
    effective_fingerprint_paths = tuple(
        Path(path)
        for path in (
            fingerprint_source_paths
            if fingerprint_source_paths is not None
            else source_paths
        )
    )
    source_fingerprint = build_qfq_nineturn_source_fingerprint(
        lake_root=lake_root,
        source_paths=effective_fingerprint_paths,
    )
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    if staging_path.exists():
        staging_path.unlink()

    try:
        with duckdb_resource.connect() as connection:
            connection.execute(copy_query_to_parquet(select_sql, staging_path))
            observed_columns = _validate_qfq_nineturn_partition(
                connection=connection,
                path=staging_path,
                schema=schema,
                partition_key=partition_key,
                freq=freq,
                expected_row_count=source_row_count,
            )
            output_row_count, stock_code_count = connection.execute(
                f"""
                SELECT count(*), count(DISTINCT ts_code)
                FROM {read_parquet(staging_path, hive_partitioning=False)}
                """
            ).fetchone()

        final_fingerprint = build_qfq_nineturn_source_fingerprint(
            lake_root=lake_root,
            source_paths=effective_fingerprint_paths,
        )
        if final_fingerprint != source_fingerprint:
            raise RuntimeError(
                "QFQ nine-turn source files changed while the partition was written."
            )
        if fallback_recomputed_code_count > int(stock_code_count):
            raise ValueError(
                "QFQ nine-turn fallback code count exceeds output stock count: "
                f"fallback={fallback_recomputed_code_count}, output={stock_code_count}."
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_path, target_path)
        return QfqNineturnPartitionWriteResult(
            target_path=target_path,
            source_row_count=source_row_count,
            output_row_count=int(output_row_count),
            stock_code_count=int(stock_code_count),
            fallback_recomputed_code_count=fallback_recomputed_code_count,
            source_file_count=len(effective_fingerprint_paths),
            source_fingerprint=source_fingerprint,
            observed_columns=observed_columns,
        )
    finally:
        if staging_path.exists():
            staging_path.unlink()


def _validate_qfq_nineturn_partition(
    *,
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    schema: Sequence[ColumnContract],
    partition_key: str,
    freq: int | None,
    expected_row_count: int,
) -> tuple[str, ...]:
    observed_schema = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(
            describe_parquet_query(path, hive_partitioning=False)
        ).fetchall()
    )
    expected_schema = tuple((column.name, column.type.upper()) for column in schema)
    if observed_schema != expected_schema:
        raise ValueError(
            "QFQ nine-turn output schema mismatch: "
            f"expected={expected_schema}, observed={observed_schema}."
        )

    source = read_parquet(path, hive_partitioning=False)
    key_columns = "ts_code, trade_date" if freq is None else "ts_code, freq, trade_time"
    freq_mismatch_sql = (
        "0" if freq is None else f"count(*) FILTER (WHERE freq != {int(freq)})"
    )
    price_value_predicate = (
        "close_qfq IS NULL OR NOT isfinite(close_qfq) OR close_qfq <= 0 OR "
        if freq is None
        else ""
    )
    metrics = connection.execute(
        f"""
        SELECT
          count(*) AS row_count,
          count(*) - count(DISTINCT ({key_columns})) AS duplicate_key_count,
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
              {"" if freq is None else "OR freq IS NULL OR trade_time IS NULL"}
          ) AS null_key_count,
          count(*) FILTER (
            WHERE trade_date != DATE {duckdb_string(partition_key)}
          ) AS partition_mismatch_count,
          {freq_mismatch_sql} AS freq_mismatch_count,
          count(*) FILTER (
            WHERE {price_value_predicate}up_count IS NULL OR down_count IS NULL
              OR up_count < 0 OR down_count < 0
              OR (up_count > 0 AND down_count > 0)
              OR (nine_up_turn IS NOT NULL AND nine_up_turn != '+9')
              OR (nine_down_turn IS NOT NULL AND nine_down_turn != '-9')
              OR (nine_up_turn = '+9' AND up_count < {QFQ_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_down_turn = '-9' AND down_count < {QFQ_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
          ) AS invalid_value_count
        FROM {source}
        """
    ).fetchone()
    names = (
        "row_count",
        "duplicate_key_count",
        "null_key_count",
        "partition_mismatch_count",
        "freq_mismatch_count",
        "invalid_value_count",
    )
    values = dict(zip(names, (int(value or 0) for value in metrics), strict=True))
    if values["row_count"] != expected_row_count:
        raise ValueError(
            "QFQ nine-turn output row count must match source row count: "
            f"source={expected_row_count}, output={values['row_count']}."
        )
    failures = {
        name: value
        for name, value in values.items()
        if name != "row_count" and value > 0
    }
    if failures:
        raise ValueError(f"QFQ nine-turn output contract failed: {failures}.")
    return tuple(name for name, _data_type in observed_schema)


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    normalized_paths = tuple(Path(path) for path in paths)
    if not normalized_paths:
        raise ValueError("At least one QFQ source parquet path is required.")
    if len(normalized_paths) == 1:
        return read_parquet(normalized_paths[0], hive_partitioning=False)
    path_list = ", ".join(duckdb_string(path) for path in normalized_paths)
    return f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true)"
