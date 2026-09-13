"""Thread-local execution and actual PostgreSQL cancellation, no Web startup."""
import asyncio
from dataclasses import replace
from threading import Event, get_ident, enumerate as threads
from time import monotonic

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_wealth_trading_assistant_persistence import database
from src.app.runtime.trading_assistant_execution_resource import TradingAssistantExecutionResource
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def policy():
    return replace(TradingAssistantExecutionPolicyV1(), batch_budget_ms=500, sql_timeout_ms=200)


def test_short_transactions_keep_commits_and_rollback_only_failed_unit(database):
    main = get_ident()
    with database.begin() as connection:
        connection.execute(text("CREATE TABLE app.ta_execution_resource_probe (id integer PRIMARY KEY)"))
    class Resource(TradingAssistantExecutionResource):
        def _unit(self, sessions, kind):
            assert get_ident() != main
            with sessions() as session, session.begin():
                session.execute(text("INSERT INTO app.ta_execution_resource_probe VALUES (1)"))
            with sessions() as session, session.begin():
                session.execute(text("INSERT INTO app.ta_execution_resource_probe VALUES (2)"))
                raise ValueError("test second transaction failed")
    async def run():
        resource = Resource(database.url, policy(), rule_version=1)
        try:
            with pytest.raises(ValueError, match="second transaction"):
                await resource.run_one("CALCULATE")
        finally:
            await resource.close()
        assert resource._closed
        with pytest.raises(RuntimeError, match="closing"):
            await resource.run_one("CALCULATE")
        assert not [t for t in threads() if t.name.startswith("ta-calculation")]
    asyncio.run(run())
    with database.connect() as connection:
        assert connection.execute(text("SELECT id FROM app.ta_execution_resource_probe")).scalars().all() == [1]


def test_sql_wait_is_cancelled_without_stalling_event_loop(database):
    class Resource(TradingAssistantExecutionResource):
        def _unit(self, sessions, kind):
            with sessions() as session, session.begin():
                session.execute(text("SELECT pg_sleep(5)"))
    async def run():
        resource = Resource(database.url, policy(), rule_version=1)
        ticks = 0
        async def heartbeat():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(.01)
        ticker = asyncio.create_task(heartbeat())
        start = monotonic()
        try:
            with pytest.raises(TimeoutError):
                await resource.run_one("CALCULATE")
        finally:
            await resource.close()
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
        assert ticks >= 10
        assert monotonic()-start < resource.policy.shutdown_grace_seconds
        assert not [t for t in threads() if t.name.startswith("ta-calculation")]
    asyncio.run(run())


def test_cancelling_waiter_does_not_fake_thread_exit_or_allow_queueing(database):
    entered = Event()
    class Resource(TradingAssistantExecutionResource):
        def _unit(self, sessions, kind):
            with sessions() as session, session.begin():
                entered.set()
                session.execute(text("SELECT pg_sleep(0.2)"))
            return "COMPLETE"
    async def run():
        resource = Resource(database.url, policy(), rule_version=1)
        waiter = asyncio.create_task(resource.run_one("CALCULATE"))
        try:
            while not entered.is_set():
                await asyncio.sleep(.001)
            with pytest.raises(RuntimeError, match="in-flight"):
                await resource.run_one("HISTORY")
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not resource._active.done()
        finally:
            await resource.close()
        assert resource._active.result() == "COMPLETE"
        assert resource._closed
    asyncio.run(run())


def test_connection_pool_wait_is_inside_unit_deadline(database):
    class Resource(TradingAssistantExecutionResource):
        async def _execute(self, kind):
            self._engine = create_async_engine(self.database_url, pool_size=1, max_overflow=0, pool_timeout=30)
            async with self._engine.connect():
                # Deliberately exhaust this isolated resource's only connection.
                return await super()._execute(kind)
        def _unit(self, sessions, kind):
            pytest.fail("The unit cannot start without its connection")
    async def run():
        resource = Resource(database.url, policy(), rule_version=1)
        start = monotonic()
        try:
            with pytest.raises(TimeoutError):
                await resource.run_one("CALCULATE")
        finally:
            await resource.close()
        assert monotonic()-start < resource.policy.shutdown_grace_seconds
    asyncio.run(run())


def test_unresponsive_local_server_handshake_obeys_connection_deadline():
    async def run():
        accepted = asyncio.Event()
        clients = []
        def blackhole(reader, writer):
            # A real local TCP peer accepts but never answers PostgreSQL's
            # handshake. No configured database or external network is used.
            clients.append(writer)
            accepted.set()
        server = await asyncio.start_server(blackhole, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        resource = TradingAssistantExecutionResource(
            f"postgresql+psycopg://isolated@127.0.0.1:{port}/unused?sslmode=disable", policy(), rule_version=1)
        start = monotonic()
        try:
            with pytest.raises(TimeoutError):
                await resource.run_one("SCHEMA")
            assert accepted.is_set()
        finally:
            await resource.close()
            for writer in clients:
                writer.close()
                await writer.wait_closed()
            server.close()
            await server.wait_closed()
        assert monotonic()-start < resource.policy.shutdown_grace_seconds
        assert not [t for t in threads() if t.name.startswith("ta-calculation")]
    asyncio.run(run())
