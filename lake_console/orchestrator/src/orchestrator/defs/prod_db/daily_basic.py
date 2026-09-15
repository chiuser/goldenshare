"""Bounded, explicit-field daily-basic history reads. Not a daily source."""

from contextlib import contextmanager
from datetime import date

from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_FIELDS,
    DailyBasicValidationError,
    daily_basic_trade_date,
)

HISTORY_BATCH_SIZE = 10_000
HISTORY_STATEMENT_TIMEOUT_MS = 10_000


def daily_basic_history_query(start, end, last_key=None):
    start, end = daily_basic_trade_date(start), daily_basic_trade_date(end)
    if start > end:
        raise DailyBasicValidationError("history_range_reversed")
    fields = ", ".join(
        "to_char(trade_date, 'YYYYMMDD') AS trade_date"
        if name == "trade_date"
        else name
        for name in DAILY_BASIC_FIELDS
    )
    params = {
        "start": date.fromisoformat(start),
        "end": date.fromisoformat(end),
        "batch_size": HISTORY_BATCH_SIZE,
    }
    boundary = ""
    if last_key is not None:
        code, day = last_key
        if not isinstance(code, str) or not code or code != code.strip():
            raise DailyBasicValidationError("history_invalid_last_key")
        parsed = date.fromisoformat(day)
        if not params["start"] <= parsed <= params["end"]:
            raise DailyBasicValidationError("history_last_date_out_of_range")
        params.update(last_code=code, last_date=parsed)
        boundary = " AND (ts_code, trade_date) > (%(last_code)s, %(last_date)s)"
    return (
        (
            f"SELECT {fields} FROM raw_tushare.daily_basic "
            "WHERE trade_date >= %(start)s AND trade_date <= %(end)s"
            f"{boundary} ORDER BY daily_basic.ts_code, daily_basic.trade_date LIMIT %(batch_size)s"
        ),
        params,
    )


class DailyBasicHistorySource:
    def __init__(self, resource):
        self.resource = resource

    @contextmanager
    def _cursor(self):
        with (
            self.resource.connect_readonly_transaction() as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SET LOCAL statement_timeout = %s", (HISTORY_STATEMENT_TIMEOUT_MS,)
            )
            yield cursor

    def fetch_page(self, start, end, last_key=None):
        sql, params = daily_basic_history_query(start, end, last_key)
        with self._cursor() as cursor:
            cursor.execute(sql, params)
            if tuple(column[0] for column in cursor.description) != DAILY_BASIC_FIELDS:
                raise DailyBasicValidationError("prod_history_field_order")
            return cursor.fetchmany(HISTORY_BATCH_SIZE)

    def inspect(self, start, end):
        """Catalog facts and non-executing plans; no business-row scan."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT column_name, data_type, is_nullable, numeric_precision, numeric_scale "
                "FROM information_schema.columns WHERE table_schema='raw_tushare' "
                "AND table_name='daily_basic' ORDER BY ordinal_position"
            )
            columns = cursor.fetchall()
            cursor.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='raw_tushare' AND tablename='daily_basic' ORDER BY indexname"
            )
            indexes = cursor.fetchall()
            cursor.execute(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_class c ON c.oid=i.indrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, position) "
                "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum "
                "WHERE n.nspname='raw_tushare' AND c.relname='daily_basic' "
                "AND i.indisprimary ORDER BY k.position"
            )
            primary_key = [row[0] for row in cursor.fetchall()]
            plans = []
            for key in (None, ("000001.SZ", start)):
                sql, params = daily_basic_history_query(start, end, key)
                cursor.execute("EXPLAIN (FORMAT JSON) " + sql, params)
                plans.append(cursor.fetchone()[0])
        return {
            "columns": columns,
            "indexes": indexes,
            "primary_key": primary_key,
            "explain": plans,
            "business_rows_read": 0,
        }
