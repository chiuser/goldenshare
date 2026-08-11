from __future__ import annotations

import base64
import binascii
import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as clock_time
from pathlib import Path
from typing import Any

from src.foundation.clients.local_lake.major_index_mins_contract import (
    EXPECTED_BARS_PER_SESSION,
    GOLD_INDICATOR_COLUMN_SPECS,
    GOLD_INDICATOR_VERSION,
    GOLD_PARAMS_KEY,
    INDEX_MINUTE_CURSOR_VERSION,
    INDEX_TS_CODE_PATTERN,
    MAX_INDEX_MINUTE_LIMIT,
    MAX_INDEX_MINUTE_PARTITION_FILES,
    SILVER_BAR_COLUMN_SPECS,
    SILVER_FREQ_VALUES,
    SUPPORTED_INDEX_MINUTE_FREQS,
    TRADE_DATE_PARTITION_PATTERN,
    IndexMinuteDataset,
    major_index_minute_frequency_root,
)


class IndexMinuteReaderError(RuntimeError):
    code = "IM_QUERY_FAILED"


class IndexMinuteRequestError(IndexMinuteReaderError):
    code = "ID_REQUEST_INVALID"


class IndexMinuteSourceContractError(IndexMinuteReaderError):
    code = "IM_SOURCE_CONTRACT_INVALID"


class IndexMinuteQueryError(IndexMinuteReaderError):
    code = "IM_QUERY_FAILED"


@dataclass(frozen=True, slots=True)
class IndexMinuteReadRequest:
    ts_code: str
    freq: int
    start_date: date | None
    end_date: date | None
    limit: int
    cursor: str | None


@dataclass(frozen=True, slots=True)
class IndexMinuteReadPage:
    rows: tuple[dict[str, Any], ...]
    count: int
    has_more: bool
    next_cursor: str | None
    observed_start_date: date | None
    observed_end_date: date | None
    scanned_file_count: int
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class _PartitionFile:
    trade_date: date
    path: Path


class MajorIndexMinsLakeReader:
    def __init__(self, lake_root: Path) -> None:
        self._lake_root = lake_root.expanduser().resolve()

    def read_bars(self, request: IndexMinuteReadRequest) -> IndexMinuteReadPage:
        return self._read(request, dataset="bars")

    def read_indicators(self, request: IndexMinuteReadRequest) -> IndexMinuteReadPage:
        return self._read(request, dataset="indicators")

    def _read(
        self,
        request: IndexMinuteReadRequest,
        *,
        dataset: IndexMinuteDataset,
    ) -> IndexMinuteReadPage:
        started = time.perf_counter()
        normalized, decoded_cursor = _normalize_request(request, dataset=dataset)
        partitions = _enumerate_partitions(
            self._lake_root,
            dataset=dataset,
            freq=normalized.freq,
            start_date=normalized.start_date,
            end_date=normalized.end_date,
            cursor=decoded_cursor,
        )
        if not partitions:
            return _empty_page(started, scanned_file_count=0)

        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - capability gate covers startup
            raise IndexMinuteQueryError("local-lake DuckDB 依赖不可用。") from exc

        connection = duckdb.connect(database=":memory:")
        selected_count = min(_initial_partition_count(normalized), len(partitions))
        rows: list[dict[str, Any]] = []
        try:
            while True:
                selected = partitions[:selected_count]
                paths = tuple(item.path for item in selected)
                _validate_combined_schema(connection, paths, dataset=dataset)
                rows = _query_rows(
                    connection,
                    partitions=selected,
                    dataset=dataset,
                    request=normalized,
                    decoded_cursor=decoded_cursor,
                )
                if len(rows) >= normalized.limit + 1 or selected_count == len(partitions):
                    break
                next_count = min(len(partitions), max(selected_count + 1, selected_count * 2))
                if next_count > MAX_INDEX_MINUTE_PARTITION_FILES:
                    raise IndexMinuteRequestError(
                        "指数分钟查询需要扫描超过 5000 个分区，请缩小日期范围。"
                    )
                selected_count = next_count
        except IndexMinuteReaderError:
            raise
        except Exception as exc:
            raise IndexMinuteQueryError("指数分钟 Lake 查询失败。") from exc
        finally:
            connection.close()

        has_more = len(rows) > normalized.limit
        page_rows = rows[: normalized.limit]
        page_rows.reverse()
        next_cursor = None
        if has_more and page_rows:
            first = page_rows[0]
            next_cursor = _encode_cursor(
                dataset=dataset,
                request=normalized,
                before_trade_date=first["trade_date"],
                before_trade_time=first["trade_time"],
            )

        observed_dates = [row["trade_date"] for row in page_rows]
        return IndexMinuteReadPage(
            rows=tuple(page_rows),
            count=len(page_rows),
            has_more=has_more,
            next_cursor=next_cursor,
            observed_start_date=min(observed_dates) if observed_dates else None,
            observed_end_date=max(observed_dates) if observed_dates else None,
            scanned_file_count=selected_count,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )


def _normalize_request(
    request: IndexMinuteReadRequest,
    *,
    dataset: IndexMinuteDataset,
) -> tuple[IndexMinuteReadRequest, dict[str, Any] | None]:
    ts_code = request.ts_code.strip().upper()
    if not INDEX_TS_CODE_PATTERN.fullmatch(ts_code):
        raise IndexMinuteRequestError("tsCode 必须是六位代码加 SH/SZ/BJ 后缀。")
    try:
        freq = int(request.freq)
    except (TypeError, ValueError) as exc:
        raise IndexMinuteRequestError("freq 必须是整数分钟频率。") from exc
    if isinstance(request.freq, bool) or freq not in SUPPORTED_INDEX_MINUTE_FREQS:
        raise IndexMinuteRequestError("不支持的指数分钟频率。")
    if request.start_date is not None and request.end_date is not None and request.start_date > request.end_date:
        raise IndexMinuteRequestError("startDate 不能晚于 endDate。")
    if not 1 <= request.limit <= MAX_INDEX_MINUTE_LIMIT:
        raise IndexMinuteRequestError("limit 必须在 1 到 10000 之间。")

    decoded_cursor = _decode_cursor(request.cursor) if request.cursor else None
    if decoded_cursor is not None:
        if decoded_cursor["dataset"] != dataset:
            raise IndexMinuteRequestError("cursor 与当前数据集不匹配。")
        if decoded_cursor["freq"] != freq or decoded_cursor["tsCode"] != ts_code:
            raise IndexMinuteRequestError("cursor 与当前代码或频率不匹配。")
        if _optional_date(decoded_cursor["startDate"]) != request.start_date:
            raise IndexMinuteRequestError("cursor 与当前 startDate 不匹配。")
        if _optional_date(decoded_cursor["endDate"]) != request.end_date:
            raise IndexMinuteRequestError("cursor 与当前 endDate 不匹配。")

    return (
        IndexMinuteReadRequest(
            ts_code=ts_code,
            freq=freq,
            start_date=request.start_date,
            end_date=request.end_date,
            limit=request.limit,
            cursor=request.cursor,
        ),
        decoded_cursor,
    )


def _enumerate_partitions(
    lake_root: Path,
    *,
    dataset: IndexMinuteDataset,
    freq: int,
    start_date: date | None,
    end_date: date | None,
    cursor: dict[str, Any] | None,
) -> tuple[_PartitionFile, ...]:
    try:
        frequency_root = major_index_minute_frequency_root(lake_root, dataset, freq)
    except ValueError as exc:
        raise IndexMinuteRequestError(str(exc)) from exc
    if not frequency_root.is_dir():
        return ()

    root = lake_root.expanduser().resolve()
    dataset_root = frequency_root.parent.resolve()
    cursor_date = date.fromisoformat(cursor["beforeTradeDate"]) if cursor is not None else None
    partitions: list[_PartitionFile] = []
    for candidate in frequency_root.glob("trade_date=*/part-000.parquet"):
        match = TRADE_DATE_PARTITION_PATTERN.fullmatch(candidate.parent.name)
        if match is None:
            continue
        partition_date = date.fromisoformat(match.group(1))
        if start_date is not None and partition_date < start_date:
            continue
        if end_date is not None and partition_date > end_date:
            continue
        if cursor_date is not None and partition_date > cursor_date:
            continue
        if _contains_symlink(candidate, stop=root):
            raise IndexMinuteSourceContractError("指数分钟分区不得使用符号链接。")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_relative_to(dataset_root):
            raise IndexMinuteSourceContractError("指数分钟分区路径越界。")
        if resolved.name != "part-000.parquet" or not resolved.is_file():
            continue
        partitions.append(_PartitionFile(trade_date=partition_date, path=resolved))

    partitions.sort(key=lambda item: item.trade_date, reverse=True)
    return tuple(partitions)


def _contains_symlink(path: Path, *, stop: Path) -> bool:
    current = path
    while current != stop:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return True
        current = parent
    return False


def _initial_partition_count(request: IndexMinuteReadRequest) -> int:
    estimated = math.ceil((request.limit + 1) / EXPECTED_BARS_PER_SESSION[request.freq]) + 2
    if estimated > MAX_INDEX_MINUTE_PARTITION_FILES:
        raise IndexMinuteRequestError("指数分钟查询需要扫描超过 5000 个分区，请缩小日期范围。")
    return max(1, estimated)


def _validate_combined_schema(
    connection: Any,
    paths: Sequence[Path],
    *,
    dataset: IndexMinuteDataset,
) -> None:
    expected = SILVER_BAR_COLUMN_SPECS if dataset == "bars" else GOLD_INDICATOR_COLUMN_SPECS
    try:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [list(map(str, paths))],
        ).fetchall()
    except Exception as exc:
        raise IndexMinuteSourceContractError("指数分钟 Parquet schema 不符合合同。") from exc
    actual = tuple((str(row[0]), _normalize_duckdb_type(row[1])) for row in description)
    if actual != expected:
        raise IndexMinuteSourceContractError("指数分钟 Parquet 列名、顺序或类型不符合合同。")


def _normalize_duckdb_type(value: Any) -> str:
    normalized = str(value).upper()
    if normalized.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    if normalized in {"TEXT", "STRING"}:
        return "VARCHAR"
    return normalized


def _query_rows(
    connection: Any,
    *,
    partitions: Sequence[_PartitionFile],
    dataset: IndexMinuteDataset,
    request: IndexMinuteReadRequest,
    decoded_cursor: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    paths = list(map(str, (item.path for item in partitions)))
    if dataset == "bars":
        source_freq = SILVER_FREQ_VALUES[request.freq]
        projection = """
            ts_code,
            ?::SMALLINT AS freq,
            CAST(regexp_extract(filename, 'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1) AS DATE) AS trade_date,
            trade_time, open, high, low, close, vol, amount, exchange
        """
        contract_predicate = """
            freq = ?
            AND regexp_full_match(ts_code, '^[0-9]{6}\\.(SH|SZ|BJ)$')
            AND CAST(trade_time AS DATE) = CAST(
              regexp_extract(filename, 'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1) AS DATE
            )
            AND isfinite(open)
            AND isfinite(high)
            AND isfinite(low)
            AND isfinite(close)
            AND isfinite(vol)
            AND isfinite(amount)
            AND exchange <> ''
        """
        identity_predicate = "ts_code = ? AND freq = ?"
        parameters: list[Any] = [paths, source_freq, request.freq, request.ts_code, source_freq]
    else:
        projection = """
            ts_code, freq, trade_date, trade_time,
            ma_5, ma_10, ma_20, ma_30, ma_60, ma_90, ma_250,
            boll_mid, boll_upper, boll_lower,
            macd_dif, macd_dea, macd, kdj_k, kdj_d, kdj_j,
            observation_count, params_key, indicator_version
        """
        contract_predicate = """
            freq = ?
            AND regexp_full_match(ts_code, '^[0-9]{6}\\.(SH|SZ|BJ)$')
            AND trade_date = CAST(
              regexp_extract(filename, 'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1) AS DATE
            )
            AND CAST(trade_time AS DATE) = trade_date
            AND params_key = ?
            AND indicator_version = ?
            AND observation_count >= 1
        """
        identity_predicate = "ts_code = ? AND freq = ?"
        parameters = [
            paths,
            request.freq,
            GOLD_PARAMS_KEY,
            GOLD_INDICATOR_VERSION,
            request.ts_code,
            request.freq,
        ]

    filters = [identity_predicate]
    if request.start_date is not None:
        filters.append("trade_date >= ?")
        parameters.append(request.start_date)
    if request.end_date is not None:
        filters.append("trade_date <= ?")
        parameters.append(request.end_date)
    if decoded_cursor is not None:
        filters.append(
            "(trade_date < CAST(? AS DATE) OR "
            "(trade_date = CAST(? AS DATE) AND trade_time < CAST(? AS TIMESTAMP)))"
        )
        before_date = decoded_cursor["beforeTradeDate"]
        parameters.extend(
            [before_date, before_date, f"{before_date} {decoded_cursor['beforeTradeTime']}"]
        )

    sql = f"""
        WITH source AS MATERIALIZED (
          SELECT *, filename
          FROM read_parquet(?, filename=true, hive_partitioning=false)
        ),
        contract AS (
          SELECT count(*) FILTER (WHERE NOT COALESCE(({contract_predicate}), FALSE)) AS invalid_count
          FROM source
        ),
        target AS (
          SELECT {projection}
          FROM source
          WHERE {' AND '.join(filters)}
        ),
        integrity AS (
          SELECT
            count(*) AS target_count,
            count(*) - count(DISTINCT (trade_date, trade_time)) AS duplicate_count
          FROM target
        ),
        paged AS (
          SELECT * FROM target
          ORDER BY trade_date DESC, trade_time DESC
          LIMIT ?
        )
        SELECT
          paged.*,
          contract.invalid_count,
          integrity.duplicate_count,
          integrity.target_count
        FROM contract CROSS JOIN integrity LEFT JOIN paged ON TRUE
    """
    parameters.append(request.limit + 1)
    try:
        cursor = connection.execute(sql, parameters)
        names = [item[0] for item in cursor.description]
        fetched = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    except IndexMinuteReaderError:
        raise
    except Exception as exc:
        raise IndexMinuteQueryError("指数分钟 Lake 查询失败。") from exc

    if fetched:
        invalid_count = int(fetched[0].pop("invalid_count"))
        duplicate_count = int(fetched[0].pop("duplicate_count"))
        target_count = int(fetched[0].pop("target_count"))
        for row in fetched[1:]:
            row.pop("invalid_count")
            row.pop("duplicate_count")
            row.pop("target_count")
        if invalid_count:
            raise IndexMinuteSourceContractError("指数分钟文件存在频率、日期、身份或版本合同错误。")
        if duplicate_count:
            raise IndexMinuteSourceContractError("指数分钟文件存在重复时间键。")
        if target_count == 0:
            return []
    return fetched


def _encode_cursor(
    *,
    dataset: IndexMinuteDataset,
    request: IndexMinuteReadRequest,
    before_trade_date: date,
    before_trade_time: datetime,
) -> str:
    payload = {
        "v": INDEX_MINUTE_CURSOR_VERSION,
        "dataset": dataset,
        "tsCode": request.ts_code,
        "freq": request.freq,
        "startDate": request.start_date.isoformat() if request.start_date else None,
        "endDate": request.end_date.isoformat() if request.end_date else None,
        "beforeTradeDate": before_trade_date.isoformat(),
        "beforeTradeTime": before_trade_time.strftime("%H:%M:%S.%f"),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    return encoded.rstrip("=")


def _decode_cursor(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise IndexMinuteRequestError("cursor 不合法。") from exc
    if not isinstance(payload, dict) or payload.get("v") != INDEX_MINUTE_CURSOR_VERSION:
        raise IndexMinuteRequestError("cursor 版本不支持。")
    required = {
        "dataset",
        "tsCode",
        "freq",
        "startDate",
        "endDate",
        "beforeTradeDate",
        "beforeTradeTime",
    }
    if set(payload) != required | {"v"}:
        raise IndexMinuteRequestError("cursor 字段不完整或包含未知字段。")
    try:
        normalized_code = str(payload["tsCode"]).strip().upper()
        if not INDEX_TS_CODE_PATTERN.fullmatch(normalized_code):
            raise ValueError
        normalized_freq = int(payload["freq"])
        if normalized_freq not in SUPPORTED_INDEX_MINUTE_FREQS:
            raise ValueError
        date.fromisoformat(str(payload["beforeTradeDate"]))
        clock_time.fromisoformat(str(payload["beforeTradeTime"]))
        if payload["startDate"] is not None:
            date.fromisoformat(str(payload["startDate"]))
        if payload["endDate"] is not None:
            date.fromisoformat(str(payload["endDate"]))
    except (TypeError, ValueError) as exc:
        raise IndexMinuteRequestError("cursor 时间或身份边界不合法。") from exc
    if payload["dataset"] not in {"bars", "indicators"}:
        raise IndexMinuteRequestError("cursor 数据集不支持。")
    payload["tsCode"] = normalized_code
    payload["freq"] = normalized_freq
    return payload


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise IndexMinuteRequestError("cursor 日期不合法。") from exc


def _empty_page(started: float, *, scanned_file_count: int) -> IndexMinuteReadPage:
    return IndexMinuteReadPage(
        rows=(),
        count=0,
        has_more=False,
        next_cursor=None,
        observed_start_date=None,
        observed_end_date=None,
        scanned_file_count=scanned_file_count,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
