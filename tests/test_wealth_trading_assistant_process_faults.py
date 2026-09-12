"""Kill real ASGI write executors against a fresh PG; never kill shared services."""
import asyncio
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
from src.biz.models.wealth.trading_assistant.recovery import WriteAttempt, ValidationCheckpoint
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recovery_maintenance import RecoveryMaintenance

NOW = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)
ROOT = "/api/v1/wealth/market/trading-assistant"


def application(deps):
    app = FastAPI()
    # JWT isolation is covered separately; no accounting service is mocked here.
    app.include_router(create_trading_assistant_router(auth_dependency=lambda: 1,
        dependencies_dependency=lambda: deps), prefix="/api/v1")
    return app


def crash_worker(url, account, payload, phase):
    original = TradingAssistantTransactions.run

    async def fault(self, work, *, deadline, write):
        name = work.__name__
        if phase == "before_accept_commit" and name == "accept":
            def crash_before_commit(session):
                work(session)
                session.flush()
                os._exit(73)
            return await original(self, crash_before_commit, deadline=deadline, write=write)
        result = await original(self, work, deadline=deadline, write=write)
        if write and ((phase == "registered" and getattr(result, "execute", False))
                      or (phase == "checkpoint" and name == "store")
                      or (phase == "after_accept_commit" and name == "accept")):
            os._exit(73)
        return result
    TradingAssistantTransactions.run = fault

    async def run():
        engine = create_async_engine(url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda: NOW, executor_id="killed-isolated-process")
        try:
            async with AsyncClient(transport=ASGITransport(app=application(deps)), base_url="http://isolated") as client:
                await client.post(ROOT + f"/accounts/{account}/cash-flows", json=payload)
        finally:
            await engine.dispose()
    asyncio.run(run())
    raise AssertionError("Fault point was not reached")


@pytest.mark.parametrize("phase", ["registered", "checkpoint", "before_accept_commit", "after_accept_commit"])
def test_process_death_read_only_recovery_then_explicit_retry(database, phase):
    with database.begin() as connection:
        account, _, _ = seed_account(connection)
    payload = dict(requestId=str(uuid4()), attemptId=str(uuid4()), direction="IN", occurredOn="2026-09-11", amount="123.45")
    process = multiprocessing.get_context("spawn").Process(target=crash_worker,
        args=(database.url.render_as_string(hide_password=False), str(account), payload, phase))
    try:
        process.start(); process.join(timeout=25)
        assert process.exitcode == 73
    finally:
        if process.is_alive():
            process.terminate(); process.join(timeout=5)
    accepted = phase == "after_accept_commit"
    with Session(database) as session:
        assert session.get(Account, account).fact_version == (2 if accepted else 1)
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == int(accepted)
        attempt = session.get(WriteAttempt, (1, UUID(payload["requestId"]), UUID(payload["attemptId"])))
        assert attempt.status == ("SAVED" if accepted else "PROCESSING")
        if phase in {"checkpoint", "before_accept_commit", "after_accept_commit"}:
            assert session.scalar(select(func.count()).select_from(ValidationCheckpoint)) > 0

    async def recover():
        engine = create_async_engine(database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda: NOW + timedelta(minutes=10), executor_id="restarted-isolated-process")
        try:
            async with AsyncClient(transport=ASGITransport(app=application(deps)), base_url="http://isolated") as client:
                status_path = ROOT + "/write-requests/" + payload["requestId"]
                before = await client.get(status_path)
                assert before.status_code == 200
                assert before.json()["outcome"] == ("SAVED" if accepted else "PROCESSING")
                again = await client.get(status_path)
                assert again.json() == before.json()  # GET neither stops nor resumes the executor.
                maintenance = RecoveryMaintenance(deps.transactions, deps.ledger.protocol, deps.policy, deps.now)
                await maintenance.sweep(deadline=Deadline.after_ms(5000), cancelled=lambda: False)
                state = (await client.get(status_path)).json()
                if accepted:
                    assert state["outcome"] == "SAVED"
                    retry = payload
                else:
                    assert state["outcome"] == "NOT_SAVED"
                    restored = await client.get(status_path + "/input")
                    assert restored.status_code == 200 and restored.json()["input"]["amount"] == "123.45"
                    retry = {**payload, "attemptId": str(uuid4()), "expectedRequestStateVersion": state["stateVersion"]}
                response = await client.post(ROOT + f"/accounts/{account}/cash-flows", json=retry)
                assert response.status_code in {200, 201}, response.text
                repeated = await client.post(ROOT + f"/accounts/{account}/cash-flows", json=retry)
                assert repeated.status_code == 200 and repeated.json() == response.json()
        finally:
            await engine.dispose()
    asyncio.run(recover())
    with Session(database) as session:
        assert session.get(Account, account).fact_version == 2
        assert session.get(Recalculation, account).target_version == 2
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == 1
