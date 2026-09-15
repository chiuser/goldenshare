"""Formal daily return route backed by real commands and M3 publication."""
import asyncio
from time import monotonic
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_daily_returns_actual_profit_fees_coverage_and_permissions(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    endpoint = ROOT + "/returns/days/2026-09-11"
                    login = await client.get("/test-session")
                    assert login.status_code == 200, login.text
                    client.headers["Authorization"] = "Bearer " + login.json()["token"]

                    async def create(code=None):
                        response = await client.post(ROOT + "/accounts", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), name=code or "现金", brokerName="券商",
                            commissionRateWan="3.00", minimumCommission="5.00", stampTaxRatePct="0.05",
                            initialCash="1000.00", initialPositions=[] if code is None else [dict(
                                clientRowId="one", tsCode=code, openedOn="2026-09-10", quantity=1000,
                                availableQuantity=1000, costPrice="10.00")]))
                        assert response.status_code == 201, response.text
                        account = response.json()["result"]["account"]["accountId"]
                        await wait_stage(client, account, "WAITING_DATA" if code == "000002.SZ" else "PUBLISHED")
                        return account

                    account = await create("000001.SZ")
                    params = dict(accountMode="SINGLE", accountId=account)
                    previous = await client.get(ROOT + "/returns/days/2026-09-10", params=params)
                    assert previous.status_code == 200, previous.text
                    assert previous.json()["profitAmount"] == "1989.00"
                    assert previous.json()["coverage"]["accounts"][0]["initializedOn"] == "2026-09-11"
                    token = previous.json()["readContext"]["contextToken"]
                    sold = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), direction="SELL", tsCode="000001.SZ",
                        tradeDate="2026-09-11", quantity=400, price="12.00"))
                    assert sold.status_code == 201, sold.text
                    await wait_stage(client, account, "PUBLISHED")
                    assert (await client.get(endpoint, params={**params, "readContext": token})).status_code == 409
                    cash = await create()
                    statements = []
                    def observe(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = app.state.trading_assistant.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        response = await client.get(endpoint, params={"accountMode": "ALL"})
                    finally:
                        elapsed = monotonic() - began
                        event.remove(engine, "before_cursor_execute", observe)
                    assert response.status_code == 200, response.text
                    value = response.json()
                    assert value["coverage"]["dataStatus"] == "Ready"
                    assert (value["profitAmount"], value["capitalAmount"], value["returnPct"]) == ("-5.00", "10000.00", "-0.05")
                    assert (value["closedTradeCount"], value["closedProfitAmount"]) == (1, "792.60")
                    assert (value["commissionAmount"], value["stampTaxAmount"], value["feeDataStatus"]) == ("5.00", "2.40", "Ready")
                    assert value["recordsScope"]["requestedStartDate"] == "2026-09-11"
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    assert elapsed < 5
                    print(f"M5 day API: accounts=2, SQL={len(statements)}, bytes={len(response.content)}, elapsed={elapsed:.5f}s")
                    cash_value = (await client.get(endpoint, params=dict(accountMode="SINGLE", accountId=cash))).json()
                    assert cash_value["coverage"]["dataStatus"] == "Empty" and cash_value["profitAmount"] is None
                    for day in ("2026-09-09", "2026-09-12"):
                        empty = await client.get(ROOT + "/returns/days/" + day, params=params)
                        assert empty.status_code == 200, empty.text
                        assert empty.json()["coverage"]["dataStatus"] == "Empty"
                    await create("000002.SZ")
                    partial = await client.get(endpoint, params={"accountMode": "ALL"})
                    assert partial.status_code == 200, partial.text
                    assert partial.json()["coverage"]["dataStatus"] == "Partial"
                    assert partial.json()["profitAmount"] is None
                    assert partial.json()["commissionAmount"] == "5.00"
                    for invalid in ("accountMode=ALL&extra=1", "accountMode=ALL&accountMode=ALL", "accountMode=SINGLE"):
                        assert (await client.get(endpoint + "?" + invalid)).status_code == 400
                    assert (await client.get(ROOT + "/returns/days/2026-02-30", params=params)).status_code == 400
                    assert (await client.get(endpoint, params=dict(accountMode="SINGLE", accountId=str(uuid4())))).status_code == 404
                    other = await client.get("/test-session", params={"user_id": 2})
                    client.headers["Authorization"] = "Bearer " + other.json()["token"]
                    assert (await client.get(endpoint, params=params)).status_code == 404
                    assert (await client.get(endpoint, params={**params, "readContext": token})).status_code == 404
                    del client.headers["Authorization"]
                    assert (await client.get(endpoint, params={"accountMode": "ALL"})).status_code == 401
        asyncio.run(run())
