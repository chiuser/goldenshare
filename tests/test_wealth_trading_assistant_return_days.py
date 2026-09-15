"""M5 internal reading: real JWT writes and M3 publication in a new local PG."""
import asyncio
from dataclasses import replace
from datetime import date
from time import monotonic
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import event

from src.biz.queries.wealth.market.trading_assistant.return_days import PublishedReturnDaysQuery, PublishedReturnsUnavailable
from src.biz.queries.wealth.market.trading_assistant.return_statistics import summarize_daily_returns
from src.biz.schemas.wealth.market.trading_assistant.common import Coverage
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import NOW, browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_fixed_published_days_page_real_results_and_preserve_unknown_cash(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    ids = []
                    for code in ("000001.SZ", "000002.SZ", None):
                        response = await client.post(ROOT + "/accounts", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), name=code or "现金", brokerName="券商",
                            initialCash="1000.00", commissionRateWan="3.00", minimumCommission="5.00",
                            stampTaxRatePct="0.05", initialPositions=[] if code is None else [dict(
                                clientRowId="one", tsCode=code, openedOn="2026-09-10", quantity=1000,
                                availableQuantity=1000, costPrice="10.00")]))
                        assert response.status_code == 201, response.text
                        ids.append(UUID(response.json()["result"]["account"]["accountId"]))
                        await wait_stage(client, str(ids[-1]), "WAITING_DATA" if code == "000002.SZ" else "PUBLISHED")
                    deps = app.state.trading_assistant
                    reader = PublishedReturnDaysQuery(replace(deps.policy, page_rows=1))
                    start, end = date(2026, 9, 1), date(2026, 9, 11)

                    async def read(account, owner=1, token=None, query_account=None):
                        def query(session, deadline, basis):
                            items, cursor, pages = [], None, 0
                            while True:
                                page = reader.page(session, basis=basis, account_id=query_account or account,
                                    start=start, end=end, deadline=deadline, after=cursor)
                                pages += 1
                                items.extend(page.items)
                                cursor = page.next_date
                                if cursor is None:
                                    return tuple(items), pages, basis.context.contextToken
                        return await deps.read_current(query, owner_id=owner, account_mode="SINGLE",
                            account_id=account, context_token=token, resolve_target_through=lambda s,d:NOW)

                    before, pages, token = await read(ids[0])
                    assert pages == 2 and [row.fact.day for row in before] == [date(2026, 9, 10), end]
                    assert before[0].cash_cents is None and before[1].cash_cents == 100000
                    assert [row.fact.result.profit_cents for row in before] == [198900, 0]
                    response = await client.post(ROOT + f"/accounts/{ids[0]}/trades", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), direction="SELL", tsCode="000001.SZ",
                        tradeDate="2026-09-11", quantity=400, price="12.00"))
                    assert response.status_code == 201, response.text
                    await wait_stage(client, str(ids[0]), "PUBLISHED")
                    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
                        await read(ids[0], token=token)
                    statements = []
                    def observe(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = deps.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        after, pages, _ = await read(ids[0])
                    finally:
                        elapsed = monotonic() - began
                        event.remove(engine, "before_cursor_execute", observe)
                    assert pages == 2 and len({row.day_result_id for row in after}) == 2
                    assert after[1].cash_cents == 579260
                    assert after[1].closed_count == 1 and after[1].closed_profit_cents == 79260
                    assert [row.fact.result.profit_cents for row in after] == [198900, -500]
                    summary = summarize_daily_returns((row.fact for row in after), start=start, end=end,
                        coverage=Coverage(dataStatus="Ready", reason=None, isFinal=True, accounts=[]))
                    assert (summary.positiveDayCount, summary.negativeDayCount, summary.computedDayCount) == (1, 1, 2)
                    assert summary.minDailyReturn.returnPct == "-0.05"
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    assert elapsed < deps.policy.read_request_budget_ms / 1000
                    print(f"M5 published days: pages={pages}, SQL={len(statements)}, elapsed={elapsed:.5f}s")
                    with pytest.raises(PublishedReturnsUnavailable):
                        await read(ids[1])
                    cash, _, _ = await read(ids[2])
                    assert len(cash) == 1 and cash[0].fact.result.status == "Empty"
                    assert cash[0].cash_cents == 100000
                    with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
                        await read(ids[0], owner=2)
                    with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
                        await read(ids[0], query_account=ids[2])
        asyncio.run(run())
