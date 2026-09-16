"""One translation between typed conditions and retained rule version fields."""
from decimal import Decimal

from src.biz.schemas.wealth.market.trading_assistant.rules import Conditions


def condition_columns(conditions: Conditions):
    price, volume = conditions.priceCondition, conditions.volumeCondition
    return dict(price_operator=price.operator if price else None,
        price_lower=Decimal(price.lower) if price and hasattr(price, "lower") else None,
        price_upper=Decimal(price.upper) if price and hasattr(price, "upper") else None,
        volume_operator=volume.operator if volume else None,
        volume_threshold_lots=Decimal(volume.thresholdLots) if volume else None)


def version_conditions(version):
    price = None
    if version.price_operator is not None:
        price = {"operator": version.price_operator}
        if version.price_lower is not None:
            price["lower"] = format(version.price_lower, ".2f")
        if version.price_upper is not None:
            price["upper"] = format(version.price_upper, ".2f")
    volume = None if version.volume_operator is None else dict(
        operator=version.volume_operator, thresholdLots=format(version.volume_threshold_lots, ".2f"))
    return Conditions(priceCondition=price, volumeCondition=volume)


def condition_summary(conditions: Conditions):
    parts = []
    price, volume = conditions.priceCondition, conditions.volumeCondition
    if price:
        if price.operator == "BETWEEN":
            parts.append(f"价格 {price.lower}–{price.upper}")
        elif price.operator == "LTE":
            parts.append(f"价格 ≤ {price.upper}")
        else:
            parts.append(f"价格 ≥ {price.lower}")
    if volume:
        operator = "≥" if volume.operator == "GTE" else "≤"
        parts.append(f"当日累计成交量 {operator} {volume.thresholdLots} 手")
    return " 且 ".join(parts)
