"""Real ASGI/SQL accounting tests with an injected authenticated identity.

These tests exercise the new router and isolated PG, not the shared JWT boundary.
"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_wealth_trading_assistant_persistence import database
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def test_real_account_cash_api_and_recovery(database):
    async def execute():
        engine = create_async_engine(database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda:datetime(2026,9,12,8,tzinfo=timezone.utc), executor_id="api-test")
        app = FastAPI()
        owner = 1
        async def authenticated_owner():
            return owner
        app.include_router(create_trading_assistant_router(auth_dependency=authenticated_owner, dependencies_dependency=lambda:deps), prefix="/api/v1")
        root = "/api/v1/wealth/market/trading-assistant"
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get(root+"/accounts")).json() == {"items":[]}
                assert (await client.get(root+"/accounts?ownerId=2")).status_code == 400
                default = (await client.get(root+"/account-initialization/defaults")).json()
                assert default == dict(stampTaxRatePct="0.05", commissionRateUnit="WAN", stampTaxRateUnit="PERCENT", currency="CNY")
                command = dict(requestId=str(uuid4()), attemptId=str(uuid4()), name="主账户", brokerName="测试券商",
                    initialCash="1000.00", initialPositions=[], commissionRateWan="3.00", minimumCommission="5.00", stampTaxRatePct="0.05")
                first = await client.post(root+"/accounts", json=command)
                assert first.status_code == 201, first.text
                repeated = await client.post(root+"/accounts", json=command)
                assert repeated.status_code == 200 and repeated.json() == first.json()
                account_id = first.json()["result"]["account"]["accountId"]
                prefix = root+"/accounts/"+account_id
                cash = dict(requestId=str(uuid4()), attemptId=str(uuid4()), direction="OUT", occurredOn="2026-09-12", amount="2000.00")
                malformed_amount = await client.post(prefix+"/cash-flows", json={**cash, "amount":"not-money"})
                assert malformed_amount.status_code == 400
                assert malformed_amount.json()["fieldErrors"][0]["field"] == "amount"
                rejected = await client.post(prefix+"/cash-flows", json=cash)
                assert rejected.status_code == 400, rejected.text
                assert rejected.json()["fieldErrors"][0]["field"] == "amount"
                assert rejected.json()["message"] == "转出金额超过当前可用现金，请检查。"
                status = await client.get(root+"/write-requests/"+cash["requestId"])
                assert status.status_code == 200 and status.json()["outcome"] == "NOT_SAVED", status.text
                recovered = await client.get(root+"/write-requests/"+cash["requestId"]+"/input")
                assert recovered.status_code == 200 and recovered.json()["input"]["amount"] == "2000.00"
                tampered = await client.post(prefix+"/cash-flows", json={**cash,"amount":"500.00"})
                assert tampered.status_code == 409 and tampered.json()["code"] == "TA_REQUEST_ID_CONFLICT"
                manual_fee = await client.post(prefix+"/cash-flows", json={**cash,"commissionAmount":"0.00"})
                assert manual_fee.status_code == 400
                saved_cash = await client.post(prefix+"/cash-flows", json={**cash, "requestId":str(uuid4()),
                    "attemptId":str(uuid4()), "amount":"500.00"})
                assert saved_cash.status_code == 201, saved_cash.text
                cash_id = saved_cash.json()["result"]["cashFlowId"]
                detail = await client.get(root+"/records/cash-flows/"+cash_id)
                assert detail.status_code == 200, detail.text
                assert detail.json()["record"]["amount"] == "500.00"
                assert detail.json()["revisions"]["nextCursor"] is None
                for query in ("limit=1&limit=2", "limit=1.0", "limit=0", "limit=101", "unexpected=1"):
                    assert (await client.get(root+"/records/cash-flows/"+cash_id+"?"+query)).status_code == 400
                assert (await client.get(root+"/records/cash-flows/"+cash_id)).json() == detail.json()
                preview = await client.post(prefix+"/cash-flows/"+cash_id+"/correction-preview", json=dict(
                    direction="OUT", occurredOn="2026-09-12", amount="600.00", expectedRevision="1"))
                assert preview.status_code == 200, preview.text
                assert preview.json()["before"]["netCashChange"] == "-500.00"
                assert preview.json()["after"]["netCashChange"] == "-600.00"
                assert preview.json()["fieldErrors"] == []
                context = await client.get(prefix+"/entry-context", params={"occurredOn":"2026-09-12"})
                assert context.status_code == 200, context.text
                assert context.json()["availableCash"] == "500.00" and context.json()["factVersion"] == "2"
                initial_preview = await client.post(prefix+"/initialization/correction-preview", json=dict(
                    initialCash="400.00", initialPositions=[], expectedRevision="1"))
                assert initial_preview.status_code == 200, initial_preview.text
                assert initial_preview.json()["before"]["initialCash"] == "1000.00"
                assert initial_preview.json()["after"]["initialCash"] == "400.00"
                assert initial_preview.json()["fieldErrors"][0]["field"] == "initialCash"
                owner = 2
                assert (await client.get(root+"/records/cash-flows/"+cash_id)).status_code == 404
                assert (await client.get(prefix+"/fees")).status_code == 404
                foreign = await client.get(root+"/write-requests/"+cash["requestId"])
                assert foreign.status_code == 404 and foreign.json()["code"] == "TA_RECOVERY_UNAVAILABLE"
                assert (await client.get(root+"/accounts")).json() == {"items":[]}
                schema = app.openapi()
                assert "CreateAccountCommand" in schema["components"]["schemas"]
        finally:
            await engine.dispose()
    asyncio.run(execute())
