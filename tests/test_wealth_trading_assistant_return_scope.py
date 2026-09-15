"""Real effective facts and M3 results drive the new return-scope coverage."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import event

from src.biz.queries.wealth.market.trading_assistant.return_coverage import ReturnDayEvidence, cover_return_days
from src.biz.queries.wealth.market.trading_assistant.return_days import PublishedReturnDaysQuery
from src.biz.queries.wealth.market.trading_assistant.return_scope import ReturnScopeQuery
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_history_participation_and_coverage_use_actual_owned_revisions(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)
        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    response = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                        name="真实日期", brokerName="券商", commissionRateWan="0.00", minimumCommission="0.00",
                        stampTaxRatePct="0.00", initialCash="1000.00", initialPositions=[dict(clientRowId="one",
                            tsCode="000001.SZ", openedOn="2026-09-10", quantity=100, availableQuantity=100, costPrice="10.00")]))
                    assert response.status_code == 201, response.text
                    account = UUID(response.json()["result"]["account"]["accountId"])
                    await wait_stage(client, str(account), "PUBLISHED")
                    deps = app.state.trading_assistant

                    async def read(stock=None, through=date(2026, 9, 11), owner=1, page_rows=1):
                        policy = replace(deps.policy, page_rows=page_rows)
                        scopes, returns, market = ReturnScopeQuery(policy), PublishedReturnDaysQuery(policy), MarketFactsReader(policy)
                        def query(session, deadline, basis):
                            scope = scopes.read(session, owner_id=owner, basis=basis, account_id=account,
                                                deadline=deadline, stock=stock)
                            all_days = []
                            for offset in range(0, (through - date(2026, 9, 9)).days + 1, page_rows):
                                begin = date(2026, 9, 9) + timedelta(days=offset)
                                end = min(through, begin + timedelta(days=page_rows - 1))
                                all_days.extend(scopes.participation(session, scope=scope, start=begin, end=end, deadline=deadline))
                            if stock is not None:
                                return scope, all_days, None
                            published, cursor = {}, None
                            while True:
                                page = returns.page(session, basis=basis, account_id=account, start=date(2026, 9, 9),
                                                    end=through, after=cursor, deadline=deadline)
                                published.update((item.fact.day, item) for item in page.items)
                                cursor = page.next_date
                                if cursor is None:
                                    break
                            evidence = []
                            for participation in all_days:
                                if participation.day < scope.history_start:
                                    continue
                                calendar = market.read_calendar(session, "SSE", participation.day, participation.day, deadline).days[0]
                                evidence.append(ReturnDayEvidence(participation, calendar.is_open, published.get(participation.day)))
                            covered = cover_return_days(scope, start=date(2026, 9, 9), end=through,
                                today=app.state.fixture_clock[0].date(), evidence=tuple(evidence))
                            return scope, all_days, covered
                        return await deps.read_current(query, owner_id=owner, account_mode="SINGLE", account_id=account,
                            resolve_target_through=lambda s,d:app.state.fixture_clock[0])

                    scope, days, covered = await read()
                    assert scope.history_start == date(2026, 9, 10) < scope.initialized_on
                    assert [d.participates for d in days] == [False, True, True]
                    assert [d.trade_count for d in days] == [0, 0, 0]
                    assert covered.coverage.dataStatus == "Ready"
                    assert [d.result.profit_cents for d in covered.days] == [20000, 0]
                    unknown, unknown_days, _ = await read("000002.SZ")
                    assert unknown.history_start is None and not any(d.participates for d in unknown_days)
                    known, known_days, _ = await read("000001.SZ")
                    assert known.history_start == scope.history_start and known_days == days
                    with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
                        await read(owner=2)
                    sold = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(requestId=str(uuid4()),
                        attemptId=str(uuid4()), direction="SELL", tsCode="000001.SZ", tradeDate="2026-09-11",
                        quantity=100, price="13.00"))
                    assert sold.status_code == 201, sold.text
                    incoming = await client.post(ROOT + f"/accounts/{account}/cash-flows", json=dict(requestId=str(uuid4()),
                        attemptId=str(uuid4()), direction="IN", occurredOn="2026-09-11", amount="500.00"))
                    assert incoming.status_code == 201, incoming.text
                    await wait_stage(client, str(account), "PUBLISHED")
                    app.state.fixture_clock[0] = datetime(2026, 9, 14, 2, tzinfo=timezone.utc)
                    statements = []
                    def observe(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = deps.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        _, days, covered = await read(through=date(2026, 9, 14))
                    finally:
                        elapsed = monotonic() - began
                        event.remove(engine, "before_cursor_execute", observe)
                    assert [d.participates for d in days] == [False, True, True, False, False, False]
                    assert days[2].opening_quantity == 100 and days[2].closing_quantity == 0 and days[2].trade_count == 1
                    assert covered.coverage.dataStatus == "Ready"
                    assert [d.result.profit_cents for d in covered.days] == [20000, 10000, None, None, None]
                    assert covered.coverage.accounts[0].calculatedThroughDate == "2026-09-11"
                    _, larger_days, larger_coverage = await read(through=date(2026, 9, 14), page_rows=3)
                    assert larger_days == days and larger_coverage == covered
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    assert elapsed < deps.policy.read_request_budget_ms / 1000
                    print(f"M5 participation and coverage: civil_pages=6, SQL={len(statements)}, elapsed={elapsed:.5f}s")
        asyncio.run(run())
