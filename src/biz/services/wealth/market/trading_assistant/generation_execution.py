"""Execute one input or calculation unit with owned Sessions and durable failure.

No loop or automatic input discovery. A caller claims one lease, calls run,
then returns to fair scheduling. Session factories must target the same database.
"""
from sqlalchemy.exc import DBAPIError

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
from .calculation_inputs import CalculationInputMismatch, CalculationDataUnavailable
from .calculation_interruptions import CalculationInterruptions
from .execution_policy import Deadline
from .generation_publication import GenerationPublication
from .generation_steps import GenerationSteps
from .market_facts import MarketFactsUnavailable, apply_sql_budget
from .recalculation_execution import CalculationExecutionLost


class GenerationExecution:
    def __init__(self, execution, sessions):
        self.execution = execution
        self.sessions = sessions

    def run(self, lease, *, generation_id):
        return self._execute(lease, generation_id=generation_id, prepare=None)

    def prepare_inputs(self, lease, *, generation_id, business_date, fee_version_id, valuation_at):
        """Prepare one bounded page under the same failure/lease rules as calculation.

        Date-specific fee and cutoff remain selected by the source adapter, not
        by this transaction owner. Already frozen inputs cannot be replaced.
        """
        return self._execute(lease, generation_id=generation_id, prepare=dict(
            business_date=business_date, fee_version_id=fee_version_id, valuation_at=valuation_at))

    def _execute(self, lease, *, generation_id, prepare):
        owner_id = None
        try:
            with self.sessions() as session, session.begin():
                deadline = Deadline.after_ms(self.execution.policy.batch_budget_ms)
                account, pending = self.execution._lock(session, lease, deadline)
                owner_id = account.owner_id
                generation = session.get(CalculationGeneration, generation_id, populate_existing=True)
                if generation is None:
                    raise CalculationInputMismatch("Missing generation")
                steps = GenerationSteps(self.execution)
                steps.inputs._generation(session, lease, account, generation_id, generation.from_date,
                    stages=("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING", "FAILED", "WAITING_DATA"))
                if generation.stage in ("FAILED", "WAITING_DATA"):
                    if generation.resume_stage not in ("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING"):
                        raise CalculationInputMismatch("Invalid interrupted stage")
                    # Restoration and the revalidated unit commit together. Any
                    # error rolls both back, preserving the prior failure state.
                    generation.stage = generation.resume_stage
                    generation.resume_stage = None
                    generation.reason = None
                    session.flush()
                if prepare is None:
                    stage = steps.advance(session, lease, generation_id=generation_id, deadline=deadline)
                else:
                    stage = steps.prepare_next_inputs(session, lease, generation_id=generation_id,
                        deadline=deadline, **prepare)
                if stage != "PUBLISHED":
                    pending.transient_failure_count = 0
                    self.execution.release(session, lease, deadline=deadline)
            return stage
        except CalculationExecutionLost:
            raise
        except Exception as error:
            # If the commit reply was lost, publication may already be complete.
            if owner_id is not None:
                with self.sessions() as session:
                    apply_sql_budget(session, Deadline.after_ms(self.execution.policy.batch_budget_ms),
                                     self.execution.policy)
                    if GenerationPublication.confirmed(session, owner_id=owner_id,
                            account_id=lease.account_id, generation_id=generation_id,
                            target_version=lease.target_version):
                        return "PUBLISHED"
            kind, reason = "FAILED", "本次核算核验未通过，已停止自动重试。"
            if isinstance(error, (MarketFactsUnavailable, CalculationDataUnavailable)):
                kind, reason = "WAITING_DATA", "核算所需行情或交易日历暂未就绪。"
            elif isinstance(error, DBAPIError):
                state = getattr(error.orig, "sqlstate", None)
                if state in ("40001", "40P01", "55P03", "57014") or (
                        isinstance(state, str) and state.startswith("08")):
                    kind, reason = "TRANSIENT", "数据库暂时不可用，稍后重试。"
            with self.sessions() as session, session.begin():
                next_attempt = CalculationInterruptions(self.execution).record(session, lease,
                    generation_id=generation_id, kind=kind, reason=reason,
                    deadline=Deadline.after_ms(self.execution.policy.batch_budget_ms))
            return "FAILED" if next_attempt is None else kind
