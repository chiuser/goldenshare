"""Historical single-stock arithmetic and real fixed-publication reads."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from time import monotonic
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, insert

from src.biz.queries.wealth.market.trading_assistant.return_endpoints import StockReturnEndpoint
from src.biz.queries.wealth.market.trading_assistant.return_stock_days import PublishedStockReturnDaysQuery, stock_day_increment
from src.biz.queries.wealth.market.trading_assistant.return_stock_period import StockPeriodReturnsQuery
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


DAY = date(2026, 9, 11)
ROUND = UUID(int=1)


def endpoint(quantity=100, pool=100000, buys=100000, net=0, profit=20000, round_id=ROUND, opened=date(2026, 9, 10)):
    return StockReturnEndpoint("000001.SZ", round_id, opened,
        PositionState(quantity, quantity, pool, buys, net), profit)


@pytest.mark.parametrize("ending,prior,initial,expected", [
    (endpoint(profit=25000), endpoint(), 0, (5000, 100000, "5.00")),
    (endpoint(quantity=60, pool=60000, net=48000), endpoint(), 0, (0, 100000, "0.00")),
    (endpoint(quantity=0, pool=0, net=130000, profit=30000), endpoint(), 0, (10000, 100000, "10.00")),
    (endpoint(quantity=50, pool=55000, buys=155000, net=130000, profit=35000), endpoint(), 0, (15000, 155000, "9.68")),
    (endpoint(opened=DAY), None, 100000, (20000, 100000, "20.00")),
    (endpoint(opened=DAY, buys=110000, pool=110000, profit=10000, round_id=UUID(int=2)),
     endpoint(quantity=0, pool=0, net=130000, profit=30000), 0, (10000, 110000, "9.09")),
])
def test_stock_day_exact_endpoints(ending, prior, initial, expected):
    item = stock_day_increment(DAY, ending, prior, initial_cost_cents=initial)
    assert (item.result.profit_cents, item.result.capital_cents, item.result.return_pct) == expected


@pytest.mark.parametrize("ending,prior,initial", [
    (endpoint(), None, 0),
    (endpoint(), endpoint(), 1),
    (endpoint(buys=90000, pool=90000), endpoint(), 0),
    (endpoint(opened=DAY, round_id=UUID(int=2)), endpoint(), 0),
    (endpoint(), replace(endpoint(), stock="000002.SZ"), 0),
    (endpoint(opened=DAY), None, True),
])
def test_stock_day_rejects_mixed_or_missing_evidence(ending, prior, initial):
    with pytest.raises(ValueError):
        stock_day_increment(DAY, ending, prior, initial_cost_cents=initial)


def test_real_stock_day_pages_include_closed_stocks_and_rebuilt_round(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        with database.begin() as conn:
            conn.execute(insert(EquityDailyBar), [dict(ts_code=code, trade_date=date(2026, 9, 14), close=price, source="tushare")
                for code, price in (("000001.SZ", "12.00"), ("000101.SZ", "11.00"), ("000102.SZ", "12.00"))])
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    response = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                        name="历史贡献", brokerName="券商", commissionRateWan="3.00", minimumCommission="5.00",
                        stampTaxRatePct="0.05", initialCash="20000.00", initialPositions=[dict(clientRowId=code,
                            tsCode=code, openedOn="2026-09-10", quantity=1000, availableQuantity=1000, costPrice="10.00")
                            for code in ("000001.SZ", "000101.SZ", "000102.SZ")]))
                    assert response.status_code == 201, response.text
                    account = UUID(response.json()["result"]["account"]["accountId"])
                    await wait_stage(client, str(account), "PUBLISHED")
                    deps = app.state.trading_assistant

                    async def read(day, page_rows=1, owner=1, token=None, stock=None):
                        reader = PublishedStockReturnDaysQuery(replace(deps.policy, page_rows=page_rows))
                        def query(session, deadline, basis):
                            result, after, pages = [], None, 0
                            while True:
                                page = reader.page(session, owner_id=owner, basis=basis, account_id=account,
                                    day=day, deadline=deadline, after_stock=after, stock=stock)
                                result.extend(page.items)
                                pages += 1
                                after = page.next_stock
                                if after is None:
                                    return result, pages, basis.context.contextToken
                        return await deps.read_current(query, owner_id=owner, account_mode="SINGLE", account_id=account,
                            context_token=token, resolve_target_through=lambda s,d:app.state.fixture_clock[0])

                    initial, pages, token = await read(date(2026, 9, 10))
                    assert pages == 3 and sum(x.result.profit_cents for x in initial) == 496750
                    assert all(x.initial_cost_cents == 1000000 and x.buy_input_cents == 0 for x in initial)
                    assert all(x.result.profit_cents == 0 for x in (await read(DAY))[0])

                    async def trade(code, quantity, direction="SELL", price="12.00", day=DAY):
                        saved = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), direction=direction, tsCode=code,
                            tradeDate=day.isoformat(), quantity=quantity, price=price))
                        assert saved.status_code == 201, saved.text

                    await trade("000001.SZ", 1000)
                    await trade("000101.SZ", 400, price="11.00")
                    await wait_stage(client, str(account), "PUBLISHED")
                    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
                        await read(DAY, token=token)
                    statements = []
                    def observe(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = deps.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        rows, pages, _ = await read(DAY)
                    finally:
                        elapsed = monotonic() - began
                        event.remove(engine, "before_cursor_execute", observe)
                    assert rows == (await read(DAY, page_rows=3))[0]
                    assert [x.endpoint.stock for x in rows] == ["000001.SZ", "000101.SZ", "000102.SZ"]
                    assert rows[0].endpoint.state.quantity == 0 and rows[0].result.profit_cents == 0
                    assert rows[1].result.profit_cents == -500 and rows[2].result.profit_cents == 0
                    detail = await client.get(ROOT + "/returns/days/2026-09-11", params=dict(accountMode="SINGLE", accountId=str(account)))
                    assert detail.status_code == 200, detail.text
                    assert detail.json()["profitAmount"] == "-5.00"
                    assert sum(x.result.profit_cents for x in rows) == -500
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    assert elapsed < 5
                    print(f"M5 stock-day: pages={pages}, stocks={len(rows)}, SQL={len(statements)}, seconds={elapsed:.5f}")
                    assert not (await read(DAY, stock="000002.SZ"))[0]
                    with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
                        await read(DAY, owner=2)
                    app.state.fixture_clock[0] = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
                    await trade("000001.SZ", 1000, "BUY", price="11.00", day=date(2026, 9, 14))
                    until = monotonic() + 25
                    while True:
                        progress = (await client.get(ROOT + f"/accounts/{account}/calculation-status")).json()
                        if progress["stage"] == "PUBLISHED" and progress["progress"]["lastCompletedTradeDate"] == "2026-09-14":
                            break
                        assert monotonic() < until, progress
                        await asyncio.sleep(.05)
                    rebuilt = (await read(date(2026, 9, 14), stock="000001.SZ"))[0][0]
                    assert rebuilt.endpoint.round_id != rows[0].endpoint.round_id
                    assert (rebuilt.opening_cost_cents, rebuilt.initial_cost_cents, rebuilt.buy_input_cents) == (0, 0, 1100500)
                    assert (rebuilt.result.profit_cents, rebuilt.result.return_pct) == (98400, "8.94")
                    async def period(start, end, stock="000001.SZ", page_rows=1, selected_account=account):
                        reader = StockPeriodReturnsQuery(replace(deps.policy, page_rows=page_rows))
                        def query(session, deadline, basis):
                            return reader.read(session, owner_id=1, basis=basis, account_id=selected_account, stock=stock,
                                start=start, end=end, today=date(2026, 9, 14), deadline=deadline)
                        return await deps.read_current(query, owner_id=1, account_mode="SINGLE", account_id=selected_account,
                            resolve_target_through=lambda s,d:app.state.fixture_clock[0])
                    statements.clear()
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        whole = await period(date(2026, 9, 10), date(2026, 9, 14))
                    finally:
                        elapsed = monotonic() - began
                        event.remove(engine, "before_cursor_execute", observe)
                    assert elapsed < 5
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    print(f"M5 single-stock range: civil_pages=5, SQL={len(statements)}, seconds={elapsed:.5f}")
                    assert whole == await period(date(2026, 9, 10), date(2026, 9, 14), page_rows=3)
                    assert (whole.result.profit_cents, whole.result.capital_cents, whole.result.return_pct) == (297300, 2100500, "14.15")
                    assert whole.coverage.dataStatus == "Ready" and whole.coverage.accounts[0].calculatedThroughDate == "2026-09-14"
                    held = await period(DAY, date(2026, 9, 14), stock="000101.SZ")
                    assert (held.result.profit_cents, held.result.capital_cents, held.result.return_pct) == (-500, 1000000, "-0.05")
                    remaining = await period(date(2026, 9, 14), date(2026, 9, 14), stock="000101.SZ")
                    assert remaining.result.capital_cents == 600000
                    assert (await period(date(2026, 9, 12), date(2026, 9, 13))).result.status == "Empty"
                    assert (await period(DAY, DAY, stock="000002.SZ")).result.status == "Empty"
                    fees = (await client.get(ROOT + f"/accounts/{account}/fees")).json()
                    changed = await client.put(ROOT + f"/accounts/{account}/fees", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), expectedFeeVersionId=fees["feeVersionId"],
                        commissionRateWan="20.00", minimumCommission="50.00", stampTaxRatePct="0.10"))
                    assert changed.status_code == 200, changed.text
                    after_fees = await period(date(2026, 9, 10), date(2026, 9, 14))
                    assert after_fees == whole
                    missing = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                        name="缺价范围", brokerName="券商", commissionRateWan="3.00", minimumCommission="5.00",
                        stampTaxRatePct="0.05", initialCash="1000.00", initialPositions=[dict(clientRowId="missing",
                            tsCode="000002.SZ", openedOn="2026-09-10", quantity=100, availableQuantity=100, costPrice="10.00")]))
                    assert missing.status_code == 201, missing.text
                    missing_account = UUID(missing.json()["result"]["account"]["accountId"])
                    await wait_stage(client, str(missing_account), "WAITING_DATA")
                    delayed = await period(date(2026, 9, 10), date(2026, 9, 14), stock="000002.SZ", selected_account=missing_account)
                    assert delayed.result.status == delayed.coverage.dataStatus == "Delayed"
                    assert delayed.result.profit_cents is None and delayed.coverage.accounts[0].calculatedThroughDate is None
        asyncio.run(run())
