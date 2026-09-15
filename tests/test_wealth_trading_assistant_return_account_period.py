"""Whole-period cash reuse against real owned commands and published snapshots."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from time import monotonic
from uuid import UUID, uuid4
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from src.biz.queries.wealth.market.trading_assistant.return_account_period import AccountPeriodReturnsQuery
from src.biz.queries.wealth.market.trading_assistant.return_stock_period import StockPeriodReturnsQuery
from src.biz.queries.wealth.market.trading_assistant.return_periods import PeriodReturnsQuery
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


@pytest.mark.parametrize("reader_type", [AccountPeriodReturnsQuery, PeriodReturnsQuery])
@pytest.mark.parametrize("start,end,today", [
    (date(2026, 9, 8), date(2026, 9, 7), date(2026, 9, 11)),
    ("2026-09-07", date(2026, 9, 8), date(2026, 9, 11)),
    (date(2026, 9, 7), date(2026, 9, 8), datetime(2026, 9, 11)),
])
def test_period_ranges_reject_invalid_dates_before_database(reader_type, start, end, today):
    reader = reader_type(SimpleNamespace(page_rows=1))
    args = dict(owner_id=1, basis=None, start=start, end=end, today=today, deadline=None)
    if reader_type is AccountPeriodReturnsQuery:
        args["account_id"] = uuid4()
    with pytest.raises(ValueError, match="range"):
        reader.read(None, **args)


def test_real_whole_period_reuses_cash_and_keeps_initialization_history(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)
        app.state.fixture_clock[0] = datetime(2026, 9, 7, 8, tzinfo=timezone.utc)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    client.headers["Authorization"] = "Bearer " + (await client.get("/test-session")).json()["token"]
                    async def create(name, positions, cash="10000.00"):
                        saved = await client.post(ROOT + "/accounts", json=dict(requestId=str(uuid4()), attemptId=str(uuid4()),
                            name=name, brokerName="券商", commissionRateWan="0.00", minimumCommission="0.00",
                            stampTaxRatePct="0.00", initialCash=cash, initialPositions=[dict(clientRowId=str(i),
                                tsCode=code, openedOn=opened, quantity=1000, availableQuantity=1000, costPrice="10.00")
                                for i, (code, opened) in enumerate(positions)]))
                        assert saved.status_code == 201, saved.text
                        return UUID(saved.json()["result"]["account"]["accountId"])

                    account = await create("复用回款", [("000001.SZ", "2026-09-07")])
                    withdrawn = await create("全部转出", [("000001.SZ", "2026-09-07")])
                    cash_only = await create("只有现金", [])
                    for target in (account, withdrawn, cash_only):
                        await wait_stage(client, str(target), "PUBLISHED")
                    app.state.fixture_clock[0] = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)
                    async def trade(account, direction, day, price):
                        saved = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), direction=direction, tsCode="000001.SZ",
                            tradeDate=day, quantity=1000, price=price))
                        assert saved.status_code == 201, saved.text

                    async def cash(account, direction, day, amount):
                        saved = await client.post(ROOT + f"/accounts/{account}/cash-flows", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), direction=direction, occurredOn=day, amount=amount))
                        assert saved.status_code == 201, saved.text

                    for target, amount in ((account, "10000.00"), (withdrawn, "21000.00")):
                        await trade(target, "SELL", "2026-09-08", "11.00")
                        await cash(target, "OUT", "2026-09-09", amount)
                        if target == withdrawn:
                            await cash(target, "IN", "2026-09-10", "20000.00")
                        await trade(target, "BUY", "2026-09-10", "11.00")
                        await trade(target, "SELL", "2026-09-11", "12.00")
                        await wait_stage(client, str(target), "PUBLISHED")
                    deps = app.state.trading_assistant

                    async def read(target=account, start=date(2026, 9, 7), end=date(2026, 9, 11), *,
                                   page_rows=1, owner=1, token=None, stock=None):
                        policy = replace(deps.policy, page_rows=page_rows)
                        reader = StockPeriodReturnsQuery(policy) if stock else AccountPeriodReturnsQuery(policy)
                        def query(session, deadline, basis):
                            args = dict(owner_id=owner, basis=basis, account_id=target, start=start, end=end,
                                today=app.state.fixture_clock[0].date(), deadline=deadline)
                            value = reader.read(session, **args, **({"stock":stock} if stock else {}))
                            return value, basis.context.contextToken
                        return await deps.read_current(query, owner_id=owner, account_mode="SINGLE", account_id=target,
                            context_token=token, resolve_target_through=lambda s,d:app.state.fixture_clock[0])

                    statements = []
                    def observe(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = deps.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        whole, token = await read()
                    finally:
                        elapsed = monotonic() - began
                        event.remove(engine, "before_cursor_execute", observe)
                    assert (whole.result.profit_cents, whole.result.capital_cents, whole.result.return_pct) == (200000, 1000000, "20.00")
                    assert whole.closing_cash_cents == 1200000
                    assert whole.coverage.dataStatus == "Ready"
                    assert whole == (await read(page_rows=3))[0]
                    single = (await read(stock="000001.SZ"))[0]
                    assert (single.result.profit_cents, single.result.capital_cents, single.result.return_pct) == (200000, 2100000, "9.52")
                    other = (await read(withdrawn))[0]
                    assert (other.result.profit_cents, other.result.capital_cents, other.result.return_pct) == (200000, 2100000, "9.52")
                    assert other.closing_cash_cents == 2100000
                    async def all_accounts():
                        def query(session, deadline, basis):
                            return PeriodReturnsQuery(deps.policy).read(session, owner_id=1, basis=basis,
                                start=date(2026, 9, 7), end=date(2026, 9, 11), today=date(2026, 9, 11), deadline=deadline)
                        return await deps.read_current(query, owner_id=1, account_mode="ALL", account_id=None,
                            resolve_target_through=lambda s,d:app.state.fixture_clock[0])
                    combined = await all_accounts()
                    assert (combined.result.profit_cents, combined.result.capital_cents, combined.result.return_pct) == (400000, 3100000, "12.90")
                    assert len(combined.coverage.accounts) == 3 and combined.coverage.dataStatus == "Ready"
                    only_later = (await read(start=date(2026, 9, 10)))[0]
                    assert (only_later.result.profit_cents, only_later.result.capital_cents, only_later.result.return_pct) == (100000, 1100000, "9.09")
                    one_day = (await read(start=date(2026, 9, 11)))[0]
                    assert one_day.result.profit_cents == 0 and one_day.result.capital_cents == 1100000
                    detail = await client.get(ROOT + "/returns/days/2026-09-11", params=dict(accountMode="SINGLE", accountId=str(account)))
                    assert detail.status_code == 200, detail.text
                    assert (detail.json()["profitAmount"], detail.json()["capitalAmount"], detail.json()["returnPct"]) == ("0.00", "11000.00", "0.00")
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    assert elapsed < 5
                    print(f"M5 whole range: civil_pages=5, SQL={len(statements)}, seconds={elapsed:.5f}")
                    with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
                        await read(owner=2)
                    await cash(account, "IN", "2026-09-11", "500.00")
                    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
                        await read(token=token)
                    await wait_stage(client, str(account), "PUBLISHED")
                    after_cash = (await read())[0]
                    assert after_cash.result == whole.result and after_cash.closing_cash_cents == 1250000
                    await wait_stage(client, str(cash_only), "PUBLISHED")
                    pure = (await read(cash_only))[0]
                    assert pure.result.status == pure.coverage.dataStatus == "Empty" and pure.closing_cash_cents == 1000000
                    # Initial holdings have earlier dates; registered cash is not backfilled.
                    earlier = await create("历史持仓", [("000001.SZ", "2026-09-07"), ("000101.SZ", "2026-09-10")], "1200.00")
                    await wait_stage(client, str(earlier), "PUBLISHED")
                    history = (await read(earlier, end=date(2026, 9, 10)))[0]
                    assert history.closing_cash_cents is None
                    assert (history.result.profit_cents, history.result.capital_cents, history.result.return_pct) == (300000, 2000000, "15.00")
                    await cash(earlier, "IN", "2026-09-11", "250.00")
                    await wait_stage(client, str(earlier), "PUBLISHED")
                    current = (await read(earlier))[0]
                    assert current.result == history.result and current.closing_cash_cents == 145000
                    missing = await create("缺价", [("000002.SZ", "2026-09-07")])
                    await wait_stage(client, str(missing), "WAITING_DATA")
                    delayed = (await read(missing))[0]
                    assert delayed.result.status == delayed.coverage.dataStatus == "Delayed"
                    assert delayed.result.profit_cents is None and delayed.coverage.accounts[0].calculatedThroughDate is None
                    partial = await all_accounts()
                    assert partial.coverage.dataStatus == "Partial" and partial.result.status == "Delayed"
                    app.state.fixture_clock[0] = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
                    await cash(account, "OUT", "2026-09-12", "500.00")
                    await cash(account, "IN", "2026-09-13", "100.00")
                    weekend = (await read(start=date(2026, 9, 12), end=date(2026, 9, 13)))[0]
                    assert weekend.result.status == "Empty" and weekend.closing_cash_cents == 1210000
        asyncio.run(run())
