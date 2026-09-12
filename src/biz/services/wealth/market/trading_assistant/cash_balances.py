"""Persist exact cash continuation without pretending a weekend is a trading day."""
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from src.biz.models.wealth.trading_assistant.accounts import Initialization
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.queries.wealth.market.trading_assistant.effective_ledger import effective_ledger
from .calculation.cash_day import close_cash_day
from .cash_day_batches import CashDayBatches
from .calculation_inputs import CalculationInputMismatch
from .persistence_values import numeric_cents


class CashBalances:
    def __init__(self, execution):
        self.execution = execution
        self.cash = CashDayBatches(execution)
        self.inputs = self.cash.inputs

    def close_date(self, session, lease, *, generation_id, business_date, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self.inputs._generation(session, lease, account, generation_id, business_date,
                                                  stages=("PREPARING", "CALCULATING"))
            source = self.cash._latest(session, lease, generation_id, business_date)
            if source is None or not source.cursor["done"]:
                raise CalculationInputMismatch("Cash date is not fully reduced")
            checked = aliased(CalculationBatch)
            missing = session.scalar(select(CalculationBatch.page_key).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == business_date, CalculationBatch.stage == "ACCOUNT_CASH",
                CalculationBatch.stock_key == "", ~select(checked.page_key).where(
                    checked.account_id == CalculationBatch.account_id,
                    checked.generation_id == CalculationBatch.generation_id,
                    checked.trade_date == CalculationBatch.trade_date, checked.stage == "ACCOUNT_CASH_CHECK",
                    checked.stock_key == "", checked.page_key == CalculationBatch.page_key,
                    checked.input_digest == CalculationBatch.input_digest,
                    checked.row_count == CalculationBatch.row_count,
                    checked.cursor == CalculationBatch.cursor).exists()).limit(1))
            if missing is not None:
                raise CalculationInputMismatch("Every cash source page must be verified before closing")
            identity = (lease.account_id, generation_id, business_date, "CASH_BALANCE", "", "1")
            existing = session.get(CalculationBatch, identity)
            previous = session.scalar(select(CalculationBatch).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.stage == "CASH_BALANCE", CalculationBatch.stock_key == "",
                CalculationBatch.trade_date < business_date).order_by(CalculationBatch.trade_date.desc()).limit(1))
            later = session.scalar(select(CalculationBatch.page_key).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.stage == "CASH_BALANCE", CalculationBatch.trade_date > business_date).limit(1))
            if existing is None and later is not None:
                raise CalculationInputMismatch("Cannot insert a cash date behind its saved continuation")
            after = previous.trade_date if previous else None
            facts = effective_ledger(owner_id=account.owner_id, account_id=lease.account_id,
                                     fact_version=generation.fact_version)
            gap = select(facts.c.ledger_id).where(facts.c.occurred_on < business_date)
            if after is not None:
                gap = gap.where(facts.c.occurred_on > after)
            if session.scalar(gap.limit(1)) is not None or (
                    business_date > account.initialized_on and (after is None or after < account.initialized_on)):
                raise CalculationInputMismatch("Cash continuation skipped movements or the initialization date")
            initial = session.get(Initialization, generation.initialization_id)
            if initial is None or initial.account_id != lease.account_id:
                raise CalculationInputMismatch("Initialization cash identity does not match")
            prior_value = previous.accumulator["closingCash"] if previous else None
            prior_cash = int(prior_value) if prior_value is not None else None
            totals = self.cash._restore(source)
            closing = close_cash_day(totals, business_date=business_date, initialized_on=account.initialized_on,
                initial_cash_cents=numeric_cents(initial.initial_cash), previous_cash_cents=prior_cash)
            opening = numeric_cents(initial.initial_cash) if business_date == account.initialized_on else prior_cash
            accumulator = {"openingCash": str(opening) if opening is not None else None,
                "closingCash": str(closing) if closing is not None else None,
                "sourceDigest": source.input_digest.hex(), "initializationId": str(initial.initialization_id),
                "previousDate": after.isoformat() if after else None,
                "previousDigest": previous.input_digest.hex() if previous else None}
            digest = sha256(self.inputs._encoded(accumulator)).digest()
            if existing is not None:
                if existing.accumulator != accumulator or existing.input_digest != digest:
                    raise CalculationInputMismatch("Saved cash balance no longer matches its inputs")
                return closing
            now = session.scalar(select(func.clock_timestamp()))
            result = CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=business_date, stage="CASH_BALANCE", stock_key="", page_key="1",
                cursor={"done": True}, accumulator=accumulator, input_digest=digest,
                row_count=totals.record_count, completed_at=now)
            session.add(result)
            session.flush()
            session.refresh(result)
            if result.accumulator != accumulator or result.input_digest != digest:
                raise CalculationInputMismatch("Cash balance read-back mismatch")
            generation.last_business_updated_at = now
            return closing
