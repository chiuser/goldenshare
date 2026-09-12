"""Select one durable generation unit; no in-memory progress or market clock."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from .calculation_inputs import CalculationInputMismatch


@dataclass(frozen=True, slots=True)
class DayInputBasis:
    fee_version_id: UUID
    valuation_at: datetime


class GenerationDispatch:
    def __init__(self, steps, resolve_day_inputs):
        self.steps = steps
        self.resolve_day_inputs = resolve_day_inputs

    def step(self, session, lease, *, generation, deadline):
        """Resolve new inputs only once; frozen pages win on every later claim.

        The injected resolver takes session/account/date/deadline, not request
        data. It must supply confirmed inputs or raise data-unavailable. It
        neither runs another unit nor chooses the next business date.
        """
        args = dict(generation_id=generation.generation_id, deadline=deadline)
        if generation.total_trade_date_count is None or generation.stage in ("VERIFYING", "PUBLISHING"):
            return self.steps.advance(session, lease, **args)
        latest = session.scalar(select(CalculationBatch).where(
            CalculationBatch.account_id == lease.account_id,
            CalculationBatch.generation_id == generation.generation_id,
            CalculationBatch.stage == "DATE_COMPLETE", CalculationBatch.stock_key == "")
            .order_by(CalculationBatch.trade_date.desc()).limit(1))
        if latest is not None:
            self.steps._verify_completed(session, lease, generation, latest)
        day = latest.trade_date + timedelta(days=1) if latest else generation.from_date
        if day > generation.through_date:
            return self.steps.advance(session, lease, **args)
        identity = (lease.account_id, generation.generation_id, day)
        if session.get(CalculationBatch, (*identity, "DATE_INPUT", "", "1")) is not None:
            return self.steps.advance(session, lease, **args)
        # A saved page includes actual values and its fee/cutoff. Do not call
        # the live resolver again after a restart or an account fee change.
        page = session.scalar(select(CalculationBatch.page_key).where(
            CalculationBatch.account_id == lease.account_id,
            CalculationBatch.generation_id == generation.generation_id,
            CalculationBatch.trade_date == day, CalculationBatch.stage == "VALUATION",
            CalculationBatch.stock_key == "").order_by(CalculationBatch.page_key.desc()).limit(1))
        terminal = session.get(CalculationBatch, (*identity, "VALUATION_END", "", "1"))
        if page is not None:
            frozen = self.steps.inputs.read_valuation_page(session, lease, trade_date=day,
                page_key=page, **args)
            basis = DayInputBasis(frozen.fee_version_id, frozen.valuation_at)
        elif terminal is not None:
            # Empty stock scope still binds a fee/cutoff. prepare_next_inputs
            # below verifies the terminal's full digest and preceding day.
            basis = DayInputBasis(UUID(terminal.accumulator["feeVersionId"]),
                datetime.fromisoformat(terminal.accumulator["valuationAt"]))
        else:
            basis = self.resolve_day_inputs(session, account_id=lease.account_id,
                business_date=day, deadline=deadline)
        if (not isinstance(basis, DayInputBasis) or not isinstance(basis.fee_version_id, UUID)
                or not isinstance(basis.valuation_at, datetime)
                or basis.valuation_at.tzinfo is None or basis.valuation_at.utcoffset() is None):
            raise CalculationInputMismatch("Invalid resolved day inputs")
        return self.steps.prepare_next_inputs(session, lease, business_date=day,
            fee_version_id=basis.fee_version_id, valuation_at=basis.valuation_at, **args)
