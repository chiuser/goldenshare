from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot


_INTRADAY_TIME_POINTS = ("09:30", "10:30", "11:30", "14:00", "15:00")


@dataclass(frozen=True, slots=True)
class TurnoverMetricsSnapshot:
    today_amount: float | None
    prev_amount: float | None
    amount_delta: float | None
    amount_delta_pct: float | None
    avg5d_amount: float | None
    avg20d_amount: float | None

    @property
    def has_any_value(self) -> bool:
        return any(
            value is not None
            for value in (
                self.today_amount,
                self.prev_amount,
                self.amount_delta,
                self.amount_delta_pct,
                self.avg5d_amount,
                self.avg20d_amount,
            )
        )


@dataclass(frozen=True, slots=True)
class TurnoverHistoryPoint:
    trade_date: date
    amount: float | None


@dataclass(frozen=True, slots=True)
class TurnoverIntradayPoint:
    time: str
    cum_amount: float | None


@dataclass(frozen=True, slots=True)
class TurnoverIntradayResult:
    points: list[TurnoverIntradayPoint]
    has_points: bool


class TurnoverQuery:
    """Load turnover metrics, history and intraday cumulative points."""

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

    def load_metrics(
        self,
        session: Session,
        *,
        trade_date: date,
        prev_trade_date: date | None,
    ) -> TurnoverMetricsSnapshot:
        today_amount = self._load_daily_total(session, trade_date=trade_date)
        prev_amount = self._load_daily_total(session, trade_date=prev_trade_date) if prev_trade_date else None

        recent_20_trade_dates = self.load_recent_trade_dates(
            session,
            end_trade_date=trade_date,
            limit_days=20,
        )
        amounts_map = self.load_amounts_by_trade_dates(session, trade_dates=recent_20_trade_dates)
        recent_5_trade_dates = recent_20_trade_dates[-5:]
        avg5d_amount = self._average_amount(amounts_map=amounts_map, trade_dates=recent_5_trade_dates)
        avg20d_amount = self._average_amount(amounts_map=amounts_map, trade_dates=recent_20_trade_dates)

        amount_delta: float | None = None
        amount_delta_pct: float | None = None
        if today_amount is not None and prev_amount is not None:
            amount_delta = today_amount - prev_amount
            if prev_amount != 0:
                amount_delta_pct = float(
                    (Decimal(str(amount_delta)) / Decimal(str(prev_amount)) * Decimal("100")).quantize(
                        Decimal("0.01"),
                        rounding=ROUND_HALF_UP,
                    )
                )

        return TurnoverMetricsSnapshot(
            today_amount=today_amount,
            prev_amount=prev_amount,
            amount_delta=amount_delta,
            amount_delta_pct=amount_delta_pct,
            avg5d_amount=avg5d_amount,
            avg20d_amount=avg20d_amount,
        )

    def load_history_points(
        self,
        session: Session,
        *,
        trade_dates: list[date],
    ) -> list[TurnoverHistoryPoint]:
        amounts_map = self.load_amounts_by_trade_dates(session, trade_dates=trade_dates)
        return [
            TurnoverHistoryPoint(
                trade_date=trade_day,
                amount=amounts_map.get(trade_day),
            )
            for trade_day in trade_dates
        ]

    def load_intraday_cumulative(
        self,
        session: Session,
        *,
        trade_date: date,
        freq: int = 30,
    ) -> TurnoverIntradayResult:
        snapshot = session.scalar(
            select(WealthMarketTurnoverSnapshot).where(
                WealthMarketTurnoverSnapshot.type == "stock",
                WealthMarketTurnoverSnapshot.market == "CN_A",
                WealthMarketTurnoverSnapshot.trade_date == trade_date,
                WealthMarketTurnoverSnapshot.freq == freq,
                WealthMarketTurnoverSnapshot.build_status == "READY",
            )
        )
        if snapshot is None:
            return TurnoverIntradayResult(
                points=[TurnoverIntradayPoint(time=time_label, cum_amount=None) for time_label in _INTRADAY_TIME_POINTS],
                has_points=False,
            )

        raw_points = snapshot.points_json if isinstance(snapshot.points_json, list) else []
        normalized_rows: list[tuple[datetime, float]] = []
        for point in raw_points:
            if not isinstance(point, dict):
                continue
            trade_time_ts = point.get("tradeTimeTs")
            if not isinstance(trade_time_ts, str) or not trade_time_ts:
                continue
            try:
                point_time = datetime.fromisoformat(trade_time_ts)
            except ValueError:
                continue
            amount = point.get("amount")
            try:
                amount_value = float(amount) if amount is not None else 0.0
            except (TypeError, ValueError):
                amount_value = 0.0
            normalized_rows.append((point_time, amount_value))

        normalized_rows.sort(key=lambda item: item[0])
        has_points = bool(normalized_rows)

        cumulative = 0.0
        row_index = 0
        points: list[TurnoverIntradayPoint] = []
        for point_label in _INTRADAY_TIME_POINTS:
            point_time = datetime.combine(trade_date, time.fromisoformat(point_label))
            while row_index < len(normalized_rows) and normalized_rows[row_index][0] <= point_time:
                cumulative += normalized_rows[row_index][1]
                row_index += 1
            points.append(TurnoverIntradayPoint(time=point_label, cum_amount=cumulative if has_points else None))
        return TurnoverIntradayResult(points=points, has_points=has_points)

    def load_amounts_by_trade_dates(self, session: Session, *, trade_dates: list[date]) -> dict[date, float]:
        if not trade_dates:
            return {}
        rows = session.execute(
            select(EquityDailyBar.trade_date, func.sum(EquityDailyBar.amount).label("amount"))
            .where(
                EquityDailyBar.trade_date.in_(tuple(trade_dates))
            )
            .group_by(EquityDailyBar.trade_date)
        ).all()
        return {
            row.trade_date: float(row.amount) if row.amount is not None else 0.0
            for row in rows
        }

    @staticmethod
    def _load_daily_total(session: Session, *, trade_date: date | None) -> float | None:
        if trade_date is None:
            return None
        amount = session.scalar(
            select(func.sum(EquityDailyBar.amount)).where(EquityDailyBar.trade_date == trade_date)
        )
        return float(amount) if amount is not None else None

    @staticmethod
    def _average_amount(*, amounts_map: dict[date, float], trade_dates: list[date]) -> float | None:
        values = [amounts_map[trade_day] for trade_day in trade_dates if trade_day in amounts_map]
        if not values:
            return None
        return float(sum(values) / len(values))
