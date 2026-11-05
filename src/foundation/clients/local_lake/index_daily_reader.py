"""Read-only access to the DG Silver sources used by index detail."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
import os
from pathlib import Path
import stat
from typing import Any

from .major_index_mins_contract import FORMAL_LAKE_ROOT as FORMAL_LAKE_ROOT

_FACTOR_DIR = Path("silver/index/index_factor_pro")
_DAILY_DIR = Path("silver/index_daily")
_CALENDAR_FILE = Path("silver/calendar/trade_calendar/full/part-000.parquet")
_BASIC_FILE = Path("silver/index_basic/full/part-000.parquet")
_PARTITION_PREFIX = "trade_date="
_PART_FILE = "part-000.parquet"
_CALENDAR_COLUMNS = (("trade_date", "DATE"), ("is_open", "BOOLEAN"), ("pretrade_date", "DATE"))
_IDENTITY_COLUMNS = ("ts_code", "name", "market", "publisher", "category")


class IndexDailyLakeSourceError(RuntimeError):
    """The configured DG Silver source is unavailable or violates its contract."""


class IndexDailyLakeReader:
    def __init__(self, root: Path | None) -> None:
        self.root = root

    def calendar_rows(
        self, *, end: date, start: date | None = None, recent_open_days: int | None = None,
    ) -> tuple[tuple[date, bool, date | None], ...]:
        """Read a bounded range of SSE dates, including closed days."""
        path = str(self._path(_CALENDAR_FILE))
        if recent_open_days is None:
            rows = _read(
                """
                SELECT trade_date, is_open, pretrade_date
                FROM read_parquet(?, hive_partitioning=false)
                WHERE exchange = 'SSE' AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [path, start if start is not None else end, end], _CALENDAR_COLUMNS,
            )
        else:
            rows = _read(
                """
                WITH calendar AS MATERIALIZED (
                    SELECT trade_date, is_open, pretrade_date
                    FROM read_parquet(?, hive_partitioning=false)
                    WHERE exchange = 'SSE' AND trade_date <= ?
                ), recent_open AS (
                    SELECT trade_date FROM calendar
                    WHERE is_open
                    ORDER BY trade_date DESC LIMIT ?
                )
                SELECT trade_date, is_open, pretrade_date FROM calendar
                WHERE trade_date >= COALESCE((SELECT min(trade_date) FROM recent_open), ?)
                  AND trade_date >= ?
                ORDER BY trade_date
                """,
                [path, end, recent_open_days, end, start or date.min], _CALENDAR_COLUMNS,
            )
        return tuple(rows)

    def factor_dates(self, *, start: date | None, end: date) -> tuple[date, ...]:
        return _partition_dates(self._path(_FACTOR_DIR), start=start, end=end)

    def factor_rows(
        self, *, ts_code: str, dates: Sequence[date], columns: Sequence[str], limit: int,
        descending: bool = False,
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
            [_part_paths(directory, dates), ts_code, min(dates), max(dates), limit], schema,
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
) -> list[tuple[Any, ...]]:
    import duckdb

    try:
        with duckdb.connect(database=":memory:") as connection:
            cursor = connection.execute(sql, params)
            actual = tuple((column[0], str(column[1])) for column in cursor.description)
            if actual != schema:
                raise IndexDailyLakeSourceError("本机DG指数日线所用字段与合同不一致。")
            return cursor.fetchall()
    except duckdb.Error as exc:
        raise IndexDailyLakeSourceError("无法读取本机DG指数日线文件。") from exc
