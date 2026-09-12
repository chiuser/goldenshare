"""Bounded long-history scan in a freshly created PG database, never production."""
import asyncio
from datetime import date, datetime, timedelta, timezone
import time
import tracemalloc
from uuid import uuid4

from sqlalchemy import select, text, func, event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions
from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate, ValidationCheckpoint
from src.biz.schemas.wealth.market.trading_assistant.accounts import CashFlowInput
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import prepare_cash
from src.biz.services.wealth.market.trading_assistant.ledger_validation import LedgerValidator, LedgerValidationInput
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader
from src.biz.services.wealth.market.trading_assistant.validation import CashValidation
from src.biz.services.wealth.market.trading_assistant.validation_pages import ValidationPageReader
from src.biz.services.wealth.market.trading_assistant.validation_checkpoints import ValidationCheckpoints
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol


def test_100000_rows_resume_with_bounded_pages(database):
    count = 100000
    prefix = str(uuid4())
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
        parameters = dict(account=account, prefix=prefix, count=count)
        conn.execute(text("""INSERT INTO app.wealth_ta_ledger (ledger_id,account_id,kind,created_at)
            SELECT md5(:prefix || n::text)::uuid,:account,'CASH_FLOW',now()
            FROM generate_series(1,:count) n"""), parameters)
        conn.execute(text("""INSERT INTO app.wealth_ta_ledger_revision
            (ledger_id,account_id,kind,revision,accepted_fact_version,occurred_on,accepted_at,status,direction,cash_amount,net_cash_change)
            SELECT md5(:prefix || n::text)::uuid,:account,'CASH_FLOW',1,n+1,DATE '2026-09-11',now(),'ACTIVE','IN',1,1
            FROM generate_series(1,:count) n"""), parameters)
        conn.execute(text("UPDATE app.wealth_ta_account SET fact_version=:version WHERE account_id=:account"),
            dict(version=count+1, account=account))
        conn.execute(text("ANALYZE app.wealth_ta_ledger"))
        conn.execute(text("ANALYZE app.wealth_ta_ledger_revision"))
    candidate, run = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with Session(database) as session, session.begin():
        session.add(ValidationCandidate(candidate_id=candidate, owner_id=1, account_id=account, purpose="PREVIEW",
            input_schema_version=1, input_digest=b"a"*32, input_payload={}, basis={}, created_at=now))
    change = prepare_cash(account_id=account, ledger_id=uuid4(),
        data=CashFlowInput(direction="IN", occurredOn="2026-09-11", amount="2.00"))
    job = LedgerValidationInput(1, candidate, run, count+1, b"b"*32, change, CashValidation(0), ())

    async def execute():
        engine = create_async_engine(database.url)
        plans = []
        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def capture_plan(connection, cursor, statement, parameters, context, executemany):
            if not plans and "row_number() OVER" in statement:
                plans.append(None)  # Do not recurse on the EXPLAIN event.
                plans[0] = connection.exec_driver_sql("EXPLAIN (FORMAT JSON) " + statement, parameters).scalar()
        policy = TradingAssistantExecutionPolicyV1()
        transactions = TradingAssistantTransactions(engine)
        checkpoints = ValidationCheckpoints(WriteProtocol(policy))
        validator = LedgerValidator(transactions, ValidationPageReader(policy, MarketFactsReader(policy)), checkpoints, policy, lambda:now)
        started, attempts = time.monotonic(), 0
        tracemalloc.start()
        try:
            while attempts < 20:
                attempts += 1
                try:
                    proof = await validator.validate(job, deadline=Deadline.after_ms(10000), cancelled=lambda:False)
                    assert proof.scans[0][3] == count+1
                    _, peak = tracemalloc.get_traced_memory()
                    assert plans and plans[0][0]["Plan"]
                    # Evidence, not a new production input limit.
                    assert peak < 64 * 1024 * 1024
                    print(f"capacity rows={count+1} attempts={attempts} seconds={time.monotonic()-started:.3f} peak_bytes={peak} plan={plans[0]}")
                    return
                except TimeoutError:
                    # New invocation resumes only durable pages; no accumulation in caller RAM.
                    with Session(database) as session:
                        assert session.scalar(select(func.count()).select_from(ValidationCheckpoint)
                            .where(ValidationCheckpoint.candidate_id == candidate)) > 0
            raise AssertionError("Long-history scan made insufficient bounded progress")
        finally:
            tracemalloc.stop()
            await engine.dispose()
    asyncio.run(execute())
    with Session(database) as session:
        pages = session.scalars(select(ValidationCheckpoint).where(ValidationCheckpoint.candidate_id == candidate)).all()
        assert len(pages) == 201
        assert sum(page.completed_range["rows"] for page in pages) == count+1
        assert all(page.completed_range["rows"] <= 500 and page.completed_range["bytes"] <= 1048576 for page in pages)
        final = next(page for page in pages if page.completed_range["complete"])
        assert final.accumulator["cash_cents"] == str((count+2)*100)
    # Exercise the real HTTP command through deadline expiry, maintenance and
    # explicit same-request retries, not only the validator orchestration.
    async def http_resume():
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
        from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
        from src.biz.services.wealth.market.trading_assistant.recovery_maintenance import RecoveryMaintenance
        from src.biz.models.wealth.trading_assistant.accounts import Account
        from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
        engine = create_async_engine(database.url)
        clock = [now]
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda:clock[0], executor_id="capacity-http")
        app = FastAPI()
        app.include_router(create_trading_assistant_router(auth_dependency=lambda:1, dependencies_dependency=lambda:deps))
        root = "/wealth/market/trading-assistant"
        payload = dict(requestId=str(uuid4()), attemptId=str(uuid4()), direction="IN", occurredOn="2026-09-11", amount="2.00")
        maintenance = RecoveryMaintenance(deps.transactions, deps.ledger.protocol, deps.policy, deps.now)
        started = time.monotonic()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                for attempt in range(20):
                    response = await client.post(root+f"/accounts/{account}/cash-flows", json=payload)
                    if response.status_code in {200,201}:
                        replay = await client.post(root+f"/accounts/{account}/cash-flows", json=payload)
                        assert replay.json() == response.json()
                        print(f"capacity_http rows={count+1} attempts={attempt+1} seconds={time.monotonic()-started:.3f}")
                        break
                    clock[0] += timedelta(minutes=1)
                    await maintenance.sweep(deadline=Deadline.after_ms(5000), cancelled=lambda:False)
                    status = (await client.get(root+"/write-requests/"+payload["requestId"])).json()
                    assert status["outcome"] == "NOT_SAVED", (response.status_code, response.text, status)
                    assert (await client.get(root+"/write-requests/"+payload["requestId"]+"/input")).status_code == 200
                    payload = {**payload, "attemptId":str(uuid4()), "expectedRequestStateVersion":status["stateVersion"]}
                else:
                    raise AssertionError("HTTP same-request resume made insufficient progress")
            with Session(database) as session:
                assert session.get(Account,account).fact_version == count+2
                assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == count+1
        finally:
            await engine.dispose()
    asyncio.run(http_resume())
