"""Deadline-aware TA session assembly using the installed SQLAlchemy/psycopg.

Only the caller supplies an engine. No connection URL, pool timeout or user setting
is created here; the shared synchronous engine and its consumers are unchanged.
"""
import asyncio
from typing import Callable, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
from src.biz.services.wealth.market.trading_assistant.transaction_boundary import CommitOutcomeUnknown

T = TypeVar("T")


class TradingAssistantTransactions:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    async def run(self, work: Callable[[Session], T], *, deadline: Deadline, write: bool) -> T:
        committing = False

        async def execute():
            nonlocal committing
            async with AsyncSession(self.engine,expire_on_commit=False) as session:
                # The await includes waiting for a pooled connection and initial connect.
                await session.connection()
                deadline.remaining_ms()
                if not write:
                    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                value = await session.run_sync(work)
                deadline.remaining_ms()
                if write:
                    committing = True
                    await session.commit()
                else:
                    await session.rollback()
                return value

        try:
            # Check before constructing the coroutine: an exhausted deadline must
            # not leave an unawaited transaction coroutine behind.
            timeout = deadline.remaining_ms()/1000
            return await asyncio.wait_for(execute(), timeout)
        except asyncio.CancelledError:
            # Caller disappearance gives no permission to retry or declare NOT_SAVED.
            raise
        except Exception as error:
            if committing:
                raise CommitOutcomeUnknown("Transaction outcome requires receipt lookup") from error
            raise
