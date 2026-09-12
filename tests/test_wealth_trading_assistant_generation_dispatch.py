"""Automatic unit selection across fresh Sessions; isolated PostgreSQL only."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY, AT
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_calculation_interruptions import interruptions_db
from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationDataUnavailable
from src.biz.services.wealth.market.trading_assistant.generation_dispatch import DayInputBasis
from src.biz.services.wealth.market.trading_assistant.generation_execution import GenerationExecution
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@pytest.mark.parametrize("held", [False, True])
def test_dispatch_resumes_entire_window_without_manual_stage_selection(interruptions_db, held):
    inputs, lease, generation, fee = setup(interruptions_db)
    # Force valuation paging, while leaving the policy's existing time budget.
    inputs.execution.policy = replace(inputs.execution.policy, page_rows=1)
    monday = DAY + timedelta(days=3)
    with interruptions_db.begin() as conn:
        EquityDailyBar.__table__.create(conn, checkfirst=True)
    with Session(interruptions_db) as session, session.begin():
        session.get(CalculationGeneration, generation).through_date = monday
        account = session.get(Account, lease.account_id)
        if held:
            for code in ("601001.SH", "601002.SH"):
                session.add(InitialPosition(account_id=lease.account_id,
                    initialization_id=account.current_initialization_id, ts_code=code,
                    client_row_id=code, opened_on=DAY, quantity=100,
                    available_quantity=100, cost_price="10.00"))
                for day, price in ((DAY, "11.00"), (monday, "12.00")):
                    session.add(EquityDailyBar(ts_code=code, trade_date=day,
                        close=Decimal(price), source="tushare"))
        for offset in range(4):
            day = DAY + timedelta(days=offset)
            if session.get(TradeCalendar, ("SSE", day)) is None:
                session.add(TradeCalendar(exchange="SSE", trade_date=day,
                    is_open=offset in (0, 3), pretrade_date=DAY-timedelta(days=1) if not offset else DAY))

    selected = []
    def resolve(session, *, account_id, business_date, deadline):
        assert account_id == lease.account_id
        # Re-resolving a frozen date would change the cutoff and fail the run.
        assert business_date not in selected
        selected.append(business_date)
        return DayInputBasis(fee, AT + (business_date-DAY))

    stages = []
    for _ in range(240):
        with Session(interruptions_db) as session:
            before = session.scalar(select(func.count()).select_from(CalculationBatch).where(
                CalculationBatch.generation_id == generation))
        # No shared Session, runner, ORM object, or in-memory stage between units.
        stage = GenerationExecution(inputs.execution, sessionmaker(interruptions_db)).step(
            lease, generation_id=generation, resolve_day_inputs=resolve)
        stages.append(stage)
        assert stage not in ("FAILED", "WAITING_DATA", "TRANSIENT")
        with Session(interruptions_db) as session, session.begin():
            after = session.scalar(select(func.count()).select_from(CalculationBatch).where(
                CalculationBatch.generation_id == generation))
            assert 0 <= after-before <= 1
            account = session.get(Account, lease.account_id)
            if stage == "PUBLISHED":
                assert account.published_generation_id == generation
                assert session.get(Recalculation, lease.account_id) is None
                break
            assert account.published_generation_id is None
            lease = inputs.execution.claim(session, executor_id="new-instance", deadline=deadline())
            assert lease is not None
    else:
        pytest.fail("Automatic unit selection failed to finish")
    assert selected == [DAY+timedelta(days=i) for i in range(4)]
    assert stages.count("DATE_COMPLETE") == 4
    assert stages.count("VALUATION") == (4 if held else 0)
    with Session(interruptions_db) as session:
        snapshots = session.scalars(select(AccountSnapshot).join(PublicationDay,
            PublicationDay.day_result_id == AccountSnapshot.day_result_id).where(
                PublicationDay.generation_id == generation).order_by(PublicationDay.trade_date)).all()
        assert len(snapshots) == 2
        assert [row.stock_market_value for row in snapshots] == ([2200, 2400] if held else [0, 0])
        assert [row.cash_amount for row in snapshots] == [0, 0]
        assert [row.holding_profit_amount for row in snapshots] == (
            [Decimal("188.90"), Decimal("388.80")] if held else [0, 0])
        assert snapshots[-1].day_profit_amount == (Decimal("199.90") if held else None)
        assert snapshots[-1].day_capital_amount == (Decimal("2000.00") if held else None)
        assert session.scalar(select(func.count()).select_from(ValuationBasis).where(
            ValuationBasis.generation_id == generation)) == (4 if held else 0)
    retire(interruptions_db, lease)


@pytest.mark.parametrize("invalid", [False, True])
def test_resolver_failure_is_durable_and_does_not_create_date_inputs(interruptions_db, invalid):
    inputs, lease, generation, fee = setup(interruptions_db)
    with Session(interruptions_db) as session, session.begin():
        if session.get(TradeCalendar, ("SSE", DAY)) is None:
            session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True,
                pretrade_date=DAY-timedelta(days=1)))
    def bad(*args, **kwargs):
        if invalid:
            return DayInputBasis(fee, AT.replace(tzinfo=None))
        raise CalculationDataUnavailable("No confirmed source cutoff")
    runner = GenerationExecution(inputs.execution, sessionmaker(interruptions_db))
    assert runner.step(lease, generation_id=generation, resolve_day_inputs=bad) == "CALENDAR"
    with Session(interruptions_db) as session, session.begin():
        lease = inputs.execution.claim(session, executor_id="resolver", deadline=deadline())
    assert runner.step(lease, generation_id=generation, resolve_day_inputs=bad) == (
        "FAILED" if invalid else "WAITING_DATA")
    with Session(interruptions_db) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
            CalculationBatch.generation_id == generation, CalculationBatch.stage != "CALENDAR")) == 0
        pending = session.get(Recalculation, lease.account_id)
        assert pending.executor_id is None
        assert (pending.next_attempt_at is None) == invalid
        assert inputs.execution.claim(session, executor_id="too-soon", deadline=deadline()) is None
        pending.next_attempt_at = session.scalar(select(func.clock_timestamp()))-timedelta(seconds=1)
    with Session(interruptions_db) as session, session.begin():
        lease = inputs.execution.claim(session, executor_id="after-recovery", deadline=deadline())
    assert runner.step(lease, generation_id=generation,
        resolve_day_inputs=lambda *a, **k: DayInputBasis(fee, AT)) == "VALUATION_END"
    retire(interruptions_db, lease)
