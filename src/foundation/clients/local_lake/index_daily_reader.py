"""Read-only access to the DG Silver sources used by index detail."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
import os
from pathlib import Path
import stat
from threading import Timer
from typing import Any

from src.foundation.clients.reference_data import ReferenceDataReadError

from .reference_data_reader import LakeTradeCalendarReader
from .major_index_mins_contract import FORMAL_LAKE_ROOT as FORMAL_LAKE_ROOT

_FACTOR_DIR = Path("silver/index/index_factor_pro")
_DAILY_DIR = Path("silver/index_daily")
_BASIC_FILE = Path("silver/index_basic/full/part-000.parquet")
_PARTITION_PREFIX = "trade_date="
_PART_FILE = "part-000.parquet"
_IDENTITY_COLUMNS = ("ts_code", "name", "market", "publisher", "category")
_QUOTE_FIELDS = ("open", "high", "low", "close", "pre_close", "change_amount", "pct_chg", "vol", "amount")


class IndexDailyLakeSourceError(RuntimeError):
    """The configured DG Silver source is unavailable or violates its contract."""


class IndexDailyLakeReader:
    def __init__(self, root: Path | None) -> None:
        self.root = root

    def calendar_rows(
        self, *, end: date, start: date | None = None, recent_open_days: int | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[date, bool, date | None], ...]:
        """Read a bounded range of SSE dates, including closed days."""
        reader = LakeTradeCalendarReader(self.root)
        try:
            if recent_open_days is None:
                rows = reader.range_rows(
                    exchange="SSE", start=start or end, end=end, timeout_seconds=timeout_seconds,
                )
            else:
                rows = reader.context_rows(
                    exchange="SSE", start=start, end=end, recent_open_days=recent_open_days,
                    timeout_seconds=timeout_seconds,
                )
        except ReferenceDataReadError as error:
            raise IndexDailyLakeSourceError(str(error)) from error
        return tuple((row.trade_date, row.is_open, row.pretrade_date) for row in rows)

    def factor_dates(self, *, start: date | None, end: date) -> tuple[date, ...]:
        return _partition_dates(self._path(_FACTOR_DIR), start=start, end=end)

    def factor_rows(
        self, *, ts_code: str, dates: Sequence[date], columns: Sequence[str], limit: int,
        descending: bool = False, timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        """Read only the selected published factor files and fields."""
        directory = self._path(_FACTOR_DIR)
        if not dates:
            return []
        # Column names come from the caller's Web contract. Validate identifiers
        # before interpolation, and bind all paths, filter values and limits.
        if not columns or any(not column.isidentifier() for column in columns):
            raise ValueError("指数日线读取列不合法。")
        projection = ", ".join(f'"{column}"' for column in columns)
        key_types = {"ts_code": "VARCHAR", "trade_date": "DATE"}
        schema = tuple((column, key_types.get(column, "DOUBLE")) for column in columns)
        direction = "DESC" if descending else "ASC"
        rows = _read(
            f"""
            SELECT {projection}
            FROM read_parquet(?, hive_partitioning=false)
            WHERE ts_code = ? AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date {direction}
            LIMIT ?
            """,
            [_part_paths(directory, dates), ts_code, min(dates), max(dates), limit], schema, timeout_seconds=timeout_seconds,
        )
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def index_identity(self, ts_code: str) -> dict[str, Any] | None:
        rows = _read(
            """
            SELECT ts_code, name, market, publisher, category
            FROM read_parquet(?, hive_partitioning=false)
            WHERE ts_code = ? LIMIT 1
            """,
            [str(self._path(_BASIC_FILE)), ts_code],
            tuple((column, "VARCHAR") for column in _IDENTITY_COLUMNS),
        )
        return dict(zip(_IDENTITY_COLUMNS, rows[0], strict=True)) if rows else None

    def latest_daily_quote(self, ts_code: str, *, start: date, end: date) -> dict[str, Any] | None:
        directory = self._path(_DAILY_DIR)
        projection = ", ".join(_QUOTE_FIELDS)
        schema = (("trade_date", "DATE"), *((field, "DOUBLE") for field in _QUOTE_FIELDS))
        for day in reversed(_partition_dates(directory, start=start, end=end)):
            path, = _part_paths(directory, (day,))
            rows = _read(
                f"""
                SELECT trade_date, {projection}
                FROM read_parquet(?, hive_partitioning=false)
                WHERE ts_code = ? LIMIT 2
                """,
                [path, ts_code], schema,
            )
            if not rows:
                continue
            if len(rows) != 1 or rows[0][0] != day:
                raise IndexDailyLakeSourceError(f"{ts_code} 普通日线与分区日期不一致或存在重复行情：{day}")
            return dict(zip(("trade_date", *_QUOTE_FIELDS), rows[0], strict=True))
        return None

    def ordinary_daily_page_dates(
        self, ts_code: str, *, start: date, end: date, before: date | None, limit: int,
    ) -> tuple[date, ...]:
        """Return the requested exchange dates after checking each published daily row."""
        bound, include_bound = (before, False) if before is not None and before <= end else (end, True)
        try:
            open_days = LakeTradeCalendarReader(self.root).recent_open_rows(
                exchange="SSE", bound=bound,
                include_bound=include_bound, start=start, limit=limit,
            )
        except ReferenceDataReadError as exc:
            raise IndexDailyLakeSourceError(str(exc)) from exc
        dates = tuple(row.trade_date for row in open_days)
        if not dates:
            return ()
        paths = _part_paths(self._path(_DAILY_DIR), dates)
        observed = _read(
            """
            SELECT filename, trade_date
            FROM read_parquet(?, hive_partitioning=false, filename=true)
            WHERE ts_code = ?
            ORDER BY filename
            """,
            [paths, ts_code], (("filename", "VARCHAR"), ("trade_date", "DATE")),
        )
        if observed != list(zip(paths, dates, strict=True)):
            raise IndexDailyLakeSourceError(f"{ts_code} 的 DG 普通日线缺失、重复或与分区日期不一致。")
        return dates

    def has_daily_after(self, *, ts_code: str, after: date, end: date) -> bool:
        directory = self._path(_DAILY_DIR)
        if after >= end:
            return False
        dates = _partition_dates(directory, start=after + timedelta(days=1), end=end)
        if not dates:
            return False
        rows = _read(
            """
            SELECT EXISTS (
                SELECT 1 FROM read_parquet(?, hive_partitioning=false)
                WHERE ts_code = ? AND trade_date > ? AND trade_date <= ?
            ) AS has_daily
            """,
            [_part_paths(directory, dates), ts_code, after, end], (("has_daily", "BOOLEAN"),),
        )
        return rows[0][0]

    def _path(self, relative: Path) -> Path:
        if self.root is None:
            raise IndexDailyLakeSourceError("本机DG指数日线来源未配置。")
        return self.root / relative


def _partition_dates(directory: Path, *, start: date | None, end: date) -> tuple[date, ...]:
    if start is not None and start > end:
        return ()
    lower = start.isoformat() if start is not None else ""
    upper = end.isoformat()
    dates = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.name.startswith(_PARTITION_PREFIX):
                    continue
                key = entry.name[len(_PARTITION_PREFIX):]
                if not (len(key) == 10 and lower <= key <= upper and entry.is_dir(follow_symlinks=False)):
                    continue
                try:
                    part_date = date.fromisoformat(key)
                    if part_date.isoformat() != key:
                        continue
                    info = os.stat(os.path.join(entry.path, _PART_FILE), follow_symlinks=False)
                except (ValueError, FileNotFoundError, NotADirectoryError):
                    continue
                if stat.S_ISREG(info.st_mode):
                    dates.append(part_date)
    except OSError as exc:
        raise IndexDailyLakeSourceError("无法读取本机DG指数日线分区。") from exc
    return tuple(sorted(dates))


def _part_paths(directory: Path, dates: Sequence[date]) -> list[str]:
    return [str(directory / f"{_PARTITION_PREFIX}{day.isoformat()}" / _PART_FILE) for day in dates]


def _read(
    sql: str, params: list[Any], schema: tuple[tuple[str, str], ...],
    *, timeout_seconds: float | None = None,
) -> list[tuple[Any, ...]]:
    import duckdb

    try:
        with duckdb.connect(database=":memory:") as connection:
            timer = None
            if timeout_seconds is not None:
                timer = Timer(timeout_seconds, connection.interrupt)
                timer.daemon = True
                timer.start()
            try:
                cursor = connection.execute(sql, params)
                actual = tuple((column[0], str(column[1])) for column in cursor.description)
                if actual != schema:
                    raise IndexDailyLakeSourceError("本机DG指数日线所用字段与合同不一致。")
                return cursor.fetchall()
            finally:
                if timer is not None:
                    timer.cancel()
    except duckdb.InterruptException as exc:
        raise TimeoutError("指数日线读取超时。") from exc
    except duckdb.Error as exc:
        raise IndexDailyLakeSourceError("无法读取本机DG指数日线文件。") from exc
