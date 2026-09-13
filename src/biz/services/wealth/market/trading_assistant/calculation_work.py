"""Claim one account and perform one unit; no lifecycle or discovery loop."""
from datetime import date, timedelta

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
from .calculation_inputs import CalculationInputs, CalculationDataUnavailable, CalculationInputMismatch
from .execution_policy import Deadline
from .generation_execution import GenerationExecution
from .recalculation_execution import CalculationExecutionLost
from .cutoff_preparation import CutoffPreparationInProgress
from .calculation_failures import classify_calculation_failure
from .calculation_interruptions import CalculationInterruptions
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation


class CalculationWork:
    def __init__(self, execution, sessions, *, rule_version, resolve_through_date):
        if type(rule_version) is not int or not 1 <= rule_version <= 9223372036854775807:
            raise ValueError("An explicit calculation rule version is required")
        self.execution = execution
        self.sessions = sessions
        self.rule_version = rule_version
        if not callable(resolve_through_date):
            raise ValueError("A trusted account cutoff resolver is required")
        self.resolve_through_date = resolve_through_date
        self._lease = self._generation_id = None

    def run_once(self, *, executor_id):
        """A fixed calendar window may wait for prices; it is not published data.

        If creation/claim loses its commit reply, propagate the failure: durable
        state is inspected on the next claim after release or lease expiration.
        Never recreate account facts or invent a second generation for a target.
        """
        deadline = Deadline.after_ms(self.execution.policy.batch_budget_ms)
        self._lease = self._generation_id = None
        with self.sessions() as session, session.begin():
            lease = self.execution.claim(session, executor_id=executor_id,
                deadline=deadline)
        if lease is None:
            return "IDLE"
        self._lease = lease
        generation_id = None
        try:
            with self.sessions() as session, session.begin():
                account, pending = self.execution._lock(session, lease, deadline)
                generation = session.scalar(select(CalculationGeneration).where(
                    CalculationGeneration.account_id == lease.account_id,
                    CalculationGeneration.target_version == lease.target_version))
                generation_id = generation.generation_id if generation is not None else None
                self._generation_id = generation_id
                if generation is not None and generation.rule_version != self.rule_version:
                    raise CalculationInputMismatch("Calculation rule version differs from the stored generation")
                if generation_id is None:
                    try:
                        through = self.resolve_through_date(session, account_id=lease.account_id,
                            target_version=lease.target_version, deadline=deadline)
                        if type(through) is not date:
                            raise ValueError("The confirmed cutoff must be a business date")
                        CalculationInputs(self.execution).prepare_from_initialization(session, lease,
                            through_date=through, rule_version=self.rule_version, deadline=deadline)
                    except CutoffPreparationInProgress:
                        self.execution.release(session, lease, deadline=deadline)
                        return "PREPARING"
                    except CalculationDataUnavailable:
                        # No generation exists yet. Keep the accepted account
                        # and pending target; do not invent a future range.
                        now = session.scalar(select(func.clock_timestamp()))
                        pending.next_attempt_at = now + timedelta(seconds=self.execution.policy.data_probe_seconds)
                        self.execution.release(session, lease, deadline=deadline)
                        return "WAITING_DATA"
                    self.execution.release(session, lease, deadline=deadline)
                    return "GENERATION"
            return GenerationExecution(self.execution, self.sessions).step_from_market(
                lease, generation_id=generation_id, deadline=deadline)
        except CalculationExecutionLost:
            # A later accepted target or another owner will continue. Do not
            # write an error onto that new target with this stale lease.
            return "SUPERSEDED"
        except Exception as error:
            return self.record_failure(error)

    def record_failure(self, error, *, sessions=None):
        # Also callable with a fresh connection after App cancels a timed-out
        # connection. Never carry the failed Session across this boundary.
        lease, generation_id = self._lease, self._generation_id
        if lease is None:
            raise error
        try:
            kind, reason = classify_calculation_failure(error)
            deadline = Deadline.after_ms(self.execution.policy.batch_budget_ms)
            with (sessions or self.sessions)() as session, session.begin():
                account, pending = self.execution._lock(session, lease, deadline)
                interruptions = CalculationInterruptions(self.execution)
                if generation_id is not None:
                    next_attempt = interruptions.record(session, lease, generation_id=generation_id,
                        kind=kind, reason=reason, deadline=deadline)
                else:
                    committed = session.scalar(select(CalculationGeneration).where(
                        CalculationGeneration.account_id == lease.account_id,
                        CalculationGeneration.target_version == lease.target_version))
                    if committed is not None:
                        if (committed.fact_version != account.fact_version
                                or committed.initialization_id != account.current_initialization_id
                                or committed.rule_version != self.rule_version):
                            raise CalculationInputMismatch("Uncertain generation commit has incompatible inputs")
                        self.execution.release(session, lease, deadline=deadline)
                        return "GENERATION"
                    now = session.scalar(select(func.clock_timestamp()))
                    next_attempt, reason = interruptions.schedule(pending, kind=kind, reason=reason, now=now)
                    row = session.get(CutoffPreparation, (lease.account_id, lease.target_version, "INITIAL"))
                    if row is not None:
                        row.state = "WAITING_DATA" if kind == "WAITING_DATA" else "FAILED"
                        row.reason, row.updated_at = reason, now
                    self.execution.release(session, lease, deadline=deadline)
            return "FAILED" if next_attempt is None else kind
        except CalculationExecutionLost:
            return "SUPERSEDED"
