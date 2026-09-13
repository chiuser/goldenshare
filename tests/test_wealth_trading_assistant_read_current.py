"""M41-TX: injected read path, not a query with a hidden transaction mode."""
import asyncio
from dataclasses import replace
from time import monotonic
from uuid import UUID

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_wealth_trading_assistant_read_context import database, migrated, publication_db
from tests.test_wealth_trading_assistant_account_acceptance import create, NOW
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def test_shared_session_paging_snapshot_no_writes_and_release(publication_db, record_property):
    identities = [UUID(create(publication_db)[2].receipt["result"]["account"]["accountId"]) for _ in range(3)]

    async def run():
        engine = create_async_engine(publication_db.url)
        statements, sessions = [], []
        event.listen(engine.sync_engine, "before_cursor_execute",
            lambda c,u,s,p,x,m: statements.append(s))
        deps = build_trading_assistant_dependencies(engine,
            policy=replace(TradingAssistantExecutionPolicyV1(), page_rows=1),
            now=lambda:NOW, executor_id="m41-read")
        def cutoff(session, deadline):
            sessions.append(session)
            assert session.scalar(text("SHOW transaction_read_only")) == "on"
            assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert session.scalar(text("SHOW statement_timeout")) == "1s"
            assert session.scalar(text("SHOW lock_timeout")) == "100ms"
            return NOW
        async def read(query=lambda s,d,b:b, token=None):
            return await deps.read_current(query, owner_id=1, account_mode="ALL", account_id=None,
                resolve_target_through=cutoff, context_token=token)
        try:
            start = monotonic()
            original = await read()
            elapsed = monotonic()-start
            pages = sum("app.wealth_ta_account.owner_id" in s and "ORDER BY" in s for s in statements)
            record_property("m41_sql_count", len(statements))
            record_property("m41_account_scan_pages", pages)
            record_property("m41_elapsed_ms", round(elapsed*1000, 2))
            assert [a.accountId for a in original.context.accounts] == sorted(map(str, identities))
            assert pages == 4  # Three full pages plus empty terminal page.
            assert elapsed < 5
            assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"

            def concurrent(session, deadline, basis):
                assert session is sessions[-1]
                with publication_db.begin() as writer:
                    writer.execute(update(Account).where(Account.account_id == identities[0]).values(
                        fact_version=Account.fact_version+1))
                assert session.scalar(select(Account.fact_version).where(Account.account_id == identities[0])) == 1
                return basis
            assert await read(concurrent) == original
            with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
                await read(token=original.context.contextToken)
            fresh = await read()
            for _ in range(3):
                assert await read() == fresh
            def write(session, deadline, basis):
                session.execute(update(Account).values(name="forbidden"))
            with pytest.raises(DBAPIError):
                await read(write)
            assert await read() == fresh
            assert engine.pool.checkedout() == 0
        finally:
            await engine.dispose()
    asyncio.run(run())
