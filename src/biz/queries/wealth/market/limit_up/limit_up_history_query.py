from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.trade_calendar import TradeCalendar


@dataclass(frozen=True, slots=True)
class LimitHistoryPoint:
    trade_date: date
    limit_up_count: int
    limit_down_count: int


class LimitUpHistoryQuery:
    """Load history points for limit-up module."""

    def load_recent_trade_dates(
        self,
        session: Session,
        *,
        end_trade_date: date,
        limit_days: int,
    ) -> list[date]:
        rows = session.scalars(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit_days)
        ).all()
        return list(sorted(rows))

    def load_history_points(
        self,
        session: Session,
        *,
        trade_dates: list[date],
    ) -> list[LimitHistoryPoint]:
        if not trade_dates:
            return []

        rows = session.execute(
            select(
                LimitListThs.trade_date,
                LimitListThs.ts_code,
                LimitListThs.limit_type,
            ).where(
                LimitListThs.trade_date.in_(trade_dates),
                LimitListThs.limit_type.in_(["涨停池", "跌停池"]),
            )
        ).all()

        up_codes_by_date: dict[date, set[str]] = {trade_date: set() for trade_date in trade_dates}
        down_codes_by_date: dict[date, set[str]] = {trade_date: set() for trade_date in trade_dates}
        for row in rows:
            trade_date = row.trade_date
            ts_code = row.ts_code
            limit_type = row.limit_type
            if trade_date is None or ts_code is None:
                continue
            if limit_type == "涨停池":
                up_codes_by_date.setdefault(trade_date, set()).add(ts_code)
            elif limit_type == "跌停池":
                down_codes_by_date.setdefault(trade_date, set()).add(ts_code)

        points: list[LimitHistoryPoint] = []
        for trade_date in sorted(trade_dates):
            points.append(
                LimitHistoryPoint(
                    trade_date=trade_date,
                    limit_up_count=len(up_codes_by_date.get(trade_date, set())),
                    limit_down_count=len(down_codes_by_date.get(trade_date, set())),
                )
            )
        return points
