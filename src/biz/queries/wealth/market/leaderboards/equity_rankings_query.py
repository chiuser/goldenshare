from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security


EquityBoardKey = Literal["gainers", "losers", "amount", "turnover", "volumeRatio"]


@dataclass(frozen=True, slots=True)
class EquityRankingRow:
    ts_code: str
    subject_name: str | None
    latest_price: Decimal | None
    change_pct: Decimal | None
    turnover_rate: Decimal | None
    volume_ratio: Decimal | None
    volume: Decimal | None
    amount: Decimal | None


class LeaderboardEquityRankingsQuery:
    """Load stock leaderboard rows from equity daily serving tables."""

    def load_board_rows(
        self,
        session: Session,
        *,
        trade_date: date,
        board_key: EquityBoardKey,
        stock_pool_codes: set[str],
        limit: int,
    ) -> list[EquityRankingRow]:
        if not stock_pool_codes:
            return []

        stmt = (
            select(
                EquityDailyBar.ts_code,
                Security.name.label("subject_name"),
                EquityDailyBar.close.label("latest_price"),
                EquityDailyBar.pct_chg.label("change_pct"),
                EquityDailyBasic.turnover_rate.label("turnover_rate"),
                EquityDailyBasic.volume_ratio.label("volume_ratio"),
                EquityDailyBar.vol.label("volume"),
                EquityDailyBar.amount.label("amount"),
            )
            .join(Security, Security.ts_code == EquityDailyBar.ts_code)
            .outerjoin(
                EquityDailyBasic,
                (EquityDailyBasic.ts_code == EquityDailyBar.ts_code)
                & (EquityDailyBasic.trade_date == EquityDailyBar.trade_date),
            )
            .where(
                EquityDailyBar.trade_date == trade_date,
                EquityDailyBar.ts_code.in_(tuple(stock_pool_codes)),
                EquityDailyBar.amount.is_not(None),
                EquityDailyBar.amount > 0,
            )
            .order_by(*self._build_ordering(board_key))
            .limit(limit)
        )
        rows = session.execute(stmt).all()
        return [
            EquityRankingRow(
                ts_code=row.ts_code,
                subject_name=row.subject_name,
                latest_price=row.latest_price,
                change_pct=row.change_pct,
                turnover_rate=row.turnover_rate,
                volume_ratio=row.volume_ratio,
                volume=row.volume,
                amount=row.amount,
            )
            for row in rows
        ]

    @staticmethod
    def _build_ordering(board_key: EquityBoardKey):
        if board_key == "gainers":
            return (
                EquityDailyBar.pct_chg.is_(None),
                EquityDailyBar.pct_chg.desc(),
                EquityDailyBar.amount.desc(),
                EquityDailyBar.ts_code.asc(),
            )
        if board_key == "losers":
            return (
                EquityDailyBar.pct_chg.is_(None),
                EquityDailyBar.pct_chg.asc(),
                EquityDailyBar.amount.desc(),
                EquityDailyBar.ts_code.asc(),
            )
        if board_key == "amount":
            return (
                EquityDailyBar.amount.is_(None),
                EquityDailyBar.amount.desc(),
                EquityDailyBar.ts_code.asc(),
            )
        if board_key == "turnover":
            return (
                EquityDailyBasic.turnover_rate.is_(None),
                EquityDailyBasic.turnover_rate.desc(),
                EquityDailyBar.amount.desc(),
                EquityDailyBar.ts_code.asc(),
            )
        if board_key == "volumeRatio":
            return (
                EquityDailyBasic.volume_ratio.is_(None),
                EquityDailyBasic.volume_ratio.desc(),
                EquityDailyBar.amount.desc(),
                EquityDailyBar.ts_code.asc(),
            )
        raise ValueError(f"unsupported equity board key: {board_key}")

