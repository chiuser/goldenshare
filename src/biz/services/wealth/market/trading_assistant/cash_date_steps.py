"""Bounded natural-date cash progression; caller owns each short transaction."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import aliased

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from .calculation_inputs import CalculationInputMismatch
from .cash_balances import CashBalances


class CashDateSteps:
    def __init__(self, execution):
        self.execution = execution
        self.balances = CashBalances(execution)
        self.cash = self.balances.cash

    def advance(self, session, lease, *, generation_id, deadline):
        """Return (date, stage), or None when the fixed cash window is complete."""
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = session.get(CalculationGeneration, generation_id, populate_existing=True)
            if generation is None:
                raise CalculationInputMismatch("Missing fixed generation")
            self.cash.inputs._generation(session, lease, account, generation_id, generation.from_date,
                stages=("PREPARING", "CALCULATING"))
            previous = session.scalar(select(CalculationBatch.trade_date).where(
                CalculationBatch.account_id == lease.account_id,
                CalculationBatch.generation_id == generation_id,
                CalculationBatch.stage == "CASH_BALANCE", CalculationBatch.stock_key == "")
                .order_by(CalculationBatch.trade_date.desc()).limit(1))
            day = previous + timedelta(days=1) if previous is not None else generation.from_date
            if day > generation.through_date:
                return None
            return day, self.step(session, lease, generation_id=generation_id,
                business_date=day, deadline=deadline)

    def step(self, session, lease, *, generation_id, business_date, deadline):
        """One source page, one verification, or one balance; never a day loop."""
        with self.execution.batch(session, lease, deadline=deadline) as account:
            self.cash.inputs._generation(session, lease, account, generation_id, business_date,
                stages=("PREPARING", "CALCULATING"))
            args = dict(generation_id=generation_id, business_date=business_date, deadline=deadline)
            source = self.cash._latest(session, lease, generation_id, business_date)
            if source is None or not source.cursor["done"]:
                self.cash.reduce_page(session, lease, **args)
                return "ACCOUNT_CASH"
            checked = aliased(CalculationBatch)
            unchecked = session.scalar(select(CalculationBatch.page_key).where(
                CalculationBatch.account_id == lease.account_id,
                CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == business_date,
                CalculationBatch.stage == "ACCOUNT_CASH", CalculationBatch.stock_key == "",
                ~select(checked.page_key).where(
                    checked.account_id == CalculationBatch.account_id,
                    checked.generation_id == CalculationBatch.generation_id,
                    checked.trade_date == CalculationBatch.trade_date,
                    checked.stage == "ACCOUNT_CASH_CHECK", checked.stock_key == "",
                    checked.page_key == CalculationBatch.page_key,
                    checked.input_digest == CalculationBatch.input_digest,
                    checked.row_count == CalculationBatch.row_count,
                    checked.cursor == CalculationBatch.cursor).exists())
                .order_by(CalculationBatch.page_key).limit(1))
            if unchecked is not None:
                self.cash.verify_page(session, lease, **args, page_key=unchecked)
                return "ACCOUNT_CASH_CHECK"
            existing = session.get(CalculationBatch,
                (lease.account_id, generation_id, business_date, "CASH_BALANCE", "", "1"))
            self.balances.close_date(session, lease, **args)
            return "COMPLETE" if existing is not None else "CASH_BALANCE"
