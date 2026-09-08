from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class WealthWatchlistMembership(TimestampMixin, Base):
    __tablename__ = "wealth_watchlist_membership"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "ts_code", name="uq_wealth_watchlist_membership_group_stock"
        ),
        Index(
            "idx_wealth_watchlist_membership_group_pin_id",
            "group_id",
            "is_pinned",
            "id",
        ),
        Index("idx_wealth_watchlist_membership_stock_group", "ts_code", "group_id"),
        {"schema": "app", "sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("app.wealth_watchlist_group.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
