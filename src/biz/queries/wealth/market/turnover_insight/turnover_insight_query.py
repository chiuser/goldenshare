from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import (
    WealthMarketTurnoverSnapshot,
)


_MAX_CANDIDATES = 4


@dataclass(frozen=True, slots=True)
class TurnoverInsightSnapshotRow:
    trade_date: date
    pretrade_date: date | None
    latest_trade_time: datetime
    total_amount_thousand_yuan: Decimal
    source_row_count: int
    security_count: int
    points: tuple[dict[str, object], ...]
    built_at: datetime


@dataclass(frozen=True, slots=True)
class TurnoverInsightCandidateSet:
    expected_trade_date: date
    expected_prev_trade_date: date | None
    rows: tuple[TurnoverInsightSnapshotRow, ...]


class TurnoverInsightQuery:
    """Load a bounded set of one-minute ready snapshots."""

    def load_candidates(
        self,
        session: Session,
        *,
        expected_trade_date: date,
        expected_prev_trade_date: date | None,
    ) -> TurnoverInsightCandidateSet:
        statement = (
            select(
                WealthMarketTurnoverSnapshot.trade_date,
                TradeCalendar.pretrade_date,
                WealthMarketTurnoverSnapshot.latest_trade_time,
                WealthMarketTurnoverSnapshot.total_amount,
                WealthMarketTurnoverSnapshot.source_row_count,
                WealthMarketTurnoverSnapshot.security_count,
                WealthMarketTurnoverSnapshot.points_json,
                WealthMarketTurnoverSnapshot.built_at,
            )
            .outerjoin(
                TradeCalendar,
                and_(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.trade_date == WealthMarketTurnoverSnapshot.trade_date,
                ),
            )
            .where(
                WealthMarketTurnoverSnapshot.type == "stock",
                WealthMarketTurnoverSnapshot.market == "CN_A",
                WealthMarketTurnoverSnapshot.freq == 1,
                WealthMarketTurnoverSnapshot.build_status == "READY",
                WealthMarketTurnoverSnapshot.trade_date <= expected_trade_date,
            )
            .order_by(WealthMarketTurnoverSnapshot.trade_date.desc())
            .limit(_MAX_CANDIDATES)
        )
        rows = session.execute(statement).all()
        return TurnoverInsightCandidateSet(
            expected_trade_date=expected_trade_date,
            expected_prev_trade_date=expected_prev_trade_date,
            rows=tuple(
                TurnoverInsightSnapshotRow(
                    trade_date=row.trade_date,
                    pretrade_date=row.pretrade_date,
                    latest_trade_time=row.latest_trade_time,
                    total_amount_thousand_yuan=Decimal(str(row.total_amount)),
                    source_row_count=int(row.source_row_count),
                    security_count=int(row.security_count),
                    points=tuple(row.points_json) if isinstance(row.points_json, list) else tuple(),
                    built_at=row.built_at,
                )
                for row in rows
            ),
        )
