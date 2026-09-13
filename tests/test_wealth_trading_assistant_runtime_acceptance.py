"""M3 real process interruption and automatic App restart on isolated PostgreSQL."""
import asyncio
import multiprocessing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import event, select, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from starlette.datastructures import State

from tests.test_wealth_trading_assistant_calculation_work import database, migrated, publication_db, interruptions_db, cutoff_db, DAY
from tests import test_wealth_trading_assistant_account_acceptance as acceptance
from src.app.runtime.trading_assistant_lifespan import trading_assistant_lifespan
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation, CalculationGeneration
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, CutoffPreparation, CutoffDiscoveryCursor
from src.biz.models.wealth.trading_assistant.publication import PublicationDay, AccountSnapshot
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar

OBSERVED = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


def fixed_clock(observed):
    def replace_clock(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT clock_timestamp()"):
            statement = statement.replace("clock_timestamp()", f"TIMESTAMPTZ '{observed.isoformat()}'")
        return statement, parameters
    return replace_clock


def interrupted_app(database_url, pipe):
    """Spawned child owns its engines; never inherits parent DB connections."""
    clock = fixed_clock(OBSERVED)
    event.listen(Engine, "before_cursor_execute", clock, retval=True)
    inserted = 0
    def stop_in_transaction(conn, cursor, statement, parameters, context, executemany):
        nonlocal inserted
        if statement.startswith("INSERT INTO app.wealth_ta_calculation_batch"):
            inserted += 1
            if inserted == 3:
                # Earlier units committed. This INSERT is deliberately still
                # uncommitted when the parent kills the whole process.
                pipe.send("UNCOMMITTED_CHECKPOINT")
                pipe.recv()
    event.listen(Engine, "after_cursor_execute", stop_in_transaction)
    async def run():
        app = SimpleNamespace(state=State())
        async with trading_assistant_lifespan(app, database_url=database_url, logger=Mock()):
            await asyncio.Event().wait()
    asyncio.run(run())


def test_kill_during_unit_then_restart_publishes_without_duplicate_facts(cutoff_db, monkeypatch):
    monkeypatch.setattr(acceptance, "NOW", OBSERVED)
    stock = "601099.SH"
    _, _, saved = acceptance.create(cutoff_db, acceptance.create_command([
        dict(clientRowId="one", tsCode=stock, openedOn=DAY.isoformat(),
            quantity=100, availableQuantity=100, costPrice="10.00")]))
    account_id = UUID(saved.receipt["result"]["account"]["accountId"])
    with cutoff_db.begin() as conn:
        EquityDailyBar.__table__.create(conn, checkfirst=True)
        conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=DAY, is_open=True,
            pretrade_date=DAY-timedelta(days=1)).on_conflict_do_nothing())
        conn.execute(insert(EquityDailyBar).values(ts_code=stock, trade_date=DAY,
            close=Decimal("11.00"), source="tushare"))

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=interrupted_app,
        args=(cutoff_db.url.render_as_string(hide_password=False), child))
    process.start()
    child.close()
    try:
        assert parent.poll(25), "Child did not reach the uncommitted unit"
        assert parent.recv() == "UNCOMMITTED_CHECKPOINT"
        with Session(cutoff_db) as session:
            before = session.scalars(select(CalculationBatch).where(CalculationBatch.account_id == account_id)).all()
            checkpoint_keys = {(r.generation_id, r.trade_date, r.stage, r.stock_key, r.page_key, r.input_digest) for r in before}
            assert checkpoint_keys
            assert session.get(Account, account_id).published_generation_id is None
        process.kill()
        process.join(5)
        assert process.exitcode is not None and process.exitcode != 0
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        parent.close()
        process.close()

    # Advance only the deterministic server-clock response past the real
    # persisted 15-second lease. No lease rows are edited by this test.
    clock = fixed_clock(OBSERVED+timedelta(seconds=20))
    event.listen(Engine, "before_cursor_execute", clock, retval=True)
    async def restart():
        app = SimpleNamespace(state=State())
        latencies = []
        async with trading_assistant_lifespan(app, database_url=cutoff_db.url, logger=Mock()):
            started = monotonic()
            while monotonic()-started < 25:
                begin = monotonic()
                result = await app.state.trading_assistant.read(
                    lambda s, d: app.state.trading_assistant.account_queries.list(s, owner_id=1, deadline=d))
                latencies.append(monotonic()-begin)
                assert len(result.items) >= 1
                with Session(cutoff_db) as session:
                    if session.get(Account, account_id).published_generation_id is not None:
                        break
                await asyncio.sleep(.02)
            else:
                pytest.fail("Restarted App did not publish the accepted account")
        assert len(latencies) >= 2
        assert max(latencies) < 5
        print(f"M3 isolated concurrent account reads: n={len(latencies)} "
              f"p95={sorted(latencies)[int((len(latencies)-1)*.95)]:.4f}s max={max(latencies):.4f}s")
    try:
        asyncio.run(restart())
    finally:
        event.remove(Engine, "before_cursor_execute", clock)
    with Session(cutoff_db) as session:
        account = session.get(Account, account_id)
        generation = session.get(CalculationGeneration, account.published_generation_id)
        assert generation.stage == "PUBLISHED"
        assert generation.through_date == DAY
        assert account.fact_version == account.calculation_target_version == 1
        assert session.get(Recalculation, account_id) is None
        assert session.scalar(select(func.count()).select_from(CalculationGeneration).where(
            CalculationGeneration.account_id == account_id)) == 1
        assert session.scalar(select(func.count()).select_from(Ledger).where(Ledger.account_id == account_id)) == 0
        after = session.scalars(select(CalculationBatch).where(CalculationBatch.account_id == account_id)).all()
        assert checkpoint_keys <= {(r.generation_id, r.trade_date, r.stage, r.stock_key, r.page_key, r.input_digest) for r in after}
        snapshot = session.scalar(select(AccountSnapshot).join(PublicationDay,
            PublicationDay.day_result_id == AccountSnapshot.day_result_id).where(
                PublicationDay.account_id == account_id, PublicationDay.generation_id == generation.generation_id))
        assert snapshot.stock_market_value == Decimal("1100.00")
        assert snapshot.day_profit_amount == Decimal("94.45")


@pytest.mark.parametrize("kind", ["CALCULATE", "HISTORY"])
def test_outer_connection_timeout_persists_retry_with_fresh_connection(cutoff_db, monkeypatch, kind):
    from src.app.runtime.trading_assistant_execution_resource import TradingAssistantExecutionResource
    from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
    from src.biz.services.wealth.market.trading_assistant.cutoff_preparation import AccountCutoffPreparation
    from src.biz.services.wealth.market.trading_assistant.history_source_preparation import HistorySourcePreparation
    policy = replace(TradingAssistantExecutionPolicyV1(), batch_budget_ms=500, sql_timeout_ms=200)
    observed = OBSERVED+timedelta(minutes=2)
    monkeypatch.setattr(acceptance, "NOW", observed)
    if kind == "CALCULATE":
        _, _, saved = acceptance.create(cutoff_db)
        identity = UUID(saved.receipt["result"]["account"]["accountId"])
        owner, method = AccountCutoffPreparation, "resolve"
    else:
        _, _, saved = acceptance.create(cutoff_db)
        identity = UUID(saved.receipt["result"]["account"]["accountId"])
        from sqlalchemy.orm import sessionmaker
        from src.biz.services.wealth.market.trading_assistant.calculation_work import CalculationWork
        from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution
        with cutoff_db.begin() as conn:
            conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=DAY, is_open=True,
                pretrade_date=DAY-timedelta(days=1)).on_conflict_do_nothing())
        seed_clock = fixed_clock(observed)
        event.listen(Engine, "before_cursor_execute", seed_clock, retval=True)
        try:
            worker = CalculationWork(RecalculationExecution(TradingAssistantExecutionPolicyV1()),
                sessionmaker(cutoff_db), rule_version=1, resolve_through_date=lambda *a, **k: DAY)
            for _ in range(100):
                worker.run_once(executor_id="test-history-seed")
                with Session(cutoff_db) as session:
                    if session.get(Account, identity).published_generation_id is not None:
                        break
            else:
                pytest.fail("History seed did not publish")
        finally:
            event.remove(Engine, "before_cursor_execute", seed_clock)
        with Session(cutoff_db) as session, session.begin():
            cursor = session.get(CutoffDiscoveryCursor, 2)
            cursor.after_account_id, cursor.next_attempt_at = None, observed
        owner, method = HistorySourcePreparation, "step"
    attempted = []
    def stalled(self, session, **kwargs):
        attempted.append(kwargs["account_id"])
        # Disable only this test transaction's SQL timeout, so cancellation is
        # demonstrably the outer connection deadline, not statement_timeout.
        session.execute(text("SET LOCAL statement_timeout = 0"))
        session.execute(text("SELECT pg_sleep(5)"))
    monkeypatch.setattr(owner, method, stalled)
    clock = fixed_clock(observed)
    event.listen(Engine, "before_cursor_execute", clock, retval=True)
    async def run():
        resource = TradingAssistantExecutionResource(cutoff_db.url, policy, rule_version=1)
        try:
            assert await resource.run_one(kind) == "TRANSIENT"
        finally:
            await resource.close()
    try:
        asyncio.run(run())
    finally:
        event.remove(Engine, "before_cursor_execute", clock)
    with Session(cutoff_db) as session:
        assert len(attempted) == 1
        identity = attempted[0]
        row = session.get(Recalculation, identity) if kind == "CALCULATE" else session.get(
            CutoffPreparation, (identity, 1, "HISTORY"))
        assert row.transient_failure_count == 1
        assert row.next_attempt_at == observed+timedelta(seconds=2)
        assert session.get(Account, identity).fact_version == 1
