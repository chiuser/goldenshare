"""Retry admission through real ASGI and isolated PostgreSQL transactions."""
import asyncio
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_calculation_interruptions import interruptions_db
from tests.test_wealth_trading_assistant_calculation_work import cutoff_db
from tests.test_wealth_trading_assistant_account_acceptance import create, NOW
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.recovery import WriteRequest
from src.biz.schemas.wealth.market.trading_assistant.calculation_status import CalculationRetryCommand
from src.biz.services.wealth.market.trading_assistant.calculation_retries import CalculationRetryService
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1


def command(target="1"):
    return dict(requestId=str(uuid4()), attemptId=str(uuid4()), calculationTargetVersion=target)


@pytest.fixture(scope="module", autouse=True)
def retry_schema(cutoff_db):
    return cutoff_db


def prepare(engine):
    _, _, saved = create(engine)
    account_id = UUID(saved.receipt["result"]["account"]["accountId"])
    generation_id = uuid4()
    with Session(engine) as session, session.begin():
        account = session.get(Account, account_id)
        session.add(CalculationGeneration(generation_id=generation_id, account_id=account_id,
            target_version=1, fact_version=1, initialization_id=account.current_initialization_id,
            rule_version=1, from_date=date(2026,9,1), through_date=date(2026,9,12), stage="FAILED",
            resume_stage="CALCULATING", completed_trade_date_count=6, total_trade_date_count=9,
            last_completed_trade_date=date(2026,9,8), last_business_updated_at=NOW, reason="核验未通过"))
        pending = session.get(Recalculation, account_id)
        pending.next_attempt_at = None
        pending.transient_failure_count = 5
    return account_id, generation_id


def test_retry_api_identity_progress_active_lease_and_target_change(publication_db):
    account_id, generation_id = prepare(publication_db)
    async def exercise():
        engine = create_async_engine(publication_db.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda: NOW, executor_id="retry-api")
        app, owner = FastAPI(), [1]
        async def auth():
            return owner[0]
        app.include_router(create_trading_assistant_router(auth_dependency=auth, dependencies_dependency=lambda: deps))
        root = "/wealth/market/trading-assistant"
        url = f"{root}/accounts/{account_id}/calculation-retries"
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                body = command()
                first = await client.post(url, json=body)
                assert first.status_code == 200, first.text
                result = first.json()["result"]
                assert result["stage"] == "FAILED"  # Admission is not proof the failed input was fixed.
                assert result["progress"]["completedTradeDateCount"] == 6
                with Session(publication_db) as session:
                    account = session.get(Account, account_id)
                    pending = session.get(Recalculation, account_id)
                    assert (account.fact_version, account.calculation_target_version) == (1,1)
                    assert account.published_generation_id is None
                    assert pending.transient_failure_count == 0
                    assert pending.next_attempt_at <= session.scalar(select(func.clock_timestamp()))
                    queued_at = pending.next_attempt_at
                    request = session.get(WriteRequest, (1,UUID(body["requestId"])))
                    assert request.candidate_id is None and request.input_payload == {"calculationTargetVersion":"1"}
                # Replay remains the original receipt even after computation changes.
                with Session(publication_db) as session, session.begin():
                    session.get(CalculationGeneration, generation_id).stage = "CALCULATING"
                assert (await client.post(url, json=body)).json() == first.json()
                with Session(publication_db) as session:
                    assert session.get(Recalculation, account_id).next_attempt_at == queued_at
                recovery = await client.get(f"{root}/write-requests/{body['requestId']}")
                assert recovery.status_code == 200, recovery.text
                assert recovery.json()["receipt"] == first.json()
                assert recovery.json()["summary"]["title"] == "重试计算"
                concurrent = command()
                responses = await asyncio.gather(client.post(url,json=concurrent),client.post(url,json=concurrent))
                assert [response.status_code for response in responses] == [200,200]
                assert responses[0].json() == responses[1].json()
                with Session(publication_db) as session:
                    assert session.scalar(select(func.count()).select_from(WriteRequest).where(
                        WriteRequest.owner_id == 1, WriteRequest.request_id == UUID(concurrent["requestId"]))) == 1
                changed = await client.post(url, json={**body,"calculationTargetVersion":"2"})
                assert changed.status_code == 409 and changed.json()["code"] == "TA_REQUEST_ID_CONFLICT"
                owner[0] = 2
                assert (await client.post(url, json=command())).status_code == 404
                owner[0] = 1
                assert (await client.post(url, json={**command(),"commissionAmount":"0.00"})).status_code == 400
                with Session(publication_db) as session, session.begin():
                    pending = session.get(Recalculation, account_id)
                    pending.executor_id = "active-worker"
                    pending.fence = 42
                    pending.lease_until = session.scalar(select(func.clock_timestamp())) + timedelta(days=1)
                    pending.next_attempt_at = pending.lease_until
                    pending.transient_failure_count = 3
                    active = (pending.executor_id,pending.fence,pending.lease_until,pending.next_attempt_at)
                assert (await client.post(url, json=command())).json()["result"]["stage"] == "CALCULATING"
                with Session(publication_db) as session:
                    pending = session.get(Recalculation, account_id)
                    assert (pending.executor_id,pending.fence,pending.lease_until,pending.next_attempt_at) == active
                    assert pending.transient_failure_count == 3
                with Session(publication_db) as session, session.begin():
                    account = session.get(Account, account_id)
                    account.fact_version = account.calculation_target_version = 2
                    pending = session.get(Recalculation, account_id)
                    pending.target_version = 2
                    pending.lease_until = None
                stale = (await client.post(url, json=command())).json()["result"]
                assert stale["calculationTargetVersion"] == "2" and stale["stage"] == "PENDING"
                with Session(publication_db) as session:
                    assert session.get(Recalculation, account_id).next_attempt_at == active[3]
        finally:
            await engine.dispose()
    asyncio.run(exercise())


def test_retry_receipt_and_schedule_rollback_together(publication_db):
    account_id, _ = prepare(publication_db)
    policy = TradingAssistantExecutionPolicyV1()
    service = CalculationRetryService(None, policy, lambda:NOW, executor_id="rollback-test")
    body = CalculationRetryCommand(**command())
    with Session(publication_db) as session:
        before = session.get(Recalculation,account_id).next_attempt_at
    with pytest.raises(RuntimeError, match="process stopped before commit"):
        with Session(publication_db) as session, session.begin():
            service.accept(session, owner_id=1, account_id=account_id, command=body,
                deadline=Deadline.after_ms(5000))
            raise RuntimeError("process stopped before commit")
    with Session(publication_db) as session:
        assert session.get(WriteRequest,(1,UUID(body.requestId))) is None
        assert session.get(Recalculation,account_id).next_attempt_at == before
        assert session.get(Recalculation,account_id).transient_failure_count == 5
