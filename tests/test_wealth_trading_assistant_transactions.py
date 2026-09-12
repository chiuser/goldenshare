"""Actual async connection wait and commit-ambiguity tests in an isolated DB."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession,create_async_engine

from tests.test_wealth_trading_assistant_persistence import database
from src.biz.models.wealth.trading_assistant.recovery import WriteScope
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
from src.biz.services.wealth.market.trading_assistant.transaction_boundary import CommitOutcomeUnknown
from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions


def test_expired_deadline_does_not_start_or_leak_transaction_coroutine(database):
    import gc
    import warnings
    async def run():
        engine = create_async_engine(database.url)
        called = []
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", RuntimeWarning)
                with pytest.raises(TimeoutError):
                    await TradingAssistantTransactions(engine).run(lambda s:called.append(True),
                        deadline=Deadline(0, lambda:1), write=True)
                gc.collect()
                assert not [warning for warning in caught if "never awaited" in str(warning.message)]
            assert not called
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_pool_wait_counts_toward_request_deadline(database):
    async def run():
        engine = create_async_engine(database.url,pool_size=1,max_overflow=0)
        runner = TradingAssistantTransactions(engine)
        called = []
        try:
            async with engine.connect():
                with pytest.raises(TimeoutError):
                    await runner.run(lambda s:called.append(True),deadline=Deadline.after_ms(30),write=False)
            assert not called
            value = await runner.run(lambda s:s.scalar(select(WriteScope.owner_id).limit(1)),
                                     deadline=Deadline.after_ms(5000),write=False)
            assert value is None
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_commit_completed_but_response_lost_is_unknown_and_not_replayed(database,monkeypatch):
    key = str(uuid4())
    original = AsyncSession.commit
    async def lose_response(session):
        await original(session)
        raise ConnectionError("injected after successful commit")
    monkeypatch.setattr(AsyncSession,"commit",lose_response)
    async def run():
        engine = create_async_engine(database.url)
        runner = TradingAssistantTransactions(engine)
        try:
            with pytest.raises(CommitOutcomeUnknown):
                await runner.run(lambda s:s.execute(insert(WriteScope).values(owner_id=1,scope_key=key)),
                                 deadline=Deadline.after_ms(10000),write=True)
            rows = await runner.run(lambda s:list(s.scalars(select(WriteScope.scope_key).where(WriteScope.scope_key == key))),
                                    deadline=Deadline.after_ms(5000),write=False)
            assert rows == [key]
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_read_boundary_rejects_writes(database):
    from sqlalchemy.exc import DBAPIError
    key = str(uuid4())
    async def run():
        engine = create_async_engine(database.url)
        try:
            with pytest.raises(DBAPIError):
                await TradingAssistantTransactions(engine).run(
                    lambda s:s.execute(insert(WriteScope).values(owner_id=1,scope_key=key)),
                    deadline=Deadline.after_ms(5000),write=False)
            async with AsyncSession(engine) as session:
                assert await session.scalar(select(WriteScope.scope_key).where(WriteScope.scope_key == key)) is None
        finally:
            await engine.dispose()
    asyncio.run(run())
