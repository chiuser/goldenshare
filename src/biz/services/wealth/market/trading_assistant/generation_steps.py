"""Walk prepared natural dates, then publish; each call is one durable unit.

Market readiness, range selection and fee selection remain input-adapter duties.
This service never fetches missing prices or enables a background loop.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from .calendar_inputs import CalendarInputs
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .cash_date_steps import CashDateSteps
from .day_calculation_steps import DayCalculationSteps
from .generation_publication import GenerationPublication
from .valuation_preparation import ValuationPreparation


class GenerationSteps:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)
        self.calendar = CalendarInputs(execution)

    def prepare_next_inputs(self, session, lease, *, generation_id, business_date,
                            fee_version_id, valuation_at, deadline):
        """One input page or date cutoff; caller supplies trusted date-specific bases."""
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self.inputs._generation(session, lease, account, generation_id, business_date,
                stages=("PREPARING", "CALCULATING"))
            latest = session.scalar(select(CalculationBatch).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.stage == "DATE_COMPLETE", CalculationBatch.stock_key == "")
                .order_by(CalculationBatch.trade_date.desc()).limit(1))
            if latest is not None:
                self._verify_completed(session, lease, generation, latest)
            expected = latest.trade_date + timedelta(days=1) if latest else generation.from_date
            if business_date != expected:
                raise CalculationInputMismatch("Inputs must target the next incomplete date")
            calendar = self.calendar.read_date(session, lease, generation_id=generation_id,
                business_date=business_date, deadline=deadline)
            if calendar["is_open"]:
                terminal = session.get(CalculationBatch,
                    (lease.account_id, generation_id, business_date, "VALUATION_END", "", "1"))
                previous_id = session.scalar(select(DayResult.day_result_id).where(
                    DayResult.account_id == lease.account_id, DayResult.origin_generation_id == generation_id,
                    DayResult.trade_date < business_date, DayResult.status == "SEALED")
                    .order_by(DayResult.trade_date.desc()).limit(1))
                done = ValuationPreparation(self.execution).step(session, lease, generation_id=generation_id,
                    business_date=business_date, previous_day_result_id=previous_id,
                    fee_version_id=fee_version_id, valuation_at=valuation_at, deadline=deadline)
                if not done or terminal is None:
                    return "VALUATION_END" if done else "VALUATION"
            self.prepare_date(session, lease, generation_id=generation_id, business_date=business_date,
                valuation_at=valuation_at, deadline=deadline)
            return "DATE_INPUT"

    def prepare_date(self, session, lease, *, generation_id, business_date, valuation_at, deadline):
        """Persist the adapter-supplied cutoff, including days with no stocks."""
        if (not isinstance(valuation_at, datetime) or valuation_at.tzinfo is None
                or valuation_at.utcoffset() is None):
            raise ValueError("A timezone-aware valuation cutoff is required")
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self.inputs._generation(session, lease, account, generation_id, business_date,
                stages=("PREPARING", "CALCULATING"))
            fact = self.calendar.read_date(session, lease, generation_id=generation_id,
                business_date=business_date, deadline=deadline)
            values = {"calendar": fact, "valuationAt": valuation_at.astimezone(timezone.utc).isoformat()}
            digest = sha256(self.inputs._encoded(values)).digest()
            identity = (lease.account_id, generation_id, business_date, "DATE_INPUT", "", "1")
            saved = session.get(CalculationBatch, identity)
            if saved is not None:
                if saved.accumulator != values or saved.input_digest != digest:
                    raise CalculationInputMismatch("Prepared date inputs changed")
                return
            now = session.scalar(select(func.clock_timestamp()))
            session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=business_date, stage="DATE_INPUT", stock_key="", page_key="1",
                cursor={"done": True}, accumulator=values, input_digest=digest, row_count=1, completed_at=now))
            generation.last_business_updated_at = now

    def _verify_completed(self, session, lease, generation, row):
        day = row.trade_date
        if not generation.from_date <= day <= generation.through_date:
            raise CalculationInputMismatch("Date checkpoint is outside the fixed window")
        prepared = session.get(CalculationBatch,
            (lease.account_id, generation.generation_id, day, "DATE_INPUT", "", "1"))
        cash = session.get(CalculationBatch,
            (lease.account_id, generation.generation_id, day, "CASH_BALANCE", "", "1"))
        previous = session.get(CalculationBatch, (lease.account_id, generation.generation_id,
            day - timedelta(days=1), "DATE_COMPLETE", "", "1")) if day > generation.from_date else None
        result = session.scalar(select(DayResult).where(DayResult.account_id == lease.account_id,
            DayResult.origin_generation_id == generation.generation_id, DayResult.trade_date == day))
        if prepared is None or cash is None or (day > generation.from_date and previous is None):
            raise CalculationInputMismatch("Completed date lost its saved inputs")
        is_open = prepared.accumulator["calendar"]["is_open"]
        values = {"input": prepared.input_digest.hex(), "cash": cash.input_digest.hex(),
            "dayId": str(result.day_result_id) if result else None,
            "dayDigest": result.input_digest.hex() if result else None,
            "previous": previous.input_digest.hex() if previous else None}
        if (bool(result) != is_open or (result is not None and result.status != "SEALED")
                or prepared.input_digest != sha256(self.inputs._encoded(prepared.accumulator)).digest()
                or cash.input_digest != sha256(self.inputs._encoded(cash.accumulator)).digest()
                or row.accumulator != values or row.cursor != {"done": True}
                or row.row_count != int(is_open)
                or row.input_digest != sha256(self.inputs._encoded(values)).digest()):
            raise CalculationInputMismatch("Completed date does not match its saved results")

    def advance(self, session, lease, *, generation_id, deadline):
        # Publication clears the pending row; do not wrap it in batch's post-check.
        account, _ = self.execution._lock(session, lease, deadline)
        candidate = session.get(CalculationGeneration, generation_id, populate_existing=True)
        if candidate is None:
            raise CalculationInputMismatch("Missing fixed generation")
        generation = self.inputs._generation(session, lease, account, generation_id, candidate.from_date,
            stages=("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING"))
        latest = session.scalar(select(CalculationBatch).where(
            CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
            CalculationBatch.stage == "DATE_COMPLETE", CalculationBatch.stock_key == "")
            .order_by(CalculationBatch.trade_date.desc()).limit(1))
        if latest is not None:
            self._verify_completed(session, lease, generation, latest)
        if latest is not None and latest.trade_date == generation.through_date:
            return GenerationPublication(self.execution).advance(session, lease,
                generation_id=generation_id, deadline=deadline)
        if generation.stage not in ("PREPARING", "CALCULATING"):
            raise CalculationInputMismatch("Publication started before natural dates completed")
        if generation.total_trade_date_count is None:
            self.calendar.freeze_next(session, lease, generation_id=generation_id, deadline=deadline)
            return "CALENDAR"
        day = latest.trade_date + timedelta(days=1) if latest else generation.from_date
        with self.execution.batch(session, lease, deadline=deadline):
            fact = self.calendar.read_date(session, lease, generation_id=generation_id,
                business_date=day, deadline=deadline)
            prepared = session.get(CalculationBatch,
                (lease.account_id, generation_id, day, "DATE_INPUT", "", "1"))
            if (prepared is None or prepared.accumulator["calendar"] != fact
                    or sha256(self.inputs._encoded(prepared.accumulator)).digest() != prepared.input_digest):
                raise CalculationInputMismatch("Date inputs are missing or changed")
            result = session.scalar(select(DayResult).where(DayResult.account_id == lease.account_id,
                DayResult.origin_generation_id == generation_id, DayResult.trade_date == day))
            if not fact["is_open"]:
                if result is not None:
                    raise CalculationInputMismatch("Nontrading date has a stock result")
                stage = CashDateSteps(self.execution).step(session, lease,
                    generation_id=generation_id, business_date=day, deadline=deadline)
                if stage != "COMPLETE":
                    return stage
            else:
                if result is None:
                    terminal = session.get(CalculationBatch,
                        (lease.account_id, generation_id, day, "VALUATION_END", "", "1"))
                    if terminal is None:
                        raise CalculationInputMismatch("Complete valuation scope is required before starting a date")
                    previous_id = session.scalar(select(DayResult.day_result_id).where(
                        DayResult.account_id == lease.account_id, DayResult.origin_generation_id == generation_id,
                        DayResult.trade_date < day, DayResult.status == "SEALED")
                        .order_by(DayResult.trade_date.desc()).limit(1))
                    from uuid import UUID
                    ValuationPreparation(self.execution).step(session, lease, generation_id=generation_id,
                        business_date=day, previous_day_result_id=previous_id,
                        fee_version_id=UUID(terminal.accumulator["feeVersionId"]),
                        valuation_at=datetime.fromisoformat(prepared.accumulator["valuationAt"]), deadline=deadline)
                    session.add(DayResult(day_result_id=uuid4(), account_id=lease.account_id,
                        origin_generation_id=generation_id, trade_date=day,
                        input_digest=prepared.input_digest, status="BUILDING"))
                    generation.stage = "CALCULATING"
                    generation.last_business_updated_at = session.scalar(select(func.clock_timestamp()))
                    return "DAY_START"
                if result.status != "SEALED":
                    previous_id = session.scalar(select(DayResult.day_result_id).where(
                        DayResult.account_id == lease.account_id, DayResult.origin_generation_id == generation_id,
                        DayResult.trade_date < day, DayResult.status == "SEALED")
                        .order_by(DayResult.trade_date.desc()).limit(1))
                    return DayCalculationSteps(self.execution).step(session, lease, generation_id=generation_id,
                        day_result_id=result.day_result_id, previous_day_result_id=previous_id,
                        valuation_at=datetime.fromisoformat(prepared.accumulator["valuationAt"]), deadline=deadline)
            balance = session.get(CalculationBatch,
                (lease.account_id, generation_id, day, "CASH_BALANCE", "", "1"))
            if balance is None:
                raise CalculationInputMismatch("Completed date has no cash continuation")
            values = {"input": prepared.input_digest.hex(), "cash": balance.input_digest.hex(),
                "dayId": str(result.day_result_id) if result else None,
                "dayDigest": result.input_digest.hex() if result else None,
                "previous": latest.input_digest.hex() if latest else None}
            now = session.scalar(select(func.clock_timestamp()))
            session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=day, stage="DATE_COMPLETE", stock_key="", page_key="1", cursor={"done": True},
                accumulator=values, input_digest=sha256(self.inputs._encoded(values)).digest(),
                row_count=int(fact["is_open"]), completed_at=now))
            generation.last_business_updated_at = now
            return "DATE_COMPLETE"
