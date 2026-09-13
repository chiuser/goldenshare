"""Real ASGI → query → isolated PostgreSQL progress, not simulated service data."""
import asyncio
from datetime import date
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_calculation_work import interruptions_db, cutoff_db
from tests.test_wealth_trading_assistant_account_acceptance import create, NOW
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def test_current_target_progress_and_owned_status_api(cutoff_db):
    publication_db = cutoff_db
    _, _, saved = create(publication_db)
    account_id = UUID(saved.receipt["result"]["account"]["accountId"])
    generation_id = uuid4()
    async def exercise():
        engine = create_async_engine(publication_db.url)
        deps = build_trading_assistant_dependencies(engine,policy=TradingAssistantExecutionPolicyV1(),
            now=lambda:NOW,executor_id="status-test")
        app, owner = FastAPI(), [1]
        async def auth():
            return owner[0]
        app.include_router(create_trading_assistant_router(auth_dependency=auth,dependencies_dependency=lambda:deps))
        url = f"/wealth/market/trading-assistant/accounts/{account_id}/calculation-status"
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
                initial = await client.get(url)
                assert initial.status_code == 200, initial.text
                assert initial.json()["stage"] == "PENDING"
                assert initial.json()["progress"] == dict(completedTradeDateCount=0,totalTradeDateCount=None,
                    currentTradeDate=None,lastCompletedTradeDate=None,lastBusinessUpdatedAt=None)
                owner[0] = 2
                assert (await client.get(url)).status_code == 404
                owner[0] = 1
                assert (await client.get(url+"?ownerId=2")).status_code == 400
                with Session(publication_db) as session, session.begin():
                    account = session.get(Account, account_id)
                    session.add(CutoffPreparation(account_id=account_id,target_version=1,fact_version=1,
                        initialization_id=account.current_initialization_id,from_date=date(2026,9,12),
                        current_date=date(2026,9,12),scan_through_date=date(2026,9,12),
                        state="WAITING_DATA",reason="当日数据尚未就绪",updated_at=NOW))
                waiting = (await client.get(url)).json()
                assert waiting["stage"] == "WAITING_DATA"
                assert waiting["progress"]["completedTradeDateCount"] == 0
                assert waiting["progress"]["lastCompletedTradeDate"] is None
                assert (await client.get(url)).json() == waiting
                with Session(publication_db) as session, session.begin():
                    account = session.get(Account,account_id)
                    session.add(CalculationGeneration(generation_id=generation_id,account_id=account_id,
                        target_version=1,fact_version=1,initialization_id=account.current_initialization_id,
                        rule_version=1,from_date=date(2026,9,1),through_date=date(2026,9,12),stage="CALCULATING",
                        completed_trade_date_count=6,total_trade_date_count=9,last_completed_trade_date=date(2026,9,8),
                        last_business_updated_at=NOW))
                calculated = (await client.get(url)).json()
                assert calculated["stage"] == "CALCULATING"
                assert calculated["progress"]["completedTradeDateCount"] == 6
                assert calculated["progress"]["totalTradeDateCount"] == 9
                assert (await client.get(url)).json() == calculated  # Query time is not progress.
                for stage in ("WAITING_DATA", "FAILED", "VERIFYING", "PUBLISHING"):
                    with Session(publication_db) as session, session.begin():
                        session.get(CalculationGeneration,generation_id).stage = stage
                    response = (await client.get(url)).json()
                    assert response["stage"] == stage and response["progress"] == calculated["progress"]
                # A new target must not borrow completed days from the previous one.
                with Session(publication_db) as session, session.begin():
                    account = session.get(Account,account_id)
                    account.fact_version = account.calculation_target_version = 2
                    session.get(Recalculation,account_id).target_version = 2
                refreshed = (await client.get(url)).json()
                assert refreshed["calculationTargetVersion"] == "2"
                assert refreshed["stage"] == "PENDING"
                assert refreshed["progress"]["completedTradeDateCount"] == 0
                assert refreshed["progress"]["totalTradeDateCount"] is None
        finally:
            await engine.dispose()
    asyncio.run(exercise())
