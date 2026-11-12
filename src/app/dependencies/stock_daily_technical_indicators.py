"""Stock daily composition: one worker, request-owned DB resources, original DTO.

The resource/response/lifespan sequences follow integration LLD §§08–11.
Importing this module does not create a runtime or a database session.
"""
from contextlib import asynccontextmanager

import anyio
from fastapi import Request
from starlette.responses import Response

from src.app.exceptions import WebAppError
from src.app.runtime.technical_indicators.composition import create_runtime
from src.app.runtime.technical_indicators.execution import _execute
from src.biz.api.wealth.market.stock_detail_dependencies import (
    StockDailyKlineBackend, get_stock_daily_kline_backend,
)
from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import StockDetailNotFoundError
from src.biz.queries.wealth.market.stock_detail.stock_detail_query import StockDetailQuery
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_calculations import (
    STOCK_DAILY_ALGORITHM_VERSIONS, STOCK_DAILY_CALCULATIONS,
    build_calculation_request, validate_stock_daily_request,
)
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
from src.db import get_session_factory
from src.foundation.clients.local_lake.stock_daily_reader import StockDailyLakeReader
from src.foundation.config.settings import Settings, get_settings
from goldenshare_technical_indicators.errors import (
    CalculationDeadlineError, CalculationUnsupportedError, ResourceCleanupError,
    SourceReadError, SourceUnsupportedError,
)
from goldenshare_technical_indicators.service import (
    TechnicalIndicatorService, raise_primary_or_cleanup_error_if_any,
)
from goldenshare_technical_indicators.sources.stock_daily import StockDailyPriceSource


from contextlib import contextmanager
from math import ceil
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from psycopg import Error as PsycopgError

@contextmanager
def open_stock_daily_read_session(session_factory, control):
    session = connection = None
    listener_attempted = False
    phase = "session"
    primary = None

    def set_timeout(conn, cursor, statement, parameters, context, executemany):
        control.check_active()
        remaining = control.work_until - control.clock()
        if remaining <= 0:
            raise CalculationDeadlineError("stock_daily_database/deadline")
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(ceil(remaining * 1000)),),
        )

    try:
        try:
            control.check_active()
            session = session_factory()
            phase = "bind"
            dialect = session.get_bind().dialect
            if (dialect.name, dialect.driver) != ("postgresql", "psycopg"):
                raise SourceUnsupportedError("stock_daily_database/unsupported_driver")
            control.check_active()
            phase = "connection"
            connection = session.connection(
                execution_options={"postgresql_readonly": True},
            )
            phase = "listener"
            listener_attempted = True
            event.listen(connection, "before_cursor_execute", set_timeout)
            control.check_active()
            phase = "query"
            yield session
            control.check_active()
        except (SQLAlchemyError, PsycopgError) as error:
            control.check_active()  # 已取消/到期时抛原控制分类
            raise SourceReadError(
                "stock_daily_database/" + phase + "/" + type(error).__name__
            ) from error
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_notes = []
        first_cleanup_error = None
        invalidate_attempted = False

        def record_cleanup(stage, error):
            nonlocal first_cleanup_error
            cleanup_notes.append(stage + ":" + type(error).__name__)
            if primary is None and first_cleanup_error is None:
                first_cleanup_error = error

        def discard_connection():
            nonlocal invalidate_attempted
            if invalidate_attempted:
                return
            invalidate_attempted = True
            try:
                if connection is not None:
                    if not connection.closed:
                        connection.invalidate()
                elif session is not None:
                    session.invalidate()
            except BaseException as error:
                record_cleanup("invalidate", error)

        try:
            if connection is not None and listener_attempted:
                try:
                    if event.contains(connection, "before_cursor_execute", set_timeout):
                        event.remove(connection, "before_cursor_execute", set_timeout)
                except BaseException as error:
                    record_cleanup("remove_listener", error)
                    discard_connection()
            if session is not None:
                try:
                    session.close()  # 正常资源归还唯一入口，不commit
                except BaseException as error:
                    record_cleanup("close_session", error)
                    discard_connection()
                    if connection is not None:
                        try:
                            connection.close()
                        except BaseException as error:
                            record_cleanup("close_connection", error)
        finally:
            session = connection = None

        if cleanup_notes:
            if primary is not None:
                primary.add_note("stock_daily_database cleanup: " + ", ".join(cleanup_notes))
            elif not isinstance(first_cleanup_error, Exception):
                raise first_cleanup_error
            else:
                raise ResourceCleanupError(
                    "stock_daily_database cleanup: " + ", ".join(cleanup_notes)
                ) from first_cleanup_error


class StockDailyKlineAppBackend:
    def __init__(self, runtime, session_factory_provider=get_session_factory, *, settings: Settings):
        self.runtime = runtime
        self.session_factory_provider = session_factory_provider
        self.service = StockDailyKlineService()
        self._price_query = StockDetailQuery()
        self._use_dg = settings.app_env.strip().lower() in {"dev", "local"}
        self._price_source_id = ("dg_silver_stock_factor_pro" if self._use_dg
                                 else "prod_core_serving_equity_factor_pro")
        self._source_tables = (
            "core_serving.security_serving",
            "dg.silver_stock_factor_pro" if self._use_dg else "core_serving.equity_factor_pro",
        )
        for item in STOCK_DAILY_CALCULATIONS:
            definition = self.runtime.registry.resolve(item.calculation_id)
            if (definition.algorithm_version !=
                    STOCK_DAILY_ALGORITHM_VERSIONS[item.calculation_id]
                    or "day" not in definition.supported_periods):
                raise CalculationUnsupportedError("Stock daily definition changed")

    def response(self, request, *, arrived_at):
        return StockDailyKlineResponse(self, request, arrived_at)

    def validate_before_wait(self, request):
        try:
            validate_stock_daily_request(request)
        except ValueError as error:
            raise WebAppError(status_code=400, code="400001",
                              message=str(error)) from error
        return request

    def work(self, request, control):
        reader = snapshot = price_source = result = dto = payload = None
        session = load_rows = read_previous = page_prices = calculation = None
        primary_error = None
        cleanup_errors = ()
        try:
            control.check_active()
            if self._use_dg:
                reader = StockDailyLakeReader(self.runtime.config)
            with open_stock_daily_read_session(
                self.session_factory_provider(), control,
            ) as session:
                def load_rows(code, end, start, count):
                    if reader is not None:
                        return reader.load_kline_rows(code, end, start, count, control.check_active)
                    return self._price_query.load_kline_rows(
                        session, ts_code=code, end_date=end, start_date=start, limit=count,
                    )
                snapshot = self.service.prepare(session, request, load_rows=load_rows)
            session = load_rows = None
            control.check_active()
            if snapshot.bars:
                def read_previous(before, count):
                    if reader is not None:
                        values = reader.load_previous_kline_rows(
                            snapshot.ts_code, before, count, control.check_active,
                        )
                    else:
                        with open_stock_daily_read_session(self.session_factory_provider(), control) as prior:
                            values = self._price_query.load_previous_kline_rows(
                                prior, ts_code=snapshot.ts_code, before=before, limit=count,
                            )
                    return tuple({"trade_date": r["trade_date"], "high": r["high_qfq"],
                                  "low": r["low_qfq"], "close": r["close_qfq"]} for r in values)
                page_prices = tuple({"trade_date": r.trade_date, "high": r.high_qfq,
                                     "low": r.low_qfq, "close": r.close_qfq} for r in snapshot.bars)
                price_source = StockDailyPriceSource(
                    page_prices, read_previous, source_id=self._price_source_id,
                )
                page_prices = None
                calculation = build_calculation_request(snapshot)
                result = TechnicalIndicatorService(
                    source=price_source, registry=self.runtime.registry,
                    config=self.runtime.config, control=control,
                ).calculate(calculation)
                calculation = read_previous = price_source = None
            control.check_active()
            dto = self.service.assemble(snapshot, result, source_tables=self._source_tables)
            snapshot = result = None
            payload = dto.model_dump(
                mode="json", by_alias=True,
                exclude_none=False, exclude_unset=False,
            )
            dto = None
            control.check_active()
            return payload
        except BaseException as error:
            primary_error = error
            raise
        finally:
            if reader is not None:
                try:
                    reader.close()
                except BaseException as error:
                    cleanup_errors = (error,)
            reader = snapshot = price_source = result = dto = payload = None
            session = load_rows = read_previous = page_prices = calculation = None
            if cleanup_errors:
                raise_primary_or_cleanup_error_if_any(primary_error, cleanup_errors)

class StockDailyKlineResponse(Response):
    def __init__(self, backend, request, arrived_at):
        super().__init__(content=b"", media_type="application/json")
        self.backend, self.request, self.arrived_at = backend, request, arrived_at

    async def __call__(self, scope, receive, send):
        try:
            await _execute(
                self.backend.runtime, arrived_at=self.arrived_at,
                validate_before_wait=lambda: self.backend.validate_before_wait(self.request),
                work=self.backend.work, receive=receive, send=send,
                response_content_type=b"application/json",
            )
        except StockDetailNotFoundError as error:
            raise WebAppError(status_code=404, code="404001",
                              message=str(error)) from error


def provide_stock_daily_kline_backend(request: Request) -> StockDailyKlineBackend:
    return request.app.state.stock_daily_kline_backend

def install_stock_daily_technical_indicators(app):
    app.dependency_overrides[get_stock_daily_kline_backend] = provide_stock_daily_kline_backend
    # 仅安装依赖提供者，不创建runtime。

@asynccontextmanager
async def stock_daily_technical_indicators_lifespan(
    app, *, settings_provider=get_settings,
    session_factory_provider=get_session_factory,
):
    runtime = backend = None
    primary_error = cleanup_error = None
    try:
        settings = settings_provider()
        runtime = create_runtime(settings)    # 正在运行的事件循环
        backend = StockDailyKlineAppBackend(runtime, session_factory_provider, settings=settings)
        app.state.technical_indicator_runtime = runtime
        app.state.stock_daily_kline_backend = backend
        yield
    except BaseException as error:
        primary_error = error
        raise
    finally:
        with anyio.CancelScope(shield=True):
            if runtime is not None:
                try:
                    await runtime.aclose()
                except BaseException as error:
                    cleanup_error = error
            for name, owned in (("stock_daily_kline_backend", backend),
                                ("technical_indicator_runtime", runtime)):
                if owned is not None and getattr(app.state, name, None) is owned:
                    delattr(app.state, name)
            backend = runtime = None
        if cleanup_error is not None:
            if primary_error is not None:
                primary_error.add_note(
                    "Technical indicator shutdown: " + type(cleanup_error).__name__)
            else:
                raise cleanup_error
