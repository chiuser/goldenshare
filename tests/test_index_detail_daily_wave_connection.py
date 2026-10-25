"""Isolated resource tests: no database or network; literal event expectations."""
import asyncio
import time
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
                initialize_delay=0, late=False, business_only=False, connect_steps=1,
                cleanup_errors=None, local_yield=False, on_rollback=None,
                initialize_error=None):
    events = []
    cleanup_errors = cleanup_errors or {}

    async def local_close(name):
        # Mirrors verified local teardown, never models extra network waiting.
        events.append(name)
        if name in cleanup_errors:
            raise cleanup_errors[name]
        if local_yield:
            await asyncio.sleep(0)
        events.append(name + ".done")

    class Raw:
        async def close(self):
            await local_close("raw.close")

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
            if on_rollback is not None:
                on_rollback()
            await asyncio.sleep(rollback_delay)
            self.is_active = False

    class Connection:
        async def execution_options(self, **options):
            events.append(("options", options))
            return self

        async def begin(self):
            events.append("begin")
            return Transaction()

        async def invalidate(self): await local_close("invalidate")
        async def close(self): await local_close("connection.close")

    class Dialect:
        def create_connect_args(self, url):
            return [], dict(host="test.invalid", dbname="db", user="reader", password="secret")

    class Engine:
        sync_engine = type("Sync", (), {"dialect": Dialect()})()

        async def connect(self):
            await self.creator()
            await asyncio.sleep(initialize_delay)
            if initialize_error is not None:
                raise initialize_error
            return Connection()

        async def dispose(self): await local_close("dispose")

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

        async def close(self): await local_close("session.close")

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


LOCAL_STEPS = ("raw.close", "invalidate", "session.close", "connection.close", "dispose")


def assert_local_closes(events, failed=None):
    for name in LOCAL_STEPS:
        assert name in events, (name, events)
        if name != failed:
            assert name + ".done" in events, (name, events)
    assert events.index("raw.close") < events.index("invalidate") < events.index("session.close") < events.index("connection.close") < events.index("dispose")


def assert_no_pending_tasks():
    assert not [task for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()]


def test_rollback_timeout_still_finishes_local_teardown_after_original_deadline(monkeypatch):
    events = environment(monkeypatch, rollback_delay=.4, local_yield=True)
    async def run():
        b = budget(); deadline = b.deadline
        instance = owner(b); started = time.monotonic()
        with pytest.raises(DailyWaveBudgetExceeded):
            async with instance as session:
                await session.execute_read(select(literal(1)))
        assert_local_closes(events)
        assert instance.closed and instance.budget.deadline == deadline
        assert events.count("rollback") == 1
        assert_no_pending_tasks()
        assert time.monotonic() - started < .45
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["known", "task"])
def test_cancellation_during_rollback_preserves_cancel_and_closes_each_resource(monkeypatch, kind):
    stop = False
    def cancel_known():
        nonlocal stop
        if kind == "known": stop = True
    events = environment(monkeypatch, rollback_delay=.4, local_yield=True, on_rollback=cancel_known)
    async def run():
        b = budget(); b.check_cancelled = lambda: stop
        instance = owner(b)
        async def request():
            async with instance as session:
                await session.execute_read(select(literal(1)))
        if kind == "known":
            with pytest.raises(DailyWaveCancelled): await request()
        else:
            task = asyncio.create_task(request())
            while "rollback" not in events: await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        assert_local_closes(events)
        assert instance.closed and events.count("rollback") == 1
        assert_no_pending_tasks()
    asyncio.run(run())


@pytest.mark.parametrize("stage", LOCAL_STEPS)
@pytest.mark.parametrize("body_error", [False, True])
def test_each_cleanup_failure_keeps_original_error_and_still_tries_other_resources(monkeypatch, stage, body_error):
    cleanup_error = RuntimeError("independent cleanup failure")
    original = DailyWaveSourceError("independent source failure") if body_error else None
    events = environment(monkeypatch, cleanup_errors={stage: cleanup_error}, local_yield=True)
    async def run():
        instance = owner(budget())
        with pytest.raises(type(original or cleanup_error)) as caught:
            async with instance as session:
                await session.execute_read(select(literal(1)))
                if original is not None: raise original
        assert caught.value is (original or cleanup_error)
        assert_local_closes(events, failed=stage)
        if original is not None:
            assert any(stage in note for note in original.__notes__)
        assert events.count("rollback") == (0 if body_error else 1)
        assert instance.closed
        assert_no_pending_tasks()
    asyncio.run(run())


def test_read_error_is_not_hidden_when_raw_close_itself_fails(monkeypatch):
    original = DailyWaveSourceError("original SELECT failure")
    events = environment(monkeypatch, cleanup_errors={"raw.close": RuntimeError("close failed")})
    async def execute(*args, **kwargs): raise original
    monkeypatch.setattr(module.DailyWaveReadSession, "_execute", execute)
    async def run():
        with pytest.raises(DailyWaveSourceError) as caught:
            async with owner(budget()) as session:
                await session.execute_read(select(literal(1)))
        assert caught.value is original and original.__notes__
        assert_local_closes(events, failed="raw.close")
        assert_no_pending_tasks()
    asyncio.run(run())


def test_sql_timeout_with_raw_close_failure_still_cancels_running_sql(monkeypatch):
    events = environment(monkeypatch, sql_delay=.4,
        cleanup_errors={"raw.close": RuntimeError("raw close failed")})
    async def run():
        instance = owner(budget())
        with pytest.raises(DailyWaveBudgetExceeded) as caught:
            async with instance as session:
                await session.execute_read(select(literal(1)))
        assert caught.value.__notes__
        assert events.index("raw.close") < events.index("sql.cancelled")
        assert "rollback" not in events
        assert_local_closes(events, failed="raw.close")
        assert instance.closed and not instance._raw_closed
        assert_no_pending_tasks()
    asyncio.run(run())


def test_multiple_cleanup_errors_keep_first_and_notes_do_not_copy_secrets(monkeypatch):
    first = RuntimeError("secret first cleanup detail")
    events = environment(monkeypatch, cleanup_errors={
        "invalidate": first,
        "session.close": ValueError("secret second cleanup detail"),
        "dispose": LookupError("secret final cleanup detail"),
    })
    async def run():
        instance = owner(budget())
        with pytest.raises(RuntimeError) as caught:
            async with instance as session:
                await session.execute_read(select(literal(1)))
        assert caught.value is first
        assert any("session.close: ValueError" in note for note in first.__notes__)
        assert any("dispose: LookupError" in note for note in first.__notes__)
        assert not any("secret" in note for note in first.__notes__)
        assert all(stage in events for stage in LOCAL_STEPS)
        assert "connection.close.done" in events
        assert events.count("rollback") == 1 and instance.closed
        assert_no_pending_tasks()
    asyncio.run(run())


def test_cleanup_error_does_not_replace_original_cancelled_error_object(monkeypatch):
    original = asyncio.CancelledError("original cancellation")
    events = environment(monkeypatch,
        cleanup_errors={"session.close": RuntimeError("close failed")})
    async def run():
        instance = owner(budget())
        with pytest.raises(asyncio.CancelledError) as caught:
            async with instance as session:
                await session.execute_read(select(literal(1)))
                raise original
        assert caught.value is original
        assert any("session.close: RuntimeError" in note for note in original.__notes__)
        assert "rollback" not in events
        assert_local_closes(events, failed="session.close")
        assert instance.closed
        assert_no_pending_tasks()
    asyncio.run(run())


def test_initialization_error_not_hidden_by_engine_disposal_failure(monkeypatch):
    original = DailyWaveSourceError("original initialization failure")
    events = environment(monkeypatch, initialize_error=original,
        cleanup_errors={"dispose": RuntimeError("dispose failed")})
    async def run():
        instance = owner(budget())
        with pytest.raises(DailyWaveSourceError) as caught:
            async with instance: pytest.fail("initialization should fail")
        assert caught.value is original and any("dispose" in note for note in original.__notes__)
        assert "raw.close.done" in events and "dispose" in events
        assert "session.close" not in events and "connection.close" not in events
        assert instance.closed
        assert_no_pending_tasks()
    asyncio.run(run())


def test_normal_teardown_and_repeated_exit_do_not_repeat_rollback_or_closes(monkeypatch):
    events = environment(monkeypatch, local_yield=True)
    async def run():
        instance = owner(budget())
        async with instance as session:
            await session.execute_read(select(literal(1)))
        assert_local_closes(events)
        before = events.copy()
        assert await instance.__aexit__(None, None, None) is False
        assert events == before and events.count("rollback") == 1
        assert_no_pending_tasks()
    asyncio.run(run())
