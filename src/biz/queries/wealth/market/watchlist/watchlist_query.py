from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.biz.models.wealth.watchlist_item import WealthWatchlistItem
from src.biz.services.wealth.market.stock_search import A_SHARE_EXCHANGES
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security


@dataclass(frozen=True, slots=True)
class WatchlistMembershipRow:
    id: int
    ts_code: str
    created_at: datetime


class WatchlistQuery:
    def count(self, session: Session, *, user_id: int) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(WealthWatchlistItem)
                .where(WealthWatchlistItem.user_id == user_id)
            )
            or 0
        )

    def contains(self, session: Session, *, user_id: int, ts_code: str) -> bool:
        return (
            session.scalar(
                select(WealthWatchlistItem.id).where(
                    WealthWatchlistItem.user_id == user_id,
                    WealthWatchlistItem.ts_code == ts_code,
                )
            )
            is not None
        )

    def list_memberships(
        self, session: Session, *, user_id: int, limit: int, after_id: int | None
    ) -> list[WatchlistMembershipRow]:
        statement = select(
            WealthWatchlistItem.id,
            WealthWatchlistItem.ts_code,
            WealthWatchlistItem.created_at,
        ).where(WealthWatchlistItem.user_id == user_id)
        if after_id is not None:
            statement = statement.where(WealthWatchlistItem.id > after_id)
        rows = session.execute(
            statement.order_by(WealthWatchlistItem.id.asc()).limit(limit + 1)
        ).all()
        return [WatchlistMembershipRow(*row) for row in rows]

    def load_snapshot(
        self,
        session: Session,
        *,
        user_id: int,
        memberships: Sequence[WatchlistMembershipRow],
        observed_trade_date: date | None,
    ) -> list[Mapping[str, Any]]:
        if not memberships:
            return []
        w, d, b, m = (
            WealthWatchlistItem,
            EquityDailyBar,
            EquityDailyBasic,
            EquityMoneyflow,
        )
        statement = (
            select(
                w.id,
                w.ts_code,
                w.created_at,
                Security.name,
                Security.industry,
                Security.list_status,
                d.close.label("price"),
                d.pct_chg,
                d.vol,
                b.pe_ttm,
                b.pb,
                b.volume_ratio,
                b.turnover_rate,
                m.net_mf_amount,
            )
            .select_from(w)
            .outerjoin(Security, Security.ts_code == w.ts_code)
            .outerjoin(
                d, and_(d.ts_code == w.ts_code, d.trade_date == observed_trade_date)
            )
            .outerjoin(
                b, and_(b.ts_code == w.ts_code, b.trade_date == observed_trade_date)
            )
            .outerjoin(
                m, and_(m.ts_code == w.ts_code, m.trade_date == observed_trade_date)
            )
            .where(w.user_id == user_id, w.id.in_([row.id for row in memberships]))
            .order_by(w.id.asc())
        )
        return list(session.execute(statement).mappings())

    def resolve_observed_trade_date(
        self, session: Session, *, expected_trade_date: date
    ) -> date | None:
        return session.scalar(
            select(func.max(EquityDailyBar.trade_date)).where(
                EquityDailyBar.trade_date <= expected_trade_date
            )
        )

    def load_added_codes(
        self, session: Session, *, user_id: int, ts_codes: Sequence[str]
    ) -> set[str]:
        if not ts_codes:
            return set()
        return set(
            session.scalars(
                select(WealthWatchlistItem.ts_code).where(
                    WealthWatchlistItem.user_id == user_id,
                    WealthWatchlistItem.ts_code.in_(ts_codes),
                )
            )
        )

    def load_eligible_security(self, session: Session, *, ts_code: str) -> str | None:
        return session.scalar(
            select(Security.ts_code).where(
                Security.ts_code == ts_code,
                Security.security_type == "EQUITY",
                Security.list_status == "L",
                Security.curr_type == "CNY",
                Security.exchange.in_(A_SHARE_EXCHANGES),
            )
        )
