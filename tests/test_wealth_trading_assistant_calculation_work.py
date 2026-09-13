"""Accepted accounts -> claimed units -> source inputs -> publication, isolated PG."""
from datetime import timedelta
from decimal import Decimal
from itertools import count
from uuid import UUID

import pytest
from sqlalchemy import event, select, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.dialects.postgresql import insert

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, DAY, AT
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_calculation_interruptions import interruptions_db
from tests import test_wealth_trading_assistant_account_acceptance as acceptance
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from src.biz.services.wealth.market.trading_assistant.calculation_work import CalculationWork
from src.biz.services.wealth.market.trading_assistant.calculation_cutoff_targets import enqueue_confirmed_cutoff
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
from src.biz.services.wealth.market.trading_assistant.cutoff_preparation import AccountCutoffPreparation
from src.biz.services.wealth.market.trading_assistant.cutoff_discovery import CutoffDiscovery
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@pytest.fixture(scope="module")
def cutoff_db(interruptions_db):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000176").module
    assert revision.down_revision == "20260912_000175"
    with interruptions_db.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()
    return interruptions_db


@pytest.mark.parametrize("intraday,real_cutoff,missing_close", [
    (False, False, False), (True, False, False), (True, True, False),
    (False, True, False), (True, True, True)])
def test_accounts_are_claimed_and_published_with_confirmed_cutoff(cutoff_db, monkeypatch, intraday, real_cutoff, missing_close):
    interruptions_db = cutoff_db
    from datetime import datetime, timezone
    observed = datetime(2026, 9, 14, 4 if intraday and not missing_close else 12, tzinfo=timezone.utc)
    stock = "601021.SH" if missing_close else "601011.SH"
    monkeypatch.setattr(acceptance, "NOW", observed if intraday else AT)
    ids = []
    for index in range(2):
        protocol, _, saved = acceptance.create(interruptions_db, acceptance.create_command([
            dict(clientRowId="a", tsCode=stock, openedOn=DAY.isoformat(),
                quantity=100, availableQuantity=100, costPrice="10.00")]))
        ids.append(UUID(saved.receipt["result"]["account"]["accountId"]))
    with interruptions_db.begin() as conn:
        EquityDailyBar.__table__.create(conn, checkfirst=True)
    with Session(interruptions_db) as session, session.begin():
        for offset in range(4):
            day = DAY+timedelta(days=offset)
            session.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=day, is_open=offset in (0, 3),
                pretrade_date=DAY-timedelta(days=1) if not offset else DAY).on_conflict_do_nothing())
        for offset, price in ((0, "11.00"), (3, "12.00")):
            if missing_close and offset == 3:
                continue
            session.execute(insert(EquityDailyBar).values(ts_code=stock, trade_date=DAY+timedelta(days=offset),
                close=Decimal(price), source="tushare").on_conflict_do_nothing())
    ticks = count()
    # Deterministic database-time response; source/calendar/fees and all writes
    # remain real PostgreSQL. No dependence on the machine's test date.
    def clock(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT clock_timestamp()"):
            statement = statement.replace("clock_timestamp()",
                f"(TIMESTAMPTZ '{observed.isoformat()}' + INTERVAL '{next(ticks)} microseconds')")
        return statement, parameters
    event.listen(interruptions_db, "before_cursor_execute", clock, retval=True)
    try:
        execution = RecalculationExecution(protocol.policy)
        cutoff_calls = []
        confirmed_through = DAY+timedelta(days=2 if intraday else 3)
        def confirmed(session, *, account_id, target_version, deadline):
            # Controlled source-confirmation adapter, not a production scanner.
            # Calendar, actual price rows and all calculation writes stay real PG.
            cutoff_calls.append((account_id, target_version))
            if real_cutoff:
                return AccountCutoffPreparation(execution.policy).resolve(session,
                    account_id=account_id, target_version=target_version, deadline=deadline)
            return confirmed_through
        stages = []
        for _ in range(250):
            worker = CalculationWork(execution, sessionmaker(interruptions_db), rule_version=1,
                resolve_through_date=confirmed)
            stage = worker.run_once(executor_id="worker")
            stages.append(stage)
            assert stage not in ("FAILED", "WAITING_DATA", "TRANSIENT", "SUPERSEDED")
            if stage == "IDLE":
                break
        else:
            pytest.fail("Persisted work did not finish")
        assert stages[:2] == (["PREPARING", "PREPARING"] if real_cutoff else ["GENERATION", "GENERATION"])
        assert stages.count("PUBLISHED") == 2
        assert sorted(set(cutoff_calls)) == sorted((identity, 1) for identity in ids)
        if not real_cutoff:
            assert len(cutoff_calls) == 2
        with Session(interruptions_db) as session:
            for account_id in ids:
                account = session.get(Account, account_id)
                generation = session.get(CalculationGeneration, account.published_generation_id)
                assert generation.stage == "PUBLISHED"
                assert (generation.from_date, generation.through_date) == (DAY, DAY+timedelta(days=2 if intraday else 3))
                rows = session.scalars(select(AccountSnapshot).join(PublicationDay,
                    PublicationDay.day_result_id == AccountSnapshot.day_result_id).where(
                        PublicationDay.account_id == account_id,
                        PublicationDay.generation_id == generation.generation_id)
                    .order_by(PublicationDay.trade_date)).all()
                assert len(rows) == (1 if intraday else 2)
                assert rows[-1].stock_market_value == (1100 if intraday else 1200)
                if not intraday:
                    assert rows[-1].day_profit_amount == Decimal("99.95")
                assert session.get(Recalculation, account_id) is None
            assert session.scalar(select(func.count()).select_from(CalculationGeneration).where(
                CalculationGeneration.account_id.in_(ids))) == 2
        if intraday:
            # A later confirmed window is a new target, never an in-place
            # extension. No trade/account re-submission is needed.
            observed = observed.replace(hour=13 if missing_close else 12)
            if missing_close:
                with Session(interruptions_db) as session, session.begin():
                    session.add(EquityDailyBar(ts_code=stock, trade_date=DAY+timedelta(days=3),
                        close=Decimal("12.00"), source="tushare"))
            confirmed_through = DAY+timedelta(days=3)
            def enqueue(session, identity, through):
                return enqueue_confirmed_cutoff(session, account_id=identity, through_date=through,
                    policy=execution.policy, deadline=Deadline.after_ms(2000))
            with pytest.raises(RuntimeError, match="lost discovery batch"):
                with Session(interruptions_db) as session, session.begin():
                    assert enqueue(session, ids[0], confirmed_through)
                    raise RuntimeError("lost discovery batch")
            with Session(interruptions_db) as session, session.begin():
                for identity in ids:
                    assert session.get(Account, identity).calculation_target_version == 1
                    assert not enqueue(session, identity, DAY+timedelta(days=2))
                    if not real_cutoff:
                        assert enqueue(session, identity, confirmed_through)
                        assert not enqueue(session, identity, confirmed_through)
                    assert session.get(Account, identity).fact_version == 1
            for _ in range(250):
                discovered = CutoffDiscovery(execution.policy, sessionmaker(interruptions_db)).run_once() if real_cutoff else "IDLE"
                stage = CalculationWork(execution, sessionmaker(interruptions_db), rule_version=1,
                    resolve_through_date=confirmed).run_once(executor_id="restarted-worker")
                assert stage not in ("FAILED", "WAITING_DATA", "TRANSIENT", "SUPERSEDED")
                if stage == "IDLE" and discovered == "IDLE":
                    break
            else:
                pytest.fail("Later confirmed window did not finish")
            with Session(interruptions_db) as session, session.begin():
                for identity in ids:
                    generations = session.scalars(select(CalculationGeneration).where(
                        CalculationGeneration.account_id == identity).order_by(CalculationGeneration.target_version)).all()
                    assert [g.through_date for g in generations] == [DAY+timedelta(days=2), confirmed_through]
                    assert [g.stage for g in generations] == ["PUBLISHED", "PUBLISHED"]
                    assert session.get(Account, identity).published_generation_id == generations[-1].generation_id
                    old_day = session.get(PublicationDay, (identity, generations[0].generation_id, DAY))
                    reused_day = session.get(PublicationDay, (identity, generations[1].generation_id, DAY))
                    assert reused_day.day_result_id == old_day.day_result_id
                    assert session.scalar(select(func.count()).select_from(DayResult).where(
                        DayResult.account_id == identity, DayResult.origin_generation_id == generations[1].generation_id)) == 1
                    assert session.scalar(select(func.count()).select_from(CalculationBatch).where(
                        CalculationBatch.account_id == identity, CalculationBatch.generation_id == generations[1].generation_id,
                        CalculationBatch.stage == "PREFIX_DATE")) == 3
                    assert session.scalar(select(func.count()).select_from(ValuationBasis).where(
                        ValuationBasis.account_id == identity, ValuationBasis.generation_id == generations[1].generation_id,
                        ValuationBasis.trade_date == DAY)) == 0
                    assert generations[1].completed_trade_date_count == 2
                    assert session.get(Recalculation, identity) is None
                    assert not enqueue(session, identity, confirmed_through)
            assert sorted(set(cutoff_calls)) == sorted((identity, target) for identity in ids for target in (1, 2))
            if not real_cutoff:
                assert len(cutoff_calls) == 4
    finally:
        event.remove(interruptions_db, "before_cursor_execute", clock)


def test_invalid_cutoff_pauses_without_losing_account_and_rule_mismatch_is_not_retried(cutoff_db, monkeypatch):
    monkeypatch.setattr(acceptance, "NOW", AT)
    protocol, _, saved = acceptance.create(cutoff_db)
    identity = UUID(saved.receipt["result"]["account"]["accountId"])
    execution = RecalculationExecution(protocol.policy)
    worker = CalculationWork(execution, sessionmaker(cutoff_db), rule_version=1,
        resolve_through_date=lambda *a, **k: None)
    assert worker.run_once(executor_id="bad-cutoff") == "FAILED"
    from src.biz.queries.wealth.market.trading_assistant.calculation_status import CalculationStatusQuery
    with Session(cutoff_db) as session, session.begin():
        pending = session.get(Recalculation, identity)
        assert pending.next_attempt_at is None and pending.executor_id is None
        assert session.get(Account, identity).fact_version == 1
        status = CalculationStatusQuery(protocol.policy).read(session, owner_id=1,
            account_id=identity, deadline=Deadline.after_ms(2000))
        assert status.stage == "FAILED"
        assert status.progress.completedTradeDateCount == 0
        pending.next_attempt_at = session.scalar(select(func.clock_timestamp()))
    good = CalculationWork(execution, sessionmaker(cutoff_db), rule_version=1,
        resolve_through_date=lambda *a, **k: DAY)
    assert good.run_once(executor_id="fixed") == "GENERATION"
    wrong_rule = CalculationWork(execution, sessionmaker(cutoff_db), rule_version=2,
        resolve_through_date=lambda *a, **k: pytest.fail("Existing range must not be reselected"))
    assert wrong_rule.run_once(executor_id="wrong-rule") == "FAILED"
    with Session(cutoff_db) as session:
        generation = session.scalar(select(CalculationGeneration).where(CalculationGeneration.account_id == identity))
        assert generation.rule_version == 1 and generation.stage == "FAILED"
        assert session.get(Recalculation, identity).next_attempt_at is None
