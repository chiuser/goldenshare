"""Persist one account's discovery failure after its failed unit rolls back."""
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo
from uuid import UUID

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation, CutoffDiscoveryCursor
from .calculation_failures import classify_calculation_failure
from .calculation_inputs import CalculationInputMismatch
from .calculation_interruptions import CalculationInterruptions
from .execution_policy import Deadline
from .market_facts import apply_sql_budget
from .recalculation_execution import RecalculationExecution


def checkpoint_stamp(row):
    return (row.current_date, row.after_stock, row.state, row.updated_at) if row else None


@dataclass(frozen=True, slots=True)
class DiscoveryAttempt:
    account_id: UUID
    target_version: int
    purpose: str
    slot: int
    previous_account: UUID | None
    checkpoint: tuple | None


def record_discovery_failure(sessions, policy, attempt, error):
    deadline = Deadline.after_ms(policy.batch_budget_ms)
    kind, reason = classify_calculation_failure(error)
    with sessions() as session, session.begin():
        apply_sql_budget(session, deadline, policy)
        cursor = session.scalar(select(CutoffDiscoveryCursor).where(CutoffDiscoveryCursor.singleton_id == attempt.slot)
            .with_for_update().execution_options(populate_existing=True))
        if cursor is None:
            raise CalculationInputMismatch("Missing discovery cursor during failure recording")
        if cursor.after_account_id != attempt.previous_account:
            return "SUPERSEDED"
        account = session.scalar(select(Account).where(Account.account_id == attempt.account_id)
            .with_for_update().execution_options(populate_existing=True))
        if (account is None or account.calculation_target_version != attempt.target_version
                or session.get(Recalculation, attempt.account_id) is not None):
            return "SUPERSEDED"
        row = session.get(CutoffPreparation, (attempt.account_id, attempt.target_version, attempt.purpose))
        if checkpoint_stamp(row) != attempt.checkpoint:
            return "SUPERSEDED"
        now = session.scalar(select(func.clock_timestamp()))
        if row is None:
            source = session.get(CalculationGeneration, account.published_generation_id) if account.published_generation_id else None
            if source is None or source.account_id != account.account_id or source.stage != "PUBLISHED":
                raise CalculationInputMismatch("Cannot attach a failure to an invalid publication")
            start = source.from_date if attempt.purpose == "HISTORY" else source.through_date+timedelta(days=1)
            row = CutoffPreparation(account_id=account.account_id, target_version=attempt.target_version,
                purpose=attempt.purpose, fact_version=account.fact_version, initialization_id=account.current_initialization_id,
                from_date=start, current_date=start, scan_through_date=source.through_date if attempt.purpose == "HISTORY"
                    else max(start, now.astimezone(ZoneInfo("Asia/Shanghai")).date()),
                state="SCANNING", transient_failure_count=0, updated_at=now)
            session.add(row)
        if row.evidence is not None:
            return "SUPERSEDED"
        next_attempt, reason = CalculationInterruptions(RecalculationExecution(policy)).schedule(
            row, kind=kind, reason=reason, now=now)
        if next_attempt is None:
            reason = "账户来源检查未通过，已暂停自动检查，待维护核验。"
        row.state = "WAITING_DATA" if kind == "WAITING_DATA" else "FAILED"
        row.reason = reason
        cursor.after_account_id = account.account_id
        deadline.remaining_ms()
        session.flush()
        return "FAILED" if next_attempt is None else kind
