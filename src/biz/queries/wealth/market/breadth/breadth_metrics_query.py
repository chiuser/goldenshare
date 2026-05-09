from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@dataclass(frozen=True, slots=True)
class BreadthMetricsSnapshot:
    up_count: int
    down_count: int
    flat_count: int
    total_count: int
    red_rate: float


class BreadthMetricsQuery:
    """Load market breadth metrics for a target trading day."""

    def load(self, session: Session, *, trade_date: date) -> BreadthMetricsSnapshot:
        up_expr = func.sum(case((EquityDailyBar.pct_chg > 0, 1), else_=0))
        down_expr = func.sum(case((EquityDailyBar.pct_chg < 0, 1), else_=0))
        flat_expr = func.sum(case((EquityDailyBar.pct_chg == 0, 1), else_=0))

        row = session.execute(
            select(
                up_expr.label("up_count"),
                down_expr.label("down_count"),
                flat_expr.label("flat_count"),
            ).where(
                EquityDailyBar.trade_date == trade_date,
                EquityDailyBar.pct_chg.is_not(None),
            )
        ).one()

        up_count = int(row.up_count or 0)
        down_count = int(row.down_count or 0)
        flat_count = int(row.flat_count or 0)
        total_count = up_count + down_count + flat_count
        red_rate = round((up_count / total_count * 100.0), 2) if total_count > 0 else 0.0
        return BreadthMetricsSnapshot(
            up_count=up_count,
            down_count=down_count,
            flat_count=flat_count,
            total_count=total_count,
            red_rate=red_rate,
        )
