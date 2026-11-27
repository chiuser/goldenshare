"""Open a request-owned, read-only PostgreSQL session for technical indicators."""

from contextlib import contextmanager
from math import ceil

from psycopg import Error as PsycopgError
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from goldenshare_technical_indicators.errors import (
    CalculationDeadlineError, ResourceCleanupError, SourceReadError, SourceUnsupportedError,
)


@contextmanager
def open_technical_indicator_read_session(session_factory, control):
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
