from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


_FOUR_DECIMAL_PLACES = Decimal("0.0001")


def calculate_contribution_point(
    *,
    index_pre_close: Any,
    weight: Any,
    constituent_pct_chg: Any,
) -> float | None:
    if index_pre_close is None or weight is None or constituent_pct_chg is None:
        return None
    contribution = (
        Decimal(str(index_pre_close))
        * (Decimal(str(weight)) / Decimal("100"))
        * (Decimal(str(constituent_pct_chg)) / Decimal("100"))
    )
    return float(contribution.quantize(_FOUR_DECIMAL_PLACES, rounding=ROUND_HALF_UP))
