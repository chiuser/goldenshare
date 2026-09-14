"""Actual owned API -> consistent positions/M3 -> current holding analysis."""
import asyncio
from dataclasses import replace
from time import monotonic
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_analysis_real_rounds_cross_accounts_and_closed_day(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    async def create(name, positions, cash="1000.00"):
                        response = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                            name=name, brokerName="券商", initialCash=cash, commissionRateWan="0.00",
                            minimumCommission="0.00", stampTaxRatePct="0.00", initialPositions=positions))
                        assert response.status_code == 201, response.text
                        account = response.json()["result"]["account"]["accountId"]
                        await wait_stage(client, account, "PUBLISHED")
                        return account
                    def initial(code, cost):
                        return dict(clientRowId=code, tsCode=code, openedOn="2026-09-10", quantity=100,
                                    availableQuantity=100, costPrice=cost)
                    first = await create("主账户", [initial(f"000{100+i}.SZ", "10.00" if i < 6 else "25.00") for i in range(1, 12)])
                    await create("同股账户", [initial("000101.SZ", "10.00")])
                    await create("纯现金", [], "500.00")
                    # Force both account and source scans over page boundaries.
                    positions = app.state.trading_assistant.positions
                    small = replace(app.state.trading_assistant.policy, page_rows=3)
                    positions.policy = positions.facts.policy = positions.industry.policy = small
                    app.state.trading_assistant.read_context.policy = small
                    parent = (await client.get(ROOT + "/positions", params={"accountMode":"ALL"})).json()
                    statements = []
                    def sql(connection, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = app.state.trading_assistant.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", sql)
                    start = monotonic()
                    response = await client.get(ROOT + "/positions/analysis", params={"accountMode":"ALL", "readContext":parent["readContext"]["contextToken"]})
                    elapsed = monotonic() - start
                    event.remove(engine, "before_cursor_execute", sql)
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert data["readContext"] == parent["readContext"]
                    assert data["top3WeightPct"] == parent["summary"]["top3WeightPct"]
                    assert data["cashAmount"] == "2500.00"
                    assert data["industries"][0]["industryCode"] == "BKTEST"
                    assert data["industries"][0]["weightPct"] == "100.00"
                    assert data["cumulative"]["positiveCount"] == 5 and data["cumulative"]["negativeCount"] == 6
                    assert data["cumulative"]["positiveAmount"] == "1600.00"
                    assert data["cumulative"]["negativeAmount"] == "-3900.00"
                    assert data["daily"]["flatCount"] == 11 and data["daily"]["positiveAmount"] == "0.00"
                    assert data["daily"]["maxPositive"] is None and data["daily"]["maxNegative"] is None
                    fact_pages = sum("sold_today" in statement and "GROUP BY" in statement for statement in statements)
                    assert fact_pages >= 6  # 11 held stocks, another held account, and a pure cash account.
                    assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements)
                    print(dict(sql=len(statements), fact_pages=fact_pages, elapsed=elapsed, bytes=len(response.content), stocks=len(parent["items"])))
                    assert elapsed < 5
                    # Fully close a held stock at a higher price: account day +900;
                    # current-holdings day stays zero; another account retains A.
                    sold = await client.post(ROOT + f"/accounts/{first}/trades", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                        direction="SELL", tsCode="000101.SZ", tradeDate="2026-09-11", price="20.00", quantity=100))
                    assert sold.status_code == 201, sold.text
                    await wait_stage(client, first, "PUBLISHED")
                    old = await client.get(ROOT + "/positions/analysis", params={"accountMode":"ALL", "readContext":parent["readContext"]["contextToken"]})
                    assert old.status_code == 409
                    single = {"accountMode":"SINGLE", "accountId":first}
                    parent = (await client.get(ROOT + "/positions", params=single)).json()
                    analysis = (await client.get(ROOT + "/positions/analysis", params=single)).json()
                    assert parent["summary"]["dayProfitAmount"] == "900.00"
                    assert analysis["daily"]["flatCount"] == 10 and analysis["daily"]["positiveAmount"] == "0.00"
                    assert analysis["cumulative"]["positiveAmount"] == "1400.00"
                    for invalid in ({"accountMode":"ALL", "accountId":first}, {"accountMode":"ALL", "extra":"x"}):
                        assert (await client.get(ROOT + "/positions/analysis", params=invalid)).status_code == 400
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session", params={"user_id":2})).json()["token"]
                    assert (await client.get(ROOT + "/positions/analysis", params=single)).status_code == 404
                    assert (await client.get(ROOT + "/positions/analysis", params={"accountMode":"ALL"})).json()["industries"] == []
        asyncio.run(run())


def test_analysis_all_industries_missing_prices_and_cash(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    async def create(name, rows, stage="PUBLISHED"):
                        response = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                            name=name, brokerName="券商", initialCash="1000.00", commissionRateWan="0.00",
                            minimumCommission="0.00", stampTaxRatePct="0.00", initialPositions=rows))
                        assert response.status_code == 201, response.text
                        account = response.json()["result"]["account"]["accountId"]
                        await wait_stage(client, account, stage)
                        return account
                    def initial(code):
                        return dict(clientRowId=code, tsCode=code, openedOn="2026-09-10", quantity=100, availableQuantity=100, costPrice="10.00")
                    account = await create("行业样本", [initial(f"{1200+i:06d}.SZ") for i in range(1, 12)])
                    params = {"accountMode":"SINGLE", "accountId":account}
                    response = await client.get(ROOT + "/positions/analysis", params=params)
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert len(data["industries"]) == 11 and len({row["industryCode"] for row in data["industries"]}) == 11
                    assert next(row for row in data["industries"] if row["industryCode"] is None)["marketValue"] == "1000.00"
                    assert data["top5WeightPct"] == "49.11" and data["top3WeightPct"] == "29.46"
                    for label in ("cumulative", "daily"):
                        contribution = data[label]
                        assert (contribution["positiveCount"], contribution["negativeCount"], contribution["flatCount"]) == (5, 3, 3)
                        assert contribution["positiveAmount"] == "500.00" and contribution["negativeAmount"] == "-300.00"
                        assert contribution["maxPositive"]["stockRef"]["tsCode"] == "001201.SZ"
                        assert contribution["maxNegative"]["stockRef"]["tsCode"] == "001206.SZ"
                    missing = await create("缺价", [initial("000002.SZ")], "WAITING_DATA")
                    data = (await client.get(ROOT + "/positions/analysis", params={"accountMode":"ALL"})).json()
                    assert data["top5WeightPct"] is None and all(row["weightPct"] is None for row in data["industries"])
                    assert data["cumulative"]["unknownCount"] == 1 and data["cumulative"]["flatCount"] == 3
                    assert data["cumulative"]["maxPositive"] is None and data["cumulative"]["positiveAmount"] == "500.00"
                    missing_data = (await client.get(ROOT + "/positions/analysis", params={"accountMode":"SINGLE", "accountId":missing})).json()
                    assert missing_data["daily"]["unknownCount"] == 1 and missing_data["daily"]["dataStatus"] != "Ready"
                    cash = await create("现金", [])
                    data = (await client.get(ROOT + "/positions/analysis", params={"accountMode":"SINGLE", "accountId":cash})).json()
                    assert data["cashWeightPct"] == "100.00" and data["industries"] == []
                    assert data["cumulative"]["dataStatus"] == "Empty" and data["largestPosition"] is None
        asyncio.run(run())
