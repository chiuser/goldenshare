"""Fixed revision cash pages, crash/retry and weekend facts on isolated PG."""
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, deadline, retire
from tests.test_wealth_trading_assistant_persistence import seed_account
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.queries.wealth.market.trading_assistant.calculation_cash import cash_day_page
from src.biz.services.wealth.market.trading_assistant.calculation.cash_day import CashDayTotals
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputs, CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.cash_day_batches import CashDayBatches
from src.biz.services.wealth.market.trading_assistant.cash_balances import CashBalances
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution

SATURDAY = date(2026, 9, 12)
SUNDAY = date(2026, 9, 13)


def test_revisions_cash_pages_and_restart(migrated):
    now = datetime.now(timezone.utc)
    with migrated.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(update(Account).where(Account.account_id == account).values(initialized_on=SATURDAY, fact_version=7))
        source = []
        for version, (direction, amount) in enumerate((("OUT", 200), ("IN", 1000), ("IN", 300), ("IN", 50)), 2):
            identity = UUID(int=(account.int & ~65535) + version)
            conn.execute(insert(Ledger).values(ledger_id=identity, account_id=account, kind="CASH_FLOW", created_at=now))
            values = dict(ledger_id=identity, account_id=account, kind="CASH_FLOW", revision=1,
                accepted_fact_version=version, occurred_on=SATURDAY, status="ACTIVE", accepted_at=now,
                direction=direction, cash_amount=amount, net_cash_change=amount if direction == "IN" else -amount)
            conn.execute(insert(LedgerRevision).values(**values))
            source.append(values)
        conn.execute(insert(LedgerRevision).values(**(source[2] | dict(revision=2, source_revision=1,
            accepted_fact_version=6, occurred_on=SUNDAY))))
        conn.execute(insert(LedgerRevision).values(**(source[3] | dict(revision=2, source_revision=1,
            accepted_fact_version=7, status="VOID"))))
        conn.execute(insert(Recalculation).values(account_id=account, target_version=1,
            affected_from_date=SATURDAY, next_attempt_at=now, fence=0, transient_failure_count=0, updated_at=now))
    execution = RecalculationExecution(replace(TradingAssistantExecutionPolicyV1(), page_rows=1))
    with Session(migrated) as session, session.begin():
        lease = execution.claim(session, executor_id="cash", deadline=deadline())
        generation = CalculationInputs(execution).prepare_generation(session, lease, from_date=SATURDAY,
            through_date=SUNDAY, rule_version=1, deadline=deadline())
    args = dict(generation_id=generation, business_date=SATURDAY)
    service = CashDayBatches(execution)
    with pytest.raises(CalculationInputMismatch, match="unprocessed"):
        with Session(migrated) as session, session.begin():
            service.completed_totals(session, lease, **args, deadline=deadline())
    with Session(migrated) as session, session.begin():
        assert not service.reduce_page(session, lease, **args, deadline=deadline())
        partial = service._latest(session, lease, generation, SATURDAY)
        assert partial.accumulator["cash_out_cents"] == "20000"
        assert partial.accumulator["cash_in_cents"] == "0"  # Do not reject a partial day's negative net.
    with pytest.raises(RuntimeError, match="crash"):
        with Session(migrated) as session, session.begin():
            service.reduce_page(session, lease, **args, deadline=deadline())
            raise RuntimeError("crash")
    restarted = CashDayBatches(execution)
    for expected in (False, True, True):
        with Session(migrated) as session, session.begin():
            assert restarted.reduce_page(session, lease, **args, deadline=deadline()) == expected
    with Session(migrated) as session, session.begin():
        totals = restarted.completed_totals(session, lease, **args, deadline=deadline())
        assert totals == CashDayTotals(100000, 20000, 0, 0, 2, 0)
        assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
            CalculationBatch.generation_id == generation)) == 3
        assert session.scalar(select(func.count()).select_from(DayResult).where(DayResult.account_id == account)) == 0
        assert session.get(Account, account).published_generation_id is None
        query_args = dict(account_id=account, business_date=SATURDAY, limit=1, policy=execution.policy)
        assert not session.execute(cash_day_page(owner_id=2, fact_version=7, **query_args)).all()
        for page in range(1, 4):
            verified = restarted.verify_page(session, lease, **args, page_key=f"{page:020d}", deadline=deadline())
        assert verified == totals
    with pytest.raises(CalculationInputMismatch, match="actual source facts"):
        with Session(migrated) as session, session.begin():
            checkpoint = session.get(CalculationBatch, (account, generation, SATURDAY, "ACCOUNT_CASH", "", f"{2:020d}"))
            checkpoint.accumulator = checkpoint.accumulator | {"cash_in_cents": "999999"}
            session.flush()
            restarted.verify_page(session, lease, **args, page_key=f"{2:020d}", deadline=deadline())
    for expected in (False, True):
        with Session(migrated) as session, session.begin():
            assert restarted.reduce_page(session, lease, generation_id=generation,
                business_date=SUNDAY, deadline=deadline()) == expected
    with Session(migrated) as session, session.begin():
        assert restarted.completed_totals(session, lease, generation_id=generation,
            business_date=SUNDAY, deadline=deadline()) == CashDayTotals(30000, 0, 0, 0, 1, 0)
    balances = CashBalances(execution)
    with pytest.raises(CalculationInputMismatch, match="Every cash source page"):
        with Session(migrated) as session, session.begin():
            balances.close_date(session, lease, generation_id=generation, business_date=SUNDAY, deadline=deadline())
    with Session(migrated) as session, session.begin():
        for page in range(1, 3):
            restarted.verify_page(session, lease, generation_id=generation, business_date=SUNDAY,
                                  page_key=f"{page:020d}", deadline=deadline())
    with pytest.raises(CalculationInputMismatch, match="skipped"):
        with Session(migrated) as session, session.begin():
            balances.close_date(session, lease, generation_id=generation, business_date=SUNDAY, deadline=deadline())
    for day, expected in ((SATURDAY, 80000), (SATURDAY, 80000), (SUNDAY, 110000), (SUNDAY, 110000)):
        with Session(migrated) as session, session.begin():
            assert balances.close_date(session, lease, generation_id=generation,
                                       business_date=day, deadline=deadline()) == expected
    retire(migrated, lease)
