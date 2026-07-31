from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as clock_time
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

SUPPORTED_MINUTE_FREQS = (1, 5, 15, 30, 60, 90, 120)
MAX_MINUTE_LIMIT = 10_000
MAX_YEAR_FILE_COUNT = 3
TS_CODE_PATTERN = re.compile(r"^[0-9]{6}\.(?:SZ|SH|BJ)$")
CURSOR_VERSION = 1

DatasetName = Literal["bars", "indicators"]

BAR_COLUMNS = (
    "ts_code",
    "freq",
    "trade_date",
    "trade_time",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "exchange",
)
INDICATOR_COLUMNS = (
    "ts_code",
    "freq",
    "trade_date",
    "trade_time",
    "macd_dif_qfq",
    "macd_dea_qfq",
    "macd_qfq",
    "kdj_k_qfq",
    "kdj_d_qfq",
    "kdj_qfq",
    "params_key",
    "indicator_version",
)


class MinuteReaderError(RuntimeError):
    code = "SM_QUERY_FAILED"


class MinuteRequestError(MinuteReaderError):
    code = "SM_REQUEST_INVALID"


class MinuteSourceContractError(MinuteReaderError):
    code = "SM_SOURCE_CONTRACT_INVALID"


class MinuteQueryError(MinuteReaderError):
    code = "SM_QUERY_FAILED"


@dataclass(frozen=True)
class MinuteReadRequest:
    ts_code: str
    freq: int
    start_date: date | None
    end_date: date | None
    limit: int
    cursor: str | None


@dataclass(frozen=True)
class MinuteReadPage:
    rows: tuple[dict[str, Any], ...]
    count: int
    has_more: bool
    next_cursor: str | None
    observed_start_date: date | None
    observed_end_date: date | None
    scanned_file_count: int
    elapsed_ms: float


def build_stock_mins_qfq_paths(
    lake_root: Path,
    dataset: DatasetName,
    ts_code: str,
    freq: int,
    years: Sequence[int],
) -> tuple[Path, ...]:
    normalized_code = _validate_ts_code(ts_code)
    normalized_freq = _validate_freq(freq)
    normalized_years = tuple(int(year) for year in years)
    if not normalized_years or len(normalized_years) > MAX_YEAR_FILE_COUNT:
        raise MinuteRequestError("分钟查询最多允许涉及 3 个年份文件。")
    if any(year < 2000 or year > 2100 for year in normalized_years):
        raise MinuteRequestError("分钟查询年份不合法。")
    if dataset not in {"bars", "indicators"}:
        raise MinuteRequestError("分钟数据集类型不支持。")

    root = lake_root.expanduser().resolve()
    dataset_path = "stk_mins_qfq" if dataset == "bars" else "stk_mins_qfq_macd_kdj"
    layer_path = "quote" if dataset == "bars" else "indicator"
    paths: list[Path] = []
    for year in normalized_years:
        candidate = (
            root
            / "gold"
            / layer_path
            / dataset_path
            / f"freq={normalized_freq}"
            / f"ts_code={normalized_code}"
            / f"year={year}"
            / "part-000.parquet"
        ).resolve()
        if not candidate.is_relative_to(root):
            raise MinuteRequestError("分钟查询路径越界。")
        if candidate.is_file():
            paths.append(candidate)
    return tuple(paths)


class StockMinsLakeReader:
    def __init__(self, lake_root: Path) -> None:
        self._lake_root = lake_root.expanduser().resolve()

    def read_bars(self, request: MinuteReadRequest) -> MinuteReadPage:
        return self._read(request, dataset="bars")

    def read_indicators(self, request: MinuteReadRequest) -> MinuteReadPage:
        return self._read(request, dataset="indicators")

    def _read(self, request: MinuteReadRequest, *, dataset: DatasetName) -> MinuteReadPage:
        started = time.perf_counter()
        normalized = _normalize_request(request)
        years = _request_years(normalized.start_date, normalized.end_date)
        paths = build_stock_mins_qfq_paths(
            self._lake_root,
            dataset,
            normalized.ts_code,
            normalized.freq,
            years,
        )
        if not paths:
            return _empty_page(started, scanned_file_count=0)

        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - capability gate covers normal startup
            raise MinuteQueryError("local-lake DuckDB 依赖不可用。") from exc

        columns = BAR_COLUMNS if dataset == "bars" else INDICATOR_COLUMNS
        connection = duckdb.connect(database=":memory:")
        try:
            for path in paths:
                _validate_file_schema(connection, path, columns)
            rows = _query_rows(
                connection,
                paths=paths,
                columns=columns,
                request=normalized,
            )
        except MinuteReaderError:
            raise
        except Exception as exc:
            raise MinuteQueryError("分钟 Lake 查询失败。") from exc
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
        elapsed_ms = (time.perf_counter() - started) * 1000
        return MinuteReadPage(
            rows=tuple(page_rows),
            count=len(page_rows),
            has_more=has_more,
            next_cursor=next_cursor,
            observed_start_date=min(observed_dates) if observed_dates else None,
            observed_end_date=max(observed_dates) if observed_dates else None,
            scanned_file_count=len(paths),
            elapsed_ms=elapsed_ms,
        )


def _normalize_request(request: MinuteReadRequest) -> MinuteReadRequest:
    ts_code = _validate_ts_code(request.ts_code)
    freq = _validate_freq(request.freq)
    if request.start_date is not None and request.end_date is not None and request.start_date > request.end_date:
        raise MinuteRequestError("startDate 不能晚于 endDate。")
    if not 1 <= request.limit <= MAX_MINUTE_LIMIT:
        raise MinuteRequestError("limit 必须在 1 到 10000 之间。")
    cursor = _decode_cursor(request.cursor) if request.cursor else None
    if cursor is not None:
        if cursor["freq"] != freq or cursor["tsCode"] != ts_code:
            raise MinuteRequestError("cursor 与当前代码或频率不匹配。")
        if _optional_date(cursor.get("startDate")) != request.start_date:
            raise MinuteRequestError("cursor 与当前 startDate 不匹配。")
        if _optional_date(cursor.get("endDate")) != request.end_date:
            raise MinuteRequestError("cursor 与当前 endDate 不匹配。")
    return MinuteReadRequest(
        ts_code=ts_code,
        freq=freq,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        cursor=request.cursor,
    )


def _request_years(start_date: date | None, end_date: date | None) -> tuple[int, ...]:
    effective_end = end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    effective_start = start_date or date(effective_end.year - (MAX_YEAR_FILE_COUNT - 1), 1, 1)
    years = tuple(range(effective_start.year, effective_end.year + 1))
    if len(years) > MAX_YEAR_FILE_COUNT:
        raise MinuteRequestError("分钟查询最多允许涉及 3 个年份文件。")
    return years


def _validate_file_schema(connection: Any, path: Path, columns: Sequence[str]) -> None:
    projection = ", ".join(columns)
    try:
        description = connection.execute(
            f"DESCRIBE SELECT {projection} FROM read_parquet(?)",
            [str(path)],
        ).fetchall()
    except Exception as exc:
        raise MinuteSourceContractError("分钟 Lake 文件 schema 不符合合同。") from exc
    described_names = tuple(row[0] for row in description)
    if described_names != tuple(columns):
        raise MinuteSourceContractError("分钟 Lake 文件列合同不一致。")

    for row in description:
        name, duckdb_type = row[0], str(row[1]).upper()
        if name in {"freq", "indicator_version"}:
            if "INT" not in duckdb_type:
                raise MinuteSourceContractError(f"分钟 Lake 字段类型不符合合同：{name}。")
        elif name in {"trade_date"}:
            if duckdb_type != "DATE":
                raise MinuteSourceContractError("分钟 Lake trade_date 类型不符合合同。")
        elif name in {"trade_time"}:
            if not duckdb_type.startswith("TIMESTAMP"):
                raise MinuteSourceContractError("分钟 Lake trade_time 类型不符合合同。")
        elif name in {"ts_code", "exchange", "params_key"}:
            if duckdb_type not in {"VARCHAR", "TEXT"}:
                raise MinuteSourceContractError(f"分钟 Lake 字段类型不符合合同：{name}。")
        elif duckdb_type not in {"DOUBLE", "FLOAT", "REAL"}:
            raise MinuteSourceContractError(f"分钟 Lake 数值字段类型不符合合同：{name}。")


def _query_rows(connection: Any, *, paths: Sequence[Path], columns: Sequence[str], request: MinuteReadRequest) -> list[dict[str, Any]]:
    projection = ", ".join(columns)
    path_filter = "read_parquet(?)"
    predicates = ["ts_code = ?", "freq = ?"]
    parameters: list[Any] = [list(map(str, paths)), request.ts_code, request.freq]
    if request.start_date is not None:
        predicates.append("trade_date >= ?")
        parameters.append(request.start_date)
    if request.end_date is not None:
        predicates.append("trade_date <= ?")
        parameters.append(request.end_date)
    if request.cursor:
        cursor = _decode_cursor(request.cursor)
        predicates.append(
            "(trade_date < CAST(? AS DATE) "
            "OR (trade_date = CAST(? AS DATE) AND trade_time < CAST(? AS TIMESTAMP)))"
        )
        before_date = cursor["beforeTradeDate"]
        before_time = cursor["beforeTradeTime"]
        parameters.extend([before_date, before_date, f"{before_date} {before_time}"])
    sql = f"""
        SELECT {projection}
        FROM {path_filter}
        WHERE {' AND '.join(predicates)}
        ORDER BY trade_date DESC, trade_time DESC
        LIMIT ?
    """
    parameters.append(request.limit + 1)
    try:
        cursor = connection.execute(sql, parameters)
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    except Exception as exc:
        raise MinuteQueryError("分钟 Lake 查询失败。") from exc


def _encode_cursor(*, dataset: DatasetName, request: MinuteReadRequest, before_trade_date: date, before_trade_time: datetime) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "dataset": dataset,
        "tsCode": request.ts_code,
        "freq": request.freq,
        "startDate": request.start_date.isoformat() if request.start_date else None,
        "endDate": request.end_date.isoformat() if request.end_date else None,
        "beforeTradeDate": before_trade_date.isoformat(),
        "beforeTradeTime": before_trade_time.strftime("%H:%M:%S.%f"),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return encoded.rstrip("=")


def _decode_cursor(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise MinuteRequestError("cursor 不合法。") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise MinuteRequestError("cursor 版本不支持。")
    required = {"dataset", "tsCode", "freq", "startDate", "endDate", "beforeTradeDate", "beforeTradeTime"}
    if not required.issubset(payload):
        raise MinuteRequestError("cursor 字段不完整。")
    try:
        _validate_ts_code(str(payload["tsCode"]))
        _validate_freq(int(payload["freq"]))
        date.fromisoformat(payload["beforeTradeDate"])
        clock_time.fromisoformat(payload["beforeTradeTime"])
        if payload["startDate"] is not None:
            date.fromisoformat(payload["startDate"])
        if payload["endDate"] is not None:
            date.fromisoformat(payload["endDate"])
    except (TypeError, ValueError) as exc:
        raise MinuteRequestError("cursor 时间边界不合法。") from exc
    if payload["dataset"] not in {"bars", "indicators"}:
        raise MinuteRequestError("cursor 数据集类型不支持。")
    return payload


def _validate_ts_code(value: str) -> str:
    normalized = value.strip().upper()
    if not TS_CODE_PATTERN.fullmatch(normalized):
        raise MinuteRequestError("tsCode 必须是六位代码加 SZ/SH/BJ 后缀。")
    return normalized


def _validate_freq(value: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise MinuteRequestError("freq 必须是整数分钟频率。") from exc
    if normalized not in SUPPORTED_MINUTE_FREQS:
        raise MinuteRequestError("不支持的分钟频率。")
    return normalized


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise MinuteRequestError("cursor 日期不合法。") from exc


def _empty_page(started: float, *, scanned_file_count: int) -> MinuteReadPage:
    return MinuteReadPage(
        rows=(),
        count=0,
        has_more=False,
        next_cursor=None,
        observed_start_date=None,
        observed_end_date=None,
        scanned_file_count=scanned_file_count,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
