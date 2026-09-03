from __future__ import annotations

import sqlite3

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.biz.models.wealth.watchlist_item import WealthWatchlistItem
from src.biz.queries.wealth.market.watchlist.watchlist_query import WatchlistQuery
from src.biz.schemas.wealth.market.watchlist import (
    WatchlistAddResponseDto,
    WatchlistRemoveResponseDto,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    WatchlistPolicy,
    WatchlistStockNotEligibleError,
)


def _is_membership_conflict(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    if diagnostic is not None:
        return diagnostic.constraint_name == "uq_wealth_watchlist_item_user_stock"
    return (
        getattr(error.orig, "sqlite_errorcode", None)
        == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        and "wealth_watchlist_item.user_id, wealth_watchlist_item.ts_code"
        in str(error.orig)
    )


class WatchlistCommandService:
    def __init__(self) -> None:
        self._query = WatchlistQuery()
        self._policy = WatchlistPolicy()

    def add(
        self, session: Session, *, user_id: int, ts_code: str
    ) -> WatchlistAddResponseDto:
        code = self._policy.normalize_ts_code(ts_code)
        try:
            if self._query.load_eligible_security(session, ts_code=code) is None:
                raise WatchlistStockNotEligibleError("仅支持添加当前上市 A 股")
            created = True
            try:
                with session.begin_nested():
                    session.add(WealthWatchlistItem(user_id=user_id, ts_code=code))
                    session.flush()
            except IntegrityError as error:
                if not _is_membership_conflict(error) or not self._query.contains(
                    session, user_id=user_id, ts_code=code
                ):
                    raise
                created = False
            session.commit()
            return WatchlistAddResponseDto(
                tsCode=code,
                isAdded=True,
                created=created,
                totalCount=self._query.count(session, user_id=user_id),
            )
        except Exception:
            session.rollback()
            raise

    def remove(
        self, session: Session, *, user_id: int, ts_code: str
    ) -> WatchlistRemoveResponseDto:
        code = self._policy.normalize_ts_code(ts_code)
        try:
            result = session.execute(
                delete(WealthWatchlistItem).where(
                    WealthWatchlistItem.user_id == user_id,
                    WealthWatchlistItem.ts_code == code,
                )
            )
            removed = result.rowcount > 0
            session.commit()
            return WatchlistRemoveResponseDto(
                tsCode=code,
                isAdded=False,
                removed=removed,
                totalCount=self._query.count(session, user_id=user_id),
            )
        except Exception:
            session.rollback()
            raise
