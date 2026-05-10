from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.dc_hot import DcHot
from src.foundation.models.core_serving.security_serving import Security


HotBoardKey = Literal["popularity", "surge"]


@dataclass(frozen=True, slots=True)
class DcHotRankingRow:
    ts_code: str
    subject_name: str | None
    latest_price: Decimal | None
    change_pct: Decimal | None
    rank: int | None


@dataclass(frozen=True, slots=True)
class DcHotRankingResult:
    rows: list[DcHotRankingRow]
    observed_trade_date: date | None
    used_fallback: bool


class LeaderboardDcHotRankingsQuery:
    """Load popularity/surge rows from dc_hot with strict/fallback behavior."""

    _A_STOCK_MARKET_VALUE = "A股市场"

    _HOT_TYPE_MAP: dict[HotBoardKey, str] = {
        "popularity": "人气榜",
        "surge": "飙升榜",
    }

    def load_board_rows(
        self,
        session: Session,
        *,
        expected_trade_date: date,
        board_key: HotBoardKey,
        limit: int,
        strict_hot_date: bool,
    ) -> DcHotRankingResult:
        hot_type = self._HOT_TYPE_MAP[board_key]
        rows = self._load_rows_by_date(session, trade_date=expected_trade_date, hot_type=hot_type, limit=limit)
        if rows:
            return DcHotRankingResult(
                rows=rows,
                observed_trade_date=expected_trade_date,
                used_fallback=False,
            )

        latest_trade_date = self._load_latest_trade_date(session, hot_type=hot_type, end_trade_date=expected_trade_date)
        if strict_hot_date:
            return DcHotRankingResult(
                rows=[],
                observed_trade_date=latest_trade_date,
                used_fallback=False,
            )

        if latest_trade_date is None:
            return DcHotRankingResult(
                rows=[],
                observed_trade_date=None,
                used_fallback=False,
            )

        fallback_rows = self._load_rows_by_date(session, trade_date=latest_trade_date, hot_type=hot_type, limit=limit)
        return DcHotRankingResult(
            rows=fallback_rows,
            observed_trade_date=latest_trade_date,
            used_fallback=latest_trade_date != expected_trade_date,
        )

    def _load_rows_by_date(
        self,
        session: Session,
        *,
        trade_date: date,
        hot_type: str,
        limit: int,
    ) -> list[DcHotRankingRow]:
        normalized_rank_time = func.nullif(func.trim(DcHot.rank_time), "")
        ranked_subquery = (
            select(
                DcHot.ts_code.label("ts_code"),
                func.coalesce(DcHot.ts_name, Security.name).label("subject_name"),
                DcHot.current_price.label("latest_price"),
                DcHot.pct_change.label("change_pct"),
                DcHot.rank.label("hot_rank"),
                normalized_rank_time.label("hot_rank_time"),
                func.row_number()
                .over(
                    partition_by=DcHot.ts_code,
                    order_by=(
                        DcHot.rank.is_(None),
                        DcHot.rank.asc(),
                        normalized_rank_time.is_(None),
                        normalized_rank_time.desc(),
                        DcHot.ts_code.asc(),
                    ),
                )
                .label("rn"),
            )
            .outerjoin(Security, Security.ts_code == DcHot.ts_code)
            .where(
                DcHot.trade_date == trade_date,
                DcHot.query_hot_type == hot_type,
                DcHot.query_market == self._A_STOCK_MARKET_VALUE,
                ~and_(DcHot.rank.is_(None), normalized_rank_time.is_(None)),
            )
            .subquery()
        )
        rows = session.execute(
            select(
                ranked_subquery.c.ts_code,
                ranked_subquery.c.subject_name,
                ranked_subquery.c.latest_price,
                ranked_subquery.c.change_pct,
                ranked_subquery.c.hot_rank,
                ranked_subquery.c.hot_rank_time,
            )
            .where(ranked_subquery.c.rn == 1)
            .order_by(
                ranked_subquery.c.hot_rank.is_(None),
                ranked_subquery.c.hot_rank.asc(),
                ranked_subquery.c.hot_rank_time.is_(None),
                ranked_subquery.c.hot_rank_time.desc(),
                ranked_subquery.c.ts_code.asc(),
            )
            .limit(limit)
        ).all()
        return [
            DcHotRankingRow(
                ts_code=row.ts_code,
                subject_name=row.subject_name,
                latest_price=row.latest_price,
                change_pct=row.change_pct,
                rank=row.hot_rank,
            )
            for row in rows
        ]

    @staticmethod
    def _load_latest_trade_date(
        session: Session,
        *,
        hot_type: str,
        end_trade_date: date,
    ) -> date | None:
        normalized_rank_time = func.nullif(func.trim(DcHot.rank_time), "")
        return session.scalar(
            select(func.max(DcHot.trade_date)).where(
                DcHot.query_hot_type == hot_type,
                DcHot.trade_date <= end_trade_date,
                DcHot.query_market == LeaderboardDcHotRankingsQuery._A_STOCK_MARKET_VALUE,
                ~and_(DcHot.rank.is_(None), normalized_rank_time.is_(None)),
            )
        )
