"""Schedule a confirmed later cutoff without mutating a published generation.

The source-discovery caller owns the short transaction and its durable cursor.
This is not a source readiness detector: a date/max(row.date) is no proof that
all account inputs are ready. Do not expose this method as a user command.
"""
from datetime import date, timedelta

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.publication import PublicationReceipt
from .calculation_inputs import CalculationInputMismatch
from .market_facts import apply_sql_budget


def enqueue_confirmed_cutoff(session, *, account_id, through_date, policy, deadline):
    if type(through_date) is not date:
        raise ValueError("A confirmed cutoff date is required")
    apply_sql_budget(session, deadline, policy)
    account = session.scalar(select(Account).where(Account.account_id == account_id)
        .with_for_update().execution_options(populate_existing=True))
    if account is None:
        raise CalculationInputMismatch("Missing account for cutoff discovery")
    pending = session.get(Recalculation, account_id, populate_existing=True)
    if pending is not None:
        if pending.target_version != account.calculation_target_version:
            raise CalculationInputMismatch("Account and pending target differ")
        # Facts/corrections take precedence; finish that immutable window first.
        # Discovery revisits the account, so this must not be treated as a
        # permanent acknowledgement that the new cutoff has been calculated.
        return False
    generation = session.get(CalculationGeneration, account.published_generation_id) if account.published_generation_id else None
    receipt = session.get(PublicationReceipt, (account_id, account.published_generation_id)) if generation else None
    if (generation is None or generation.account_id != account_id or generation.stage != "PUBLISHED"
            or generation.target_version != account.calculation_target_version
            or generation.fact_version != account.fact_version
            or generation.initialization_id != account.current_initialization_id
            or receipt is None or receipt.target_version != generation.target_version):
        raise CalculationInputMismatch("Cutoff advance requires an intact current publication")
    if through_date <= generation.through_date:
        return False
    account.calculation_target_version += 1
    now = session.scalar(select(func.clock_timestamp()))
    session.add(Recalculation(account_id=account_id, target_version=account.calculation_target_version,
        affected_from_date=generation.through_date+timedelta(days=1), next_attempt_at=now,
        fence=0, transient_failure_count=0, updated_at=now))
    deadline.remaining_ms()
    session.flush()
    return True
