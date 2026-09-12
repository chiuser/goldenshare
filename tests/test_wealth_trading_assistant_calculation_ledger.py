"""Real PG window/keyset parity with the M1 whole-day cent algorithm."""
from datetime import date, datetime, timezone
from decimal import Decimal
import random
from uuid import UUID

import pytest
from sqlalchemy import insert

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.queries.wealth.market.trading_assistant.calculation_ledger import allocated_sell_page, trade_page
from src.biz.services.wealth.market.trading_assistant.calculation.allocation import allocate_sell_costs, SellQuantity
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1

DAY = date(2026, 9, 11)
POLICY = TradingAssistantExecutionPolicyV1()


def seed_sells(conn, quantities):
    account, _, fee = seed_account(conn)
    now = datetime.now(timezone.utc)
    # UUID order is the same as canonical fixed-width source text order.
    ids = [UUID(int=account.int ^ (i + 1)) for i in range(len(quantities))]
    rows = list(zip(ids, quantities))
    random.Random(41).shuffle(rows)
    conn.execute(insert(Ledger), [dict(ledger_id=identity, account_id=account,
        kind="TRADE", created_at=now) for identity, _ in rows])
    versions = {identity: index + 2 for index, identity in enumerate(ids)}
    conn.execute(insert(LedgerRevision), [dict(ledger_id=identity, revision=1,
        account_id=account, kind="TRADE", accepted_fact_version=versions[identity],
        occurred_on=DAY, status="ACTIVE", accepted_at=now, direction="SELL", ts_code="000001.SZ",
        price=Decimal("1.00"), quantity=quantity, gross_amount=Decimal(quantity),
        fee_version_id=fee, commission_rate=Decimal(0), minimum_commission=Decimal(0),
        stamp_tax_rate=Decimal(0), commission_amount=Decimal(0), stamp_tax_amount=Decimal(0),
        net_cash_change=Decimal(quantity)) for identity, quantity in rows])
    return account, ids


@pytest.mark.parametrize("quantities,pool,opening,page_size", [
    ([100, 100, 100], 1000000, 300, 1),
    ([1] * 503, 1000001, 1000, 500),
    ([1, 17, 2, 33], 10**70 + 7, 90, 2),
])
def test_global_allocation_is_not_page_local(database, quantities, pool, opening, page_size):
    with database.begin() as conn:
        account, ids = seed_sells(conn, quantities)
    expected = allocate_sell_costs(pool, opening,
        tuple(SellQuantity(str(identity), quantity) for identity, quantity in zip(ids, quantities)))
    arguments = dict(owner_id=1, account_id=account, fact_version=len(ids)+1,
        trade_date=DAY, stock="000001.SZ", opening_quantity=opening, opening_pool_cents=pool,
        limit=page_size, policy=POLICY)
    actual, cursor = {}, None
    with database.connect() as conn:
        while True:
            page = conn.execute(allocated_sell_page(**arguments, after=cursor)).mappings().all()
            if not page:
                break
            assert len(page) <= page_size
            for row in page:
                assert int(row["allocation_target_cents"]) == expected.allocated_cents
                assert int(row["total_sold"]) == sum(quantities)
                assert row["sell_count"] == len(ids)
                actual[str(row["ledger_id"])] = int(row["allocated_cost_cents"])
            cursor = page[-1]["ledger_id"]
        assert actual == {item.source_id: item.cost_cents for item in expected.items}
        assert sum(actual.values()) == expected.allocated_cents
        assert not conn.execute(allocated_sell_page(**(arguments | {"owner_id": 2}))).all()


def test_revisions_are_selected_before_stock_day_filters(database):
    with database.begin() as conn:
        account, ids = seed_sells(conn, [7])
        old = conn.execute(LedgerRevision.__table__.select().where(
            LedgerRevision.ledger_id == ids[0])).mappings().one()
        conn.execute(insert(LedgerRevision).values(**(dict(old) | {
            "revision": 2, "source_revision": 1, "accepted_fact_version": 3,
            "occurred_on": date(2026, 9, 10)})))
        conn.execute(insert(LedgerRevision).values(**(dict(old) | {
            "revision": 3, "source_revision": 2, "accepted_fact_version": 4, "status": "VOID"})))
    arguments = dict(owner_id=1, account_id=account, trade_date=DAY, stock="000001.SZ",
                     limit=500, policy=POLICY)
    with database.connect() as conn:
        assert len(conn.execute(trade_page(**arguments, fact_version=2)).all()) == 1
        for version in (3, 4):
            assert not conn.execute(trade_page(**arguments, fact_version=version)).all()
            assert not conn.execute(allocated_sell_page(**arguments, fact_version=version,
                opening_quantity=7, opening_pool_cents=700)).all()
