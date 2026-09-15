"""Actual M3 publications back completed-round pagination and exact-range review."""
import asyncio
from time import monotonic
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from src.biz.queries.wealth.market.trading_assistant.completed_rounds import round_key
from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


@pytest.mark.parametrize("key", [None, [], ["2026-09-11", "bad", "000001.SZ", str(uuid4())],
    ["20260911", str(uuid4()), "000001.SZ", str(uuid4())],
    ["2026-09-11", str(uuid4()), "", str(uuid4())]])
def test_completed_key_rejects_noncanonical_values(key):
    with pytest.raises((ValueError, TypeError)):
        round_key(key)


def test_rounds_review_real_pagination_permissions_and_conservation(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    token = (await client.get("/test-session")).json()["token"]
                    client.headers["Authorization"] = "Bearer " + token
                    accounts = []
                    for name in ("甲", "乙"):
                        created = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                            name=name, brokerName="券商", commissionRateWan="3.00", minimumCommission="5.00",
                            stampTaxRatePct="0.05", initialCash="1000.00", initialPositions=[dict(clientRowId=code,
                                tsCode=code, openedOn="2026-09-10", quantity=1000, availableQuantity=1000, costPrice="10.00")
                                for code in ("000001.SZ", "000101.SZ")]))
                        assert created.status_code == 201, created.text
                        account = created.json()["result"]["account"]["accountId"]
                        accounts.append(account)
                        await wait_stage(client, account, "PUBLISHED")
                        for code in ("000001.SZ", "000101.SZ"):
                            # Two partial sales are two closed trades, one completed round.
                            for quantity in (400, 600):
                                saved = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(
                                    requestId=str(uuid4()), attemptId=str(uuid4()), direction="SELL", tsCode=code,
                                    tradeDate="2026-09-11", quantity=quantity, price="12.00"))
                                assert saved.status_code == 201, saved.text
                        await wait_stage(client, account, "PUBLISHED")
                    params = dict(accountMode="ALL", stockMode="ALL", requestedStartDate="2026-09-11", requestedEndDate="2026-09-11")
                    statements = []
                    def observe(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = app.state.trading_assistant.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        reviewed = await client.get(ROOT + "/returns/review", params=params)
                    finally:
                        event.remove(engine, "before_cursor_execute", observe)
                    elapsed = monotonic() - began
                    assert reviewed.status_code == 200, reviewed.text
                    review = reviewed.json()
                    assert review["requestedStartDate"] == review["requestedEndDate"] == "2026-09-11"
                    assert review["closedTrades"]["closedTradeCount"] == 8
                    assert review["completedRounds"]["completedRoundCount"] == 4
                    assert review["dailyStats"]["computedDayCount"] == 1
                    assert review["dailyStats"]["positiveDayCount"] == 1  # Accounts are not counted as separate days.
                    assert elapsed < 5
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    print(f"M5 review: SQL={len(statements)}, bytes={len(reviewed.content)}, seconds={elapsed:.5f}")
                    context = review["readContext"]["contextToken"]
                    url = ROOT + "/holding-rounds/completed"
                    paging = {**params, "readContext":context, "limit":1}
                    rows, cursor = [], None
                    while True:
                        response = await client.get(url, params={**paging, **({"cursor":cursor} if cursor else {})})
                        assert response.status_code == 200, response.text
                        body = response.json()
                        assert body["completedRoundCount"] == 4
                        rows.extend(body["items"])
                        cursor = body["nextCursor"]
                        if cursor is None:
                            break
                        assert len(rows) < 4
                        bad = await client.get(url, params={**paging, "cursor":cursor, "requestedStartDate":"2026-09-10"})
                        assert bad.status_code == 400
                    assert [(r["accountId"], r["stockRef"]["tsCode"]) for r in rows] == [
                        (account, code) for account in sorted(accounts) for code in ("000001.SZ", "000101.SZ")]
                    assert all(r["roundProfitAmount"] == "1984.00" and r["roundReturnPct"] == "19.84" for r in rows)
                    first = rows[0]
                    detail_url = ROOT + f"/accounts/{first['accountId']}/holding-rounds/{first['roundId']}"
                    detail = await client.get(detail_url, params={"readContext":context})
                    assert detail.status_code == 200, detail.text
                    assert detail.json()["detail"]["closedTradeCount"] == 2
                    assert len(detail.json()["readContext"]["accounts"]) == 1
                    closed = await client.get(ROOT + "/records/closed-trades", params={
                        "accountId":first["accountId"], "roundId":first["roundId"], "readContext":context})
                    assert closed.status_code == 200, closed.text
                    assert closed.json()["summary"]["closedProfitAmount"] == detail.json()["detail"]["roundProfitAmount"]
                    closed_rows = closed.json()["items"]
                    assert sorted(r["quantity"] for r in closed_rows) == [400, 600]
                    # The fixture fixes recordedAt too; ties use stable ledger ID,
                    # not request arrival order or the quantity entered.
                    assert [r["tradeId"] for r in closed_rows] == sorted(r["tradeId"] for r in closed_rows)
                    calendar = await client.get(ROOT + "/returns/calendar", params={"accountMode":"ALL", "month":"2026-09"})
                    assert calendar.status_code == 200, calendar.text
                    month_review = await client.get(ROOT + "/returns/review", params={**params, "requestedStartDate":"2026-09-01", "requestedEndDate":"2026-09-30"})
                    assert month_review.status_code == 200, month_review.text
                    for key in ("positiveDayCount", "negativeDayCount", "flatDayCount", "computedDayCount"):
                        assert month_review.json()["dailyStats"][key] == calendar.json()["monthSummary"][key]
                    for extra in ({"granularity":"MONTH"}, {"requestedEndDate":"2026-09-01"}, {"extra":"x"}):
                        assert (await client.get(ROOT + "/returns/review", params={**params, **extra})).status_code == 400
                    missing = await client.post(ROOT + f"/accounts/{first['accountId']}/trades", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), direction="BUY", tsCode="000002.SZ",
                        tradeDate="2026-09-11", quantity=100, price="1.00"))
                    assert missing.status_code == 201, missing.text
                    # M3 can publish the priced prefix (Sep 10), while Sep 11 is
                    # still unpriced. A PUBLISHED stage is not complete coverage.
                    await wait_stage(client, first["accountId"], "PUBLISHED")
                    unavailable = await client.get(detail_url)
                    assert unavailable.status_code == 200, unavailable.text
                    assert unavailable.json()["coverage"]["dataStatus"] == "Delayed"
                    assert unavailable.json()["detail"] is None and unavailable.json()["coverage"]["reason"]
                    assert (await client.get(detail_url, params={"readContext":context})).status_code == 409
                    partial = await client.get(url, params=params)
                    assert partial.status_code == 200, partial.text
                    assert partial.json()["coverage"]["dataStatus"] == "Partial"
                    assert partial.json()["completedRoundCount"] is None
                    assert len(partial.json()["items"]) == 2
                    assert all(row["accountId"] != first["accountId"] for row in partial.json()["items"])
                    other = (await client.get("/test-session", params={"user_id":2})).json()["token"]
                    client.headers["Authorization"] = "Bearer " + other
                    assert (await client.get(detail_url)).status_code == 404
                    assert (await client.get(url, params={**paging})).status_code in (404, 409)
                    own = await client.get(url, params=params)
                    assert own.status_code == 200 and own.json()["items"] == [] and own.json()["completedRoundCount"] == 0
        asyncio.run(run())
