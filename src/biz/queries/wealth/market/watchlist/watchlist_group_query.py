from __future__ import annotations

from collections.abc import Sequence
from datetime import timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup as Group
from src.biz.models.wealth.watchlist_membership import (
    WealthWatchlistMembership as Membership,
)
from src.biz.schemas.wealth.market.watchlist import (
    WatchlistGroupDto,
    WatchlistStockGroupDto,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import WatchlistError


def group_dto(group: Group, count: int) -> WatchlistGroupDto:
    return WatchlistGroupDto(
        id=group.id,
        name=group.name,
        isDefault=group.is_default,
        color=group.color,
        memberCount=count,
        createdAt=group.created_at.replace(tzinfo=timezone.utc)
        if group.created_at.tzinfo is None
        else group.created_at,
    )


class WatchlistGroupQuery:
    def get_default_group(
        self, session: Session, *, user_id: int, for_update: bool = False
    ) -> Group:
        stmt = select(Group).where(Group.user_id == user_id, Group.is_default.is_(True))
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        group = session.scalar(stmt)
        if group is None:
            raise WatchlistError(
                "WL_WRITE_FAILED" if for_update else "WL_QUERY_FAILED",
                "默认分组数据不完整",
            )
        return group

    def get_owned_group(
        self, session: Session, *, user_id: int, group_id: int, for_update: bool = False
    ) -> Group:
        stmt = select(Group).where(Group.user_id == user_id, Group.id == group_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        group = session.scalar(stmt)
        if group is None:
            raise WatchlistError("WL_GROUP_NOT_FOUND", "分组不存在")
        return group

    def lock_all_groups(self, session: Session, *, user_id: int) -> list[Group]:
        default = self.get_default_group(session, user_id=user_id, for_update=True)
        others = list(
            session.scalars(
                select(Group)
                .where(Group.user_id == user_id, Group.id != default.id)
                .order_by(Group.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        return [default, *others]

    def lock_groups(
        self, session: Session, *, user_id: int, group_ids: Sequence[int]
    ) -> list[Group]:
        return list(
            session.scalars(
                select(Group)
                .where(Group.user_id == user_id, Group.id.in_(group_ids))
                .order_by(Group.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def count_memberships(
        self, session: Session, group_ids: Sequence[int]
    ) -> dict[int, int]:
        counts = dict.fromkeys(group_ids, 0)
        if group_ids:
            counts.update(
                session.execute(
                    select(Membership.group_id, func.count())
                    .where(Membership.group_id.in_(group_ids))
                    .group_by(Membership.group_id)
                ).all()
            )
        return counts

    def list_groups(self, session: Session, *, user_id: int) -> list[WatchlistGroupDto]:
        rows = session.execute(
            select(Group, func.count(Membership.id))
            .outerjoin(Membership, Membership.group_id == Group.id)
            .where(Group.user_id == user_id)
            .group_by(Group.id)
            .order_by(Group.is_default.desc(), Group.id)
        ).all()
        if not rows or not rows[0][0].is_default:
            raise WatchlistError("WL_QUERY_FAILED", "默认分组数据不完整")
        return [group_dto(group, count) for group, count in rows]

    def list_stock_groups(
        self, session: Session, *, user_id: int, ts_code: str
    ) -> list[WatchlistStockGroupDto]:
        rows = session.execute(
            select(Group, Membership.id)
            .outerjoin(
                Membership,
                and_(Membership.group_id == Group.id, Membership.ts_code == ts_code),
            )
            .where(Group.user_id == user_id)
            .order_by(Group.is_default.desc(), Group.id)
        ).all()
        if not rows or not rows[0][0].is_default:
            raise WatchlistError("WL_QUERY_FAILED", "默认分组数据不完整")
        return [
            WatchlistStockGroupDto(
                groupId=g.id,
                name=g.name,
                isDefault=g.is_default,
                color=g.color,
                selected=member_id is not None,
            )
            for g, member_id in rows
        ]

    def find_right_neighbor_or_default(
        self, groups: Sequence[Group], current_id: int
    ) -> int:
        return next(
            (g.id for g in groups if not g.is_default and g.id > current_id),
            groups[0].id,
        )
