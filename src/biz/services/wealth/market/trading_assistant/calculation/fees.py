"""Per-trade fees and valuation; snapshots are selected by the caller."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from .precision import CalculationInvariantError, parse_money_cents, require_integer, round_ratio_half_up


@dataclass(frozen=True, slots=True)
class FeeSnapshot:
    commission_rate_millionths: int
    minimum_commission_cents: int
    stamp_tax_rate_ten_thousandths: int

    def __post_init__(self) -> None:
        for value in (self.commission_rate_millionths, self.minimum_commission_cents,
                      self.stamp_tax_rate_ten_thousandths):
            require_integer(value, minimum=0)
        if self.stamp_tax_rate_ten_thousandths > 10000:
            raise CalculationInvariantError("Stamp tax exceeds 100 percent")

    @classmethod
    def from_inputs(cls, commission_rate_wan: str, minimum_commission: str,
                    stamp_tax_rate_pct: str) -> "FeeSnapshot":
        return cls(parse_money_cents(commission_rate_wan), parse_money_cents(minimum_commission),
                   parse_money_cents(stamp_tax_rate_pct))


@dataclass(frozen=True, slots=True)
class FeeAmounts:
    gross_cents: int
    commission_cents: int
    stamp_tax_cents: int
    net_cash_change_cents: int


def calculate_trade_fees(gross_cents: int, fee_snapshot: FeeSnapshot,
                         direction: Literal["BUY", "SELL"]) -> FeeAmounts:
    require_integer(gross_cents, minimum=1)
    if direction not in ("BUY", "SELL"):
        raise CalculationInvariantError("Unknown trade direction")
    commission = max(fee_snapshot.minimum_commission_cents,
                     round_ratio_half_up(gross_cents * fee_snapshot.commission_rate_millionths, 1000000))
    tax = (round_ratio_half_up(gross_cents * fee_snapshot.stamp_tax_rate_ten_thousandths, 10000)
           if direction == "SELL" else 0)
    net = gross_cents - commission - tax if direction == "SELL" else -(gross_cents + commission)
    return FeeAmounts(gross_cents, commission, tax, net)


def estimate_liquidation(quantity: int, price: Fraction, fees: FeeSnapshot) -> FeeAmounts:
    """price is the exact source price in yuan, not a two-decimal display price."""
    require_integer(quantity, minimum=0)
    if not isinstance(price, Fraction) or price < 0:
        raise CalculationInvariantError("Expected nonnegative exact source price")
    if quantity == 0:
        return FeeAmounts(0, 0, 0, 0)
    if price == 0:
        raise CalculationInvariantError("Held stock has no valid valuation price")
    exact_cents = price * quantity * 100
    gross = round_ratio_half_up(exact_cents.numerator, exact_cents.denominator)
    commission_ratio = exact_cents * Fraction(fees.commission_rate_millionths, 1000000)
    commission = max(fees.minimum_commission_cents,
                     round_ratio_half_up(commission_ratio.numerator, commission_ratio.denominator))
    tax_ratio = exact_cents * Fraction(fees.stamp_tax_rate_ten_thousandths, 10000)
    tax = round_ratio_half_up(tax_ratio.numerator, tax_ratio.denominator)
    return FeeAmounts(gross, commission, tax, gross - commission - tax)
