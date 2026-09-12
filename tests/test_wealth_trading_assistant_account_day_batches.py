"""Bounded stock candidates -> account accumulator, isolated PostgreSQL."""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, fact, DAY, AT, deadline, retire
from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion
from src.biz.models.wealth.trading_assistant.calculation import DayResult, PositionState as StoredPosition
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.services.wealth.market.trading_assistant.account_day_batches import AccountDayBatches, _totals_value
from src.biz.services.wealth.market.trading_assistant.calculation.account_day import finish_account_day
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution
from src.biz.services.wealth.market.trading_assistant.stock_day_batches import StockDayBatches


def test_account_reduction_restarts_without_duplicating_stock_profit(migrated):
    inputs, lease, generation, fee = setup(migrated)
    execution = RecalculationExecution(replace(inputs.policy, page_rows=1))
    stocks, service = StockDayBatches(execution), AccountDayBatches(execution)
    day = uuid4()
    with Session(migrated) as session, session.begin():
        session.add(DayResult(day_result_id=day, account_id=lease.account_id, origin_generation_id=generation,
            trade_date=DAY, input_digest=b"a"*32, status="BUILDING"))
        inputs.save_valuation_page(session, lease, generation_id=generation,
            facts=(fact("000001.SZ", "11.00"), fact("000002.SZ", "11.00")),
            fee_version_id=fee, valuation_at=AT, after_stock=None, deadline=deadline())
    kwargs = dict(generation_id=generation, day_result_id=day, previous_day_result_id=None)
    with pytest.raises(CalculationInputMismatch, match="earlier sealed"):
        with Session(migrated) as session, session.begin():
            service.reduce_page(session, lease, **(kwargs | {"previous_day_result_id": day}), deadline=deadline())
    for code in ("000001.SZ", "000002.SZ"):
        args = dict(generation_id=generation, day_result_id=day, stock=code,
            opening=PositionState(1000, 1000, 1000000, 1000000, 0))
        with Session(migrated) as session, session.begin():
            assert stocks.summarize_page(session, lease, **args, deadline=deadline())
            assert stocks.close_page(session, lease, **args, round_id=uuid4(), opened_on=DAY, deadline=deadline())
    # A duplicate round at a one-row page boundary must not be silently skipped.
    with pytest.raises(CalculationInputMismatch, match="Multiple rounds"):
        with Session(migrated) as session, session.begin():
            session.add(StoredPosition(account_id=lease.account_id, day_result_id=day, ts_code="000001.SZ",
                round_id=uuid4(), opened_on=DAY, quantity=1000, remaining_buy_cost=10000,
                cumulative_buy_input=10000, cumulative_sell_net=0))
            session.flush()
            service.reduce_page(session, lease, **kwargs, deadline=deadline())
    # The saved valuation fee, not this newly selected configuration, is used.
    with Session(migrated) as session, session.begin():
        new_fee = uuid4()
        session.add(FeeVersion(fee_version_id=new_fee, account_id=lease.account_id,
            commission_rate="0.001", minimum_commission="100.00", stamp_tax_rate="0.001",
            created_at=datetime.now(timezone.utc)))
        session.get(Account, lease.account_id).current_fee_version_id = new_fee
    with Session(migrated) as session, session.begin():
        assert not service.reduce_page(session, lease, **kwargs, deadline=deadline())
    with pytest.raises(RuntimeError, match="crash"):
        with Session(migrated) as session, session.begin():
            assert not service.reduce_page(session, lease, **kwargs, deadline=deadline())
            raise RuntimeError("crash")
    restarted = AccountDayBatches(execution)
    for done in (False, True, True):
        with Session(migrated) as session, session.begin():
            assert restarted.reduce_page(session, lease, **kwargs, deadline=deadline()) == done
    with Session(migrated) as session:
        checkpoints = session.scalars(select(CalculationBatch).where(CalculationBatch.generation_id == generation,
            CalculationBatch.stage == "ACCOUNT_STOCKS").order_by(CalculationBatch.page_key)).all()
        assert len(checkpoints) == 3 and [row.row_count for row in checkpoints] == [1, 1, 0]
        totals = _totals_value(checkpoints[-1].accumulator["totals"])
        result = finish_account_day(totals, account_id=str(lease.account_id), business_date=DAY,
            opening_cash_cents=0, cash_in_cents=0, cash_out_cents=0)
        assert (result.day_return.profit_cents, result.day_return.capital_cents,
                result.day_return.return_pct) == (197900, 2000000, "9.90")
        assert session.get(Account, lease.account_id).published_generation_id is None
        assert session.get(DayResult, day).status == "BUILDING"
    retire(migrated, lease)
