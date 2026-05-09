from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


@dataclass(frozen=True, slots=True)
class MarketStyleCurrentSnapshot:
    large_pct: float | None
    small_pct: float | None
    median_pct: float | None

    @property
    def has_any_value(self) -> bool:
        return any(item is not None for item in (self.large_pct, self.small_pct, self.median_pct))


@dataclass(frozen=True, slots=True)
class MarketStyleHistoryPoint:
    trade_date: date
    large_pct: float | None
    small_pct: float | None
    median_pct: float | None


class MarketStyleQuery:
    """Load market style current snapshot and history points."""

    def load_recent_trade_dates(
        self,
        session: Session,
        *,
        end_trade_date: date,
        limit_days: int,
    ) -> list[date]:
        rows = session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit_days)
        ).scalars().all()
        return list(reversed(rows))

    def load_current_snapshot(
        self,
        session: Session,
        *,
        trade_date: date,
        large_index_code: str,
        small_index_code: str,
    ) -> MarketStyleCurrentSnapshot:
        index_rows = session.execute(
            select(IndexDailyServing.ts_code, IndexDailyServing.pct_chg).where(
                IndexDailyServing.trade_date == trade_date,
                IndexDailyServing.ts_code.in_((large_index_code, small_index_code)),
            )
        ).all()
        index_map: dict[str, float | None] = {
            row.ts_code: (float(row.pct_chg) if row.pct_chg is not None else None) for row in index_rows
        }

        median_series = session.execute(
            select(EquityDailyBar.pct_chg)
            .where(
                EquityDailyBar.trade_date == trade_date,
                EquityDailyBar.pct_chg.is_not(None),
            )
            .order_by(EquityDailyBar.pct_chg.asc())
        ).scalars().all()
        median_pct = self._discrete_median(median_series)

        return MarketStyleCurrentSnapshot(
            large_pct=index_map.get(large_index_code),
            small_pct=index_map.get(small_index_code),
            median_pct=median_pct,
        )

    def load_history_points(
        self,
        session: Session,
        *,
        trade_dates: list[date],
        large_index_code: str,
        small_index_code: str,
    ) -> list[MarketStyleHistoryPoint]:
        if not trade_dates:
            return []

        index_rows = session.execute(
            select(
                IndexDailyServing.trade_date,
                IndexDailyServing.ts_code,
                IndexDailyServing.pct_chg,
            ).where(
                IndexDailyServing.trade_date.in_(tuple(trade_dates)),
                IndexDailyServing.ts_code.in_((large_index_code, small_index_code)),
            )
        ).all()
        index_by_date: dict[date, dict[str, float | None]] = defaultdict(dict)
        for row in index_rows:
            index_by_date[row.trade_date][row.ts_code] = float(row.pct_chg) if row.pct_chg is not None else None

        equity_rows = session.execute(
            select(EquityDailyBar.trade_date, EquityDailyBar.pct_chg).where(
                EquityDailyBar.trade_date.in_(tuple(trade_dates)),
                EquityDailyBar.pct_chg.is_not(None),
            )
            .order_by(EquityDailyBar.trade_date.asc(), EquityDailyBar.pct_chg.asc())
        ).all()
        median_inputs: dict[date, list[Decimal]] = defaultdict(list)
        for row in equity_rows:
            if row.pct_chg is not None:
                median_inputs[row.trade_date].append(row.pct_chg)
        median_by_date = {
            trade_date: self._discrete_median(values)
            for trade_date, values in median_inputs.items()
        }

        points: list[MarketStyleHistoryPoint] = []
        for trade_day in trade_dates:
            index_values = index_by_date.get(trade_day, {})
            points.append(
                MarketStyleHistoryPoint(
                    trade_date=trade_day,
                    large_pct=index_values.get(large_index_code),
                    small_pct=index_values.get(small_index_code),
                    median_pct=median_by_date.get(trade_day),
                )
            )
        return points

    @staticmethod
    def _discrete_median(values: list[Decimal]) -> float | None:
        if not values:
            return None
        middle_index = (len(values) - 1) // 2
        return float(values[middle_index])
