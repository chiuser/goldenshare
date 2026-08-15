from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from src.foundation.clients.local_lake.nine_turn_minute_contract import (
    decode_nine_turn_minute_cursor,
    encode_nine_turn_minute_cursor,
    existing_safe_partition_paths,
)
from src.foundation.clients.local_lake.stock_nine_turn_contract import (
    BAR_COLUMN_SPECS,
    FORMAL_LAKE_ROOT,
    MAX_NINE_TURN_LIMIT,
    MAX_NINE_TURN_PARTITION_FILES,
    NINE_TURN_COLUMN_SPECS,
    STOCK_TS_CODE_PATTERN,
    SUPPORTED_STOCK_NINE_TURN_FREQS,
    stock_minute_bar_dataset_root,
    stock_minute_nine_turn_dataset_root,
)


class StockNineTurnReaderError(RuntimeError):
    code = "NT_QUERY_FAILED"


class StockNineTurnRequestError(StockNineTurnReaderError):
    code = "NT_REQUEST_INVALID"


class StockNineTurnSourceContractError(StockNineTurnReaderError):
    code = "NT_SOURCE_CONTRACT_INVALID"


class StockNineTurnQueryError(StockNineTurnReaderError):
    code = "NT_QUERY_FAILED"


@dataclass(frozen=True, slots=True)
class StockNineTurnReadRequest:
    ts_code: str
    freq: int
    start_date: date | None
    end_date: date | None
    limit: int
    cursor: str | None


@dataclass(frozen=True, slots=True)
class StockNineTurnReadPage:
    rows: tuple[dict[str, Any], ...]
    source_row_count: int
    matched_row_count: int
    missing_row_count: int
    has_more: bool
    next_cursor: str | None
    observed_start_date: date | None
    observed_end_date: date | None
    scanned_file_count: int
    elapsed_ms: float


class StockNineTurnLakeReader:
    def __init__(self, lake_root: Path) -> None:
        normalized_root = lake_root.expanduser().resolve()
        if normalized_root != FORMAL_LAKE_ROOT.resolve():
            raise StockNineTurnRequestError(
                "股票九转分钟 Reader 只允许正式 /Volumes/datasource/data_lake。"
            )
        self._lake_root = normalized_root
        self._connection: Any | None = None
        self._connection_lock = Lock()

    def read(self, request: StockNineTurnReadRequest) -> StockNineTurnReadPage:
        started = time.perf_counter()
        normalized, cursor = _normalize_request(request)
        bar_paths = _bar_paths(self._lake_root, normalized)
        if not bar_paths:
            return _empty_page(started)

        with self._connection_lock:
            connection = self._connection_for_read()
            try:
                _validate_files(connection, bar_paths, BAR_COLUMN_SPECS)
                _validate_bar_contract(connection, bar_paths, normalized)
                bar_rows = _query_rows(
                    connection,
                    bar_paths=bar_paths,
                    nine_turn_paths=(),
                    request=normalized,
                    cursor=cursor,
                )
                nine_turn_paths = _nine_turn_paths(
                    self._lake_root,
                    normalized,
                    trade_dates={row["trade_date"] for row in bar_rows},
                )
                scanned_file_count = len(bar_paths) + len(nine_turn_paths)
                if scanned_file_count > MAX_NINE_TURN_PARTITION_FILES:
                    raise StockNineTurnRequestError(
                        "查询将扫描超过 5000 个分区文件，请缩小日期窗口。"
                    )
                if nine_turn_paths:
                    _validate_files(
                        connection,
                        nine_turn_paths,
                        NINE_TURN_COLUMN_SPECS,
                    )
                    _validate_nine_turn_contract(
                        connection,
                        nine_turn_paths,
                        normalized,
                    )
                    rows = _query_rows(
                        connection,
                        bar_paths=bar_paths,
                        nine_turn_paths=nine_turn_paths,
                        request=normalized,
                        cursor=cursor,
                    )
                else:
                    rows = bar_rows
            except StockNineTurnReaderError:
                raise
            except Exception as exc:
                raise StockNineTurnQueryError("股票九转分钟查询失败。") from exc

        has_more = len(rows) > normalized.limit
        page_rows = rows[: normalized.limit]
        page_rows.reverse()
        _validate_result_rows(page_rows, normalized)
        next_cursor = None
        if has_more and page_rows:
            first = page_rows[0]
            next_cursor = encode_nine_turn_minute_cursor(
                dataset="stock_minute_nine_turn",
                subject_type="stock",
                ts_code=normalized.ts_code,
                freq=normalized.freq,
                start_date=normalized.start_date,
                end_date=normalized.end_date,
                before_trade_date=first["trade_date"],
                before_trade_time=first["trade_time"],
            )

        matched_rows = [row for row in page_rows if row["nine_turn_matched"]]
        observed_dates = [row["trade_date"] for row in matched_rows]
        return StockNineTurnReadPage(
            rows=tuple(page_rows),
            source_row_count=len(page_rows),
            matched_row_count=len(matched_rows),
            missing_row_count=len(page_rows) - len(matched_rows),
            has_more=has_more,
            next_cursor=next_cursor,
            observed_start_date=min(observed_dates) if observed_dates else None,
            observed_end_date=max(observed_dates) if observed_dates else None,
            scanned_file_count=scanned_file_count,
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
        except ImportError as exc:  # pragma: no cover - capability gate covers startup
            raise StockNineTurnQueryError("local-lake DuckDB 依赖不可用。") from exc
        connection = duckdb.connect(database=":memory:")
        connection.execute("SET memory_limit='256MB'")
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=false")
        self._connection = connection
        return connection


def _normalize_request(
    request: StockNineTurnReadRequest,
) -> tuple[StockNineTurnReadRequest, dict[str, Any] | None]:
    ts_code = request.ts_code.strip().upper()
    if not STOCK_TS_CODE_PATTERN.fullmatch(ts_code):
        raise StockNineTurnRequestError("tsCode 必须是六位代码加 SH/SZ/BJ 后缀。")
    try:
        freq = int(request.freq)
    except (TypeError, ValueError) as exc:
        raise StockNineTurnRequestError("freq 必须是整数分钟频率。") from exc
    if freq not in SUPPORTED_STOCK_NINE_TURN_FREQS:
        raise StockNineTurnRequestError("股票九转 freq 只允许 30/60/90/120。")
    if not 1 <= request.limit <= MAX_NINE_TURN_LIMIT:
        raise StockNineTurnRequestError("limit 必须在 1 到 10000 之间。")
    if (
        request.start_date is not None
        and request.end_date is not None
        and request.start_date > request.end_date
    ):
        raise StockNineTurnRequestError("startDate 不能晚于 endDate。")
    effective_end = request.end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    effective_start = request.start_date or date(effective_end.year - 2, 1, 1)
    if effective_end.year - effective_start.year > 2:
        raise StockNineTurnRequestError("股票九转分钟查询最多允许涉及 3 个自然年。")

    normalized = StockNineTurnReadRequest(
        ts_code=ts_code,
        freq=freq,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        cursor=request.cursor,
    )
    try:
        cursor = decode_nine_turn_minute_cursor(
            request.cursor,
            dataset="stock_minute_nine_turn",
            subject_type="stock",
            ts_code=ts_code,
            freq=freq,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except ValueError as exc:
        raise StockNineTurnRequestError(str(exc)) from exc
    return normalized, cursor


def _bar_paths(
    lake_root: Path,
    request: StockNineTurnReadRequest,
) -> tuple[Path, ...]:
    effective_end = request.end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    effective_start = request.start_date or date(effective_end.year - 2, 1, 1)
    frequency_root = (
        stock_minute_bar_dataset_root(lake_root)
        / f"freq={request.freq}"
        / f"ts_code={request.ts_code}"
    )
    paths = [
        frequency_root / f"year={year}" / "part-000.parquet"
        for year in range(effective_start.year, effective_end.year + 1)
    ]
    try:
        return existing_safe_partition_paths(
            lake_root=lake_root,
            dataset_root=stock_minute_bar_dataset_root(lake_root),
            candidates=paths,
        )
    except ValueError as exc:
        raise StockNineTurnSourceContractError(str(exc)) from exc


def _nine_turn_paths(
    lake_root: Path,
    request: StockNineTurnReadRequest,
    *,
    trade_dates: set[date],
) -> tuple[Path, ...]:
    frequency_root = (
        stock_minute_nine_turn_dataset_root(lake_root) / f"freq={request.freq}"
    )
    if not frequency_root.is_dir() or not trade_dates:
        return ()
    candidates = [
        frequency_root / f"trade_date={trade_date.isoformat()}" / "part-000.parquet"
        for trade_date in sorted(trade_dates)
    ]
    try:
        return existing_safe_partition_paths(
            lake_root=lake_root,
            dataset_root=stock_minute_nine_turn_dataset_root(lake_root),
            candidates=candidates,
        )
    except ValueError as exc:
        raise StockNineTurnSourceContractError(str(exc)) from exc


def _validate_files(
    connection: Any,
    paths: Sequence[Path],
    specs: Sequence[tuple[str, str]],
) -> None:
    if not paths:
        return
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
        raise StockNineTurnSourceContractError(
            "股票九转分钟文件 schema 不符合合同。"
        ) from exc
    by_file: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for file_name, name, duckdb_type in schema_rows:
        by_file[str(Path(file_name).resolve())].append(
            (str(name), _normalize_duckdb_type(duckdb_type))
        )
    expected = tuple(specs)
    expected_names = {name for name, _type in expected}
    exact = expected == NINE_TURN_COLUMN_SPECS
    for path in paths:
        observed_all = tuple(by_file.get(str(path.resolve()), ()))
        observed = (
            observed_all
            if exact
            else tuple(item for item in observed_all if item[0] in expected_names)
        )
        if observed != expected:
            raise StockNineTurnSourceContractError(
                f"股票九转分钟文件字段合同不一致：{path.name}。"
            )


def _normalize_duckdb_type(value: object) -> str:
    normalized = str(value).upper()
    if normalized.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    if normalized in {"TEXT", "STRING"}:
        return "VARCHAR"
    return normalized


def _validate_bar_contract(
    connection: Any,
    paths: Sequence[Path],
    request: StockNineTurnReadRequest,
) -> None:
    invalid_count, duplicate_count = connection.execute(
        """
        WITH source AS (
          SELECT ts_code, freq, trade_date, trade_time, filename
          FROM read_parquet(?, filename=true, hive_partitioning=false)
        )
        SELECT
          count(*) FILTER (
            WHERE ts_code != ? OR freq != ?
              OR trade_date != CAST(trade_time AS DATE)
              OR year(trade_date) != CAST(
                regexp_extract(filename, 'year=([0-9]{4})', 1) AS INTEGER
              )
          ),
          count(*) - count(DISTINCT (ts_code, freq, trade_time))
        FROM source
        """,
        [list(map(str, paths)), request.ts_code, request.freq],
    ).fetchone()
    if int(invalid_count or 0):
        raise StockNineTurnSourceContractError(
            "股票分钟 K 线存在代码、频率或日期分区合同错误。"
        )
    if int(duplicate_count or 0):
        raise StockNineTurnSourceContractError("股票分钟 K 线存在重复时间键。")


def _validate_nine_turn_contract(
    connection: Any,
    paths: Sequence[Path],
    request: StockNineTurnReadRequest,
) -> None:
    invalid_count, duplicate_count = connection.execute(
        """
        WITH source AS (
          SELECT ts_code, freq, trade_date, trade_time,
                 up_count, down_count, nine_up_turn, nine_down_turn, filename
          FROM read_parquet(?, filename=true, hive_partitioning=false)
          WHERE ts_code = ?
        )
        SELECT
          count(*) FILTER (
            WHERE freq != ?
              OR NOT regexp_full_match(ts_code, '^[0-9]{6}\\.(SH|SZ|BJ)$')
              OR trade_date != CAST(trade_time AS DATE)
              OR trade_date != CAST(
                regexp_extract(filename, 'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1)
                AS DATE
              )
              OR up_count IS NULL OR down_count IS NULL
              OR up_count < 0 OR down_count < 0
              OR (up_count > 0 AND down_count > 0)
              OR (nine_up_turn IS NOT NULL AND nine_up_turn != '+9')
              OR (nine_down_turn IS NOT NULL AND nine_down_turn != '-9')
              OR (nine_up_turn = '+9' AND up_count < 9)
              OR (nine_down_turn = '-9' AND down_count < 9)
              OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
          ),
          count(*) - count(DISTINCT (ts_code, freq, trade_time))
        FROM source
        """,
        [list(map(str, paths)), request.ts_code, request.freq],
    ).fetchone()
    if int(invalid_count or 0):
        raise StockNineTurnSourceContractError(
            "股票九转分钟文件存在身份、分区或值域合同错误。"
        )
    if int(duplicate_count or 0):
        raise StockNineTurnSourceContractError("股票九转分钟文件存在重复时间键。")


def _query_rows(
    connection: Any,
    *,
    bar_paths: Sequence[Path],
    nine_turn_paths: Sequence[Path],
    request: StockNineTurnReadRequest,
    cursor: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    predicates = ["ts_code = ?", "freq = ?"]
    parameters: list[Any] = [list(map(str, bar_paths)), request.ts_code, request.freq]
    if request.start_date is not None:
        predicates.append("trade_date >= ?")
        parameters.append(request.start_date)
    if request.end_date is not None:
        predicates.append("trade_date <= ?")
        parameters.append(request.end_date)
    if cursor is not None:
        predicates.append(
            "(trade_date < CAST(? AS DATE) OR "
            "(trade_date = CAST(? AS DATE) AND trade_time < CAST(? AS TIMESTAMP)))"
        )
        parameters.extend(
            [
                cursor["beforeTradeDate"],
                cursor["beforeTradeDate"],
                f"{cursor['beforeTradeDate']} {cursor['beforeTradeTime']}",
            ]
        )
    parameters.append(request.limit + 1)

    bars_cte = f"""
        SELECT ts_code, freq, trade_date, trade_time
        FROM read_parquet(?, hive_partitioning=false)
        WHERE {" AND ".join(predicates)}
        ORDER BY trade_date DESC, trade_time DESC
        LIMIT ?
    """
    if nine_turn_paths:
        sql = f"""
            WITH bars AS ({bars_cte}),
            nine_turn AS (
              SELECT ts_code, freq, trade_date, trade_time,
                     up_count, down_count, nine_up_turn, nine_down_turn
              FROM read_parquet(?, hive_partitioning=false)
              WHERE ts_code = ? AND freq = ?
            )
            SELECT b.ts_code, b.freq, b.trade_date, b.trade_time,
                   n.up_count, n.down_count,
                   n.nine_up_turn, n.nine_down_turn,
                   n.ts_code IS NOT NULL AS nine_turn_matched
            FROM bars b
            LEFT JOIN nine_turn n
              ON n.ts_code = b.ts_code AND n.freq = b.freq
             AND n.trade_date = b.trade_date AND n.trade_time = b.trade_time
            ORDER BY b.trade_date DESC, b.trade_time DESC
        """
        parameters.extend(
            [list(map(str, nine_turn_paths)), request.ts_code, request.freq]
        )
    else:
        sql = f"""
            WITH bars AS ({bars_cte})
            SELECT ts_code, freq, trade_date, trade_time,
                   NULL::INTEGER AS up_count, NULL::INTEGER AS down_count,
                   NULL::VARCHAR AS nine_up_turn,
                   NULL::VARCHAR AS nine_down_turn, FALSE AS nine_turn_matched
            FROM bars
            ORDER BY trade_date DESC, trade_time DESC
        """
    try:
        result = connection.execute(sql, parameters)
        names = [item[0] for item in result.description]
        return [dict(zip(names, row, strict=True)) for row in result.fetchall()]
    except Exception as exc:
        raise StockNineTurnQueryError("股票九转分钟查询失败。") from exc


def _validate_result_rows(
    rows: Sequence[dict[str, Any]],
    request: StockNineTurnReadRequest,
) -> None:
    keys: set[tuple[str, int, datetime]] = set()
    previous: tuple[date, datetime] | None = None
    for row in rows:
        if row["ts_code"] != request.ts_code or int(row["freq"]) != request.freq:
            raise StockNineTurnSourceContractError("股票九转分钟结果身份不一致。")
        if row["trade_time"].date() != row["trade_date"]:
            raise StockNineTurnSourceContractError("trade_time 不属于 trade_date。")
        key = (row["ts_code"], int(row["freq"]), row["trade_time"])
        if key in keys:
            raise StockNineTurnSourceContractError("股票九转分钟时间键重复。")
        keys.add(key)
        current = (row["trade_date"], row["trade_time"])
        if previous is not None and current <= previous:
            raise StockNineTurnSourceContractError("股票九转分钟结果未严格升序。")
        previous = current


def _empty_page(started: float) -> StockNineTurnReadPage:
    return StockNineTurnReadPage(
        rows=(),
        source_row_count=0,
        matched_row_count=0,
        missing_row_count=0,
        has_more=False,
        next_cursor=None,
        observed_start_date=None,
        observed_end_date=None,
        scanned_file_count=0,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
