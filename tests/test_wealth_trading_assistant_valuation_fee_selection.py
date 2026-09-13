"""Historical fee recovery across calculation targets, isolated PostgreSQL."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, DAY, AT, deadline, fact, retire
from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.valuation_fee_selection import valuation_fee_version
from src.biz.services.wealth.market.trading_assistant.generation_steps import GenerationSteps
from src.foundation.models.core.trade_calendar import TradeCalendar


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("corrupt", [False, True])
def test_recompute_keeps_original_day_fee_but_can_use_corrected_prices(migrated, empty, corrupt):
    inputs, lease, original_generation, original_fee = setup(migrated)
    with Session(migrated) as session, session.begin():
        session.get(Account, lease.account_id).initialized_on = DAY-timedelta(days=30)
        if empty:
            if session.get(TradeCalendar, ("SSE", DAY)) is None:
                session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True,
                    pretrade_date=DAY-timedelta(days=1)))
                session.flush()
            steps = GenerationSteps(inputs.execution)
            assert steps.advance(session, lease, generation_id=original_generation, deadline=deadline()) == "CALENDAR"
            assert steps.prepare_next_inputs(session, lease, generation_id=original_generation,
                business_date=DAY, fee_version_id=original_fee, valuation_at=AT, deadline=deadline()) == "VALUATION_END"
        else:
            inputs.save_valuation_page(session, lease, generation_id=original_generation,
                facts=(fact(price="10.00"),), fee_version_id=original_fee,
                valuation_at=AT, after_stock=None, deadline=deadline())
        inputs.execution.release(session, lease, deadline=deadline())
        account = session.get(Account, lease.account_id)
        newer_fee = uuid4()
        session.add(FeeVersion(fee_version_id=newer_fee, account_id=lease.account_id,
            commission_rate="0.0020", minimum_commission="0.00", stamp_tax_rate="0.0020", created_at=AT))
        account.current_fee_version_id = newer_fee
        account.calculation_target_version = 2
        pending = session.get(Recalculation, lease.account_id)
        pending.target_version = 2
        pending.next_attempt_at = session.scalar(select(func.clock_timestamp()))
        if corrupt:
            saved = session.scalar(select(CalculationBatch).where(
                CalculationBatch.generation_id == original_generation,
                CalculationBatch.stage == ("VALUATION_END" if empty else "VALUATION")))
            saved.input_digest = b"x"*32
    with Session(migrated) as session, session.begin():
        lease = inputs.execution.claim(session, executor_id="new-target", deadline=deadline())
        generation = inputs.prepare_generation(session, lease, from_date=DAY,
            through_date=DAY+timedelta(days=1), rule_version=1, deadline=deadline())
    if corrupt:
        with pytest.raises(CalculationInputMismatch):
            with Session(migrated) as session, session.begin():
                valuation_fee_version(session, inputs.execution, lease, generation_id=generation,
                    business_date=DAY, deadline=deadline())
    else:
        with Session(migrated) as session, session.begin():
            selected = valuation_fee_version(session, inputs.execution, lease, generation_id=generation,
                business_date=DAY, deadline=deadline())
            assert selected == original_fee
            # New prices belong to the new target; fee restoration is not an
            # excuse to copy old valuation prices or computed profits.
            inputs.save_valuation_page(session, lease, generation_id=generation,
                facts=(fact(price="11.00"),), fee_version_id=selected,
                valuation_at=AT, after_stock=None, deadline=deadline())
            assert valuation_fee_version(session, inputs.execution, lease, generation_id=generation,
                business_date=DAY+timedelta(days=1), deadline=deadline()) == newer_fee
        with Session(migrated) as session:
            rows = session.scalars(select(ValuationBasis).where(
                ValuationBasis.account_id == lease.account_id)).all()
            assert {row.fee_version_id for row in rows} == {original_fee}
            assert {str(row.price) for row in rows} == ({"11.00"} if empty else {"10.00", "11.00"})
    retire(migrated, lease)
