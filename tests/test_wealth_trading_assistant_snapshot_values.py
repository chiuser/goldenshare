"""Real PostgreSQL read-back of computed snapshot fields; no production access."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, deadline, retire, DAY
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_account_day import held, finish
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import DayResult
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationReceipt
from src.biz.services.wealth.market.trading_assistant.calculation.account_day import AccountDayTotals, add_stock_day
from src.biz.services.wealth.market.trading_assistant.snapshot_values import snapshot_values


@pytest.mark.parametrize("cash", [None, 0, 500000])
def test_computed_snapshot_readback_is_not_publication(publication_db, cash):
    store, lease, generation, _ = setup(publication_db)
    day = uuid4()
    amounts = finish(add_stock_day(AccountDayTotals(), held()), cash=cash)
    expected = snapshot_values(amounts, account_id=lease.account_id, day_result_id=day,
        trade_date=DAY, valuation_at=datetime(2026, 9, 11, 7, tzinfo=timezone.utc))
    with Session(publication_db) as session, session.begin():
        with store.execution.batch(session, lease, deadline=deadline()):
            session.add(DayResult(day_result_id=day, account_id=lease.account_id, origin_generation_id=generation,
                trade_date=DAY, input_digest=b"a"*32, status="BUILDING"))
            session.flush()
            session.add(AccountSnapshot(**expected))
    with Session(publication_db) as session:
        saved = session.get(AccountSnapshot, (lease.account_id, day))
        assert {key: getattr(saved, key) for key in expected} == expected
        assert saved.holding_return_pct == saved.day_return_pct == 10
        assert saved.closed_profit_amount == 0 and saved.day_profit_amount == 1000
        assert saved.day_capital_amount == 10000
        assert session.get(Account, lease.account_id).published_generation_id is None
        assert session.scalar(select(PublicationReceipt).where(PublicationReceipt.account_id == lease.account_id)) is None
        assert session.get(DayResult, day).status == "BUILDING"
    retire(publication_db, lease)


def test_pure_cash_has_null_return_triples():
    values = snapshot_values(finish(AccountDayTotals(), cash=100000), account_id=uuid4(), day_result_id=uuid4(),
        trade_date=DAY, valuation_at=datetime.now(timezone.utc))
    assert values["holding_return_pct"] is None
    assert values["day_profit_amount"] is values["day_capital_amount"] is values["day_return_pct"] is None
    assert values["cash_amount"] == values["total_assets"] == 1000
    with pytest.raises(ValueError, match="identity"):
        snapshot_values(finish(AccountDayTotals()), account_id=uuid4(), day_result_id=uuid4(),
            trade_date=DAY, valuation_at=datetime(2026, 9, 11))
