from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class StdMappingRule(TimestampMixin, Base):
    __tablename__ = "std_mapping_rule"
    __table_args__ = (
        Index("idx_std_mapping_rule_dataset_source_status", "dataset_key", "source_key", "status"),
        Index("idx_std_mapping_rule_rule_set_version", "dataset_key", "source_key", "rule_set_version"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    src_field: Mapped[str] = mapped_column(String(64), nullable=False)
    std_field: Mapped[str] = mapped_column(String(64), nullable=False)
    src_type: Mapped[str | None] = mapped_column(String(32))
    std_type: Mapped[str | None] = mapped_column(String(32))
    transform_fn: Mapped[str | None] = mapped_column(String(64))
    lineage_preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    rule_set_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
