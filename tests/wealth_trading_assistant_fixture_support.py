"""Test-only fixed HTTP/SQL clock, scoped to one newly created local cluster."""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.engine import Engine


@contextmanager
def fixed_fixture_clock(database, clock):
    identity = (database.url.host, database.url.port, database.url.database)
    if identity[0] != "127.0.0.1":
        raise ValueError("Only the isolated loopback fixture is allowed")

    class FixtureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                raise ValueError("Fixture requires timezone-aware time")
            return clock[0].astimezone(tz)

    def sql_clock(conn, cursor, statement, parameters, context, executemany):
        url = conn.engine.url
        if (url.host, url.port, url.database) == identity and statement.startswith("SELECT clock_timestamp()"):
            statement = statement.replace("clock_timestamp()", f"TIMESTAMPTZ '{clock[0].isoformat()}'")
        return statement, parameters

    event.listen(Engine, "before_cursor_execute", sql_clock, retval=True)
    try:
        with patch("src.app.runtime.trading_assistant_lifespan.datetime", FixtureDateTime):
            yield
    finally:
        event.remove(Engine, "before_cursor_execute", sql_clock)
