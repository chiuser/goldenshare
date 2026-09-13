"""One persisted account/date-page discovery unit, interleavable with work."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation, CalculationGeneration
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffDiscoveryCursor, CutoffPreparation
from .calculation_cutoff_targets import enqueue_confirmed_cutoff
from .calculation_inputs import CalculationDataUnavailable, CalculationInputMismatch
from .cutoff_preparation import AccountCutoffPreparation, CutoffPreparationInProgress
from .execution_policy import Deadline
from .market_facts import apply_sql_budget
from .discovery_interruptions import DiscoveryAttempt, checkpoint_stamp, record_discovery_failure


class CutoffDiscovery:
    def __init__(self, policy, sessions, *, purpose="CUTOFF"):
        if purpose not in ("CUTOFF", "HISTORY"):
            raise ValueError("Unknown account discovery purpose")
        self.policy, self.sessions = policy, sessions
        self.purpose = purpose

    def run_once(self):
        self._attempt = None
        try:
            return self._run_once()
        except Exception as error:
            return self.record_failure(error)

    def record_failure(self, error, *, sessions=None):
        """Called after rollback, including by App after a connection timeout."""
        if self._attempt is None:
            raise error
        return record_discovery_failure(sessions or self.sessions, self.policy, self._attempt, error)

    def _run_once(self):
        deadline = Deadline.after_ms(self.policy.batch_budget_ms)
        with self.sessions() as session, session.begin():
            apply_sql_budget(session, deadline, self.policy)
            now = session.scalar(select(func.clock_timestamp()))
            slot = 1 if self.purpose == "CUTOFF" else 2
            cursor = session.scalar(select(CutoffDiscoveryCursor).where(
                CutoffDiscoveryCursor.singleton_id == slot, CutoffDiscoveryCursor.next_attempt_at <= now)
                .with_for_update(skip_locked=True))
            if cursor is None:
                if session.get(CutoffDiscoveryCursor, slot) is None:
                    raise CalculationInputMismatch("Missing durable discovery cursor")
                return "IDLE"
            purpose = "DISCOVERY" if self.purpose == "CUTOFF" else "HISTORY"
            probe = CutoffPreparation
            eligible_probe = or_(probe.account_id.is_(None), and_(probe.state != "CHANGED",
                or_(probe.next_attempt_at <= now, and_(probe.next_attempt_at.is_(None), probe.state != "FAILED"))))
            query = select(Account).outerjoin(Recalculation, Recalculation.account_id == Account.account_id).outerjoin(
                probe, and_(probe.account_id == Account.account_id, probe.target_version == Account.calculation_target_version,
                    probe.purpose == purpose)).where(Account.published_generation_id.is_not(None),
                        Recalculation.account_id.is_(None), eligible_probe)
            needs_later_date = select(CalculationGeneration.generation_id).where(
                    CalculationGeneration.account_id == Account.account_id,
                    CalculationGeneration.generation_id == Account.published_generation_id,
                    CalculationGeneration.through_date < now.astimezone(ZoneInfo("Asia/Shanghai")).date()).exists()
            if self.purpose == "CUTOFF":
                query = query.where(needs_later_date)
            if cursor.after_account_id is not None:
                query = query.where(Account.account_id > cursor.after_account_id)
            account = session.scalar(query.order_by(Account.account_id).limit(1)
                .with_for_update(of=Account, skip_locked=True))
            if account is None:
                cursor.after_account_id = None
                retry_query = select(func.min(probe.next_attempt_at)).join(Account,
                    and_(Account.account_id == probe.account_id, Account.calculation_target_version == probe.target_version))
                retry_query = retry_query.outerjoin(Recalculation, Recalculation.account_id == Account.account_id).where(
                    probe.purpose == purpose, probe.next_attempt_at.is_not(None), probe.state != "CHANGED",
                    Account.published_generation_id.is_not(None), Recalculation.account_id.is_(None))
                if self.purpose == "CUTOFF":
                    retry_query = retry_query.where(needs_later_date)
                next_probe = session.scalar(retry_query)
                idle_until = now+timedelta(seconds=self.policy.data_probe_seconds)
                cursor.next_attempt_at = now if cursor.cycle_progress else min(idle_until, next_probe or idle_until)
                stage = "WRAP" if cursor.next_attempt_at <= now else "IDLE"
                cursor.cycle_progress = False
            else:
                target = account.calculation_target_version
                row = session.get(CutoffPreparation, (account.account_id, target, purpose))
                self._attempt = DiscoveryAttempt(account.account_id, target, purpose, slot,
                    cursor.after_account_id, checkpoint_stamp(row))
                try:
                    if self.purpose == "HISTORY":
                        from .history_source_preparation import HistorySourcePreparation
                        from .recalculation_execution import RecalculationExecution
                        stage = HistorySourcePreparation(RecalculationExecution(self.policy)).step(
                            session, account_id=account.account_id, deadline=deadline)
                        cursor.cycle_progress |= stage in ("PREPARING", "VERIFIED", "ENQUEUED")
                    else:
                        through = AccountCutoffPreparation(self.policy).resolve(session, account_id=account.account_id,
                            target_version=account.calculation_target_version, purpose="DISCOVERY", deadline=deadline)
                        changed = enqueue_confirmed_cutoff(session, account_id=account.account_id,
                            through_date=through, policy=self.policy, deadline=deadline)
                        cursor.cycle_progress |= changed
                        stage = "ENQUEUED" if changed else "UNCHANGED"
                except CutoffPreparationInProgress:
                    cursor.cycle_progress = True
                    stage = "PREPARING"
                except CalculationDataUnavailable:
                    stage = "WAITING_DATA"
                row = session.get(CutoffPreparation, (account.account_id, target, purpose))
                if row is not None:
                    row.transient_failure_count = 0
                    row.next_attempt_at = now+timedelta(seconds=self.policy.data_probe_seconds) if stage in (
                        "WAITING_DATA", "VERIFIED") else None
                cursor.after_account_id = account.account_id
            deadline.remaining_ms()
            session.flush()
            return stage
