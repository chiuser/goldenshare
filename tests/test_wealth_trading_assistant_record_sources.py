"""Real commands and M3 publication exercise record source SQL, not fake profits."""
import asyncio
from datetime import date
from uuid import uuid4
from time import monotonic

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select

from src.biz.queries.wealth.market.trading_assistant.record_sources import (
    record_facts, with_published_closed, filtered_records, trade_day_groups,
)
from src.biz.queries.wealth.market.trading_assistant.record_group_projection import project_trade_day_group
from src.biz.schemas.wealth.market.trading_assistant.common import AccountRef, StockRef
from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import NOW, browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_real_published_group_revisions_and_owner_isolation(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    identity = lambda: dict(requestId=str(uuid4()), attemptId=str(uuid4()))
                    app.state.fixture_clock[0] = NOW.replace(day=10)
                    response = await client.post(ROOT + "/accounts", json=dict(**identity(), name="日汇总", brokerName="券商",
                        initialCash="1000.00", commissionRateWan="2.50", minimumCommission="5.00", stampTaxRatePct="0.05",
                        initialPositions=[dict(clientRowId="a", tsCode="000001.SZ", openedOn="2026-09-10",
                            quantity=6000, availableQuantity=6000, costPrice="40.01")]))
                    assert response.status_code == 201, response.text
                    account = response.json()["result"]["account"]["accountId"]
                    app.state.fixture_clock[0] = NOW
                    ids = []
                    for quantity, price in ((2000, "40.20"), (3000, "40.40")):
                        response = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(**identity(),
                            tsCode="000001.SZ", tradeDate="2026-09-11", direction="SELL", price=price, quantity=quantity))
                        assert response.status_code == 201, response.text
                        ids.append(response.json()["result"]["tradeId"])
                    await wait_stage(client, account, "PUBLISHED")

                    params = dict(accountMode="ALL", stockMode="ALL", requestedStartDate="2026-09-11", requestedEndDate="2026-09-11")
                    statements = []
                    def observed(connection, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = app.state.trading_assistant.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observed)
                    started = monotonic()
                    try:
                        response = await client.get(ROOT + "/records/trade-day-groups", params=params)
                    finally:
                        event.remove(engine, "before_cursor_execute", observed)
                    elapsed = monotonic() - started
                    assert elapsed < 5
                    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
                    print(dict(day_group_sql=len(statements), seconds=elapsed, response_bytes=len(response.content)))
                    assert response.status_code == 200, response.text
                    group = response.json()["items"][0]
                    assert (group["closedProfitAmount"], group["closedReturnPct"], group["allocatedCost"]) == ("1398.80", "0.70", "200050.00")
                    response = await client.get(ROOT + "/records/trades", params={**params, "limit": 1})
                    assert response.status_code == 200, response.text
                    first = response.json()
                    assert len(first["items"]) == 1 and first["nextCursor"]
                    assert first["items"][0]["closedDataStatus"] == "Ready"
                    assert first["items"][0]["closedReason"] is None
                    detail = await client.get(ROOT + f"/records/trades/{ids[0]}", params={
                        "readContext": first["readContext"]["contextToken"]})
                    assert detail.status_code == 200, detail.text
                    closed = detail.json()["closedTrade"]
                    assert closed["tradeId"] == ids[0]
                    assert closed["dayOpeningUnitCost"] == "40.01"
                    assert closed["dayEndQuantity"] == "1000"
                    assert closed["allocatedCost"] == "80020.00"
                    assert closed["profitAmount"] == "319.70"
                    assert closed["roundRef"]["roundNumber"] == 1
                    assert detail.json()["record"]["closedDataStatus"] == "Ready"
                    statements.clear()
                    event.listen(engine, "before_cursor_execute", observed)
                    started = monotonic()
                    try:
                        ranged = await client.get(ROOT + "/records/closed-trades", params={**params, "limit":1})
                    finally:
                        event.remove(engine, "before_cursor_execute", observed)
                    elapsed = monotonic() - started
                    assert elapsed < 5
                    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
                    print(dict(closed_sql=len(statements), seconds=elapsed, response_bytes=len(ranged.content)))
                    assert ranged.status_code == 200, ranged.text
                    page = ranged.json()
                    assert page["summary"] == dict(closedTradeCount=2, closedProfitAmount="1398.80", dataStatus="Ready", reason=None)
                    assert len(page["items"]) == 1 and page["nextCursor"]
                    tail = await client.get(ROOT + "/records/closed-trades", params={**params, "limit":1,
                        "cursor":page["nextCursor"], "readContext":page["readContext"]["contextToken"]})
                    assert tail.status_code == 200, tail.text
                    assert tail.json()["summary"] == page["summary"]
                    assert {page["items"][0]["tradeId"], tail.json()["items"][0]["tradeId"]} == set(ids)
                    round_params = dict(accountId=account, roundId=closed["roundRef"]["roundId"],
                        readContext=page["readContext"]["contextToken"])
                    whole = await client.get(ROOT + "/records/closed-trades", params=round_params)
                    assert whole.status_code == 200, whole.text
                    assert whole.json()["requestedStartDate"] == "2026-09-10"
                    assert whole.json()["recordsScope"] == {key:round_params[key] for key in ("accountId", "roundId")}
                    assert [r["tradeId"] for r in whole.json()["items"]] == [tail.json()["items"][0]["tradeId"], page["items"][0]["tradeId"]]
                    round_head = await client.get(ROOT + "/records/closed-trades", params={**round_params, "limit":1})
                    assert round_head.status_code == 200, round_head.text
                    round_tail = await client.get(ROOT + "/records/closed-trades", params={**round_params, "limit":1,
                        "cursor":round_head.json()["nextCursor"]})
                    assert round_tail.status_code == 200, round_tail.text
                    assert round_tail.json()["nextCursor"] is None
                    assert round_head.json()["items"] + round_tail.json()["items"] == whole.json()["items"]
                    assert round_tail.json()["summary"] == whole.json()["summary"]
                    absent = await client.get(ROOT + "/records/closed-trades", params={**round_params, "roundId":str(uuid4())})
                    assert absent.status_code == 404, absent.text
                    owner_token = client.headers["Authorization"]
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session", params={"user_id":2})).json()["token"]
                    foreign = await client.get(ROOT + "/records/closed-trades", params=round_params)
                    assert foreign.status_code == 404, foreign.text
                    client.headers["Authorization"] = owner_token
                    for patch in ({"accountMode":"ALL"}, {"requestedStartDate":"2026-09-11"}, {"tsCode":"000001.SZ"}, {"cursor":page["nextCursor"]}):
                        assert (await client.get(ROOT + "/records/closed-trades", params={**round_params, **patch})).status_code == 400
                    response = await client.get(ROOT + "/records/trades", params={**params, "limit": 1,
                        "cursor": first["nextCursor"], "readContext": first["readContext"]["contextToken"]})
                    assert response.status_code == 200, response.text
                    second = response.json()
                    assert second["nextCursor"] is None
                    assert {first["items"][0]["tradeId"], second["items"][0]["tradeId"]} == set(ids)
                    assert first["readContext"] == second["readContext"]
                    summary = await client.get(ROOT + "/records/summary", params=params)
                    assert summary.status_code == 200, summary.text
                    assert summary.json()["tradeCount"] == summary.json()["closedTradeCount"] == 2
                    assert summary.json()["closedProfitAmount"] == "1398.80"
                    assert summary.json()["cashInAmount"] == "0.00"  # Initialization is not a transfer.
                    for patch in ({"limit":"1.0"}, {"limit":"101"}, {"unknown":"x"}, {"cursor":"garbage"}):
                        assert (await client.get(ROOT + "/records/trades", params={**params, **patch})).status_code == 400

                    async def read(owner=1, start=date(2026, 9, 11), end=date(2026, 9, 11)):
                        deps = app.state.trading_assistant
                        def query(session, deadline, basis):
                            source = with_published_closed(record_facts(owner_id=owner, basis=basis))
                            filtered = filtered_records(source, kind="TRADE", start=start, end=end)
                            rows = session.execute(select(filtered).order_by(filtered.c.ledger_id)).all()
                            groups = session.execute(select(trade_day_groups(filtered))).all()
                            return rows, groups
                        return await deps.read_current(query, owner_id=owner, account_mode="ALL", account_id=None,
                            resolve_target_through=lambda session, deadline: NOW)

                    rows, groups = await read()
                    assert len(rows) == 2 and len(groups) == 1 and groups[0].closed_count == 2
                    dto = project_trade_day_group(groups[0], account_ref=AccountRef(accountId=account, name="日汇总", brokerName="券商"),
                        stock_ref=StockRef(tsCode="000001.SZ", name="平安银行"), closed_state="Ready", reason=None)
                    assert (dto.quantity, dto.averagePrice, dto.grossAmount) == ("5000", "40.32", "201600.00")
                    assert (dto.commissionAmount, dto.stampTaxAmount, dto.netCashChange) == ("50.40", "100.80", "201448.80")
                    assert (dto.allocatedCost, dto.closedProfitAmount, dto.closedReturnPct) == ("200050.00", "1398.80", "0.70")
                    assert await read(owner=2) == ([], [])
                    # Effective selection happens before date filtering: a moved
                    # sale must not resurrect its revision 1 on the old date.
                    response = await client.post(ROOT + f"/accounts/{account}/trades/{ids[0]}/corrections", json=dict(**identity(),
                        expectedRevision="1", tsCode="000001.SZ", tradeDate="2026-09-10", direction="SELL", price="40.20", quantity=2000))
                    assert response.status_code == 200, response.text
                    stale = await client.get(ROOT + "/records/trades", params={**params, "cursor":first["nextCursor"]})
                    assert stale.status_code == 409, stale.text
                    stale_detail = await client.get(ROOT + f"/records/trades/{ids[0]}", params={
                        "readContext":first["readContext"]["contextToken"]})
                    assert stale_detail.status_code == 409, stale_detail.text
                    stale_closed = await client.get(ROOT + "/records/closed-trades", params={**params,
                        "cursor":page["nextCursor"], "readContext":page["readContext"]["contextToken"]})
                    assert stale_closed.status_code == 409, stale_closed.text
                    rows, groups = await read()
                    assert len(rows) == 1 and str(rows[0].ledger_id) == ids[1]
                    await wait_stage(client, account, "PUBLISHED")
                    rows, groups = await read(start=date(2026, 9, 10))
                    assert len(rows) == 2 and len(groups) == 2
                    assert all(row.closed_source_id is not None for row in rows)
                    corrected = await client.get(ROOT + f"/records/trades/{ids[0]}")
                    assert corrected.status_code == 200, corrected.text
                    assert corrected.json()["closedTrade"]["sellRevision"] == "2"
                    assert corrected.json()["closedTrade"]["dayOpeningUnitCost"] == "40.01"
                    assert corrected.json()["closedTrade"]["dayEndQuantity"] == "4000"
                    assert corrected.json()["revisions"]["items"][1]["closedDataStatus"] == "Empty"
                    response = await client.post(ROOT + f"/accounts/{account}/trades/{ids[0]}/voids", json=dict(**identity(), expectedRevision="2"))
                    assert response.status_code == 200, response.text
                    rows, groups = await read(start=date(2026, 9, 10))
                    assert len(rows) == 1 and str(rows[0].ledger_id) == ids[1]
                    detail = await client.get(ROOT + f"/records/trades/{ids[0]}", params={"limit":1})
                    assert detail.status_code == 200, detail.text
                    body = detail.json()
                    assert body["closedTrade"] is None and body["record"]["status"] == "VOID"
                    assert body["record"]["closedDataStatus"] == "Empty"
                    history = await client.get(ROOT + f"/records/trades/{ids[0]}", params={"limit":1,
                        "cursor":body["revisions"]["nextCursor"], "readContext":body["readContext"]["contextToken"]})
                    assert history.status_code == 200, history.text
                    historical = history.json()["revisions"]["items"][0]
                    assert historical["revision"] == "2" and historical["closedDataStatus"] == "Empty"
                    assert historical["closedReason"] == "历史修订不关联当前闭环"
        asyncio.run(run())


def test_cash_pages_summary_full_scope_and_same_content_kept(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    identity = lambda: dict(requestId=str(uuid4()), attemptId=str(uuid4()))
                    response = await client.post(ROOT + "/accounts", json=dict(**identity(), name="资金分页", brokerName="券商",
                        initialCash="1000.00", commissionRateWan="0.00", minimumCommission="0.00", stampTaxRatePct="0.00", initialPositions=[]))
                    assert response.status_code == 201, response.text
                    account = response.json()["result"]["account"]["accountId"]
                    ids = set()
                    for index in range(23):
                        response = await client.post(ROOT + f"/accounts/{account}/cash-flows", json=dict(**identity(),
                            occurredOn="2026-09-11", direction="IN" if index < 22 else "OUT", amount="10.00"))
                        assert response.status_code == 201, response.text
                        ids.add(response.json()["result"]["cashFlowId"])
                    await wait_stage(client, account, "PUBLISHED")
                    params = dict(accountMode="SINGLE", accountId=account, requestedStartDate="2026-09-01", requestedEndDate="2026-09-11")
                    empty = await client.get(ROOT + "/records/closed-trades", params={**params, "stockMode":"ALL"})
                    assert empty.status_code == 200, empty.text
                    assert empty.json()["items"] == [] and empty.json()["nextCursor"] is None
                    assert empty.json()["summary"] == dict(closedTradeCount=0, closedProfitAmount="0.00", dataStatus="Empty", reason=None)
                    response = await client.get(ROOT + "/records/cash-flows", params=params)
                    assert response.status_code == 200, response.text
                    first = response.json()
                    assert len(first["items"]) == 20 and first["nextCursor"]
                    response = await client.get(ROOT + "/records/cash-flows", params={**params, "cursor":first["nextCursor"],
                        "readContext":first["readContext"]["contextToken"]})
                    assert response.status_code == 200, response.text
                    second = response.json()
                    assert len(second["items"]) == 3 and second["nextCursor"] is None
                    assert {r["cashFlowId"] for r in first["items"] + second["items"]} == ids
                    response = await client.get(ROOT + "/records/summary", params={**params, "stockMode":"ALL"})
                    assert response.status_code == 200, response.text
                    summary = response.json()
                    assert (summary["cashInAmount"], summary["cashOutAmount"], summary["tradeCount"]) == ("220.00", "10.00", 0)
                    assert summary["closedProfitAmount"] == "0.00" and summary["closedDataStatus"] == "Empty"
                    changed = await client.get(ROOT + "/records/cash-flows", params={**params, "direction":"IN", "cursor":first["nextCursor"]})
                    assert changed.status_code == 400
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session", params={"user_id":2})).json()["token"]
                    assert (await client.get(ROOT + "/records/cash-flows", params=params)).status_code == 404
                    other = await client.get(ROOT + "/records/cash-flows", params={k:v for k,v in {**params, "accountMode":"ALL"}.items() if k != "accountId"})
                    assert other.status_code == 200 and other.json()["items"] == []
        asyncio.run(run())


def test_missing_quote_sale_is_readable_but_not_marked_closed(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    identity = lambda: dict(requestId=str(uuid4()), attemptId=str(uuid4()))
                    response = await client.post(ROOT + "/accounts", json=dict(**identity(), name="缺行情",
                        brokerName="券商", initialCash="1000.00", commissionRateWan="0.00", minimumCommission="0.00",
                        stampTaxRatePct="0.00", initialPositions=[dict(clientRowId="a", tsCode="000002.SZ",
                            openedOn="2026-09-11", quantity=100, availableQuantity=100, costPrice="10.00")]))
                    assert response.status_code == 201, response.text
                    account = response.json()["result"]["account"]["accountId"]
                    response = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(**identity(),
                        tsCode="000002.SZ", tradeDate="2026-09-11", direction="SELL", price="12.00", quantity=40))
                    assert response.status_code == 201, response.text
                    trade = response.json()["result"]["tradeId"]
                    await wait_stage(client, account, "WAITING_DATA")
                    params = dict(accountMode="ALL", stockMode="ALL", requestedStartDate="2026-09-11", requestedEndDate="2026-09-11")
                    response = await client.get(ROOT + "/records/trades", params=params)
                    assert response.status_code == 200, response.text
                    row = response.json()["items"][0]
                    assert row["closedDataStatus"] == "Delayed" and row["closedReason"]
                    assert row["grossAmount"] == row["netCashChange"] == "480.00"
                    detail = await client.get(ROOT + f"/records/trades/{trade}", params={
                        "readContext":response.json()["readContext"]["contextToken"]})
                    assert detail.status_code == 200, detail.text
                    assert detail.json()["closedTrade"] is None
                    assert detail.json()["record"] == row
                    closed = await client.get(ROOT + "/records/closed-trades", params=params)
                    assert closed.status_code == 200, closed.text
                    assert closed.json()["items"] == []
                    assert closed.json()["summary"]["closedProfitAmount"] is None
                    assert closed.json()["summary"]["dataStatus"] == "Delayed"
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session", params={"user_id":2})).json()["token"]
                    denied = await client.get(ROOT + f"/records/trades/{trade}", params={
                        "readContext":response.json()["readContext"]["contextToken"]})
                    assert denied.status_code == 404, denied.text
        asyncio.run(run())
