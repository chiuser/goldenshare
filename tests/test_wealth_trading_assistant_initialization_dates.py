"""Approved INIT-DATE contract: explicit dates, unchanged cash, no invented trades."""
import asyncio
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_wealth_trading_assistant_persistence import database
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.biz.schemas.wealth.market.trading_assistant.accounts import InitializationPositionInput
from src.biz.services.wealth.market.trading_assistant.initialization_dates import affected_initialization_date
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.security_serving import Security


def row():
    return dict(clientRowId="initial-a", tsCode="000001.SZ", openedOn="2026-09-10",
                quantity=600, availableQuantity=600, costPrice="10.00")


@pytest.mark.parametrize("change,cash,expected", [
    ({"openedOn":"2026-09-09"}, False, "2026-09-09"),
    ({"openedOn":"2026-09-11"}, False, "2026-09-10"),
    ({"quantity":700}, False, "2026-09-10"),
    ({"costPrice":"11.00"}, False, "2026-09-10"),
    ({"availableQuantity":0}, False, "2026-09-12"),
    ({}, True, "2026-09-12"), ({}, False, "2026-09-12"),
])
def test_affected_date_is_not_always_submission_date(change, cash, expected):
    before = InitializationPositionInput(**row())
    after = InitializationPositionInput(**(row() | change))
    assert affected_initialization_date(date(2026,9,12), [before], [after], cash_changed=cash).isoformat() == expected


def test_dates_through_real_api_preview_save_and_recovery(database):
    with database.begin() as conn:
        conn.execute(insert(Security).values(ts_code="000001.SZ", name="测试股票", exchange="SZSE",
            security_type="EQUITY", curr_type="CNY", source="date-test").on_conflict_do_nothing())
        for day, opened in ((9,True),(10,True),(11,True),(12,False),(14,True)):
            conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=date(2026,9,day),
                is_open=opened, pretrade_date=date(2026,9,day-1)).on_conflict_do_nothing())

    async def execute():
        engine = create_async_engine(database.url)
        now = datetime(2026,9,12,8,tzinfo=timezone.utc)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda:now, executor_id="date-api")
        async def owner(): return 1
        app = FastAPI()
        app.include_router(create_trading_assistant_router(auth_dependency=owner,
            dependencies_dependency=lambda:deps), prefix="/api/v1")
        root = "/api/v1/wealth/market/trading-assistant"
        def ids(): return dict(requestId=str(uuid4()), attemptId=str(uuid4()))
        base = dict(name="日期账户", brokerName="券商", initialCash="1000.00",
            commissionRateWan="2.50", minimumCommission="5.00", stampTaxRatePct="0.05")
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                for value, message in ((None,"请输入有效的建仓日期。"), ("bad","请输入有效的建仓日期。"),
                    ("2026-09-14","建仓日期不能晚于今天。"), ("2026-09-12","请选择实际建仓的交易日。")):
                    response = await client.post(root+"/accounts", json=base | ids() | {"initialPositions":[row() | {"openedOn":value}]})
                    assert response.status_code == 400, response.text
                    assert response.json()["fieldErrors"][0]["message"] == message
                    assert response.json()["fieldErrors"][0]["clientRowId"] == "initial-a"
                missing = row(); del missing["openedOn"]
                response = await client.post(root+"/accounts", json=base | ids() | {"initialPositions":[missing]})
                assert response.status_code == 400 and response.json()["fieldErrors"][0]["message"] == "请选择建仓日期。"
                created = await client.post(root+"/accounts", json=base | ids() | {"initialPositions":[row()]})
                assert created.status_code == 201, created.text
                result = created.json()["result"]
                account = result["account"]["accountId"]
                assert result["account"]["initializedOn"] == "2026-09-12"
                prefix = root+"/accounts/"+account
                current = (await client.get(prefix+"/initialization")).json()
                assert current["initialPositions"][0]["openedOn"] == "2026-09-10"
                assert current["initialPositions"][0]["costAmount"] == "6000.00"
                assert current["initialCash"] == "1000.00"
                now = datetime(2026,9,14,8,tzinfo=timezone.utc)
                correction = dict(initialCash="1000.00", expectedRevision="1", initialPositions=[row() | {"openedOn":"2026-09-14"}])
                preview = await client.post(prefix+"/initialization/correction-preview", json=correction)
                assert preview.status_code == 400, preview.text
                command = correction | ids()
                saved = await client.post(prefix+"/initialization/corrections", json=command)
                assert saved.status_code == 400, saved.text
                assert saved.json()["fieldErrors"][0]["message"] == "建仓日期不能晚于首次录入日期。"
                recovered = await client.get(root+"/write-requests/"+command["requestId"]+"/input")
                assert recovered.status_code == 200, recovered.text
                assert recovered.json()["input"]["initialPositions"][0]["openedOn"] == "2026-09-14"
                correction["initialPositions"] = [row() | {"openedOn":"2026-09-11"}]
                preview = await client.post(prefix+"/initialization/correction-preview", json=correction)
                assert preview.status_code == 200, preview.text
                assert preview.json()["affectedFromDate"] == "2026-09-10"
                assert {"field":"initialPositions.openedOn","clientRowId":"initial-a"} in preview.json()["changedFields"]
                saved = await client.post(prefix+"/initialization/corrections", json=correction | ids())
                assert saved.status_code == 200, saved.text
                current = (await client.get(prefix+"/initialization")).json()
                assert current["initialPositions"][0]["openedOn"] == "2026-09-11"
                with database.connect() as conn:
                    assert conn.scalar(select(func.count()).select_from(Ledger).where(Ledger.account_id==UUID(account))) == 0
                    assert set(conn.scalars(select(InitialPosition.opened_on).where(InitialPosition.account_id==UUID(account)))) == {date(2026,9,10),date(2026,9,11)}
                    assert conn.scalar(select(Recalculation.affected_from_date).where(Recalculation.account_id==UUID(account))) == date(2026,9,10)
        finally:
            await engine.dispose()
    asyncio.run(execute())
