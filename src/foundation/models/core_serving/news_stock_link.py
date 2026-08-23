from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class NewsStockLink(TimestampMixin, Base):
    __tablename__ = "news_stock_link"
    __table_args__ = (
        CheckConstraint(
            "match_method IN ('CODE_EXACT', 'FULL_NAME_EXACT', 'SHORT_NAME_EXACT')",
            name="match_method",
        ),
        CheckConstraint(
            "source_field IN ('title', 'content', 'title_and_content')",
            name="source_field",
        ),
        Index("ix_news_stock_link_ts_code", "ts_code"),
        {"schema": "core_serving"},
    )

    news_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    source_field: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
