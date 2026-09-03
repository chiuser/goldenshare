from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class WealthWatchlistItem(TimestampMixin, Base):
    __tablename__ = "wealth_watchlist_item"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "ts_code", name="uq_wealth_watchlist_item_user_stock"
        ),
        Index("idx_wealth_watchlist_item_user_id_id", "user_id", "id"),
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
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
