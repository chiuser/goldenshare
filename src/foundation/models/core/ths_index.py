from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class ThsIndex(TimestampMixin, Base):
    __tablename__ = "ths_index"
    __table_args__ = (
        Index("idx_ths_index_exchange", "exchange"),
        Index("idx_ths_index_type", "type"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    count: Mapped[int | None] = mapped_column(Integer)
    exchange: Mapped[str | None] = mapped_column(String(16))
    list_date: Mapped[date | None] = mapped_column(Date)
    type_: Mapped[str | None] = mapped_column("type", String(32))
