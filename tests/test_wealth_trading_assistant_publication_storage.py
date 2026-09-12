"""New publication DDL and nullable pre-initialization cash, isolated PG only."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, DAY
from src.biz.models.wealth.trading_assistant.calculation import DayResult
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay, PublicationReceipt


@pytest.fixture(scope="module")
def publication_db(migrated):
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000174").module
    assert revision.down_revision == "20260912_000173"
    with migrated.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()
    return migrated


def snapshot_values(account, day):
    return dict(account_id=account, day_result_id=day, trade_date=DAY,
        valuation_at=datetime.now(timezone.utc), cash_amount=None, total_assets=None,
        stock_market_value="11000.00", cash_in_amount="0.00", cash_out_amount="0.00",
        current_buy_input="10000.00", current_sell_net="0.00", dynamic_cost_amount="10000.00",
        estimated_sell_commission="5.00", estimated_stamp_tax="5.50", estimated_net_proceeds="10989.50",
        holding_profit_amount="989.50", holding_return_pct="9.90", day_profit_amount="989.50",
        day_capital_amount="10000.00", day_return_pct="9.90", closed_trade_count=0, closed_profit_amount="0.00")


def test_snapshot_unknown_cash_is_not_zero_and_manifest_fk(publication_db):
    _, lease, generation, _ = setup(publication_db)
    day = uuid4()
    with publication_db.begin() as conn:
        conn.execute(insert(DayResult).values(day_result_id=day, account_id=lease.account_id,
            origin_generation_id=generation, trade_date=DAY, input_digest=b"x"*32,
            status="SEALED", sealed_at=datetime.now(timezone.utc)))
        conn.execute(insert(AccountSnapshot).values(**snapshot_values(lease.account_id, day)))
        conn.execute(insert(PublicationDay).values(account_id=lease.account_id, generation_id=generation,
                                                  trade_date=DAY, day_result_id=day))
        conn.execute(insert(PublicationReceipt).values(account_id=lease.account_id, generation_id=generation,
            target_version=1, published_at=datetime.now(timezone.utc), manifest_digest=b"a"*32, day_count=1))
    with publication_db.connect() as conn:
        row = conn.execute(select(AccountSnapshot).where(AccountSnapshot.day_result_id==day)).mappings().one()
        assert row["cash_amount"] is None and row["total_assets"] is None
        assert str(row["holding_profit_amount"]) == "989.50"
    for values in ({"cash_amount":"0.00"}, {"total_assets":"11000.00"},
                   {"stock_market_value":"NaN"}, {"day_return_pct":None},
                   {"day_capital_amount":"0.00"}, {"closed_trade_count":-1}):
        with pytest.raises(IntegrityError):
            with publication_db.begin() as conn:
                conn.execute(AccountSnapshot.__table__.update().where(AccountSnapshot.day_result_id==day).values(**values))
    with pytest.raises(IntegrityError):
        with publication_db.begin() as conn:
            conn.execute(PublicationDay.__table__.update().where(PublicationDay.generation_id==generation)
                         .values(day_result_id=uuid4()))
    revision=ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000174").module
    with pytest.raises(RuntimeError, match="must be retained"):
        with publication_db.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            revision.downgrade()
