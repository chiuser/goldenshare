"""M4.1: real JWT commands, runtime calculations and publication in fresh PG."""
import asyncio
from decimal import Decimal
from time import monotonic
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from src.biz.models.wealth.trading_assistant.calculation import ClosedTrade
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from tests.wealth_trading_assistant_browser_fixture import NOW
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres

ROOT = "/api/v1/wealth/market/trading-assistant"


async def wait_stage(client, account, expected):
    until = monotonic() + 25
    last = None
    while monotonic() < until:
        response = await client.get(f"{ROOT}/accounts/{account}/calculation-status")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["stage"] == expected:
            return last
        await asyncio.sleep(.05)
    raise AssertionError(f"M3 publication timed out: {last}")


def test_fixture_publishes_actual_holdings_cash_and_missing_price(tmp_path, monkeypatch):
    from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions
    failures = []
    original_run = TradingAssistantTransactions.run
    async def observed_run(self, *args, **kwargs):
        try:
            return await original_run(self, *args, **kwargs)
        except Exception as error:
            failures.append(repr(error))
            raise
    monkeypatch.setattr(TradingAssistantTransactions, "run", observed_run)
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    token = (await client.get("/test-session")).json()["token"]
                    client.headers["Authorization"] = "Bearer " + token
                    identities = []
                    for code in ("000001.SZ", None, "000002.SZ"):
                        command = dict(requestId=str(uuid4()), attemptId=str(uuid4()), name=code or "现金",
                            brokerName="测试券商", initialCash="1000.00", commissionRateWan="3.00",
                            minimumCommission="5.00", stampTaxRatePct="0.05", initialPositions=[])
                        if code:
                            command["initialPositions"] = [dict(clientRowId="one", tsCode=code,
                                openedOn="2026-09-10", quantity=1000, availableQuantity=1000, costPrice="10.00")]
                        response = await client.post(ROOT + "/accounts", json=command)
                        assert response.status_code == 201, response.text
                        account = response.json()["result"]["account"]["accountId"]
                        identities.append(account)
                        await wait_stage(client, account, "WAITING_DATA" if code == "000002.SZ" else "PUBLISHED")
                    context = await client.get("/test-read-context", params={"accountMode":"ALL"})
                    assert context.status_code == 200, context.text
                    accounts = context.json()["accounts"]
                    assert [a["accountId"] for a in accounts] == sorted(identities)
                    assert next(a for a in accounts if a["accountId"] == identities[2])["publishedGenerationId"] is None
                    normal = next(a for a in accounts if a["accountId"] == identities[0])
                    assert normal["publishedGenerationId"] is not None
                    old_token = context.json()["contextToken"]
                    sold = await client.post(f"{ROOT}/accounts/{identities[0]}/trades", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), tsCode="000001.SZ", direction="SELL",
                        tradeDate="2026-09-11", price="12.00", quantity=400))
                    assert sold.status_code == 201, sold.text
                    for direction, amount in (("IN", "500.00"), ("OUT", "100.00")):
                        response = await client.post(f"{ROOT}/accounts/{identities[0]}/cash-flows", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), direction=direction,
                            occurredOn="2026-09-11", amount=amount))
                        assert response.status_code == 201, response.text
                    await wait_stage(client, identities[0], "PUBLISHED")
                    stale = await client.get("/test-read-context", params={"accountMode":"ALL", "readContext":old_token})
                    assert stale.status_code == 409, stale.text
                    assert "TA_READ_CONTEXT_CHANGED" in stale.text
                    context = await client.get("/test-read-context", params={"accountMode":"ALL"})
                    normal = next(a for a in context.json()["accounts"] if a["accountId"] == identities[0])
                    with Session(database) as session:
                        snapshot = session.scalars(select(AccountSnapshot).join(PublicationDay,
                            (PublicationDay.account_id == AccountSnapshot.account_id) &
                            (PublicationDay.day_result_id == AccountSnapshot.day_result_id)).where(
                            PublicationDay.account_id == UUID(identities[0]),
                            PublicationDay.generation_id == UUID(normal["publishedGenerationId"])
                            ).order_by(AccountSnapshot.trade_date.desc())).first()
                        assert snapshot.cash_amount == Decimal("6192.60")
                        assert snapshot.stock_market_value == Decimal("7200")
                        assert snapshot.holding_profit_amount == Decimal("1984.00")
                        closed = session.scalars(select(ClosedTrade).where(
                            ClosedTrade.account_id == UUID(identities[0]),
                            ClosedTrade.day_result_id == snapshot.day_result_id)).one()
                        assert closed.quantity == 400
                        assert closed.allocated_cost == Decimal("4000")
                        assert closed.net_proceeds == Decimal("4792.60")
                        assert closed.profit_amount == Decimal("792.60")
                        assert closed.return_pct == Decimal("19.82")
                    other = (await client.get("/test-session", params={"user_id":2})).json()["token"]
                    forbidden = await client.get("/test-read-context", params={"accountMode":"SINGLE",
                        "accountId":identities[0], "readContext":context.json()["contextToken"]},
                        headers={"Authorization":"Bearer " + other})
                    assert forbidden.status_code == 404, forbidden.text
                    # Regression of the browser's published cash-account correction.
                    target = identities[1]
                    bought = await client.post(f"{ROOT}/accounts/{target}/trades", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), tsCode="000001.SZ", direction="BUY",
                        tradeDate="2026-09-11", price="11.00", quantity=13))
                    assert bought.status_code == 201, bought.text
                    await wait_stage(client, target, "PUBLISHED")
                    revised = await client.post(f"{ROOT}/accounts/{target}/initialization/corrections", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), expectedRevision="1",
                        initialCash="1100.00", initialPositions=[]))
                    assert revised.status_code == 200, (revised.text, failures)
                    await wait_stage(client, target, "PUBLISHED")
                    # The established 100ms lock budget may reject a concurrent
                    # save. Prove STOPPED + retained input, not silent success.
                    blocked = dict(requestId=str(uuid4()), attemptId=str(uuid4()), expectedRevision="2",
                        initialCash="1200.00", initialPositions=[])
                    from src.biz.services.wealth.market.trading_assistant.initialization_acceptance import InitializationAcceptance
                    original_accept = InitializationAcceptance.accept
                    def locked_accept(acceptance, *args, **kwargs):
                        with database.begin() as locker:
                            locker.execute(text("SELECT account_id FROM app.wealth_ta_account "
                                "WHERE account_id=:id FOR UPDATE"), {"id":UUID(target)})
                            return original_accept(acceptance, *args, **kwargs)
                    with monkeypatch.context() as contention:
                        contention.setattr(InitializationAcceptance, "accept", locked_accept)
                        rejected = await client.post(f"{ROOT}/accounts/{target}/initialization/corrections", json=blocked)
                        assert rejected.status_code == 500, rejected.text
                    recovered = await client.get(f"{ROOT}/write-requests/{blocked['requestId']}")
                    assert recovered.json()["outcome"] == "NOT_SAVED", recovered.text
                    retained = await client.get(f"{ROOT}/write-requests/{blocked['requestId']}/input")
                    assert retained.status_code == 200 and "1200.00" in retained.text, retained.text
                    unchanged = await client.get(f"{ROOT}/accounts/{target}/initialization")
                    assert "1100.00" in unchanged.text and "1200.00" not in unchanged.text
                    assert any("LockNotAvailable" in failure for failure in failures), failures
            assert not hasattr(app.state, "trading_assistant")
            assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("ta-")]
            # No coordinator runs during these GETs. Observe row counts and account
            # versions before/after; reads cannot accidentally enqueue more work.
            def state():
                with database.connect() as conn:
                    tables = conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='app' "
                        "AND tablename LIKE 'wealth_ta_%' ORDER BY tablename")).all()
                    counts = [(name, conn.scalar(text(f'SELECT count(*) FROM app."{name}"'))) for name in tables]
                    versions = conn.execute(text("SELECT account_id, fact_version, calculation_target_version, "
                        "published_generation_id FROM app.wealth_ta_account ORDER BY account_id")).all()
                    return counts, versions
            before = state()
            engine = create_async_engine(database.url)
            app.state.trading_assistant = build_trading_assistant_dependencies(engine,
                policy=TradingAssistantExecutionPolicyV1(), now=lambda:NOW, executor_id="m41-read-only")
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated",
                        headers={"Authorization":"Bearer " + token}) as reader:
                    for _ in range(3):
                        assert (await reader.get("/test-read-context", params={"accountMode":"ALL"})).status_code == 200
                        assert (await reader.get(f"{ROOT}/accounts/{identities[0]}/calculation-status")).status_code == 200
                        assert (await reader.get(f"/test-publication/{identities[0]}")).status_code == 200
                assert state() == before
            finally:
                del app.state.trading_assistant
                await engine.dispose()
            # Same database can restart the real runtime without duplicated loops.
            async with app.router.lifespan_context(app):
                assert len([t for t in asyncio.all_tasks() if t.get_name() == "ta-calculation-coordinator"]) == 1
            assert not hasattr(app.state, "trading_assistant")
        asyncio.run(run())
