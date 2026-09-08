from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    DEFAULT_GROUP_NAME,
    PALETTE,
)
from src.foundation.models.base import Base, TimestampMixin


class WealthWatchlistGroup(TimestampMixin, Base):
    __tablename__ = "wealth_watchlist_group"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_wealth_watchlist_group_user_name"),
        Index(
            "uq_wealth_watchlist_group_user_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        Index("idx_wealth_watchlist_group_user_id_id", "user_id", "id"),
        CheckConstraint(
            "length(name) > 0", name=conv("ck_wealth_watchlist_group_name_nonempty")
        ),
        CheckConstraint(
            f"(is_default AND name = '{DEFAULT_GROUP_NAME}' AND color IS NULL) OR "
            f"(NOT is_default AND name <> '{DEFAULT_GROUP_NAME}' AND color IS NOT NULL "
            f"AND color IN ({','.join(repr(color) for color in PALETTE)}))",
            name=conv("ck_wealth_watchlist_group_identity"),
        ),
        {"schema": "app", "sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("app.app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
