"""M1 results round-trip in independent closed-sale rows; no M3 publication."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_day_result
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.models.wealth.trading_assistant.calculation import ClosedTrade, PositionState
from src.biz.services.wealth.market.trading_assistant.calculation.daily import calculate_stock_day, initialize_position, Trade
from src.biz.services.wealth.market.trading_assistant.calculation.fees import FeeSnapshot, calculate_trade_fees
from src.biz.services.wealth.market.trading_assistant.persistence_values import money_numeric, numeric_cents


def test_each_partial_sale_result_is_independently_stored_and_reconciles(database):
    day, now, round_id = date(2026,9,11), datetime.now(timezone.utc), uuid4()
    fees = FeeSnapshot.from_inputs("2.35", "5.00", "0.05")
    with database.begin() as connection:
        account, day_id = seed_day_result(connection)
        fee_id = connection.scalar(select(Account.current_fee_version_id).where(Account.account_id == account))
        trades = tuple(Trade(str(uuid4()), str(account), "600000.SH", day, "SELL", quantity, 1100, fees)
            for quantity in (200, 300))
        result = calculate_stock_day(str(account), "600000.SH", day, initialize_position(1000,1000,1000), trades)
        for version, trade in enumerate(trades, 2):
            amounts = calculate_trade_fees(trade.quantity * trade.price_cents, fees, "SELL")
            connection.execute(insert(Ledger).values(ledger_id=UUID(trade.source_id), account_id=account, kind="TRADE", created_at=now))
            connection.execute(insert(LedgerRevision).values(ledger_id=UUID(trade.source_id), account_id=account, kind="TRADE", revision=1,
                accepted_fact_version=version, occurred_on=day, status="ACTIVE", accepted_at=now, direction="SELL", ts_code=trade.stock_code,
                price="11.00", quantity=trade.quantity, gross_amount=money_numeric(amounts.gross_cents), fee_version_id=fee_id,
                commission_rate="0.000235", minimum_commission="5.00", stamp_tax_rate="0.0005",
                commission_amount=money_numeric(amounts.commission_cents), stamp_tax_amount=money_numeric(amounts.stamp_tax_cents),
                net_cash_change=money_numeric(amounts.net_cash_change_cents)))
        for sale in result.closed_sales:
            connection.execute(insert(ClosedTrade).values(account_id=account, day_result_id=day_id, sell_ledger_id=UUID(sale.source_id),
                sell_revision=1, round_id=round_id, quantity=sale.quantity, allocated_cost=money_numeric(sale.allocated_cost_cents),
                net_proceeds=money_numeric(sale.net_proceeds_cents), profit_amount=money_numeric(sale.profit_cents), return_pct=Decimal(sale.return_pct)))
        state = result.closing
        connection.execute(insert(PositionState).values(account_id=account, day_result_id=day_id, ts_code="600000.SH", round_id=round_id,
            opened_on=day, quantity=state.quantity, remaining_buy_cost=money_numeric(state.pool_cents),
            cumulative_buy_input=money_numeric(state.buy_investment_cents), cumulative_sell_net=money_numeric(state.sell_net_cents)))
    with Session(database) as session:
        rows = session.scalars(select(ClosedTrade).where(ClosedTrade.account_id == account).order_by(ClosedTrade.sell_ledger_id)).all()
        assert len(rows) == 2
        for row, expected in zip(rows, result.closed_sales, strict=True):
            assert str(row.sell_ledger_id) == expected.source_id and row.quantity == expected.quantity
            assert numeric_cents(row.allocated_cost) == expected.allocated_cost_cents
            assert numeric_cents(row.net_proceeds) == expected.net_proceeds_cents
            assert numeric_cents(row.profit_amount) == expected.profit_cents
            assert row.return_pct == Decimal(expected.return_pct)
        assert sum(numeric_cents(row.profit_amount) for row in rows) == 48725
        stored = session.get(PositionState, (account, day_id, "600000.SH", round_id))
        assert stored.quantity == 500 and numeric_cents(stored.remaining_buy_cost) == 500000
        assert session.get(Account, account).published_generation_id is None
