"""Join completed stock and cash reductions into an unpublished daily snapshot."""
from hashlib import sha256
from datetime import datetime, timezone

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot
from .account_day_batches import _totals_value
from .calculation.account_day import finish_account_day
from .calculation_inputs import CalculationInputMismatch
from .cash_day_batches import CashDayBatches
from .snapshot_values import snapshot_values
from .stock_day_batches import StockDayBatches


class SnapshotCandidates:
    def __init__(self, execution):
        self.execution = execution
        self.stocks = StockDayBatches(execution)
        self.cash = CashDayBatches(execution)

    def save(self, session, lease, *, generation_id, day_result_id, valuation_at, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day, generation = self.stocks._day(session, lease, account, generation_id, day_result_id)
            stocks = self.stocks._latest(session, lease, generation_id, day.trade_date, "", "ACCOUNT_STOCKS")
            cash_source = self.cash._latest(session, lease, generation_id, day.trade_date)
            balance = session.get(CalculationBatch,
                (lease.account_id, generation_id, day.trade_date, "CASH_BALANCE", "", "1"))
            if (stocks is None or not stocks.cursor["done"] or cash_source is None
                    or not cash_source.cursor["done"] or balance is None):
                raise CalculationInputMismatch("Complete stock and cash candidates are required")
            if (stocks.accumulator["binding"]["dayResultId"] != str(day_result_id)
                    or balance.accumulator["sourceDigest"] != cash_source.input_digest.hex()):
                raise CalculationInputMismatch("Snapshot sources no longer match their completed reductions")
            totals, cash = _totals_value(stocks.accumulator["totals"]), self.cash._restore(cash_source)
            if (totals.buy_input_cents, totals.sell_net_cents) != (cash.buy_input_cents, cash.sell_net_cents):
                raise CalculationInputMismatch("Stock and cash trade totals do not reconcile")
            opening_text = balance.accumulator["openingCash"]
            amounts = finish_account_day(totals, account_id=str(lease.account_id), business_date=day.trade_date,
                opening_cash_cents=int(opening_text) if opening_text is not None else None,
                cash_in_cents=cash.cash_in_cents, cash_out_cents=cash.cash_out_cents)
            if (str(amounts.cash_cents) if amounts.cash_cents is not None else None) != balance.accumulator["closingCash"]:
                raise CalculationInputMismatch("Snapshot cash does not match the persisted daily balance")
            values = snapshot_values(amounts, account_id=lease.account_id, day_result_id=day_result_id,
                                     trade_date=day.trade_date, valuation_at=valuation_at)
            evidence = {"stocks": stocks.input_digest.hex(), "cash": balance.input_digest.hex(),
                        "values": {key: (value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime)
                            else str(value) if value is not None else None) for key, value in values.items()}}
            digest = sha256(self.stocks.inputs._encoded(evidence)).digest()
            identity = (lease.account_id, generation_id, day.trade_date, "ACCOUNT_SNAPSHOT", "", "1")
            checkpoint = session.get(CalculationBatch, identity)
            saved = session.get(AccountSnapshot, (lease.account_id, day_result_id))
            if checkpoint is not None or saved is not None:
                if (checkpoint is None or saved is None or checkpoint.input_digest != digest
                        or any(getattr(saved, key) != value for key, value in values.items())):
                    raise CalculationInputMismatch("Existing snapshot candidate differs; it cannot be overwritten")
                return
            now = session.scalar(select(func.clock_timestamp()))
            saved = AccountSnapshot(**values)
            session.add(saved)
            session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=day.trade_date, stage="ACCOUNT_SNAPSHOT", stock_key="", page_key="1",
                cursor={"done": True}, accumulator=evidence, input_digest=digest, row_count=1, completed_at=now))
            session.flush()
            session.refresh(saved)
            if any(getattr(saved, key) != value for key, value in values.items()):
                raise CalculationInputMismatch("Snapshot candidate read-back mismatch")
            generation.last_business_updated_at = now
