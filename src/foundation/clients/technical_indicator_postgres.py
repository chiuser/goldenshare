"""Bounded PostgreSQL input for the technical indicator kernel."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import time
from itertools import groupby
from operator import itemgetter
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from goldenshare_technical_indicators.calculation.calculation import SqlStep
from goldenshare_technical_indicators.errors import (
    CalculationDeadlineError, ResourceLimitError, SourceContractError, SourceReadError,
    SourceUnsupportedError,
)
from goldenshare_technical_indicators.sources.contracts import PriceReadSelection, SourceBatch, SourceDescription

from .technical_indicator_index_minutes import index_minute_projection, index_minute_volume_unit
from .technical_indicator_index_period import (
    INDEX_PERIOD_DATASETS, check_index_period_cutoff, check_period_key, describe_index_period,
    index_period_positions, period_bounds, period_request_start, preceding_limit, require_index_period,
)
from .technical_indicator_stock_daily import (
    INDEX_DAILY_ORIGINS, daily_adjustment_paths, daily_price_projection, full_day_suspension,
    scheduled_open_days, scheduled_stock_days,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_OPENING_BAR = "b.trade_time::time = TIME '09:35'"


def _identifier(value):
    return '"' + value.replace('"', '""') + '"'


def _relation(target):
    return ".".join(_identifier(target.location[key]) for key in ("schema", "relation"))


def _price_scope(requirement, *, requested_columns=()):
    relation = _relation(requirement.target)
    if requirement.period == "day" or requirement.period in INDEX_PERIOD_DATASETS:
        return f"{relation} AS b", "b.ts_code = %s", (requirement.ts_code,)
    # One indexed lookup for a requested opening bar. The backing table has
    # one row per (ts_code, freq, trade_time). LIMIT keeps the lateral lookup
    # gated by the 09:35 timestamp in PostgreSQL's execution plan.
    auction_columns = ["a.trade_time"]
    if {"open", "high", "low"} & set(requested_columns):
        auction_columns.append("a.close")
    auction_columns.extend(f'a."{name}"' for name in ("vol", "amount") if name in requested_columns)
    source = f"""{relation} AS b
        LEFT JOIN LATERAL (
            SELECT {", ".join(auction_columns)} FROM {relation} AS a
            WHERE {_OPENING_BAR} AND a.ts_code = b.ts_code AND a.freq = b.freq
            AND a.trade_time = b.trade_time - INTERVAL '5 minutes' LIMIT 1
        ) AS auction ON TRUE"""
    filters = f"""b.ts_code = %s AND b.freq = %s
        AND b.trade_time::time <> TIME '09:30'
        AND (NOT ({_OPENING_BAR}) OR auction.trade_time IS NOT NULL)"""
    return source, filters, (requirement.ts_code, requirement.target.location["filters"]["freq"])


def _minute_price_column(name):
    column = f"b.{_identifier(name)}"
    if name == "open":
        combined = "auction.close"
    elif name in ("high", "low"):
        operation = "GREATEST" if name == "high" else "LEAST"
        combined = (f"CASE WHEN {column} > '-Infinity'::float8 AND {column} < 'Infinity'::float8 "
                    "AND auction.close > '-Infinity'::float8 AND auction.close < 'Infinity'::float8 "
                    f"THEN {operation}({column}, auction.close) END")
    elif name in ("vol", "amount"):
        combined = (f"CASE WHEN {column} IS NULL THEN auction.{name} "
                    f"WHEN auction.{name} IS NULL THEN {column} ELSE {column} + auction.{name} END")
    else:
        return column
    return f"CASE WHEN {_OPENING_BAR} THEN {combined} ELSE {column} END AS {_identifier(name)}"


@contextmanager
def _operation(connection, control, *, deadline=True):
    driver = connection.connection.driver_connection

    def interrupt():
        driver.cancel_safe(timeout=control.config.cleanup_reserve_ms / 1000)

    control.set_source_interrupt(interrupt)
    try:
        control.check_active()
        if deadline:
            remaining = max(1, int((control.work_until - control.clock()) * 1000))
            connection.exec_driver_sql(
                "SELECT set_config('statement_timeout', %s, true)", (str(remaining),)
            ).close()
        yield
        control.check_active()
    except SQLAlchemyError as exc:
        control.check_active()
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "57014":
            raise CalculationDeadlineError("PostgreSQL read deadline was reached") from exc
        raise SourceReadError("The PostgreSQL market data query failed") from exc
    finally:
        control.set_source_interrupt(None)


def _query(connection, control, sql, params):
    with _operation(connection, control):
        with connection.exec_driver_sql(sql, params) as result:
            return result.fetchall()


class PostgresTechnicalIndicatorPriceSource:
    def __init__(self, config, session_factory):
        self._config = config
        self._session_factory = session_factory

    def _connection(self, read_context, control):
        control.check_active()
        try:
            connection, first = read_context.open_postgres(self._session_factory)
        except SQLAlchemyError as exc:
            control.check_active()
            raise SourceReadError("The PostgreSQL source connection failed") from exc
        if first:
            with _operation(connection, control, deadline=False):
                connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY").close()
        return connection

    def create_locator(self, executor, requirement, *, read_context):
        if requirement.period in INDEX_PERIOD_DATASETS:
            require_index_period(requirement, "prod_pg")
        elif requirement.period.endswith("m"):
            index_minute_volume_unit(requirement, "prod_pg")
        else:
            daily_adjustment_paths(requirement, "prod_pg")
        return _PostgresPriceLocator(self, requirement, read_context, executor.control)

    def open(self, executor, description, requirement, *, read_context):
        connection = self._connection(read_context, executor.control)
        selection = description.selection
        minute = requirement.period.endswith("m")
        project = _minute_price_column if minute else _identifier
        columns = ", ".join(project(name) for name in description.source_projection)
        relation, filters, identity = _price_scope(requirement, requested_columns=description.source_projection)
        position = "b.trade_time" if minute else "b.trade_date"
        start, end = selection.read_start, selection.read_end
        if requirement.period in INDEX_PERIOD_DATASETS:
            keys = read_context.source_state.keys
            position = "b.period_start_date"
            start, end = keys[0][0], keys[-1][0]
        elif minute:
            start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
        statement = (
            f"SELECT {columns} FROM {relation} "
            f"WHERE {filters} AND {position} BETWEEN %s AND %s ORDER BY {position}"
        )
        return _PostgresPriceStream(
            connection, statement, (*identity, start, end),
            description, read_context, executor.control, requirement.batch_rows, minute=minute,
        )

    def expected_positions(self, requirement, selection, *, read_context, control):
        connection = self._connection(read_context, control)
        dates = read_context.source_state
        if requirement.period in INDEX_PERIOD_DATASETS:
            start, end = dates.calendar_start, dates.calendar_end
        else:
            start, end = min(requirement.start, selection.read_start), requirement.end
        index = requirement.target.dataset_id == "index_daily"
        if index:
            start = max(start, INDEX_DAILY_ORIGINS["prod_pg"])
        calendar_target = self._config.resolve_dataset_location("trade_calendar")
        calendar = _query(connection, control, f"""
            SELECT trade_date, is_open FROM {_relation(calendar_target)}
            WHERE exchange = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date
        """, (calendar_target.location["filters"]["exchange"], start, end))
        if requirement.period in INDEX_PERIOD_DATASETS:
            yield from index_period_positions(calendar, dates, requirement.period)
            return
        if index:
            yield from scheduled_open_days(calendar, start, end)
            return
        lifecycle_target = self._config.resolve_dataset_location("stock_lifecycle")
        suspension_target = self._config.resolve_dataset_location("stock_suspend_daily")
        lifecycle = _query(
            connection, control, f"SELECT list_date, delist_date FROM {_relation(lifecycle_target)} WHERE ts_code = %s",
            (requirement.ts_code,),
        )
        suspensions = _query(connection, control, f"""
            SELECT trade_date, suspend_type, suspend_timing FROM {_relation(suspension_target)}
            WHERE ts_code = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date
        """, (requirement.ts_code, start, end))
        suspended = {
            day for day, rows in groupby(suspensions, key=itemgetter(0))
            if full_day_suspension((kind, timing) for _, kind, timing in rows)
        }
        for day in scheduled_stock_days(calendar, lifecycle, start, end):
            control.check_active()
            if day not in suspended:
                yield day

    def prepare_basis(self, executor, description, requirement, *, table_name, read_context):
        connection = self._connection(read_context, executor.control)
        relation = _relation(self._config.resolve_dataset_location("stock_adj_factor"))
        rows = _query(connection, executor.control, f"""
            SELECT trade_date, adj_factor FROM {relation}
            WHERE ts_code = %s ORDER BY trade_date DESC LIMIT 1
        """, (requirement.ts_code,))
        if not rows:
            raise SourceContractError("The declared daily conversion has no available basis row")
        day, raw_value = rows[0]
        value = float(raw_value) if raw_value is not None else None
        table = _identifier(table_name)
        executor.execute(SqlStep(
            "prepare_basis", f"CREATE TEMP TABLE {table} AS SELECT ?::DATE AS basis_date, ?::DOUBLE AS basis_value",
            (day, value), (), (table_name,), 1,
        ))
        return replace(description, basis_date=day, basis_value=value)

    def prepare_factors(self, executor, description, requirement, trade_dates, *, table_name, read_context):
        connection = self._connection(read_context, executor.control)
        relation = _relation(self._config.resolve_dataset_location("stock_adj_factor"))
        rows = _query(connection, executor.control, f"""
            SELECT trade_date, adj_factor FROM {relation} WHERE ts_code = %s AND trade_date = ANY(%s)
        """, (requirement.ts_code, list(trade_dates)))
        table = _identifier(table_name)
        if rows:
            values = ", ".join("(?::DATE, ?::DOUBLE)" for _ in rows)
            sql = f"SELECT * FROM (VALUES {values}) AS f(trade_date, adj_factor)"
            bindings = tuple(item for day, factor in rows for item in (
                day, float(factor) if factor is not None else None,
            ))
        else:
            sql = "SELECT NULL::DATE AS trade_date, NULL::DOUBLE AS adj_factor WHERE FALSE"
            bindings = ()
        executor.execute(SqlStep("prepare_factors", f"CREATE TEMP TABLE {table} AS {sql}",
                                 bindings, (), (table_name,), len(rows)))


class _PostgresPriceLocator:
    def __init__(self, source, requirement, read_context, control):
        self._source = source
        self._requirement = requirement
        self._read_context = read_context
        self._control = control
        self._described = False

    def _describe_index_period(self, connection):
        requirement, context = self._requirement, self._read_context
        relation, filters, identity = _price_scope(requirement)
        scope = f"SELECT b.period_start_date, b.trade_date FROM {relation} WHERE {filters}"
        first = _query(connection, self._control, f"{scope} ORDER BY b.period_start_date LIMIT 1", identity)
        if not first:
            return describe_index_period(requirement, context, (), (), None, None)
        latest = _query(connection, self._control, f"{scope} ORDER BY b.period_start_date DESC LIMIT 1", identity)[0]
        check_period_key(latest, requirement.period)
        start = period_request_start(requirement)
        last_start, last_end = period_bounds(requirement.end, requirement.period)
        if start > last_start:
            return describe_index_period(requirement, context, (), (), first[0], latest)
        last_period = _query(connection, self._control, f"""
            {scope} AND b.period_start_date BETWEEN %s AND %s ORDER BY b.period_start_date LIMIT 2
        """, (*identity, last_start, last_end))
        if len(last_period) > 1:
            raise SourceContractError("Index period positions are duplicated or out of order")
        if last_period:
            check_period_key(last_period[0], requirement.period)
            check_index_period_cutoff(last_period[0][1], requirement, last_end)
        targets = _query(connection, self._control, f"""
            {scope} AND b.period_start_date BETWEEN %s AND %s ORDER BY b.period_start_date LIMIT %s
        """, (*identity, start, last_end, context.config.max_output_rows + 1))
        context.record_locator_rows(len(first) + 1 + len(last_period) + len(targets))
        if len(targets) > context.config.max_output_rows:
            raise ResourceLimitError("Target positions exceed max_output_rows")
        preceding = []
        if targets:
            wanted, _ = preceding_limit(context.config, requirement, len(targets))
            preceding = _query(connection, self._control, f"""
                {scope} AND b.period_start_date < %s ORDER BY b.period_start_date DESC LIMIT %s
            """, (*identity, targets[0][0], wanted + 1))
            context.record_locator_rows(len(preceding))
            preceding.reverse()
        return describe_index_period(requirement, context, targets, preceding, first[0], latest)

    def describe(self):
        if self._described:
            raise SourceContractError("A source locator can only describe one request")
        self._described = True
        requirement, config = self._requirement, self._read_context.config
        connection = self._source._connection(self._read_context, self._control)
        if requirement.period in INDEX_PERIOD_DATASETS:
            return self._describe_index_period(connection)
        minute = requirement.period.endswith("m")
        relation, filters, identity = _price_scope(requirement)
        position = "b.trade_time" if minute else "b.trade_date"
        start, end = requirement.start, requirement.end
        if minute:
            start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
        auction_keys = "count(*) FILTER (WHERE position::time = TIME '09:35')" if minute else "0"
        count, first, last, extra_keys = _query(connection, self._control, f"""
            SELECT count(*), min(position), max(position), {auction_keys} FROM (
                SELECT {position} AS position FROM {relation}
                WHERE {filters} AND {position} BETWEEN %s AND %s ORDER BY {position} LIMIT %s
            ) AS target
        """, (*identity, start, end, config.max_output_rows + 1))[0]
        self._read_context.record_locator_rows(count + extra_keys)
        if count > config.max_output_rows:
            raise ResourceLimitError("Target positions exceed max_output_rows")
        selection = PriceReadSelection(None, None, None, None, 0, 0, False, ())
        if count:
            available = config.max_input_rows - count
            if available < 0:
                raise ResourceLimitError("Selected input exceeds max_input_rows")
            history = requirement.history
            needs_origin = history.requires_source_origin or history.warmup_rows > available
            wanted = available if needs_origin else history.warmup_rows
            scanned, oldest, extra_keys = _query(connection, self._control, f"""
                SELECT count(*), min(position) FILTER (WHERE ordinal <= %s), {auction_keys} FROM (
                    SELECT {position} AS position, row_number() OVER (ORDER BY {position} DESC) AS ordinal
                    FROM {relation} WHERE {filters} AND {position} < %s
                    ORDER BY {position} DESC LIMIT %s
                ) AS preceding
            """, (wanted, *identity, first, wanted + 1))[0]
            self._read_context.record_locator_rows(scanned + extra_keys)
            if needs_origin and scanned > wanted:
                raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
            if minute:
                first, last = first.replace(tzinfo=_SHANGHAI), last.replace(tzinfo=_SHANGHAI)
                oldest = oldest.replace(tzinfo=_SHANGHAI) if oldest is not None else None
            selection = PriceReadSelection(first, last, oldest or first, last, count, min(scanned, wanted),
                                           scanned <= wanted, ())
        project = index_minute_projection if minute else daily_price_projection
        physical, standard = project(requirement.history.fields)
        volume_unit = index_minute_volume_unit(requirement, "prod_pg") if minute else "lot"
        adjustments = (("none", "none"),) if minute else daily_adjustment_paths(requirement, "prod_pg")
        converted = requirement.target_adjustment == "qfq"
        return SourceDescription(
            source_id=requirement.target.dataset_id, contract_version="1", input_adjustment="none",
            basis_rule="latest_available_factor" if converted else None, basis_date=None, basis_value=None,
            price_unit="index_point" if minute or requirement.target.dataset_id == "index_daily" else "CNY",
            volume_unit=volume_unit, amount_unit="CNY" if minute else "thousand_CNY", timezone="Asia/Shanghai",
            period_label_rule="trade_time" if minute else "period_start", history_origin_rule="earliest_available_formal_row",
            available_through=None, supports_partial_period=False, supported_adjustment_paths=adjustments,
            converted=converted, selection=selection, source_projection=physical, standard_projection=standard,
        )

    def close(self):
        self._described = True


class _PostgresPriceStream:
    def __init__(self, connection, sql, params, description, read_context, control, batch_rows, *, minute):
        import pyarrow as pa

        self._connection, self._sql, self._params = connection, sql, params
        self._context, self._control = read_context, control
        self._columns, self._batch_rows = description.source_projection, batch_rows
        self._period_dates = read_context.source_state
        types = {"trade_date": pa.date32(), "period_start_date": pa.date32(),
                 "ts_code": pa.string(), "vol": pa.decimal128(20, 4),
                 "amount": pa.decimal128(20, 4)}
        fallback = pa.decimal128(18, 4)
        self._minute_time_index = None
        if minute:
            types = {"trade_date": pa.date32(), "trade_time": pa.timestamp("us"),
                     "ts_code": pa.string(), "freq": pa.string()}
            fallback = pa.float64()
            self._minute_time_index = self._columns.index("trade_time")
        self._schema = pa.schema((name, types.get(name, fallback)) for name in self._columns)
        self._cursor: Any = None
        self._current = None
        self._delivered = 0
        self._closed = self._exhausted = False

    def next_batch(self, max_rows):
        import pyarrow as pa

        if self._closed or self._current is not None or max_rows != self._batch_rows:
            raise SourceContractError("PostgreSQL price stream is not ready for the next batch")
        if self._exhausted:
            return None
        with _operation(self._connection, self._control):
            if self._cursor is None:
                self._cursor = self._connection.exec_driver_sql(
                    self._sql, self._params, execution_options={"stream_results": True, "max_row_buffer": max_rows},
                )
            rows = self._cursor.fetchmany(max_rows)
        if not rows:
            self._exhausted = True
            return None
        auction_rows = 0
        if self._minute_time_index is not None:
            auction_rows = sum(row[self._minute_time_index].time() == time(9, 35) for row in rows)
        if self._period_dates is not None:
            start, cutoff = (self._columns.index(name) for name in ("period_start_date", "trade_date"))
            self._period_dates.check_delivery(self._delivered, [(row[start], row[cutoff]) for row in rows])
        self._context.record_price_rows(len(rows), additional_source_rows=auction_rows)
        try:
            columns = [pa.array([row[i] for row in rows], type=field.type) for i, field in enumerate(self._schema)]
            self._current = pa.RecordBatch.from_arrays(columns, schema=self._schema)
        except (pa.ArrowException, TypeError, ValueError) as exc:
            raise SourceContractError("PostgreSQL prices do not match their declared fields") from exc
        first = self._delivered + 1
        self._delivered += len(rows)
        return SourceBatch(self._current, first, self._delivered, len(rows) + auction_rows, len(rows), 0, 0)

    def release_current_batch(self):
        self._current = None

    def close(self):
        self.release_current_batch()
        if self._cursor is not None:
            self._cursor.close()
            self._cursor = None
        self._closed = True
