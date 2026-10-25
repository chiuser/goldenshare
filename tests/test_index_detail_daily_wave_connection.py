"""Isolated resource tests: no database or network; literal event expectations."""
import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select, literal, text
from sqlalchemy.exc import DBAPIError

from src.app.dependencies import daily_wave as module
from src.biz.services.wealth.market.index_detail_daily_wave.budget import (
    DailyWaveBudget, DailyWaveBudgetExceeded, DailyWaveCancelled,
)
from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC
from src.biz.queries.wealth.market.index_detail_daily_wave.query import DailyWaveSourceError


def environment(monkeypatch, *, connect_delay=0, sql_delay=0, rollback_delay=0,
                initialize_delay=0, late=False, business_only=False, connect_steps=1):
    events = []

    class Raw:
        async def close(self):
            events.append("raw.close")

    async def connect(*args, **kwargs):
        events.append(("connect", kwargs))
        try:
            for index in range(connect_steps):
                events.append(("address",index))
                await asyncio.sleep(connect_delay)
        except asyncio.CancelledError:
            if not late:
                raise
        return Raw()

    class Transaction:
        is_active = True

        async def rollback(self):
            events.append("rollback")
            await asyncio.sleep(rollback_delay)
            self.is_active = False

    class Connection:
        async def execution_options(self, **options):
            events.append(("options", options))
            return self

        async def begin(self):
            events.append("begin")
            return Transaction()

        async def invalidate(self): events.append("invalidate")
        async def close(self): events.append("connection.close")

    class Dialect:
        def create_connect_args(self, url):
            return [], dict(host="test.invalid", dbname="db", user="reader", password="secret")

    class Engine:
        sync_engine = type("Sync", (), {"dialect": Dialect()})()

        async def connect(self):
            await self.creator()
            await asyncio.sleep(initialize_delay)
            return Connection()

        async def dispose(self): events.append("dispose")

    def engine(url, **kwargs):
        events.append(("engine", kwargs))
        result = Engine()
        result.creator = kwargs["async_creator"]
        return result

    class Result:
        def mappings(self): return self
        def all(self): return [{"value": 1}]

    class Session:
        def __init__(self, **kwargs): events.append(("session", kwargs))

        async def execute(self, statement, parameters=None):
            events.append(("execute", str(statement), parameters))
            try:
                await asyncio.sleep(sql_delay if not business_only or "set_config" not in str(statement) else 0)
            except asyncio.CancelledError:
                events.append("sql.cancelled")
                raise
            return Result()

        async def close(self): events.append("session.close")

    monkeypatch.setattr(module.psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(module, "create_async_engine", engine)
    monkeypatch.setattr(module, "AsyncSession", Session)
    return events


def budget(**overrides):
    return DailyWaveBudget(replace(DEFAULT_SPEC, calculation_seconds=.3,
        connection_seconds=.025, query_seconds=.025, lock_seconds=.01,
        cleanup_seconds=.05, **overrides))


def owner(b):
    return module.DailyWaveReadSession(budget=b,
        database_url="postgresql+psycopg://reader:secret@test.invalid/db")


def test_normal_connection_transaction_projection_and_exact_single_rollback(monkeypatch):
    events = environment(monkeypatch)

    async def run():
        async with owner(budget()) as session:
            assert await session.execute_read(select(literal(1))) == ({"value": 1},)
            with pytest.raises(DailyWaveSourceError, match="SELECT"):
                await session.execute_read(text("DELETE FROM never_execute"))
        assert session.closed

    asyncio.run(run())
    assert events.count("rollback") == 1
    assert events.index("begin") > next(i for i, e in enumerate(events) if isinstance(e, tuple) and e[0] == "options")
    kwargs = next(e[1] for e in events if isinstance(e, tuple) and e[0] == "connect")
    assert kwargs["dbname"] == "db" and kwargs["password"] == "secret"
    assert "default_transaction_read_only=on" in kwargs["options"]
    session_options = next(e[1] for e in events if isinstance(e, tuple) and e[0] == "session")
    assert session_options["join_transaction_mode"] == "rollback_only"
    statements = [e for e in events if isinstance(e, tuple) and e[0] == "execute"]
    assert len(statements) == 2 and "set_config" in statements[0][1]
    assert 0 < int(statements[0][2]["lock_ms"]) < int(statements[0][2]["statement_ms"])


@pytest.mark.parametrize("kind", ["connect", "initialize", "sql", "business", "rollback", "late"])
def test_each_wait_is_bounded_and_late_handle_cannot_continue(monkeypatch, kind):
    options = {"connect_delay": .08} if kind in {"connect", "late"} else {
        {"initialize": "initialize_delay", "sql": "sql_delay", "business": "sql_delay", "rollback": "rollback_delay"}[kind]: .4}
    if kind == "late": options["late"] = True
    if kind == "business": options["business_only"] = True
    events = environment(monkeypatch, **options)

    async def run():
        with pytest.raises(DailyWaveBudgetExceeded):
            async with owner(budget()) as session:
                await session.execute_read(select(literal(1)))
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]

    asyncio.run(run())
    if kind != "connect": assert "raw.close" in events
    if kind in {"initialize", "late"}: assert "begin" not in events
    if "sql.cancelled" in events:
        assert events.index("raw.close") < events.index("sql.cancelled")


def test_known_cancellation_closes_before_cancel_and_does_not_restart(monkeypatch):
    events = environment(monkeypatch, sql_delay=.1)
    stop = False

    async def run():
        nonlocal stop
        b = budget()
        b.check_cancelled = lambda: stop
        with pytest.raises(DailyWaveCancelled):
            async with owner(b) as session:
                async def cancel():
                    nonlocal stop
                    await asyncio.sleep(.005)
                    stop = True
                task = asyncio.create_task(cancel())
                try:
                    await session.execute_read(select(literal(1)))
                finally:
                    await task

    asyncio.run(run())
    assert events.count("rollback") == 0
    assert events.index("raw.close") < events.index("sql.cancelled")
    assert sum(isinstance(e, tuple) and e[0] == "connect" for e in events) == 1


def test_overall_connect_deadline_does_not_restart_for_each_address(monkeypatch):
    events=environment(monkeypatch,connect_delay=.015,connect_steps=4)
    async def run():
        with pytest.raises(DailyWaveBudgetExceeded):
            async with owner(budget()):
                pytest.fail("combined address attempts escaped the overall connect limit")
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(run())
    attempts=[e for e in events if isinstance(e,tuple) and e[0]=="address"]
    assert 1<=len(attempts)<4


def test_same_owner_rejects_concurrent_operation_without_cancelling_normal_read(monkeypatch):
    events=environment(monkeypatch,sql_delay=.005,business_only=True)
    async def run():
        async with owner(budget()) as session:
            first=asyncio.create_task(session.execute_read(select(literal(1))))
            await asyncio.sleep(0)
            with pytest.raises(DailyWaveSourceError,match="并发"):
                await session.execute_read(select(literal(2)))
            assert await first==({"value":1},)
    asyncio.run(run())
    assert len([e for e in events if isinstance(e,tuple) and e[0]=="execute"])==2


@pytest.mark.parametrize("state",["57014","55P03","42501"])
def test_server_timeout_classification_does_not_hide_other_database_errors(monkeypatch,state):
    events=environment(monkeypatch)
    class Origin(Exception):sqlstate=state
    async def execute(self,*args,**kwargs):
        raise DBAPIError("SELECT",{},Origin("independent server status"),False)
    monkeypatch.setattr(module.DailyWaveReadSession,"_execute",execute)
    async def run():
        with pytest.raises(DailyWaveBudgetExceeded if state!="42501" else DBAPIError):
            async with owner(budget()) as session:
                await session.execute_read(select(literal(1)))
        assert session.closed and "raw.close" in events
    asyncio.run(run())


@pytest.mark.parametrize("url",["sqlite://", "invalid secret connection string"])
def test_configuration_error_is_explicit_without_connecting_or_echoing_url(monkeypatch,url):
    events=environment(monkeypatch)
    async def run():
        with pytest.raises(DailyWaveSourceError) as caught:
            async with module.DailyWaveReadSession(budget=budget(),database_url=url):
                pytest.fail("invalid driver reached a usable session")
        assert url not in str(caught.value)
    asyncio.run(run())
    assert not any(isinstance(e,tuple) and e[0]=="connect" for e in events)
