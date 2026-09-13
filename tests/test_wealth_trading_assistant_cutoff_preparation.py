"""Readiness is account scoped, persistent and distinct from calculation inputs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_work import database, migrated, publication_db, interruptions_db, cutoff_db
from tests.test_wealth_trading_assistant_calculation_inputs import DAY, AT
from tests import test_wealth_trading_assistant_account_acceptance as acceptance
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation
from src.biz.services.wealth.market.trading_assistant.cutoff_preparation import AccountCutoffPreparation, CutoffPreparationInProgress
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationDataUnavailable
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@pytest.mark.parametrize("scope", ["cash", "missing_first", "missing_later", "two_stocks"])
def test_real_readiness_is_paged_and_does_not_invent_missing_history(cutoff_db, monkeypatch, scope):
    monkeypatch.setattr(acceptance, "NOW", AT)
    codes = [] if scope == "cash" else (["601111.SH", "601112.SH"] if scope == "two_stocks" else
        ["601113.SH" if scope == "missing_first" else "601114.SH"])
    protocol, _, saved = acceptance.create(cutoff_db, acceptance.create_command([
        dict(clientRowId=c, tsCode=c, openedOn=DAY.isoformat(), quantity=100, availableQuantity=100,
            costPrice="10.00") for c in codes]))
    identity = UUID(saved.receipt["result"]["account"]["accountId"])
    with cutoff_db.begin() as conn:
        EquityDailyBar.__table__.create(conn, checkfirst=True)
    with Session(cutoff_db) as session, session.begin():
        for offset in range(4):
            session.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=DAY+timedelta(days=offset),
                is_open=offset in (0, 3), pretrade_date=DAY-timedelta(days=1) if offset == 0 else DAY).on_conflict_do_nothing())
        for c in codes:
            for offset in (0, 3):
                if scope == "missing_first" or (scope == "missing_later" and offset == 3):
                    continue
                session.execute(insert(EquityDailyBar).values(ts_code=c, trade_date=DAY+timedelta(days=offset),
                    close=Decimal("11.00"), source="tushare").on_conflict_do_nothing())
    def clock(conn, cursor, statement, params, context, executemany):
        if statement.startswith("SELECT clock_timestamp()"):
            statement = statement.replace("clock_timestamp()", "TIMESTAMPTZ '2026-09-14 12:00:00+00'")
        return statement, params
    event.listen(cutoff_db, "before_cursor_execute", clock, retval=True)
    policy = replace(protocol.policy, page_rows=1)
    def unit(session):
        try:
            return AccountCutoffPreparation(policy).resolve(session, account_id=identity,
                target_version=1, deadline=Deadline.after_ms(2000))
        except CutoffPreparationInProgress:
            return "NEXT"
        except CalculationDataUnavailable:
            return "WAITING"
    try:
        with pytest.raises(RuntimeError, match="rollback"):
            with Session(cutoff_db) as session, session.begin():
                unit(session)
                raise RuntimeError("rollback")
        with Session(cutoff_db) as session:
            assert session.get(CutoffPreparation, (identity, 1, "INITIAL")) is None
        progress = []
        for _ in range(20):
            with Session(cutoff_db) as session, session.begin():
                result = unit(session)
                row = session.get(CutoffPreparation, (identity, 1, "INITIAL"))
                progress.append((row.current_date, row.after_stock))
            if result != "NEXT":
                break
        else:
            pytest.fail("Readiness scan did not yield a decision")
        if scope == "missing_first":
            assert result == "WAITING"
            with Session(cutoff_db) as session, session.begin():
                row = session.get(CutoffPreparation, (identity, 1, "INITIAL"))
                assert row.state == "WAITING_DATA" and row.complete_through is None
                assert session.get(Account, identity).fact_version == 1
                assert unit(session) == "WAITING"
        else:
            assert result == DAY+timedelta(days=2 if scope == "missing_later" else 3)
            with Session(cutoff_db) as session, session.begin():
                assert unit(session) == result  # Frozen range decision on retry.
        if scope == "two_stocks":
            assert (DAY, "601111.SH") in progress and (DAY, "601112.SH") in progress
        with Session(cutoff_db) as session:
            assert session.scalar(select(func.count()).select_from(CalculationGeneration).where(
                CalculationGeneration.account_id == identity)) == 0
    finally:
        event.remove(cutoff_db, "before_cursor_execute", clock)


@pytest.mark.parametrize("sold", [40, 100])
def test_scope_includes_sell_day_but_not_already_closed_positions(database, sold):
    from tests.test_wealth_trading_assistant_calculation_ledger import seed_sells
    from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
    from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
    from src.biz.queries.wealth.market.trading_assistant.cutoff_stocks import cutoff_stock_page
    from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
    with database.begin() as conn:
        identity, ids = seed_sells(conn, [sold])
    with Session(database) as session, session.begin():
        account = session.get(Account, identity)
        account.fact_version = 2
        session.add(InitialPosition(account_id=identity, initialization_id=account.current_initialization_id,
            ts_code="000001.SZ", client_row_id="initial", opened_on=DAY-timedelta(days=1),
            quantity=100, available_quantity=100, cost_price="10.00"))
        session.flush()
        def scope(day, after=None):
            return list(session.scalars(cutoff_stock_page(account=account, business_date=day,
                after=after, policy=TradingAssistantExecutionPolicyV1())))
        assert scope(DAY) == ["000001.SZ"]
        assert scope(DAY, after="000001.SZ") == []
        assert scope(DAY+timedelta(days=3)) == (["000001.SZ"] if sold == 40 else [])
        old = session.execute(select(*LedgerRevision.__table__.columns).where(
            LedgerRevision.ledger_id == ids[0])).mappings().one()
        session.execute(insert(LedgerRevision).values(**(dict(old) | {
            "revision": 2, "source_revision": 1, "accepted_fact_version": 3, "status": "VOID"})))
        account.fact_version = 3
        session.flush()
        assert scope(DAY+timedelta(days=3)) == ["000001.SZ"]


def test_preparation_byte_budget_is_not_ignored():
    from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
    from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
    service = AccountCutoffPreparation(replace(TradingAssistantExecutionPolicyV1(), page_bytes=8))
    service._check_bytes({})
    with pytest.raises(CalculationInputMismatch, match="byte budget"):
        service._check_bytes({"evidence": "too big"})


def test_readiness_scope_100000_trades_uses_bounded_sql(database):
    from time import monotonic
    from uuid import uuid4
    from sqlalchemy import text
    from tests.test_wealth_trading_assistant_persistence import seed_account
    from src.biz.queries.wealth.market.trading_assistant.cutoff_stocks import cutoff_stock_page
    from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
    from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
    count, prefix = 100000, str(uuid4())
    with database.begin() as conn:
        identity, initialization, fee = seed_account(conn)
        args = dict(account=identity, initialization=initialization, fee=fee, prefix=prefix, count=count)
        conn.execute(text("UPDATE app.wealth_ta_initialization SET initial_cash=600000 WHERE initialization_id=:initialization"), args)
        conn.execute(text("""INSERT INTO app.wealth_ta_ledger (ledger_id, account_id, kind, created_at)
            SELECT md5(:prefix || n::text)::uuid, :account, 'TRADE', now() FROM generate_series(1,:count) n"""), args)
        conn.execute(text("""INSERT INTO app.wealth_ta_ledger_revision
            (ledger_id,account_id,kind,revision,accepted_fact_version,occurred_on,accepted_at,status,
             direction,ts_code,price,quantity,gross_amount,fee_version_id,commission_rate,minimum_commission,
             stamp_tax_rate,commission_amount,stamp_tax_amount,net_cash_change)
            SELECT md5(:prefix || n::text)::uuid,:account,'TRADE',1,n+1,DATE '2026-09-11',now(),'ACTIVE',
             'BUY','000001.SZ',1,1,1,:fee,0.000235,5,0.0005,5,0,-6 FROM generate_series(1,:count) n"""), args)
        conn.execute(text("UPDATE app.wealth_ta_account SET fact_version=:count+1 WHERE account_id=:account"), args)
        conn.execute(text("ANALYZE app.wealth_ta_ledger_revision"))
    policy = TradingAssistantExecutionPolicyV1()
    with Session(database) as session, session.begin():
        account = session.get(Account, identity)
        deadline = Deadline.after_ms(policy.batch_budget_ms)
        apply_sql_budget(session, deadline, policy)
        started = monotonic()
        rows = list(session.scalars(cutoff_stock_page(account=account,
            business_date=DAY+timedelta(days=3), after=None, policy=policy)))
        deadline.remaining_ms()
        assert rows == ["000001.SZ"]
        print(f"cutoff_scope input_trades={count} output_rows={len(rows)} elapsed={monotonic()-started:.4f}s")
