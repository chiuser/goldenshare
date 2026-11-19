"""Read A-share securities and the SSE calendar from the published DG files."""

from collections.abc import Sequence
from dataclasses import fields
from datetime import date
from pathlib import Path
from threading import Timer

import duckdb

from src.foundation.clients.reference_data import (
    ReferenceDataReadError,
    SecurityPlanningRow,
    SecurityReferenceRow,
    TradeCalendarRow,
)

STOCK_BASIC_LOCATION = "raw/tushare/stock_basic"
TRADE_CALENDAR_LOCATION = "silver/calendar/trade_calendar"
_FULL_FILE = "full/part-000.parquet"
_CALENDAR_COLUMNS = (
    ("exchange", "VARCHAR"),
    ("trade_date", "DATE"),
    ("is_open", "BOOLEAN"),
    ("pretrade_date", "DATE"),
)
_SECURITY_COLUMNS = tuple(
    (field.name, "DATE" if field.name in {"list_date", "delist_date"} else "VARCHAR")
    for field in fields(SecurityReferenceRow)
)
_SECURITY_TYPES = dict(_SECURITY_COLUMNS)
_SECURITY_EXPRESSIONS = {
    "list_date": "strptime(nullif(list_date, ''), '%Y%m%d')::DATE AS list_date",
    "delist_date": "strptime(nullif(delist_date, ''), '%Y%m%d')::DATE AS delist_date",
    "security_type": "'EQUITY' AS security_type",
    "source": "'tushare' AS source",
}
_SECURITY_SELECT = ", ".join(
    _SECURITY_EXPRESSIONS.get(name, name) for name, _ in _SECURITY_COLUMNS
)
_CALENDAR_SELECT = "exchange, trade_date, is_open, pretrade_date"


def _read(
    root: Path | None,
    location: str,
    sql: str,
    params: list,
    columns: tuple[tuple[str, str], ...],
    *,
    timeout_seconds: float | None = None,
) -> list[tuple]:
    if root is None:
        raise ReferenceDataReadError(f"本地 DG 根目录未配置，无法读取 {location}")
    try:
        with duckdb.connect(database=":memory:") as connection:
            timer = None
            if timeout_seconds is not None:
                timer = Timer(timeout_seconds, connection.interrupt)
                timer.daemon = True
                timer.start()
            try:
                cursor = connection.execute(
                    sql, [str(root / location / _FULL_FILE), *params]
                )
                actual = tuple((item[0], str(item[1])) for item in cursor.description)
                if actual != columns:
                    raise ReferenceDataReadError(
                        f"本地 DG 字段或类型不匹配：{location}"
                    )
                return cursor.fetchall()
            finally:
                if timer is not None:
                    timer.cancel()
    except duckdb.InterruptException as exc:
        raise TimeoutError(f"本地 DG 读取超时：{location}") from exc
    except duckdb.Error as exc:
        raise ReferenceDataReadError(f"无法读取本地 DG 数据集：{location}") from exc


class LakeTradeCalendarReader:
    def __init__(self, root: Path | None) -> None:
        self.root = root

    def _rows(
        self, statement, params, *, timeout_seconds=None
    ) -> tuple[TradeCalendarRow, ...]:
        # Keep missing mandatory keys visible even when the requested range is empty.
        statement = f"""
            WITH calendar_source AS NOT MATERIALIZED (
                SELECT {_CALENDAR_SELECT} FROM read_parquet(?, hive_partitioning=false)
            )
            SELECT {_CALENDAR_SELECT} FROM ({statement})
            UNION ALL
            SELECT NULL, NULL, NULL, NULL WHERE EXISTS (
                SELECT 1 FROM calendar_source
                WHERE nullif(trim(exchange), '') IS NULL OR trade_date IS NULL OR is_open IS NULL
            )
            ORDER BY trade_date
        """
        rows = _read(
            self.root,
            TRADE_CALENDAR_LOCATION,
            statement,
            params,
            _CALENDAR_COLUMNS,
            timeout_seconds=timeout_seconds,
        )
        keys = {(exchange, day) for exchange, day, _, _ in rows}
        if len(keys) != len(rows) or any(
            not exchange or day is None or opened is None
            for exchange, day, opened, _ in rows
        ):
            raise ReferenceDataReadError(
                f"本地 DG 交易日历主键或开市标记无效：{TRADE_CALENDAR_LOCATION}"
            )
        return tuple(TradeCalendarRow(*row) for row in rows)

    def get(self, *, exchange: str, day: date) -> TradeCalendarRow | None:
        rows = self.range_rows(exchange=exchange, start=day, end=day)
        return rows[0] if rows else None

    def range_rows(
        self,
        *,
        exchange: str,
        start: date,
        end: date,
        open_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[TradeCalendarRow, ...]:
        return self._rows(
            f"""SELECT {_CALENDAR_SELECT} FROM calendar_source
                WHERE exchange = ? AND trade_date BETWEEN ? AND ? AND (NOT ? OR is_open)
                ORDER BY trade_date""",
            [exchange, start, end, open_only],
            timeout_seconds=timeout_seconds,
        )

    def recent_open_rows(
        self,
        *,
        exchange: str,
        bound: date,
        limit: int,
        include_bound: bool = True,
        start: date | None = None,
    ) -> tuple[TradeCalendarRow, ...]:
        boundary = "<=" if include_bound else "<"
        return self._rows(
            f"""SELECT * FROM (
                    SELECT {_CALENDAR_SELECT} FROM calendar_source
                    WHERE exchange = ? AND is_open AND trade_date >= ? AND trade_date {boundary} ?
                    ORDER BY trade_date DESC LIMIT ?
                ) ORDER BY trade_date""",
            [exchange, start or date.min, bound, limit],
        )

    def context_rows(
        self,
        *,
        exchange: str,
        end: date,
        recent_open_days: int,
        start: date | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[TradeCalendarRow, ...]:
        return self._rows(
            f"""WITH calendar AS MATERIALIZED (
                    SELECT {_CALENDAR_SELECT} FROM calendar_source
                    WHERE exchange = ? AND trade_date <= ?
                ), recent_open AS (
                    SELECT trade_date FROM calendar WHERE is_open
                    ORDER BY trade_date DESC LIMIT ?
                )
                SELECT {_CALENDAR_SELECT} FROM calendar
                WHERE trade_date >= COALESCE((SELECT min(trade_date) FROM recent_open), ?)
                  AND trade_date >= ?
                ORDER BY trade_date""",
            [exchange, end, recent_open_days, end, start or date.min],
            timeout_seconds=timeout_seconds,
        )


class LakeSecurityReferenceReader:
    def __init__(self, root: Path | None) -> None:
        self.root = root

    def get(
        self, *, ts_code: str, timeout_seconds: float | None = None
    ) -> SecurityReferenceRow | None:
        return self.read_by_codes(
            ts_codes=(ts_code,), timeout_seconds=timeout_seconds
        ).get(ts_code)

    def read_by_codes(
        self, *, ts_codes: Sequence[str], timeout_seconds: float | None = None
    ) -> dict[str, SecurityReferenceRow]:
        if not ts_codes:
            return {}
        rows = _read(
            self.root,
            STOCK_BASIC_LOCATION,
            f"""SELECT {_SECURITY_SELECT} FROM read_parquet(?, hive_partitioning=false)
                WHERE ts_code IN (SELECT unnest(?))""",
            [list(ts_codes)],
            _SECURITY_COLUMNS,
            timeout_seconds=timeout_seconds,
        )
        result = {row[0]: SecurityReferenceRow(*row) for row in rows}
        if len(result) != len(rows) or any(
            not item.ts_code or not item.name for item in result.values()
        ):
            raise ReferenceDataReadError(
                f"本地 DG 股票基础信息主键或名称无效：{STOCK_BASIC_LOCATION}"
            )
        return result

    def project_by_codes(
        self,
        *,
        ts_codes: Sequence[str],
        columns: Sequence[str],
    ) -> tuple[tuple, ...]:
        if not ts_codes:
            return ()
        schema = tuple((name, _SECURITY_TYPES[name]) for name in columns)
        projection = ", ".join(
            _SECURITY_EXPRESSIONS.get(name, name) for name, _ in schema
        )
        rows = _read(
            self.root,
            STOCK_BASIC_LOCATION,
            f"""SELECT {projection} FROM read_parquet(?, hive_partitioning=false)
                WHERE ts_code IN (SELECT unnest(?))""",
            [list(ts_codes)],
            schema,
        )
        keys = [row[columns.index("ts_code")] for row in rows]
        if len(keys) != len(set(keys)) or any(not key for key in keys):
            raise ReferenceDataReadError(
                f"本地 DG 股票基础信息主键无效：{STOCK_BASIC_LOCATION}"
            )
        return tuple(rows)

    def search_a_shares(
        self,
        *,
        keyword: str,
        escaped_prefix: str,
        limit: int,
        exchanges: Sequence[str],
    ) -> tuple[tuple[str, str], ...]:
        rows = _read(
            self.root,
            STOCK_BASIC_LOCATION,
            r"""WITH candidates AS (
                    SELECT ts_code, name, upper(coalesce(symbol, '')) AS search_symbol,
                           upper(coalesce(ts_code, '')) AS search_code,
                           upper(coalesce(cnspell, '')) AS search_pinyin
                    FROM read_parquet(?, hive_partitioning=false)
                    WHERE list_status = 'L' AND curr_type = 'CNY'
                      AND exchange IN (SELECT unnest(?))
                ), matches AS (
                    SELECT ts_code, name, search_symbol, search_code,
                           search_symbol LIKE ? ESCAPE '\' AS by_symbol,
                           search_code LIKE ? ESCAPE '\' AS by_code,
                           search_pinyin LIKE ? ESCAPE '\' AS by_pinyin
                    FROM candidates
                )
                SELECT ts_code, name FROM matches
                WHERE by_symbol OR by_code OR by_pinyin
                ORDER BY CASE WHEN search_symbol = ? OR search_code = ? THEN 0
                              WHEN by_symbol THEN 1 WHEN by_code THEN 2
                              WHEN by_pinyin THEN 3 ELSE 4 END, ts_code LIMIT ?""",
            [
                list(exchanges),
                escaped_prefix,
                escaped_prefix,
                escaped_prefix,
                keyword,
                keyword,
                limit,
            ],
            (("ts_code", "VARCHAR"), ("name", "VARCHAR")),
        )
        if len({code for code, _ in rows}) != len(rows) or any(
            not code or not name for code, name in rows
        ):
            raise ReferenceDataReadError(
                f"本地 DG 股票搜索结果主键或名称无效：{STOCK_BASIC_LOCATION}"
            )
        return tuple(rows)

    def leaderboard_codes(self, *, trade_date: date) -> tuple[str, ...]:
        rows = _read(
            self.root,
            STOCK_BASIC_LOCATION,
            """SELECT ts_code FROM read_parquet(?, hive_partitioning=false)
               WHERE exchange IN ('SSE', 'SZSE') AND list_status = 'L'
                 AND strptime(nullif(list_date, ''), '%Y%m%d')::DATE <= ?
                 AND (nullif(delist_date, '') IS NULL OR strptime(delist_date, '%Y%m%d')::DATE > ?)
                 AND NOT (upper(name) LIKE 'ST%' OR upper(name) LIKE '*ST%')""",
            [trade_date, trade_date],
            (("ts_code", "VARCHAR"),),
        )
        return tuple(code for (code,) in rows)

    def suggest_equities(
        self, *, keyword: str, limit: int
    ) -> tuple[tuple[str, str], ...]:
        prefix, contains = f"{keyword}%", f"%{keyword}%"
        return tuple(
            _read(
                self.root,
                STOCK_BASIC_LOCATION,
                """SELECT ts_code, name FROM read_parquet(?, hive_partitioning=false)
               WHERE ts_code ILIKE ? OR symbol ILIKE ? OR cnspell ILIKE ? OR name ILIKE ?
               ORDER BY CASE WHEN ts_code ILIKE ? THEN 0 WHEN symbol ILIKE ? THEN 1
                             WHEN cnspell ILIKE ? THEN 2 WHEN name ILIKE ? THEN 3
                             ELSE 4 END, ts_code LIMIT ?""",
                [
                    prefix,
                    prefix,
                    prefix,
                    contains,
                    prefix,
                    prefix,
                    prefix,
                    prefix,
                    limit,
                ],
                (("ts_code", "VARCHAR"), ("name", "VARCHAR")),
            )
        )

    def planning_equities(self) -> tuple[SecurityPlanningRow, ...]:
        rows = _read(
            self.root,
            STOCK_BASIC_LOCATION,
            """SELECT ts_code, name, list_status, 'tushare' AS source
               FROM read_parquet(?, hive_partitioning=false)
               WHERE list_status IN ('L', 'P', 'D')""",
            [],
            tuple(
                (name, "VARCHAR")
                for name in ("ts_code", "name", "list_status", "source")
            ),
        )
        if len({row[0] for row in rows}) != len(rows) or any(
            not row[0] or not row[1] for row in rows
        ):
            raise ReferenceDataReadError(
                f"本地 DG 股票规划对象主键或名称无效：{STOCK_BASIC_LOCATION}"
            )
        return tuple(SecurityPlanningRow(*row) for row in rows)
