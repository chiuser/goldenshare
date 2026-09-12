"""New day uses the current pointer, not the fee at market close."""
from datetime import timedelta
from fractions import Fraction
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, setup, DAY, AT, deadline, fact, retire
from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion
from src.biz.services.wealth.market.trading_assistant.new_valuation_fees import new_valuation_fee_version
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.calculation.daily import initialize_position
from src.biz.services.wealth.market.trading_assistant.calculation.returns import value_round
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import fee_snapshot


def test_after_close_update_is_used_once_and_later_updates_do_not_change_frozen_fees(migrated):
    inputs, lease, generation, original = setup(migrated)
    changed, unused = uuid4(), uuid4()
    with Session(migrated) as session, session.begin():
        account = session.get(Account, lease.account_id)
        account.initialized_on = DAY-timedelta(days=30)
        session.get(FeeVersion, original).commission_rate = "0.0005"
        for identity, rate, hour in ((changed, "0.0010", 3), (unused, "0.0020", 6)):
            session.add(FeeVersion(fee_version_id=identity, account_id=lease.account_id,
                commission_rate=rate, minimum_commission="0.00", stamp_tax_rate="0.0005",
                created_at=AT+timedelta(hours=hour)))
        # 18:00 fee is the accepted current pointer. A later audit timestamp
        # does not itself make another fee version current.
        account.current_fee_version_id = changed
    with Session(migrated) as session, session.begin():
        selected = new_valuation_fee_version(session, inputs.execution, lease,
            generation_id=generation, business_date=DAY, deadline=deadline())
        assert selected == changed
        result = value_round(initialize_position(1000, 1000, 1000), Fraction(10),
            fee_snapshot(session.get(FeeVersion, selected)))
        assert result.liquidation.commission_cents == 1000  # 10.00, not 5.00.
        inputs.save_valuation_page(session, lease, generation_id=generation,
            facts=(fact(price="10.00"),), fee_version_id=selected, valuation_at=AT,
            after_stock=None, deadline=deadline())
    with Session(migrated) as session, session.begin():
        session.get(Account, lease.account_id).current_fee_version_id = unused
    with Session(migrated) as session, session.begin():
        with pytest.raises(CalculationInputMismatch, match="Restore"):
            new_valuation_fee_version(session, inputs.execution, lease,
                generation_id=generation, business_date=DAY, deadline=deadline())
        frozen = inputs.read_valuation_page(session, lease, generation_id=generation,
            trade_date=DAY, page_key="000001.SZ", deadline=deadline())
        assert frozen.fee_version_id == changed
        assert session.get(Account, lease.account_id).calculation_target_version == 1
    retire(migrated, lease)
