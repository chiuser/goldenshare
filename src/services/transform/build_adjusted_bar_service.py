from __future__ import annotations

from datetime import date
from decimal import Decimal


class BuildAdjustedBarService:
    def calculate_qfq_price(
        self,
        raw_price: Decimal | None,
        adj_factor: Decimal | None,
        end_adj_factor: Decimal | None,
    ) -> Decimal | None:
        if raw_price is None or adj_factor is None or end_adj_factor in (None, Decimal("0")):
            return None
        return (raw_price * adj_factor / end_adj_factor).quantize(Decimal("0.0001"))

    def build_view_sql(self) -> str:
        return "REFRESH MATERIALIZED VIEW dm.equity_daily_snapshot"
