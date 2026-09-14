"""Real commands -> M3 publication -> formal positions endpoints in isolated PG."""
import asyncio
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_positions_use_real_publication_and_keep_unknown_facts(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    accounts = []
                    for stock in ("000001.SZ", "000002.SZ"):
                        response = await client.post(ROOT + "/accounts", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), name=stock, brokerName="券商",
                            initialCash="1000.00", commissionRateWan="3.00", minimumCommission="5.00",
                            stampTaxRatePct="0.05", initialPositions=[dict(clientRowId="one", tsCode=stock,
                                openedOn="2026-09-10", quantity=1000, availableQuantity=600, costPrice="10.00")]))
                        assert response.status_code == 201, response.text
                        account_id = response.json()["result"]["account"]["accountId"]
                        accounts.append(account_id)
                        await wait_stage(client, account_id, "PUBLISHED" if stock == "000001.SZ" else "WAITING_DATA")
                    response = await client.get(ROOT + "/positions", params={"accountMode":"SINGLE", "accountId":accounts[0]})
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert data["summary"]["stockMarketValue"] == "12000.00"
                    assert data["summary"]["holdingProfitAmount"] == "1989.00"
                    assert data["items"][0]["availableQuantity"] == "600"
                    assert data["items"][0]["estimatedTotalFeeAmount"] == "11.00"
                    detail = await client.get(ROOT + "/positions/000001.SZ", params={"accountMode":"SINGLE",
                        "accountId":accounts[0], "readContext":data["readContext"]["contextToken"]})
                    assert detail.status_code == 200, detail.text
                    assert detail.json()["accountRounds"][0]["openingSource"] == "INITIALIZATION"
                    assert detail.json()["accountRounds"][0]["roundRef"]["roundNumber"] == 1
                    response = await client.get(ROOT + "/positions", params={"accountMode":"ALL"})
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert len(data["items"]) == 2
                    assert data["summary"]["stockMarketValue"] is None
                    assert data["summary"]["cashAmount"] == "2000.00"
                    missing = next(item for item in data["items"] if item["stockRef"]["tsCode"] == "000002.SZ")
                    assert missing["quantity"] == "1000" and missing["accountRounds"] == []
                    assert missing["marketValue"] is None
                    for params in ({"accountMode":"ALL", "accountId":accounts[0]},
                                   {"accountMode":"ALL", "unexpected":"x"}):
                        invalid = await client.get(ROOT + "/positions", params=params)
                        assert invalid.status_code == 400, invalid.text
        asyncio.run(run())
