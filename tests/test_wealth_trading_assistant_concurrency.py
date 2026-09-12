"""Two actual Python processes, each with four concurrent accounting requests."""
import asyncio
from datetime import date, datetime, timezone
import multiprocessing
from uuid import UUID, uuid4

from sqlalchemy import select, func, insert, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
from src.biz.models.wealth.trading_assistant.recovery import WriteAttempt
from src.biz.schemas.wealth.market.trading_assistant.accounts import CashFlowCommand, TradeCommand
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def concurrent_worker(url, items, barrier, results, worker_id):
    async def run():
        engine = create_async_engine(url, pool_size=4)
        services = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda: datetime(2026, 9, 11, 8, tzinfo=timezone.utc), executor_id=worker_id)
        async def one(item):
            account_id, payload = item
            try:
                trade = "tsCode" in payload
                state = await services.ledger.save(owner_id=1, account_id=UUID(account_id),
                    operation="TRADE_CREATE" if trade else "CASH_FLOW_CREATE",
                    command=(TradeCommand if trade else CashFlowCommand).model_validate(payload))
                return {"status": state.status, "receipt": state.receipt}
            except Exception as error:
                # No payloads, connection strings or secrets in cross-process errors.
                return {"error": type(error).__name__}
        try:
            return await asyncio.gather(*(one(item) for item in items))
        finally:
            await engine.dispose()
    try:
        barrier.wait(timeout=15)
        results.put(asyncio.run(run()))
    except Exception as error:
        results.put({"workerError": type(error).__name__})


def run_two_workers(database, items):
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    workers = [context.Process(target=concurrent_worker, args=(database.url.render_as_string(hide_password=False),
        items[index * 4:(index + 1) * 4], barrier, results, f"isolated-worker-{index}")) for index in range(2)]
    try:
        for worker in workers:
            worker.start()
        batches = [results.get(timeout=40) for _ in workers]
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        assert all(isinstance(batch, list) for batch in batches), batches
        return [row for batch in batches for row in batch]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        results.close()


def command():
    return dict(requestId=str(uuid4()), attemptId=str(uuid4()), direction="IN", occurredOn="2026-09-11", amount="123.45")


def test_two_process_same_request_eight_submissions_record_once(database):
    with database.begin() as connection:
        account, _, _ = seed_account(connection)
    payload = command()
    outcomes = run_two_workers(database, [(str(account), payload)] * 8)
    successful = [result["receipt"] for result in outcomes if result.get("status") == "SAVED"]
    assert successful, outcomes
    assert all(receipt == successful[0] for receipt in successful)
    with Session(database) as session:
        assert session.get(Account, account).fact_version == 2
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == 1
        attempt = session.get(WriteAttempt, (1, UUID(payload["requestId"]), UUID(payload["attemptId"])))
        assert attempt.status == "SAVED" and attempt.receipt == successful[0]
    assert all(result.get("status") in {"SAVED", "PROCESSING"} for result in outcomes), outcomes


def test_eight_distinct_accounts_progress_without_global_write_lock(database):
    with database.begin() as connection:
        accounts = [seed_account(connection)[0] for _ in range(8)]
    outcomes = run_two_workers(database, [(str(account), command()) for account in accounts])
    assert all(result.get("status") == "SAVED" for result in outcomes), outcomes
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id.in_(accounts))) == 8
        assert all(session.get(Account, account).fact_version == 2 for account in accounts)


def test_competing_cash_outs_cannot_spend_the_same_cash(database):
    with database.begin() as connection:
        account, initial, _ = seed_account(connection)
        connection.execute(update(Initialization).where(Initialization.initialization_id == initial).values(initial_cash="1000.00"))
    payloads = [{**command(), "direction": "OUT", "amount": "700.00"} for _ in range(8)]
    outcomes = run_two_workers(database, [(str(account), payload) for payload in payloads])
    assert sum(result.get("status") == "SAVED" for result in outcomes) == 1, outcomes
    with Session(database) as session:
        assert session.get(Account, account).fact_version == 2
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == 1


def test_competing_sales_cannot_sell_the_same_available_shares(database):
    from src.foundation.models.core_serving.security_serving import Security
    from src.foundation.models.core.trade_calendar import TradeCalendar
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    with database.begin() as connection:
        account, initial, _ = seed_account(connection)
        connection.execute(insert(InitialPosition).values(initialization_id=initial, account_id=account,
            ts_code="600002.SH", client_row_id="opening", quantity=600, available_quantity=600, cost_price="10.00"))
        connection.execute(pg_insert(Security).values(ts_code="600002.SH", name="并发测试股票", exchange="SSE",
            security_type="EQUITY", curr_type="CNY", source="test").on_conflict_do_nothing())
        connection.execute(pg_insert(TradeCalendar).values(exchange="SSE", trade_date=date(2026,9,11), is_open=True,
            pretrade_date=date(2026,9,10)).on_conflict_do_nothing())
    payloads = [dict(requestId=str(uuid4()), attemptId=str(uuid4()), direction="SELL", tsCode="600002.SH",
        tradeDate="2026-09-11", price="11.00", quantity=400) for _ in range(8)]
    outcomes = run_two_workers(database, [(str(account), payload) for payload in payloads])
    assert sum(result.get("status") == "SAVED" for result in outcomes) == 1, outcomes
    with Session(database) as session:
        assert session.get(Account, account).fact_version == 2
        assert session.scalar(select(func.sum(LedgerRevision.quantity)).where(LedgerRevision.account_id == account)) == 400
