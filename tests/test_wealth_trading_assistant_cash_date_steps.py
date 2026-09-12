"""Natural-date continuation with real isolated PostgreSQL facts and rollbacks."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, deadline, retire
from tests.test_wealth_trading_assistant_cash_day_batches import SATURDAY, SUNDAY
from tests.test_wealth_trading_assistant_persistence import seed_account
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputs
from src.biz.services.wealth.market.trading_assistant.cash_date_steps import CashDateSteps
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution, CalculationExecutionLost


def test_natural_dates_resume_each_unit_without_weekend_stock_snapshots(migrated):
    now = datetime.now(timezone.utc)
    friday = SATURDAY - timedelta(days=1)
    with migrated.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(update(Account).where(Account.account_id == account).values(
            initialized_on=SATURDAY, fact_version=3))
        for version, day, direction, amount in ((2, SATURDAY, "IN", 100), (3, SUNDAY, "OUT", 20)):
            identity = uuid4()
            conn.execute(insert(Ledger).values(ledger_id=identity, account_id=account,
                kind="CASH_FLOW", created_at=now))
            conn.execute(insert(LedgerRevision).values(ledger_id=identity, account_id=account,
                kind="CASH_FLOW", revision=1, accepted_fact_version=version,
                occurred_on=day, status="ACTIVE", accepted_at=now, direction=direction,
                cash_amount=amount, net_cash_change=amount if direction == "IN" else -amount))
        conn.execute(insert(Recalculation).values(account_id=account, target_version=1,
            affected_from_date=friday, next_attempt_at=now, fence=0,
            transient_failure_count=0, updated_at=now))
    execution = RecalculationExecution(replace(TradingAssistantExecutionPolicyV1(), page_rows=1))
    with Session(migrated) as session, session.begin():
        lease = execution.claim(session, executor_id="cash-dates", deadline=deadline())
        assert lease.account_id == account
        generation = CalculationInputs(execution).prepare_generation(session, lease,
            from_date=friday, through_date=SUNDAY, rule_version=1, deadline=deadline())
    count_query = select(func.count()).select_from(CalculationBatch).where(
        CalculationBatch.generation_id == generation)
    expected = [(friday, stage) for stage in ("ACCOUNT_CASH", "ACCOUNT_CASH_CHECK", "CASH_BALANCE")]
    for day in (SATURDAY, SUNDAY):
        expected.extend((day, stage) for stage in (
            "ACCOUNT_CASH", "ACCOUNT_CASH", "ACCOUNT_CASH_CHECK", "ACCOUNT_CASH_CHECK", "CASH_BALANCE"))
    for count, result in enumerate(expected):
        with pytest.raises(RuntimeError, match="interrupt"):
            with Session(migrated) as session, session.begin():
                assert CashDateSteps(execution).advance(session, lease,
                    generation_id=generation, deadline=deadline()) == result
                raise RuntimeError("interrupt before commit")
        with Session(migrated) as session, session.begin():
            assert session.scalar(count_query) == count
            assert CashDateSteps(execution).advance(session, lease,
                generation_id=generation, deadline=deadline()) == result
            assert session.scalar(count_query) == count + 1
    for _ in range(2):
        with Session(migrated) as session, session.begin():
            assert CashDateSteps(execution).advance(session, lease,
                generation_id=generation, deadline=deadline()) is None
            assert session.scalar(count_query) == len(expected)
            for day, closing in ((friday, None), (SATURDAY, "10000"), (SUNDAY, "8000")):
                saved = session.get(CalculationBatch, (account, generation, day, "CASH_BALANCE", "", "1"))
                assert saved.accumulator["closingCash"] == closing
            assert session.scalar(select(func.count()).select_from(DayResult).where(
                DayResult.account_id == account)) == 0
            assert session.get(Account, account).published_generation_id is None
    with pytest.raises(CalculationExecutionLost):
        with Session(migrated) as session, session.begin():
            CashDateSteps(execution).advance(session, replace(lease, fence=lease.fence + 1),
                generation_id=generation, deadline=deadline())
    retire(migrated, lease)
