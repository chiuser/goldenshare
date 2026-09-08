from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import logging
import sqlite3
from typing import TypeVar

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup as Group
from src.biz.models.wealth.watchlist_membership import (
    WealthWatchlistMembership as Membership,
)
from src.biz.queries.wealth.market.watchlist.watchlist_group_query import (
    WatchlistGroupQuery,
    group_dto,
)
from src.biz.queries.wealth.market.watchlist.watchlist_item_query import (
    WatchlistItemQuery,
)
from src.biz.schemas.wealth.market.watchlist import (
    WatchlistAddResponseDto,
    WatchlistBatchActionResponseDto,
    WatchlistGroupCountDto,
    WatchlistGroupDeleteResponseDto,
    WatchlistGroupMutationResponseDto,
    WatchlistStockGroupsReplaceResponseDto,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    MAX_API_ID,
    MAX_BATCH_MEMBERSHIPS,
    MAX_CUSTOM_GROUPS,
    MAX_GROUPS,
    WatchlistError,
    WatchlistPolicy,
    WatchlistRequestError,
    normalize_group_name,
)

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


def _name_conflict(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    if diagnostic is not None:
        return diagnostic.constraint_name == "uq_wealth_watchlist_group_user_name"
    return (
        getattr(error.orig, "sqlite_errorcode", None)
        == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        and "wealth_watchlist_group.user_id, wealth_watchlist_group.name"
        in str(error.orig)
    )


def _confirmed_commit_rejection(error: Exception) -> bool:
    if isinstance(error, IntegrityError):
        return True
    if isinstance(error, DBAPIError):
        return getattr(error.orig, "sqlstate", None) in {"40001", "40P01", "25P02"}
    return False


class WatchlistCommandService:
    def __init__(self) -> None:
        self._groups = WatchlistGroupQuery()
        self._items = WatchlistItemQuery()
        self._policy = WatchlistPolicy()

    def _write(self, session: Session, operation: Callable[[], ResultT]) -> ResultT:
        committing = False
        try:
            result = operation()  # Includes flush, counts and fully materialized DTO.
            committing = True
            session.commit()
            return result
        except Exception as exc:
            try:
                session.rollback()
            except Exception:
                logger.exception("watchlist session cleanup failed")
            if committing and not _confirmed_commit_rejection(exc):
                raise WatchlistError(
                    "WL_WRITE_OUTCOME_UNKNOWN", "操作结果暂无法确认，请先刷新核验"
                ) from exc
            if isinstance(exc, WatchlistError):
                raise
            raise WatchlistError("WL_WRITE_FAILED", "自选操作失败，请重试") from exc

    def _group_result(
        self, session: Session, group: Group
    ) -> WatchlistGroupMutationResponseDto:
        session.flush()
        count = self._groups.count_memberships(session, [group.id])[group.id]
        return WatchlistGroupMutationResponseDto(group=group_dto(group, count))

    def create_group(
        self, session: Session, *, user_id: int, name: str, color: str
    ) -> WatchlistGroupMutationResponseDto:
        def operation():
            self._groups.get_default_group(session, user_id=user_id, for_update=True)
            groups = self._groups.list_groups(session, user_id=user_id)
            if len(groups) >= MAX_GROUPS:
                raise WatchlistError(
                    "WL_GROUP_LIMIT_REACHED", "最多建立 9 个自定义分组"
                )
            group = Group(
                user_id=user_id,
                name=normalize_group_name(name),
                color=self._policy.color(color),
                is_default=False,
            )
            session.add(group)
            try:
                session.flush()
            except IntegrityError as exc:
                if _name_conflict(exc):
                    raise WatchlistError(
                        "WL_GROUP_NAME_CONFLICT", "分组名称已存在"
                    ) from exc
                raise
            return self._group_result(session, group)

        return self._write(session, operation)

    def change_color(
        self, session: Session, *, user_id: int, group_id: int, color: str
    ) -> WatchlistGroupMutationResponseDto:
        def operation():
            group = self._groups.get_owned_group(
                session, user_id=user_id, group_id=group_id, for_update=True
            )
            self._mutable(group)
            group.color = self._policy.color(color)
            group.updated_at = datetime.now(timezone.utc)
            return self._group_result(session, group)

        return self._write(session, operation)

    @staticmethod
    def _mutable(group: Group) -> None:
        if group.is_default:
            raise WatchlistError("WL_DEFAULT_GROUP_IMMUTABLE", "默认分组不可删除或修改")

    def delete_group(
        self, session: Session, *, user_id: int, group_id: int
    ) -> WatchlistGroupDeleteResponseDto:
        def operation():
            groups = self._groups.lock_all_groups(session, user_id=user_id)
            group = next((g for g in groups if g.id == group_id), None)
            if group is None:
                raise WatchlistError("WL_GROUP_NOT_FOUND", "分组不存在")
            self._mutable(group)
            next_id = self._groups.find_right_neighbor_or_default(groups, group_id)
            count = self._groups.count_memberships(session, [group_id])[group_id]
            session.execute(delete(Membership).where(Membership.group_id == group_id))
            session.delete(group)
            session.flush()
            return WatchlistGroupDeleteResponseDto(
                deletedGroupId=group_id, deletedMemberCount=count, nextGroupId=next_id
            )

        return self._write(session, operation)

    def _validate_eligible(
        self, session: Session, pairs: Sequence[tuple[int, str]]
    ) -> None:
        codes = sorted({code for _, code in pairs})
        if codes and self._items.load_eligible_ts_codes(session, codes) != set(codes):
            raise WatchlistError("WL_STOCK_NOT_ELIGIBLE", "新增关系仅支持当前上市 A 股")

    def _insert_missing_memberships(
        self, session: Session, pairs: Sequence[tuple[int, str]]
    ) -> int:
        if not pairs:
            return 0
        values = [
            dict(group_id=group_id, ts_code=code, is_pinned=False)
            for group_id, code in pairs
        ]
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = (
                pg_insert(Membership)
                .values(values)
                .on_conflict_do_nothing(
                    constraint="uq_wealth_watchlist_membership_group_stock"
                )
            )
        elif dialect == "sqlite":
            statement = (
                sqlite_insert(Membership)
                .values(values)
                .on_conflict_do_nothing(index_elements=["group_id", "ts_code"])
            )
        else:
            raise RuntimeError("Unsupported watchlist database dialect")
        ids = session.scalars(statement.returning(Membership.id)).all()
        for member_id in ids:
            # An allocated ID is a server fact, not an invalid client request.
            if type(member_id) is not int or not 1 <= member_id <= MAX_API_ID:
                raise ValueError("Allocated membership ID exceeds API range")
        return len(ids)

    def add_item(
        self, session: Session, *, user_id: int, group_id: int, ts_code: str
    ) -> WatchlistAddResponseDto:
        def operation():
            code = self._policy.normalize_ts_code(ts_code)
            self._groups.get_owned_group(
                session, user_id=user_id, group_id=group_id, for_update=True
            )
            existing = self._items.load_added_codes(
                session, group_id=group_id, ts_codes=[code]
            )
            pairs = [] if existing else [(group_id, code)]
            self._validate_eligible(session, pairs)
            created = self._insert_missing_memberships(session, pairs)
            session.flush()
            return WatchlistAddResponseDto(
                groupId=group_id,
                tsCode=code,
                isAdded=True,
                created=bool(created),
                memberCount=self._groups.count_memberships(session, [group_id])[
                    group_id
                ],
            )

        return self._write(session, operation)

    def batch(
        self,
        session: Session,
        *,
        user_id: int,
        group_id: int,
        action: str,
        membership_ids: list[int],
        target_group_ids: list[int] | None = None,
    ) -> WatchlistBatchActionResponseDto:
        def operation():
            if action not in ("MOVE", "ADD_TO_GROUPS", "REMOVE", "PIN", "UNPIN"):
                raise WatchlistRequestError("无效的批量操作")
            self._policy.ids(
                membership_ids, maximum=MAX_BATCH_MEMBERSHIPS, code="WL_REQUEST_INVALID"
            )
            targets = target_group_ids or []
            if action in ("MOVE", "ADD_TO_GROUPS"):
                self._policy.ids(
                    targets,
                    maximum=1 if action == "MOVE" else MAX_CUSTOM_GROUPS,
                    code="WL_TARGET_GROUP_INVALID",
                )
                if group_id in targets:
                    raise WatchlistError(
                        "WL_TARGET_GROUP_INVALID", "目标分组不能是当前分组"
                    )
            elif targets:
                raise WatchlistError("WL_TARGET_GROUP_INVALID", "该操作不接受目标分组")
            involved = sorted([group_id, *targets])
            groups = self._groups.lock_groups(
                session, user_id=user_id, group_ids=involved
            )
            found = {g.id for g in groups}
            if group_id not in found:
                raise WatchlistError("WL_GROUP_NOT_FOUND", "分组不存在")
            if found != set(involved):
                raise WatchlistError("WL_TARGET_GROUP_INVALID", "目标分组无效")
            sources = list(
                session.scalars(
                    select(Membership)
                    .where(
                        Membership.group_id == group_id,
                        Membership.id.in_(membership_ids),
                    )
                    .order_by(Membership.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if len(sources) != len(membership_ids):
                raise WatchlistError("WL_SELECTION_STALE", "选中股票已变化，请重新选择")
            created = removed = updated = 0
            if targets:
                existing = set(
                    session.execute(
                        select(Membership.group_id, Membership.ts_code).where(
                            Membership.group_id.in_(targets),
                            Membership.ts_code.in_([s.ts_code for s in sources]),
                        )
                    ).all()
                )
                pairs = [
                    (target, source.ts_code)
                    for target in sorted(targets)
                    for source in sources
                    if (target, source.ts_code) not in existing
                ]
                self._validate_eligible(session, pairs)
                created = self._insert_missing_memberships(session, pairs)
            predicate = (
                Membership.group_id == group_id,
                Membership.id.in_(membership_ids),
            )
            if action in ("MOVE", "REMOVE"):
                removed = session.execute(delete(Membership).where(*predicate)).rowcount
            elif action in ("PIN", "UNPIN"):
                pinned = action == "PIN"
                updated = session.execute(
                    update(Membership)
                    .where(*predicate, Membership.is_pinned.is_(not pinned))
                    .values(is_pinned=pinned, updated_at=datetime.now(timezone.utc))
                ).rowcount
            session.flush()
            counts = self._groups.count_memberships(session, involved)
            return WatchlistBatchActionResponseDto(
                action=action,
                requestedCount=len(sources),
                createdCount=created,
                removedCount=removed,
                updatedCount=updated,
                groupCounts=[
                    WatchlistGroupCountDto(groupId=i, memberCount=counts[i])
                    for i in involved
                ],
            )

        return self._write(session, operation)

    def replace_stock_groups(
        self, session: Session, *, user_id: int, ts_code: str, group_ids: list[int]
    ) -> WatchlistStockGroupsReplaceResponseDto:
        def operation():
            code = self._policy.normalize_ts_code(ts_code)
            if not group_ids:
                raise WatchlistError("WL_MEMBERSHIP_REQUIRED", "至少选择一个分组")
            self._policy.ids(
                group_ids, maximum=MAX_GROUPS, code="WL_TARGET_GROUP_INVALID"
            )
            groups = self._groups.lock_all_groups(session, user_id=user_id)
            if not set(group_ids).issubset({g.id for g in groups}):
                raise WatchlistError("WL_TARGET_GROUP_INVALID", "目标分组无效")
            rows = list(
                session.scalars(
                    select(Membership)
                    .where(
                        Membership.group_id.in_([g.id for g in groups]),
                        Membership.ts_code == code,
                    )
                    .order_by(Membership.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            existing = {row.group_id for row in rows}
            pairs = [(i, code) for i in sorted(set(group_ids) - existing)]
            self._validate_eligible(session, pairs)
            created = self._insert_missing_memberships(session, pairs)
            removed = 0
            to_remove = existing - set(group_ids)
            if to_remove:
                removed = session.execute(
                    delete(Membership).where(
                        Membership.group_id.in_(to_remove), Membership.ts_code == code
                    )
                ).rowcount
            session.flush()
            return WatchlistStockGroupsReplaceResponseDto(
                tsCode=code,
                isAdded=True,
                groupIds=[g.id for g in groups if g.id in group_ids],
                createdCount=created,
                removedCount=removed,
            )

        return self._write(session, operation)
