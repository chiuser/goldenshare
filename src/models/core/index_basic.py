from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class IndexBasic(TimestampMixin, Base):
    __tablename__ = "index_basic"
    __table_args__ = (
        Index("idx_index_basic_market", "market"),
        Index("idx_index_basic_publisher", "publisher"),
        Index("idx_index_basic_category", "category"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    fullname: Mapped[str | None] = mapped_column(String(256))
    market: Mapped[str | None] = mapped_column(String(32))
    publisher: Mapped[str | None] = mapped_column(String(128))
    index_type: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(64))
    base_date: Mapped[date | None] = mapped_column(Date)
    base_point: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    list_date: Mapped[date | None] = mapped_column(Date)
    weight_rule: Mapped[str | None] = mapped_column(String(128))
    desc: Mapped[str | None] = mapped_column(Text)
    exp_date: Mapped[date | None] = mapped_column(Date)
