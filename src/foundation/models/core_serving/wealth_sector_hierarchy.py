from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class WealthSectorHierarchy(Base):
    __tablename__ = "wealth_sector_hierarchy"
    __table_args__ = (
        CheckConstraint(
            "industry_level BETWEEN 1 AND 3",
            name="industry_level_range",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="display_order_non_negative",
        ),
        CheckConstraint(
            "(industry_level = 1 AND parent_sector_code IS NULL AND parent_sector_name IS NULL) "
            "OR (industry_level IN (2, 3) AND parent_sector_code IS NOT NULL "
            "AND parent_sector_name IS NOT NULL)",
            name="parent_fields_by_level",
        ),
        Index(
            "idx_wealth_sector_hierarchy_level_order_code",
            "industry_level",
            "display_order",
            "sector_code",
        ),
        Index(
            "idx_wealth_sector_hierarchy_parent_level_order_code",
            "parent_sector_code",
            "industry_level",
            "display_order",
            "sector_code",
        ),
        Index(
            "idx_wealth_sector_hierarchy_root_level_order_code",
            "root_sector_code",
            "industry_level",
            "display_order",
            "sector_code",
        ),
        {"schema": "core_serving"},
    )

    sector_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    industry_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    industry_level_name: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_sector_code: Mapped[str | None] = mapped_column(String(16))
    parent_sector_name: Mapped[str | None] = mapped_column(String(128))
    root_sector_code: Mapped[str] = mapped_column(String(16), nullable=False)
    root_sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    hierarchy_path: Mapped[str] = mapped_column(String(512), nullable=False)
    is_leaf: Mapped[bool] = mapped_column(Boolean, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_received_date: Mapped[date] = mapped_column(Date, nullable=False)
    code_reference_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
