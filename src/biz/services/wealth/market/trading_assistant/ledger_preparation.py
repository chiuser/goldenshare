"""Prepare immutable arithmetic facts; no acceptance, commit or return calculation."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from src.biz.queries.wealth.market.trading_assistant.effective_ledger import ReplacementFact
from src.biz.schemas.wealth.market.trading_assistant.accounts import TradeInput, CashFlowInput
from .calculation.fees import FeeSnapshot, FeeAmounts, calculate_trade_fees
from .calculation.precision import parse_money_cents
from .persistence_values import numeric_cents


def scaled_integer(value: Decimal, scale: int) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Expected finite stored decimal")
    numerator, denominator = value.as_integer_ratio()
    result, remainder = divmod(numerator * 10**scale, denominator)
    if remainder or result < 0:
        raise ValueError("Stored fee has invalid precision or sign")
    return result


def fee_snapshot(row) -> FeeSnapshot:
    """Accept the explicitly selected fee version or original trade revision."""
    return FeeSnapshot(scaled_integer(row.commission_rate, 6), numeric_cents(row.minimum_commission),
                       scaled_integer(row.stamp_tax_rate, 4))


@dataclass(frozen=True, slots=True)
class PreparedLedgerChange:
    account_id: UUID
    ledger_id: UUID
    source_revision: int | None
    occurred_on: date
    original_date: date | None
    kind: str
    direction: str
    status: str
    ts_code: str | None
    original_stock: str | None
    quantity: int | None
    price_cents: int | None
    cash_cents: int | None
    fee_version_id: UUID | None
    fees: FeeSnapshot | None
    amounts: FeeAmounts | None
    net_cash_cents: int
    note: str | None

    @property
    def affected_from(self):
        return min(self.occurred_on, self.original_date or self.occurred_on)

    @property
    def affected_stocks(self):
        return tuple(sorted({s for s in (self.ts_code, self.original_stock) if s is not None}))

    @property
    def replacement(self):
        if self.status == "VOID":
            return None
        return ReplacementFact(self.ledger_id, self.occurred_on, self.kind, self.direction,
                               self.quantity, self.ts_code, self.net_cash_cents)

    @property
    def replaced_ledger_id(self):
        return self.ledger_id if self.source_revision is not None else None


def _check_original(original, account_id, ledger_id, kind):
    if original is not None and (original.account_id != account_id or original.ledger_id != ledger_id
                                 or original.kind != kind or original.status != "ACTIVE"):
        raise ValueError("Original revision must be the owned active target")


def prepare_trade(*, account_id: UUID, ledger_id: UUID, data: TradeInput, fee, original=None):
    _check_original(original, account_id, ledger_id, "TRADE")
    if fee.account_id != account_id:
        raise ValueError("Fee version belongs to another account")
    # A correction always uses retained original rates, regardless of current settings.
    selected = original if original is not None else fee
    snapshot = fee_snapshot(selected)
    price = parse_money_cents(data.price)
    amounts = calculate_trade_fees(price * data.quantity, snapshot, data.direction)
    return PreparedLedgerChange(account_id, ledger_id, original.revision if original else None,
        date.fromisoformat(data.tradeDate), original.occurred_on if original else None,
        "TRADE", data.direction, "ACTIVE", data.tsCode, original.ts_code if original else None,
        data.quantity, price, None, selected.fee_version_id, snapshot, amounts,
        amounts.net_cash_change_cents, data.note)


def prepare_cash(*, account_id: UUID, ledger_id: UUID, data: CashFlowInput, original=None):
    _check_original(original, account_id, ledger_id, "CASH_FLOW")
    amount = parse_money_cents(data.amount)
    return PreparedLedgerChange(account_id, ledger_id, original.revision if original else None,
        date.fromisoformat(data.occurredOn), original.occurred_on if original else None,
        "CASH_FLOW", data.direction, "ACTIVE", None, None, None, None, amount, None, None, None,
        amount if data.direction == "IN" else -amount, data.note)


def prepare_void(*, account_id: UUID, ledger_id: UUID, original):
    _check_original(original, account_id, ledger_id, original.kind)
    fees = fee_snapshot(original) if original.kind == "TRADE" else None
    amounts = FeeAmounts(numeric_cents(original.gross_amount), numeric_cents(original.commission_amount),
                        numeric_cents(original.stamp_tax_amount), numeric_cents(original.net_cash_change)) if fees else None
    return PreparedLedgerChange(account_id, ledger_id, original.revision, original.occurred_on,
        original.occurred_on, original.kind, original.direction, "VOID", original.ts_code, original.ts_code,
        original.quantity, numeric_cents(original.price) if fees else None,
        numeric_cents(original.cash_amount) if not fees else None,
        original.fee_version_id, fees, amounts, numeric_cents(original.net_cash_change), original.note)
