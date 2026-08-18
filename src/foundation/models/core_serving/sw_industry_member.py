from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class SwIndustryMember(TimestampMixin, Base):
    __tablename__ = "sw_industry_member"
    __table_args__ = (
        ForeignKeyConstraint(
            ("classification_version", "l3_code"),
            (
                "core_serving.sw_industry_classification.src",
                "core_serving.sw_industry_classification.index_code",
            ),
            name="fk_sw_industry_member_classification_l3",
        ),
        CheckConstraint(
            "out_date IS NULL OR out_date >= in_date",
            name="out_date_not_before_in_date",
        ),
        Index(
            "idx_sw_industry_member_l3_current_stock", "l3_code", "is_new", "ts_code"
        ),
        Index(
            "idx_sw_industry_member_l3_membership_dates",
            "l3_code",
            "in_date",
            "out_date",
        ),
        Index(
            "idx_sw_industry_member_stock_membership_dates",
            "ts_code",
            "in_date",
            "out_date",
        ),
        {"schema": "core_serving"},
    )

    l3_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    in_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source_l1_code: Mapped[str] = mapped_column(String(16), nullable=False)
    l1_code: Mapped[str] = mapped_column(String(16), nullable=False)
    l1_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_l2_code: Mapped[str] = mapped_column(String(16), nullable=False)
    l2_code: Mapped[str] = mapped_column(String(16), nullable=False)
    l2_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_l3_code: Mapped[str] = mapped_column(String(16), nullable=False)
    l3_name: Mapped[str] = mapped_column(String(64), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    out_date: Mapped[date | None] = mapped_column(Date)
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False)
    classification_version: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    normalization_rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
