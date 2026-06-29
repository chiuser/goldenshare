from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string, read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.stock_daily_qfq import (
    GoldStockDailyQfqPartitionWriteResult,
    load_stock_daily_qfq_previous_lookup_trade_dates,
    write_gold_stock_daily_qfq_partition,
)


TRADE_DATE_PARTITION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GOLD_STOCK_DAILY_QFQ_HISTORY_SAMPLE_SIZE = 3
GOLD_STOCK_DAILY_QFQ_HISTORY_SAMPLE_LIMIT = 20


@dataclass(frozen=True, slots=True)
class GoldStockDailyQfqHistoryPlan:
    bootstrap_as_of_trade_date: str
    as_of_adj_factor_file_path: str
    as_of_adj_factor_file_exists: bool
    selected_partition_keys: tuple[str, ...]
    expected_trade_date_count: int
    silver_stock_daily_partition_count: int
    silver_adj_factor_partition_count: int
    complete_input_partition_count: int
    existing_target_file_count: int
    planned_write_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    sample_partition_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GoldStockDailyQfqHistoryWriteReport:
    bootstrap_as_of_trade_date: str
    as_of_adj_factor_file_path: str
    selected_partition_keys: tuple[str, ...]
    written_partition_keys: tuple[str, ...]
    skipped_existing_partition_keys: tuple[str, ...]
    write_results: tuple[GoldStockDailyQfqPartitionWriteResult, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "bootstrap_as_of_trade_date": self.bootstrap_as_of_trade_date,
            "as_of_adj_factor_file_path": self.as_of_adj_factor_file_path,
            "selected_partition_keys": list(self.selected_partition_keys),
            "written_partition_keys": list(self.written_partition_keys),
            "skipped_existing_partition_keys": list(
                self.skipped_existing_partition_keys
            ),
            "write_results": [
                {
                    "path": str(result.path),
                    "stock_daily_file_path": str(result.stock_daily_file_path),
                    "trade_adj_factor_file_path": str(
                        result.trade_adj_factor_file_path
                    ),
                    "as_of_adj_factor_file_path": str(result.as_of_adj_factor_file_path),
                    "previous_lookup_trade_date_count": (
                        result.previous_lookup_trade_date_count
                    ),
                    "previous_stock_daily_file_count": (
                        result.previous_stock_daily_file_count
                    ),
                    "previous_adj_factor_file_count": (
                        result.previous_adj_factor_file_count
                    ),
                    "source_row_count": result.source_row_count,
                    "output_row_count": result.output_row_count,
                    "missing_previous_row_count": result.missing_previous_row_count,
                    "observed_columns": list(result.observed_columns),
                }
                for result in self.write_results
            ],
            "elapsed_ms": self.elapsed_ms,
        }


def discover_gold_stock_daily_qfq_partitions(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> tuple[str, ...]:
    target_root = Path(lake_root) / "gold" / "quote" / "stock_daily_qfq"
    return _discover_trade_date_partitions(target_root)


def discover_silver_stock_daily_partitions_for_qfq(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> tuple[str, ...]:
    source_root = Path(lake_root) / "silver" / "quote" / "stock_daily"
    return _discover_trade_date_partitions(source_root)


def discover_silver_adj_factor_partitions_for_stock_daily_qfq(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> tuple[str, ...]:
    source_root = Path(lake_root) / "silver" / "quote" / "adj_factor"
    return _discover_trade_date_partitions(source_root)


def load_gold_stock_daily_qfq_expected_trade_dates(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    start_date: str,
    end_date: str | None = None,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    normalized_start = _normalize_trade_date(start_date, field_name="start_date")
    normalized_end = (
        _normalize_trade_date(end_date, field_name="end_date")
        if end_date is not None
        else None
    )
    end_date_filter = (
        ""
        if normalized_end is None
        else f"AND CAST(trade_date AS DATE) <= DATE {duckdb_string(normalized_end)}"
    )
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS trade_date
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE CAST(exchange AS VARCHAR) = 'SSE'
              AND CAST(is_open AS BOOLEAN)
              AND CAST(trade_date AS DATE) >= DATE {duckdb_string(normalized_start)}
              {end_date_filter}
            ORDER BY CAST(trade_date AS DATE)
            """
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def plan_gold_stock_daily_qfq_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    as_of_trade_date: str,
    partition_keys: Sequence[str] | None = None,
    start_date: str = "2014-01-01",
    end_date: str | None = None,
    skip_existing: bool = True,
) -> GoldStockDailyQfqHistoryPlan:
    normalized_as_of_trade_date = _normalize_trade_date(
        as_of_trade_date,
        field_name="as_of_trade_date",
    )
    as_of_adj_factor_path = silver_adj_factor_path(
        lake_root,
        normalized_as_of_trade_date,
    )
    expected_trade_dates = load_gold_stock_daily_qfq_expected_trade_dates(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        start_date=start_date,
        end_date=end_date,
    )
    silver_stock_daily_partitions = set(
        discover_silver_stock_daily_partitions_for_qfq(lake_root)
    )
    silver_adj_factor_partitions = set(
        discover_silver_adj_factor_partitions_for_stock_daily_qfq(lake_root)
    )
    complete_input_partitions = tuple(
        trade_date
        for trade_date in expected_trade_dates
        if trade_date in silver_stock_daily_partitions
        and trade_date in silver_adj_factor_partitions
    )
    selected_partition_keys = _select_partition_keys(
        complete_input_partitions,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
    )
    existing_target_partitions = set(discover_gold_stock_daily_qfq_partitions(lake_root))
    missing_input_samples = _missing_input_samples(lake_root, selected_partition_keys)
    planned_write_count = sum(
        1
        for partition_key in selected_partition_keys
        if not skip_existing or partition_key not in existing_target_partitions
    )
    return GoldStockDailyQfqHistoryPlan(
        bootstrap_as_of_trade_date=normalized_as_of_trade_date,
        as_of_adj_factor_file_path=str(as_of_adj_factor_path),
        as_of_adj_factor_file_exists=as_of_adj_factor_path.exists(),
        selected_partition_keys=selected_partition_keys,
        expected_trade_date_count=len(expected_trade_dates),
        silver_stock_daily_partition_count=len(silver_stock_daily_partitions),
        silver_adj_factor_partition_count=len(silver_adj_factor_partitions),
        complete_input_partition_count=len(complete_input_partitions),
        existing_target_file_count=sum(
            1
            for partition_key in selected_partition_keys
            if partition_key in existing_target_partitions
        ),
        planned_write_count=planned_write_count,
        missing_input_count=len(missing_input_samples),
        missing_input_samples=tuple(
            missing_input_samples[:GOLD_STOCK_DAILY_QFQ_HISTORY_SAMPLE_LIMIT]
        ),
        sample_partition_keys=_sample_partition_keys(selected_partition_keys),
    )


def generate_gold_stock_daily_qfq_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str],
    as_of_trade_date: str,
    skip_existing: bool = True,
    overwrite: bool = False,
) -> GoldStockDailyQfqHistoryWriteReport:
    normalized_as_of_trade_date = _normalize_trade_date(
        as_of_trade_date,
        field_name="as_of_trade_date",
    )
    as_of_adj_factor_path = silver_adj_factor_path(
        lake_root,
        normalized_as_of_trade_date,
    )
    if not as_of_adj_factor_path.exists():
        raise FileNotFoundError(
            f"silver as-of adj factor file is missing: {as_of_adj_factor_path}"
        )
    selected_partition_keys = tuple(sorted(set(partition_keys)))
    if not selected_partition_keys:
        raise ValueError("At least one gold stock daily qfq partition key is required.")
    missing_input_samples = _missing_input_samples(lake_root, selected_partition_keys)
    if missing_input_samples:
        raise FileNotFoundError(
            "gold stock daily qfq history inputs are missing: "
            f"{tuple(missing_input_samples[:GOLD_STOCK_DAILY_QFQ_HISTORY_SAMPLE_LIMIT])}"
        )

    started_at = perf_counter()
    written: list[str] = []
    skipped: list[str] = []
    write_results: list[GoldStockDailyQfqPartitionWriteResult] = []
    with duckdb_resource.connect() as connection:
        with TemporaryDirectory(prefix="gold_stock_daily_qfq_as_of_") as temp_dir:
            effective_as_of_adj_factor_path = (
                _write_effective_as_of_adj_factor_snapshot(
                    connection=connection,
                    lake_root=lake_root,
                    as_of_trade_date=normalized_as_of_trade_date,
                    temp_dir=Path(temp_dir),
                )
            )
            for partition_key in selected_partition_keys:
                target_path = gold_stock_daily_qfq_path(lake_root, partition_key)
                if target_path.exists() and skip_existing and not overwrite:
                    skipped.append(partition_key)
                    continue
                if target_path.exists() and not overwrite and not skip_existing:
                    raise FileExistsError(
                        "gold stock daily qfq target already exists; use overwrite "
                        f"or skip_existing: {target_path}"
                    )
                previous_lookup_trade_dates = (
                    load_stock_daily_qfq_previous_lookup_trade_dates(
                        connection=connection,
                        lake_root=lake_root,
                        trade_date=partition_key,
                    )
                )
                result = write_gold_stock_daily_qfq_partition(
                    connection=connection,
                    lake_root=lake_root,
                    trade_date=partition_key,
                    previous_lookup_trade_dates=previous_lookup_trade_dates,
                    as_of_trade_date=normalized_as_of_trade_date,
                    as_of_adj_factor_path=effective_as_of_adj_factor_path,
                )
                written.append(partition_key)
                write_results.append(result)

    return GoldStockDailyQfqHistoryWriteReport(
        bootstrap_as_of_trade_date=normalized_as_of_trade_date,
        as_of_adj_factor_file_path=str(as_of_adj_factor_path),
        selected_partition_keys=selected_partition_keys,
        written_partition_keys=tuple(written),
        skipped_existing_partition_keys=tuple(skipped),
        write_results=tuple(write_results),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def _write_effective_as_of_adj_factor_snapshot(
    *,
    connection,
    lake_root: Path,
    as_of_trade_date: str,
    temp_dir: Path,
) -> Path:
    source_pattern = (
        lake_root / "silver" / "quote" / "adj_factor" / "trade_date=*" / "part-000.parquet"
    )
    target_path = temp_dir / f"effective_as_of_adj_factor_{as_of_trade_date}.parquet"
    as_of_date_sql = f"DATE {duckdb_string(as_of_trade_date)}"
    source_sql = read_parquet(source_pattern, hive_partitioning=False)
    select_sql = f"""
WITH ranked_factors AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS source_trade_date,
    CAST(adj_factor AS DOUBLE) AS adj_factor,
    row_number() OVER (
      PARTITION BY CAST(ts_code AS VARCHAR)
      ORDER BY CAST(trade_date AS DATE) DESC
    ) AS row_number
  FROM {source_sql}
  WHERE CAST(trade_date AS DATE) <= {as_of_date_sql}
)
SELECT
  ts_code,
  {as_of_date_sql} AS trade_date,
  adj_factor
FROM ranked_factors
WHERE row_number = 1
ORDER BY ts_code
"""
    connection.execute(copy_query_to_parquet(select_sql, target_path))
    row_count = connection.execute(
        f"SELECT count(*) FROM {read_parquet(target_path, hive_partitioning=False)}"
    ).fetchone()[0]
    if int(row_count) <= 0:
        raise ValueError(
            "effective stock daily qfq as-of adj factor snapshot has no rows: "
            f"as_of_trade_date={as_of_trade_date}"
        )
    return target_path


def _discover_trade_date_partitions(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    return tuple(
        sorted(
            partition_key
            for partition_key in (
                path.parent.name.removeprefix("trade_date=")
                for path in root.glob("trade_date=*/part-000.parquet")
                if path.is_file()
            )
            if TRADE_DATE_PARTITION_PATTERN.match(partition_key)
        )
    )


def _select_partition_keys(
    complete_input_partitions: Sequence[str],
    *,
    partition_keys: Sequence[str] | None,
    start_date: str,
    end_date: str | None,
) -> tuple[str, ...]:
    complete = tuple(complete_input_partitions)
    if partition_keys is not None:
        requested = tuple(
            sorted(
                {
                    _normalize_trade_date(partition_key, field_name="partition_key")
                    for partition_key in partition_keys
                }
            )
        )
        missing = tuple(
            partition_key for partition_key in requested if partition_key not in complete
        )
        if missing:
            raise ValueError(
                "Requested gold stock daily qfq partitions are missing complete "
                f"silver inputs: {missing}"
            )
        return requested
    normalized_start = _normalize_trade_date(start_date, field_name="start_date")
    normalized_end = (
        _normalize_trade_date(end_date, field_name="end_date")
        if end_date is not None
        else None
    )
    return tuple(
        partition_key
        for partition_key in complete
        if partition_key >= normalized_start
        and (normalized_end is None or partition_key <= normalized_end)
    )


def _missing_input_samples(
    lake_root: Path,
    partition_keys: Sequence[str],
) -> list[str]:
    missing = []
    for partition_key in partition_keys:
        for input_path, label in (
            (silver_stock_daily_path(lake_root, partition_key), "silver_stock_daily"),
            (silver_adj_factor_path(lake_root, partition_key), "silver_adj_factor"),
        ):
            if not input_path.exists():
                missing.append(f"{partition_key}:{label}:{input_path}")
    return missing


def _sample_partition_keys(partition_keys: Sequence[str]) -> tuple[str, ...]:
    if not partition_keys:
        return ()
    ordered = tuple(partition_keys)
    samples = (
        ordered[0],
        ordered[len(ordered) // 2],
        ordered[-1],
    )
    return tuple(dict.fromkeys(samples))[:GOLD_STOCK_DAILY_QFQ_HISTORY_SAMPLE_SIZE]


def _normalize_trade_date(value: str | None, *, field_name: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError(f"{field_name} is required.")
    try:
        if len(raw_value) != 10:
            raise ValueError
        return date.fromisoformat(raw_value).isoformat()
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from error
