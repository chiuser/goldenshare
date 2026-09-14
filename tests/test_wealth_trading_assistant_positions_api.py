"""Real commands -> M3 publication -> formal positions endpoints in isolated PG."""
import asyncio
from time import monotonic
from dataclasses import replace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from src.biz.queries.wealth.market.trading_assistant.positions import PositionsQuery
from src.biz.queries.wealth.market.trading_assistant.read_context import CurrentReadContextQuery

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
                    login = await client.get("/test-session")
                    assert login.status_code == 200, login.text
                    client.headers["Authorization"] = "Bearer " + login.json()["token"]
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
                    old_context = data["readContext"]["contextToken"]
                    sale = await client.post(ROOT + f"/accounts/{accounts[0]}/trades", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), direction="SELL", tsCode="000001.SZ",
                        tradeDate="2026-09-11", price="12.00", quantity=400, note=None))
                    assert sale.status_code == 201, sale.text
                    await wait_stage(client, accounts[0], "PUBLISHED")
                    old = await client.get(ROOT + "/positions/000001.SZ", params={"accountMode":"SINGLE", "accountId":accounts[0], "readContext":old_context})
                    assert old.status_code == 409, old.text
                    current = (await client.get(ROOT + "/positions", params={"accountMode":"SINGLE", "accountId":accounts[0]})).json()
                    assert current["summary"]["cashAmount"] == "5792.60"
                    assert current["summary"]["holdingProfitAmount"] == "1984.00"
                    assert current["items"][0]["quantity"] == "600"
                    assert current["items"][0]["availableQuantity"] == "200"
                    response = await client.get(ROOT + "/positions", params={"accountMode":"ALL"})
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert len(data["items"]) == 2
                    assert data["summary"]["stockMarketValue"] is None
                    assert data["summary"]["cashAmount"] == "6792.60"
                    missing = next(item for item in data["items"] if item["stockRef"]["tsCode"] == "000002.SZ")
                    assert missing["quantity"] == "1000" and missing["accountRounds"] == []
                    assert missing["marketValue"] is None
                    for params in ({"accountMode":"ALL", "accountId":accounts[0]},
                                   {"accountMode":"ALL", "unexpected":"x"}):
                        invalid = await client.get(ROOT + "/positions", params=params)
                        assert invalid.status_code == 400, invalid.text
        asyncio.run(run())


def test_cash_t1_negative_cost_and_fully_closed_day(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    response = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                        name="现金后买入", brokerName="券商", initialCash="20000.00", commissionRateWan="0.00",
                        minimumCommission="0.00", stampTaxRatePct="0.00", initialPositions=[]))
                    assert response.status_code == 201, response.text
                    account = response.json()["result"]["account"]["accountId"]
                    params = {"accountMode":"SINGLE", "accountId":account}
                    await wait_stage(client, account, "PUBLISHED")
                    cash = (await client.get(ROOT + "/positions", params=params)).json()
                    assert cash["items"] == [] and cash["summary"]["dayReturnPct"] is None
                    assert cash["allocation"]["stockValueSlices"] is None
                    assert cash["allocation"]["totalAssetSlices"][0]["weightPct"] == "100.00"

                    async def trade(direction, quantity, price, day="2026-09-11"):
                        return await client.post(ROOT + f"/accounts/{account}/trades", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), direction=direction,
                            tsCode="000001.SZ", quantity=quantity, price=price, tradeDate=day))
                    bought = await trade("BUY", 1000, "10.00")
                    assert bought.status_code == 201, bought.text
                    await wait_stage(client, account, "PUBLISHED")
                    held = (await client.get(ROOT + "/positions", params=params)).json()
                    assert held["items"][0]["availableQuantity"] == "0"
                    rejected = await trade("SELL", 1, "12.00")
                    assert rejected.status_code == 400, rejected.text
                    # Advance the fixture clock across the explicitly closed weekend.
                    # M3 catches up using existing market facts; no fake result inserts.
                    from datetime import datetime, timezone
                    app.state.fixture_clock[0] = datetime(2026, 9, 14, 2, tzinfo=timezone.utc)
                    unlocked = (await client.get(ROOT + "/positions", params=params)).json()
                    assert unlocked["items"][0]["availableQuantity"] == "1000"
                    assert unlocked["summary"]["dayProfitAmount"] is None
                    assert unlocked["items"][0]["quoteAt"].startswith("2026-09-11")
                    sale = await trade("SELL", 400, "25.00", "2026-09-14")
                    assert sale.status_code == 201, sale.text
                    # At the new close provide only a real source bar and let M3 publish.
                    from sqlalchemy import insert
                    from datetime import date
                    from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
                    with database.begin() as connection:
                        connection.execute(insert(EquityDailyBar), dict(ts_code="000001.SZ", trade_date=date(2026, 9, 14), close="12.00", source="tushare"))
                    app.state.fixture_clock[0] = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
                    await wait_stage(client, account, "PUBLISHED")
                    zero_cost = (await client.get(ROOT + "/positions", params=params)).json()
                    assert zero_cost["items"][0]["dynamicCostAmount"] == "0.00"
                    assert zero_cost["items"][0]["holdingReturnPct"] == "72.00"
                    sale = await trade("SELL", 100, "30.00", "2026-09-14")
                    assert sale.status_code == 201, sale.text
                    await wait_stage(client, account, "PUBLISHED")
                    negative = (await client.get(ROOT + "/positions", params=params)).json()
                    assert negative["items"][0]["dynamicCostAmount"] == "-3000.00"
                    assert negative["items"][0]["holdingReturnPct"] == "90.00"
                    sale = await trade("SELL", 500, "12.00", "2026-09-14")
                    assert sale.status_code == 201, sale.text
                    await wait_stage(client, account, "PUBLISHED")
                    closed = (await client.get(ROOT + "/positions", params=params)).json()
                    assert closed["items"] == []
                    assert closed["summary"]["holdingReturnPct"] is None
                    assert closed["summary"]["dayProfitAmount"] == "7000.00"
                    assert closed["summary"]["dayReturnPct"] == "70.00"
        asyncio.run(run())


def test_eleven_stocks_cross_account_weights_and_permissions(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)
        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    login = await client.get("/test-session")
                    assert login.status_code == 200, login.text
                    client.headers["Authorization"] = "Bearer " + login.json()["token"]
                    accounts = []
                    for index, count in enumerate((11, 1)):
                        response = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                            name=f"账户{index}", brokerName="测试券商", initialCash="1000.00", commissionRateWan="3.00",
                            minimumCommission="5.00" if index == 0 else "10.00", stampTaxRatePct="0.05",
                            initialPositions=[dict(clientRowId=str(i), tsCode=f"{100+i:06d}.SZ", openedOn="2026-09-10",
                                quantity=100, availableQuantity=100, costPrice="10.00") for i in range(1, count+1)]))
                        assert response.status_code == 201, response.text
                        account = response.json()["result"]["account"]["accountId"]
                        accounts.append(account)
                        await wait_stage(client, account, "PUBLISHED")
                    deps = app.state.trading_assistant
                    policy = replace(deps.policy, page_rows=3)
                    app.state.trading_assistant = replace(deps, policy=policy, positions=PositionsQuery(policy), read_context=CurrentReadContextQuery(policy))
                    statements = []
                    def counted(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    event.listen(deps.transactions.engine.sync_engine, "before_cursor_execute", counted)
                    started = monotonic()
                    response = await client.get(ROOT + "/positions", params={"accountMode":"ALL"})
                    event.remove(deps.transactions.engine.sync_engine, "before_cursor_execute", counted)
                    assert response.status_code == 200, response.text
                    elapsed = monotonic() - started
                    result = response.json()
                    assert len(result["items"]) == 11
                    assert result["summary"]["stockMarketValue"] == "18700.00"
                    assert result["summary"]["cashAmount"] == "2000.00"
                    assert result["summary"]["holdingProfitAmount"] == "6625.65"
                    assert result["summary"]["top3WeightPct"] == "33.69"
                    first = result["items"][0]
                    assert first["stockRef"]["tsCode"] == "000101.SZ"
                    assert first["quantity"] == first["availableQuantity"] == "200"
                    assert first["estimatedSellCommission"] == "15.00"
                    assert first["industry"] == "测试三级行业"
                    assert first["valuationMethod"] == "SAME_DAY_CLOSE"
                    for key, count in (("stockValueSlices", 8), ("totalAssetSlices", 9)):
                        slices = result["allocation"][key]
                        assert len(slices) == count
                        other = next(item for item in slices if item["kind"] == "OTHER")
                        assert len(other["members"]) == 4
                        codes = [item["stockRef"]["tsCode"] for item in slices if item["kind"] == "STOCK"] + [item["stockRef"]["tsCode"] for item in other["members"]]
                        assert len(set(codes)) == 11
                    detail = await client.get(ROOT + "/positions/000101.SZ", params={"accountMode":"ALL", "readContext":result["readContext"]["contextToken"]})
                    assert detail.status_code == 200, detail.text
                    assert len(detail.json()["accountRounds"]) == 2
                    assert {item["estimatedSellCommission"] for item in detail.json()["accountRounds"]} == {"5.00", "10.00"}
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session", params={"user_id":2})).json()["token"]
                    forbidden = await client.get(ROOT + "/positions", params={"accountMode":"SINGLE", "accountId":accounts[0]})
                    assert forbidden.status_code == 404, forbidden.text
                    fact_pages = sum("sold_today" in sql and "GROUP BY" in sql for sql in statements)
                    assert fact_pages >= 5  # 11 stocks / 3 per page plus the second account.
                    assert elapsed < 5
                    print(f"M42 real positions: rows=11 accounts=2 page_size=3 fact_pages={fact_pages} sql={len(statements)} bytes={len(response.content)} seconds={elapsed:.4f}")
        asyncio.run(run())


def test_confirmed_suspension_exposes_original_price_date(tmp_path):
    from datetime import date
    from sqlalchemy import insert
    from src.foundation.models.core_serving.security_serving import Security
    from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
    from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
    from src.foundation.models.core.equity_suspend_d import EquitySuspendD
    with isolated_postgres(tmp_path) as database:
        seed(database)
        code = "000003.SZ"
        with database.begin() as connection:
            connection.execute(insert(Security), dict(ts_code=code, symbol="000003", name="停牌样本", exchange="SZSE",
                security_type="EQUITY", curr_type="CNY", list_status="L", source="isolated-test"))
            connection.execute(insert(EquityDailyBar), dict(ts_code=code, trade_date=date(2026, 9, 10), close="10.1234", source="tushare"))
            connection.execute(insert(EquityAdjFactor), [dict(ts_code=code, trade_date=date(2026, 9, day), adj_factor="1.00") for day in (10, 11)])
            connection.execute(insert(EquitySuspendD), dict(ts_code=code, trade_date=date(2026, 9, 11), row_key_hash=uuid4().hex, suspend_type="S", suspend_timing=None))
        app = browser_app(database)
        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    created = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                        name="停牌", brokerName="券商", initialCash="0.00", commissionRateWan="0.00", minimumCommission="0.00", stampTaxRatePct="0.00",
                        initialPositions=[dict(clientRowId="one", tsCode=code, openedOn="2026-09-10", quantity=1000, availableQuantity=1000, costPrice="10.00")]))
                    assert created.status_code == 201, created.text
                    account = created.json()["result"]["account"]["accountId"]
                    await wait_stage(client, account, "PUBLISHED")
                    response = await client.get(ROOT + "/positions", params={"accountMode":"SINGLE", "accountId":account})
                    assert response.status_code == 200, response.text
                    row = response.json()["items"][0]
                    assert row["price"] == "10.12" and row["marketValue"] == "10123.40"
                    assert row["valuationDate"] == "2026-09-11" and row["priceDate"] == "2026-09-10"
                    assert row["valuationMethod"] == "CONFIRMED_SUSPENSION_CARRY"
                    assert row["dayProfitAmount"] == "0.00" and response.json()["summary"]["dayReturnPct"] == "0.00"
                    detail = await client.get(ROOT + "/positions/" + code, params={"accountMode":"SINGLE", "accountId":account, "readContext":response.json()["readContext"]["contextToken"]})
                    assert detail.status_code == 200, detail.text
                    assert detail.json()["accountRounds"][0]["priceDate"] == "2026-09-10"
                    from datetime import datetime, timezone
                    app.state.fixture_clock[0] = datetime(2026, 9, 15, 8, tzinfo=timezone.utc)
                    unavailable = await client.get(ROOT + "/positions", params={"accountMode":"SINGLE", "accountId":account})
                    assert unavailable.status_code == 200, unavailable.text
                    missing = unavailable.json()["items"][0]
                    assert missing["quantity"] == "1000" and missing["availableQuantity"] is None
                    assert missing["price"] is None and missing["accountRounds"] == []
                    assert missing["dataStatus"] == "Error" and "交易日历" in missing["reason"]
        asyncio.run(run())
