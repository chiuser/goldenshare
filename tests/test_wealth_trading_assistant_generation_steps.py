"""Prepared window -> sequential dates -> atomic publication on isolated PG."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY, AT, fact
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import DayResult, CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from src.biz.services.wealth.market.trading_assistant.generation_steps import GenerationSteps
from src.biz.services.wealth.market.trading_assistant.generation_publication import GenerationPublication
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.foundation.models.core.trade_calendar import TradeCalendar


@pytest.mark.parametrize("held", [False, True])
def test_window_resumes_one_unit_including_weekend_cash(publication_db, held):
    inputs, lease, generation_id, fee = setup(publication_db)
    monday = DAY + timedelta(days=3)
    with Session(publication_db) as session, session.begin():
        generation = session.get(CalculationGeneration, generation_id)
        generation.through_date = monday
        generation.fact_version = 3
        account = session.get(Account, lease.account_id)
        account.fact_version = 3
        if held:
            session.add(InitialPosition(initialization_id=account.current_initialization_id,
                account_id=lease.account_id, ts_code="000001.SZ", client_row_id="holding",
                opened_on=DAY, quantity=1000, available_quantity=1000, cost_price="10.00"))
        for offset in range(4):
            current = DAY + timedelta(days=offset)
            if session.get(TradeCalendar, ("SSE", current)) is None:
                session.add(TradeCalendar(exchange="SSE", trade_date=current, is_open=offset in (0, 3),
                    pretrade_date=DAY - timedelta(days=1) if offset == 0 else DAY))
        for version, offset, direction, amount in ((2, 1, "IN", 100), (3, 2, "OUT", 20)):
            identity = uuid4()
            session.add(Ledger(ledger_id=identity, account_id=lease.account_id, kind="CASH_FLOW", created_at=AT))
            session.flush()
            session.add(LedgerRevision(ledger_id=identity, account_id=lease.account_id, kind="CASH_FLOW",
                revision=1, accepted_fact_version=version, occurred_on=DAY + timedelta(days=offset),
                status="ACTIVE", accepted_at=AT, direction=direction, cash_amount=amount,
                net_cash_change=amount if direction == "IN" else -amount))
        session.flush()
    args = dict(generation_id=generation_id)
    with Session(publication_db) as session, session.begin():
        assert GenerationSteps(inputs.execution).advance(session, lease, **args, deadline=deadline()) == "CALENDAR"
    with pytest.raises(CalculationInputMismatch, match="Date inputs"):
        with Session(publication_db) as session, session.begin():
            GenerationSteps(inputs.execution).advance(session, lease, **args, deadline=deadline())
    with Session(publication_db) as session, session.begin():
        for offset in range(4):
            current = DAY + timedelta(days=offset)
            GenerationSteps(inputs.execution).prepare_date(session, lease, **args,
                business_date=current, valuation_at=AT + timedelta(days=offset), deadline=deadline())
        if held:
            for current, price in ((DAY, "11.00"), (monday, "12.00")):
                inputs.save_valuation_page(session, lease, **args,
                    facts=(replace(fact(price=price), valuation_date=current, price_date=current),),
                    fee_version_id=fee, valuation_at=AT + (current - DAY), after_stock=None, deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="Prepared date inputs changed"):
        with Session(publication_db) as session, session.begin():
            GenerationSteps(inputs.execution).prepare_date(session, lease, **args,
                business_date=DAY, valuation_at=AT + timedelta(minutes=1), deadline=deadline())
    stages = []
    for _ in range(100):
        with Session(publication_db) as session:
            before = session.scalar(select(func.count()).select_from(CalculationBatch).where(
                CalculationBatch.generation_id == generation_id))
        with pytest.raises(RuntimeError, match="interrupted"):
            with Session(publication_db) as session, session.begin():
                expected = GenerationSteps(inputs.execution).advance(session, lease, **args, deadline=deadline())
                raise RuntimeError("interrupted")
        with Session(publication_db) as session, session.begin():
            assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
                CalculationBatch.generation_id == generation_id)) == before
            assert session.get(Account, lease.account_id).published_generation_id is None
            stage = GenerationSteps(inputs.execution).advance(session, lease, **args, deadline=deadline())
            assert stage == expected
            after = session.scalar(select(func.count()).select_from(CalculationBatch).where(
                CalculationBatch.generation_id == generation_id))
            assert 0 <= after - before <= 1
            assert session.scalar(select(func.count()).select_from(DayResult).where(
                DayResult.origin_generation_id == generation_id, DayResult.status == "BUILDING")) <= 1
        stages.append(stage)
        if stage == "DATE_COMPLETE":
            with pytest.raises(CalculationInputMismatch, match="Completed date"):
                with Session(publication_db) as session, session.begin():
                    marker = session.scalar(select(CalculationBatch).where(
                        CalculationBatch.generation_id == generation_id,
                        CalculationBatch.stage == "DATE_COMPLETE")
                        .order_by(CalculationBatch.trade_date.desc()).limit(1))
                    marker.accumulator = marker.accumulator | {"cash": "wrong"}
                    session.flush()
                    GenerationSteps(inputs.execution).advance(session, lease, **args, deadline=deadline())
        if stage == "PUBLISHED":
            break
    else:
        pytest.fail("Prepared window did not complete")
    assert stages.count("DATE_COMPLETE") == 4
    assert stages.count("DAY_START") == stages.count("SEALED") == 2
    assert stages.count("MANIFEST") == stages.count("MANIFEST_CHECK") == 4
    with Session(publication_db) as session:
        days = session.scalars(select(PublicationDay).where(PublicationDay.generation_id == generation_id)
            .order_by(PublicationDay.trade_date)).all()
        assert [day.trade_date for day in days] == [DAY, monday]
        snapshot = session.get(AccountSnapshot, (lease.account_id, days[-1].day_result_id))
        assert snapshot.cash_amount == 80
        assert snapshot.stock_market_value == (12000 if held else 0)
        assert snapshot.day_profit_amount == (Decimal("999.50") if held else None)
        assert session.get(Recalculation, lease.account_id) is None
        assert GenerationPublication.confirmed(session, owner_id=1, account_id=lease.account_id,
            generation_id=generation_id, target_version=lease.target_version)
    retire(publication_db, lease)


def test_missing_price_cannot_complete_or_publish_date(publication_db):
    inputs, lease, generation, _ = setup(publication_db)
    with Session(publication_db) as session, session.begin():
        account = session.get(Account, lease.account_id)
        session.add(InitialPosition(initialization_id=account.current_initialization_id,
            account_id=lease.account_id, ts_code="000001.SZ", client_row_id="missing",
            opened_on=DAY, quantity=100, available_quantity=100, cost_price="10.00"))
        if session.get(TradeCalendar, ("SSE", DAY)) is None:
            session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True,
                pretrade_date=DAY - timedelta(days=1)))
    with Session(publication_db) as session, session.begin():
        GenerationSteps(inputs.execution).advance(session, lease, generation_id=generation, deadline=deadline())
        GenerationSteps(inputs.execution).prepare_date(session, lease, generation_id=generation,
            business_date=DAY, valuation_at=AT, deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="valuation"):
        for _ in range(30):
            with Session(publication_db) as session, session.begin():
                GenerationSteps(inputs.execution).advance(session, lease, generation_id=generation, deadline=deadline())
    with Session(publication_db) as session:
        assert session.get(CalculationGeneration, generation).completed_trade_date_count == 0
        assert session.get(Account, lease.account_id).published_generation_id is None
        assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
            CalculationBatch.generation_id == generation,
            CalculationBatch.stage.in_(("DATE_COMPLETE", "MANIFEST")))) == 0
        assert session.get(Recalculation, lease.account_id) is not None
    retire(publication_db, lease)
