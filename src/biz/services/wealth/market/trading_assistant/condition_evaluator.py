"""Pure same-checkpoint rule evaluation; not a coverage or final-result decision."""

from dataclasses import dataclass
from decimal import Decimal

from src.biz.schemas.wealth.market.trading_assistant.rules import Conditions
from src.biz.schemas.wealth.market.trading_assistant.value_types import decimal_cents


@dataclass(frozen=True)
class CheckpointEvaluation:
    price_satisfied: bool | None
    volume_satisfied: bool | None
    satisfied: bool


def evaluate_checkpoint(
    condition: Conditions,
    price: Decimal | None,
    cumulative_shares: int | None,
) -> CheckpointEvaluation:
    """Compare only enabled fields supplied for one already-validated checkpoint.

    The caller owns minute identity, prefix coverage, version selection and time
    bounds. Missing/invalid required data raises; it must never become a false
    final result. Prices are source-precision QFQ decimals, never display values.
    """
    price_satisfied = None
    volume_satisfied = None
    price_condition = condition.priceCondition
    if price_condition is not None:
        if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
            raise ValueError("Enabled price condition requires a positive finite Decimal")
        if price_condition.operator == "LTE":
            price_satisfied = price <= Decimal(price_condition.upper)
        elif price_condition.operator == "GTE":
            price_satisfied = price >= Decimal(price_condition.lower)
        else:
            price_satisfied = (
                Decimal(price_condition.lower) <= price <= Decimal(price_condition.upper)
            )
    volume_condition = condition.volumeCondition
    if volume_condition is not None:
        if type(cumulative_shares) is not int or cumulative_shares < 0:
            raise ValueError("Enabled volume condition requires nonnegative integer shares")
        # A lot is 100 shares: the existing exact two-decimal parser produces
        # precisely this integer, without Decimal context or float arithmetic.
        threshold_shares = decimal_cents(volume_condition.thresholdLots)
        if volume_condition.operator == "LTE":
            volume_satisfied = cumulative_shares <= threshold_shares
        else:
            volume_satisfied = cumulative_shares >= threshold_shares
    return CheckpointEvaluation(
        price_satisfied=price_satisfied,
        volume_satisfied=volume_satisfied,
        satisfied=price_satisfied is not False and volume_satisfied is not False,
    )
