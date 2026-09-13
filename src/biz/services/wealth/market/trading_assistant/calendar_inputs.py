"""Freeze complete, bounded calendar windows before walking calculation days."""
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .market_facts import MarketFactsReader


class CalendarInputs:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)

    def freeze_next(self, session, lease, *, generation_id, deadline):
        from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
        with self.execution.batch(session, lease, deadline=deadline) as account:
            candidate = session.get(CalculationGeneration, generation_id)
            if candidate is None:
                raise CalculationInputMismatch("Missing generation")
            generation = self.inputs._generation(session, lease, account, generation_id, candidate.from_date)
            previous = session.scalar(select(CalculationBatch).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.stage == "CALENDAR", CalculationBatch.stock_key == "")
                .order_by(CalculationBatch.trade_date.desc()).limit(1))
            if previous and previous.cursor["done"]:
                return True
            from datetime import date
            start = date.fromisoformat(previous.cursor["through"]) + timedelta(days=1) if previous else generation.from_date
            end = min(generation.through_date, start + timedelta(days=self.execution.policy.page_rows - 1))
            basis = MarketFactsReader(self.execution.policy).read_calendar(session, "SSE", start, end, deadline)
            rows = [{key: value.isoformat() if isinstance(value, date) else value for key, value in asdict(day).items()}
                    for day in basis.days]
            count = (int(previous.accumulator["tradeCount"]) if previous else 0) + sum(day.is_open for day in basis.days)
            cursor = {"through": end.isoformat(), "done": end == generation.through_date}
            accumulator = {"rows": rows, "tradeCount": str(count), "sourceVersion": basis.source_version}
            digest = sha256(self.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
                "cursor": cursor, "accumulator": accumulator})).digest()
            now = session.scalar(select(func.clock_timestamp()))
            row = CalculationBatch(account_id=lease.account_id, generation_id=generation_id, trade_date=start,
                stage="CALENDAR", stock_key="", page_key="1", cursor=cursor, accumulator=accumulator,
                input_digest=digest, row_count=len(rows), completed_at=now)
            session.add(row)
            session.flush()
            session.refresh(row)
            if (row.cursor, row.accumulator, row.input_digest) != (cursor, accumulator, digest):
                raise CalculationInputMismatch("Calendar checkpoint readback differs")
            if cursor["done"]:
                generation.total_trade_date_count = count
            generation.last_business_updated_at = now
            return cursor["done"]

    def read_date(self, session, lease, *, generation_id, business_date, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            self.inputs._generation(session, lease, account, generation_id, business_date,
                                    stages=("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING"))
            return self._read_saved_date(session, lease.account_id, generation_id, business_date)

    def _read_saved_date(self, session, account_id, generation_id, business_date):
        """Read-only integrity check; caller must fence/authorize the account."""
        row = session.scalar(select(CalculationBatch).where(CalculationBatch.account_id == account_id,
            CalculationBatch.generation_id == generation_id, CalculationBatch.stage == "CALENDAR",
            CalculationBatch.stock_key == "", CalculationBatch.trade_date <= business_date)
            .order_by(CalculationBatch.trade_date.desc()).limit(1))
        if row is None:
            raise CalculationInputMismatch("Calendar date has not been frozen")
        previous = session.scalar(select(CalculationBatch).where(CalculationBatch.account_id == account_id,
            CalculationBatch.generation_id == generation_id, CalculationBatch.stage == "CALENDAR",
            CalculationBatch.stock_key == "", CalculationBatch.trade_date < row.trade_date)
            .order_by(CalculationBatch.trade_date.desc()).limit(1))
        digest = sha256(self.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
            "cursor": row.cursor, "accumulator": row.accumulator})).digest()
        if digest != row.input_digest or row.row_count != len(row.accumulator["rows"]):
            raise CalculationInputMismatch("Frozen calendar contents changed")
        for fact in row.accumulator["rows"]:
            if fact["trade_date"] == business_date.isoformat():
                return fact
        raise CalculationInputMismatch("Calendar date is missing from the frozen page")
