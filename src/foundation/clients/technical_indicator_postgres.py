"""Bounded PostgreSQL input for the technical indicator kernel."""

from contextlib import contextmanager
from itertools import groupby
from operator import itemgetter
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from goldenshare_technical_indicators.errors import (
    CalculationDeadlineError, ResourceLimitError, SourceContractError, SourceReadError,
    SourceUnsupportedError,
)
from goldenshare_technical_indicators.sources.contracts import PriceReadSelection, SourceBatch, SourceDescription

from .technical_indicator_stock_daily import daily_price_projection, full_day_suspension, require_stock_daily, scheduled_stock_days


def _identifier(value):
    return '"' + value.replace('"', '""') + '"'


def _relation(target):
    return ".".join(_identifier(target.location[key]) for key in ("schema", "relation"))


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
        require_stock_daily(requirement, "prod_pg")
        return _PostgresPriceLocator(self, requirement, read_context, executor.control)

    def open(self, executor, description, requirement, *, read_context):
        connection = self._connection(read_context, executor.control)
        selection = description.selection
        columns = ", ".join(_identifier(name) for name in description.source_projection)
        statement = (
            f"SELECT {columns} FROM {_relation(requirement.target)} "
            "WHERE ts_code = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date"
        )
        return _PostgresPriceStream(
            connection, statement, (requirement.ts_code, selection.read_start, selection.read_end),
            description, read_context, executor.control, requirement.batch_rows,
        )

    def expected_positions(self, requirement, selection, *, read_context, control):
        connection = self._connection(read_context, control)
        start, end = min(requirement.start, selection.read_start), requirement.end
        calendar_target = self._config.resolve_dataset_location("trade_calendar")
        lifecycle_target = self._config.resolve_dataset_location("stock_lifecycle")
        suspension_target = self._config.resolve_dataset_location("stock_suspend_daily")
        lifecycle = _query(
            connection, control, f"SELECT list_date, delist_date FROM {_relation(lifecycle_target)} WHERE ts_code = %s",
            (requirement.ts_code,),
        )
        calendar = _query(connection, control, f"""
            SELECT trade_date, is_open FROM {_relation(calendar_target)}
            WHERE exchange = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date
        """, (calendar_target.location["filters"]["exchange"], start, end))
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
        raise SourceUnsupportedError("PostgreSQL stock daily adjustment is not enabled")

    def prepare_factors(self, executor, description, requirement, trade_dates, *, table_name, read_context):
        raise SourceUnsupportedError("PostgreSQL stock daily adjustment is not enabled")


class _PostgresPriceLocator:
    def __init__(self, source, requirement, read_context, control):
        self._source = source
        self._requirement = requirement
        self._read_context = read_context
        self._control = control
        self._described = False

    def describe(self):
        if self._described:
            raise SourceContractError("A source locator can only describe one request")
        self._described = True
        requirement, config = self._requirement, self._read_context.config
        connection = self._source._connection(self._read_context, self._control)
        relation = _relation(requirement.target)
        count, first, last = _query(connection, self._control, f"""
            SELECT count(*), min(trade_date), max(trade_date) FROM (
                SELECT trade_date FROM {relation}
                WHERE ts_code = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date LIMIT %s
            ) AS target
        """, (requirement.ts_code, requirement.start, requirement.end, config.max_output_rows + 1))[0]
        self._read_context.record_locator_rows(count)
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
            scanned, oldest = _query(connection, self._control, f"""
                SELECT count(*), min(trade_date) FILTER (WHERE ordinal <= %s) FROM (
                    SELECT trade_date, row_number() OVER (ORDER BY trade_date DESC) AS ordinal
                    FROM {relation} WHERE ts_code = %s AND trade_date < %s
                    ORDER BY trade_date DESC LIMIT %s
                ) AS preceding
            """, (wanted, requirement.ts_code, first, wanted + 1))[0]
            self._read_context.record_locator_rows(scanned)
            if needs_origin and scanned > wanted:
                raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
            selection = PriceReadSelection(first, last, oldest or first, last, count, min(scanned, wanted),
                                           scanned <= wanted, ())
        physical, standard = daily_price_projection(requirement.history.fields)
        return SourceDescription(
            source_id=requirement.target.dataset_id, contract_version="1", input_adjustment="none",
            basis_rule=None, basis_date=None, basis_value=None, price_unit="CNY",
            volume_unit="lot", amount_unit="thousand_CNY", timezone="Asia/Shanghai",
            period_label_rule="period_start", history_origin_rule="earliest_available_formal_row",
            available_through=None, supports_partial_period=False, supported_adjustment_paths=(("none", "none"),),
            converted=False, selection=selection, source_projection=physical, standard_projection=standard,
        )

    def close(self):
        self._described = True


class _PostgresPriceStream:
    def __init__(self, connection, sql, params, description, read_context, control, batch_rows):
        import pyarrow as pa

        self._connection, self._sql, self._params = connection, sql, params
        self._context, self._control = read_context, control
        self._columns, self._batch_rows = description.source_projection, batch_rows
        types = {"trade_date": pa.date32(), "ts_code": pa.string(), "vol": pa.decimal128(20, 4),
                 "amount": pa.decimal128(20, 4)}
        self._schema = pa.schema((name, types.get(name, pa.decimal128(18, 4))) for name in self._columns)
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
        self._context.record_price_rows(len(rows))
        try:
            columns = [pa.array([row[i] for row in rows], type=field.type) for i, field in enumerate(self._schema)]
            self._current = pa.RecordBatch.from_arrays(columns, schema=self._schema)
        except (pa.ArrowException, TypeError, ValueError) as exc:
            raise SourceContractError("PostgreSQL prices do not match their declared fields") from exc
        first = self._delivered + 1
        self._delivered += len(rows)
        return SourceBatch(self._current, first, self._delivered, len(rows), len(rows), 0, 0)

    def release_current_batch(self):
        self._current = None

    def close(self):
        self.release_current_batch()
        if self._cursor is not None:
            self._cursor.close()
            self._cursor = None
        self._closed = True
