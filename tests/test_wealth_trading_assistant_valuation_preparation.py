"""Bounded actual source reads and frozen resume on isolated PostgreSQL."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, DAY, AT, fact, retire
from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from src.biz.services.wealth.market.trading_assistant.calendar_inputs import CalendarInputs
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution
from src.biz.services.wealth.market.trading_assistant.valuation_preparation import ValuationPreparation
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@pytest.mark.parametrize("held", [False, True])
def test_preparation_pages_freeze_actual_values_and_resume(migrated, held):
    inputs, lease, generation, fee = setup(migrated)
    execution = RecalculationExecution(replace(inputs.policy, page_rows=1))
    with migrated.begin() as conn:
        EquityDailyBar.__table__.create(conn, checkfirst=True)
    with Session(migrated) as session, session.begin():
        if session.get(TradeCalendar, ("SSE", DAY)) is None:
            session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True,
                pretrade_date=DAY-timedelta(days=1)))
        if held:
            account = session.get(Account, lease.account_id)
            for code in ("000001.SZ", "600000.SH"):
                session.add(InitialPosition(initialization_id=account.current_initialization_id,
                    account_id=lease.account_id, ts_code=code, client_row_id=code, opened_on=DAY,
                    quantity=100, available_quantity=100, cost_price="10.00"))
            session.add(EquityDailyBar(ts_code="000001.SZ", trade_date=DAY,
                close=Decimal("10.1234"), source="tushare"))
        CalendarInputs(execution).freeze_next(session, lease, generation_id=generation, deadline=deadline())
    args = dict(generation_id=generation, business_date=DAY, previous_day_result_id=None,
                fee_version_id=fee, valuation_at=AT)
    with pytest.raises(CalculationInputMismatch, match="fee basis"):
        with Session(migrated) as session, session.begin():
            ValuationPreparation(execution).step(session, lease,
                **(args | {"fee_version_id": uuid4()}), deadline=deadline())
    for index in range(3 if held else 1):
        with pytest.raises(RuntimeError, match="rollback"):
            with Session(migrated) as session, session.begin():
                ValuationPreparation(execution).step(session, lease, **args, deadline=deadline())
                raise RuntimeError("rollback")
        with Session(migrated) as session, session.begin():
            done = ValuationPreparation(execution).step(session, lease, **args, deadline=deadline())
            assert done == (index == (2 if held else 0))
        if held and index == 0:
            with migrated.begin() as conn:
                conn.execute(update(EquityDailyBar).where(EquityDailyBar.ts_code=="000001.SZ")
                    .values(close=Decimal("99.00")))
            with pytest.raises(CalculationInputMismatch, match="basis changed"):
                with Session(migrated) as session, session.begin():
                    ValuationPreparation(execution).step(session, lease,
                        **(args | {"valuation_at": AT+timedelta(minutes=1)}), deadline=deadline())
    with Session(migrated) as session, session.begin():
        assert ValuationPreparation(execution).step(session, lease, **args, deadline=deadline())
        assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
            CalculationBatch.generation_id==generation, CalculationBatch.stage=="VALUATION_END")) == 1
        rows = session.scalars(select(ValuationBasis).where(ValuationBasis.generation_id==generation)
            .order_by(ValuationBasis.ts_code)).all()
        assert len(rows) == (2 if held else 0)
        if held:
            assert rows[0].price == Decimal("10.1234")
            assert rows[1].price is None and rows[1].quality == "UNAVAILABLE"
    with pytest.raises(CalculationInputMismatch, match="completed valuation scope"):
        with Session(migrated) as session, session.begin():
            inputs.save_valuation_page(session, lease, generation_id=generation,
                facts=(fact(code="920002.BJ"),), fee_version_id=fee, valuation_at=AT,
                after_stock="600000.SH" if held else None, deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="completion changed"):
        with Session(migrated) as session, session.begin():
            terminal = session.get(CalculationBatch, (lease.account_id, generation, DAY, "VALUATION_END", "", "1"))
            terminal.accumulator = terminal.accumulator | {"previousDigest": "invalid"}
            session.flush()
            ValuationPreparation(execution).step(session, lease, **args, deadline=deadline())
    retire(migrated, lease)
