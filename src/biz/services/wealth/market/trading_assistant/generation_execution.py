"""Execute one input or calculation unit with owned Sessions and durable failure.

No loop or automatic input discovery. A caller claims one lease, calls run,
then returns to fair scheduling. Session factories must target the same database.
"""
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
from .calculation_inputs import CalculationInputMismatch
from .calculation_interruptions import CalculationInterruptions
from .execution_policy import Deadline
from .generation_publication import GenerationPublication
from .generation_steps import GenerationSteps
from .generation_dispatch import DayInputBasis, GenerationDispatch
from .valuation_fee_selection import valuation_fee_version
from .valuation_clock import read_valuation_cutoff
from .market_facts import apply_sql_budget
from .recalculation_execution import CalculationExecutionLost
from .calculation_failures import classify_calculation_failure


class GenerationExecution:
    def __init__(self, execution, sessions):
        self.execution = execution
        self.sessions = sessions

    def run(self, lease, *, generation_id):
        return self._execute(lease, generation_id=generation_id, prepare=None)

    def step(self, lease, *, generation_id, resolve_day_inputs, deadline=None):
        """Choose one next unit from committed state, within its owned transaction."""
        return self._execute(lease, generation_id=generation_id, prepare=None,
                             resolve_day_inputs=resolve_day_inputs, deadline=deadline)

    def step_with_valuation_cutoff(self, lease, *, generation_id, resolve_valuation_at, deadline=None):
        """Source supplies only the cutoff; the account service owns fee selection."""
        def resolve(session, *, account_id, business_date, deadline):
            cutoff = resolve_valuation_at(session, account_id=account_id,
                business_date=business_date, deadline=deadline)
            fee_id = valuation_fee_version(session, self.execution, lease,
                generation_id=generation_id, business_date=business_date, deadline=deadline)
            return DayInputBasis(fee_id, cutoff)
        return self.step(lease, generation_id=generation_id, resolve_day_inputs=resolve, deadline=deadline)

    def step_from_market(self, lease, *, generation_id, deadline=None):
        """Frozen calendar + database time + existing account-scoped price reader.

        Passing the close-time check alone never permits publication. The
        existing valuation scope and all day/manifest checks still run.
        """
        def cutoff(session, *, account_id, business_date, deadline):
            return read_valuation_cutoff(session, self.execution, lease,
                generation_id=generation_id, business_date=business_date, deadline=deadline)
        return self.step_with_valuation_cutoff(lease, generation_id=generation_id,
            resolve_valuation_at=cutoff, deadline=deadline)

    def prepare_inputs(self, lease, *, generation_id, business_date, fee_version_id, valuation_at):
        """Prepare one bounded page under the same failure/lease rules as calculation.

        Date-specific fee and cutoff remain selected by the source adapter, not
        by this transaction owner. Already frozen inputs cannot be replaced.
        """
        return self._execute(lease, generation_id=generation_id, prepare=dict(
            business_date=business_date, fee_version_id=fee_version_id, valuation_at=valuation_at))

    def _execute(self, lease, *, generation_id, prepare, resolve_day_inputs=None, deadline=None):
        owner_id = None
        try:
            with self.sessions() as session, session.begin():
                deadline = deadline or Deadline.after_ms(self.execution.policy.batch_budget_ms)
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
                if resolve_day_inputs is not None:
                    stage = GenerationDispatch(steps, resolve_day_inputs).step(session, lease,
                        generation=generation, deadline=deadline)
                elif prepare is None:
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
            kind, reason = classify_calculation_failure(error)
            with self.sessions() as session, session.begin():
                next_attempt = CalculationInterruptions(self.execution).record(session, lease,
                    generation_id=generation_id, kind=kind, reason=reason,
                    deadline=Deadline.after_ms(self.execution.policy.batch_budget_ms))
            return "FAILED" if next_attempt is None else kind
