from __future__ import annotations

from sqlalchemy import Boolean, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class SwIndustryClassification(TimestampMixin, Base):
    __tablename__ = "sw_industry_classification"
    __table_args__ = (
        UniqueConstraint(
            "src", "index_code", name="uq_sw_industry_classification_src_index_code"
        ),
        Index("idx_sw_industry_classification_src_level_pub", "src", "level", "is_pub"),
        Index("idx_sw_industry_classification_src_parent", "src", "parent_code"),
        {"schema": "core_serving"},
    )

    src: Mapped[str] = mapped_column(String(16), primary_key=True)
    industry_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_index_code: Mapped[str] = mapped_column(String(16), nullable=False)
    index_code: Mapped[str] = mapped_column(String(16), nullable=False)
    industry_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_parent_code: Mapped[str | None] = mapped_column(String(16))
    parent_code: Mapped[str | None] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(2), nullable=False)
    is_pub: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    normalization_rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
