"""Persist a classified interruption and scheduling decision atomically.

Call only after the failed calculation transaction has rolled back, in a fresh
short transaction. Unknown errors must not be guessed to be transient here.
"""
from datetime import timedelta

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
from .calculation_inputs import CalculationInputs, CalculationInputMismatch


class CalculationInterruptions:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)

    def record(self, session, lease, *, generation_id, kind, reason, deadline):
        if kind not in ("FAILED", "WAITING_DATA", "TRANSIENT"):
            raise ValueError("An explicit interruption classification is required")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A safe, nonempty interruption reason is required")
        self.inputs._encoded({"reason": reason})
        account, pending = self.execution._lock(session, lease, deadline)
        candidate = session.get(CalculationGeneration, generation_id, populate_existing=True)
        if candidate is None:
            raise CalculationInputMismatch("Missing generation")
        generation = self.inputs._generation(session, lease, account, generation_id, candidate.from_date,
            stages=("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING", "WAITING_DATA", "FAILED"))
        resume = generation.resume_stage if generation.stage in ("WAITING_DATA", "FAILED") else generation.stage
        if resume not in ("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING"):
            raise CalculationInputMismatch("Interrupted generation has no valid resume stage")
        now = session.scalar(select(func.clock_timestamp()))
        if kind == "FAILED":
            next_attempt = None
        elif kind == "WAITING_DATA":
            next_attempt = now + timedelta(seconds=self.execution.policy.data_probe_seconds)
        else:
            pending.transient_failure_count += 1
            delays = self.execution.policy.transient_retry_delays_seconds
            next_attempt = now + timedelta(seconds=delays[min(pending.transient_failure_count, len(delays)) - 1])
        stage = "WAITING_DATA" if kind == "WAITING_DATA" else "FAILED"
        changed = (generation.stage, generation.resume_stage, generation.reason) != (stage, resume, reason)
        generation.resume_stage = resume
        generation.stage = stage
        generation.reason = reason
        if changed:
            generation.last_business_updated_at = now
        pending.next_attempt_at = next_attempt
        pending.updated_at = now
        session.flush()
        self.execution._verify(session, lease, account, pending, deadline)
        pending.executor_id = None
        pending.lease_until = None
        session.flush()
        return next_attempt
