from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup as Group
from src.biz.models.wealth.watchlist_membership import (
    WealthWatchlistMembership as Membership,
)
from src.biz.schemas.wealth.market.watchlist import WatchlistGroupMarkDto
from src.biz.services.wealth.market.stock_search import A_SHARE_EXCHANGES
from src.biz.services.wealth.market.watchlist.watchlist_cursor import WatchlistCursor
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow as Moneyflow
from src.foundation.models.core_serving.equity_daily_bar import (
    EquityDailyBar as DailyBar,
)
from src.foundation.models.core_serving.equity_daily_basic import (
    EquityDailyBasic as DailyBasic,
)
from src.foundation.models.core_serving.security_serving import Security

SORT_COLUMNS = {
    "price": DailyBar.close,
    "changePct": DailyBar.pct_chg,
    "vol": DailyBar.vol,
    "peTtm": DailyBasic.pe_ttm,
    "pb": DailyBasic.pb,
    "volumeRatio": DailyBasic.volume_ratio,
    "turnoverRate": DailyBasic.turnover_rate,
    "netAmount": Moneyflow.net_mf_amount,
}


@dataclass(frozen=True, slots=True)
class WatchlistSortSpec:
    sort_by: str | None
    direction: str | None

    @property
    def pin_rank(self):
        return case((Membership.is_pinned.is_(True), 0), else_=1)

    @property
    def column(self):
        return SORT_COLUMNS[self.sort_by] if self.sort_by is not None else None

    @property
    def missing_rank(self):
        return case((self.column.is_(None), 1), else_=0)

    def order_by(self):
        order = [self.pin_rank.asc()]
        if self.sort_by is not None:
            order += [
                self.missing_rank.asc(),
                self.column.desc() if self.direction == "desc" else self.column.asc(),
            ]
        return [
            *order,
            case((Membership.is_pinned.is_(True), Membership.id)).desc(),
            case((Membership.is_pinned.is_(False), Membership.id)).asc(),
        ]

    def after(self, cursor: WatchlistCursor):
        id_after = (
            Membership.id < cursor.membership_id
            if cursor.pin_rank == 0
            else Membership.id > cursor.membership_id
        )
        within = id_after
        if self.sort_by is not None:
            if cursor.missing_rank == 1:
                within = and_(self.missing_rank == 1, id_after)
            else:
                value_after = (
                    self.column < cursor.value
                    if self.direction == "desc"
                    else self.column > cursor.value
                )
                within = or_(
                    self.missing_rank > cursor.missing_rank,
                    and_(
                        self.missing_rank == cursor.missing_rank,
                        or_(value_after, and_(self.column == cursor.value, id_after)),
                    ),
                )
        return or_(
            self.pin_rank > cursor.pin_rank,
            and_(self.pin_rank == cursor.pin_rank, within),
        )

    def cursor(
        self, row: Mapping[str, Any], *, group_id: int, observed: date | None
    ) -> str:
        value = row["sort_value"] if self.sort_by is not None else None
        return WatchlistCursor(
            group_id,
            self.sort_by,
            self.direction,
            observed,
            0 if row["is_pinned"] else 1,
            int(self.sort_by is not None and value is None),
            Decimal(str(value)) if value is not None else None,
            row["id"],
        ).encode()


class WatchlistItemQuery:
    def resolve_observed_trade_date(
        self, session: Session, *, expected_trade_date: date
    ) -> date | None:
        return session.scalar(
            select(func.max(DailyBar.trade_date)).where(
                DailyBar.trade_date <= expected_trade_date
            )
        )

    def page(
        self,
        session: Session,
        *,
        group_id: int,
        observed: date | None,
        sort: WatchlistSortSpec,
        cursor: WatchlistCursor | None,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        w, d, b, m = Membership, DailyBar, DailyBasic, Moneyflow
        columns = [
            w.id,
            w.ts_code,
            w.created_at,
            w.is_pinned,
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
        ]
        if sort.column is not None:
            columns.append(sort.column.label("sort_value"))
        stmt = (
            select(*columns)
            .select_from(w)
            .outerjoin(Security, Security.ts_code == w.ts_code)
        )
        for model in (d, b, m):
            stmt = stmt.outerjoin(
                model, and_(model.ts_code == w.ts_code, model.trade_date == observed)
            )
        stmt = stmt.where(w.group_id == group_id)
        if cursor is not None:
            stmt = stmt.where(sort.after(cursor))
        return list(
            session.execute(stmt.order_by(*sort.order_by()).limit(limit + 1)).mappings()
        )

    def group_marks(
        self, session: Session, *, user_id: int, ts_codes: Sequence[str]
    ) -> dict[str, list[WatchlistGroupMarkDto]]:
        result: dict[str, list[WatchlistGroupMarkDto]] = {}
        if not ts_codes:
            return result
        rows = session.execute(
            select(Membership.ts_code, Group.id, Group.name, Group.color)
            .join(Group, Group.id == Membership.group_id)
            .where(
                Group.user_id == user_id,
                Group.is_default.is_(False),
                Membership.ts_code.in_(ts_codes),
            )
            .order_by(Group.id)
        ).all()
        for code, group_id, name, color in rows:
            result.setdefault(code, []).append(
                WatchlistGroupMarkDto(groupId=group_id, name=name, color=color)
            )
        return result

    def load_added_codes(
        self, session: Session, *, group_id: int, ts_codes: Sequence[str]
    ) -> set[str]:
        if not ts_codes:
            return set()
        return set(
            session.scalars(
                select(Membership.ts_code).where(
                    Membership.group_id == group_id, Membership.ts_code.in_(ts_codes)
                )
            )
        )

    def load_eligible_ts_codes(
        self, session: Session, ts_codes: Sequence[str]
    ) -> set[str]:
        if not ts_codes:
            return set()
        return set(
            session.scalars(
                select(Security.ts_code).where(
                    Security.ts_code.in_(ts_codes),
                    Security.security_type == "EQUITY",
                    Security.list_status == "L",
                    Security.curr_type == "CNY",
                    Security.exchange.in_(A_SHARE_EXCHANGES),
                )
            )
        )
