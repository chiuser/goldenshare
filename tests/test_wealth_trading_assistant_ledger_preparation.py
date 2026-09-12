"""Fixed-fee candidate arithmetic; these tests do not claim final acceptance."""
from datetime import date
from decimal import Decimal, localcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.biz.schemas.wealth.market.trading_assistant.accounts import TradeInput, CashFlowInput
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import (
    prepare_trade, prepare_cash, prepare_void, scaled_integer,
)


def fee(account, *, rate="0.0003", minimum="5.00", tax="0.0005"):
    return SimpleNamespace(account_id=account, fee_version_id=uuid4(), commission_rate=Decimal(rate),
                           minimum_commission=Decimal(minimum), stamp_tax_rate=Decimal(tax))


def test_correction_uses_original_fee_snapshot_and_both_affected_stocks():
    account, record = uuid4(), uuid4()
    original = SimpleNamespace(**vars(fee(account)), ledger_id=record, revision=2, kind="TRADE",
        status="ACTIVE", occurred_on=date(2026,9,10), ts_code="600000.SH")
    current = fee(account, rate="0.01", minimum="100.00", tax="0.01")
    data = TradeInput(tsCode="000001.SZ",direction="SELL",tradeDate="2026-09-11",price="10.00",quantity=1000)
    change = prepare_trade(account_id=account,ledger_id=record,data=data,fee=current,original=original)
    assert change.amounts.commission_cents == 500 and change.amounts.stamp_tax_cents == 500
    assert change.net_cash_cents == 999000 and change.fee_version_id == original.fee_version_id
    assert change.affected_stocks == ("000001.SZ","600000.SH")
    assert change.affected_from == date(2026,9,10)
    assert change.replaced_ledger_id == record and change.replacement.ledger_id == record
    assert original.ts_code == "600000.SH" and original.revision == 2
    fresh = prepare_trade(account_id=account,ledger_id=uuid4(),data=data,fee=current)
    assert fresh.fee_version_id == current.fee_version_id
    assert fresh.amounts.commission_cents == 10000 and fresh.amounts.stamp_tax_cents == 10000


def test_buy_is_tax_free_and_large_arithmetic_ignores_decimal_context():
    account = uuid4()
    data = TradeInput(tsCode="600000.SH",direction="BUY",tradeDate="2026-09-11",
                     price="999999999999999999.99",quantity=9007199254740991)
    with localcontext() as context:
        context.prec = 2
        change = prepare_trade(account_id=account,ledger_id=uuid4(),data=data,fee=fee(account))
    assert change.amounts.gross_cents == 99999999999999999999 * data.quantity
    assert change.amounts.stamp_tax_cents == 0
    assert change.net_cash_cents == -(change.amounts.gross_cents+change.amounts.commission_cents)


def test_cash_replacement_and_void_are_not_opposite_cash_entries():
    account, record = uuid4(), uuid4()
    original = SimpleNamespace(account_id=account,ledger_id=record,revision=1,kind="CASH_FLOW",status="ACTIVE",
        occurred_on=date(2026,9,11),direction="IN",net_cash_change=Decimal("100.00"),cash_amount=Decimal("100.00"),
        ts_code=None,quantity=None,fee_version_id=None,note="原记录")
    changed = prepare_cash(account_id=account,ledger_id=record,
        data=CashFlowInput(direction="OUT",occurredOn="2026-09-10",amount="50.00"),original=original)
    assert changed.net_cash_cents == -5000 and changed.replacement.net_cash_cents == -5000
    assert changed.affected_from == date(2026,9,10) and changed.affected_stocks == ()
    voided = prepare_void(account_id=account,ledger_id=record,original=original)
    assert voided.replacement is None and voided.replaced_ledger_id == record
    assert voided.direction == "IN" and voided.net_cash_cents == 10000 and voided.status == "VOID"
    with pytest.raises(ValueError):
        prepare_void(account_id=uuid4(),ledger_id=record,original=original)


@pytest.mark.parametrize("value", ["NaN","Infinity","-0.01","0.0000001"])
def test_stored_rate_precision_is_not_silently_rounded(value):
    with pytest.raises(ValueError):
        scaled_integer(Decimal(value),6)
