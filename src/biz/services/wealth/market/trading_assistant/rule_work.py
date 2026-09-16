"""One resumable rule unit on the shared App execution resource (§11.15).

Transactions are short: claim; plan or freeze; one frozen batch. Source I/O is
outside the rule lock. A unit never sends a message or changes account facts.
"""
from datetime import datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import func, select, text
from src.biz.models.wealth.trading_assistant.rule_checks import RuleCheck, RuleCheckProgress, RuleMarketBasis
from src.foundation.clients.local_lake.stock_mins_reader import MinuteQueryError
from .execution_policy import Deadline, DeadlineExceeded
from .market_facts import MarketFactsReader, MarketFactsUnavailable
from .rule_execution import RuleExecutionStore, RuleExecutionLost
from .rule_work_target import next_target, required_minutes
from .rule_calendar import BEIJING
from .rule_frozen_basis import freeze_basis, read_frozen_minutes
from .rule_minute_batch import MinuteScanProgress, evaluate_minute_batch
from .rule_publication import publish_rule_result


class RuleWork:
    def __init__(self, policy, sessions, *, minute_reader):
        self.policy, self.sessions, self.minute_reader = policy, sessions, minute_reader
        self.store, self.market = RuleExecutionStore(policy), MarketFactsReader(policy)
        self.lease = self.target = self.check_id = None

    def run_once(self, *, executor_id):
        self.deadline = Deadline.after_ms(self.policy.batch_budget_ms)
        try:
            with self.sessions.begin() as session:
                self.lease = self.store.claim(session, executor_id=executor_id, deadline=self.deadline)
            if self.lease is None:
                return "IDLE"
            with self.sessions.begin() as session:
                with self.store.batch(session, self.lease, deadline=self.deadline) as (rule, execution):
                    now = session.scalar(select(func.clock_timestamp()))
                    self.target = next_target(session, rule, execution, deadline=self.deadline, policy=self.policy)
                    if self.target is None:
                        from src.biz.models.wealth.trading_assistant.rules import RuleVersion
                        end = session.get(RuleVersion, rule.current_version_id).deadline_at.astimezone(BEIJING).date()
                        if execution.next_trade_date <= end:
                            execution.next_trade_date += timedelta(days=1)
                        execution.last_business_updated_at = now
                    else:
                        close = datetime.combine(self.target.day, time(15), tzinfo=BEIJING)
                        if now < close:
                            execution.next_attempt_at = close
                            deferred = True
                        else:
                            deferred = False
                            self.check_id = session.scalar(select(RuleCheck.check_id).where(
                                RuleCheck.rule_id == rule.rule_id, RuleCheck.rule_version_id == self.target.version_id,
                                RuleCheck.trade_date == self.target.day, RuleCheck.requested_from == self.target.interval.after,
                                RuleCheck.requested_through == self.target.interval.through,
                                RuleCheck.status == "CHECKING").order_by(RuleCheck.check_no.desc()).limit(1))
            if self.target is None:
                return self._advance_or_publish()
            if deferred:
                return self._release("UNCHANGED")
            if self.check_id is not None:
                return self._evaluate()
            return self._prepare(now)
        except RuleExecutionLost:
            return "SUPERSEDED"
        except DeadlineExceeded:
            raise
        except Exception as error:
            return self.record_failure(error)

    def _advance_or_publish(self):
        from src.biz.models.wealth.trading_assistant.rules import RuleVersion
        with self.sessions.begin() as session:
            rule, execution = self.store._lock(session, self.lease, self.deadline)
            version = session.get(RuleVersion, rule.current_version_id)
            now = session.scalar(select(func.clock_timestamp()))
            if execution.next_trade_date > version.deadline_at.astimezone(BEIJING).date() and now >= version.deadline_at:
                publish_rule_result(session, self.store, self.lease, deadline=self.deadline)
                return "PUBLISHED"
            if execution.next_trade_date > version.deadline_at.astimezone(BEIJING).date():
                execution.next_attempt_at = version.deadline_at
            self.store.release(session, self.lease, deadline=self.deadline)
        return "ADVANCED"

    def _prepare(self, now):
        target = self.target
        # Calendar and suspension facts are read before external file I/O.
        with self.sessions.begin() as session:
            security = self.market.resolve_security(session, target.stock_code, self.deadline)
            calendar = self.market.read_calendar(session, security.exchange, target.day, target.day, self.deadline)
            suspensions = session.execute(text("""SELECT suspend_type, suspend_timing FROM core_serving.equity_suspend_d
                WHERE ts_code=:code AND trade_date=:day ORDER BY suspend_type, suspend_timing LIMIT :limit"""),
                dict(code=target.stock_code, day=target.day, limit=self.policy.page_rows + 1)).all()
        if len(suspensions) > self.policy.page_rows:
            raise ValueError("Suspension evidence exceeds the bounded page")
        full_suspend = bool(suspensions) and all(kind == "S" and timing is None for kind, timing in suspensions)
        required = required_minutes(target, is_open=calendar.days[0].is_open, full_day_suspended=full_suspend)
        evidence = dict(calendarVersion=calendar.source_version, isOpen=calendar.days[0].is_open,
            calendarExchange=calendar.calendar_exchange, fullDaySuspended=full_suspend,
            suspensionSource="core_serving.equity_suspend_d", suspensions=[list(row) for row in suspensions])
        source = None
        if required:
            if self.minute_reader is None:
                raise MarketFactsUnavailable("分钟行情能力尚不可用")
            source = self.minute_reader.read_day(stock_code=target.stock_code, trade_date=target.day,
                row_limit=self.policy.page_rows, byte_limit=self.policy.page_bytes, remaining_ms=self.deadline.remaining_ms)
        with self.sessions.begin() as session:
            with self.store.batch(session, self.lease, deadline=self.deadline) as (rule, execution):
                basis = freeze_basis(session, target, required=required, source=source, session_evidence=evidence,
                    now=now, policy=self.policy, deadline=self.deadline)
                check = self._new_check(session, rule, "CHECKING", now, basis.market_basis_id)
                session.add(RuleCheckProgress(check_id=check.check_id, market_basis_id=basis.market_basis_id,
                    cursor={}, cumulative_volume_shares=0, processed_rows=0, updated_at=now))
                execution.last_business_updated_at = now
                execution.waiting_reason = None
        return self._release("PREPARED")

    def _new_check(self, session, rule, status, now, basis_id=None):
        rule.last_check_no += 1
        target = self.target
        check = RuleCheck(check_id=uuid4(), owner_user_id=rule.owner_user_id, rule_id=rule.rule_id,
            rule_version_id=target.version_id, check_no=rule.last_check_no, trade_date=target.day,
            requested_from=target.interval.after, requested_through=target.interval.through, started_at=now,
            status=status, missing_ranges=[], market_basis_id=basis_id, evaluator_version="TA_RULE_V1",
            execution_fence=self.lease.fence)
        session.add(check)
        session.flush()
        self.check_id = check.check_id
        return check

    def _evaluate(self):
        with self.sessions.begin() as session:
            rule, execution = self.store._lock(session, self.lease, self.deadline)
            check = session.get(RuleCheck, self.check_id)
            basis = session.get(RuleMarketBasis, check.market_basis_id)
            progress = session.get(RuleCheckProgress, check.check_id)
            after = datetime.fromisoformat(progress.cursor["after"]) if progress.cursor.get("after") else None
            required, facts = read_frozen_minutes(basis, after=after, limit=self.policy.page_rows, deadline=self.deadline)
            result = evaluate_minute_batch(basis_id=str(basis.market_basis_id), trade_date=self.target.day,
                condition=self.target.conditions, interval=self.target.interval, required=required, facts=facts,
                progress=MinuteScanProgress(str(basis.market_basis_id), self.target.day, after,
                    int(progress.cumulative_volume_shares) if progress.cumulative_volume_shares is not None else None,
                    progress.processed_rows), policy=self.policy, deadline=self.deadline)
            now = session.scalar(select(func.clock_timestamp()))
            progress.cursor = dict(after=result.progress.last_at.isoformat() if result.progress.last_at else None)
            progress.cumulative_volume_shares = result.progress.cumulative_shares
            progress.processed_rows, progress.updated_at = result.progress.processed_rows, now
            if result.progress.last_at is not None and self.target.interval.contains(result.progress.last_at):
                progress.last_checkpoint_at = check.checked_through_at = result.progress.last_at
            execution.last_business_updated_at = now
            match = result.match
            if result.waiting_at is not None:
                check.status = "WAITING_DATA"
                check.missing_ranges = [{"from": result.waiting_at.isoformat(), "through": result.waiting_at.isoformat()}]
                execution.next_attempt_at = now + timedelta(seconds=self.policy.data_probe_seconds)
                execution.waiting_reason = "分钟行情尚不完整"
                outcome = "WAITING_DATA"
            elif match is not None or result.progress.processed_rows == len(basis.coverage["required"]):
                check.status, check.completed_at = "COMPLETED", now
                if match:
                    progress.first_match_at, progress.first_match_price = match.at, match.price
                    progress.first_match_cumulative_shares = match.cumulative_shares
                    progress.price_satisfied, progress.volume_satisfied = match.evaluation.price_satisfied, match.evaluation.volume_satisfied
                execution.transient_failures = 0
                outcome = "COMPLETED"
            else:
                outcome = "ADVANCED"
            session.flush()
            self.store._verify(session, self.lease, rule, execution, self.deadline)
            if match:
                publish_rule_result(session, self.store, self.lease, deadline=self.deadline, check=check, match=match)
                return "PUBLISHED"
            self.store.release(session, self.lease, deadline=self.deadline)
            return outcome

    def _release(self, outcome):
        with self.sessions.begin() as session:
            self.store.release(session, self.lease, deadline=self.deadline)
        return outcome

    def record_failure(self, error, *, sessions=None):
        if self.lease is None:
            raise error
        sessions = sessions or self.sessions
        self.deadline = Deadline.after_ms(self.policy.batch_budget_ms)
        try:
            with sessions.begin() as session:
                with self.store.batch(session, self.lease, deadline=self.deadline) as (rule, execution):
                    now = session.scalar(select(func.clock_timestamp()))
                    waiting = isinstance(error, (MarketFactsUnavailable, MinuteQueryError))
                    status = "WAITING_DATA" if waiting else "FAILED"
                    check = session.get(RuleCheck, self.check_id) if self.check_id else None
                    if check is None and self.target is not None:
                        check = self._new_check(session, rule, status, now)
                    if check is not None and check.status != "COMPLETED":
                        check.status = status
                        check.failure_reason = "尚未取得完整行情依据" if waiting else "本次验证未完成"
                    execution.waiting_reason = "尚未取得完整行情依据" if waiting else "本次验证未完成"
                    if waiting:
                        execution.next_attempt_at = now + timedelta(seconds=self.policy.data_probe_seconds)
                    else:
                        execution.transient_failures += 1
                        delays = self.policy.transient_retry_delays_seconds
                        execution.next_attempt_at = now + timedelta(seconds=delays[execution.transient_failures - 1]) if execution.transient_failures <= len(delays) else None
                self.store.release(session, self.lease, deadline=self.deadline)
            return "WAITING_DATA" if waiting else "FAILED"
        except RuleExecutionLost:
            return "SUPERSEDED"
