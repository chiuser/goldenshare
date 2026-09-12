"""Prepare one bounded stock-price page using caller-selected cutoff and fees.

No clock, fee selection, source discovery or background loop is hidden here.
An empty source page proves scope exhaustion, not that all prices are ready.
"""
from hashlib import sha256
from datetime import date, datetime, timezone

from sqlalchemy import select, func

from src.biz.models.wealth.trading_assistant.calculation import DayResult
from src.biz.models.wealth.trading_assistant.accounts import FeeVersion
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.queries.wealth.market.trading_assistant.calculation_stocks import stock_day_page
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .calendar_inputs import CalendarInputs
from .valuation_facts import DailyCloseFactsReader


class ValuationPreparation:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)

    def step(self, session, lease, *, generation_id, business_date,
             previous_day_result_id, fee_version_id, valuation_at, deadline):
        if not isinstance(valuation_at, datetime) or valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
            raise ValueError("Timezone-aware valuation cutoff required")
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self.inputs._generation(session, lease, account, generation_id,
                business_date, stages=("PREPARING", "CALCULATING"))
            fee = session.get(FeeVersion, fee_version_id)
            if fee is None or fee.account_id != lease.account_id:
                raise CalculationInputMismatch("Valuation fee basis belongs to another account")
            calendar = CalendarInputs(self.execution).read_date(session, lease,
                generation_id=generation_id, business_date=business_date, deadline=deadline)
            if not calendar["is_open"]:
                raise CalculationInputMismatch("Valuation preparation requires a trading date")
            prior_date = date.fromisoformat(calendar["previous_trade_date"]) if calendar["previous_trade_date"] else None
            previous = session.get(DayResult, previous_day_result_id) if previous_day_result_id else None
            if previous_day_result_id is not None:
                if (previous is None or previous.account_id != lease.account_id
                        or previous.origin_generation_id != generation_id or previous.status != "SEALED"
                        or previous.trade_date != prior_date):
                    raise CalculationInputMismatch("Valuation scope requires the sealed preceding day")
            elif prior_date is not None and prior_date >= generation.from_date:
                raise CalculationInputMismatch("Missing preceding day for valuation scope")
            latest = session.scalar(select(CalculationBatch).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == business_date, CalculationBatch.stage == "VALUATION",
                CalculationBatch.stock_key == "").order_by(CalculationBatch.page_key.desc()).limit(1))
            after = latest.page_key if latest else None
            if latest:
                frozen = self.inputs.read_valuation_page(session, lease, generation_id=generation_id,
                    trade_date=business_date, page_key=after, deadline=deadline)
                if (frozen.fee_version_id, frozen.valuation_at) != (fee_version_id, valuation_at):
                    raise CalculationInputMismatch("Valuation preparation basis changed between pages")
            binding = {"previousDayId": str(previous_day_result_id) if previous else None,
                "previousDigest": previous.input_digest.hex() if previous else None,
                "feeVersionId": str(fee_version_id), "valuationAt": valuation_at.astimezone(timezone.utc).isoformat(),
                "lastPageDigest": latest.input_digest.hex() if latest else None}
            digest = sha256(self.inputs._encoded(binding)).digest()
            identity = (lease.account_id, generation_id, business_date, "VALUATION_END", "", "1")
            terminal = session.get(CalculationBatch, identity)
            if terminal is not None:
                if (terminal.accumulator != binding or terminal.input_digest != digest
                        or terminal.cursor != {"afterStock": after, "done": True} or terminal.row_count != 0):
                    raise CalculationInputMismatch("Valuation scope completion changed")
                return True
            if session.scalar(select(DayResult.day_result_id).where(
                DayResult.account_id == lease.account_id, DayResult.origin_generation_id == generation_id,
                DayResult.trade_date == business_date).limit(1)) is not None:
                raise CalculationInputMismatch("Valuation preparation must precede this day's calculation")
            codes = tuple(session.scalars(stock_day_page(owner_id=account.owner_id,
                account_id=lease.account_id, initialization_id=generation.initialization_id,
                fact_version=generation.fact_version, trade_date=business_date,
                previous_day_result_id=previous_day_result_id, limit=self.execution.policy.page_rows,
                policy=self.execution.policy, after=after)).all())
            if codes:
                facts = DailyCloseFactsReader(self.execution.policy).read(session, codes, business_date, deadline)
                self.inputs.save_valuation_page(session, lease, generation_id=generation_id,
                    facts=facts, fee_version_id=fee_version_id, valuation_at=valuation_at,
                    after_stock=after, deadline=deadline)
                return False
            now = session.scalar(select(func.clock_timestamp()))
            row = CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=business_date, stage="VALUATION_END", stock_key="", page_key="1",
                cursor={"afterStock": after, "done": True}, accumulator=binding,
                input_digest=digest, row_count=0, completed_at=now)
            session.add(row)
            session.flush()
            session.refresh(row)
            if (row.accumulator, row.input_digest, row.cursor, row.row_count) != (
                    binding, digest, {"afterStock": after, "done": True}, 0):
                raise CalculationInputMismatch("Valuation scope completion readback differs")
            generation.last_business_updated_at = now
            return True
