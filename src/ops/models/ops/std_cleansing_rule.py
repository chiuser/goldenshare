from __future__ import annotations

from sqlalchemy import BigInteger, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class StdCleansingRule(TimestampMixin, Base):
    __tablename__ = "std_cleansing_rule"
    __table_args__ = (
        Index("idx_std_cleansing_rule_dataset_source_status", "dataset_key", "source_key", "status"),
        Index("idx_std_cleansing_rule_rule_set_version", "dataset_key", "source_key", "rule_set_version"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    condition_expr: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    rule_set_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
