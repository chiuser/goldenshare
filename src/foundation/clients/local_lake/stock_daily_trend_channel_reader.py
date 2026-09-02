from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any

from src.foundation.clients.local_lake.stock_daily_trend_channel_contract import (
    FORMAL_LAKE_ROOT,
    FORMULA_VERSION,
    MAX_TREND_CHANNEL_LIMIT,
    RESULT_COLUMN_SPECS,
    STOCK_TS_CODE_PATTERN,
    TRADE_DATE_PARTITION_PATTERN,
    stock_daily_trend_channel_dataset_root,
)


class StockDailyTrendChannelReaderError(RuntimeError):
    """Base error for the bounded local-Lake reader."""


class StockDailyTrendChannelRequestError(StockDailyTrendChannelReaderError):
    """Raised for an invalid stock trend-channel request."""


class StockDailyTrendChannelSourceNotReadyError(
    StockDailyTrendChannelReaderError
):
    """Raised when the selected formal result files are not safe to consume."""


class StockDailyTrendChannelReadError(StockDailyTrendChannelReaderError):
    """Raised when DuckDB cannot execute an otherwise valid bounded read."""


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelReadRequest:
    ts_code: str
    end_date: date | None
    limit: int


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelReadResult:
    rows: tuple[dict[str, Any], ...]
    observed_trade_date: date | None
    scanned_file_count: int
    elapsed_ms: float


class StockDailyTrendChannelLakeReader:
    def __init__(self, lake_root: Path) -> None:
        normalized_root = lake_root.expanduser().resolve()
        if normalized_root != FORMAL_LAKE_ROOT.resolve():
            raise StockDailyTrendChannelRequestError(
                "股票趋势通道 Reader 只允许正式 /Volumes/datasource/data_lake。"
            )
        self._lake_root = normalized_root
        self._connection: Any | None = None
        self._connection_lock = Lock()

    def read(
        self,
        request: StockDailyTrendChannelReadRequest,
    ) -> StockDailyTrendChannelReadResult:
        started = time.perf_counter()
        normalized = _normalize_request(request)
        partitions = _select_partition_files(self._lake_root, normalized)
        if not partitions:
            raise StockDailyTrendChannelSourceNotReadyError(
                "股票趋势通道正式分区尚未准备完成。"
            )

        paths = tuple(item.path for item in partitions)
        try:
            with self._connection_lock:
                connection = self._connection_for_read()
                _validate_file_schemas(connection, paths)
                rows = _query_rows(connection, paths, normalized)
            _validate_result_rows(rows, partitions, normalized)
        except StockDailyTrendChannelReaderError:
            raise
        except Exception as exc:
            raise StockDailyTrendChannelReadError(
                "股票趋势通道本地读取失败。"
            ) from exc

        return StockDailyTrendChannelReadResult(
            rows=tuple(rows),
            observed_trade_date=rows[-1]["trade_date"] if rows else None,
            scanned_file_count=len(paths),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def close(self) -> None:
        with self._connection_lock:
            if self._connection is None:
                return
            self._connection.close()
            self._connection = None

    def _connection_for_read(self) -> Any:
        if self._connection is not None:
            return self._connection
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - capability checks startup
            raise StockDailyTrendChannelReadError(
                "local-lake DuckDB 依赖不可用。"
            ) from exc
        connection = duckdb.connect(database=":memory:")
        connection.execute("SET memory_limit='256MB'")
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=false")
        self._connection = connection
        return connection


@dataclass(frozen=True, slots=True)
class _PartitionFile:
    trade_date: date
    path: Path


def _normalize_request(
    request: StockDailyTrendChannelReadRequest,
) -> StockDailyTrendChannelReadRequest:
    ts_code = request.ts_code.strip().upper()
    if not STOCK_TS_CODE_PATTERN.fullmatch(ts_code):
        raise StockDailyTrendChannelRequestError(
            "tsCode 必须是六位代码加 SH/SZ/BJ 后缀。"
        )
    if not 1 <= request.limit <= MAX_TREND_CHANNEL_LIMIT:
        raise StockDailyTrendChannelRequestError("limit 必须在 1 到 2000 之间。")
    return StockDailyTrendChannelReadRequest(
        ts_code=ts_code,
        end_date=request.end_date,
        limit=request.limit,
    )


def _select_partition_files(
    lake_root: Path,
    request: StockDailyTrendChannelReadRequest,
) -> tuple[_PartitionFile, ...]:
    dataset_root = stock_daily_trend_channel_dataset_root(lake_root)
    if not dataset_root.is_dir():
        return ()

    partition_directories: list[tuple[date, Path]] = []
    try:
        children = tuple(dataset_root.iterdir())
    except OSError as exc:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道正式目录不可读。"
        ) from exc
    for child in children:
        match = TRADE_DATE_PARTITION_PATTERN.fullmatch(child.name)
        if not match or not child.is_dir():
            continue
        try:
            trade_date = date.fromisoformat(match.group(1))
        except ValueError as exc:
            raise StockDailyTrendChannelSourceNotReadyError(
                f"股票趋势通道分区日期非法：{child.name}。"
            ) from exc
        if request.end_date is not None and trade_date > request.end_date:
            continue
        partition_directories.append((trade_date, child))

    partition_directories.sort(key=lambda item: item[0], reverse=True)
    candidates: list[_PartitionFile] = []
    for trade_date, child in partition_directories[: request.limit]:
        target = (child / "part-000.parquet").resolve()
        if not target.is_relative_to(dataset_root.resolve()) or not target.is_file():
            raise StockDailyTrendChannelSourceNotReadyError(
                f"股票趋势通道分区缺少唯一正式文件：{child.name}。"
            )
        extra_parquet = tuple(
            path for path in child.glob("*.parquet") if path.name != "part-000.parquet"
        )
        if extra_parquet:
            raise StockDailyTrendChannelSourceNotReadyError(
                f"股票趋势通道分区存在非合同文件：{child.name}。"
            )
        candidates.append(_PartitionFile(trade_date=trade_date, path=target))
    return tuple(candidates)


def _validate_file_schemas(connection: Any, paths: Sequence[Path]) -> None:
    try:
        schema_rows = connection.execute(
            """
            SELECT file_name, name, upper(duckdb_type)
            FROM parquet_schema(?)
            WHERE name != 'duckdb_schema'
            ORDER BY file_name, column_id
            """,
            [list(map(str, paths))],
        ).fetchall()
    except Exception as exc:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道 Parquet schema 无法读取。"
        ) from exc

    by_file: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for file_name, name, duckdb_type in schema_rows:
        by_file[str(Path(file_name).resolve())].append(
            (str(name), _normalize_duckdb_type(duckdb_type))
        )
    for path in paths:
        if tuple(by_file.get(str(path.resolve()), ())) != RESULT_COLUMN_SPECS:
            raise StockDailyTrendChannelSourceNotReadyError(
                f"股票趋势通道文件字段合同不一致：{path.parent.name}。"
            )


def _query_rows(
    connection: Any,
    paths: Sequence[Path],
    request: StockDailyTrendChannelReadRequest,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        WITH bounded AS (
          SELECT
            ts_code, trade_date, open, high, low, close,
            short_upper, short_lower, short_position, short_state,
            long_upper, long_lower, long_position, long_state,
            combined_state, formula_version, filename
          FROM read_parquet(?, filename=true)
          WHERE ts_code = ?
            AND (? IS NULL OR trade_date <= ?)
          ORDER BY trade_date DESC
          LIMIT ?
        )
        SELECT * FROM bounded ORDER BY trade_date ASC
        """,
        [
            list(map(str, paths)),
            request.ts_code,
            request.end_date,
            request.end_date,
            request.limit + 1,
        ],
    ).fetchall()
    columns = (
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "short_upper",
        "short_lower",
        "short_position",
        "short_state",
        "long_upper",
        "long_lower",
        "long_position",
        "long_state",
        "combined_state",
        "formula_version",
        "source_file",
    )
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _validate_result_rows(
    rows: Sequence[dict[str, Any]],
    partitions: Sequence[_PartitionFile],
    request: StockDailyTrendChannelReadRequest,
) -> None:
    if len(rows) > request.limit:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道日期唯一性合同失效。"
        )
    expected_paths = {item.path.resolve(): item.trade_date for item in partitions}
    previous_date: date | None = None
    seen_dates: set[date] = set()
    for row in rows:
        trade_date = row["trade_date"]
        source_file = _resolve_source_file(row.pop("source_file", None))
        if row["ts_code"] != request.ts_code:
            raise StockDailyTrendChannelSourceNotReadyError(
                "股票趋势通道返回了其他股票的数据。"
            )
        if row["formula_version"] != FORMULA_VERSION:
            raise StockDailyTrendChannelSourceNotReadyError(
                "股票趋势通道公式版本不符合当前合同。"
            )
        if source_file not in expected_paths or expected_paths[source_file] != trade_date:
            raise StockDailyTrendChannelSourceNotReadyError(
                "股票趋势通道分区日期与文件内容不一致。"
            )
        if trade_date in seen_dates or (
            previous_date is not None and trade_date <= previous_date
        ):
            raise StockDailyTrendChannelSourceNotReadyError(
                "股票趋势通道日期必须唯一且严格升序。"
            )
        _validate_values(row)
        seen_dates.add(trade_date)
        previous_date = trade_date


def _resolve_source_file(raw_value: object) -> Path:
    if not isinstance(raw_value, str) or not raw_value:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道返回行缺少来源文件。"
        )
    try:
        return Path(raw_value).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道返回行的来源文件非法。"
        ) from exc


def _validate_values(row: dict[str, Any]) -> None:
    numeric_fields = (
        "open",
        "high",
        "low",
        "close",
        "short_upper",
        "short_lower",
        "long_upper",
        "long_lower",
    )
    try:
        values_are_finite = all(
            math.isfinite(float(row[field])) for field in numeric_fields
        )
    except (TypeError, ValueError) as exc:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道包含非法数值。"
        ) from exc
    if not values_are_finite:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道包含非有限数值。"
        )
    if row["short_upper"] < row["short_lower"] or row["long_upper"] < row["long_lower"]:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道上下轨顺序非法。"
        )
    if row["short_position"] not in {"ABOVE", "INSIDE", "BELOW"} or row[
        "long_position"
    ] not in {"ABOVE", "INSIDE", "BELOW"}:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道位置枚举非法。"
        )
    if row["short_state"] not in {"UNKNOWN", "UP", "DOWN"} or row[
        "long_state"
    ] not in {"UNKNOWN", "UP", "DOWN"}:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道状态枚举非法。"
        )
    if row["combined_state"] not in {
        "UNKNOWN",
        "UP_UP",
        "UP_DOWN",
        "DOWN_UP",
        "DOWN_DOWN",
    }:
        raise StockDailyTrendChannelSourceNotReadyError(
            "股票趋势通道组合状态非法。"
        )


def _normalize_duckdb_type(value: object) -> str:
    normalized = str(value).upper()
    if normalized.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    if normalized in {"TEXT", "STRING"}:
        return "VARCHAR"
    return normalized
