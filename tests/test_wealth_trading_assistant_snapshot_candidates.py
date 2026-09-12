"""Computed stock and cash stages join into a candidate, never an early publication."""
from datetime import timedelta
from uuid import uuid4, uuid5

import pytest
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY, AT, fact
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import DayResult
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot
from src.biz.services.wealth.market.trading_assistant.account_day_batches import AccountDayBatches
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.cash_balances import CashBalances
from src.biz.services.wealth.market.trading_assistant.cash_day_batches import CashDayBatches
from src.biz.services.wealth.market.trading_assistant.snapshot_candidates import SnapshotCandidates
from src.biz.services.wealth.market.trading_assistant.stock_day_batches import StockDayBatches
from src.biz.services.wealth.market.trading_assistant.day_scope_verification import DayScopeVerification
from src.biz.services.wealth.market.trading_assistant.day_sealing import DaySealing
from src.biz.services.wealth.market.trading_assistant.stock_day_verification import StockDayVerification
from src.biz.services.wealth.market.trading_assistant.calendar_inputs import CalendarInputs
from src.biz.services.wealth.market.trading_assistant.generation_publication import GenerationPublication
from src.foundation.models.core.trade_calendar import TradeCalendar


@pytest.mark.parametrize("held", [False, True])
def test_snapshot_composition_requires_completed_inputs(publication_db, held):
    inputs, lease, generation, fee = setup(publication_db)
    execution = inputs.execution
    day = uuid4()
    args = dict(generation_id=generation, day_result_id=day)
    snapshots = SnapshotCandidates(execution)
    with Session(publication_db) as session, session.begin():
        if session.get(TradeCalendar, ("SSE", DAY)) is None:
            session.add(TradeCalendar(exchange="SSE", trade_date=DAY, is_open=True, pretrade_date=DAY-timedelta(days=1)))
        session.add(DayResult(day_result_id=day, account_id=lease.account_id, origin_generation_id=generation,
            trade_date=DAY, input_digest=b"a"*32, status="BUILDING"))
        if held:
            account = session.get(Account, lease.account_id)
            session.add(InitialPosition(initialization_id=account.current_initialization_id,
                account_id=lease.account_id, ts_code="000001.SZ", client_row_id="initial-1", opened_on=DAY,
                quantity=1000, available_quantity=1000, cost_price="10.00"))
            inputs.save_valuation_page(session, lease, generation_id=generation,
                facts=(fact(price="11.00"),), fee_version_id=fee, valuation_at=AT,
                after_stock=None, deadline=deadline())
        assert CalendarInputs(execution).freeze_next(session, lease, generation_id=generation, deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="Complete stock and cash"):
        with Session(publication_db) as session, session.begin():
            snapshots.save(session, lease, **args, valuation_at=AT, deadline=deadline())
    if held:
        stock_args = args | dict(stock="000001.SZ", opening=PositionState(1000, 1000, 1000000, 1000000, 0))
        with Session(publication_db) as session, session.begin():
            stocks = StockDayBatches(execution)
            assert stocks.summarize_page(session, lease, **stock_args, deadline=deadline())
            assert stocks.prepare_sell_page(session, lease, **stock_args, deadline=deadline())
            initial_id = session.get(Account, lease.account_id).current_initialization_id
            round_id = uuid5(lease.account_id, f"INITIAL:{initial_id}:000001.SZ")
            assert stocks.close_page(session, lease, **stock_args, round_id=round_id, opened_on=DAY, deadline=deadline())
    for expected in ([False, True] if held else [True]):
        with Session(publication_db) as session, session.begin():
            assert DayScopeVerification(execution).verify_next(session, lease, **args,
                previous_day_result_id=None, deadline=deadline()) == expected
    for expected in ([False, True] if held else [True]):
        with Session(publication_db) as session, session.begin():
            assert AccountDayBatches(execution).reduce_page(session, lease, **args,
                previous_day_result_id=None, deadline=deadline()) == expected
    for page in range(1, 3 if held else 2):
        with Session(publication_db) as session, session.begin():
            assert AccountDayBatches(execution).verify_page(session, lease, **args,
                previous_day_result_id=None, page_key=f"{page:020d}", deadline=deadline()) == (page == (2 if held else 1))
    with Session(publication_db) as session, session.begin():
        cash = CashDayBatches(execution)
        cash_args = dict(generation_id=generation, business_date=DAY)
        assert cash.reduce_page(session, lease, **cash_args, deadline=deadline())
        cash.verify_page(session, lease, **cash_args, page_key=f"{1:020d}", deadline=deadline())
        assert CashBalances(execution).close_date(session, lease, **cash_args, deadline=deadline()) == 0
    with pytest.raises(RuntimeError, match="crash"):
        with Session(publication_db) as session, session.begin():
            snapshots.save(session, lease, **args, valuation_at=AT, deadline=deadline())
            raise RuntimeError("crash")
    for _ in range(2):
        with Session(publication_db) as session, session.begin():
            SnapshotCandidates(execution).save(session, lease, **args, valuation_at=AT, deadline=deadline())
    with Session(publication_db) as session:
        saved = session.get(AccountSnapshot, (lease.account_id, day))
        assert saved.cash_amount == 0
        assert saved.stock_market_value == saved.total_assets == (11000 if held else 0)
        assert saved.day_profit_amount == (989.50 if held else None)
        assert saved.closed_trade_count == 0
        assert session.get(DayResult, day).status == "BUILDING"
        assert session.get(Account, lease.account_id).published_generation_id is None
    with pytest.raises(CalculationInputMismatch, match="cannot be overwritten"):
        with Session(publication_db) as session, session.begin():
            snapshots.save(session, lease, **args, valuation_at=AT+timedelta(minutes=1), deadline=deadline())
    if held:
        with pytest.raises(CalculationInputMismatch, match="unverified"):
            with Session(publication_db) as session, session.begin():
                DaySealing(execution).seal(session, lease, **args, deadline=deadline())
        for stage in ("STOCK_SUMMARY", "STOCK_BASE", "STOCK_CLOSED"):
            with Session(publication_db) as session, session.begin():
                assert StockDayVerification(execution).verify_page(session, lease, **stock_args,
                    round_id=round_id, opened_on=DAY, stage=stage, page_key=f"{1:020d}", deadline=deadline())
    with pytest.raises(RuntimeError, match="crash"):
        with Session(publication_db) as session, session.begin():
            DaySealing(execution).seal(session, lease, **args, deadline=deadline())
            raise RuntimeError("crash")
    for _ in range(2):
        with Session(publication_db) as session, session.begin():
            assert len(DaySealing(execution).seal(session, lease, **args, deadline=deadline())) == 32
    with Session(publication_db) as session:
        assert session.get(DayResult, day).status == "SEALED"
        assert session.get(Account, lease.account_id).published_generation_id is None
    publisher = GenerationPublication(execution)
    with pytest.raises(CalculationInputMismatch):
        with Session(publication_db) as session, session.begin():
            publisher.publish(session, lease, generation_id=generation, deadline=deadline())
    for _ in range(2):
        with Session(publication_db) as session, session.begin():
            assert publisher.append_next(session, lease, generation_id=generation, deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="readback"):
        with Session(publication_db) as session, session.begin():
            publisher.publish(session, lease, generation_id=generation, deadline=deadline())
    with Session(publication_db) as session, session.begin():
        assert publisher.verify_date(session, lease, generation_id=generation, business_date=DAY, deadline=deadline())
    with pytest.raises(RuntimeError, match="crash"):
        with Session(publication_db) as session, session.begin():
            publisher.publish(session, lease, generation_id=generation, deadline=deadline())
            raise RuntimeError("crash")
    with Session(publication_db) as session, session.begin():
        assert not publisher.confirmed(session, owner_id=1, account_id=lease.account_id,
            generation_id=generation, target_version=lease.target_version)
        publisher.publish(session, lease, generation_id=generation, deadline=deadline())
    with Session(publication_db) as session:
        assert session.get(Account, lease.account_id).published_generation_id == generation
        assert publisher.confirmed(session, owner_id=1, account_id=lease.account_id,
            generation_id=generation, target_version=lease.target_version)
        assert not publisher.confirmed(session, owner_id=2, account_id=lease.account_id,
            generation_id=generation, target_version=lease.target_version)
    retire(publication_db, lease)
