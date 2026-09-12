"""Accepted suspension checks on isolated PostgreSQL; never source writes."""
from datetime import timedelta
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from sqlalchemy import update, insert, select, func
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import (
    database, migrated, setup, DAY, AT, deadline, retire)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.equity_dividend import EquityDividend
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.biz.models.wealth.trading_assistant.calculation_inputs import ValuationBasis
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.valuation_facts import DailyCloseFactsReader


CASES = ("ok", "gap_factor", "changed_factor", "zero_factor", "gap_calendar", "intraday",
         "conflict", "gap_suspend", "event", "invalid_price", "current", "invalid_current")


@pytest.fixture(scope="module", autouse=True)
def source_tables(migrated):
    with migrated.begin() as conn:
        EquityDailyBar.__table__.create(conn, checkfirst=True)


@pytest.mark.parametrize("case", CASES)
def test_carry_requires_complete_accepted_evidence_and_freezes(migrated, case):
    inputs, lease, generation, fee = setup(migrated)
    code = f"{100000 + CASES.index(case):06d}.SZ"
    start = DAY-timedelta(days=3)
    with Session(migrated) as session, session.begin():
        session.add(EquityDailyBar(ts_code=code, trade_date=start,
            close=Decimal("NaN" if case == "invalid_price" else "10.1234"), source="tushare"))
        for offset in range(4):
            day = start+timedelta(days=offset)
            # Calendar is shared across cases; missing coverage uses a savepoint below.
            if session.get(TradeCalendar, ("SSE", day)) is None:
                session.add(TradeCalendar(exchange="SSE", trade_date=day, is_open=True,
                    pretrade_date=day-timedelta(days=1)))
            if not (case == "gap_factor" and offset == 1):
                value = "2" if case == "changed_factor" and offset == 1 else "1"
                session.add(EquityAdjFactor(ts_code=code, trade_date=day,
                    adj_factor=Decimal("0" if case == "zero_factor" else value)))
            if offset and not (case == "gap_suspend" and offset == 1):
                session.add(EquitySuspendD(ts_code=code, trade_date=day, row_key_hash=uuid4().hex,
                    suspend_type="S", suspend_timing="09:30-10:00" if case == "intraday" else None))
        if case == "conflict":
            session.add(EquitySuspendD(ts_code=code, trade_date=DAY, row_key_hash=uuid4().hex,
                suspend_type="R", suspend_timing=None))
        if case == "event":
            session.add(EquityDividend(ts_code=code, row_key_hash=uuid4().hex, event_key_hash=uuid4().hex,
                end_date=start, ann_date=start, div_proc="实施", ex_date=DAY, cash_div_tax=Decimal("0.1")))
        if case in ("current", "invalid_current"):
            session.add(EquityDailyBar(ts_code=code, trade_date=DAY,
                close=Decimal("12.34" if case == "current" else "0"), source="tushare"))
    with Session(migrated) as session, session.begin():
        nested = session.begin_nested()
        if case == "gap_calendar":
            # Keep the row but move it outside this window; rollback after reading.
            session.execute(update(TradeCalendar).where(TradeCalendar.exchange=="SSE",
                TradeCalendar.trade_date==start+timedelta(days=1)).values(trade_date=start-timedelta(days=30)))
        fact = DailyCloseFactsReader(inputs.policy).read(session, (code,), DAY, deadline())[0]
        nested.rollback()
        if case not in ("ok", "current"):
            assert fact.price is None and fact.suspension_evidence is None
        elif case == "current":
            assert fact.price_date == DAY and fact.price_text == "12.3400" and fact.suspension_evidence is None
        else:
            assert fact.price_date == start and fact.price_text == "10.1234"
            assert json.loads(fact.suspension_evidence)["factorDays"] == 4
            inputs.save_valuation_page(session, lease, generation_id=generation, facts=(fact,),
                fee_version_id=fee, valuation_at=AT, after_stock=None, deadline=deadline())
    if case == "ok":
        with Session(migrated) as session, session.begin():
            session.execute(update(EquityAdjFactor).where(EquityAdjFactor.ts_code==code).values(adj_factor=3))
            basis = session.scalar(select(ValuationBasis).where(ValuationBasis.generation_id==generation))
            assert json.loads(basis.source_ref)["tradeDate"] == start.isoformat()
            assert basis.trade_date == DAY and basis.valuation_method == "CONFIRMED_SUSPENSION_CARRY"
            saved = inputs.read_valuation_page(session, lease, generation_id=generation,
                trade_date=DAY, page_key=code, deadline=deadline())
            assert saved.facts == (fact,)  # Frozen evidence does not follow changed source data.
        with pytest.raises(CalculationInputMismatch):
            with Session(migrated) as session, session.begin():
                session.execute(update(ValuationBasis).where(ValuationBasis.generation_id==generation)
                    .values(suspension_evidence_ref=fact.suspension_evidence.replace('"factor":"1.00000000"', '"factor":"2"')))
                inputs.read_valuation_page(session, lease, generation_id=generation,
                    trade_date=DAY, page_key=code, deadline=deadline())
    retire(migrated, lease)


def test_continuous_suspension_keeps_original_date_then_resumes(migrated):
    from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
    code = "200001.SZ"
    with Session(migrated) as session, session.begin():
        for offset in range(6):
            day = DAY+timedelta(days=offset)
            if session.get(TradeCalendar, ("SSE", day)) is None:
                session.add(TradeCalendar(exchange="SSE", trade_date=day, is_open=offset not in (1,2),
                    pretrade_date=DAY if offset <= 3 else day-timedelta(days=1)))
            if offset not in (1,2):
                session.add(EquityAdjFactor(ts_code=code, trade_date=day, adj_factor=1))
            if offset in (0,5):
                session.add(EquityDailyBar(ts_code=code, trade_date=day, close=Decimal("10"), source="tushare"))
            if offset in (3,4):
                session.add(EquitySuspendD(ts_code=code, trade_date=day, row_key_hash=uuid4().hex,
                    suspend_type="S", suspend_timing=None))
        session.add(EquityDividend(ts_code=code, row_key_hash=uuid4().hex, event_key_hash=uuid4().hex,
            end_date=DAY, ann_date=DAY, div_proc="预案", ex_date=DAY+timedelta(days=3), cash_div_tax=1))
    with Session(migrated) as session, session.begin():
        reader = DailyCloseFactsReader(TradingAssistantExecutionPolicyV1())
        for offset in (3,4,5):
            day = DAY+timedelta(days=offset)
            fact = reader.read(session, (code,), day, deadline())[0]
            assert fact.price_text == "10.0000"
            assert fact.price_date == (DAY if offset < 5 else day)
            assert (fact.suspension_evidence is not None) == (offset < 5)
        assert session.scalar(select(func.count()).select_from(EquityDailyBar).where(
            EquityDailyBar.ts_code==code)) == 2  # No synthetic source rows.


def test_maximum_stock_page_is_bounded_and_preserves_all_evidence(migrated):
    from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
    inputs, lease, generation, fee = setup(migrated)
    codes = tuple(f"{300000+i:06d}.SZ" for i in range(500))
    start = DAY-timedelta(days=1)
    with Session(migrated) as session, session.begin():
        for day in (start, DAY):
            if session.get(TradeCalendar, ("SSE", day)) is None:
                session.add(TradeCalendar(exchange="SSE", trade_date=day, is_open=True,
                    pretrade_date=day-timedelta(days=1)))
    with migrated.begin() as conn:
        conn.execute(insert(EquityDailyBar), [dict(ts_code=code, trade_date=start,
            close=Decimal("10"), source="tushare") for code in codes])
        conn.execute(insert(EquityAdjFactor), [dict(ts_code=code, trade_date=day, adj_factor=1)
            for code in codes for day in (start,DAY)])
        conn.execute(insert(EquitySuspendD), [dict(ts_code=code, trade_date=DAY,
            row_key_hash=uuid4().hex, suspend_type="S", suspend_timing=None) for code in codes])
    with Session(migrated) as session, session.begin():
        facts = DailyCloseFactsReader(TradingAssistantExecutionPolicyV1()).read(session, codes, DAY, deadline())
        assert len(facts) == 500
        assert all(f.price_date == start and f.price_text == "10.0000" and f.suspension_evidence for f in facts)
    with Session(migrated) as session, session.begin():
        inputs.save_valuation_page(session, lease, generation_id=generation, facts=facts,
            fee_version_id=fee, valuation_at=AT, after_stock=None, deadline=deadline())
    with Session(migrated) as session, session.begin():
        assert inputs.read_valuation_page(session, lease, generation_id=generation,
            trade_date=DAY, page_key=codes[-1], deadline=deadline()).facts == facts
    retire(migrated, lease)
