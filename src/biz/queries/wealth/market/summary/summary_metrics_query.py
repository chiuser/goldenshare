from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core.market_moneyflow_dc import MarketMoneyflowDc


@dataclass(frozen=True, slots=True)
class SummaryMetricsSnapshot:
    major_index_up_count: int
    major_index_total_count: int
    up_count: int
    down_count: int
    flat_count: int
    turnover_total: Decimal | None
    prev_turnover_total: Decimal | None
    market_net_amount: Decimal | None
    limit_up_count: int
    limit_down_count: int
    broken_limit_count: int


class SummaryMetricsQuery:
    """Load metric facts for market summary cards."""

    def load(
        self,
        session: Session,
        *,
        trade_date: date,
        prev_trade_date: date | None,
        index_codes: list[str],
    ) -> SummaryMetricsSnapshot:
        up_expr = func.sum(case((EquityDailyBar.pct_chg > 0, 1), else_=0))
        down_expr = func.sum(case((EquityDailyBar.pct_chg < 0, 1), else_=0))
        flat_expr = func.sum(case((EquityDailyBar.pct_chg == 0, 1), else_=0))
        turnover_expr = func.sum(EquityDailyBar.amount)

        bar_row = session.execute(
            select(
                up_expr.label("up_count"),
                down_expr.label("down_count"),
                flat_expr.label("flat_count"),
                turnover_expr.label("turnover_total"),
            ).where(EquityDailyBar.trade_date == trade_date)
        ).one()

        prev_turnover_total: Decimal | None = None
        if prev_trade_date is not None:
            prev_turnover_total = session.scalar(
                select(func.sum(EquityDailyBar.amount)).where(EquityDailyBar.trade_date == prev_trade_date)
            )

        market_net_amount = session.scalar(
            select(MarketMoneyflowDc.net_amount).where(MarketMoneyflowDc.trade_date == trade_date).limit(1)
        )

        limit_up_count = session.scalar(
            select(func.count())
            .select_from(
                select(LimitListThs.ts_code)
                .where(
                    LimitListThs.trade_date == trade_date,
                    LimitListThs.limit_type == "涨停池",
                )
                .distinct()
                .subquery()
            )
        )
        limit_down_count = session.scalar(
            select(func.count())
            .select_from(
                select(LimitListThs.ts_code)
                .where(
                    LimitListThs.trade_date == trade_date,
                    LimitListThs.limit_type == "跌停池",
                )
                .distinct()
                .subquery()
            )
        )
        broken_limit_count = session.scalar(
            select(func.count())
            .select_from(
                select(LimitListThs.ts_code)
                .where(
                    LimitListThs.trade_date == trade_date,
                    LimitListThs.limit_type == "炸板池",
                )
                .distinct()
                .subquery()
            )
        )

        index_codes_tuple = tuple(code.strip().upper() for code in index_codes if code.strip())
        major_index_up_count = 0
        major_index_total_count = 0
        if index_codes_tuple:
            index_row = session.execute(
                select(
                    func.sum(case((IndexDailyServing.pct_chg > 0, 1), else_=0)).label("up_count"),
                    func.count(IndexDailyServing.ts_code).label("total_count"),
                ).where(
                    IndexDailyServing.trade_date == trade_date,
                    IndexDailyServing.ts_code.in_(index_codes_tuple),
                )
            ).one()
            major_index_up_count = int(index_row.up_count or 0)
            major_index_total_count = int(index_row.total_count or 0)

        return SummaryMetricsSnapshot(
            major_index_up_count=major_index_up_count,
            major_index_total_count=major_index_total_count,
            up_count=int(bar_row.up_count or 0),
            down_count=int(bar_row.down_count or 0),
            flat_count=int(bar_row.flat_count or 0),
            turnover_total=bar_row.turnover_total,
            prev_turnover_total=prev_turnover_total,
            market_net_amount=market_net_amount,
            limit_up_count=int(limit_up_count or 0),
            limit_down_count=int(limit_down_count or 0),
            broken_limit_count=int(broken_limit_count or 0),
        )
