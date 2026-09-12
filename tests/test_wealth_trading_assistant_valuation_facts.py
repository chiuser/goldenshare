"""Real isolated source reads; no production mutation or implicit old-price fill."""
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest
from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.valuation_facts import DailyCloseFactsReader


def test_exact_current_close_missing_price_and_source_revision(database):
    day = date(2026, 9, 11)
    with database.begin() as conn:
        EquityDailyBar.__table__.create(conn)
        conn.execute(insert(EquityDailyBar), [
            dict(ts_code="000001.SZ", trade_date=day, close=Decimal("10.1234"), source="tushare"),
            dict(ts_code="600000.SH", trade_date=date(2026,9,10), close=Decimal("9.2600"), source="tushare"),
            dict(ts_code="920002.BJ", trade_date=day, close=Decimal("0"), source="tushare"),
            dict(ts_code="000002.SZ", trade_date=day, close=Decimal("NaN"), source="tushare"),
            dict(ts_code="000004.SZ", trade_date=day, close=Decimal("10"), source="unverified"),
        ])
    reader = DailyCloseFactsReader(TradingAssistantExecutionPolicyV1())
    codes = ("600000.SH", "000001.SZ", "920002.BJ", "000002.SZ", "000003.SZ", "000004.SZ")
    with Session(database) as session, session.begin():
        facts = reader.read(session, codes, day, Deadline.after_ms(5000))
        assert facts == reader.read(session, tuple(reversed(codes)), day, Deadline.after_ms(5000))
        good = facts[0]
        assert good.price_text == "10.1234" and good.price == Fraction(50617,5000)
        assert good.price_date == day and good.reason is None
        assert all(f.price is None and f.price_date is None and f.reason for f in facts[1:])
    with database.begin() as conn:
        conn.execute(update(EquityDailyBar).where(EquityDailyBar.ts_code == "000001.SZ")
                     .values(close=Decimal("10.1235")))
    with Session(database) as session, session.begin():
        revised = reader.read(session, ("000001.SZ",), day, Deadline.after_ms(5000))[0]
        assert revised.source_version != good.source_version
        assert good.price_text == "10.1234"  # An already-read fact is immutable.


@pytest.mark.parametrize("codes", [("a", "a"), ("",), (True,), tuple(str(i) for i in range(501))])
def test_invalid_or_unbounded_pages_do_not_issue_sql(codes):
    class NoSQL:
        def execute(self, *args, **kwargs):
            pytest.fail("Invalid source page issued SQL")
    with pytest.raises(ValueError):
        DailyCloseFactsReader(TradingAssistantExecutionPolicyV1()).read(
            NoSQL(), codes, date(2026,9,11), Deadline.after_ms(5000))
